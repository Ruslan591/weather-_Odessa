"""
Диагностический скрипт: генерирует несколько mp3-вариантов слова
"Одесса" с разной разметкой ударения, чтобы на слух сравнить,
какой вариант edge-tts читает стабильно правильно (Оде́сса)
на обоих используемых в проекте голосах.
"""
import asyncio
import os
import edge_tts

OUT_DIR = "diag_odessa_out"
os.makedirs(OUT_DIR, exist_ok=True)

VOICES = ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"]

# Варианты текста для теста
VARIANTS = {
    "01_baseline_no_mark":      "Одесса",
    "02_current_u0301_after_e": "Оде\u0301сса",          # текущий вариант из make_blocks_gemini_cloud.py
    "03_plus_before_vowel":     "Од+есса",                # альтернативная разметка (+ перед гласной)
    "04_in_sentence_current":   "Сегодня в Оде\u0301ссе ожидается ясная погода.",
    "05_in_sentence_baseline":  "Сегодня в Одессе ожидается ясная погода.",
}

RATE = "+0%"
PITCH = "+0Hz"

async def gen(text, voice, out_path):
    communicate = edge_tts.Communicate(text, voice=voice, rate=RATE, pitch=PITCH)
    await communicate.save(out_path)

async def main():
    for voice in VOICES:
        voice_tag = "svetlana" if "Svetlana" in voice else "dmitry"
        for name, text in VARIANTS.items():
            out_path = os.path.join(OUT_DIR, f"{name}__{voice_tag}.mp3")
            print(f"-> {out_path}  :  {text!r}")
            await gen(text, voice, out_path)

if __name__ == "__main__":
    asyncio.run(main())
    print("Готово. Файлы в", OUT_DIR)
