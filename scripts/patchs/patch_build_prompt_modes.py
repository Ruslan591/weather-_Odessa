FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''GOOD_HOURS_UTC = [9, 12, 15, 21]'''
NEW = '''GOOD_HOURS_UTC = [3, 9, 12, 15, 21]'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''def build_prompt(days, marine=None):
    now_local = datetime.now(timezone.utc).astimezone()
    now_str = now_local.strftime("%d.%m.%Y %H:%M местного")
    evening_mode = now_local.hour >= 20

    # Даты блоков
    dates = [datetime.strptime(d["date"], "%Y-%m-%d") for d in days]

    if evening_mode:
        # Вечерний режим: блок 0 = эта ночь, блок 1 = завтра днём
        d0 = dates[0] if dates else now_local
        d1 = dates[1] if len(dates) > 1 else d0
        d2 = dates[2] if len(dates) > 2 else d1
        d_last = dates[-1] if dates else d0
        # Последующие: +2..+4 от сегодня = индексы 2,3,4
        next_start = dates[2] if len(dates) > 2 else d1
        next_end   = dates[4] if len(dates) > 4 else dates[-1]
        tend_start = dates[5] if len(dates) > 5 else dates[-1]
        tend_end   = dates[-1]
        block1 = f"## Этой ночью"
        block2 = f"## Завтра днём, {fmt_date(d1)}"
        block3 = f"## Последующие дни, {fmt_date(next_start)}–{fmt_date(next_end)}"
        block5 = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"
        struct = [
            f"1. {block1} — ночные условия до рассвета (2-3 предложения)",
            f"2. {block2} — подробный дневной анализ (3-5 предложений)",
            f"3. {block3} — общий обзор (3-4 предложения)",
            f"4. ## \u26a0\ufe0f Предупреждения — только если есть реальные риски. Если рисков нет — пропусти.",
            f"5. {block5} — краткий прогноз изменений (1-2 предложения)",
        ]
        mode_hint = "Сейчас вечер. Первый блок — только ночь (до рассвета), без дневных показателей."
    else:
        d0 = dates[0] if dates else now_local
        d1 = dates[1] if len(dates) > 1 else d0
        next_start = dates[2] if len(dates) > 2 else d1
        next_end   = dates[4] if len(dates) > 4 else dates[-1]
        tend_start = dates[5] if len(dates) > 5 else dates[-1]
        tend_end   = dates[-1]
        block1 = f"## Сегодня, {fmt_date(d0)}"
        block2 = f"## Завтра, {fmt_date(d1)}"
        block3 = f"## Последующие дни, {fmt_date(next_start)}–{fmt_date(next_end)}"
        block5 = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"
        struct = [
            f"1. {block1} — подробный анализ (3-5 предложений)",
            f"2. {block2} — подробный анализ (3-5 предложений)",
            f"3. {block3} — общий обзор (3-4 предложения)",
            f"4. ## \u26a0\ufe0f Предупреждения — только если есть реальные риски. Если рисков нет — пропусти.",
            f"5. {block5} — краткий прогноз изменений (1-2 предложения)",
        ]
        mode_hint = ""'''

NEW2 = '''def _get_mode(now_utc_hour):
    """Определяем режим по часу UTC."""
    if now_utc_hour == 3:   return "morning"
    if now_utc_hour == 9:   return "midday"
    if now_utc_hour == 12:  return "afternoon"
    if now_utc_hour == 15:  return "evening"
    if now_utc_hour == 21:  return "night"
    # Вне окон — по часу
    if 0 <= now_utc_hour < 6:   return "night"
    if 6 <= now_utc_hour < 10:  return "morning"
    if 10 <= now_utc_hour < 13: return "midday"
    if 13 <= now_utc_hour < 16: return "afternoon"
    if 16 <= now_utc_hour < 18: return "evening"
    return "evening"  # 18-23 UTC

def build_prompt(days, marine=None):
    now_local = datetime.now(timezone.utc).astimezone()
    now_utc   = datetime.now(timezone.utc)
    now_str   = now_local.strftime("%d.%m.%Y %H:%M местного")
    mode      = _get_mode(now_utc.hour)

    dates = [datetime.strptime(d["date"], "%Y-%m-%d") for d in days]
    d0 = dates[0] if dates else now_local
    d1 = dates[1] if len(dates) > 1 else d0
    next_start = dates[2] if len(dates) > 2 else d1
    next_end   = dates[4] if len(dates) > 4 else dates[-1]
    tend_start = dates[5] if len(dates) > 5 else dates[-1]
    tend_end   = dates[-1]
    tend_block = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"
    next_block = f"## Последующие дни, {fmt_date(next_start)}–{fmt_date(next_end)}"

    if mode == "night":
        block1 = f"## Сегодня, {fmt_date(d0)}"
        block2 = f"## Завтра, {fmt_date(d1)}"
        mode_hint = "Только что сменились сутки. Первый блок — полные сутки сегодня от ночи до вечера."
        b1_desc = "полные сутки: ночь, утро, день, вечер (3-5 предложений)"
        b2_desc = "подробный анализ (3-5 предложений)"
    elif mode == "morning":
        block1 = f"## Утром и днём, {fmt_date(d0)}"
        block2 = f"## Завтра, {fmt_date(d1)}"
        mode_hint = ("Сейчас раннее утро. Первый блок — утро и день. "
                     "Начни одним вводным предложением про ночь в сослагательном наклонении "
                     "(«По прогнозу ночью...»), затем акцент на утро и день.")
        b1_desc = "вводное предложение про ночь + утро и день (3-4 предложения)"
        b2_desc = "подробный анализ (3-5 предложений)"
    elif mode == "midday":
        block1 = f"## Днём и вечером, {fmt_date(d0)}"
        block2 = f"## Завтра, {fmt_date(d1)}"
        mode_hint = ("Сейчас полдень. Первый блок — вторая половина дня и вечер. "
                     "Если утром было что-то значимое — одно вводное предложение, "
                     "затем акцент на день и вечер.")
        b1_desc = "день и вечер, при необходимости вводное про утро (3-4 предложения)"
        b2_desc = "подробный анализ (3-5 предложений)"
    elif mode == "afternoon":
        block1 = f"## Сегодня вечером, {fmt_date(d0)}"
        block2 = f"## Завтра, {fmt_date(d1)}"
        mode_hint = "Сейчас вторая половина дня. Первый блок — только вечерние условия."
        b1_desc = "только вечер сегодня (2-3 предложения)"
        b2_desc = "подробный анализ (3-5 предложений)"
    else:  # evening
        block1 = f"## Этой ночью"
        block2 = f"## Завтра днём, {fmt_date(d1)}"
        mode_hint = "Сейчас вечер. Первый блок — только ночные условия до рассвета."
        b1_desc = "только ночь до рассвета (2-3 предложения)"
        b2_desc = "подробный дневной анализ (3-5 предложений)"

    struct = [
        f"1. {block1} — {b1_desc}",
        f"2. {block2} — {b2_desc}",
        f"3. {next_block} — общий обзор (3-4 предложения)",
        f"4. ## \u26a0\ufe0f Предупреждения — только если есть реальные риски. Если рисков нет — пропусти.",
        f"5. ## \U0001f30a Море — температура воды, волнение, условия (1-2 предложения)",
        f"6. {tend_block} — краткий прогноз изменений (1-2 предложения)",
    ]'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
