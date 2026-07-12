"""
Тестовый (разовый) скрипт: скачивает аудио из TikTok-ролика по ссылке,
распознаёт речь (Whisper) и пытается вытащить упоминание температуры
морской воды. Это MVP для проверки, что подход вообще работает на
конкретном ролике — до того как городить постоянный пайплайн по
нескольким каналам.

Использование (локально или в GitHub Actions):
    python3 scripts/fetch_tiktok_sea_temp.py "https://vt.tiktok.com/ZSXY59J4y/"

Зависимости (не входят в основной пайплайн, ставятся отдельно в workflow):
    pip install yt-dlp openai-whisper
    apt-get install ffmpeg

Результат пишется (накопительно, по url) в data/tiktok_sea_temp.json:
    [{"url":..., "timestamp": ISO8601Z, "transcript": "...",
      "sea_temp": float|None}, ...]

Ограничение: распаршиваются только цифровые упоминания вида
"температура ... 22 градус..." / "22°". Числительные словами
("двадцать два") пока не разбираются — если модель их не запишет
цифрами, потребуется расширить парсер.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "tiktok_sea_temp.json")

# Число может идти с десятичной запятой/точкой (например "20,2 градуса"),
# перед числом могут стоять уточняющие слова вроде "в Одессе" — окно расширено.
TEMP_RE = re.compile(
    r'температур[а-яіїєґ]*\s+(?:вод[а-яіїєґ]*\s+)?(?:[а-яіїєґ\s]{0,25}?)(\d{1,2}(?:[.,]\d)?)\s*градус',
    re.IGNORECASE
)


def download_audio(url, workdir):
    out_tmpl = os.path.join(workdir, "audio.%(ext)s")
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "-o", out_tmpl, url],
        check=True, cwd=workdir
    )
    for name in os.listdir(workdir):
        if name.startswith("audio."):
            return os.path.join(workdir, name)
    raise RuntimeError("yt-dlp не создал аудиофайл")


def transcribe(audio_path):
    import whisper
    model = whisper.load_model("small")
    result = model.transcribe(audio_path, language="ru")
    return result.get("text", "")


def parse_sea_temp(text):
    m = TEMP_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if val < 3 or val > 32:
        return None
    return val


def main():
    if len(sys.argv) < 2:
        print("Usage: fetch_tiktok_sea_temp.py <url>")
        sys.exit(1)
    url = sys.argv[1]

    with tempfile.TemporaryDirectory() as workdir:
        print(f"  Скачиваю аудио: {url}")
        audio_path = download_audio(url, workdir)

        print("  Распознаю речь (Whisper)...")
        text = transcribe(audio_path)
        print(f"  Транскрипт: {text!r}")

    sea_temp = parse_sea_temp(text)
    if sea_temp is None:
        print("  [WARN] температура воды в транскрипте не найдена / не распарсилась")
    else:
        print(f"  ✓ Распознана температура воды: {sea_temp}°C")

    entry = {
        "url":        url,
        "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcript": text,
        "sea_temp":   sea_temp,
    }

    history = []
    if os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(entry)

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
