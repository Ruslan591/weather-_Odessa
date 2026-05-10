#!/usr/bin/env python3
"""
pws_sync.py — почасовая загрузка наблюдений PWS-станций.
Запускается GitHub Actions каждый час.
Пишет в data/pws_raw.json.
"""

import os, json, base64, math, logging
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Конфиг ──────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = "ruslan591"
GITHUB_REPO  = "weather-_Odessa"
FILE_PATH    = "data/pws_raw.json"
KEEP_DAYS    = 30

PWS_STATIONS = [
    {"id": "IODESA137", "name": "пос. Котовского",  "pressureOffset": 0    },
    {"id": "IODESA138", "name": "Центр",             "pressureOffset": 10.3 },
    {"id": "IODESA139", "name": "Чудо Город",        "pressureOffset": 0    },
    {"id": "IODESS41",  "name": "Судостроительная",  "pressureOffset": 0    },
    {"id": "IODESS44",  "name": "Аркадия",           "pressureOffset": -1.8 },
    {"id": "IODESS16",  "name": "Таирова",           "pressureOffset": 1.2  },
    {"id": "IODESS31",  "name": "Савиньон",          "pressureOffset": 0    },
    {"id": "IODESS37",  "name": "Застава",           "pressureOffset": 8.2  },
    {"id": "IKRASN91",  "name": "пос. Степовое",     "pressureOffset": 0    },
]

WU_KEYS = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525",
]
_key_index = 0

def next_key():
    return WU_KEYS[_key_index % len(WU_KEYS)]

def bump_key():
    global _key_index
    _key_index += 1

# ── HTTP ─────────────────────────────────────────────────────────────────────
def http_get_json(url, timeout=20):
    req = Request(url)
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

# ── GitHub API ───────────────────────────────────────────────────────────────
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def gh_get():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{FILE_PATH}"
    try:
        req  = Request(url, headers=GH_HEADERS)
        with urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
    except HTTPError as e:
        if e.code == 404:
            return [], None
        raise
    sha  = resp["sha"]
    # Большой файл — через download_url
    if "content" not in resp or not resp.get("content", "").strip():
        dl_url = resp.get("download_url")
        req2 = Request(dl_url)
        with urlopen(req2, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data, sha
    text = base64.b64decode(resp["content"].replace("\n", "")).decode("utf-8")
    return json.loads(text), sha

def gh_put(data, sha):
    content = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n]"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body    = {"message": "pws raw update", "content": encoded}
    if sha:
        body["sha"] = sha
    url  = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{FILE_PATH}"
    req  = Request(url,
                   data=json.dumps(body).encode("utf-8"),
                   headers={**GH_HEADERS, "Content-Type": "application/json"},
                   method="PUT")
    with urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return resp["content"]["sha"]

# ── Weather Underground API ──────────────────────────────────────────────────
def fetch_station(station_id, date_ymd, is_current):
    global _key_index
    for attempt in range(len(WU_KEYS)):
        key = next_key()
        if is_current:
            url = (f"https://api.weather.com/v2/pws/observations/all/1day"
                   f"?stationId={station_id}&format=json&units=m"
                   f"&numericPrecision=decimal&apiKey={key}")
        else:
            url = (f"https://api.weather.com/v2/pws/history/all"
                   f"?stationId={station_id}&format=json&units=m"
                   f"&numericPrecision=decimal&date={date_ymd}&apiKey={key}")
        try:
            data = http_get_json(url, timeout=20)
            obs  = data.get("observations", [])
            if not obs:
                raise ValueError("Нет наблюдений")
            return obs
        except HTTPError as e:
            if e.code in (401, 403):
                log.warning("  Ключ %s недействителен, пробуем следующий", key)
                bump_key()
            else:
                raise
    raise RuntimeError(f"Все ключи исчерпаны для {station_id}")

def pick_hourly(observations):
    """Выбирает одно наблюдение на час (ближайшее к целому часу ±10 мин)."""
    by_hour = {}
    for o in observations:
        t_str = o.get("obsTimeUtc", "")
        try:
            t = datetime.strptime(t_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        mn = t.minute
        if mn >= 49:
            rounded = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            dist = 60 - mn
        elif 4 <= mn <= 9:
            rounded = t.replace(minute=0, second=0, microsecond=0)
            dist = mn
        else:
            continue
        hk = rounded.strftime("%Y-%m-%dT%H")
        m  = o.get("metric", {})
        pt = m.get("precipTotal")
        gust = m.get("windgustHigh")
        gust_ms = round(gust / 3.6 * 10) / 10 if gust is not None else None
        if hk not in by_hour:
            by_hour[hk] = {"dist": dist, "obs": o, "ptMin": pt, "ptMax": pt, "gustMax": gust_ms}
        else:
            if dist < by_hour[hk]["dist"]:
                by_hour[hk]["dist"] = dist
                by_hour[hk]["obs"]  = o
            if pt is not None:
                if by_hour[hk]["ptMin"] is None or pt < by_hour[hk]["ptMin"]:
                    by_hour[hk]["ptMin"] = pt
                if by_hour[hk]["ptMax"] is None or pt > by_hour[hk]["ptMax"]:
                    by_hour[hk]["ptMax"] = pt
            if gust_ms is not None and (by_hour[hk]["gustMax"] is None or gust_ms > by_hour[hk]["gustMax"]):
                by_hour[hk]["gustMax"] = gust_ms

    result = []
    for hk in sorted(by_hour):
        entry = by_hour[hk]
        o = entry["obs"]
        m = o.get("metric", {})
        pressure = m.get("pressureMin") or m.get("pressureMax")
        precip = None
        if entry["ptMax"] is not None and entry["ptMin"] is not None:
            precip = round((entry["ptMax"] - entry["ptMin"]) * 10) / 10
            if precip < 0:
                precip = entry["ptMax"]
        wind = m.get("windspeedAvg")
        wind_ms = round(wind / 3.6 * 10) / 10 if wind is not None else None
        result.append({
            "hourKey":    hk,
            "obsTimeUtc": o.get("obsTimeUtc"),
            "temp":       m.get("tempAvg"),
            "humidity":   o.get("humidityAvg"),
            "wind":       wind_ms,
            "windGust":   entry["gustMax"],
            "windDir":    o.get("winddirAvg"),
            "pressure":   pressure,
            "precip":     precip,
        })
    return result

# ── Главная функция ──────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    log.info("=== pws_sync.py запущен %s ===", now.isoformat())

    # Загружаем существующие данные
    existing, sha = gh_get()
    log.info("  Загружено %d записей из pws_raw.json", len(existing))

    exist_keys = {(r["hourKey"], r.get("stationId", "")) for r in existing}

    # Определяем последний час в файле
    last_hk = max((r["hourKey"] for r in existing), default=None)
    cur_hk = now.strftime("%Y-%m-%dT%H")

    if last_hk and last_hk >= cur_hk:
        log.info("  Данные актуальны (последний час: %s)", last_hk)
        return

    # Определяем диапазон дат для загрузки
    if last_hk:
        start_date = datetime.strptime(last_hk[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_date = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    dates = []
    d = start_date
    while d <= now:
        dates.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)

    today_ymd = now.strftime("%Y%m%d")

    new_recs = []
    for station in PWS_STATIONS:
        sid    = station["id"]
        offset = station.get("pressureOffset", 0)
        log.info("  Станция %s (%s)...", sid, station["name"])
        for date_ymd in dates:
            is_current = date_ymd == today_ymd
            try:
                observations = fetch_station(sid, date_ymd, is_current)
                hourly = pick_hourly(observations)
                added = 0
                for obs in hourly:
                    key = (obs["hourKey"], sid)
                    if key in exist_keys:
                        continue
                    pressure = obs["pressure"]
                    if pressure is not None:
                        pressure = round((pressure + offset) * 100) / 100
                    new_recs.append({
                        "hourKey":    obs["hourKey"],
                        "stationId":  sid,
                        "obsTimeUtc": obs["obsTimeUtc"],
                        "temp":       obs["temp"],
                        "pressure":   pressure,
                        "wind":       obs["wind"],
                        "windGust":   obs["windGust"],
                        "windDir":    obs["windDir"],
                        "humidity":   obs["humidity"],
                        "precip":     obs["precip"],
                    })
                    exist_keys.add(key)
                    added += 1
                if added:
                    log.info("    %s: +%d записей", date_ymd, added)
            except Exception as e:
                log.warning("    %s %s: %s", sid, date_ymd, e)

    if not new_recs:
        log.info("  Нет новых записей")
        return

    # Чистим старые записи
    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H")
    merged = [r for r in existing if r.get("hourKey", "") >= cutoff]
    merged += new_recs
    merged.sort(key=lambda r: (r["hourKey"], r.get("stationId", "")))

    log.info("  Сохраняем %d записей (+%d новых)...", len(merged), len(new_recs))
    gh_put(merged, sha)
    log.info("  ✓ pws_raw.json обновлён")
    log.info("=== Готово ===")


if __name__ == "__main__":
    main()
