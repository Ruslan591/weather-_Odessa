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


DIRS_RU = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ","Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"]

WW_TEXT = {
    0:"ясно", 1:"облачность менялась", 2:"облачно (без осадков)", 3:"пыльная буря/метель",
    4:"туман", 5:"морось", 6:"морось (замерзающая)", 7:"снежная метель",
    8:"ливень (прошёл)", 9:"гроза (прошла)",
    10:"туман", 11:"туман (пятнами)", 12:"туман (стал гуще)", 13:"гроза без осадков",
    14:"гроза с осадками", 15:"ледяной дождь", 16:"гроза с градом",
    17:"гроза с осадками", 18:"шквал", 19:"смерч",
    20:"морось (прошла)", 21:"дождь (прошёл)", 22:"снег (прошёл)", 23:"ледяной дождь (прошёл)",
    24:"ледяная морось (прошла)", 25:"ливень (прошёл)", 26:"снежный ливень (прошёл)",
    27:"град (прошёл)", 28:"туман (прошёл)", 29:"гроза (прошла)",
    30:"слабая пыльная буря (ослабевает)", 31:"слабая пыльная буря", 32:"слабая пыльная буря (усиливается)",
    33:"умеренная пыльная буря (ослабевает)", 34:"умеренная пыльная буря", 35:"умеренная пыльная буря (усиливается)",
    36:"слабая метель (низовая)", 37:"сильная метель (низовая)", 38:"слабая метель", 39:"сильная метель",
    40:"туман на расстоянии", 41:"туман (пятнами)", 42:"туман (стал тоньше, небо видно)",
    43:"туман (стал тоньше, небо не видно)", 44:"туман (без изменений, небо видно)",
    45:"туман", 46:"туман (стал гуще, небо видно)", 47:"туман (стал гуще, небо не видно)",
    48:"туман с изморозью (небо видно)", 49:"туман с изморозью (небо не видно)",
    50:"слабая прерывистая морось", 51:"слабая непрерывная морось",
    52:"умеренная прерывистая морось", 53:"умеренная непрерывная морось",
    54:"сильная прерывистая морось", 55:"сильная непрерывная морось",
    56:"слабая замерзающая морось", 57:"умеренная/сильная замерзающая морось",
    58:"слабая морось с дождём", 59:"умеренная/сильная морось с дождём",
    60:"слабый прерывистый дождь", 61:"слабый непрерывный дождь",
    62:"умеренный прерывистый дождь", 63:"умеренный непрерывный дождь",
    64:"сильный прерывистый дождь", 65:"сильный непрерывный дождь",
    66:"слабый замерзающий дождь", 67:"умеренный/сильный замерзающий дождь",
    68:"слабый дождь со снегом", 69:"умеренный/сильный дождь со снегом",
    70:"слабый прерывистый снег", 71:"слабый непрерывный снег",
    72:"умеренный прерывистый снег", 73:"умеренный непрерывный снег",
    74:"сильный прерывистый снег", 75:"сильный непрерывный снег",
    76:"ледяные иглы", 77:"снежная крупа", 78:"снежные кристаллы", 79:"ледяной дождь",
    80:"слабый ливневый дождь", 81:"умеренный ливневый дождь", 82:"сильный ливневый дождь",
    83:"слабый ливневый дождь со снегом", 84:"умеренный/сильный ливневый дождь со снегом",
    85:"слабый ливневый снег", 86:"умеренный/сильный ливневый снег",
    87:"слабая снежная крупа", 88:"умеренная/сильная снежная крупа",
    89:"слабый град (без грозы)", 90:"умеренный/сильный град (без грозы)",
    91:"слабый дождь, гроза в прошлом", 92:"умеренный/сильный дождь, гроза в прошлом",
    93:"слабый снег/крупа, гроза в прошлом", 94:"умеренный снег/крупа, гроза в прошлом",
    95:"гроза со слабым дождём или снегом", 96:"гроза с градом",
    97:"сильная гроза со слабым дождём или снегом", 98:"гроза с пыльной бурей",
    99:"сильная гроза с градом",
}

W_PAST_TEXT = {
    "0":"ясно", "1":"облачность менялась", "2":"облачно",
    "3":"пыль/туман", "4":"туман", "5":"морось",
    "6":"дождь", "7":"снег", "8":"ливень", "9":"гроза",
}

CLOUD_N_TEXT = {
    0:"ясно (0/8)", 1:"1/8", 2:"2/8", 3:"3/8", 4:"4/8",
    5:"5/8", 6:"6/8", 7:"7/8", 8:"пасмурно (8/8)", 9:"небо закрыто",
}


def _signed_tenths(group):
    if not group or len(group) != 5: return None
    sign = -1 if group[1] == "1" else 1
    try: val = int(group[2:])
    except ValueError: return None
    return sign * val / 10


def _pressure_from_group(group):
    if not group: return None
    try: p = int(group[1:]) / 10
    except ValueError: return None
    return p + 1000 if p < 500 else p


def _deg_to_text(dd):
    if dd is None: return None
    if dd == 0: return "штиль"
    idx = round(((dd % 360) + 360) % 360 / 22.5) % 16
    return DIRS_RU[idx]


def decode_synop(raw_line):
    """
    Декодирует одну строку synop_YYYY.txt и возвращает читаемую строку.
    Формат входа: СТАНЦИЯ,YYYY,MM,DD,HH,MM,AAXX ...
    """
    try:
        parts = raw_line.strip().split(",", 6)
        if len(parts) < 7: return raw_line.strip()
        hh = parts[4].zfill(2)
        telegram = parts[6]

        tok = telegram.strip().split()
        aaxx_idx = next((i for i,t in enumerate(tok) if t == "AAXX"), -1)
        if aaxx_idx == -1: return f"{hh}:00 UTC: (не удалось разобрать)"

        wind_group = tok[aaxx_idx + 4] if aaxx_idx + 4 < len(tok) else None

        body, sec333 = [], []
        section = "main"
        for t in tok[aaxx_idx + 5:]:
            g = t.rstrip("=")
            if g == "333": section = "333"; continue
            if g in ("444","555"): section = g; continue
            if not g: continue
            if section == "main": body.append(g)
            elif section == "333": sec333.append(g)

        # Nddff
        cloud_n = wind_dir = wind_spd = None
        if wind_group and len(wind_group) == 5 and wind_group.isdigit():
            cloud_n = int(wind_group[0])
            dd = int(wind_group[1:3])
            wind_dir = None if dd == 0 else dd * 10
            wind_spd = int(wind_group[3:5])

        temp = dew = sta_pres = sea_pres = None
        ww = w1 = w2 = None
        import re as _re
        for g in body:
            if _re.match(r"^1[01/]\d{3}$", g): temp = _signed_tenths(g)
            elif _re.match(r"^2[01/]\d{3}$", g): dew = _signed_tenths(g)
            elif _re.match(r"^3\d{4}$", g): sta_pres = _pressure_from_group(g)
            elif _re.match(r"^4\d{4}$", g): sea_pres = _pressure_from_group(g)
            elif _re.match(r"^7\d{4}$", g):
                try:
                    ww = int(g[1:3]); w1 = g[3]; w2 = g[4]
                except Exception: pass

        temp_max = temp_min = None
        for g in sec333:
            c = g.rstrip("=")
            if _re.match(r"^1[01]\d{3}$", c): temp_max = _signed_tenths(c)
            elif _re.match(r"^2[01]\d{3}$", c): temp_min = _signed_tenths(c)

        # Собираем строку
        res = [f"{hh}:00 UTC:"]
        if temp is not None: res.append(f"T={temp:+.1f}°C")
        if dew is not None:
            rh = None
            try:
                import math
                es = 6.112 * math.exp(17.62 * temp / (243.12 + temp))
                e  = 6.112 * math.exp(17.62 * dew  / (243.12 + dew))
                rh = round(e / es * 100)
            except Exception: pass
            res.append(f"Td={dew:+.1f}°C" + (f" (RH~{rh}%)" if rh else ""))
        if cloud_n is not None: res.append(f"облачность: {CLOUD_N_TEXT.get(cloud_n, str(cloud_n)+'/8')}")
        if wind_spd is not None:
            dir_txt = _deg_to_text(wind_dir) or "штиль"
            res.append(f"ветер: {dir_txt} {wind_spd} м/с")
        if sea_pres is not None: res.append(f"Pмор={sea_pres:.1f} гПа")
        if ww is not None:
            ww_desc = WW_TEXT.get(ww, f"ww={ww}")
            w1_desc = W_PAST_TEXT.get(str(w1), str(w1)) if w1 else None
            w2_desc = W_PAST_TEXT.get(str(w2), str(w2)) if w2 else None
            res.append(f"погода: {ww_desc}" +
                       (f" / прошлое: {w1_desc},{w2_desc}" if w1_desc else ""))
        if temp_max is not None: res.append(f"Tмакс={temp_max:+.1f}°C")
        if temp_min is not None: res.append(f"Tмин={temp_min:+.1f}°C")
        return "  ".join(res)
    except Exception as ex:
        return f"{raw_line.strip()}  (ошибка декодирования: {ex})"


def format_verification_prompt_block(prev_date, prev_period, prev_summary, synop_lines):
    """Текст для вставки в промпт: что говорили + сырые SYNOP-строки факта."""
    label = PERIOD_LABELS_RU.get(prev_period, prev_period)
    lines = [
        f"СВЕРКА ПРОГНОЗА С ФАКТОМ за прошедший период ({label}, {prev_date}):",
        f"  Прогнозировалось (наш текст из прошлого анализа): \"{prev_summary}\"",
        "  Фактические данные SYNOP (станция 33837, расшифровано):",
    ]
    if synop_lines:
        for raw_line in synop_lines:
            lines.append(f"    {decode_synop(raw_line)}")
    else:
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
