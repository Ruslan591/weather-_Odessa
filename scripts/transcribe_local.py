#!/usr/bin/env python3
"""
Локальная транскрипция mp3 -> текст через Vosk (офлайн, для Termux).
Используется для проверки произношения TTS-блоков (Claude/Gemini озвучка).

Установка (один раз в Termux):
    pkg install ffmpeg
    pip install vosk

Модель (один раз, ~50 МБ):
    cd ~/storage/shared/Documents/weather/
    curl -LO https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
    unzip vosk-model-small-ru-0.22.zip

Использование:
    python scripts/transcribe_local.py input.mp3
    python scripts/transcribe_local.py input.mp3 --model vosk-model-small-ru-0.22
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave

try:
    from vosk import Model, KaldiRecognizer
except ImportError:
    print("Ошибка: не установлен пакет vosk. Установите: pip install vosk", file=sys.stderr)
    sys.exit(1)


def convert_to_wav(mp3_path: str, wav_path: str) -> None:
    """Конвертирует mp3 в wav 16kHz mono через ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", mp3_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Ошибка ffmpeg:", result.stderr, file=sys.stderr)
        sys.exit(1)


def transcribe(wav_path: str, model_path: str) -> str:
    if not os.path.isdir(model_path):
        print(f"Ошибка: модель не найдена по пути '{model_path}'.", file=sys.stderr)
        print("Скачайте: https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip", file=sys.stderr)
        sys.exit(1)

    model = Model(model_path)
    wf = wave.open(wav_path, "rb")

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
        print("Ошибка: ожидается WAV mono 16-bit (конвертация должна была это обеспечить).", file=sys.stderr)
        sys.exit(1)

    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    full_text = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            part = json.loads(rec.Result()).get("text", "")
            if part:
                full_text.append(part)

    final_part = json.loads(rec.FinalResult()).get("text", "")
    if final_part:
        full_text.append(final_part)

    return " ".join(full_text).strip()


def main():
    parser = argparse.ArgumentParser(description="Транскрипция mp3 в текст (офлайн, Vosk)")
    parser.add_argument("mp3", help="Путь к mp3-файлу")
    parser.add_argument(
        "--model",
        default="vosk-model-small-ru-0.22",
        help="Путь к папке с моделью Vosk (по умолчанию: vosk-model-small-ru-0.22)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.mp3):
        print(f"Ошибка: файл '{args.mp3}' не найден.", file=sys.stderr)
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        convert_to_wav(args.mp3, wav_path)
        text = transcribe(wav_path, args.model)
        print(text)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


if __name__ == "__main__":
    main()
