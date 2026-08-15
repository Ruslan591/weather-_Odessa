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
    """Разбирает ТОЛЬКО поля, нужные для верификации термодинамической
    подписи фронта (давление + 3ч-тенденция, температура, ветер, общая
    облачность) — НЕ полный парсер, как parseSynop() в synop.js (там для
    отображения на фронтенде нужно всё; здесь — только сигнал "похоже на
    фронт или нет" для станций впереди/позади трека). Секции 333/444/555
    сознательно не разбираются — не нужны для этой задачи. Возвращает
    dict или None если AAXX не найден (телеграмма битая/NIL)."""
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

    return {
        "temp": temp,
        "station_pressure": station_pressure,
        "sea_pressure": sea_pressure,
        "pressure_tendency_code": tendency_code,
        "pressure_tendency_value": tendency_value,
        "total_cloud_okta": total_cloud,
        "wind_dir_deg": wind_dir,
        "wind_speed_ms": wind_speed,
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

    print("\nOK: все assert прошли (офлайн-тест парсинга на реальных телеграммах).")
