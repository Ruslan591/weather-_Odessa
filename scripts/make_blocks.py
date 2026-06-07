#!/usr/bin/env python3
"""
make_blocks.py — нарезка forecast_analysis_claude.json на блоки с озвучкой.
Запуск: python3 scripts/make_blocks.py [--force]
"""

import json, os, re, asyncio, argparse, random, subprocess
from datetime import datetime, timezone, timedelta
import edge_tts
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_BODY_SIZE = 52
LINES_PER_PAGE = 15

FONT_CANDIDATES = [
    "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/NotoSans-Regular.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
]

def _find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p): return p
    return None

def _get_font():
    p = _find_font()
    if p:
        try: return ImageFont.truetype(p, FONT_BODY_SIZE)
        except: pass
    return ImageFont.load_default()

def _wrap_text(text, font, maxw, draw):
    words = text.split()
    lines = []; cur = []
    for w in words:
        t = ' '.join(cur + [w])
        if draw.textbbox((0,0), t, font=font)[2] > maxw and cur:
            lines.append(' '.join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def split_into_pages(text):
    raw = re.sub(r'\*+', '', re.sub(r'\s+', ' ', text)).strip()
    paragraphs = [p.strip() for p in raw.split('\n') if p.strip()]
    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img)
    font = _get_font()
    maxw = W - 130
    all_lines = []
    for para in paragraphs:
        all_lines.extend(_wrap_text(para, font, maxw, draw))
        all_lines.append('')
    while all_lines and all_lines[-1] == '': all_lines.pop()
    pages = []
    i = 0
    while i < len(all_lines):
        pages.append(' '.join(l for l in all_lines[i:i+LINES_PER_PAGE] if l))
        i += LINES_PER_PAGE
    return pages

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE  = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
BLOCKS_DIR  = os.path.join(BASE_DIR, "data", "blocks")
META_FILE   = os.path.join(BLOCKS_DIR, "blocks_meta.json")

VOICES = [
    "ru-RU-SvetlanaNeural",
    "ru-RU-DmitryNeural",
    "ru-RU-DariyaNeural",
]
RATE = "-5%"

MONTH_RU = [
    'января','февраля','марта','апреля','мая','июня',
    'июля','августа','сентября','октября','ноября','декабря'
]

# Ключи поиска секций по режиму (mode → prefix для find_section)
MODE_BLOCK1 = {
    "night":     ("today",   "Сегодня",        "block_0_today.mp3",    "Сегодня",        "☀️"),
    "morning":   ("today",   "Утром и днём",   "block_0_today.mp3",    "Утром и днём",   "🌅"),
    "midday":    ("today",   "Днём и вечером", "block_0_today.mp3",    "Днём и вечером", "☀️"),
    "afternoon": ("today",   "Сегодня вечером","block_0_today.mp3",    "Сегодня вечером","🌆"),
    "evening":   ("tonight", "Этой ночью",     "block_0_tonight.mp3",  "Этой ночью",     "🌙"),
}
MODE_BLOCK2 = {
    "night":     ("tomorrow","Завтра",          "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    "morning":   ("tomorrow","Завтра",          "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    "midday":    ("tomorrow","Завтра",          "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    "afternoon": ("tomorrow","Завтра",          "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    "evening":   ("tomorrow","Завтра днём",     "block_1_tomorrow.mp3", "Завтра",         "🌤"),
}
BLOCK_DEFS_COMMON = [
    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),
    ("warnings", "\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("marine",   "\U0001f30a", "block_4_marine.mp3",   "Море",           "🌊"),
    ("trend",    "Тенденция",   "block_5_trend.mp3",    "Тенденция",      "📈"),
]

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

def preprocess_tts(text):
    # Предупреждения
    text = text.replace('\u26a0\ufe0f', 'Внимание!')
    text = text.replace('\u26a0', 'Внимание!')

    # Украинская С (U+0421) вместо латинской C — edge_tts падает
    text = text.replace('\u00b0\u0421', '\u00b0C')
    text = text.replace('\u00b0\u0441', '\u00b0C')

    # Защищаем диапазоны дат (9-10 июня, 7-8 июля и т.п.) — временная замена
    text = re.sub(
        r'(\d{1,2})\s*[-\u2013\u2014]\s*(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)',
        lambda m: f'с {m.group(1)} по {m.group(2)} {m.group(3)}',
        text
    )

    # Диапазоны температур: 14–16°C → 14–16 градусов (без "от...до" чтобы не дублировать предлоги)
    text = re.sub(
        r'(-?\d+)\s*[-\u2013\u2014]\s*(-?\d+)\s*\u00b0C',
        lambda m: f'{m.group(1)}\u2013{m.group(2)} градусов',
        text
    )

    # Одиночные температуры со склонением (без слова Цельсия)
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
        return f'{m.group(1)} {w}'

    text = re.sub(r'(-?\d+)\s*\u00b0C', temp_word, text)
    text = text.replace('\u00b0C', 'градусов')
    text = text.replace('\u00b0', ' градусов')

    # Давление
    text = text.replace('гПа', 'гектопаскалей')

    # Скорость ветра
    text = re.sub(r'(\d+(?:\.\d+)?)\s*м/с', r'\1 метров в секунду', text)

    # Осадки
    text = re.sub(r'(\d+(?:\.\d+)?)\s*мм', r'\1 миллиметра', text)

    # Энергия
    text = text.replace('Дж/кг', 'джоулей на килограмм')

    # Аббревиатуры — T-Td заменяем БЕЗ слова «дефицит» чтобы не дублировать
    text = re.sub(r'\bT-Td\b', 'точки росы', text)
    text = re.sub(r'\bCAPE\b', 'индекс конвективной энергии', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    text = re.sub(r'\bCIN\b', 'конвективное торможение', text)
    text = re.sub(r'\bKI\b', 'индекс Кельтса', text)

    # Ударения
    text = text.replace('малооблачн', 'малоо\u0301блачн')

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
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()

_selected_voice = VOICES[0]

async def _tts_async(text, out_path):
    communicate = edge_tts.Communicate(text, voice=_selected_voice, rate=RATE)
    await communicate.save(out_path)

def strip_silence(path):
    """Убирает тишину в начале и конце mp3 через ffmpeg."""
    tmp = path + ".tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", path,
        "-af", "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB"
               ":stop_periods=1:stop_silence=0.05:stop_threshold=-50dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        tmp
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)

def generate_block_tts(text, out_path, retries=3, delay=5, trim_silence=False):
    import time
    clean = preprocess_tts(text)
    if not clean.strip():
        return 0
    for attempt in range(1, retries + 1):
        try:
            asyncio.run(_tts_async(clean, out_path))
            if trim_silence:
                strip_silence(out_path)
            size_kb = os.path.getsize(out_path) // 1024
            print(f"    \u2192 {os.path.basename(out_path)} ({size_kb} кб)")
            return size_kb
        except Exception as e:
            print(f"    [TTS] Ошибка (попытка {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
    print(f"    [TTS] Не удалось сгенерировать {os.path.basename(out_path)} — пропускаю")
    return 0

def get_mp3_duration(path):
    try:
        size = os.path.getsize(path)
        return round(size / 16000, 1)
    except:
        return 0

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

    global _selected_voice
    _selected_voice = random.choice(VOICES)
    print(f"  [BLOCKS] Голос: {_selected_voice}")
    print("  [BLOCKS] Генерирую блоки озвучки...")

    gen_at = data.get('generated_at', '')
    try:
        base_dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00')).astimezone()
    except Exception:
        base_dt = datetime.now(timezone.utc).astimezone()

    now_local = datetime.now(timezone.utc).astimezone()
    now_utc_h = datetime.now(timezone.utc).hour

    # Определяем режим по UTC часу генерации
    gen_utc_h = base_dt.utctimetuple().tm_hour
    if 0 <= gen_utc_h < 6:    gen_mode = "night"
    elif 6 <= gen_utc_h < 10: gen_mode = "morning"
    elif 10 <= gen_utc_h < 13: gen_mode = "midday"
    elif 13 <= gen_utc_h < 16: gen_mode = "afternoon"
    else:                       gen_mode = "evening"

    # Если анализ дневной но уже вечер — блок today устарел
    today_stale = (gen_mode != "evening") and (now_local.hour >= 20)

    def date_label(dt):
        return f"{dt.day} {MONTH_RU[dt.month - 1]}"

    DATE_PREFIX = {
        'today':    f"{date_label(base_dt)}. ",
        'tonight':  "Сегодня ночью. ",
        'tomorrow': f"Завтра, {date_label(base_dt + timedelta(days=1))}. ",
    }

    b1 = MODE_BLOCK1[gen_mode]
    b2 = MODE_BLOCK2[gen_mode]
    BLOCK_DEFS = [b1, b2] + BLOCK_DEFS_COMMON

    blocks_meta = []
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:
        if key == 'today' and today_stale:
            print(f"    → {filename}: пропущен (устарел, уже вечер)")
            continue
        section_text = find_section(sections, section_title)

        if not section_text.strip():
            print(f"    \u2192 {filename}: пропущен (пусто)")
            continue

        tts_text = DATE_PREFIX.get(key, '') + section_text
        out_path = os.path.join(BLOCKS_DIR, filename)
        size_kb = generate_block_tts(tts_text, out_path)

        if size_kb > 0:
            # Постраничные mp3
            pages = split_into_pages(section_text)
            page_files = []
            for pi, page_text in enumerate(pages):
                page_tts = DATE_PREFIX.get(key, '') + page_text if pi == 0 else page_text
                page_fn = filename.replace('.mp3', f'_p{pi+1}.mp3')
                page_path = os.path.join(BLOCKS_DIR, page_fn)
                psize = generate_block_tts(page_tts, page_path, trim_silence=True)
                if psize > 0:
                    page_files.append({
                        "filename": page_fn,
                        "path": f"data/blocks/{page_fn}",
                        "duration": get_mp3_duration(page_path),
                        "text": page_text,
                    })
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
                "pages":    page_files,
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
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    main(force=a.force)
