"""
Постоянный парсер температуры воды из TikTok-роликов.

Работает по КАНАЛАМ: при первом запуске резолвит канал из seed-ссылки на
видео через `yt-dlp -j`, дальше на каждом запуске проверяет последний
ролик канала и обрабатывает только НОВЫЙ (дедуп по video_id).

Два независимых источника данных из одного и того же видео:

1) РЕЧЬ (Whisper, ru) — дата ("12 июля" -> ISO), температура (озвученная),
   упоминание пляжа (best-effort по списку известных мест Одессы).

2) НАЛОЖЕННЫЙ НА КАДР ТЕКСТ (OCR, Tesseract, rus) — у некоторых каналов
   поверх видео печатают точные "14.9 градусов" и "Время 7:15" — этого
   в речи нет, только на картинке. Кадры вытаскиваются через ffmpeg
   (несколько fps на первые ~40 секунд ролика), каждый прогоняется через
   Tesseract, тексты со всех кадров склеиваются и парсятся.

Итоговое значение sea_temp: если OCR нашёл число — используем его
(точный печатный текст надёжнее распознанной речи), иначе — из речи.
Время (time) — только из OCR, в речи оно не озвучивается.

Состояние по каналам (channel_url, last_video_id) — data/tiktok_channels.json
История наблюдений (накопительно, все каналы) — data/tiktok_sea_temp.json

Доп. зависимости (не входят в основной пайплайн, только в workflow этого скрипта):
    pip install yt-dlp openai-whisper pytesseract Pillow
    apt-get install ffmpeg tesseract-ocr tesseract-ocr-rus
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "tiktok_channels.json")
HISTORY_FILE  = os.path.join(BASE_DIR, "data", "tiktok_sea_temp.json")

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# Best-effort список известных пляжей/точек Одессы для сопоставления подстрокой.
BEACHES = [
    "ланжерон", "аркадия", "аркадію", "отрада", "золотой берег", "дельфин",
    "чайка", "куяльник", "лузановка", "черноморка", "санта-барбара",
    "вилла медичи", "большой фонтан", "малый фонтан", "средний фонтан",
    "16 фонтана", "трасса здоровья", "бугаз", "затока", "ревьера", "ревьере",
]

# Число перед "градус" — ищем везде, потом проверяем контекст (слово
# "температур" где-то раньше в пределах 100 символов) отдельно в parse_temp.
NUMBER_BEFORE_GRADUS_RE = re.compile(r'(\d{1,2}(?:[.,]\d)?)\s*град', re.IGNORECASE)
DATE_RE = re.compile(
    r'(\d{1,2})\s+(' + "|".join(MONTHS_RU.keys()) + r')',
    re.IGNORECASE,
)
# OCR-версия времени: "Время 7:15" / "Время 07.15" — Tesseract может
# ошибиться в отдельных буквах слова "Время", поэтому матчим по обрубку "рем".
OCR_TIME_RE = re.compile(r'[Вв]рем[а-яА-Я]*\W{0,4}(\d{1,2})[:.\s](\d{2})')
# Устный вариант времени (на случай, если где-то всё же озвучат) — прежнее поведение.
TIME_COLON_RE = re.compile(r'\b(\d{1,2}):(\d{2})\b')
TIME_HOUR_RE  = re.compile(r'\bв\s+(\d{1,2})\s+час', re.IGNORECASE)


def _yt_dlp_json(url):
    out = subprocess.run(
        ["yt-dlp", "-j", "--no-warnings", url],
        capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:])
    return json.loads(out.stdout.splitlines()[0])


def resolve_channel_url(seed_video_url):
    info = _yt_dlp_json(seed_video_url)
    return info.get("channel_url") or info.get("uploader_url")


def latest_video_info(channel_url):
    out = subprocess.run(
        ["yt-dlp", "-j", "--no-warnings", "--playlist-items", "1", channel_url],
        capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:])
    return json.loads(out.stdout.splitlines()[0])


def download_video(url, workdir):
    out_tmpl = os.path.join(workdir, "video.%(ext)s")
    subprocess.run(
        ["yt-dlp", "-f", "mp4/best", "-o", out_tmpl, url],
        check=True, cwd=workdir, timeout=180
    )
    for name in os.listdir(workdir):
        if name.startswith("video."):
            return os.path.join(workdir, name)
    raise RuntimeError("yt-dlp не создал видеофайл")


def extract_audio(video_path, workdir):
    audio_path = os.path.join(workdir, "audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-q:a", "2", audio_path],
        check=True, capture_output=True, timeout=60
    )
    return audio_path


def extract_frames(video_path, workdir, fps=2, max_seconds=40):
    frames_dir = os.path.join(workdir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-t", str(max_seconds),
         "-vf", f"fps={fps}", os.path.join(frames_dir, "f_%04d.png")],
        check=True, capture_output=True, timeout=90
    )
    return sorted(
        os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".png")
    )


def ocr_frames(frame_paths):
    import pytesseract
    from PIL import Image
    texts = []
    for fp in frame_paths:
        try:
            texts.append(pytesseract.image_to_string(Image.open(fp), lang="rus"))
        except Exception as e:
            print(f"  [WARN] OCR кадра {fp} не удался: {e}")
    return "\n".join(texts)


_whisper_model = None


def transcribe(audio_path):
    global _whisper_model
    import whisper
    if _whisper_model is None:
        _whisper_model = whisper.load_model("small")
    result = _whisper_model.transcribe(audio_path, language="ru")
    return result.get("text", "")


def parse_temp_from_speech(text):
    best = None
    for m in NUMBER_BEFORE_GRADUS_RE.finditer(text):
        window_before = text[max(0, m.start() - 100):m.start()]
        if not re.search(r'температур', window_before, re.IGNORECASE):
            continue
        try:
            val = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 3 <= val <= 32:
            best = val
    return best


def parse_temp_from_ocr(text):
    # На кадре формат обычно простой: "14.9 градусов" без лишнего текста
    # рядом — контекстную проверку на "температур" не требуем.
    best = None
    for m in NUMBER_BEFORE_GRADUS_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 3 <= val <= 32:
            best = val
    return best


def parse_date(text, fallback_dt):
    m = DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS_RU[m.group(2).lower()]
    year = fallback_dt.year
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def parse_beach(text):
    low = text.lower()
    for b in BEACHES:
        if b in low:
            return b
    return None


def parse_time_ocr(text):
    m = OCR_TIME_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_time_speech(text):
    m = TIME_COLON_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = TIME_HOUR_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def process_channel(entry, history):
    seed = entry["seed_video"]
    label = entry.get("label") or seed

    def _record_error(msg):
        entry["last_error"]    = msg[-800:]
        entry["last_error_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not entry.get("channel_url"):
        try:
            entry["channel_url"] = resolve_channel_url(seed)
            print(f"  [{label}] резолвнут канал: {entry['channel_url']}")
        except Exception as e:
            print(f"  [WARN][{label}] не удалось резолвнуть канал: {e}")
            _record_error(f"resolve_channel_url: {e}")
            return

    try:
        info = latest_video_info(entry["channel_url"])
    except Exception as e:
        print(f"  [WARN][{label}] не удалось получить последний ролик: {e}")
        _record_error(f"latest_video_info: {e}")
        return

    video_id = info.get("id")
    video_url = info.get("webpage_url") or info.get("original_url") or seed

    if video_id and video_id == entry.get("last_video_id"):
        print(f"  [{label}] новых роликов нет (последний уже обработан)")
        return

    speech_text = ""
    ocr_text = ""
    with tempfile.TemporaryDirectory() as workdir:
        try:
            print(f"  [{label}] скачиваю видео: {video_url}")
            video_path = download_video(video_url, workdir)

            print(f"  [{label}] извлекаю аудио и распознаю речь...")
            audio_path = extract_audio(video_path, workdir)
            speech_text = transcribe(audio_path)

            print(f"  [{label}] извлекаю кадры и распознаю наложенный текст (OCR)...")
            frames = extract_frames(video_path, workdir)
            ocr_text = ocr_frames(frames)
        except Exception as e:
            print(f"  [WARN][{label}] обработка не удалась: {e}")
            _record_error(f"process: {e}")
            return

    entry.pop("last_error", None)
    entry.pop("last_error_at", None)
    now = datetime.now(timezone.utc)

    temp_speech = parse_temp_from_speech(speech_text)
    temp_ocr    = parse_temp_from_ocr(ocr_text)
    time_ocr    = parse_time_ocr(ocr_text)
    time_speech = parse_time_speech(speech_text)

    result = {
        "channel":       label,
        "video_id":      video_id,
        "url":           video_url,
        "timestamp":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcript":    speech_text,
        "ocr_text":      ocr_text,
        "date":          parse_date(speech_text, now),
        "sea_temp":      temp_ocr if temp_ocr is not None else temp_speech,
        "sea_temp_ocr":  temp_ocr,
        "sea_temp_speech": temp_speech,
        "beach":         parse_beach(speech_text),
        "time":          time_ocr if time_ocr is not None else time_speech,
    }
    print(f"  [{label}] дата={result['date']} темп={result['sea_temp']}°C "
          f"(ocr={temp_ocr}, речь={temp_speech}) пляж={result['beach']} время={result['time']}")

    history.append(result)
    entry["last_video_id"] = video_id


def main():
    channels = load_json(CHANNELS_FILE, [])
    history  = load_json(HISTORY_FILE, [])

    if not channels:
        print("  [WARN] data/tiktok_channels.json пуст — нечего обрабатывать")
        return

    for entry in channels:
        process_channel(entry, history)

    save_json(CHANNELS_FILE, channels)
    save_json(HISTORY_FILE, history)


if __name__ == "__main__":
    main()
