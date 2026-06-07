FILE = 'scripts/make_blocks.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''BLOCK_DEFS_DAY = [
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

NEW = '''# Ключи поиска секций по режиму (mode → prefix для find_section)
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
    ("warnings", "\\u26a0",      "block_3_warnings.mp3", "Предупреждения", "⚠️"),
    ("marine",   "\\U0001f30a", "block_4_marine.mp3",   "Море",           "🌊"),
    ("trend",    "Тенденция",   "block_5_trend.mp3",    "Тенденция",      "📈"),
]'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    gen_at = data.get('generated_at', '')
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
            print(f"    → {filename}: пропущен (устарел, уже вечер)")
            continue
        section_text = find_section(sections, section_title)'''

NEW2 = '''    gen_at = data.get('generated_at', '')
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
        section_text = find_section(sections, section_title)'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
