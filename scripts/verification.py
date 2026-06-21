"""
Верификация: текстовая сверка прогноза с фактом по 4 периодам суток.
Периоды (Europe/Kiev, не зависит от системного TZ устройства): night 00-06,
morning 06-12, day 12-18, evening 18-24.

Подход: модель сама пишет краткий блок <PERIOD_SUMMARY>...</PERIOD_SUMMARY> про
ближайшие 6 часов в конце ответа (служебный, вырезается перед сохранением и
показом пользователю). Этот текст сохраняется как "что мы говорили" про текущий
период. При следующей генерации, когда период сменился, этот сохранённый текст
плюс сырые SYNOP-телеграммы за тот период (факт) передаются модели заново —
она сама сравнивает прогноз с фактом и пишет оценку точности.
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

STATION = "33837"
SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

PERIODS = [
    ("night",   0, 6),
    ("morning", 6, 12),
    ("day",     12, 18),
    ("evening", 18, 24),
]
PERIOD_LABELS_RU = {
    "night": "ночь (00-06)", "morning": "утро (06-12)",
    "day": "день (12-18)", "evening": "вечер (18-24)",
}

PERIOD_SUMMARY_TAG_RE = re.compile(r"<PERIOD_SUMMARY>(.*?)</PERIOD_SUMMARY>", re.DOTALL)


def _kiev_dst_offset(utc_dt):
    """EU DST: переход в последнее воскресенье марта (01:00 UTC, +2->+3) и
    последнее воскресенье октября (01:00 UTC, +3->+2). Используется только как
    fallback, если на устройстве нет базы tzdata для zoneinfo."""
    year = utc_dt.year

    def last_sunday(y, month):
        d = datetime(y, month, 31, tzinfo=timezone.utc)
        while d.month != month:
            d -= timedelta(days=1)
        while d.weekday() != 6:  # 6 = воскресенье
            d -= timedelta(days=1)
        return d.replace(hour=1, minute=0, second=0, microsecond=0)

    dst_start = last_sunday(year, 3)
    dst_end = last_sunday(year, 10)
    if dst_start <= utc_dt < dst_end:
        return 3  # EEST (летнее)
    return 2  # EET (зимнее)


def _to_kiev(utc_dt):
    """Конвертирует UTC datetime в Europe/Kiev. НЕ зависит от системного TZ
    устройства (он может быть выставлен неверно/измениться) — использует
    zoneinfo, а если базы tzdata нет на устройстве — расчёт DST вручную."""
    try:
        from zoneinfo import ZoneInfo
        return utc_dt.astimezone(ZoneInfo("Europe/Kiev"))
    except Exception:
        return utc_dt.astimezone(timezone(timedelta(hours=_kiev_dst_offset(utc_dt))))


def local_now():
    return _to_kiev(datetime.now(timezone.utc))


def current_and_previous_period(now_local=None):
    """Возвращает (date_str_current, period_current, date_str_prev, period_prev) по Europe/Kiev."""
    if now_local is None:
        now_local = local_now()
    h = now_local.hour
    idx = h // 6  # 0..3
    cur_period = PERIODS[idx][0]
    cur_date = now_local.strftime("%Y-%m-%d")
    if idx == 0:
        prev_idx = 3
        prev_dt = now_local - timedelta(days=1)
    else:
        prev_idx = idx - 1
        prev_dt = now_local
    prev_period = PERIODS[prev_idx][0]
    prev_date = prev_dt.strftime("%Y-%m-%d")
    return cur_date, cur_period, prev_date, prev_period


# ── Извлечение служебного тега из ответа модели ────────────────────────────

def extract_period_summary(text):
    """
    Ищет <PERIOD_SUMMARY>...</PERIOD_SUMMARY> в тексте ответа модели.
    Возвращает (clean_text, summary_or_None) — clean_text это текст БЕЗ тега
    и БЕЗ лишних пустых строк на его месте, summary — содержимое тега (или None).
    """
    m = PERIOD_SUMMARY_TAG_RE.search(text)
    if not m:
        return text, None
    summary = m.group(1).strip()
    clean_text = (text[:m.start()] + text[m.end():]).rstrip()
    return clean_text, summary


# ── SYNOP сырые строки за период (без расшифровки — модель читает сама) ────

def _synop_line_local_dt(raw_line):
    """Возвращает datetime (Europe/Kiev) для строки synop_YYYY.txt, или None."""
    parts = raw_line.strip().split(",", 6)
    if len(parts) < 7:
        return None
    st, y, mo, dd, hh, mm = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    if st != STATION:
        return None
    try:
        hour = int(hh)
    except ValueError:
        return None
    if hour not in SYNOP_HOURS:
        return None
    dt_utc = datetime(int(y), int(mo), int(dd), hour, tzinfo=timezone.utc)
    return _to_kiev(dt_utc)


def get_synop_lines_for_period(synop_text, date_str, period_name):
    """Возвращает список сырых SYNOP-строк (как в файле), попадающих в период."""
    period_def = dict((p[0], (p[1], p[2])) for p in PERIODS)
    h_start, h_end = period_def[period_name]

    out = []
    for line in synop_text.splitlines():
        if not line.strip():
            continue
        local_dt = _synop_line_local_dt(line)
        if local_dt is None:
            continue
        if local_dt.strftime("%Y-%m-%d") != date_str:
            continue
        if h_start <= local_dt.hour < h_end:
            out.append(line.strip())
    return out


# ── Хранение и формирование текста для промпта ─────────────────────────────

def load_verification_store(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_verification_store(path, store):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def format_verification_prompt_block(prev_date, prev_period, prev_summary, synop_lines):
    """Текст для вставки в промпт: что говорили + сырые SYNOP-строки факта."""
    label = PERIOD_LABELS_RU.get(prev_period, prev_period)
    lines = [
        f"СВЕРКА ПРОГНОЗА С ФАКТОМ за прошедший период ({label}, {prev_date}):",
        f"  Прогнозировалось (наш текст из прошлого анализа): \"{prev_summary}\"",
        "  Факт — сырые метеосводки SYNOP (формат AAXX, станция 33837), расшифруй их сам:",
    ]
    for raw_line in synop_lines:
        lines.append(f"    {raw_line}")
    if not synop_lines:
        lines.append("    (фактических данных SYNOP за этот период пока нет)")
    return "\n".join(lines)


def get_verification_prompt_block(store_path, synop_text):
    """
    Точка входа для формирования блока сверки для ТЕКУЩЕЙ генерации.
    Смотрит, есть ли в store сохранённый prev_summary за предыдущий период —
    если есть, формирует текст для промпта. Не изменяет store (запись текущего
    периода делается отдельно, после получения ответа модели, см. save_current_period_summary).
    """
    store = load_verification_store(store_path)
    cur_date, cur_period, prev_date, prev_period = current_and_previous_period()
    prev_key = f"{prev_date}_{prev_period}"
    prev_entry = store.get(prev_key)
    if not prev_entry or not prev_entry.get("summary"):
        return None
    synop_lines = get_synop_lines_for_period(synop_text, prev_date, prev_period)
    return format_verification_prompt_block(prev_date, prev_period, prev_entry["summary"], synop_lines)


def save_current_period_summary(store_path, summary):
    """Сохраняет (перезаписывает) текст <PERIOD_SUMMARY> под ТЕКУЩИЙ период."""
    if not summary:
        return
    store = load_verification_store(store_path)
    cur_date, cur_period, _, _ = current_and_previous_period()
    cur_key = f"{cur_date}_{cur_period}"
    store[cur_key] = {"summary": summary}
    save_verification_store(store_path, store)
