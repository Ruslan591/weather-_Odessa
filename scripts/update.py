#!/usr/bin/env python3
"""
update.py — автоматическое обновление данных погодного проекта.

Запускается GitHub Actions по расписанию (cron).
Делает всё что раньше делали вручную:
  1. Получает новые SYNOP с ogimet → synop_YYYY.txt
  2. Дописывает modelData_YYYY.json (исторические прогнозы + наблюдения)
  3. Получает свежий ансамблевый прогноз → ensemble_snapshots_synop.json / _pws.json
  4. Выжимает старые снимки → ensemble_accuracy.json, удаляет выжатые
  5. Чистит pws_raw.json (старше 30 дней)
  6. Пересчитывает model_weights.json
"""

import os, json, math, time, base64, logging
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote

# ── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Конфиг ──────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]   # секрет из GitHub Actions
GITHUB_OWNER = "ruslan591"
GITHUB_REPO  = "weather-_Odessa"

STATION  = "33837"
LAT      = 46.4406
LON      = 30.7703

SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

# Модели ансамбля (из models.js)
ENSEMBLE_MODELS = [
    {"id": "ecmwf_ifs",                     "metaId": "ecmwf_ifs025"},
    {"id": "icon_eu",                        "metaId": "dwd_icon_eu"},
    {"id": "icon_global",                    "metaId": None},
    {"id": "ukmo_global_deterministic_10km", "metaId": "ukmo_global_deterministic_10km"},
    {"id": "meteofrance_arpege_europe",      "metaId": "meteofrance_arpege_europe"},
    {"id": "gfs_global",                     "metaId": "ncep_gfs013"},
    {"id": "gem_global",                     "metaId": None},
    {"id": "cma_grapes_global",              "metaId": "cma_grapes_global"},
]

OGIMET_PROXIES = [
    "https://api.allorigins.win/raw?url=",
    "https://corsproxy.io/?",
]

HOURLY_FIELDS = (
    "temperature_2m,apparent_temperature,pressure_msl,relative_humidity_2m,"
    "weather_code,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
    "precipitation,precipitation_probability,showers,snowfall,snow_depth,"
    "shortwave_radiation,direct_radiation,diffuse_radiation,dew_point_2m,runoff,"
    "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high"
)

PWS_KEEP_DAYS = 30        # сколько дней хранить pws_raw.json
SNAP_EXPIRE_HOURS = 400   # снимок удаляем когда все его часы прошли (чуть больше 16 суток)

# ── HTTP-утилиты ─────────────────────────────────────────────────────────────
def http_get(url, headers=None, timeout=20):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def http_get_json(url, headers=None, timeout=20):
    return json.loads(http_get(url, headers, timeout))

def retry(fn, attempts=3, delay=5):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            log.warning("  Retry %d/%d after: %s", i+1, attempts, e)
            time.sleep(delay)

# ── GitHub API ───────────────────────────────────────────────────────────────
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def gh_get(path):
    """Возвращает (text, sha) или (None, None) если файл не найден."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        resp = http_get_json(url, GH_HEADERS)
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    sha = resp.get("sha")
    if "content" in resp:
        text = base64.b64decode(resp["content"].replace("\n","")).decode("utf-8")
        return text, sha
    # Большой файл — через download_url
    dl_url = resp.get("download_url")
    if dl_url:
        text = http_get(dl_url, timeout=60)
        return text, sha
    return None, sha

def gh_put(path, content, sha, message):
    """Записывает файл на GitHub. Возвращает новый sha."""
    import urllib.request
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {"message": message, "content": encoded}
    if sha:
        body["sha"] = sha
    data = json.dumps(body).encode("utf-8")
    url  = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    req  = Request(url, data=data, headers={**GH_HEADERS, "Content-Type": "application/json"}, method="PUT")
    with urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return resp["content"]["sha"]

def gh_load_json(path, default=None):
    text, sha = gh_get(path)
    if text is None:
        return default if default is not None else [], sha
    try:
        return json.loads(text), sha
    except Exception:
        return default if default is not None else [], sha

def gh_save_json(path, data, sha, message, compact=False):
    if compact:
        content = json.dumps(data, ensure_ascii=False, separators=(",",":"))
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2)
    return gh_put(path, content, sha, message)

# ── Gist live-лог ────────────────────────────────────────────────────────────
GIST_ID    = os.environ.get("GIST_ID", "")
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")

_gist_lines = []

def gist_log(msg):
    """Логирует строку и пушит весь лог в Gist для live-отображения."""
    log.info(msg)
    if not GIST_ID or not GIST_TOKEN:
        return
    _gist_lines.append(msg)
    content = "\n".join(_gist_lines)
    import urllib.request
    data = json.dumps({"files": {"update_live.log": {"content": content}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=data,
        headers={
            "Authorization": f"Bearer {GIST_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        },
        method="PATCH"
    )
    try:
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e:
        log.warning("gist_log error: %s", e)

# ── Время ────────────────────────────────────────────────────────────────────
def utcnow():
    return datetime.now(timezone.utc)

def parse_iso(s):
    """Парсит ISO-строку в datetime с tzinfo=UTC."""
    s = s.rstrip("Z").split("+")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse datetime: {s!r}")

# ════════════════════════════════════════════════════════════════════════════
# 1. SYNOP: получение с ogimet и парсинг
# ════════════════════════════════════════════════════════════════════════════

def fetch_synop_ogimet(date_utc):
    """Получает SYNOP за один день (UTC). Возвращает текст или None."""
    y  = date_utc.year
    mo = f"{date_utc.month:02d}"
    d  = f"{date_utc.day:02d}"
    begin = f"{y}{mo}{d}0000"
    next_day = date_utc + timedelta(days=1)
    end = f"{next_day.year}{next_day.month:02d}{next_day.day:02d}0000"

    url = f"https://www.ogimet.com/cgi-bin/getsynop?block={STATION}&begin={begin}&end={end}"

    # Сначала пробуем напрямую (в Actions обычно работает)
    try:
        text = retry(lambda: http_get(url, timeout=15))
        if text and STATION in text:
            return text
    except Exception as e:
        log.debug("  Direct ogimet failed: %s", e)

    # Прокси
    for proxy in OGIMET_PROXIES:
        try:
            purl = proxy + quote(url, safe="")
            text = retry(lambda: http_get(purl, timeout=20))
            if text and STATION in text:
                return text
        except Exception as e:
            log.debug("  Proxy %s failed: %s", proxy, e)

    return None


def parse_synop_line(raw_line):
    """
    Парсит одну строку вида:
      33837,YYYY,MM,DD,HH,mm,AAXX ...телеграмма...
    Возвращает dict или None.
    """
    m = raw_line.strip()
    # Формат: SSSSS,YYYY,MM,DD,HH,mm,AAXX...
    parts = m.split(",", 6)
    if len(parts) < 7:
        return None
    st, y, mo, dd, hh, mm, telegram = parts
    if st != STATION:
        return None
    if "NILL" in telegram:
        return None
    hour = int(hh)
    if hour not in SYNOP_HOURS:
        return None

    synop_time = f"{y}{mo}{dd}{hh}{mm}"

    toks = telegram.split()
    # Находим секцию 333 — останавливаемся перед ней
    try:
        sec333 = toks.index("333")
    except ValueError:
        sec333 = len(toks)
    main = toks[:sec333]

    # iRIXhVV (индекс 3 от AAXX)
    aaxi = 0
    try:
        aaxi = toks.index("AAXX")
    except ValueError:
        pass

    visibility = None
    iR = None
    grp3 = main[aaxi + 3] if len(main) > aaxi + 3 else ""
    if len(grp3) == 5 and grp3[3:5].isdigit():
        iR = int(grp3[0]) if grp3[0].isdigit() else None
        vv = int(grp3[3:5])
        if vv <= 50:
            visibility = vv * 100
        elif vv <= 80:
            visibility = (vv - 50) * 1000
        elif vv == 89:
            visibility = 70000

    # Nddff (индекс 4)
    cloudcover = wind_dir = wind = None
    grp4 = main[aaxi + 4] if len(main) > aaxi + 4 else ""
    if len(grp4) == 5 and grp4.isdigit():
        N = int(grp4[0])
        cloudcover = round(N / 8 * 100) if N <= 8 else None
        wind_dir   = int(grp4[1:3]) * 10
        wind       = int(grp4[3:5])
        if math.isnan(wind_dir): wind_dir = None
        if math.isnan(wind):     wind     = None

    temp = dew = pressure = precip = ww = None
    for g in main[aaxi + 5:]:
        g = g.rstrip("=")
        if len(g) != 5:
            continue
        if g[0] == "1" and g[1] in "01" and g[2:].isdigit():
            temp = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        elif g[0] == "2" and g[1] in "01" and g[2:].isdigit():
            dew = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        elif g[0] == "4" and g[1:].isdigit():
            val = int(g[1:]) / 10
            pressure = (1000 + val) if val < 500 else (900 + val)
            if not (920 < pressure < 1050):
                pressure = None
        elif g[0] == "6" and g[1:4].isdigit() and iR in (0, 1, 2):
            rrr = int(g[1:4])
            precip = 0 if rrr in (0, 990) else (rrr - 990) * 0.1 if rrr >= 991 else rrr
        elif g[0] == "7" and g[1:3].isdigit():
            ww = int(g[1:3])

    if temp is None:
        return None

    humidity = None
    if temp is not None and dew is not None:
        try:
            humidity = round(100 * math.exp((17.625*dew)/(243.04+dew))
                             / math.exp((17.625*temp)/(243.04+temp)))
        except Exception:
            pass

    txt_line = f"{STATION},{y},{mo},{dd},{hh},{mm},{telegram}"
    return {
        "synopTime": synop_time,
        "txtLine":   txt_line,
        "obs": {
            "synopTime":  synop_time,
            "temp":       temp,
            "pressure":   pressure,
            "wind":       wind,
            "windDir":    wind_dir,
            "cloudcover": cloudcover,
            "precip":     precip,
            "ww":         ww,
            "visibility": visibility,
            "dew":        dew,
            "humidity":   humidity,
            "synop":      telegram,
        }
    }


def parse_synop_text(text):
    results = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = parse_synop_line(line)
        if rec and rec["synopTime"] not in seen:
            seen.add(rec["synopTime"])
            results.append(rec)
    return results

# ════════════════════════════════════════════════════════════════════════════
# 2. Open-Meteo: исторические прогнозы (для modelData)
# ════════════════════════════════════════════════════════════════════════════

MODEL_FIELDS = (
    "temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,cloud_cover,precipitation,weather_code,"
    "visibility,dew_point_2m"
)

def fetch_historical_model(model_id, date_str):
    """Возвращает hourly dict для одной модели за один день."""
    url = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={MODEL_FIELDS}"
        f"&models={model_id}"
        f"&start_date={date_str}&end_date={date_str}"
        "&timezone=UTC&wind_speed_unit=ms"
    )
    data = retry(lambda: http_get_json(url, timeout=25), attempts=3, delay=10)
    return data.get("hourly")


def build_model_record(synop_rec, hourly_by_model):
    """Собирает одну запись modelData из SYNOP + прогнозов моделей."""
    tk = synop_rec["synopTime"]
    target = f"{tk[:4]}-{tk[4:6]}-{tk[6:8]}T{tk[8:10]}:00"

    # Ищем индекс часа
    time_arr = None
    for h in hourly_by_model.values():
        if h:
            time_arr = h.get("time", [])
            break
    if not time_arr:
        return None
    try:
        hi = next(i for i, t in enumerate(time_arr) if t.startswith(target))
    except StopIteration:
        return None

    models_data = {}
    for mid, h in hourly_by_model.items():
        if not h:
            continue
        def v(field):
            arr = h.get(field)
            return arr[hi] if arr and hi < len(arr) else None
        wd = v("wind_direction_10m")
        models_data[mid] = {
            "temp":        v("temperature_2m"),
            "pressure":    v("pressure_msl"),
            "wind":        v("wind_speed_10m"),
            "windDir":     round(wd / 10) * 10 if wd is not None else None,
            "gusts":       v("wind_gusts_10m"),
            "cloudcover":  v("cloud_cover"),
            "precip":      v("precipitation"),
            "weatherCode": v("weather_code"),
            "visibility":  v("visibility"),
            "dewPoint":    v("dew_point_2m"),
            "temp850":     None,
        }

    return {
        "synopTime":    tk,
        "forecastHour": None,
        "obs":          synop_rec["obs"],
        "models":       models_data,
    }

# ════════════════════════════════════════════════════════════════════════════
# 3. Open-Meteo: свежий ансамблевый прогноз (для снимков)
# ════════════════════════════════════════════════════════════════════════════

def fetch_ensemble_ready_time():
    """Возвращает datetime готовности последнего прогона или None."""
    times = []
    for m in ENSEMBLE_MODELS:
        if not m["metaId"]:
            continue
        try:
            url  = f"https://api.open-meteo.com/data/{m['metaId']}/static/meta.json"
            data = http_get_json(url, timeout=10)
            ts   = data.get("last_run_availability_time")
            if ts:
                times.append(int(ts))
        except Exception:
            pass
    if not times:
        return None
    ready_ts = max(times)
    return datetime.fromtimestamp(ready_ts, tz=timezone.utc)


def fetch_forecast_model(model_id, days=16):
    """Текущий прогноз одной модели на days суток."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&models={model_id}"
        f"&timezone=UTC&forecast_days={days}&wind_speed_unit=ms"
    )
    data = retry(lambda: http_get_json(url, timeout=25), attempts=3, delay=10)
    return data.get("hourly")


def parse_hourly(h):
    """Преобразует hourly dict в список часовых объектов."""
    times = h.get("time", [])
    def v(field, i):
        arr = h.get(field)
        return arr[i] if arr and i < len(arr) else None
    result = []
    for i, t in enumerate(times):
        result.append({
            "time":                 t,
            "temperature_2m":       v("temperature_2m", i),
            "apparent_temperature": v("apparent_temperature", i),
            "pressure_msl":         v("pressure_msl", i),
            "relative_humidity_2m": v("relative_humidity_2m", i),
            "weather_code":         v("weather_code", i),
            "visibility":           v("visibility", i),
            "wind_speed_10m":       v("wind_speed_10m", i),
            "wind_gusts_10m":       v("wind_gusts_10m", i),
            "wind_direction_10m":   v("wind_direction_10m", i),
            "rain":                 v("precipitation", i) or 0,
            "showers":              v("showers", i) or 0,
            "precip_prob":          v("precipitation_probability", i),
            "snowfall":             v("snowfall", i),
            "snow_depth":           v("snow_depth", i),
            "shortwave_radiation":  v("shortwave_radiation", i),
            "direct_radiation":     v("direct_radiation", i),
            "diffuse_radiation":    v("diffuse_radiation", i),
            "dew_point_2m":         v("dew_point_2m", i),
            "runoff":               v("runoff", i),
            "cloud_cover":          v("cloud_cover", i),
            "cloud_cover_low":      v("cloud_cover_low", i),
            "cloud_cover_mid":      v("cloud_cover_mid", i),
            "cloud_cover_high":     v("cloud_cover_high", i),
        })
    return result


def merge_ensemble(all_model_hours, succeeded):
    """Смешивает прогнозы моделей в ансамбль (равные веса)."""
    if not succeeded:
        return []
    base = all_model_hours[succeeded[0]]
    numeric = [
        "temperature_2m","apparent_temperature","pressure_msl","relative_humidity_2m",
        "wind_speed_10m","wind_gusts_10m","rain","showers","precip_prob","snowfall",
        "snow_depth","cloud_cover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
        "shortwave_radiation","dew_point_2m","visibility",
    ]
    result = []
    w = 1 / len(succeeded)
    for i, bh in enumerate(base):
        merged = {"time": bh["time"]}
        for f in numeric:
            vals = [all_model_hours[m][i][f] for m in succeeded
                    if all_model_hours[m] and i < len(all_model_hours[m])
                    and all_model_hours[m][i][f] is not None]
            merged[f] = sum(vals) / len(vals) if vals else None
        # Направление ветра — векторное среднее
        sx = sy = 0
        for m in succeeded:
            mh = all_model_hours[m]
            if mh and i < len(mh) and mh[i]["wind_direction_10m"] is not None:
                rad = mh[i]["wind_direction_10m"] * math.pi / 180
                sx += math.sin(rad)
                sy += math.cos(rad)
        merged["wind_direction_10m"] = (math.degrees(math.atan2(sx, sy)) + 360) % 360 if (sx or sy) else None
        # weather_code — мажоритарный
        codes = {}
        for m in succeeded:
            mh = all_model_hours[m]
            c = mh[i]["weather_code"] if mh and i < len(mh) else None
            if c is not None:
                codes[c] = codes.get(c, 0) + 1
        merged["weather_code"] = max(codes, key=codes.get) if codes else 0
        result.append(merged)
    return result


def apply_bias(value, key, bias_dict):
    """Вычитает bias из значения прогноза. windDir не корректируем."""
    if value is None or key == "windDir":
        return value
    b = (bias_dict.get(key) or {}).get("bias")
    if b is None:
        return value
    return round((value - b) * 10) / 10


def build_snapshot(ensemble_hours, saved_at, run_time, mode="synop", bias=None):
    """Формирует снимок в формате совместимом с forecast.html."""
    hours_out = []
    snap_dt = parse_iso(saved_at)

    for h in ensemble_hours:
        t_str = h["time"] if "T" in h["time"] else h["time"].replace(" ", "T") + ":00"
        t_dt  = parse_iso(t_str)
        horizon_h = (t_dt - snap_dt).total_seconds() / 3600

        if mode == "synop":
            # Только синоптические часы и первые 4 дня
            if int(t_str[11:13]) not in {0, 3, 6, 9, 12, 15, 18, 21}:
                continue
            if horizon_h > 96:
                break
            hours_out.append({
                "time":        h["time"],
                "temp":        round(h["temperature_2m"] * 10) / 10 if h["temperature_2m"] is not None else None,
                "pressure":    round(h["pressure_msl"] * 10) / 10 if h["pressure_msl"] is not None else None,
                "wind":        round(h["wind_speed_10m"] * 10) / 10 if h["wind_speed_10m"] is not None else None,
                "windGust":    round((h["wind_gusts_10m"] or h["wind_speed_10m"] or 0) * 10) / 10,
                "windDir":     round(h["wind_direction_10m"]) if h["wind_direction_10m"] is not None else None,
                "humidity":    round(h["relative_humidity_2m"]) if h["relative_humidity_2m"] is not None else None,
                "rain":        round(h["rain"] * 10) / 10 if h["rain"] is not None else None,
                "cloudcover":  round(h["cloud_cover"]) if h["cloud_cover"] is not None else None,
                "weatherCode": h["weather_code"],
            })
        else:  # pws — каждый час, первые 4 дня
            if horizon_h > 96:
                break
            b = bias or {}
            hours_out.append({
                "time":     h["time"],
                "temp":     apply_bias(round(h["temperature_2m"] * 10) / 10 if h["temperature_2m"] is not None else None, "temp", b),
                "pressure": apply_bias(round(h["pressure_msl"] * 10) / 10 if h["pressure_msl"] is not None else None, "pressure", b),
                "wind":     apply_bias(round(h["wind_speed_10m"] * 10) / 10 if h["wind_speed_10m"] is not None else None, "wind", b),
                "windGust": apply_bias(round((h["wind_gusts_10m"] or h["wind_speed_10m"] or 0) * 10) / 10, "windGust", b),
                "windDir":  round(h["wind_direction_10m"]) if h["wind_direction_10m"] is not None else None,
                "humidity": apply_bias(round(h["relative_humidity_2m"]) if h["relative_humidity_2m"] is not None else None, "humidity", b),
                "rain":     round(h["rain"] * 10) / 10 if h["rain"] is not None else None,
            })

    return {
        "savedAt": saved_at,
        "runTime": run_time,
        "hours":   hours_out,
    }

# ════════════════════════════════════════════════════════════════════════════
# 4. Выжимка снимков → ensemble_accuracy.json
# ════════════════════════════════════════════════════════════════════════════

# Числовые параметры: (поле в снимке, поле в наблюдении)
PARAM_MAP = {
    "temp":       ("temp",       "temp"),
    "pressure":   ("pressure",   "pressure"),
    "wind":       ("wind",       "wind"),
    "windDir":    ("windDir",    "windDir"),
    "humidity":   ("humidity",   "humidity"),
    "cloudcover": ("cloudcover", "cloudcover"),
    "precip":     ("rain",       "precip"),       # прогноз: rain, набл: precip
    "visibility": ("visibility", "visibility"),
}

# Для совместимости с update_accuracy (список числовых параметров)
ACCURACY_PARAMS = list(PARAM_MAP.keys())


def wmo_group(code):
    """Группа явлений по WMO weather_code (Open-Meteo)."""
    if code is None: return None
    if code <= 1:           return "clear"
    if code <= 3:           return "cloudy"
    if code in (45, 48):    return "fog"
    if 51 <= code <= 67:    return "rain"
    if 71 <= code <= 77:    return "snow"
    if 80 <= code <= 94:    return "shower"
    if code >= 95:          return "thunder"
    return "cloudy"


def synop_group(ww):
    """Группа явлений по SYNOP ww."""
    if ww is None: return None
    if ww <= 1:           return "clear"
    if ww <= 39:          return "cloudy"
    if 40 <= ww <= 49:    return "fog"
    if 50 <= ww <= 69:    return "rain"
    if 70 <= ww <= 79:    return "snow"
    if 80 <= ww <= 90:    return "shower"
    if 91 <= ww <= 99:    return "thunder"
    return None


def angle_diff(a, b):
    """Минимальная разница углов в градусах."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def calc_errors(forecast_val, obs_val, param):
    """Возвращает (error, abs_error) или None если нет данных."""
    if forecast_val is None or obs_val is None:
        return None
    if param == "windDir":
        err = angle_diff(forecast_val, obs_val)
        return err, err
    err = forecast_val - obs_val
    return err, abs(err)


def squeeze_snapshots(snaps, obs_by_time, mode="synop"):
    """
    Выжимает снимки:
    - считает ошибки для часов у которых есть наблюдения
    - возвращает (accuracy_records, remaining_snaps)
      remaining_snaps — те что ещё не истекли (последний час в будущем)
    """
    now = utcnow()
    accuracy_records = []   # список {savedAt, dayKey, horizonH, param→error}
    remaining = []

    for snap in snaps:
        saved_at = parse_iso(snap["savedAt"])
        hours    = snap.get("hours", [])
        if not hours:
            continue

        # Проверяем истёк ли снимок
        last_hour_str = hours[-1]["time"]
        last_hour_dt  = parse_iso(last_hour_str.replace(" ", "T") + ":00" if "T" not in last_hour_str else last_hour_str)
        expired = (now - saved_at).total_seconds() > 96 * 3600

        # Выжимаем часы у которых есть наблюдения
        for h in hours:
            t_str = h["time"] if "T" in h["time"] else h["time"].replace(" ", "T") + ":00"
            t_dt  = parse_iso(t_str)
            if t_dt >= now:
                break  # остальные ещё не прошли

            # Ключ наблюдения для SYNOP: YYYYMMDDHH00
            obs_key = t_dt.strftime("%Y%m%d%H00")
            obs = obs_by_time.get(obs_key)
            if obs is None:
                continue

            horizon_h = round((t_dt - saved_at).total_seconds() / 3600)
            day_key   = t_dt.strftime("%Y-%m-%d")

            rec = {
                "savedAt":  snap["savedAt"],
                "dayKey":   day_key,
                "horizonH": horizon_h,
            }
            # Числовые параметры через маппинг прогнозного поля → наблюдательного
            for param, (fc_field, obs_field) in PARAM_MAP.items():
                obs_val = obs.get(obs_field)
                fc_val  = h.get(fc_field)
                err = calc_errors(fc_val, obs_val, param)
                if err is not None:
                    rec[param] = {"err": round(err[0], 2), "ae": round(err[1], 2)}
            # Явления погоды — категориальные (hits/total)
            fc_wmo = h.get("weatherCode")
            obs_ww = obs.get("ww")
            if fc_wmo is not None and obs_ww is not None:
                fg = wmo_group(fc_wmo)
                og = synop_group(obs_ww)
                if fg is not None and og is not None:
                    rec["wx"] = {"hit": 1 if fg == og else 0}
            accuracy_records.append(rec)

        if not expired:
            remaining.append(snap)
        else:
            log.info("  Удалён снимок %s (%d часов)", snap["savedAt"][:16], len(hours))

    return accuracy_records, remaining


def update_accuracy(existing_acc, new_records, mode="synop"):
    """
    Обновляет ensemble_accuracy.json новыми записями.
    Структура:
    {
      "updated": "...",
      "overall":  {param: {mae, rmse, bias, n}},
      "byDay":    {dayKey: {param: {mae, rmse, bias, n}}},
      "byHorizon":{str(h): {param: {mae, rmse, bias, n}}}
    }
    """
    # Собираем все записи: существующие raw + новые
    # Для экономии места храним агрегированные данные, не сырые записи
    acc = existing_acc or {"updated": None, "overall": {}, "byDay": {}, "byHorizon": {}, "wx": {"hits": 0, "total": 0}, "wxByDay": {}}

    def add_to_bucket(bucket, key, param, ae, err):
        if key not in bucket:
            bucket[key] = {}
        if param not in bucket[key]:
            bucket[key][param] = {"sum_ae": 0, "sum_sq": 0, "sum_err": 0, "n": 0}
        b = bucket[key][param]
        b["sum_ae"]  += ae
        b["sum_sq"]  += ae * ae
        b["sum_err"] += err
        b["n"]       += 1

    def add_to_overall(bucket, param, ae, err):
        if param not in bucket:
            bucket[param] = {"sum_ae": 0, "sum_sq": 0, "sum_err": 0, "n": 0}
        b = bucket[param]
        b["sum_ae"]  += ae
        b["sum_sq"]  += ae * ae
        b["sum_err"] += err
        b["n"]       += 1

    # Восстанавливаем суммы из хранимых агрегатов если они есть
    # (при первом запуске overall хранит mae/rmse/bias — переконвертируем)
    def ensure_sums(bucket_dict):
        for key, params in bucket_dict.items():
            for param, stats in params.items():
                if "sum_ae" not in stats and "mae" in stats:
                    n = stats.get("n", 0)
                    stats["sum_ae"]  = stats["mae"] * n
                    stats["sum_sq"]  = (stats.get("rmse", 0) ** 2) * n
                    stats["sum_err"] = stats.get("bias", 0) * n

    ensure_sums(acc.get("byDay", {}))
    ensure_sums(acc.get("byHorizon", {}))
    if "overall" in acc:
        ensure_sums({"_": acc["overall"]})

    overall    = acc.setdefault("overall", {})
    by_day     = acc.setdefault("byDay", {})
    by_horizon = acc.setdefault("byHorizon", {})

    wx_overall = acc.setdefault("wx", {"hits": 0, "total": 0})
    wx_by_day  = acc.setdefault("wxByDay", {})

    for rec in new_records:
        day_key   = rec["dayKey"]
        horizon_h = str(rec["horizonH"])
        for param in ACCURACY_PARAMS:
            if param not in rec:
                continue
            ae  = rec[param]["ae"]
            err = rec[param]["err"]
            add_to_overall(overall, param, ae, err)
            add_to_bucket(by_day,     day_key,   param, ae, err)
            add_to_bucket(by_horizon, horizon_h, param, ae, err)
        # Явления погоды
        if "wx" in rec:
            wx_overall["hits"]  += rec["wx"]["hit"]
            wx_overall["total"] += 1
            if day_key not in wx_by_day:
                wx_by_day[day_key] = {"hits": 0, "total": 0}
            wx_by_day[day_key]["hits"]  += rec["wx"]["hit"]
            wx_by_day[day_key]["total"] += 1

    # Финализируем — вычисляем MAE/RMSE/bias из накопленных сумм
    def finalize(bucket_dict):
        result = {}
        for key, params in bucket_dict.items():
            result[key] = {}
            for param, s in params.items():
                n = s.get("n", 0)
                if n == 0:
                    continue
                result[key][param] = {
                    "mae":  round(s["sum_ae"]  / n, 3),
                    "rmse": round(math.sqrt(s["sum_sq"] / n), 3),
                    "bias": round(s["sum_err"] / n, 3),
                    "n":    n,
                    # Сохраняем суммы для будущего пополнения
                    "sum_ae":  round(s["sum_ae"], 4),
                    "sum_sq":  round(s["sum_sq"], 4),
                    "sum_err": round(s["sum_err"], 4),
                }
        return result

    # Финализируем overall отдельно
    overall_final = {}
    for param, s in overall.items():
        n = s.get("n", 0)
        if n == 0:
            continue
        overall_final[param] = {
            "mae":     round(s["sum_ae"] / n, 3),
            "rmse":    round(math.sqrt(s["sum_sq"] / n), 3),
            "bias":    round(s["sum_err"] / n, 3),
            "n":       n,
            "sum_ae":  round(s["sum_ae"], 4),
            "sum_sq":  round(s["sum_sq"], 4),
            "sum_err": round(s["sum_err"], 4),
        }

    # Финализируем wx: добавляем pct
    wx_final = {
        "hits":  wx_overall.get("hits", 0),
        "total": wx_overall.get("total", 0),
    }
    if wx_final["total"] > 0:
        wx_final["pct"] = round(wx_final["hits"] / wx_final["total"] * 100)

    wx_by_day_final = {}
    for dk, w in wx_by_day.items():
        wx_by_day_final[dk] = {
            "hits": w["hits"], "total": w["total"],
            "pct": round(w["hits"] / w["total"] * 100) if w["total"] > 0 else 0,
        }

    return {
        "updated":   utcnow().isoformat(),
        "overall":   overall_final,
        "byDay":     finalize(by_day),
        "byHorizon": finalize(by_horizon),
        "wx":        wx_final,
        "wxByDay":   wx_by_day_final,
    }

# ════════════════════════════════════════════════════════════════════════════
# 5. model_weights.json — пересчёт
# ════════════════════════════════════════════════════════════════════════════

WEIGHT_PARAMS = {
    "temp":       ["temp"],
    "pressure":   ["pressure"],
    "wind":       ["wind"],
    "windDir":    ["windDir"],
    "cloudcover": ["cloudcover"],
    "precip":     ["rain"],
}

SEASON_MAP = {12: "DJF", 1: "DJF", 2: "DJF",
              3: "MAM", 4: "MAM", 5: "MAM",
              6: "JJA", 7: "JJA", 8: "JJA",
              9: "SON", 10: "SON", 11: "SON"}

def get_season(year, month):
    s = SEASON_MAP[month]
    sy = year + 1 if month == 12 else year
    return s, f"{sy}-{s}"

def compute_mae_per_model(model_data_list):
    """
    Из списка записей modelData считает MAE каждой модели по параметрам.
    Возвращает {model_id: {param: {mae, n}}}
    """
    # {model: {param: [abs_errors]}}
    errs = {}
    obs_fields = {"temp": "temp", "pressure": "pressure", "wind": "wind",
                  "windDir": "windDir", "cloudcover": "cloudcover", "precip": "precip"}

    for rec in model_data_list:
        obs = rec.get("obs", {})
        for mid, mdata in rec.get("models", {}).items():
            if mid not in errs:
                errs[mid] = {p: [] for p in obs_fields}
            for param, obs_key in obs_fields.items():
                ov = obs.get(obs_key)
                mv = mdata.get("temp" if param == "temp" else
                               "pressure" if param == "pressure" else
                               "wind" if param == "wind" else
                               "windDir" if param == "windDir" else
                               "cloudcover" if param == "cloudcover" else
                               "precip")
                if ov is None or mv is None:
                    continue
                ae = angle_diff(mv, ov) if param == "windDir" else abs(mv - ov)
                errs[mid][param].append(ae)

    result = {}
    for mid, params in errs.items():
        result[mid] = {}
        for param, vals in params.items():
            if vals:
                result[mid][param] = {"mae": round(sum(vals)/len(vals), 4), "n": len(vals)}
    return result


def top3_for_param(model_mae, param, all_models):
    """Возвращает список [{model, mae}] топ-3 по MAE для параметра."""
    scored = []
    for mid in all_models:
        if mid in model_mae and param in model_mae[mid]:
            scored.append({"model": mid, "mae": model_mae[mid][param]["mae"]})
    scored.sort(key=lambda x: x["mae"])
    return scored[:3]


def build_weights_from_modeldata(all_records):
    """
    Строит model_weights.json из списка всех записей modelData.
    Скользящее окно: seasonal/monthly — последние 3 года.
    allSeasons/allMonths — всё что есть.
    """
    now   = utcnow()
    cutoff_3y = now - timedelta(days=3*365)

    # Группируем записи
    groups = {
        "allSeasons": {},   # season → [records]
        "allMonths":  {},   # mm → [records]
        "seasonal":   {},   # YYYY-SSS → [records]
        "monthly":    {},   # YYYY-MM → [records]
    }

    days_set = set()

    for rec in all_records:
        st   = rec.get("synopTime", "")
        if len(st) < 10:
            continue
        try:
            y, mo = int(st[:4]), int(st[4:6])
            dt = datetime(y, mo, int(st[6:8]), tzinfo=timezone.utc)
        except Exception:
            continue
        days_set.add(st[:8])
        season, season_key = get_season(y, mo)
        month_key = f"{y}-{st[4:6]}"
        month_num = st[4:6]

        groups["allSeasons"].setdefault(season, []).append(rec)
        groups["allMonths"].setdefault(month_num, []).append(rec)
        if dt >= cutoff_3y:
            groups["seasonal"].setdefault(season_key, []).append(rec)
            groups["monthly"].setdefault(month_key, []).append(rec)

    all_model_ids = list({mid for rec in all_records for mid in rec.get("models", {})})

    def make_section(period_groups):
        section = {}
        for period_key, recs in period_groups.items():
            model_mae = compute_mae_per_model(recs)
            section[period_key] = {}
            for param in ["temp","pressure","wind","windDir","cloudcover","precip","phenomena"]:
                if param == "phenomena":
                    section[period_key][param] = []
                    continue
                section[period_key][param] = top3_for_param(model_mae, param, all_model_ids)
        return section

    days_sorted = sorted(days_set)
    return {
        "updated":    now.isoformat(),
        "coverage": {
            "from":    days_sorted[0]  if days_sorted else None,
            "to":      days_sorted[-1] if days_sorted else None,
            "days":    len(days_sorted),
            "records": len(all_records),
        },
        "allSeasons":  make_section(groups["allSeasons"]),
        "allMonths":   make_section(groups["allMonths"]),
        "seasonal":    make_section(groups["seasonal"]),
        "monthly":     make_section(groups["monthly"]),
    }

# ════════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ════════════════════════════════════════════════════════════════════════════

def main():
    now  = utcnow()
    year = now.year
    _gist_lines.clear()
    log.info("GIST_ID=%s GIST_TOKEN_present=%s", GIST_ID, bool(GIST_TOKEN))
    gist_log(f"=== update.py запущен {now.strftime('%H:%M:%S')} UTC ===")

    # ── 1. Загружаем synop_YYYY.txt с GitHub ────────────────────────────────
    gist_log("--- 1. SYNOP ---")
    synop_path = f"data/synop_{year}.txt"
    synop_text, synop_sha = gh_get(synop_path)
    synop_text = synop_text or ""

    # Существующие ключи
    existing_synop_keys = set()
    synop_obs_by_time   = {}  # synopTime → obs dict (для выжимки снимков)
    for line in synop_text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = parse_synop_line(line)
        if rec:
            existing_synop_keys.add(rec["synopTime"])
            synop_obs_by_time[rec["synopTime"]] = rec["obs"]

    # Определяем дату последней записи
    if existing_synop_keys:
        last_key = max(existing_synop_keys)
        last_dt  = datetime(int(last_key[:4]), int(last_key[4:6]), int(last_key[6:8]),
                            tzinfo=timezone.utc)
        start_dt = last_dt
    else:
        start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)

    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0)

    new_synop_lines  = []
    new_synop_parsed = []

    day = start_dt
    while day <= yesterday:
        date_str = day.strftime("%Y-%m-%d")
        log.info("  SYNOP %s ...", date_str)
        text = fetch_synop_ogimet(day)
        if text:
            parsed = parse_synop_text(text)
            for rec in parsed:
                if rec["synopTime"] not in existing_synop_keys:
                    new_synop_lines.append(rec["txtLine"])
                    new_synop_parsed.append(rec)
                    existing_synop_keys.add(rec["synopTime"])
                    synop_obs_by_time[rec["synopTime"]] = rec["obs"]
            log.info("    → %d новых сводок", len([r for r in parsed
                                                    if r["synopTime"] in existing_synop_keys]))
        else:
            log.warning("    → SYNOP недоступен")
        time.sleep(2)
        day += timedelta(days=1)

    if new_synop_lines:
        merged_txt = synop_text.rstrip() + "\n" + "\n".join(new_synop_lines) + "\n"
        synop_sha  = gh_put(synop_path, merged_txt, synop_sha,
                            f"synop {year}: +{len(new_synop_lines)} lines")
        log.info("  ✓ synop_%d.txt сохранён (+%d строк)", year, len(new_synop_lines))
    else:
        log.info("  synop_%d.txt актуален", year)

    # ── 2. Дописываем modelData в месячные файлы ────────────────────────────
    gist_log("--- 2. modelData ---")

    # Группируем новые сводки по месяцам
    by_month = {}
    for rec in new_synop_parsed:
        mk = f"modelData_{rec['synopTime'][:4]}_{rec['synopTime'][4:6]}"  # modelData_2026_05   
        by_month.setdefault(mk, []).append(rec)

    if not by_month:
        log.info("  modelData актуален")
    else:
        for mk, recs in sorted(by_month.items()):
            md_path = f"data/modeldata/{mk}.json"
            month_data, md_sha = gh_load_json(md_path, default=[])
            existing_md_keys = {r["synopTime"] for r in month_data}
            to_add = [r for r in recs if r["synopTime"] not in existing_md_keys]

            if not to_add:
                log.info("  %s.json актуален", mk)
                continue

            log.info("  %s.json: загружаем прогнозы для %d сводок...", mk, len(to_add))
            by_date = {}
            for rec in to_add:
                dk = f"{rec['synopTime'][:4]}-{rec['synopTime'][4:6]}-{rec['synopTime'][6:8]}"
                by_date.setdefault(dk, []).append(rec)

            new_md_records = []
            for date_str, date_recs in by_date.items():
                log.info("  Модели за %s ...", date_str)
                hourly_by_model = {}
                for mid in [m["id"] for m in ENSEMBLE_MODELS]:
                    try:
                        h = fetch_historical_model(mid, date_str)
                        hourly_by_model[mid] = h
                        time.sleep(0.5)
                    except Exception as e:
                        log.warning("    ✗ %s: %s", mid, e)
                        hourly_by_model[mid] = None
                for rec in date_recs:
                    md_rec = build_model_record(rec, hourly_by_model)
                    if md_rec:
                        new_md_records.append(md_rec)

            if new_md_records:
                merged = sorted(month_data + new_md_records, key=lambda r: r["synopTime"])
                md_sha = gh_save_json(md_path, merged, md_sha,
                                      f"modelData {mk}: +{len(new_md_records)} records")
                log.info("  ✓ %s.json сохранён (+%d записей)", mk, len(new_md_records))

    # ── 3. Свежий ансамблевый прогноз → снимки ──────────────────────────────
    gist_log("--- 3. Ансамблевый прогноз ---")

    ensemble_ready_time = fetch_ensemble_ready_time()
    gist_log(f"  Время готовности ансамбля: {ensemble_ready_time.isoformat() if ensemble_ready_time else 'неизвестно'}")

    snap_synop_path = "data/ensemble_snapshots_synop.json"
    snap_pws_path   = "data/ensemble_snapshots_pws.json"
    snaps_synop, snaps_synop_sha = gh_load_json(snap_synop_path, default=[])
    snaps_pws,   snaps_pws_sha   = gh_load_json(snap_pws_path,   default=[])
    acc_pws_for_bias, _ = gh_load_json("data/ensemble_accuracy_pws.json", default=None)
    pws_bias = (acc_pws_for_bias or {}).get("overall", {})

    # Проверяем нужен ли новый снимок
    last_synop_run = parse_iso(snaps_synop[-1]["runTime"]) if snaps_synop and snaps_synop[-1].get("runTime") else None
    last_pws_run   = parse_iso(snaps_pws[-1]["runTime"])   if snaps_pws   and snaps_pws[-1].get("runTime")   else None

    need_synop = ensemble_ready_time is not None and (not last_synop_run or last_synop_run < ensemble_ready_time)
    need_pws   = ensemble_ready_time is not None and (not last_pws_run   or last_pws_run   < ensemble_ready_time)

    if need_synop or need_pws:
        log.info("  Загружаем прогнозы моделей...")
        all_model_hours = {}
        succeeded = []
        for m in ENSEMBLE_MODELS:
            try:
                h = fetch_forecast_model(m["id"], days=16)
                if h:
                    all_model_hours[m["id"]] = parse_hourly(h)
                    succeeded.append(m["id"])
                    log.info("    ✓ %s", m["id"])
            except Exception as e:
                log.warning("    ✗ %s: %s", m["id"], e)
            time.sleep(0.5)

        if succeeded:
            ensemble_hours = merge_ensemble(all_model_hours, succeeded)
            saved_at  = now.isoformat()
            run_time  = ensemble_ready_time.isoformat() if ensemble_ready_time else None

            # SYNOP-снимок (только в синоптические часы UTC: 0,3,6,9,12,15,18,21)
            synop_hour = (now.hour // 3) * 3  # ближайший прошедший синоптический час
            last_run = snaps_synop[-1].get("runTime") if snaps_synop else None
            same_run = last_run and run_time and parse_iso(last_run) == parse_iso(run_time)
            if need_synop and (now.hour - synop_hour) <= 2 and not same_run:
                snap = build_snapshot(ensemble_hours, saved_at, run_time, mode="synop")
                snaps_synop.append(snap)
                snaps_synop_sha = gh_save_json(
    snap_synop_path, snaps_synop, snaps_synop_sha,
    f"ensemble synop snapshot {saved_at[:16]}", compact=True)
                log.info("  ✓ SYNOP-снимок сохранён (%d точек)", len(snap["hours"]))
            elif need_synop:
                log.info("  SYNOP-снимок пропущен (не синоптический час: %dh UTC)", now.hour)

            last_run_pws = snaps_pws[-1].get("runTime") if snaps_pws else None
            same_run_pws = last_run_pws and run_time and parse_iso(last_run_pws) == parse_iso(run_time)
            if need_pws and not same_run_pws:
                snap = build_snapshot(ensemble_hours, saved_at, run_time, mode="pws", bias=pws_bias)
                snaps_pws.append(snap)
                snaps_pws_sha = gh_save_json(
                    snap_pws_path, snaps_pws, snaps_pws_sha,
                    f"ensemble pws snapshot {saved_at[:16]}", compact=True)
                log.info("  ✓ PWS-снимок сохранён (%d часов)", len(ensemble_hours))
        else:
            log.warning("  Ни одна модель не ответила")
    else:
        gist_log("  Снимки актуальны")

    # ── 4. Выжимка снимков → ensemble_accuracy.json ─────────────────────────
    gist_log("--- 4. Выжимка снимков ---")

    acc_synop_path = "data/ensemble_accuracy_synop.json"
    acc_pws_path   = "data/ensemble_accuracy_pws.json"
    acc_synop, acc_synop_sha = gh_load_json(acc_synop_path, default=None)
    acc_pws,   acc_pws_sha   = gh_load_json(acc_pws_path,   default=None)

    # Наблюдения SYNOP для верификации
    new_recs_synop, remaining_synop = squeeze_snapshots(snaps_synop, synop_obs_by_time, mode="synop")
    gist_log(f"  SYNOP: выжато {len(new_recs_synop)} записей, осталось {len(remaining_synop)} снимков")

    if new_recs_synop:
        acc_synop = update_accuracy(acc_synop, new_recs_synop, mode="synop")
        acc_synop_sha = gh_save_json(acc_synop_path, acc_synop, acc_synop_sha,
                                     "ensemble accuracy synop update")
        log.info("  ✓ ensemble_accuracy_synop.json обновлён")

    if len(remaining_synop) < len(snaps_synop):
        snaps_synop_sha = gh_save_json(snap_synop_path, remaining_synop, snaps_synop_sha,
                               f"cleanup synop snapshots: {len(snaps_synop)-len(remaining_synop)} removed",
                               compact=True)
        log.info("  ✓ ensemble_snapshots_synop.json очищен")

    # PWS наблюдения для верификации — из pws_raw.json
    pws_raw, pws_raw_sha = gh_load_json("data/pws_raw.json", default=[])
    pws_obs_by_time = {}
    for rec in pws_raw:
        hk = rec.get("hourKey", "")   # формат: "2026-04-29T03"
        if hk:
            try:
                dt = datetime.strptime(hk, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
                obs_key = dt.strftime("%Y%m%d%H00")
                pws_obs_by_time[obs_key] = {
                    "temp":     rec.get("temp"),
                    "pressure": rec.get("pressure"),
                    "wind":     rec.get("wind"),
                    "windDir":  rec.get("windDir"),
                    "humidity": rec.get("humidity"),
                    "rain":     rec.get("precip"),
                }
            except Exception:
                pass

    new_recs_pws, remaining_pws = squeeze_snapshots(snaps_pws, pws_obs_by_time, mode="pws")
    gist_log(f"  PWS: выжато {len(new_recs_pws)} записей, осталось {len(remaining_pws)} снимков")

    if new_recs_pws:
        acc_pws = update_accuracy(acc_pws, new_recs_pws, mode="pws")
        acc_pws_sha = gh_save_json(acc_pws_path, acc_pws, acc_pws_sha,
                                   "ensemble accuracy pws update")
        log.info("  ✓ ensemble_accuracy_pws.json обновлён")

    if len(remaining_pws) < len(snaps_pws):
        snaps_pws_sha = gh_save_json(snap_pws_path, remaining_pws, snaps_pws_sha,
                                     f"cleanup pws snapshots: {len(snaps_pws)-len(remaining_pws)} removed")
        log.info("  ✓ ensemble_snapshots_pws.json очищен")

    # ── 5. Чистка pws_raw.json ──────────────────────────────────────────────
    gist_log("--- 5. Чистка pws_raw.json ---")
    cutoff_pws = now - timedelta(days=PWS_KEEP_DAYS)
    pws_before = len(pws_raw)
    pws_raw = [r for r in pws_raw
               if datetime.strptime(r["hourKey"], "%Y-%m-%dT%H").replace(tzinfo=timezone.utc) >= cutoff_pws]
    if len(pws_raw) < pws_before:
        pws_raw_sha = gh_save_json("data/pws_raw.json", pws_raw, pws_raw_sha,
                                   f"pws_raw cleanup: removed {pws_before-len(pws_raw)} old records")
        log.info("  ✓ Удалено %d старых записей PWS", pws_before - len(pws_raw))
    else:
        log.info("  pws_raw.json актуален (%d записей)", len(pws_raw))

    # ── 6. model_weights.json ───────────────────────────────────────────────
    gist_log("--- 6. model_weights.json ---")
    gist_log("  Пересчёт весов выполняется через calc_weights.yml (ежедневно)")

    gist_log("=== Готово ===")


if __name__ == "__main__":
    main()
