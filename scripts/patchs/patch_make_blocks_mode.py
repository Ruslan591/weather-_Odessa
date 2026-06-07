FILE = 'scripts/make_blocks.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = 'BLOCK_DEFS = [\n    ("today",    "Сегодня",     "block_0_today.mp3",    "Сегодня",        "☀️"),\n    ("tomorrow", "Завтра",      "block_1_tomorrow.mp3", "Завтра",         "🌤"),\n    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),\n    ("warnings", "\\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),\n    ("trend",    "Тенденция",   "block_4_trend.mp3",    "Тенденция",      "📈"),\n]'

NEW = '''BLOCK_DEFS_DAY = [
    ("today",    "Сегодня",     "block_0_today.mp3",    "Сегодня",        "☀️"),
    ("tomorrow", "Завтра",      "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),
    ("warnings", "\\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("trend",    "Тенденция",   "block_4_trend.mp3",    "Тенденция",      "📈"),
]
BLOCK_DEFS_EVE = [
    ("tonight",  "Этой ночью",  "block_0_tonight.mp3",  "Этой ночью",     "🌙"),
    ("tomorrow", "Завтра днём", "block_1_tomorrow.mp3", "Завтра",         "🌤"),
    ("next3",    "Последующие", "block_2_next3.mp3",    "Ближайшие дни",  "📅"),
    ("warnings", "\\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("trend",    "Тенденция",   "block_4_trend.mp3",    "Тенденция",      "📈"),
]'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    gen_at = data.get('generated_at', '')
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
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:'''

NEW2 = '''    gen_at = data.get('generated_at', '')
    try:
        base_dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00')).astimezone()
    except Exception:
        base_dt = datetime.now(timezone.utc).astimezone()

    now_local = datetime.now(timezone.utc).astimezone()
    evening_mode = base_dt.hour >= 20
    today_stale = (not evening_mode) and (now_local.hour >= 20)
    BLOCK_DEFS = BLOCK_DEFS_EVE if evening_mode else BLOCK_DEFS_DAY

    def date_label(dt):
        return f"{dt.day} {MONTH_RU[dt.month - 1]}"

    DATE_PREFIX = {
        'today':    f"Сегодня, {date_label(base_dt)}. ",
        'tonight':  "Сегодня ночью. ",
        'tomorrow': f"Завтра, {date_label(base_dt + timedelta(days=1))}. ",
    }

    blocks_meta = []
    for key, section_title, filename, display_title, icon in BLOCK_DEFS:
        if key == 'today' and today_stale:
            print(f"    \u2192 {filename}: пропущен (устарел, уже вечер)")
            continue'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
