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
или вручную: python3 scripts/make_blocks.py [--force]
"""

import json, os, re, asyncio, argparse, random
from datetime import datetime, timezone, timedelta
import edge_tts

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE  = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
BLOCKS_DIR  = os.path.join(BASE_DIR, "data", "blocks")
META_FILE   = os.path.join(BLOCKS_DIR, "blocks_meta.json")

VOICES = [
    "ru-RU-SvetlanaNeural",   # женский
    "ru-RU-DmitryNeural",     # мужской
    "ru-RU-DariyaNeural",     # женский, другой тембр
]
RATE  = "-5%"

MONTH_RU = [
    'января','февраля','марта','апреля','мая','июня',
    'июля','августа','сентября','октября','ноября','декабря'
]

# ── Блоки — порядок и названия ───────────────────────────────────────────────
BLOCK_DEFS = [
    ("today",    "Сегодня",     "block_0_today.mp3",    "Сегодня",        "☀️"),
    ("tomorrow", "Завтра",      "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),
    ("warnings", "\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("trend",    "Тенденция",   "block_4_trend.mp3",    "Тенденция",      "📈"),
]

# ── Парсинг секций ────────────────────────────────────────────────────────────

def parse_sections(text):
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

# ── TTS preprocess ────────────────────────────────────────────────────────────

def preprocess_tts(text):
    # Предупреждения
    text = text.replace('\u26a0\ufe0f', 'Внимание!')
    text = text.replace('\u26a0', 'Внимание!')

    # Диапазоны температур: 14–16°C / -2-+3°C → от 14 до 16 градусов Цельсия
    # Тире: обычное, en-dash, em-dash
    text = re.sub(
        r'(-?\d+)\s*[\u2013\u2014\-]\s*(-?\d+)\s*\u00b0C',
        lambda m: f'от {m.group(1)} до {m.group(2)} градусов Цельсия',
        text
    )

    # Одиночные температуры со склонением
    def temp_word(m):
        n = abs(int(m.group(1)))
        last2 = n % 100
        last1 = n % 10
        if 11 <= last2 <= 19:
            w = 'градусов'
        elif last1 == 1:
            w = 'градус'
        elif 2 <= last1 <= 4:
            w = 'градуса'
        else:
            w = 'градусов'
        return f'{m.group(1)} {w} Цельсия'

    text = re.sub(r'(-?\d+)\s*\u00b0C', temp_word, text)
    text = text.replace('\u00b0C', 'градусов Цельсия')
    text = text.replace('\u00b0', ' градусов')

    # Давление
    text = text.replace('гПа', 'гектопаскалей')

    # Скорость ветра
    text = re.sub(r'(\d+(?:\.\d+)?)\s*м/с', r'\1 метров в секунду', text)

    # Осадки
    text = re.sub(r'(\d+(?:\.\d+)?)\s*мм', r'\1 миллиметра', text)

    # Энергия
    text = text.replace('Дж/кг', 'джоулей на килограмм')

    # Аббревиатуры — до decimal_to_words чтобы не ломать числа
    text = re.sub(r'\bCAPE\b', 'индекс конвективной энергии', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    text = re.sub(r'\bCIN\b', 'конвективное торможение', text)
    text = re.sub(r'\bT-Td\b', 'дефицит точки росы', text)
    text = re.sub(r'\bKI\b', 'индекс Кельтса', text)
    text = re.sub(r'\bTT\b', 'индекс тотальных тотал', text)

    # Десятичные дроби
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

    # Проценты
    text = re.sub(r'(\d+)\s*%', r'\1 процентов', text)

    # Убираем markdown
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*+', '', text)

    # Убираем лишние пробелы
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()

# ── TTS ───────────────────────────────────────────────────────────────────────

_selected_voice = VOICES[0]  # будет выбран в main()

async def _tts_async(text, out_path):
    communicate = edge_tts.Communicate(text, voice=_selected_voice, rate=RATE)
    await communicate.save(out_path)

def generate_block_tts(text, out_path):
    clean = preprocess_tts(text)
    if not clean.strip():
        return 0
    asyncio.run(_tts_async(clean, out_path))
    size_kb = os.path.getsize(out_path) // 1024
    print(f"    \u2192 {os.path.basename(out_path)} ({size_kb} \u043a\u0431)")
    return size_kb

# ── Длительность mp3 ─────────────────────────────────────────────────────────

def get_mp3_duration(path):
    try:
        size = os.path.getsize(path)
        return round(size / 16000, 1)
    except:
        return 0

# ── Основная логика ───────────────────────────────────────────────────────────

def main(force=False):
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
    if not force and existing_meta.get('data_hash') == src_hash and src_hash:
        print("  [BLOCKS] Данные не изменились — пропускаю генерацию блоков")
        return

    # Выбираем голос рандомно для этого запуска
    global _selected_voice
    _selected_voice = random.choice(VOICES)
    print(f"  [BLOCKS] Голос: {_selected_voice}")
    print("  [BLOCKS] Генерирую блоки озвучки...")

    # Дата для заголовков блоков
    gen_at = data.get('generated_at', '')
    try:
        base_dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00'))
    except Exception:
        base_dt = datetime.now(timezone.utc)

    def date_label(dt):
        return f"{dt.day} {MONTH_RU[dt.month - 1]}"

    DATE_PREFIX = {
        'today':    f"Сегодня, {date_label(base_dt)}. ",
        'tomorrow': f"Завтра, {date_label(base_dt + timedelta(days=1))}. ",
    }

    blocks_meta = []
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:
        section_text = find_section(sections, section_title)

        if not section_text.strip():
            print(f"    \u2192 {filename}: пропущен (пусто)")
            continue

        # Добавляем дату в начало озвучки для today/tomorrow
        tts_text = DATE_PREFIX.get(key, '') + section_text

        out_path = os.path.join(BLOCKS_DIR, filename)
        size_kb = generate_block_tts(tts_text, out_path)

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

    meta = {
        "generated_at": data.get('generated_at', ''),
        "data_hash":    src_hash,
        "voice":        _selected_voice,
        "blocks_count": len(blocks_meta),
        "blocks":       blocks_meta,
    }
    with open(META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    total_dur = sum(b['duration'] for b in blocks_meta)
    print(f"  [BLOCKS] \u2705 {len(blocks_meta)} блоков, ~{total_dur:.0f} сек суммарно")
    print(f"  [BLOCKS] Мета: {META_FILE}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Перегенерировать даже если данные не изменились")
    a = p.parse_args()
    main(force=a.force)
