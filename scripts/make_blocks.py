#!/usr/bin/env python3
"""
make_blocks.py — нарезка forecast_analysis_claude.json на блоки с озвучкой.
Читает data/forecast_analysis_claude.json, генерирует:
  data/blocks/block_0_today.mp3
  data/blocks/block_1_tomorrow.mp3
  data/blocks/block_2_next3.mp3
  data/blocks/block_3_warnings.mp3   (только если есть предупреждения)
  data/blocks/block_4_trend.mp3
  data/blocks/blocks_meta.json       (мета: заголовки, длительности, наличие)

Вызывается из check_model_runs.py после generate_ai_analysis.py,
или вручную: python3 scripts/make_blocks.py
"""

import json, os, re, asyncio
from datetime import datetime, timezone
import edge_tts

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE  = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
BLOCKS_DIR  = os.path.join(BASE_DIR, "data", "blocks")
META_FILE   = os.path.join(BLOCKS_DIR, "blocks_meta.json")

VOICE = "ru-RU-SvetlanaNeural"
RATE  = "-5%"

# ── Блоки — порядок и названия ────────────────────────────────────────────────
# Префиксы — ищем по началу заголовка (дата в скобках игнорируется)
BLOCK_DEFS = [
    ("today",    "Сегодня",     "block_0_today.mp3",    "Сегодня",        "☀️"),
    ("tomorrow", "Завтра",      "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),
    ("warnings", "\u26a0",     "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("trend",    "Тенденция",   "block_4_trend.mp3",    "Тенденция",      "📈"),
]

# ── Парсинг секций ────────────────────────────────────────────────────────────

def parse_sections(text):
    """Разбивает markdown-текст на секции по ## заголовкам."""
    sections = {}
    current_key = None
    current_lines = []
    for line in text.split('\n'):
        if line.startswith('## '):
            if current_key is not None:
                sections[current_key] = '\n'.join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_key is not None:
        sections[current_key] = '\n'.join(current_lines).strip()
    return sections

def find_section(sections, prefix):
    for key, val in sections.items():
        if key.startswith(prefix):
            return val
    return ''

# ── Подготовка текста для TTS (из generate_ai_analysis.py) ───────────────────

def preprocess_tts(text):
    text = text.replace('\u26a0\ufe0f', 'Внимание!')
    text = text.replace('\u26a0', 'Внимание!')
    text = text.replace('гПа', 'гектопаскалей')
    text = re.sub(r'(\d+)\s*\u00b0C', r'\1 градуса Цельсия', text)
    text = re.sub(r'(-\d+)\s*\u00b0C', r'\1 градуса Цельсия', text)
    text = text.replace('\u00b0C', 'градусов Цельсия')
    text = re.sub(r'(\d+(?:\.\d+)?)\s*м/с', r'\1 метров в секунду', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*мм', r'\1 миллиметра', text)
    text = text.replace('Дж/кг', 'джоулей на килограмм')

    def decimal_to_words(m):
        int_part = m.group(1)
        dec_part = m.group(2)
        if len(dec_part) == 1:
            tenth = {
                '1': 'одна', '2': 'две', '3': 'три', '4': 'четыре',
                '5': 'пять', '6': 'шесть', '7': 'семь',
                '8': 'восемь', '9': 'девять', '0': 'ноль'
            }
            return f"{int_part} целых {tenth.get(dec_part, dec_part)} десятых"
        return f"{int_part} целых {dec_part} сотых"

    text = re.sub(r'(\d+)\.(\d{1,2})', decimal_to_words, text)
    text = re.sub(r'(\d+)\s*%', r'\1 процентов', text)
    text = text.replace('CAPE', 'индекс CAPE')
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*+', '', text)
    return text

# ── TTS ───────────────────────────────────────────────────────────────────────

async def _tts_async(text, out_path):
    communicate = edge_tts.Communicate(text, voice=VOICE, rate=RATE)
    await communicate.save(out_path)

def generate_block_tts(text, out_path):
    clean = preprocess_tts(text)
    if not clean.strip():
        return 0
    asyncio.run(_tts_async(clean, out_path))
    size_kb = os.path.getsize(out_path) // 1024
    print(f"    → {os.path.basename(out_path)} ({size_kb} кб)")
    return size_kb

# ── Длительность mp3 ─────────────────────────────────────────────────────────

def get_mp3_duration(path):
    """Приблизительная длительность mp3 в секундах по размеру файла."""
    try:
        size = os.path.getsize(path)
        # edge_tts ~128 kbps = 16000 байт/сек
        return round(size / 16000, 1)
    except:
        return 0

# ── Основная логика ───────────────────────────────────────────────────────────

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"  [BLOCKS] Файл не найден: {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text = data.get('text', '')
    if not text:
        print("  [BLOCKS] Нет текста в JSON")
        return

    os.makedirs(BLOCKS_DIR, exist_ok=True)

    sections = parse_sections(text)
    print(f"\n  [BLOCKS] Найдено секций: {list(sections.keys())}")

    # Проверяем изменился ли текст
    existing_meta = {}
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, 'r', encoding='utf-8') as f:
                existing_meta = json.load(f)
        except:
            pass

    src_hash = data.get('data_hash', '')
    if existing_meta.get('data_hash') == src_hash and src_hash:
        print("  [BLOCKS] Данные не изменились — пропускаю генерацию блоков")
        return

    print("  [BLOCKS] Генерирую блоки озвучки...")

    blocks_meta = []
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:
        section_text = find_section(sections, section_title)

        # Пропускаем пустые блоки (например, нет предупреждений)
        if not section_text.strip():
            print(f"    → {filename}: пропущен (пусто)")
            continue

        out_path = os.path.join(BLOCKS_DIR, filename)
        size_kb = generate_block_tts(section_text, out_path)

        if size_kb > 0:
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
            })

    # Сохраняем мета
    meta = {
        "generated_at": data.get('generated_at', ''),
        "data_hash":    src_hash,
        "blocks_count": len(blocks_meta),
        "blocks":       blocks_meta,
    }
    with open(META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    total_dur = sum(b['duration'] for b in blocks_meta)
    print(f"  [BLOCKS] ✅ {len(blocks_meta)} блоков, ~{total_dur:.0f} сек суммарно")
    print(f"  [BLOCKS] Мета: {META_FILE}")

if __name__ == "__main__":
    main()
