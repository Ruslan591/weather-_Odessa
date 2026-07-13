"""
Постоянный (не разовый) парсер температуры воды из TikTok-роликов.
Работает по КАНАЛАМ, а не по разовым ссылкам на видео: при первом запуске
резолвит сам канал из seed-ссылки на видео через `yt-dlp -j` (поле
channel_url/uploader_url), дальше на каждом запуске проверяет последний
ролик канала и обрабатывает только НОВЫЙ (дедуп по video_id).

Из речи (Whisper, ru) вытаскивает:
  - дату замера ("12 июля" -> ISO, год берётся текущий на момент обработки)
  - температуру воды (учитывает десятичную запятую/точку: "20,2 градуса")
  - место/пляж — по списку известных пляжей Одессы (best-effort, подстрокой
    по транскрипту; список можно расширять по мере появления промахов)
  - время — ТОЛЬКО если произнесено голосом ("в 9:15", "в 8 часов").
    Точное время, которое у них подаётся текстом на кадре, сюда не входит —
    для этого нужен отдельный OCR-пайплайн по кадрам, здесь его нет.

Состояние по каналам (channel_url, last_video_id) — data/tiktok_channels.json
История наблюдений (накопительно, все каналы) — data/tiktok_sea_temp.json
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
# Расширять по мере появления непойманных названий в транскриптах.
BEACHES = [
    "ланжерон", "аркадия", "аркадію", "отрада", "золотой берег", "дельфин",
    "чайка", "куяльник", "лузановка", "черноморка", "санта-барбара",
    "вилла медичи", "большой фонтан", "малый фонтан", "средний фонтан",
    "16 фонтана", "трасса здоровья", "бугаз", "затока", "ревьера", "ревьере",
]

# Ищем число перед "градус" и отдельно проверяем, что где-то РАНЬШЕ (в пределах
# 100 символов) встречалось слово "температура" — без ограничения на то, что
# может стоять между ними (Whisper часто вставляет мусорные цифры/пунктуацию
# в паузах речи, например "воды в 10. 14,9 градусов").
NUMBER_BEFORE_GRADUS_RE = re.compile(r'(\d{1,2}(?:[.,]\d)?)\s*градус', re.IGNORECASE)
DATE_RE = re.compile(
    r'(\d{1,2})\s+(' + "|".join(MONTHS_RU.keys()) + r')',
    re.IGNORECASE,
)
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


def download_audio(url, workdir):
    out_tmpl = os.path.join(workdir, "audio.%(ext)s")
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", out_tmpl, url],
        check=True, cwd=workdir, timeout=180
    )
    for name in os.listdir(workdir):
        if name.startswith("audio."):
            return os.path.join(workdir, name)
    raise RuntimeError("yt-dlp не создал аудиофайл")


_whisper_model = None


def transcribe(audio_path):
    global _whisper_model
    import whisper
    if _whisper_model is None:
        _whisper_model = whisper.load_model("small")
    result = _whisper_model.transcribe(audio_path, language="ru")
    return result.get("text", "")


def parse_temp(text):
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
            best = val  # берём последнее по тексту подходящее упоминание
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


def parse_time(text):
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

    if not entry.get("channel_url"):
        try:
            entry["channel_url"] = resolve_channel_url(seed)
            print(f"  [{label}] резолвнут канал: {entry['channel_url']}")
        except Exception as e:
            print(f"  [WARN][{label}] не удалось резолвнуть канал: {e}")
            return

    try:
        info = latest_video_info(entry["channel_url"])
    except Exception as e:
        print(f"  [WARN][{label}] не удалось получить последний ролик: {e}")
        return

    video_id = info.get("id")
    video_url = info.get("webpage_url") or info.get("original_url") or seed

    if video_id and video_id == entry.get("last_video_id"):
        print(f"  [{label}] новых роликов нет (последний уже обработан)")
        return

    text = ""
    with tempfile.TemporaryDirectory() as workdir:
        try:
            print(f"  [{label}] скачиваю аудио: {video_url}")
            audio_path = download_audio(video_url, workdir)
            print(f"  [{label}] распознаю речь...")
            text = transcribe(audio_path)
        except Exception as e:
            print(f"  [WARN][{label}] обработка не удалась: {e}")
            return

    now = datetime.now(timezone.utc)
    result = {
        "channel":    label,
        "video_id":   video_id,
        "url":        video_url,
        "timestamp":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcript": text,
        "date":       parse_date(text, now),
        "sea_temp":   parse_temp(text),
        "beach":      parse_beach(text),
        "time":       parse_time(text),
    }
    print(f"  [{label}] дата={result['date']} темп={result['sea_temp']}°C "
          f"пляж={result['beach']} время={result['time']}")

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
