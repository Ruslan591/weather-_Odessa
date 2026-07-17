#!/usr/bin/env python3
"""
Транскрипция mp3 -> текст для проверки произношения TTS-блоков (Claude/Gemini озвучка).

Использует SpeechRecognition + бесплатное Google Web Speech API (нужен интернет,
но НЕ нужна локальная модель — это важно, т.к. vosk не ставится в Termux
из-за отсутствия совместимого wheel под архитектуру Android).

Установка (один раз в Termux):
    pkg install ffmpeg
    pip install SpeechRecognition pydub

Использование:
    python scripts/transcribe_local.py input.mp3
    python scripts/transcribe_local.py input.mp3 --lang ru-RU
"""

import argparse
import os
import sys
import tempfile

try:
    import speech_recognition as sr
except ImportError:
    print("Ошибка: не установлен пакет SpeechRecognition.", file=sys.stderr)
    print("Установите: pip install SpeechRecognition pydub", file=sys.stderr)
    sys.exit(1)

try:
    from pydub import AudioSegment
except ImportError:
    print("Ошибка: не установлен пакет pydub.", file=sys.stderr)
    print("Установите: pip install pydub", file=sys.stderr)
    sys.exit(1)


def convert_to_wav(mp3_path: str, wav_path: str) -> None:
    """Конвертирует mp3 в wav 16kHz mono через pydub (требует ffmpeg в PATH)."""
    try:
        audio = AudioSegment.from_mp3(mp3_path)
    except Exception as e:
        print(f"Ошибка конвертации (проверьте, что установлен ffmpeg: pkg install ffmpeg): {e}", file=sys.stderr)
        sys.exit(1)
    audio = audio.set_frame_rate(16000).set_channels(1)
    audio.export(wav_path, format="wav")


def transcribe(wav_path: str, language: str) -> str:
    r = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio = r.record(source)
    try:
        return r.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        return "[не удалось распознать речь — возможно, тишина или сильный шум]"
    except sr.RequestError as e:
        print(f"Ошибка запроса к сервису распознавания (нужен интернет): {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Транскрипция mp3 в текст (Google Web Speech API)")
    parser.add_argument("mp3", help="Путь к mp3-файлу")
    parser.add_argument("--lang", default="ru-RU", help="Код языка (по умолчанию: ru-RU)")
    args = parser.parse_args()

    if not os.path.isfile(args.mp3):
        print(f"Ошибка: файл '{args.mp3}' не найден.", file=sys.stderr)
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        convert_to_wav(args.mp3, wav_path)
        text = transcribe(wav_path, args.lang)
        print(text)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


if __name__ == "__main__":
    main()
