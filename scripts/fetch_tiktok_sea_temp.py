"""
Парсер температуры воды из TikTok-роликов. v3: добавлен OCR наложенного
текста на кадре ("14.9 градусов / Время 7:15") — приоритетный источник,
надёжнее распознавания речи. Whisper остаётся как фоллбэк, если OCR
ничего не нашёл (не у всех каналов есть текстовый оверлей).

Работает по КАНАЛАМ: при первом запуске резолвит канал из seed-ссылки на
видео через `yt-dlp -j`, дальше на каждом запуске проверяет последний
ролик канала и обрабатывает только НОВЫЙ (дедуп по video_id).

Зависимости (ставятся в workflow, не в основном пайплайне):
    pip install yt-dlp openai-whisper pytesseract Pillow
    apt-get install ffmpeg tesseract-ocr tesseract-ocr-rus

Состояние по каналам (channel_url, last_video_id) — data/tiktok_channels.json
История наблюдений (накопительно, все каналы)     — data/tiktok_sea_temp.json
"""

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNELS_FILE = os.path.join(BASE_DIR, "data", "tiktok_channels.json")
HISTORY_FILE  = os.path.join(BASE_DIR, "data", "tiktok_sea_temp.json")

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# словоформа (как встречается в речи/OCR, нижний регистр) -> канонично отображаемое имя
BEACHES = {
    "ланжерон": "Ланжерон", "ланжероне": "Ланжерон",
    "аркадия": "Аркадия", "аркадии": "Аркадия", "аркадію": "Аркадия",
    "отрада": "Отрада", "отраде": "Отрада",
    "золотой берег": "Золотой берег",
    "дельфин": "Дельфин",
    "чайка": "Чайка",
    "куяльник": "Куяльник",
    "лузановка": "Лузановка", "лузановке": "Лузановка",
    "черноморка": "Черноморка", "черноморке": "Черноморка",
    "санта-барбара": "Санта-Барбара",
    "вилла медичи": "Вилла Медичи",
    "большой фонтан": "Большой Фонтан",
    "малый фонтан": "Малый Фонтан",
    "средний фонтан": "Средний Фонтан",
    "16 фонтана": "16-я станция Фонтана",
    "трасса здоровья": "Трасса здоровья",
    "бугаз": "Бугаз",
    "затока": "Затока",
    "ревьера": "Ривьера", "ревьере": "Ривьера", "ревьеры": "Ривьера",
    "ривьера": "Ривьера", "ривьере": "Ривьера", "ривьеры": "Ривьера",
}

# --- речь (Whisper) ---
NUMBER_BEFORE_GRADUS_RE = re.compile(r'(\d{1,2}(?:[.,]\d)?)\s*градус', re.IGNORECASE)
DATE_RE = re.compile(r'(\d{1,2})\s+(' + "|".join(MONTHS_RU.keys()) + r')', re.IGNORECASE)
TIME_COLON_RE = re.compile(r'\b(\d{1,2}):(\d{2})\b')
TIME_HOUR_RE  = re.compile(r'\bв\s+(\d{1,2})\s+час', re.IGNORECASE)

# --- наложенный текст на кадре (OCR) ---
OCR_TEMP_RE = re.compile(r'(\d{1,2}[.,]?\d?)\s*(?:°\s*[CС]?|град|[CС])\*?', re.IGNORECASE)
# ^ помимо "22°"/"22 град" ловим и формат "21C*"/"21С" (латинская или
# кириллическая C), который встречается на некоторых каналах вместо °.
# Диапазон 3-32°C уже проверяется отдельно в parse_temp_ocr, так что
# ложных срабатываний на случайный OCR-мусор по одной букве 'C' не боимся.
OCR_TIME_RE = re.compile(r'[Вв]рем[яи]\D{0,5}(\d{1,2})[:.](\d{2})')
# запасной вариант: голое "ЧЧ:ММ" без подписи "Время" — так тоже бывает в оверлее
# (например, время идёт отдельной строкой сразу после даты)
OCR_BARE_TIME_RE = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b')
# числовая дата на кадре вида "13.07.2026"
OCR_DATE_RE = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b')


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
    # ВАЖНО: --playlist-items 1 не годится — у аккаунта может быть закреплённый
    # (pinned) ролик, который TikTok всегда показывает первым в списке профиля
    # независимо от даты публикации. Берём несколько первых позиций и выбираем
    # реально самый новый по timestamp/upload_date, игнорируя порядок в списке.
    out = subprocess.run(
        ["yt-dlp", "-j", "--no-warnings", "--playlist-items", "1-5", channel_url],
        capture_output=True, text=True, timeout=90
    )
    # ВАЖНО: если хотя бы ОДИН из 5 роликов в диапазоне не извлёкся (например
    # временная ошибка TikTok на конкретном старом видео), yt-dlp вернёт
    # ненулевой код возврата — но JSON остальных, успешно извлечённых роликов
    # всё равно приходит в stdout. Раньше здесь падали сразу по returncode,
    # выбрасывая эти уже полученные данные. Теперь сначала парсим всё, что
    # реально пришло, и считаем ошибкой только полное отсутствие результата.
    candidates = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not candidates:
        if out.returncode != 0:
            raise RuntimeError(out.stderr[-500:])
        raise RuntimeError("yt-dlp не вернул ни одного видео для канала")

    def sort_key(info):
        # timestamp (unix, точнее) приоритетнее upload_date (только дата)
        return (info.get("timestamp") or 0, info.get("upload_date") or "")

    candidates.sort(key=sort_key, reverse=True)
    debug_info = [
        {"id": c.get("id"), "timestamp": c.get("timestamp"), "upload_date": c.get("upload_date")}
        for c in candidates
    ]
    return candidates[0], debug_info


def probe_formats(url):
    """Список форматов конкретного видео (не плейлиста) с acodec/vcodec —
    нужен, чтобы понять, был ли у ролика вообще доступен формат со звуком,
    ДО того как yt-dlp выберет и смёрджит финальный файл. Раньше единственной
    диагностикой был ffprobe УЖЕ СКАЧАННОГО файла, который не показывает,
    что было доступно на источнике и почему выбор мог не включить audio."""
    try:
        out = subprocess.run(
            ["yt-dlp", "-j", "--no-warnings", url],
            capture_output=True, text=True, timeout=60
        )
        if out.returncode != 0 or not out.stdout.strip():
            return {"probe_formats_error": out.stderr[-500:]}
        info = json.loads(out.stdout.splitlines()[0])
        formats = info.get("formats") or []
        summary = [
            {
                "format_id": f.get("format_id"),
                "acodec": f.get("acodec"),
                "vcodec": f.get("vcodec"),
                "ext": f.get("ext"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
            }
            for f in formats
        ]
        return {"n_formats": len(summary), "formats": summary}
    except Exception as e:
        return {"probe_formats_error": str(e)[:500]}


def download_video(url, workdir):
    # ВАЖНО: у TikTok обычно есть ГОТОВЫЙ комбинированный поток (видео+аудио
    # уже смешаны). Раньше здесь стояло "bestvideo+bestaudio/best" — принудительное
    # раздельное слияние — но на части роликов это давало video-only файл
    # (bestvideo матчился, отдельного bestaudio не находилось, и итоговый
    # файл оставался без звука, хотя в оригинале звук есть).
    # Поэтому сначала пробуем уже смешанный формат с аудио+видео, и только
    # если такого нет — падаем на раздельное слияние как раньше.
    out_tmpl = os.path.join(workdir, "video.%(ext)s")
    try:
        subprocess.run(
            ["yt-dlp", "-f", "best[acodec!=none][vcodec!=none]/bestvideo+bestaudio/best",
             "--merge-output-format", "mp4", "-o", out_tmpl, url],
            check=True, cwd=workdir, timeout=180,
            capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp exit={e.returncode}: {e.stderr[-400:]}")

    for name in os.listdir(workdir):
        if name.startswith("video."):
            path = os.path.join(workdir, name)
            size = os.path.getsize(path)
            if size < 1024:
                raise RuntimeError(f"скачанный файл подозрительно маленький ({size} байт) — возможен rate-limit/бан TikTok")
            return path
    raise RuntimeError("yt-dlp не создал видеофайл")


def _last_lines(text, n=15):
    """Последние N строк вывода ffmpeg, а не последние N символов.
    Баннер сборки ffmpeg — это одна гигантская строка (список --enable-...
    флагов) на несколько тысяч символов, поэтому срез по символам почти
    всегда попадает внутрь баннера, а не на реальное сообщение об ошибке,
    которое идёт отдельными строками ПОСЛЕ него."""
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def probe_video(video_path):
    """Диагностика контейнера/кодека входного файла через ffprobe —
    нужна, когда ffmpeg падает с невнятным exit-кодом (например 234 =
    -22 & 0xff, EINVAL), чтобы понять, ЧТО именно не так с файлом."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=format_name,duration,size:stream=codec_name,codec_type,width,height,pix_fmt",
             "-of", "json", video_path],
            capture_output=True, text=True, timeout=30
        )
        info = {}
        if out.stdout.strip():
            try:
                info = json.loads(out.stdout)
            except json.JSONDecodeError:
                info = {"raw_stdout": out.stdout[-500:]}
        if out.returncode != 0:
            info["ffprobe_stderr"] = out.stderr[-500:]
        return info
    except Exception as e:
        return {"probe_error": str(e)[:300]}


def extract_audio(video_path, workdir):
    audio_path = os.path.join(workdir, "audio.mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "mp3", audio_path],
            check=True, capture_output=True, timeout=60, text=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg exit={e.returncode}: {_last_lines(e.stderr)}")
    return audio_path


def _probe_duration(video_path):
    """Длительность видео в секундах через ffprobe. Раньше длительность
    пытались подставить как eval-переменную 'duration' прямо внутрь
    ffmpeg-фильтра fps=... — но fps-фильтр такую переменную не поддерживает
    (отсюда 'Undefined constant ... duration' и 0 кадров на ЛЮБОМ видео).
    Поэтому считаем fps самостоятельно, в Python, и передаём в ffmpeg уже
    готовое число."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def extract_frames(video_path, workdir, n=6):
    # ВАЖНО: интро-плашка с локацией/датой/временем у этих каналов обычно
    # видна всего 2-5 секунд В САМОМ НАЧАЛЕ ролика. Раньше кадры брались
    # равномерно по всей длительности (fps=n/duration) — на длинных видео
    # (несколько минут) шаг между кадрами мог быть ~30-40 сек, и окно
    # с текстом легко проскакивало мимо, либо попадало смазанным кадром
    # ровно на стыке перехода.
    #
    # Теперь берём кадры точными сиквенами по времени (-ss), не через
    # общий fps-фильтр: плотно по 1 кадру в секунду первые 8 секунд
    # (гарантированно ловим интро-плашку целиком), плюс несколько кадров
    # дальше по видео на случай повторной плашки с показанием термометра
    # ближе к концу.
    duration = _probe_duration(video_path)
    intro_times = [t for t in range(1, 9) if t < duration]
    tail_fracs = [0.3, 0.5, 0.7, 0.9]
    intro_end = intro_times[-1] if intro_times else 0
    tail_times = [
        round(duration * f, 2) for f in tail_fracs
        if duration * f > intro_end + 1
    ]
    timestamps = intro_times + tail_times
    if not timestamps:
        timestamps = [round(max(0.5, duration / 2), 2)]

    frames = []
    for i, t in enumerate(timestamps):
        out_path = os.path.join(workdir, f"frame_{i:03d}.png")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", video_path,
                 "-frames:v", "1", out_path],
                check=True, capture_output=True, timeout=20, text=True
            )
        except subprocess.CalledProcessError:
            # один неудачный кадр (например seek за пределы потока) не
            # должен рушить остальные — просто пропускаем его
            continue
        if os.path.exists(out_path):
            frames.append(out_path)

    if not frames:
        raise RuntimeError("ни один кадр не извлёкся ни по одному из timestamp'ов")
    return frames


def ocr_frames(frames):
    import pytesseract
    from PIL import Image
    texts = []
    for fp in frames:
        try:
            texts.append(pytesseract.image_to_string(Image.open(fp), lang="rus"))
        except Exception as e:
            print(f"    [WARN] OCR кадра не удался: {e}")
    return "\n".join(texts)


_whisper_model = None


def transcribe(audio_path):
    global _whisper_model
    import whisper
    if _whisper_model is None:
        _whisper_model = whisper.load_model("small")
    result = _whisper_model.transcribe(audio_path, language="ru")
    return result.get("text", "")


def parse_temp_speech(text):
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


def parse_temp_ocr(text):
    m = OCR_TEMP_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if 3 <= val <= 32:
        return val
    return None


def parse_time_ocr(text):
    m = OCR_TIME_RE.search(text)
    if m:
        h, mm = int(m.group(1)), m.group(2)
        if 0 <= h <= 23:
            return f"{h:02d}:{mm}"
    # фоллбэк: ищем голое "ЧЧ:ММ" рядом с датой (в пределах ~40 симв. после неё),
    # чтобы не хватать случайные цифры из другого места оверлея/шума OCR
    date_m = OCR_DATE_RE.search(text)
    if date_m:
        window = text[date_m.end(): date_m.end() + 40]
        m2 = OCR_BARE_TIME_RE.search(window)
        if m2:
            h, mm = int(m2.group(1)), m2.group(2)
            if 0 <= h <= 23:
                return f"{h:02d}:{mm}"
    return None


def parse_date_speech(text, fallback_dt):
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


def parse_date_ocr(text):
    m = OCR_DATE_RE.search(text)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def parse_beach(text):
    low = text.lower()
    for variant, canon in BEACHES.items():
        if variant in low:
            return canon
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

    if not entry.get("channel_url"):
        try:
            entry["channel_url"] = resolve_channel_url(seed)
            print(f"  [{label}] резолвнут канал: {entry['channel_url']}")
        except Exception as e:
            err = f"resolve_channel_url: {e}"
            print(f"  [WARN][{label}] не удалось резолвнуть канал: {e}")
            entry["last_error"] = err[-500:]
            return

    try:
        info, playlist_debug = latest_video_info(entry["channel_url"])
        entry["last_playlist_debug"] = playlist_debug
    except Exception as e:
        err = f"latest_video_info: {e}"
        print(f"  [WARN][{label}] не удалось получить последний ролик: {e}")
        entry["last_error"] = err[-500:]
        return

    video_id = info.get("id")
    video_url = info.get("webpage_url") or info.get("original_url") or seed

    if video_id and video_id == entry.get("last_video_id"):
        print(f"  [{label}] новых роликов нет (последний уже обработан)")
        return

    speech_text, ocr_text = "", ""
    with tempfile.TemporaryDirectory() as workdir:
        # Речь и OCR — независимо друг от друга: у ролика может не быть
        # звуковой дорожки (слайд-шоу/muted), но при этом текст на кадре
        # всё равно можно распознать, и наоборот.
        diag = {"video_size": None, "audio_size": None, "n_frames": None,
                "speech_len": 0, "ocr_len": 0}

        print(f"  [{label}] проверяю доступные форматы (acodec/vcodec)...")
        diag["formats_probe"] = probe_formats(video_url)

        try:
            print(f"  [{label}] скачиваю видео: {video_url}")
            video_path = download_video(video_url, workdir)
        except Exception as e:
            err = f"download_video: {e}"
            print(f"  [WARN][{label}] скачивание не удалось: {e}")
            entry["last_error"] = err[-500:]
            entry["last_run_diag"] = diag
            return
        try:
            diag["video_size"] = os.path.getsize(video_path)
        except Exception:
            pass

        diag["probe"] = probe_video(video_path)

        try:
            audio_path = extract_audio(video_path, workdir)
            diag["audio_size"] = os.path.getsize(audio_path)
            print(f"  [{label}] распознаю речь... (аудио {diag['audio_size']} байт)")
            speech_text = transcribe(audio_path)
            diag["speech_len"] = len(speech_text)
            diag["speech_text_sample"] = speech_text[:600]
        except Exception as e:
            print(f"  [WARN][{label}] речь недоступна/не распозналась: {e}")
            diag["speech_error"] = str(e)[:800]

        try:
            frames = extract_frames(video_path, workdir)
            diag["n_frames"] = len(frames)
            print(f"  [{label}] OCR по {len(frames)} кадрам...")
            ocr_text = ocr_frames(frames)
            diag["ocr_len"] = len(ocr_text)
            # Сам текст (обрезанный) — чтобы видеть реальный OCR-мусор и
            # подгонять регексы дат/времени/температуры под то, что тессеракт
            # реально распознаёт (например, точки-разделители в дате часто
            # пропадают: "15.07.2026" -> "151072026").
            diag["ocr_text_sample"] = ocr_text[:600]
        except Exception as e:
            print(f"  [WARN][{label}] OCR не удался: {e}")
            diag["ocr_error"] = str(e)[:800]

        entry["last_run_diag"] = diag

        if not speech_text and not ocr_text:
            entry["last_error"] = "ни речь, ни OCR не дали результата (видео без звука и без читаемого оверлея?)"

    now = datetime.now(timezone.utc)

    ocr_temp    = parse_temp_ocr(ocr_text)
    ocr_time    = parse_time_ocr(ocr_text)
    ocr_date    = parse_date_ocr(ocr_text)
    ocr_beach   = parse_beach(ocr_text)
    speech_temp  = parse_temp_speech(speech_text)
    speech_time  = parse_time_speech(speech_text)
    speech_date  = parse_date_speech(speech_text, now)
    speech_beach = parse_beach(speech_text)

    # Если ни OCR, ни речь не назвали пляж явно — берём default_beach из
    # конфига канала (например, у tiktok_1 обычно снимают на Ревьере, но
    # название не всегда звучит/читается). Если пляж РЕАЛЬНО распознан —
    # он всегда важнее дефолта.
    detected_beach = ocr_beach if ocr_beach is not None else speech_beach
    default_beach = entry.get("default_beach")
    final_beach = detected_beach if detected_beach is not None else default_beach
    if detected_beach is not None:
        beach_source = "ocr" if ocr_beach is not None else "speech"
    elif default_beach is not None:
        beach_source = "default"
    else:
        beach_source = None

    result = {
        "channel":       label,
        "video_id":      video_id,
        "url":           video_url,
        "timestamp":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcript":    speech_text,
        "ocr_text":      ocr_text,
        "date":          ocr_date  if ocr_date  is not None else speech_date,
        "date_source":   "ocr" if ocr_date  is not None else ("speech" if speech_date  is not None else None),
        "sea_temp":      ocr_temp  if ocr_temp  is not None else speech_temp,
        "sea_temp_source": "ocr" if ocr_temp  is not None else ("speech" if speech_temp  is not None else None),
        "beach":         final_beach,
        "beach_source":  beach_source,
        "time":          ocr_time  if ocr_time  is not None else speech_time,
        "time_source":   "ocr" if ocr_time  is not None else ("speech" if speech_time  is not None else None),
    }
    print(f"  [{label}] дата={result['date']} темп={result['sea_temp']}°C"
          f"({result['sea_temp_source']}) время={result['time']}({result['time_source']}) "
          f"пляж={result['beach']}")

    # Если не нашлось ни температуры, ни даты — это, скорее всего, не ролик
    # с замером (например, случайный тренд/аудио-клип в ленте канала).
    # Отмечаем ролик просмотренным (чтобы не гонять Whisper повторно), но
    # НЕ засоряем историю бесполезной записью.
    if result["sea_temp"] is None and result["date"] is None:
        print(f"  [{label}] похоже, это не ролик с замером — пропускаю запись в историю")
        entry["last_video_id"] = video_id
        entry["last_skipped_reason"] = "no temp/date parsed (вероятно нерелевантный ролик)"
        return

    entry.pop("last_skipped_reason", None)
    entry.pop("last_error", None)
    history.append(result)
    entry["last_video_id"] = video_id


def main():
    channels = load_json(CHANNELS_FILE, [])
    history  = load_json(HISTORY_FILE, [])

    if not channels:
        print("  [WARN] data/tiktok_channels.json пуст — нечего обрабатывать")
        return

    for i, entry in enumerate(channels):
        if i > 0:
            print("  пауза 20с между каналами (снизить риск rate-limit TikTok)...")
            time.sleep(20)
        process_channel(entry, history)

    save_json(CHANNELS_FILE, channels)
    save_json(HISTORY_FILE, history)


if __name__ == "__main__":
    main()
