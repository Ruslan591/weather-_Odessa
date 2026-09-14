"""
ground_station_obs_fetch.py — получение и разбор ПОСЛЕДНЕЙ SYNOP-телеграммы
для произвольной станции (не только 33837) — план шага 5, пункт 3.

Логика запроса к ogimet (прямой + proxy-fallback) — тот же паттерн, что уже
проверен в scripts/update.py::fetch_synop_ogimet(), но параметризована по
station id, а не жёстко привязана к STATION="33837". СОЗНАТЕЛЬНО копия, а
не импорт из update.py — update.py это главный продакшн-пайплайн (шаг 1
основного пайплайна), трогать его ради несвязанной спутниковой фичи
нежелательно (риск сломать существующий рабочий код при рефакторинге).

Не пишет файлов — только fetch+parse, возвращает структуры. Запись в
eumetsat_frontal_track.json — план пункт 4, отдельный шаг.

Формат begin/end у ogimet getsynop — 12 знаков YYYYMMDDHHMM (год-месяц-
день-час-МИНУТЫ), см. находку 2026-08-15 в docs/topics/eumetsat.md — с
10-значным форматом (без минут) возвращает пусто.
"""

import re
import time
import logging
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.parse import quote

log = logging.getLogger(__name__)

# ── Осадки (группа 6RRRtr) и текущая погода (группа 7wwW1W2) ────────────
# Добавлено 2026-08-15 (продолжение) по запросу: "информации об осадках,
# ветре и экстремальных явлениях не хватает" — ветер уже был в essentials
# (wind_dir_deg/wind_speed_ms), тут добор осадков и опасных явлений.

PRECIP_PERIOD_HOURS = {
    "0": 6, "1": 12, "2": 18, "3": 24,
    "4": 1, "5": 2, "6": 3, "7": 9, "8": 15,
}

# Присутствующая погода (код ww, таблица ВМО 4677) — НЕ полная таблица,
# только опасные/значимые явления (нужные для is_extreme_weather) плюс их
# читаемые подписи. Остальные коды (00-16 без явлений в срок, 20-28
# явления в предыдущий час без грозы/шквала, обычные дождь/снег/морось/
# туман без усиления) для задачи верификации фронта не критичны, дают
# generic "явление ww=NN" вместо расшифровки.
WW_LABELS = {
    17: "гроза (без осадков в срок наблюдения)",
    18: "шквал(ы)",
    19: "смерч/торнадо",
    29: "гроза в предыдущий час",
    30: "пыльная/песчаная буря (слабая, ослабевает)",
    31: "пыльная/песчаная буря (слабая-умеренная)",
    32: "пыльная/песчаная буря (слабая-умеренная, усиливается)",
    33: "сильная пыльная/песчаная буря (ослабевает)",
    34: "сильная пыльная/песчаная буря (без изменений)",
    35: "сильная пыльная/песчаная буря (усиливается)",
    36: "позёмок снега (слабый-умеренный)",
    37: "позёмок снега (сильный)",
    38: "низовая метель (слабая-умеренная)",
    39: "низовая метель (сильная)",
    56: "переохлаждённая морось (слабая)",
    57: "переохлаждённая морось (умеренная-сильная)",
    66: "переохлаждённый дождь (слабый)",
    67: "переохлаждённый дождь (умеренный-сильный)",
    82: "сильный ливень",
    84: "очень сильный ливень",
    86: "сильный ливневый снег",
    87: "слабая/умеренная ледяная/снежная крупа",
    88: "сильная ледяная/снежная крупа",
    89: "слабый/умеренный град",
    90: "сильный град",
    91: "гроза слабая/умеренная с дождём/снегом",
    92: "гроза сильная с дождём/снегом",
    93: "гроза слабая/умеренная с градом",
    94: "гроза сильная с градом",
    95: "гроза слабая/умеренная",
    96: "гроза слабая/умеренная с градом",
    97: "гроза сильная с дождём/снегом",
    98: "гроза с пыльной/песчаной бурей",
    99: "гроза сильная с градом",
}

# ww-коды, при которых явление считается ОПАСНЫМ для верификации фронта
# (гроза, шквал, смерч, сильные ливни/град/метели/бури, переохлаждённые
# осадки). Отдельно от WW_LABELS (та шире, справочная).
EXTREME_WW_CODES = {
    17, 18, 19, 29, 33, 34, 35, 37, 39, 56, 57, 66, 67,
    82, 84, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}


def _decode_precip_group(g):
    """g — токен '6RRRtr' (5 символов). Код таблицы ВМО 3590: 000-988 —
    осадки в мм (целое число); 989 — 989мм и более; 990 — след осадков
    (<0.1мм, приближённо возвращаем 0.05); 991-999 — (RRR-990)/10 мм.
    tr — код периода накопления (таблица 4019, см. PRECIP_PERIOD_HOURS).
    '/' в RRR — измерение недоступно (mm=None, период всё равно вернём,
    если tr читаем)."""
    rrr, tr = g[1:4], g[4]
    period = PRECIP_PERIOD_HOURS.get(tr)
    if not rrr.isdigit():
        return None, period
    rrr_i = int(rrr)
    if rrr_i <= 988:
        mm = float(rrr_i)
    elif rrr_i == 989:
        mm = 989.0
    elif rrr_i == 990:
        mm = 0.05
    else:
        mm = (rrr_i - 990) / 10.0
    return mm, period

OGIMET_PROXIES = [
    "https://api.allorigins.win/raw?url=",
    "https://corsproxy.io/?",
]


def _http_get(url, timeout=20):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _retry(fn, attempts=2, delay=3):
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last_exc


def fetch_synop_ogimet(station_id, hours_back=9, timeout=15):
    """Возвращает сырой текст ogimet getsynop за последние hours_back часов
    для station_id, или None если ни прямой запрос, ни оба прокси не
    сработали."""
    now = datetime.now(timezone.utc)
    begin = (now - timedelta(hours=hours_back)).strftime("%Y%m%d%H%M")
    end = now.strftime("%Y%m%d%H%M")
    url = f"https://www.ogimet.com/cgi-bin/getsynop?block={station_id}&begin={begin}&end={end}"

    try:
        text = _retry(lambda: _http_get(url, timeout=timeout))
        if text and station_id in text:
            return text
    except Exception as e:
        log.debug("  [%s] прямой запрос ogimet не сработал: %s", station_id, e)

    for proxy in OGIMET_PROXIES:
        try:
            purl = proxy + quote(url, safe="")
            text = _retry(lambda: _http_get(purl, timeout=timeout + 5))
            if text and station_id in text:
                return text
        except Exception as e:
            log.debug("  [%s] прокси %s не сработал: %s", station_id, proxy, e)

    return None


def latest_telegram_line(raw_text, station_id):
    """Из многострочного ответа ogimet (одна строка на срок наблюдения)
    выбирает строку с максимальным временем. Формат строки:
    STATION,YYYY,MM,DD,HH,MM,AAXX ...телеграмма...="""
    best_line, best_ts = None, None
    for raw in (raw_text or "").splitlines():
        line = raw.strip()
        if not line.startswith(station_id + ","):
            continue
        parts = line.split(",", 6)
        if len(parts) < 7:
            continue
        try:
            ts = datetime(int(parts[1]), int(parts[2]), int(parts[3]),
                          int(parts[4]), int(parts[5]), tzinfo=timezone.utc)
        except ValueError:
            continue
        if best_ts is None or ts > best_ts:
            best_ts, best_line = ts, line
    return best_line, best_ts


def parse_synop_essentials(line):
    """Разбирает поля, нужные для верификации термодинамической подписи
    фронта: давление + 3ч-тенденция, температура, ветер, общая облачность,
    ОСАДКИ (группа 6RRRtr) и ТЕКУЩАЯ ПОГОДА/опасные явления (группа
    7wwW1W2 — гроза/шквал/град/сильные ливни и т.п., см. WW_LABELS/
    EXTREME_WW_CODES выше) — добавлено 2026-08-15 по запросу "не хватает
    осадков/ветра/экстремальных явлений" (ветер уже был). НЕ полный
    парсер, как parseSynop() в synop.js (там для отображения на фронтенде
    нужно всё; здесь — только сигнал "похоже на фронт или нет" для станций
    впереди/позади трека). Секции 333/444/555 сознательно не разбираются —
    не нужны для этой задачи. Возвращает dict или None если AAXX не найден
    (телеграмма битая/NIL)."""
    if not line:
        return None
    telegram = line.split(",", 6)[-1] if "," in line else line
    parts = telegram.strip().split()
    if "AAXX" not in parts:
        return None
    i = parts.index("AAXX")
    wind_group = parts[i + 4] if len(parts) > i + 4 else None

    total_cloud = wind_dir = wind_speed = None
    if wind_group and re.fullmatch(r"\d{5}", wind_group):
        total_cloud = int(wind_group[0])
        raw_dir = int(wind_group[1:3])
        wind_dir = None if raw_dir == 0 else raw_dir * 10
        wind_speed = int(wind_group[3:5])

    temp = station_pressure = sea_pressure = None
    tendency_code = tendency_value = None
    precip_mm = precip_period_hours = None
    ww_code = present_weather_label = None
    is_extreme_weather = False

    for g in parts[i + 5:]:
        g = g.rstrip("=")
        if not g:
            continue
        if g in ("333", "444", "555"):
            break  # дальше секции, для этой задачи не нужны
        if re.fullmatch(r"1[01]\d{3}", g):
            sign = -1 if g[1] == "1" else 1
            temp = sign * int(g[2:]) / 10
        elif re.fullmatch(r"3\d{4}", g):
            p = int(g[1:]) / 10
            station_pressure = p + 1000 if p < 500 else p
        elif re.fullmatch(r"4\d{4}", g):
            p = int(g[1:]) / 10
            sea_pressure = p + 1000 if p < 500 else p
        elif re.fullmatch(r"5\d{4}", g):
            tendency_code = g[1]
            t_raw = int(g[2:]) / 10
            tendency_value = -t_raw if g[1] in "5678" else t_raw
        elif re.fullmatch(r"6[\d/]{4}", g):
            precip_mm, precip_period_hours = _decode_precip_group(g)
        elif re.fullmatch(r"7[\d/]{4}", g):
            ww_raw = g[1:3]
            if ww_raw.isdigit():
                ww_code = int(ww_raw)
                present_weather_label = WW_LABELS.get(ww_code, f"явление ww={ww_code}")
                is_extreme_weather = ww_code in EXTREME_WW_CODES

    return {
        "temp": temp,
        "station_pressure": station_pressure,
        "sea_pressure": sea_pressure,
        "pressure_tendency_code": tendency_code,
        "pressure_tendency_value": tendency_value,
        "total_cloud_okta": total_cloud,
        "wind_dir_deg": wind_dir,
        "wind_speed_ms": wind_speed,
        "precip_mm": precip_mm,
        "precip_period_hours": precip_period_hours,
        "present_weather_code": ww_code,
        "present_weather_label": present_weather_label,
        "is_extreme_weather": is_extreme_weather,
        "obs_source": "SYNOP",
    }


def fetch_latest_obs(station_id, hours_back=9):
    """Высокоуровневая функция: fetch + выбор последней строки + парсинг.
    Возвращает dict {"obs_time", "raw", **essentials} если станция
    ответила (даже если телеграмма не распарсилась — тогда essentials
    поля будут None), либо None если сеть/ogimet вообще не ответили
    (отличие от "станция ответила пустым списком" важно для верхнего
    уровня — не путать "нет сети" с "нет данных за период")."""
    raw_text = fetch_synop_ogimet(station_id, hours_back=hours_back)
    if raw_text is None:
        return None
    line, ts = latest_telegram_line(raw_text, station_id)
    if line is None:
        return {"obs_time": None, "raw": None}
    essentials = parse_synop_essentials(line) or {}
    return {
        "obs_time": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
        "raw": line,
        **essentials,
    }


if __name__ == "__main__":
    # Офлайн-тест парсинга на РЕАЛЬНЫХ телеграммах (получены через Termux
    # 2026-08-15, станция 33745 Бэлць, MD) — без сети, sandbox не может
    # достучаться до ogimet.com напрямую (не в network allowlist), но
    # latest_telegram_line()/parse_synop_essentials() тестируются на уже
    # полученном тексте без проблем.
    SAMPLE = """\
33745,2026,08,14,00,00,AAXX 14001 33745 42997 00501 10124 20077 30075 40267 57009 555 10014=
33745,2026,08,14,03,00,AAXX 14031 33745 42997 20000 10118 20110 30069 40261 57005 82030 333 55129 555 20117 7000/=
33745,2026,08,14,06,00,AAXX 14061 33745 32997 50000 10173 20124 30071 40259 53002 82031 333 20117 555 800//=
33745,2026,08,14,09,00,AAXX 14091 33745 42697 60202 10243 20091 30065 40249 58006 83130=
33745,2026,08,14,12,00,AAXX 14121 33745 42697 53602 10253 20083 30051 40234 57014 82101 555 10051=
33745,2026,08,14,15,00,AAXX 14151 33745 42997 23402 10259 20070 30040 40222 57011 80001=
33745,2026,08,14,18,00,AAXX 14181 33745 32997 03501 10209 20079 30042 40227 53002 333 10267 555 800//=
33745,2026,08,14,21,00,AAXX 14211 33745 42997 00501 10171 20083 30050 40238 52008=
33745,2026,08,15,00,00,AAXX 15001 33745 42997 00000 10121 20095 30051 40242 52001 555 10014=
"""

    line, ts = latest_telegram_line(SAMPLE, "33745")
    print("Последняя строка:", line)
    print("ts:", ts)
    assert ts is not None and ts.hour == 0 and ts.day == 15, ts
    assert line.startswith("33745,2026,08,15,00,00,"), line

    essentials = parse_synop_essentials(line)
    print("essentials:", essentials)

    # Телеграмма 15.08 00:00: AAXX 15001 33745 42997 00000 10121 20095
    # 30051 40242 52001 555 10014=
    # Nddff=00000 → N=0 (ясно), dd=00 → штиль (None), ff=00 → 0 м/с
    # 1(0)121 → temp=+12.1°C
    # 3(0)051 → давление на станции: 005.1 → <500 → +1000 = 1005.1 гПа
    # 4(0)242 → давление на уровне моря: 024.2 → <500 → +1000 = 1024.2 гПа
    # 5(2)001 → тенденция код=2 (непрерывно росло), значение +0.1 гПа
    assert essentials["temp"] == 12.1, essentials
    assert essentials["station_pressure"] == 1005.1, essentials
    assert essentials["sea_pressure"] == 1024.2, essentials
    assert essentials["pressure_tendency_code"] == "2"
    assert essentials["pressure_tendency_value"] == 0.1, essentials
    assert essentials["total_cloud_okta"] == 0, essentials
    assert essentials["wind_dir_deg"] is None  # dd=00 → штиль
    assert essentials["wind_speed_ms"] == 0, essentials

    # Ещё одна проверка — телеграмма с секцией 333 (03:00), essentials
    # должны игнорировать 333 и не выбрасывать исключение.
    line2, _ = latest_telegram_line(SAMPLE.replace("2026,08,15", "2026,08,99"), "33745")
    # (искусственно "скрыли" самую свежую строку заменой даты на невалидную
    # 99 — она не пройдёт datetime(...) и будет пропущена, следующая по
    # свежести — 21:00 14.08, без секции 333)
    print("line2 (без 15.08):", line2)
    assert line2.startswith("33745,2026,08,14,21,00,"), line2

    line3, _ = latest_telegram_line(SAMPLE, "33745")
    # используем строку с 333-секцией напрямую (03:00 14.08) для проверки
    # что парсер не падает и корректно останавливается на "333"
    line_0300 = [l for l in SAMPLE.splitlines() if l.startswith("33745,2026,08,14,03,00,")][0]
    essentials_0300 = parse_synop_essentials(line_0300)
    print("essentials (с секцией 333):", essentials_0300)
    assert essentials_0300["temp"] == 11.8, essentials_0300  # 1(0)118

    # Синтетическая проверка групп 6RRRtr (осадки) и 7wwW1W2 (текущая
    # погода/опасные явления) — 2026-08-15, реальных телеграмм с этими
    # группами в SAMPLE не оказалось, поэтому синтетика. 60063 → RRR=006,
    # tr=3 (24ч) → 6.0мм/24ч. 791// → ww=91 (гроза слабая/умеренная с
    # дождём/снегом) → is_extreme_weather=True.
    line_precip = (
        "33745,2026,08,15,03,00,AAXX 15031 33745 42997 00501 10121 20095 "
        "30051 40242 52001 60063 791// 333 8/// 555 10014="
    )
    ess_precip = parse_synop_essentials(line_precip)
    print("essentials (осадки+явление):", ess_precip)
    assert ess_precip["precip_mm"] == 6.0, ess_precip
    assert ess_precip["precip_period_hours"] == 24, ess_precip
    assert ess_precip["present_weather_code"] == 91, ess_precip
    assert ess_precip["present_weather_label"] == WW_LABELS[91], ess_precip
    assert ess_precip["is_extreme_weather"] is True, ess_precip
    # temp/pressure/tendency должны продолжать парситься как раньше, группы
    # 6/7 не должны их ломать.
    assert ess_precip["temp"] == 12.1, ess_precip
    assert ess_precip["sea_pressure"] == 1024.2, ess_precip
    assert ess_precip["obs_source"] == "SYNOP", ess_precip

    # Обычное явление (не в EXTREME_WW_CODES) — is_extreme_weather=False.
    line_normal = line_precip.replace("791//", "761//")  # ww=61 (обычный дождь)
    ess_normal = parse_synop_essentials(line_normal)
    assert ess_normal["present_weather_code"] == 61, ess_normal
    assert ess_normal["is_extreme_weather"] is False, ess_normal

    print("\nOK: все assert прошли (офлайн-тест парсинга на реальных телеграммах).")
