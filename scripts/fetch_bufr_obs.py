#!/usr/bin/env python3
"""
fetch_bufr_obs.py — парсит BUFR-наблюдения с Meteomanz для ст. 33837
и дописывает записи в data/bufr_YYYY.json.

Запуск:
    python3 scripts/fetch_bufr_obs.py [--hours N] [--dry-run]
"""
import re, json, os, time, datetime, logging
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATION  = "33837"
SYNOP_HOURS = [3, 9, 15, 21]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
    "Referer":    "https://www.meteomanz.com/",
}

# [ИЗМЕНЕНО 2026-09-18] НАХОДКА: 403/страница "Access limitation" от
# meteomanz.com — это НЕ блокировка по IP (подтверждено: с другой сети тот
# же URL открывается нормально), а мягкий rate-limit самого сайта на общий
# объём запросов ("probably due to issues related to massive data
# downloads", их собственный текст). Прокси-каскад, добавленный раньше как
# фикс "от IP", на самом деле УТРАИВАЛ трафик на каждую неудачную попытку —
# убран. Настоящая причина объёма: fetch_latest_meteomanz_essentials() и
# fetch_latest_bufr_essentials() перебирают 4 часа назад КАЖДЫЙ вызов, и
# вызываются НЕЗАВИСИМО из vps_pipeline.py и vps_satellite_pipeline.py
# каждые ~5 минут без общего кэша между ними — сотни запросов в сутки на
# одну и ту же станцию. Настоящий фикс — общий кулдаун ниже
# (COOLDOWN_FILE), проверяемый во всех точках вызова перед сетевым
# запросом.
COOLDOWN_FILE = os.path.join(BASE_DIR, "data", "bufr_fetch_cooldown.json")
COOLDOWN_MIN = 20  # минут между повторными попытками одного и того же (station, hour)


def _cooldown_key(station, dt):
    return f"{station}:{dt:%Y-%m-%dT%H}"


def _load_cooldown():
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cooldown(data):
    tmp = COOLDOWN_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, COOLDOWN_FILE)
    except Exception as e:
        log.debug("  cooldown save error: %s", e)


def in_cooldown(station, dt):
    """True, если (station, час) уже пытались недавно и неудачно —
    пропускаем сетевой запрос."""
    data = _load_cooldown()
    ts = data.get(_cooldown_key(station, dt))
    if not ts:
        return False
    try:
        last = datetime.datetime.fromisoformat(ts)
    except Exception:
        return False
    return (datetime.datetime.utcnow() - last).total_seconds() < COOLDOWN_MIN * 60


def mark_attempt(station, dt):
    """Отмечает неудачную попытку и заодно подчищает записи старше 3
    часов, чтобы файл не рос бесконечно."""
    data = _load_cooldown()
    data[_cooldown_key(station, dt)] = datetime.datetime.utcnow().isoformat()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=3)
    for k in list(data.keys()):
        try:
            if datetime.datetime.fromisoformat(data[k]) < cutoff:
                del data[k]
        except Exception:
            del data[k]
    _save_cooldown(data)


# ── HTML-парсинг ──────────────────────────────────────────────────────────────

def fetch_html(dt: datetime.datetime, station: str = None) -> str:
    station = station or STATION
    url = (
        f"https://www.meteomanz.com/sy1?ty=hd&ind={station}&l=1"
        f"&d1={dt.day:02d}&m1={dt.month:02d}&y1={dt.year}"
        f"&d2={dt.day:02d}&m2={dt.month:02d}&y2={dt.year}"
        f"&h1={dt.hour:02d}Z&h2={dt.hour:02d}Z&min=0&rt=0&ext=1"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    # [ДОБАВЛЕНО 2026-09-18] Rate-limit meteomanz отдаётся как HTTP 200 с
    # текстом "Access limitation", а не как HTTP-ошибка — без этой проверки
    # такой ответ считался бы "успешным пустым часом" и не попадал в
    # кулдаун, что позволяло долбить сайт дальше без пауз.
    if "Access limitation" in html:
        raise RuntimeError("meteomanz: rate-limit (Access limitation page)")
    return html

def _val(html: str, label: str):
    """
    Ищет паттерн двух видов:
      <b><i>Label: </i></b> число<br>
      <b><i>Label: </i></b> текст (число)<br>   <- берём число в скобках
    Возвращает float или None.
    """
    pat = re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>"
    m = re.search(pat, html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw in ("-", "", "—"):
        return None
    # Число в скобках в конце: "Some text (123.4)"
    m2 = re.search(r'\((-?[\d.]+)\)\s*$', raw)
    if m2:
        try: return float(m2.group(1))
        except ValueError: return None
    # Просто число
    m3 = re.match(r'^-?[\d.]+', raw)
    if m3:
        try: return float(m3.group())
        except ValueError: return None
    return None

def _txt(html: str, label: str):
    """Возвращает текстовое значение поля (до скобок или до <br>)."""
    pat = re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>"
    m = re.search(pat, html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw in ("-", "", "—"):
        return None
    # Убираем часть в скобках в конце
    txt = re.sub(r'\s*\(-?[\d.]+\)\s*$', '', raw).strip()
    return txt or None

# [2026-10-06] таблицы подписей вынесены на уровень модуля (были внутри parse_obs) —
# нужны и для SYNOP-fallback (synop_line_to_bufr_record).
TEND_RU = {
    0: "Росло, затем падало; давление такое же или выше, чем 3 ч назад",
    1: "Росло, затем стало постоянным или замедлилось; выше, чем 3 ч назад",
    2: "Непрерывно росло; выше, чем 3 ч назад",
    3: "Падало или было постоянным, затем росло; выше, чем 3 ч назад",
    4: "Постоянное; давление такое же, как 3 ч назад",
    5: "Падало, затем росло; такое же или ниже, чем 3 ч назад",
    6: "Падало, затем стало постоянным или замедлилось; ниже, чем 3 ч назад",
    7: "Непрерывно падало; ниже, чем 3 ч назад",
    8: "Росло или было постоянным, затем стало падать; ниже, чем 3 ч назад",
}
CL_RU = {
    30: "Облаков нет",
    31: "Кучевые плоские (Cu humilis)",
    32: "Кучевые средние или мощные (Cu mediocris / congestus)",
    33: "Кучево-дождевые лысые (Cb calvus)",
    34: "Слоисто-кучевые из кучевых (Sc cumulogenitus)",
    35: "Слоисто-кучевые (Sc)",
    36: "Слоистые разорванные (St nebulosus / fractus)",
    37: "Разорванно-дождевые или разорванно-кучевые плохой погоды",
    38: "Кучевые и слоисто-кучевые вместе",
    39: "Кучево-дождевые с наковальней (Cb capillatus)",
}
CM_RU = {
    20: "Облаков нет",
    21: "Высокослоистые просвечивающие (As translucidus)",
    22: "Высокослоистые плотные или высокослоисто-дождевые (As opacus / Ns)",
    23: "Высококучевые просвечивающие на одном уровне (Ac translucidus)",
    24: "Высококучевые изменяющиеся или хлопьевидные (Ac lenticularis / floccus)",
    25: "Высококучевые полосами, заполняющие небо",
    26: "Высококучевые из кучевых (Ac cumulogenitus)",
    27: "Высококучевые двойные или вместе с высокослоистыми",
    28: "Высококучевые башенковидные (Ac castellanus)",
    29: "Высококучевые хаотические",
}
CH_RU = {
    10: "Облаков нет",
    11: "Перистые нитевидные (Ci fibratus)",
    12: "Перистые плотные хлопьевидные (Ci spissatus)",
    13: "Перистые плотные, из Cb (Ci cumulonimbogenitus)",
    14: "Перистые когтевидные, постепенно закрывающие небо (Ci uncinus)",
    15: "Перистые и перисто-слоистые низко над горизонтом",
    16: "Перистые и перисто-слоистые высоко над горизонтом",
    17: "Перисто-слоистые, закрывающие всё небо (Cs)",
    18: "Перисто-слоистые, не закрывающие всё небо (Cs)",
    19: "Перисто-кучевые одни или преобладающие (Cc)",
}
WW_RU = {
    0: "Облачность уменьшается или не меняется",
    1: "Облака рассеиваются или становятся тоньше",
    2: "Состояние неба без изменений",
    3: "Облачность увеличивается или развивается",
    4: "Видимость ухудшена дымом",
    5: "Сухая мгла",
    6: "Взвешенная пыль в воздухе",
    7: "Пыль или песок, поднятые ветром",
    8: "Пыльные или песчаные вихри",
    9: "Пыльная или песчаная буря вдали",
    10: "Дымка (видимость 1-10 км)",
    11: "Приземный туман клочьями",
    12: "Сплошной приземный туман",
    13: "Зарница",
    14: "Полосы осадков, не достигающие земли",
    15: "Осадки вдали (далее 5 км)",
    16: "Осадки вблизи станции (ближе 5 км)",
    17: "Гроза без осадков",
    18: "Шквал",
    19: "Смерч или водяной столб",
    20: "Морось или замерзающая морось (прошедшая)",
    21: "Дождь (прошедший)",
    22: "Снег (прошедший)",
    23: "Дождь со снегом или ледяной дождь (прошедший)",
    24: "Замерзающий дождь или морось (прошедшие)",
    25: "Ливневый дождь (прошедший)",
    26: "Ливневый снег или дождь со снегом (прошедший)",
    27: "Град или крупа без грозы (прошедшие)",
    28: "Туман или ледяной туман (прошедший)",
    29: "Гроза (прошедшая)",
    30: "Слабая или умеренная пыльная буря, ослабла",
    31: "Слабая или умеренная пыльная буря, без изменений",
    32: "Слабая или умеренная пыльная буря, усилилась",
    33: "Сильная пыльная буря, ослабла",
    34: "Сильная пыльная буря, без изменений",
    35: "Сильная пыльная буря, усилилась",
    36: "Поземок слабый или умеренный",
    37: "Поземок сильный",
    38: "Низовая метель слабая или умеренная",
    39: "Низовая метель сильная",
    40: "Туман в окрестности (на станции нет)",
    41: "Туман клочьями",
    42: "Туман, небо видно, ослаб за последний час",
    43: "Туман, небо скрыто, ослаб за последний час",
    44: "Туман, небо видно, без изменений",
    45: "Туман, небо скрыто, без изменений",
    46: "Туман, небо видно, усилился за последний час",
    47: "Туман, небо скрыто, усилился за последний час",
    48: "Ледяной туман, небо видно",
    49: "Ледяной туман, небо скрыто",
    50: "Морось слабая прерывистая",
    51: "Морось слабая непрерывная",
    52: "Морось умеренная прерывистая",
    53: "Морось умеренная непрерывная",
    54: "Морось сильная прерывистая",
    55: "Морось сильная непрерывная",
    56: "Морось замерзающая слабая",
    57: "Морось замерзающая умеренная или сильная",
    58: "Морось с дождём слабая",
    59: "Морось с дождём умеренная или сильная",
    60: "Дождь слабый прерывистый",
    61: "Дождь слабый непрерывный",
    62: "Дождь умеренный прерывистый",
    63: "Дождь умеренный непрерывный",
    64: "Дождь сильный прерывистый",
    65: "Дождь сильный непрерывный",
    66: "Дождь замерзающий слабый",
    67: "Дождь замерзающий умеренный или сильный",
    68: "Дождь со снегом или морось со снегом, слабые",
    69: "Дождь со снегом или морось со снегом, умеренные или сильные",
    70: "Снег слабый прерывистый",
    71: "Снег слабый непрерывный",
    72: "Снег умеренный прерывистый",
    73: "Снег умеренный непрерывный",
    74: "Снег сильный прерывистый",
    75: "Снег сильный непрерывный",
    76: "Снег сильный непрерывный",
    77: "Снежные зёрна (алмазная пыль)",
    78: "Иглы льда (кристаллы при ясном небе)",
    79: "Ледяной дождь (ледяная крупа)",
    80: "Ливневый дождь слабый",
    81: "Ливневый дождь умеренный или сильный",
    82: "Ливневый дождь очень сильный",
    83: "Ливневый дождь со снегом слабый",
    84: "Ливневый дождь со снегом умеренный или сильный",
    85: "Ливневый снег слабый",
    86: "Ливневый снег умеренный или сильный",
    87: "Ливневая снежная или замерзшая крупа слабая",
    88: "Ливневая снежная или замерзшая крупа умеренная или сильная",
    89: "Ливневый град слабый (без грозы)",
    90: "Ливневый град умеренный или сильный (без грозы)",
    91: "Слабый дождь, гроза была в последний час",
    92: "Сильный дождь, гроза была в последний час",
    93: "Слабый снег или град, гроза была в последний час",
    94: "Сильный снег или град, гроза была в последний час",
    95: "Гроза слабая или умеренная с дождём или снегом",
    96: "Гроза слабая или умеренная с градом",
    97: "Гроза сильная с дождём или снегом",
    98: "Гроза с пыльной или песчаной бурей",
    99: "Гроза сильная с крупным градом",
    500: "Нет существенных явлений", 508: "Нет существенных явлений",
    510: "Явления отсутствуют", 511: "Данные отсутствуют",
}
W_PAST_RU = {
    0: "Ясно", 1: "Облачно",
    2: "Облачно было", 3: "Песок/пыль",
    4: "Туман", 5: "Морось",
    6: "Дождь", 7: "Снег/метель",
    8: "Ливень", 9: "Гроза",
    10: "Значимых явлений не наблюдалось",
}


def parse_obs(html: str, dt: datetime.datetime, station: str = None) -> dict | None:
    station = station or STATION
    if "BUFR report" not in html or "No data for the selected dates" in html:
        return None

    # Облачные типы — их три подряд с одним label
    def cloud_code(label):
        m = re.search(re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>", html)
        if not m: return None
        raw = m.group(1).strip()
        if raw in ("-", ""): return None
        m2 = re.search(r"\((\d+)\)\s*$", raw)
        return int(m2.group(1)) if m2 else None

    # Парсинг через дескрипторы BUFR (_ext_val/_ext_txt)
    def _ext_val(h, desc, occ=0):
        pat = re.escape(f"<b>{desc} <i>") + r"[^<]+</i> </b>\s*(.*?)<br>"
        ms = list(re.finditer(pat, h))
        if occ >= len(ms): return None
        raw = ms[occ].group(1).strip()
        if raw in ("-", "", "\u2014"): return None
        m2 = re.search(r"\((-?[\d.]+)\)\s*$", raw)
        if m2:
            try: return float(m2.group(1))
            except ValueError: return None
        m3 = re.match(r"^-?[\d.]+", raw)
        if m3:
            try: return float(m3.group())
            except ValueError: return None
        return None

    def _ext_txt(h, desc, occ=0):
        pat = re.escape(f"<b>{desc} <i>") + r"[^<]+</i> </b>\s*(.*?)<br>"
        ms = list(re.finditer(pat, h))
        if occ >= len(ms): return None
        raw = ms[occ].group(1).strip()
        if raw in ("-", "", "\u2014"): return None
        txt = re.sub(r"\s*\(-?[\d.]+\)\s*$", "", raw).strip()
        return txt or None

    def _ru(code, table):
        if code is None: return None
        return table.get(int(code))

    wind_spd_ms_m = re.search(
        r'011002 <i>[^<]+</i> </b>\s*([\d.]+)\s*Km/h\s*\((-?[\d.]+)\)', html
    )
    if wind_spd_ms_m:
        wind_spd_kmh = float(wind_spd_ms_m.group(1))
        wind_spd_ms  = float(wind_spd_ms_m.group(2))
    else:
        wind_spd_kmh = None
        wind_spd_ms  = None

    obs = {
        "dt":      dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": station,

        # Давление (Па → гПа, тенденция Па*10 → гПа)
        "station_pressure":       round(_ext_val(html, "010004") / 100, 1) if _ext_val(html, "010004") else None,
        "slp":                    round(_ext_val(html, "010051") / 100, 1) if _ext_val(html, "010051") else None,
        "pressure_tendency_val":  round(_ext_val(html, "010061") / 100, 1) if _ext_val(html, "010061") else None,
        "pressure_tendency_code": _ext_val(html, "010063"),
        "pressure_tendency_txt":  _ru(_ext_val(html, "010063"), TEND_RU),
        "pressure_change_24h":    _ext_val(html, "010062"),

        # Температура и влажность (K → °C)
        "temp":     round(_ext_val(html, "012101") - 273.15, 1) if _ext_val(html, "012101") else None,
        "dew":      round(_ext_val(html, "012103") - 273.15, 1) if _ext_val(html, "012103") else None,
        "humidity": _ext_val(html, "013003"),

        # Ветер
        "wind_dir":                _ext_val(html, "011001"),
        "wind_spd_kmh":            wind_spd_kmh,
        "wind_spd_ms":             wind_spd_ms,
        "wind_gust_spd_10min_ms":  _ext_val(html, "011041", 0),
        "wind_gust_dir_10min":     _ext_val(html, "011043", 0),
        "wind_gust_spd_180min_ms": _ext_val(html, "011041", 1),
        "wind_gust_dir_180min":    _ext_val(html, "011043", 1),

        # Видимость
        "visibility": _ext_val(html, "020001"),

        # Облачность
        "cloud_cover_pct":   _ext_val(html, "020010"),
        "cloud_amount":      _ext_val(html, "020011", 0),
        "cloud_base_m":      _ext_val(html, "020013", 0),
        "cloud_type_cl":     _ext_val(html, "020012", 0),
        "cloud_type_cm":     _ext_val(html, "020012", 1),
        "cloud_type_ch":     _ext_val(html, "020012", 2),
        "cloud_type_cl_txt": _ru(_ext_val(html, "020012", 0), CL_RU),
        "cloud_type_cm_txt": _ru(_ext_val(html, "020012", 1), CM_RU),
        "cloud_type_ch_txt": _ru(_ext_val(html, "020012", 2), CH_RU),

        # Погода
        "weather_now":       _ext_val(html, "020003"),
        "weather_now_txt":   _ru(_ext_val(html, "020003"), WW_RU),
        "weather_past1":     _ext_val(html, "020004"),
        "weather_past1_txt": _ru(_ext_val(html, "020004"), W_PAST_RU),
        "weather_past2":     _ext_val(html, "020005"),
        "weather_past2_txt": _ru(_ext_val(html, "020005"), W_PAST_RU),

        # Осадки
        "precip_period1_mm": _ext_val(html, "013011", 0),
        "precip_period2_mm": _ext_val(html, "013011", 1),
        "precip_24h_mm":     _ext_val(html, "013023"),
        "snow_depth_m":      _ext_val(html, "013013"),

        # Температура почвы
        "ground_temp":         round(_ext_val(html, "012120") - 273.15, 1) if _ext_val(html, "012120") else None,
        "ground_min_temp_12h": round(_ext_val(html, "012113") - 273.15, 1) if _ext_val(html, "012113") else None,
        "ground_state":        _ext_val(html, "020062"),

        # Экстремумы температуры
        "temp_max_12h": round(_ext_val(html, "012111") - 273.15, 1) if _ext_val(html, "012111") else None,
        "temp_min_12h": round(_ext_val(html, "012112") - 273.15, 1) if _ext_val(html, "012112") else None,
        "temp_change":  _ext_val(html, "012049"),

        # Инсоляция
        "sunshine_period1_min": _ext_val(html, "014031", 0),
        "sunshine_24h_min":     _ext_val(html, "014031", 1),

        # Испарение
        "evaporation": _ext_val(html, "013033"),

        # Радиация период 1
        "rad1_lw":      _ext_val(html, "014002", 0),
        "rad1_sw":      _ext_val(html, "014004", 0),
        "rad1_net":     _ext_val(html, "014016", 0),
        "rad1_global":  _ext_val(html, "014028", 0),
        "rad1_diffuse": _ext_val(html, "014029", 0),
        "rad1_direct":  _ext_val(html, "014030", 0),

        # Радиация период 2
        "rad2_lw":      _ext_val(html, "014002", 1),
        "rad2_sw":      _ext_val(html, "014004", 1),
        "rad2_net":     _ext_val(html, "014016", 1),
        "rad2_global":  _ext_val(html, "014028", 1),
        "rad2_diffuse": _ext_val(html, "014029", 1),
        "rad2_direct":  _ext_val(html, "014030", 1),
    }
    return obs

# ── JSON I/O ──────────────────────────────────────────────────────────────────

def load_bufr_json(year: int) -> list:
    path = os.path.join(BASE_DIR, f"data/bufr_{year}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bufr_json(year: int, records: list):
    path = os.path.join(BASE_DIR, f"data/bufr_{year}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def dt_exists(records: list, dt: datetime.datetime) -> bool:
    key = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return any(r.get("dt") == key for r in records)


def find_record(records: list, dt: datetime.datetime):
    key = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in records:
        if r.get("dt") == key:
            return r
    return None


# ── SYNOP-fallback (ogimet) ───────────────────────────────────────────────
# [ДОБАВЛЕНО 2026-10-06] НАХОДКА: Meteomanz отдаёт с VPS HTTP 403 почти весь
# день (виден лимит/блок по IP), BUFR-запись попадала в bufr_YYYY.json только
# в окно ~00–04 UTC (1–2 раза в сутки). SYNOP с ogimet при этом приходит
# штатно каждые 3 часа (data/synop_YYYY.txt, шаг update.py). Если BUFR для
# срока не получен, собираем запись той же формы из SYNOP-телеграммы и
# помечаем obs_source="SYNOP-ogimet". Когда настоящий BUFR позже
# приходит (окно <=48 ч), fetch_and_append() заменяет такую запись.
SYNOP_FALLBACK_SRC = "SYNOP-ogimet"
SYNOP_UPGRADE_HOURS = 48


def _synop_vv_to_m(vv: str):
    if not vv.isdigit():
        return None
    v = int(vv)
    if v == 0:
        return 50.0
    if 1 <= v <= 50:
        return v * 100.0
    if 56 <= v <= 80:
        return (v - 50) * 1000.0
    if 81 <= v <= 88:
        return (30 + (v - 80) * 5) * 1000.0
    if v == 89:
        return 70000.0
    return {90: 25.0, 91: 50.0, 92: 200.0, 93: 500.0, 94: 1000.0,
            95: 2000.0, 96: 4000.0, 97: 10000.0, 98: 20000.0, 99: 50000.0}.get(v)


def synop_line_to_bufr_record(line: str, dt: datetime.datetime, station: str = None):
    """Строка ogimet getsynop ('33837,2026,10,04,15,00,AAXX ...=') ->
    словарь той же формы, что parse_obs() (BUFR). Поля, которых нет в SYNOP
    (порывы, радиация, влажность, температура поверхности и т.д.), = None."""
    station = station or STATION
    telegram = line.split(",", 6)[-1] if "," in line else line
    parts = telegram.strip().rstrip("=").split()
    if "AAXX" not in parts:
        return None
    i = parts.index("AAXX")
    if len(parts) < i + 5:
        return None
    iw = parts[i + 1][4] if len(parts[i + 1]) == 5 else "1"
    irixhvv = parts[i + 3]
    wind_group = parts[i + 4]
    ix = irixhvv[1] if re.fullmatch(r"[\d/]{5}", irixhvv) else None
    visibility = _synop_vv_to_m(irixhvv[3:5]) if ix is not None else None

    n_raw = wind_dir = wind_ms = None
    if re.fullmatch(r"[\d/]{5}", wind_group):
        if wind_group[0].isdigit():
            n_raw = int(wind_group[0])
        if wind_group[1:3].isdigit():
            wind_dir = int(wind_group[1:3]) * 10.0
        if wind_group[3:5].isdigit():
            ff = float(wind_group[3:5])
            wind_ms = ff if iw in "01" else round(ff * 0.514444, 1)

    rec = {
        "temp": None, "dew": None, "station_pressure": None, "slp": None,
        "tend_a": None, "tend_v": None, "precip": None, "g7": None, "g8": None,
    }
    for g in parts[i + 5:]:
        g = g.rstrip("=")
        if not g:
            continue
        if g in ("333", "444", "555"):
            break
        if re.fullmatch(r"1[01]\d{3}", g):
            rec["temp"] = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        elif re.fullmatch(r"2[01]\d{3}", g):
            rec["dew"] = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        elif re.fullmatch(r"3\d{4}", g):
            p = int(g[1:]) / 10
            rec["station_pressure"] = p + 1000 if p < 500 else p
        elif re.fullmatch(r"4\d{4}", g):
            p = int(g[1:]) / 10
            rec["slp"] = p + 1000 if p < 500 else p
        elif re.fullmatch(r"5[0-8]\d{3}", g):
            a = int(g[1])
            t = int(g[2:]) / 10
            rec["tend_a"] = a
            rec["tend_v"] = -t if a >= 5 else t
        elif re.fullmatch(r"6[\d/]{4}", g):
            from ground_station_obs_fetch import _decode_precip_group
            rec["precip"], _ = _decode_precip_group(g)
        elif re.fullmatch(r"7[\d/]{4}", g):
            rec["g7"] = g
        elif re.fullmatch(r"8[\d/]{4}", g):
            rec["g8"] = g
    if rec["temp"] is None or rec["slp"] is None:
        return None  # битая/неполная телеграмма — не пишем

    # облачность: N (окта) -> %, Nh -> cloud_amount, CL/CM/CH -> коды BUFR 30+/20+/10+
    okta = None if n_raw is None else (8 if n_raw == 9 else n_raw)
    cloud_pct = None if okta is None else round(okta * 12.5, 1)
    g8 = rec["g8"]
    nh = cl = cm = ch = None
    if g8:
        nh = int(g8[1]) if g8[1].isdigit() else None
        cl = 30 + int(g8[2]) if g8[2].isdigit() else None
        cm = 20 + int(g8[3]) if g8[3].isdigit() else None
        ch = 10 + int(g8[4]) if g8[4].isdigit() else None
    elif n_raw == 0:
        nh, cl, cm, ch = 0, 30, 20, 10

    # текущая/прошедшая погода
    ww = w1 = w2 = None
    g7 = rec["g7"]
    if ix in ("1", "4") and g7:
        ww = int(g7[1:3]) if g7[1:3].isdigit() else None
        w1 = int(g7[3]) if g7[3].isdigit() else None
        w2 = int(g7[4]) if g7[4].isdigit() else None
    elif ix in ("2", "5"):
        ww, w1, w2 = 508, 10, 10

    a = rec["tend_a"]
    obs = {k: None for k in (
        "pressure_change_24h", "humidity", "wind_gust_spd_10min_ms",
        "wind_gust_dir_10min", "wind_gust_spd_180min_ms", "wind_gust_dir_180min",
        "cloud_base_m", "precip_period2_mm", "precip_24h_mm", "snow_depth_m",
        "ground_temp", "ground_min_temp_12h", "ground_state", "temp_max_12h",
        "temp_min_12h", "temp_change", "sunshine_period1_min", "sunshine_24h_min",
        "evaporation", "rad1_lw", "rad1_sw", "rad1_net", "rad1_global",
        "rad1_diffuse", "rad1_direct", "rad2_lw", "rad2_sw", "rad2_net",
        "rad2_global", "rad2_diffuse", "rad2_direct")}
    obs.update({
        "dt": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": station,
        "station_pressure": rec["station_pressure"],
        "slp": rec["slp"],
        "pressure_tendency_val": rec["tend_v"],
        "pressure_tendency_code": None if a is None else float(a),
        "pressure_tendency_txt": None if a is None else TEND_RU.get(a),
        "temp": rec["temp"],
        "dew": rec["dew"],
        "wind_dir": wind_dir,
        "wind_spd_ms": wind_ms,
        "wind_spd_kmh": None if wind_ms is None else round(wind_ms * 3.6, 1),
        "visibility": visibility,
        "cloud_cover_pct": cloud_pct,
        "cloud_amount": None if nh is None else float(nh),
        "cloud_type_cl": None if cl is None else float(cl),
        "cloud_type_cm": None if cm is None else float(cm),
        "cloud_type_ch": None if ch is None else float(ch),
        "cloud_type_cl_txt": CL_RU.get(cl) if cl is not None else None,
        "cloud_type_cm_txt": CM_RU.get(cm) if cm is not None else None,
        "cloud_type_ch_txt": CH_RU.get(ch) if ch is not None else None,
        "weather_now": None if ww is None else float(ww),
        "weather_now_txt": WW_RU.get(ww) if ww is not None else None,
        "weather_past1": None if w1 is None else float(w1),
        "weather_past1_txt": W_PAST_RU.get(w1) if w1 is not None else None,
        "weather_past2": None if w2 is None else float(w2),
        "weather_past2_txt": W_PAST_RU.get(w2) if w2 is not None else None,
        "precip_period1_mm": rec["precip"],
        "obs_source": SYNOP_FALLBACK_SRC,
    })
    return obs


def synop_fallback_for_missing(days_back: int = 2, dry_run: bool = False) -> list:
    """Для сроков SYNOP_HOURS за последние days_back суток, которых нет в
    bufr_YYYY.json, строит запись из data/synop_YYYY.txt (уже скачан
    ogimet-шагом update.py). Сеть не трогает. Возвращает список изменённых
    файлов (относительные пути) для git."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    changed = []
    by_year = {}
    for d in range(days_back + 1):
        day = now - datetime.timedelta(days=d)
        for h in SYNOP_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            if t <= now:
                by_year.setdefault(t.year, []).append(t)
    for year, targets in by_year.items():
        synop_path = os.path.join(BASE_DIR, f"data/synop_{year}.txt")
        if not os.path.exists(synop_path):
            continue
        with open(synop_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        records = load_bufr_json(year)
        dirty = False
        for t in sorted(targets):
            if dt_exists(records, t):
                continue
            prefix = f"{STATION},{t.year},{t.month:02d},{t.day:02d},{t.hour:02d},00,"
            line = next((l for l in reversed(lines) if l.startswith(prefix)), None)
            if not line:
                continue
            obs = synop_line_to_bufr_record(line, t)
            if obs is None:
                continue
            log.info(f"[BUFR] fallback SYNOP-ogimet: {t:%Y-%m-%d %H}:00 UTC  T={obs['temp']}°C  SLP={obs['slp']}hPa")
            records.append(obs)
            dirty = True
        if dirty and not dry_run:
            records.sort(key=lambda r: r["dt"])
            save_bufr_json(year, records)
            changed.append(f"data/bufr_{year}.json")
    return changed

# ── BUFR как fallback для произвольной станции (не только 33837) ─────────
# Добавлено 2026-08-16. Находка: FETESTI (WMO 15444) и MAHMUDIA (WMO
# 15337) — станции ahead/behind трека фронта — больше не шлют классический
# SYNOP на ogimet (Meteostat подтверждает: данные оборвались в 2021), но
# продолжают слать почасовой АВТОМАТИЧЕСКИЙ BUFR через тот же WMO-индекс
# на Meteomanz. Ниже — обобщение fetch_html()/parse_obs() (уже сделано
# выше, station-параметр) плюс адаптер к той же форме словаря, что
# ground_station_obs_fetch.py::parse_synop_essentials() — чтобы
# eumetsat_ground_station_verify.py и фронтенд не знали разницы между
# SYNOP и BUFR-фолбэком, кроме поля obs_source.

def _essentials_from_bufr(obs: dict, dt: datetime.datetime) -> dict:
    """Адаптер BUFR (Meteomanz, см. parse_obs) -> essentials-словарь той
    же формы, что parse_synop_essentials() в ground_station_obs_fetch.py.
    weather_now в BUFR закодирован ТЕМ ЖЕ кодом ВМО 4677, что и ручной
    SYNOP ww (проверено — таблица WW_RU выше совпадает по значениям с
    WW_LABELS), поэтому переиспользуем WW_LABELS/EXTREME_WW_CODES оттуда,
    а не заводим вторую копию классификации опасных явлений."""
    from ground_station_obs_fetch import WW_LABELS, EXTREME_WW_CODES

    cloud_okta = None
    ca = obs.get("cloud_amount")
    if ca is not None and 0 <= ca <= 8:
        cloud_okta = int(ca)

    ww_raw = obs.get("weather_now")
    ww_code = int(ww_raw) if ww_raw is not None else None
    present_weather_label = WW_LABELS.get(ww_code, f"явление ww={ww_code}") if ww_code is not None else None
    is_extreme = ww_code in EXTREME_WW_CODES if ww_code is not None else False

    wind_dir_raw = obs.get("wind_dir")

    return {
        "obs_time": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temp": obs.get("temp"),
        "station_pressure": obs.get("station_pressure"),
        "sea_pressure": obs.get("slp"),
        "pressure_tendency_code": None,  # BUFR даёт готовое число (010061), не код 0-8, как в SYNOP
        "pressure_tendency_value": obs.get("pressure_tendency_val"),
        "total_cloud_okta": cloud_okta,
        "wind_dir_deg": int(wind_dir_raw) if wind_dir_raw is not None else None,
        "wind_speed_ms": obs.get("wind_spd_ms"),
        "precip_mm": obs.get("precip_period1_mm"),
        "precip_period_hours": None,  # BUFR период накопления (004024) пока не парсится
        "present_weather_code": ww_code,
        "present_weather_label": present_weather_label,
        "is_extreme_weather": is_extreme,
        "obs_source": "BUFR",
    }


# ── SYNOP-ветка той же страницы Meteomanz (не BUFR) ──────────────────────
# Добавлено 2026-09-03. Находка: `sy1?ty=hd&ind=...` — ОДИН И ТОТ ЖЕ URL,
# что уже используется выше для BUFR — отдаёт ВТОРОЙ вариант разметки для
# станций без автоматического BUFR (ручной SYNOP), маркер в HTML —
# "Synop, reported by a manned station." (в отличие от "BUFR report, by
# an automatic station." у автоматических). Подтверждено вживую через
# Termux пользователя (сеть Meteomanz недоступна из песочницы Claude) на
# станции TIRASPOL/33829, срок 03Z 2026-09-02 — см. SAMPLE_SYNOP_METEOMANZ
# в офлайн-тесте ниже, это дословный реальный образец.
#
# Разметка полей ЗЕРКАЛЬНАЯ относительно BUFR-ветки: <i><b>Label: </b></i>
# значение<br> (у BUFR — <b><i>Label: </i></b>, italic внутри bold, здесь
# наоборот) — поэтому отдельные _val_synop()/_label_pattern(), а не общие
# с _val()/_txt() выше.
#
# Схема возвращаемого словаря — ТА ЖЕ, что parse_synop_essentials() в
# ground_station_obs_fetch.py (ogimet), чтобы код-потребитель
# (ground_station_field_fetch.py, фронтенд) не видел разницы, откуда
# пришёл SYNOP.

EXTREME_WEATHER_KEYWORDS_EN = (
    "thunderstorm", "hail", "tornado", "waterspout", "squall",
    "blizzard", "duststorm", "dust storm", "sandstorm", "sand storm",
    "freezing rain", "freezing drizzle", "heavy shower", "heavy rain",
    "heavy snow",
)


def _label_pattern(label):
    """Собирает regex-паттерн из текста лейбла, заменяя пробелы между
    словами на \\s+ — у SYNOP-разметки Meteomanz внутри самого лейбла
    иногда лишние пробелы (реальный образец: "Present and past" затем
    ~20 пробелов, затем "weather") — обычный re.escape(label) целиком
    такое не поймает."""
    return r"\s+".join(re.escape(w) for w in label.split())


def _val_synop(html, label):
    """Аналог _val()/_txt() выше, но под зеркальный порядок тегов SYNOP-
    ветки: <i><b>Label\\s*:\\s*</b></i>значение<br>. Возвращает сырую
    строку значения БЕЗ попытки распарсить число — у этой ветки слишком
    разнородные форматы (диапазоны, составные значения, октаты словом),
    единую числовую логику как у BUFR-ветки сделать нельзя, разбор чисел
    делает каждый вызывающий код сам под свой формат поля."""
    pat = r"<i><b>\s*" + _label_pattern(label) + r"\s*:\s*</b></i>\s*(.*?)<br>"
    m = re.search(pat, html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()
    return raw if raw not in ("-", "", "\u2014") else None


def _num_synop(raw):
    if raw is None:
        return None
    m = re.match(r"^[+-]?\d+(?:\.\d+)?", raw)
    return float(m.group()) if m else None


def _pressure_tendency_code_from_text(text):
    """Сопоставляет текстовое описание тенденции давления с кодом ВМО
    (таблица 0200, 0-8). ПОДТВЕРЖДЕНО ВЖИВУЮ только простое "increasing"
    (без "then") + "higher" -> 2 (реальный образец 2026-09-03: "Increasing
    steadily; resultant pressure higher"). Симметричный простой случай
    "decreasing"+"lower" -> 7 и "steady"+"same" -> 4 добавлены по прямой
    симметрии таблицы, тоже не встречались вживую, но простые (без "then")
    и логически однозначные. СОСТАВНЫЕ варианты (коды 0,1,3,5,6,8 — "then
    decreasing"/"then steady"/"then increasing" и т.п., см. WMO table 0200)
    сознательно НЕ реализованы — ни одного реального образца текста для
    них от Meteomanz ещё не видели, гадать по общей формулировке таблицы
    не буду. Возвращает None и для них, и для нераспознанного текста —
    отсутствие кода лучше, чем неверный код."""
    if not text:
        return None
    low = text.lower()
    if "then" in low:
        return None
    if "increasing" in low and "higher" in low:
        return 2
    if "decreasing" in low and "lower" in low:
        return 7
    if "steady" in low and "same" in low:
        return 4
    return None


def parse_synop_essentials_from_meteomanz(html):
    """Парсит РУЧНОЙ SYNOP-вариант страницы Meteomanz (маркер "Synop,
    reported by a manned station.") в essentials-словарь той же формы,
    что parse_synop_essentials() в ground_station_obs_fetch.py (ogimet).
    Возвращает None, если это не та ветка (BUFR-страница или "нет
    данных") — тогда вызывающий код должен пробовать parse_obs() (BUFR)
    отдельно, см. fetch_latest_meteomanz_essentials() ниже, где оба
    парсера пробуются на ОДНОМ И ТОМ ЖЕ HTML-ответе.

    present_weather_code сознательно оставлен None — эта ветка Meteomanz
    отдаёт только ТЕКСТОВОЕ описание погодного явления (например "no
    significant weather"), не числовой код ВМО ww (таблица 4677/4680),
    поэтому обратно восстановить код нельзя без риска ошибки. Вместо
    этого is_extreme_weather определяется поиском англоязычных ключевых
    слов (EXTREME_WEATHER_KEYWORDS_EN) прямо в тексте — это эвристика под
    задачу проекта ("похоже ли на опасное явление рядом с фронтом"), не
    точное соответствие таблице ВМО."""
    if "Synop, reported by a manned station" not in html:
        return None
    if "No data for the selected dates" in html:
        return None

    temp = _num_synop(_val_synop(html, "Air Temperature"))
    station_pressure = _num_synop(_val_synop(html, "Station pressure"))
    sea_pressure = _num_synop(_val_synop(html, "Sea level pressure"))

    tendency_raw = _val_synop(html, "Pressure change")
    tendency_value = _num_synop(tendency_raw) if tendency_raw else None
    tendency_code = _pressure_tendency_code_from_text(tendency_raw)

    wind_dir_raw = _val_synop(html, "Wind direction")
    wind_dir_deg = None
    if wind_dir_raw:
        nums = re.findall(r"(\d+)\s*\u00ba", wind_dir_raw)
        if len(nums) == 2:
            wind_dir_deg = int(round((int(nums[0]) + int(nums[1])) / 2))
        elif len(nums) == 1:
            wind_dir_deg = int(nums[0])

    wind_speed_raw = _val_synop(html, "Wind speed")
    wind_speed_ms = None
    if wind_speed_raw:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*m/s", wind_speed_raw)
        if m:
            wind_speed_ms = float(m.group(1))

    cloud_raw = _val_synop(html, "Total cloud cover")
    total_cloud_okta = None
    if cloud_raw:
        m = re.match(r"^(\d+)", cloud_raw)
        if m:
            total_cloud_okta = int(m.group(1))

    precip_raw = _val_synop(html, "Precipitation data")
    precip_mm = None
    if precip_raw and "not available" not in precip_raw.lower():
        m = re.search(r"([\d.]+)\s*mm", precip_raw, re.IGNORECASE)
        if m:
            precip_mm = float(m.group(1))

    ww_text = _val_synop(html, "Present and past weather")
    is_extreme_weather = False
    if ww_text:
        low = ww_text.lower()
        is_extreme_weather = any(kw in low for kw in EXTREME_WEATHER_KEYWORDS_EN)

    day_raw = _val_synop(html, "Day")
    hour_raw = _val_synop(html, "Hour")
    obs_time = None
    if day_raw and hour_raw:
        m_day = re.match(r"(\d{2})/(\d{2})/(\d{4})", day_raw)
        m_hour = re.match(r"(\d{2})", hour_raw)
        if m_day and m_hour:
            dd, mm, yyyy = m_day.groups()
            obs_time = f"{yyyy}-{mm}-{dd}T{m_hour.group(1)}:00:00Z"

    return {
        "obs_time": obs_time,
        "temp": temp,
        "station_pressure": station_pressure,
        "sea_pressure": sea_pressure,
        "pressure_tendency_code": tendency_code,
        "pressure_tendency_value": tendency_value,
        "total_cloud_okta": total_cloud_okta,
        "wind_dir_deg": wind_dir_deg,
        "wind_speed_ms": wind_speed_ms,
        "precip_mm": precip_mm,
        "precip_period_hours": None,  # период накопления не парсится из этого текстового поля — не критично для задачи
        "present_weather_code": None,  # см. докстринг — эта ветка не даёт числовой код
        "present_weather_label": ww_text,
        "is_extreme_weather": is_extreme_weather,
        "obs_source": "SYNOP",
    }


def fetch_latest_meteomanz_essentials(station_id, hours_back=4):
    """Единый fetch с Meteomanz: ОДИН HTTP-запрос на попытку (не два
    отдельных BUFR-first/SYNOP-fallback запроса, как было бы при
    обращении к разным источникам) — пробует распарсить ответ И как BUFR
    (parse_obs), И как ручной SYNOP (parse_synop_essentials_from_
    meteomanz) на ОДНОМ И ТОМ ЖЕ HTML, поскольку это буквально одна и та
    же страница с разной разметкой в зависимости от станции/срока (см.
    докстринг раздела выше). Идёт назад по часу до hours_back попыток.
    Возвращает essentials-словарь или None, если ни один час не дал ни
    BUFR, ни SYNOP."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None, minute=0, second=0, microsecond=0
    )
    for h in range(hours_back):
        dt = now - datetime.timedelta(hours=h)
        if in_cooldown(station_id, dt):
            continue
        try:
            html = fetch_html(dt, station=station_id)
        except Exception as e:
            log.debug(f"[Meteomanz] {station_id} {dt:%Y-%m-%d %H}:00 UTC fetch ошибка: {e}")
            mark_attempt(station_id, dt)
            time.sleep(0.3)
            continue

        obs = parse_obs(html, dt, station=station_id)
        if obs is not None:
            return _essentials_from_bufr(obs, dt)

        synop_ess = parse_synop_essentials_from_meteomanz(html)
        if synop_ess is not None:
            if not synop_ess.get("obs_time"):
                synop_ess["obs_time"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            return synop_ess

        time.sleep(0.3)
    return None


def fetch_latest_bufr_essentials(station_id: str, hours_back: int = 4):
    """Идёт назад от текущего часа по одному часу (BUFR у этих станций —
    почасовой), до hours_back попыток, возвращает essentials-словарь на
    первом успешном часе или None, если ничего не нашлось за это окно.
    Используется как fallback в eumetsat_ground_station_verify.py, когда
    fetch_latest_obs() (SYNOP/ogimet) вернул None."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None, minute=0, second=0, microsecond=0
    )
    for h in range(hours_back):
        dt = now - datetime.timedelta(hours=h)
        if in_cooldown(station_id, dt):
            continue
        try:
            html = fetch_html(dt, station=station_id)
        except Exception as e:
            log.debug(f"[BUFR fallback] {station_id} {dt:%Y-%m-%d %H}:00 UTC fetch ошибка: {e}")
            mark_attempt(station_id, dt)
            time.sleep(0.3)
            continue
        obs = parse_obs(html, dt, station=station_id)
        if obs is None:
            time.sleep(0.3)
            continue
        return _essentials_from_bufr(obs, dt)
    return None

# ── Основная логика (штатный запуск для ст. 33837, без изменений) ────────

def fetch_and_append(dt: datetime.datetime, dry_run=False, station: str = None) -> bool:
    station = station or STATION
    records = load_bufr_json(dt.year)
    existing = find_record(records, dt)
    if existing is not None:
        age_h = (datetime.datetime.utcnow() - dt).total_seconds() / 3600
        if existing.get("obs_source") != SYNOP_FALLBACK_SRC or age_h > SYNOP_UPGRADE_HOURS:
            log.info(f"[BUFR] уже есть: {dt:%Y-%m-%d %H}:00 UTC")
            return False
        # запись собрана из SYNOP — пробуем заменить настоящим BUFR

    if in_cooldown(station, dt):
        log.info(f"[BUFR] кулдаун активен, пропуск: {dt:%Y-%m-%d %H}:00 UTC")
        return False

    try:
        html = fetch_html(dt, station=station)
    except Exception as e:
        log.warning(f"[BUFR] fetch ошибка {dt:%Y-%m-%d %H}:00 UTC: {e}")
        mark_attempt(station, dt)
        return False

    obs = parse_obs(html, dt, station=station)
    if obs is None:
        log.info(f"[BUFR] нет данных: {dt:%Y-%m-%d %H}:00 UTC")
        return False

    non_null = sum(1 for v in obs.values() if v is not None and v != obs["dt"] and v != obs["station"])
    log.info(f"[BUFR] {dt:%Y-%m-%d %H}:00 UTC  T={obs.get('temp')}°C  "
             f"SLP={obs.get('slp')}hPa  wind={obs.get('wind_spd_ms')}m/s  "
             f"fields={non_null}")

    if not dry_run:
        if existing is not None:
            records = [r for r in records if r.get("dt") != obs["dt"]]
        records.append(obs)
        records.sort(key=lambda r: r["dt"])
        save_bufr_json(dt.year, records)
    return True

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch BUFR obs from Meteomanz")
    parser.add_argument("--hours", type=int, default=1,
                        help="Сколько последних сроков забрать (default=1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Не писать файл, только показать что нашли")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Добрать N последних суток (например --backfill 3)")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    if args.backfill > 0:
        candidates = []
        for d in range(args.backfill + 1):
            day = now - datetime.timedelta(days=d)
            for h in SYNOP_HOURS:
                candidates.append(
                    day.replace(hour=h, minute=0, second=0, microsecond=0)
                )
        targets = sorted([c for c in candidates if c <= now])
    else:
        candidates = []
        for d in range(2):
            day = now - datetime.timedelta(days=d)
            for h in SYNOP_HOURS:
                candidates.append(
                    day.replace(hour=h, minute=0, second=0, microsecond=0)
                )
        candidates.sort(reverse=True)
        targets = [c for c in candidates if c <= now][:args.hours]
        targets = list(reversed(targets))

    for dt in targets:
        fetch_and_append(dt, dry_run=args.dry_run)
        time.sleep(2)

if __name__ == "__main__":
    main()
