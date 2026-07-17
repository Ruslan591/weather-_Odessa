#!/usr/bin/env python3
"""
make_blocks.py — нарезка forecast_analysis_gemini.json на блоки с озвучкой.

Cloud-версия для GitHub Actions. Идентична телефонной (make_blocks_gemini.py),
кроме добавленного Ubuntu-пути к шрифту DejaVuSans. Логику НЕ менять без
зеркального патча в scripts/make_blocks_gemini.py.

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
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
INPUT_FILE  = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
BLOCKS_DIR  = os.path.join(BASE_DIR, "data", "blocks_gemini")
META_FILE   = os.path.join(BLOCKS_DIR, "blocks_meta.json")

VOICES = [
    "ru-RU-SvetlanaNeural",
    "ru-RU-DmitryNeural",
]
RATE = "-5%"
PITCH = "+10Hz"

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
    ("verification", "📊 Точность", "block_v_verification.mp3", "Точность прогноза", "📊"),
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

def find_section(sections, *prefixes):
    for prefix in prefixes:
        for key, val in sections.items():
            if key.startswith(prefix):
                return val
    return ''

# Порядковые числительные для диапазонов дат (родительный после "с", именительный/винительный после "по")
_ORDINAL_GEN = {
    1:'первого',2:'второго',3:'третьего',4:'четвёртого',5:'пятого',
    6:'шестого',7:'седьмого',8:'восьмого',9:'девятого',10:'десятого',
    11:'одиннадцатого',12:'двенадцатого',13:'тринадцатого',14:'четырнадцатого',
    15:'пятнадцатого',16:'шестнадцатого',17:'семнадцатого',18:'восемнадцатого',
    19:'девятнадцатого',20:'двадцатого',30:'тридцатого',31:'тридцать первого',
}
for _u, _w in {1:'первого',2:'второго',3:'третьего',4:'четвёртого',5:'пятого',
               6:'шестого',7:'седьмого',8:'восьмого',9:'девятого'}.items():
    _ORDINAL_GEN[20+_u] = f'двадцать {_w}'

_ORDINAL_NOM = {
    1:'первое',2:'второе',3:'третье',4:'четвёртое',5:'пятое',
    6:'шестое',7:'седьмое',8:'восьмое',9:'девятое',10:'десятое',
    11:'одиннадцатое',12:'двенадцатое',13:'тринадцатое',14:'четырнадцатое',
    15:'пятнадцатое',16:'шестнадцатое',17:'семнадцатое',18:'восемнадцатое',
    19:'девятнадцатое',20:'двадцатое',30:'тридцатое',31:'тридцать первое',
}
for _u, _w in {1:'первое',2:'второе',3:'третье',4:'четвёртое',5:'пятое',
               6:'шестое',7:'седьмое',8:'восьмое',9:'девятое'}.items():
    _ORDINAL_NOM[20+_u] = f'двадцать {_w}'

_MONTHS_RE = r'(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)'

def _decline(n, one, few, many):
    """Склонение числительных: 1->one, 2-4->few, 5-20->many (кроме 11-19->many)."""
    n = abs(int(round(n)))
    last2 = n % 100
    last1 = n % 10
    if 11 <= last2 <= 19: return many
    if last1 == 1: return one
    if 2 <= last1 <= 4: return few
    return many

def _range_sub(text, unit_pattern, unit_word, allow_decimal=False):
    """Диапазон "X-Y{unit}" -> "от X до Y {unit_word}". Если перед диапазоном
    уже стоит предлог "от"/"до" (частая формулировка вроде "опускалась до
    15-16°C"), не дублирует предлог, а просто вставляет "до" между числами."""
    num_pat = r'-?\d+(?:[.,]\d+)?' if allow_decimal else r'-?\d+'
    pattern = re.compile(
        r'(?:(от|до)\s+)?(' + num_pat + r')\s*[-\u2013\u2014]\s*(' + num_pat + r')\s*' + unit_pattern,
        re.IGNORECASE
    )
    def repl(m):
        prep, n1, n2 = m.group(1), m.group(2), m.group(3)
        if prep:
            return f'{prep} {n1} до {n2} {unit_word}'
        return f'от {n1} до {n2} {unit_word}'
    return pattern.sub(repl, text)

def _dedupe_repeated_units(text, forms):
    """Если в одном предложении несколько отдельных чисел с одной и той же
    словесной единицей измерения (напр. "с 26 градусов до 19 градусов" или
    "18 градусов ... 19 градусов ... 22 градуса"), убираем единицу у всех
    вхождений, кроме последнего в предложении — она проговаривается один раз
    в конце, а не после каждого числа."""
    unit_alt = '|'.join(sorted(forms, key=len, reverse=True))
    pattern = re.compile(r'(-?\d+(?:[.,]\d+)?)(\s+)(' + unit_alt + r')\b')

    def process_sentence(sent):
        matches = list(pattern.finditer(sent))
        if len(matches) < 2:
            return sent
        last_idx = len(matches) - 1
        out = []
        pos = 0
        for i, m in enumerate(matches):
            out.append(sent[pos:m.start()])
            out.append(m.group(0) if i == last_idx else m.group(1))
            pos = m.end()
        out.append(sent[pos:])
        return ''.join(out)

    parts = re.split(r'([.!?]\s+)', text)
    for i in range(0, len(parts), 2):
        parts[i] = process_sentence(parts[i])
    return ''.join(parts)

def preprocess_tts(text):
    # Предупреждения
    text = text.replace('\u26a0\ufe0f', 'Внимание!')
    text = text.replace('\u26a0', 'Внимание!')

    # Украинская С (U+0421) вместо латинской C — edge_tts падает
    text = text.replace('\u00b0\u0421', '\u00b0C')
    text = text.replace('\u00b0\u0441', '\u00b0C')

    # Диапазоны дат вида "11-12 июля" -> "с одиннадцатого по двенадцатое июля"
    def _date_range(m):
        n1, n2 = int(m.group(1)), int(m.group(2))
        g1 = _ORDINAL_GEN.get(n1, str(n1))
        g2 = _ORDINAL_NOM.get(n2, str(n2))
        return f'с {g1} по {g2} {m.group(3)}'
    text = re.sub(
        r'(\d{1,2})\s*[-\u2013\u2014]\s*(\d{1,2})\s+' + _MONTHS_RE,
        _date_range, text
    )
    # Уже готовые "с X по Y месяца" (без дефиса) — та же проблема:
    # edge-tts иначе читает оба числа в родительном падеже ("по двенадцатого")
    def _date_spo(m):
        n1, n2 = int(m.group(1)), int(m.group(2))
        g1 = _ORDINAL_GEN.get(n1, str(n1))
        g2 = _ORDINAL_NOM.get(n2, str(n2))
        return f'с {g1} по {g2} {m.group(3)}'
    text = re.sub(
        r'\bс\s+(\d{1,2})\s+по\s+(\d{1,2})\s+' + _MONTHS_RE,
        _date_spo, text, flags=re.IGNORECASE
    )

    # Диапазоны температур: "15-16°C" -> "от 15 до 16 градусов"
    text = _range_sub(text, r'\u00b0C', 'градусов')

    # Одиночные температуры со склонением (без слова Цельсия)
    def temp_word(m):
        n = int(m.group(1))
        w = _decline(n, 'градус', 'градуса', 'градусов')
        return f'{m.group(1)} {w}'
    text = re.sub(r'(-?\d+)\s*\u00b0C', temp_word, text)
    text = text.replace('\u00b0C', 'градусов')
    text = text.replace('\u00b0', ' градусов')

    # Давление
    text = text.replace('гПа', 'гектопаскалей')
    # "700 гектопаскалей 3095 м" -> "700 гектопаскалей" (высота избыточна и режет слух)
    text = re.sub(r'(гектопаскалей)\s+\d+(?:[.,]\d+)?\s*м\b(?!/с)', r'\1', text)

    # Диапазоны скорости ветра: "2-5 м/с" -> "от 2 до 5 метров в секунду"
    text = _range_sub(text, r'м/с', 'метров в секунду', allow_decimal=True)
    def wind_word(m):
        n = float(m.group(1).replace(',', '.'))
        w = _decline(n, 'метр', 'метра', 'метров')
        return f'{m.group(1)} {w} в секунду'
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*м/с', wind_word, text)

    # Осадки
    text = re.sub(r'(\d+(?:\.\d+)?)\s*мм', r'\1 миллиметра', text)

    # Диапазоны в сантиметрах: "10-20 см" -> "10, 20 см"
    text = _range_sub(text, r'см\b', 'см')

    # Энергия
    text = text.replace('Дж/кг', 'джоулей на килограмм')

    # Аббревиатуры — T-Td заменяем БЕЗ слова «дефицит» чтобы не дублировать
    text = re.sub(r'\bT-Td\b', 'точки росы', text)
    text = re.sub(r'конвективной энергии\s*\(CAPE\)', 'индекса конвективной энергии', text, flags=re.IGNORECASE)
    text = re.sub(r'\bCAPE\b', 'индекс конвективной энергии', text)
    # Если перед LI уже стоит слово "индекс"/"индекса" и т.п. — не дублируем его
    text = re.sub(r'(?i)(\bиндекс[а-я]*)\s+LI\b', r'\1 неустойчивости', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    # CIN с падежными формами
    text = re.sub(r'(?i)(\bотрицательном|\bвысоком|\bнизком|\bсильном|\bслабом|\bувеличенном)\s+CIN\b', r'\1 конвективном торможении', text)
    text = re.sub(r'(?i)\b(увеличение|рост|снижение|уменьшение|значение|величина|присутствие)\s+CIN\b', r'\1 конвективного торможения', text)
    text = re.sub(r'(?i)\b(при|с|без|под)\s+CIN\b', r'\1 конвективным торможением', text)
    text = re.sub(r'\bCIN\b', 'конвективное торможение', text)
    # Убираем «бы» после глаголов прошедшего времени
    text = re.sub(r'(\w+(?:ла|ло|ли|лся|лась))\s+бы\b', r'\1', text)
    text = re.sub(r'\bKI\b', 'индекс Кельтса', text)

    # УФ-индекс -> развёрнуто (аббревиатура звучит коряво)
    text = re.sub(r'\bУФ[\s-]*индекс', 'ультрафиолетовый индекс', text, flags=re.IGNORECASE)

    # Ударения
    text = text.replace('малооблачн', 'малоо\u0301блачн')
    # 'Одесса' убрано из разметки ударений: тест показал, что u0301 не просто
    # не помогает, а полностью ломает распознавание слова этим голосом.
    # В реальных блоках слово всегда стоит внутри предложения ("в Одессе...",
    # "Одесса окажется...") и без разметки читается корректно само по себе.
    text = re.sub(r'([Пп])о-летнему', lambda m: m.group(1) + 'о-ле\u0301тнему', text)
    text = re.sub(r'\b(юго|северо)-(западн\w*|восточн\w*)', lambda m: f'{m.group(1)}\u2011{m.group(2)}', text)
    text = re.sub(r'(высотой)\s+волны\b', lambda m: m.group(1) + ' волны\u0301', text)
    _stress_forms = {'а':'а\u0301', 'е':'е\u0301', 'у':'у\u0301', 'ы':'ы\u0301', 'ой':'о\u0301й'}
    text = re.sub(r'\bжар([аеуы]|ой)\b', lambda m: 'жар' + _stress_forms[m.group(1)], text)
    text = re.sub(r'\bЖар([аеуы]|ой)\b', lambda m: 'Жар' + _stress_forms[m.group(1)], text)

    # "о чем" -> "о чём" (частый пропуск ё в исходном тексте; не трогаем
    # обычное "чем" без "о" — там ё не нужна, напр. "теплее, чем вчера")
    text = re.sub(r'\b([оО]) чем\b', r'\1 чём', text)

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

    # Диапазоны процентов: "20-25%" -> "от 20 до 25 процентов"
    text = _range_sub(text, r'%', 'процентов')
    def percent_word(m):
        n = int(m.group(1))
        w = _decline(n, 'процент', 'процента', 'процентов')
        return f'{m.group(1)} {w}'
    text = re.sub(r'(\d+)\s*%', percent_word, text)

    # Схлопываем дублирующиеся единицы измерения, если в одном предложении
    # несколько отдельных чисел подряд (температура, ветер, проценты)
    text = _dedupe_repeated_units(text, ['градус', 'градуса', 'градусов'])
    text = _dedupe_repeated_units(text, ['метр в секунду', 'метра в секунду', 'метров в секунду'])
    text = _dedupe_repeated_units(text, ['процент', 'процента', 'процентов'])

    # Убираем markdown
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()

_selected_voice = VOICES[0]

async def _tts_async(text, out_path, collect_boundaries=False):
    communicate = edge_tts.Communicate(text, voice=_selected_voice, rate=RATE, pitch=PITCH)
    boundaries = []
    with open(out_path, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary" and collect_boundaries:
                boundaries.append({
                    "offset": chunk["offset"] / 1e7,
                    "duration": chunk["duration"] / 1e7,
                    "text": chunk["text"],
                })
    return boundaries

def strip_silence(path):
    """Убирает тишину в начале, сжимает длинные внутренние паузы между
    предложениями до ~0.35с, и добавляет фиксированную паузу 0.5с в самом
    конце — чтобы между блоками при склейке видео была заметная, но не
    случайная пауза (просто обрезка тишины в 0 давала полное отсутствие
    паузы между блоками, а нерегулируемая natural-tail тишина от edge-tts
    была нестабильной от 0 до 1.2с)."""
    tmp = path + ".tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", path,
        "-af", "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-45dB"
               ":stop_periods=-1:stop_silence=0.35:stop_threshold=-45dB,"
               "apad=pad_dur=0.5",
        "-c:a", "libmp3lame", "-q:a", "4",
        tmp
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)

def generate_block_tts(text, out_path, retries=3, delay=5, trim_silence=False, collect_boundaries=False):
    import time
    clean = preprocess_tts(text)
    if not clean.strip():
        return (0, []) if collect_boundaries else 0
    for attempt in range(1, retries + 1):
        try:
            boundaries = asyncio.run(_tts_async(clean, out_path, collect_boundaries))
            if trim_silence:
                strip_silence(out_path)
            size_kb = os.path.getsize(out_path) // 1024
            print(f"    \u2192 {os.path.basename(out_path)} ({size_kb} кб)")
            return (size_kb, boundaries) if collect_boundaries else size_kb
        except Exception as e:
            print(f"    [TTS] Ошибка (попытка {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
    print(f"    [TTS] Не удалось сгенерировать {os.path.basename(out_path)} — пропускаю")
    return (0, []) if collect_boundaries else 0

def get_mp3_duration(path):
    try:
        size = os.path.getsize(path)
        return round(size / 16000, 1)
    except:
        return 0

SENT_RE = re.compile(r'[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$')

def split_sentences(text):
    return [s.strip() for s in SENT_RE.findall(text) if s.strip()]

def build_text_segments(section_text, date_prefix, boundaries):
    sentences = split_sentences(section_text)
    if not sentences or not boundaries:
        return []
    segments = []
    bi = 0
    n = len(boundaries)
    for si, sent in enumerate(sentences):
        if bi >= n:
            break
        prefix = date_prefix if si == 0 else ''
        wcount = max(1, len(preprocess_tts(prefix + sent).split()))
        start_i = bi
        end_i = min(bi + wcount, n) - 1
        start = boundaries[start_i]["offset"]
        end = boundaries[end_i]["offset"] + boundaries[end_i]["duration"]
        segments.append({"text": sent, "start": round(start, 2), "end": round(end, 2)})
        bi += wcount
    return segments


def main(force=False):
    if not os.path.exists(INPUT_FILE):
        print(f"  [BLOCKS-Gemini] Файл не найден: {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    text = data.get('text', '')
    if not text:
        print("  [BLOCKS-Gemini] Нет текста в JSON")
        return

    os.makedirs(BLOCKS_DIR, exist_ok=True)
    sections = parse_sections(text)
    print(f"\n  [BLOCKS-Gemini] Найдено секций: {list(sections.keys())}")

    existing_meta = {}
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, 'r', encoding='utf-8') as f:
                existing_meta = json.load(f)
        except:
            pass

    src_hash = data.get('data_hash', '')
    if not force and existing_meta.get('data_hash') == src_hash and src_hash:
        print("  [BLOCKS-Gemini] Данные не изменились — пропускаю генерацию блоков")
        return

    global _selected_voice
    _selected_voice = random.choice(VOICES)
    print(f"  [BLOCKS-Gemini] Голос: {_selected_voice}")
    print("  [BLOCKS-Gemini] Генерирую блоки озвучки...")

    gen_at = data.get('generated_at', '')
    try:
        base_dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00')).astimezone()
    except Exception:
        base_dt = datetime.now(timezone.utc).astimezone()

    now_local = datetime.now(timezone.utc).astimezone()
    now_utc_h = datetime.now(timezone.utc).hour

    # Режим берём напрямую из JSON (сохранён generate_ai_analysis.py в момент генерации текста) —
    # это исключает рассинхронизацию с реальным заголовком блока1 в тексте.
    # Фоллбэк на пересчёт по UTC-часу — только для старых файлов без поля "mode".
    gen_mode = data.get("mode")
    if not gen_mode:
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
        'warnings': "Внимание! Предупреждение о значительных изменениях погоды. ",
    }

    b1 = MODE_BLOCK1[gen_mode]
    b2 = MODE_BLOCK2[gen_mode]
    BLOCK_DEFS = [b1, b2] + BLOCK_DEFS_COMMON

    # Читаем t_min/t_max из forecast_days.json
    _days_file = os.path.join(os.path.dirname(BLOCKS_DIR), "forecast_days.json")
    _days_by_idx = {}
    if os.path.exists(_days_file):
        try:
            import json as _json2
            _days = _json2.load(open(_days_file, encoding='utf-8'))
            for _i, _d in enumerate(_days):
                _days_by_idx[_i] = (_d.get('T',{}).get('min'), _d.get('T',{}).get('max'))
        except Exception: pass

    # Соответствие key -> индекс дня
    _key_to_day = {'today':0,'tonight':0,'tomorrow':1,'next3':2,'marine':None,'trend':None,'warnings':None,'verification':None}

    blocks_meta = []
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:
        if key == 'today' and today_stale:
            print(f"    → {filename}: пропущен (устарел, уже вечер)")
            continue
        ALT = {
            'today':   ('Сегодня', 'Утром и', 'Утром', 'Днём'),
            'tonight': ('Этой ночью', 'Ночью', 'Сегодня ночью'),
        }
        if key in ALT:
            section_text = find_section(sections, *ALT[key])
        else:
            section_text = find_section(sections, section_title)

        if not section_text.strip():
            print(f"    \u2192 {filename}: пропущен (пусто)")
            continue

        tts_text = DATE_PREFIX.get(key, '') + section_text
        out_path = os.path.join(BLOCKS_DIR, filename)
        size_kb, _boundaries = generate_block_tts(tts_text, out_path, trim_silence=True, collect_boundaries=True)
        text_segments = build_text_segments(section_text, DATE_PREFIX.get(key, ''), _boundaries)

        if size_kb > 0:
            # Постраничные mp3
            pages = split_into_pages(section_text)
            page_files = []
            for pi, page_text in enumerate(pages):
                page_tts = DATE_PREFIX.get(key, '') + page_text if pi == 0 else page_text
                page_fn = filename.replace('.mp3', f'_p{pi+1}.mp3')
                page_path = os.path.join(BLOCKS_DIR, page_fn)
                psize = generate_block_tts(page_tts, page_path, trim_silence=False)
                if psize > 0:
                    page_files.append({
                        "filename": page_fn,
                        "path": f"data/blocks_gemini/{page_fn}",
                        "duration": get_mp3_duration(page_path),
                        "text": page_text,
                    })
            _day_idx = _key_to_day.get(key)
            _t_min, _t_max = _days_by_idx.get(_day_idx, (None, None)) if _day_idx is not None else (None, None)
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks_gemini/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
                "pages":    page_files,
                "text_segments": text_segments,
                "t_min":    _t_min,
                "t_max":    _t_max,
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
    print(f"  [BLOCKS-Gemini] \u2705 {len(blocks_meta)} блоков, ~{total_dur:.0f} сек суммарно")
    print(f"  [BLOCKS-Gemini] Мета: {META_FILE}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    main(force=a.force)

