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

import open_meteo_guard as _om_guard
import open_meteo_request_log as _om_log

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
    {"id": "icon_global",                    "metaId": "dwd_icon"},
    {"id": "ukmo_global_deterministic_10km", "metaId": "ukmo_global_deterministic_10km"},
    {"id": "meteofrance_arpege_europe",      "metaId": "meteofrance_arpege_europe"},
    {"id": "gfs_global",                     "metaId": "ncep_gfs013"},
    {"id": "gem_global",                     "metaId": "cmc_gem_gdps"},
    {"id": "cma_grapes_global",              "metaId": "cma_grapes_global"},
]

# [ДОБАВЛЕНО 2026-09-12, OPEN_METEO_PER_MODEL_UPDATE_ARCHITECTURE_001, GPT APPROVED]
MODEL_FORECAST_CACHE_PATH = "data/model_forecast_cache.json"


def load_forecast_cache():
    """Загружает data/model_forecast_cache.json. Формат:
    {"version": 1, "models": {model_id: {"source_run_time","fetched_at","hours"}}}."""
    cache, sha = gh_load_json(MODEL_FORECAST_CACHE_PATH, default={"version": 1, "models": {}})
    if not isinstance(cache, dict) or "models" not in cache:
        cache = {"version": 1, "models": {}}
    return cache, sha


def get_changed_models(history, cache):
    """Возвращает (changed_ids, run_time_by_id) — список model_id, чей
    run_time (из model_runs_history.json) ещё не совпадает с
    cache["models"][id]["source_run_time"], плюс карта id->run_time_iso
    (для тех моделей, где run_time вообще известен из history).

    Модель без записи в кэше — тоже "changed" (первый запуск / новая модель).
    Модель без label в _ID_TO_HISTORY_LABEL или без записей в history —
    в changed НЕ попадает автоматически: без сравнения не с чем; такие
    модели просто продолжают жить со старым кэшем, пока их run_time не
    появится в history (это не должно происходить для всех 8 моделей после
    расширения _ID_TO_HISTORY_LABEL — оставлено на случай будущей модели
    без due-tracking)."""
    cache_models = cache.get("models", {})
    changed = []
    run_time_by_id = {}
    for m in ENSEMBLE_MODELS:
        mid = m["id"]
        label = _ID_TO_HISTORY_LABEL.get(mid)
        run_time_iso = None
        if label:
            entries = (history or {}).get(label)
            if entries:
                run_time_iso = entries[-1].get("run_time")
        if run_time_iso:
            run_time_by_id[mid] = run_time_iso
        cached_entry = cache_models.get(mid)
        if cached_entry is None:
            changed.append(mid)  # нет в кэше вообще — нужен фетч (первый запуск)
        elif run_time_iso and run_time_iso != cached_entry.get("source_run_time"):
            changed.append(mid)
        # если run_time_iso неизвестен (нет label/history), но кэш уже есть —
        # не считаем changed: нечего сравнивать, используем то, что в кэше.
    return changed, run_time_by_id

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
MAX_PWS_SNAPS = 48    # ~2 суток при почасовом сборе, ≈ 720 КБ

# ── HTTP-утилиты ─────────────────────────────────────────────────────────────
def http_get(url, headers=None, timeout=40):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def http_get_json(url, headers=None, timeout=40):
    return json.loads(http_get(url, headers, timeout))

def retry(fn, attempts=3, delay=5, log_ctx=None):
    """[ИСПРАВЛЕНО 2026-09-12, GPT review OPEN_METEO_REQUEST_ARCHITECTURE_001,
    п. A2] HTTP 429 — НЕ временная ошибка, а сигнал общего circuit breaker
    (open_meteo_guard.py). Раньше retry() ловил 429 наравне с сетевыми
    сбоями и тратил все `attempts` попыток (с паузой `delay` между ними)
    ПРЕЖДЕ чем исключение доходило до вызывающего кода и guard.record_429()
    успевал сработать — то есть каждая модель, поймавшая 429, реально
    делала 3 запроса вместо 1, усиливая burst в 3 раза. Теперь 429
    пробрасывается немедленно, без ретрая; retry остаётся только для
    сетевых сбоев и остальных HTTP-ошибок.

    log_ctx (опционально) — dict(script=, function=, endpoint=, model=) для
    единого лога запросов (open_meteo_request_log.py, GPT review: "нужен
    единый счётчик/лог реальных HTTP-вызовов"). Логируется КАЖДАЯ попытка
    с её номером — это даёт видимость реального retry-усиления в логе."""
    for i in range(attempts):
        try:
            result = fn()
            if log_ctx:
                _om_log.log(log_ctx["script"], log_ctx["function"], log_ctx["endpoint"],
                            model=log_ctx.get("model"), status="ok", attempt=i + 1)
            return result
        except HTTPError as e:
            if log_ctx:
                _om_log.log(log_ctx["script"], log_ctx["function"], log_ctx["endpoint"],
                            model=log_ctx.get("model"),
                            status="429" if e.code == 429 else str(e.code), attempt=i + 1)
            if e.code == 429:
                raise
            if i == attempts - 1:
                raise
            log.warning("  Retry %d/%d after: %s", i+1, attempts, e)
            time.sleep(delay)
        except Exception as e:
            if log_ctx:
                _om_log.log(log_ctx["script"], log_ctx["function"], log_ctx.get("endpoint"),
                            model=log_ctx.get("model"), status=f"error:{e}", attempt=i + 1)
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
        text = http_get(dl_url, GH_HEADERS, timeout=60)
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



def gist_log(msg):
    log.info(msg)

def gist_log_save(label, fn, gh_path=None):
    result = fn()
    ts = datetime.now(timezone.utc).strftime("%H:%M")
    if gh_path:
        try:
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{gh_path}"
            info = http_get_json(url, GH_HEADERS, timeout=10)
            size_str = f" · {info.get('size', 0) / 1024:.1f} КБ"
        except Exception:
            size_str = ""
    else:
        size_str = ""
    gist_log(f"    [{ts}] {label}{size_str}")
    return result

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
            pressure = val if val >= 500 else (1000 + val)
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
    data = retry(lambda: http_get_json(url, timeout=25), attempts=3, delay=10,
                 log_ctx={"script": "update.py", "function": "fetch_historical_model",
                          "endpoint": "historical", "model": model_id})
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

# id -> label в model_runs_history.json (та же карта, что vps_pipeline.py::MODELS —
# поддерживать синхронно при добавлении/переименовании моделей в обоих файлах).
#
# [РАСШИРЕНО 2026-09-12, OPEN_METEO_PER_MODEL_UPDATE_ARCHITECTURE_001, GPT APPROVED]
# icon_global/gem_global добавлены после подтверждения живыми запросами (VPS):
#   dwd_icon        → icon_global : HTTP 200, данные свежие (last_run 2026-09-12,
#                      update_interval_seconds=21600) — полноценно event-driven.
#   cmc_gem_gdps    → gem_global  : HTTP 200, НО данные STALE (last_run 2026-05-26,
#                      last_run_availability_time 2026-07-01 — на момент проверки
#                      отстают на ~3.5 месяца от текущей даты). Других рабочих
#                      кандидатов domain-id для GEM Global не найдено (проверены
#                      cmc_gem_global/cmc_gem/cmc_gem_gdps_global/gem_global — все
#                      HTTP 500). Включено в tracked по прямому указанию GPT
#                      (APPROVED, п.8: "не оставлять gem_global безусловным
#                      fetch"), но практический эффект: пока Open-Meteo не
#                      обновит этот bucket, run_time для GEM Global не изменится
#                      → changed_models никогда не включит gem_global → её кэш
#                      останется с данными первого fill навсегда. Риск: due-gate
#                      в vps_pipeline.py будет опрашивать meta.json для этой
#                      модели КАЖДЫЙ цикл (раз в 5 мин, а не по interval), т.к.
#                      next_expected так и останется в прошлом — это не меняли
#                      (п.10 задачи: due-gate не трогать без необходимости).
#                      Наблюдать; если станет проблемой — отдельная задача.
_ID_TO_HISTORY_LABEL = {
    "ecmwf_ifs":                     "ECMWF IFS",
    "icon_eu":                       "ICON EU",
    "icon_global":                   "ICON Global",
    "ukmo_global_deterministic_10km": "UKMO",
    "meteofrance_arpege_europe":     "Arpège",
    "gfs_global":                    "GFS",
    "gem_global":                    "GEM Global",
    "cma_grapes_global":             "GRAPES",
}


def fetch_ensemble_ready_time():
    """Возвращает datetime готовности последнего прогона или None.

    [ИСПРАВЛЕНО 2026-09-12, GPT review OPEN_METEO_REQUEST_ARCHITECTURE_001,
    п. A1, APPROVED после проверки семантики] Раньше эта функция сама делала
    6 HTTP-запросов к /data/{metaId}/static/meta.json — ТЕ ЖЕ САМЫЕ 6
    проверок, которые vps_pipeline.py уже сделал (due-гейтированно) в
    начале этого же цикла и сохранил в data/model_runs_history.json. Теперь
    вместо повторного сетевого запроса читаем уже известные значения
    оттуда: поле "run_time" в history — это ts_to_iso(last_run_availability_time)
    (проверено на факте 2026-09-12: НЕ detected_at, семантика совпадает 1:1
    с тем, что раньше отдавал HTTP-запрос). Сетевое discovery остаётся
    ТОЛЬКО в vps_pipeline.py — экономия ~6 запросов на каждый вызов
    update.py::main() (и по run_pipeline(), и по SYNOP-окну)."""
    history, _ = gh_load_json("data/model_runs_history.json", default={})
    times = []
    for m in ENSEMBLE_MODELS:
        label = _ID_TO_HISTORY_LABEL.get(m["id"])
        if not label:
            continue  # icon_global/gem_global — без metaId, не отслеживаются в history
        entries = (history or {}).get(label)
        if entries:
            run_time_iso = entries[-1].get("run_time")
            if run_time_iso:
                try:
                    dt = datetime.strptime(run_time_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    times.append(dt.timestamp())
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
    data = retry(lambda: http_get_json(url, timeout=25), attempts=3, delay=10,
                 log_ctx={"script": "update.py", "function": "fetch_forecast_model",
                          "endpoint": "forecast", "model": model_id})
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

# Маппинг: поле open-meteo → ключ в model_bias.json
_BIAS_FIELD_MAP = {
    "temperature_2m":    "temp",
    "pressure_msl":      "pressure",
    "wind_speed_10m":    "wind",
    "wind_direction_10m":"windDir",
    "cloud_cover":       "cloudcover",
    "visibility":        "visibility",
}

def debias_model_hours(model_id, hours, model_bias_models):
    """Вычитает per-model bias из часовых данных модели до усреднения."""
    if not hours or model_id not in model_bias_models:
        return hours
    m_bias = model_bias_models[model_id]
    month_key = hours[0]["time"][5:7] if hours else None  # "MM" из ISO-строки
    # byMonth → fallback overall
    by_month  = m_bias.get("byMonth", {}).get(month_key, {})
    overall   = m_bias.get("overall", {})

    result = []
    for h in hours:
        hc = dict(h)
        for field, param in _BIAS_FIELD_MAP.items():
            val = hc.get(field)
            if val is None:
                continue
            b = (by_month.get(param) or overall.get(param) or {}).get("bias")
            if b is None:
                continue
            if param == "windDir":
                hc[field] = (val - b) % 360
            elif param in ("wind_speed_10m",):
                hc[field] = max(0.0, round((val - b) * 10) / 10)
            else:
                hc[field] = round((val - b) * 10) / 10
        result.append(hc)
    return result

def merge_ensemble(all_model_hours, succeeded, min_time=None):
    """Смешивает прогнозы моделей в ансамбль (равные веса).

    min_time (опционально) — строка "YYYY-MM-DDTHH:MM", нижняя граница
    времени для итогового ряда. [ДОБАВЛЕНО 2026-09-12, найдено при
    тестировании per-model кэша] Без этой границы протухший кэш (пример —
    GEM Global, meta.json не обновлялся с мая 2026) мог бы протащить в
    ensemble_hours "осиротевшие" записи с календарными датами из далёкого
    прошлого (те часы, что есть ТОЛЬКО в устаревшем кэше и ни у одной другой
    модели) — technically корректные по значению, но не имеющие отношения к
    текущему прогнозному окну, и способные сломать ожидания потребителей
    снимка (forecast.html и т.п. ожидают непрерывный ряд от "сегодня"
    вперёд). Вызывающий код передаёт min_time = (now − несколько часов).

    [ИСПРАВЛЕНО 2026-09-12, OPEN_METEO_PER_MODEL_UPDATE_ARCHITECTURE_001,
    GPT APPROVED, найдено при реализации п.6] Раньше объединение шло по
    ПОЗИЦИИ индекса i в массиве первой succeeded-модели — это было безопасно,
    только пока ВСЕ модели фетчились синхронно "сейчас" (единый time-axis:
    hours[0] у всех = полночь сегодняшнего UTC-дня). После введения
    per-model кэша (data/model_forecast_cache.json) часть массивов hours
    может быть получена несколько часов/дней назад — их time-axis СМЕЩЁН
    относительно свежих моделей на N часов. Слияние по индексу в этом
    случае молча усредняло бы данные РАЗНЫХ календарных часов между собой
    (например, сегодняшние 12:00 свежей модели с позавчерашними 12:00
    кэшированной) — тихая порча ensemble/PWS/SYNOP без единой ошибки в логе.

    Теперь выравнивание — по фактической метке времени h["time"] (точное
    совпадение строки), а не по позиции. Модель, чьи закэшированные часы не
    пересекаются по времени с текущим окном (как в пределе — GEM Global с
    протухшим meta.json), просто не участвует в среднем для соответствующих
    часов — вместо порчи данных получаем корректное исключение по каждому
    часу отдельно. Поведение для случая "все модели свежие" (совпадающий
    time-axis) не изменилось."""
    if not succeeded:
        return []

    by_time = {}
    for m in succeeded:
        mh = all_model_hours.get(m) or []
        by_time[m] = {h["time"]: h for h in mh}

    all_times = sorted({t for d in by_time.values() for t in d.keys()})
    if min_time:
        all_times = [t for t in all_times if t >= min_time]

    numeric = [
        "temperature_2m","apparent_temperature","pressure_msl","relative_humidity_2m",
        "wind_speed_10m","wind_gusts_10m","rain","showers","precip_prob","snowfall",
        "snow_depth","cloud_cover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
        "shortwave_radiation","dew_point_2m","visibility",
    ]
    result = []
    for t in all_times:
        present = [m for m in succeeded if t in by_time[m]]
        if not present:
            continue
        merged = {"time": t}
        for f in numeric:
            vals = [by_time[m][t][f] for m in present if by_time[m][t].get(f) is not None]
            # Фильтр выбросов для давления
            if f == "pressure_msl" and vals:
                vals = [v for v in vals if 930 < v < 1060]
            merged[f] = sum(vals) / len(vals) if vals else None
        # Направление ветра — векторное среднее
        sx = sy = 0
        for m in present:
            v = by_time[m][t].get("wind_direction_10m")
            if v is not None:
                rad = v * math.pi / 180
                sx += math.sin(rad)
                sy += math.cos(rad)
        merged["wind_direction_10m"] = (math.degrees(math.atan2(sx, sy)) + 360) % 360 if (sx or sy) else None
        # weather_code — мажоритарный
        codes = {}
        for m in present:
            c = by_time[m][t].get("weather_code")
            if c is not None:
                codes[c] = codes.get(c, 0) + 1
        merged["weather_code"] = max(codes, key=codes.get) if codes else 0
        result.append(merged)
    return result


def apply_bias(value, key, bias_overall, bias_by_horizon=None, horizon_h=None):
    if value is None:
        return value
    # Ищем bias по горизонту, fallback на overall
    b = None
    if bias_by_horizon is not None and horizon_h is not None:
        h_key = str(max(0, round(horizon_h)))
        b = (bias_by_horizon.get(h_key, {}).get(key) or {}).get("bias")
    if b is None:
        b = (bias_overall.get(key) or {}).get("bias")
    if b is None:
        return value
    if key == "windDir":
        return round((value - b) % 360)
    result = round((value - b) * 10) / 10
    if key in ("wind", "windGust"):
        result = max(0, result)
    if key == "humidity":
        result = max(0, min(100, result))
    return result


def build_snapshot(ensemble_hours, saved_at, run_time, mode="synop", bias=None, bias_by_horizon=None, all_model_hours=None, succeeded=None, model_run_times=None):
    """Формирует снимок в формате совместимом с forecast.html.

    [ДОБАВЛЕНО 2026-09-12, OPEN_METEO_PER_MODEL_UPDATE_ARCHITECTURE_001,
    GPT APPROVED, п.7] model_run_times — {model_id: run_time_iso}, per-model
    времена прогонов, вошедших в этот снимок (часть — из свежего фетча, часть
    — из model_forecast_cache.json). Пишется в новое поле "modelRunTimes"
    ДОПОЛНИТЕЛЬНО к существующему "runTime" (агрегированный max(), сохранён
    для обратной совместимости — старые потребители снимка не меняются).
    Старые снимки не мигрируются, у них просто не будет этого поля."""
    hours_out = []
    saved_dt = parse_iso(saved_at)
    snap_dt  = saved_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    # Индекс времени → индекс часа по каждой модели (для быстрого поиска)
    model_time_index = {}
    if all_model_hours and succeeded:
        for mid in succeeded:
            mh = all_model_hours.get(mid) or []
            model_time_index[mid] = {h2["time"][:13]: i for i, h2 in enumerate(mh)}

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

            # Данные по отдельным моделям для этого часа
            models_out = {}
            if model_time_index:
                t_key = t_str[:13]
                for mid in succeeded:
                    mh = all_model_hours.get(mid) or []
                    idx = model_time_index.get(mid, {}).get(t_key)
                    if idx is None:
                        continue
                    mhh = mh[idx]
                    models_out[mid] = {
                        "temp":       round(mhh["temperature_2m"] * 10) / 10 if mhh.get("temperature_2m") is not None else None,
                        "pressure":   round(mhh["pressure_msl"] * 10) / 10 if mhh.get("pressure_msl") is not None else None,
                        "wind":       round(mhh["wind_speed_10m"] * 10) / 10 if mhh.get("wind_speed_10m") is not None else None,
                        "windDir":    round(mhh["wind_direction_10m"]) if mhh.get("wind_direction_10m") is not None else None,
                        "humidity":   round(mhh["relative_humidity_2m"]) if mhh.get("relative_humidity_2m") is not None else None,
                        "cloudcover": round(mhh["cloud_cover"]) if mhh.get("cloud_cover") is not None else None,
                        "visibility": round(mhh["visibility"]) if mhh.get("visibility") is not None else None,
                    }

            entry = {
                "time":        h["time"],
                "temp":        round(h["temperature_2m"] * 10) / 10 if h["temperature_2m"] is not None else None,
                "pressure":    round(h["pressure_msl"] * 10) / 10 if h["pressure_msl"] is not None else None,
                "wind":        round(h["wind_speed_10m"] * 10) / 10 if h["wind_speed_10m"] is not None else None,
                "windGust":    round((h["wind_gusts_10m"] or h["wind_speed_10m"] or 0) * 10) / 10,
                "windDir":     round(h["wind_direction_10m"]) if h["wind_direction_10m"] is not None else None,
                "humidity":    round(h["relative_humidity_2m"]) if h["relative_humidity_2m"] is not None else None,
                "rain":        round(h["rain"] * 10) / 10 if h["rain"] is not None else None,
                "cloudcover":  round(h["cloud_cover"]) if h["cloud_cover"] is not None else None,
                "visibility":  round(h["visibility"]) if h.get("visibility") is not None else None,
                "weatherCode": h["weather_code"],
            }
            if models_out:
                entry["models"] = models_out
            hours_out.append(entry)
        else:  # pws — каждый час, первые 4 дня, без коррекции (применяется на клиенте)
            if horizon_h > 96:
                break

            # Данные по отдельным моделям для PWS
            models_out_pws = {}
            if model_time_index:
                t_key_pws = t_str[:13]
                for mid in succeeded:
                    mh = all_model_hours.get(mid) or []
                    idx = model_time_index.get(mid, {}).get(t_key_pws)
                    if idx is None:
                        continue
                    mhh = mh[idx]
                    models_out_pws[mid] = {
                        "temp":       round(mhh["temperature_2m"] * 10) / 10 if mhh.get("temperature_2m") is not None else None,
                        "pressure":   round(mhh["pressure_msl"] * 10) / 10 if mhh.get("pressure_msl") is not None else None,
                        "wind":       round(mhh["wind_speed_10m"] * 10) / 10 if mhh.get("wind_speed_10m") is not None else None,
                        "windGust":   round((mhh.get("wind_gusts_10m") or mhh.get("wind_speed_10m") or 0) * 10) / 10,
                        "windDir":    round(mhh["wind_direction_10m"]) if mhh.get("wind_direction_10m") is not None else None,
                        "humidity":   round(mhh["relative_humidity_2m"]) if mhh.get("relative_humidity_2m") is not None else None,
                    }

            entry_pws = {
                "time":     h["time"],
                "horizonH": round(horizon_h),
                "temp":     round(h["temperature_2m"] * 10) / 10 if h["temperature_2m"] is not None else None,
                "pressure": round(h["pressure_msl"] * 10) / 10 if h["pressure_msl"] is not None else None,
                "wind":     round(h["wind_speed_10m"] * 10) / 10 if h["wind_speed_10m"] is not None else None,
                "windGust": round((h["wind_gusts_10m"] or h["wind_speed_10m"] or 0) * 10) / 10,
                "windDir":  round(h["wind_direction_10m"]) if h["wind_direction_10m"] is not None else None,
                "humidity": round(h["relative_humidity_2m"]) if h["relative_humidity_2m"] is not None else None,
                "rain":     round(h["rain"] * 10) / 10 if h["rain"] is not None else None,
                "visibility": round(h["visibility"]) if h.get("visibility") is not None else None,
            }
            if models_out_pws:
                entry_pws["models"] = models_out_pws
            hours_out.append(entry_pws)

    snapshot_out = {
        "savedAt": saved_at,
        "runTime": run_time,
        "hours":   hours_out,
    }
    if model_run_times:
        snapshot_out["modelRunTimes"] = model_run_times
    return snapshot_out

# ════════════════════════════════════════════════════════════════════════════
# 4. Выжимка снимков → ensemble_accuracy.json
# ════════════════════════════════════════════════════════════════════════════

# Числовые параметры: (поле в снимке, поле в наблюдении)
PARAM_MAP = {
    "temp":       ("temp",       "temp"),
    "pressure":   ("pressure",   "pressure"),
    "wind":       ("wind",       "wind"),
    "windGust":   ("windGust",   "windGust"),
    "windDir":    ("windDir",    "windDir"),
    "humidity":   ("humidity",   "humidity"),
    "cloudcover": ("cloudcover", "cloudcover"),
    "precip":     ("rain",       "precip"),
    "visibility": ("visibility", "visibility"),
}

# поля, которые build_snapshot() реально сохраняет ПО КАЖДОЙ МОДЕЛИ отдельно
# для PWS (models{} в entry_pws) — precip/cloudcover/visibility там нет
MODEL_PARAM_KEYS = ["temp", "pressure", "wind", "windGust", "windDir", "humidity"]

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
        err = ((forecast_val - obs_val + 180) % 360) - 180
        return err, abs(err)
    err = forecast_val - obs_val
    return err, abs(err)


def squeeze_snapshots(snaps, obs_by_time, mode="synop", processed_keys=None):
    """
    Выжимает снимки:
    - считает ошибки для часов у которых есть наблюдения
    - пропускает уже обработанные пары (дедупликация)
    - для mode="pws" попутно вытаскивает ошибки ПО КАЖДОЙ МОДЕЛИ отдельно
      (данные уже есть в снимке в h["models"], просто раньше не читались)
    - возвращает (accuracy_records, remaining_snaps, new_processed_keys, model_records)
    """
    now = utcnow()
    if processed_keys is None:
        processed_keys = set()

    accuracy_records = []
    model_records = []
    remaining = []
    new_processed = set()

    for snap in snaps:
        saved_at = parse_iso(snap["savedAt"])
        hours    = snap.get("hours", [])
        if not hours:
            continue

        expired = (now - saved_at).total_seconds() > 96 * 3600

        for h in hours:
            t_str = h["time"] if "T" in h["time"] else h["time"].replace(" ", "T") + ":00"
            t_dt  = parse_iso(t_str)
            if t_dt >= now:
                break

            # Дедупликация: пропускаем уже обработанные пары
            pair_key = snap["savedAt"][:16] + "|" + t_str[:13]
            if pair_key in processed_keys:
                continue

            obs_key = t_dt.strftime("%Y%m%d%H00")
            obs = obs_by_time.get(obs_key)
            if obs is None:
                continue

            # Горизонт от savedAt, округлённый до 3ч — согласованно с JS
            horizon_h_raw = (t_dt - saved_at).total_seconds() / 3600
            horizon_h     = round(horizon_h_raw / 3) * 3
            day_key       = t_dt.strftime("%Y-%m-%d")
            hour_utc      = t_dt.hour

            rec = {
                "savedAt":  snap["savedAt"],
                "dayKey":   day_key,
                "horizonH": horizon_h,
                "hourUTC":  hour_utc,
            }
            for param, (fc_field, obs_field) in PARAM_MAP.items():
                obs_val = obs.get(obs_field)
                fc_val  = h.get(fc_field)
                err = calc_errors(fc_val, obs_val, param)
                if err is not None:
                    rec[param] = {"err": round(err[0], 2), "ae": round(err[1], 2)}

            fc_wmo = h.get("weatherCode")
            obs_ww = obs.get("ww")
            if fc_wmo is not None and obs_ww is not None:
                fg = wmo_group(fc_wmo)
                og = synop_group(obs_ww)
                if fg is not None and og is not None:
                    rec["wx"] = {"hit": 1 if fg == og else 0}

            accuracy_records.append(rec)

            if mode == "pws":
                for mid, mdata in (h.get("models") or {}).items():
                    mrec = {"dayKey": day_key, "horizonH": horizon_h, "hourUTC": hour_utc, "model": mid}
                    has_any = False
                    for param in MODEL_PARAM_KEYS:
                        obs_val = obs.get(param)
                        fc_val  = mdata.get(param)
                        err = calc_errors(fc_val, obs_val, param)
                        if err is not None:
                            mrec[param] = {"err": round(err[0], 2), "ae": round(err[1], 2)}
                            has_any = True
                    if has_any:
                        model_records.append(mrec)

            new_processed.add(pair_key)

        if not expired:
            remaining.append(snap)
        else:
            log.info("  Удалён снимок %s (%d часов)", snap["savedAt"][:16], len(hours))

    return accuracy_records, remaining, new_processed, model_records


def update_model_bias_pws(existing, new_model_records):
    """
    Копит bias/MAE/RMSE ПО КАЖДОЙ МОДЕЛИ ОТДЕЛЬНО относительно PWS.
    Аналог calc_model_bias.py (тот считает то же самое, но относительно SYNOP,
    отдельным fetch через data/modeldata/*.json) — здесь же используются данные,
    уже присутствующие в ensemble_snapshots_pws.json (models{} в build_snapshot),
    без единого лишнего запроса к API.
    Структура: { updated, records, models: { model_id: { overall, bySeason, byMonth, byHourUTC } } }
    Как и в update_accuracy() — каждый bucket хранит и финализированные bias/mae/rmse,
    и сырые sum_*, чтобы продолжать копить инкрементально без пересчёта с нуля.
    """
    acc = existing or {"updated": None, "records": 0, "models": {}}
    models = acc.setdefault("models", {})

    def ensure_sums(bucket):
        for s in bucket.values():
            if "sum_ae" not in s and "mae" in s:
                n = s.get("n", 0)
                s["sum_ae"]  = s["mae"]  * n
                s["sum_sq"]  = (s.get("rmse", 0) ** 2) * n
                s["sum_err"] = s.get("bias", 0) * n

    for m in models.values():
        ensure_sums(m.get("overall", {}))
        for params in m.get("bySeason", {}).values():  ensure_sums(params)
        for params in m.get("byMonth", {}).values():   ensure_sums(params)
        for params in m.get("byHourUTC", {}).values(): ensure_sums(params)

    def add(bucket, param, err, ae):
        if param not in bucket or "sum_ae" not in bucket[param]:
            bucket[param] = {"sum_err": 0.0, "sum_ae": 0.0, "sum_sq": 0.0, "n": 0}
        b = bucket[param]
        b["sum_err"] += err
        b["sum_ae"]  += ae
        b["sum_sq"]  += ae * ae
        b["n"]       += 1

    for rec in new_model_records:
        mid = rec["model"]
        m = models.setdefault(mid, {"overall": {}, "bySeason": {}, "byMonth": {}, "byHourUTC": {}})
        month_key = rec["dayKey"][5:7]
        season    = SEASON_MAP.get(int(month_key))
        hour_key  = str(rec["hourUTC"])
        for param in MODEL_PARAM_KEYS:
            if param not in rec:
                continue
            err = rec[param]["err"]; ae = rec[param]["ae"]
            add(m["overall"], param, err, ae)
            if season:
                add(m["bySeason"].setdefault(season, {}), param, err, ae)
            add(m["byMonth"].setdefault(month_key, {}), param, err, ae)
            add(m["byHourUTC"].setdefault(hour_key, {}), param, err, ae)
        acc["records"] = acc.get("records", 0) + 1

    def finalize(bucket):
        for param in list(bucket.keys()):
            s = bucket[param]
            n = s.get("n", 0)
            if n == 0:
                del bucket[param]
                continue
            bucket[param] = {
                "bias": round(s["sum_err"] / n, 3),
                "mae":  round(s["sum_ae"]  / n, 3),
                "rmse": round(math.sqrt(s["sum_sq"] / n), 3),
                "n": n,
                "sum_err": round(s["sum_err"], 4),
                "sum_ae":  round(s["sum_ae"], 4),
                "sum_sq":  round(s["sum_sq"], 4),
            }

    for m in models.values():
        finalize(m["overall"])
        for params in m["bySeason"].values():  finalize(params)
        for params in m["byMonth"].values():   finalize(params)
        for params in m["byHourUTC"].values(): finalize(params)

    acc["updated"] = utcnow().isoformat()
    return acc


def update_accuracy(existing_acc, new_records, new_processed_keys=None, mode="synop"):
    """
    Обновляет ensemble_accuracy.json новыми записями.
    Структура:
    {
      "updated":       "...",
      "squeezed":      [...],          # ключи уже обработанных пар (дедупликация)
      "overall":       {param: {mae, rmse, bias, n}},
      "overallRecent": {param: {mae, rmse, bias, n}},  # скользящий: последние 14 дней
      "byDay":         {dayKey: {param: {mae, rmse, bias, n}}},
      "byHorizon":     {str(h): {param: {mae, rmse, bias, n}}}
    }
    """
    acc = existing_acc or {
        "updated": None, "squeezed": [],
        "overall": {}, "byDay": {}, "byHorizon": {}, "byHourUTC": {},
        "wx": {"hits": 0, "total": 0}, "wxByDay": {}
    }

    # Миграция: при отсутствии squeezed — старый формат.
    # Сбрасываем byHorizon (данные с неверными ключами) и начинаем заново.
    if "squeezed" not in acc:
        log.info("  Миграция: сброс byHorizon (новое определение горизонта)")
        acc["byHorizon"] = {}
        acc["squeezed"]  = []

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
    ensure_sums(acc.get("byHourUTC", {}))
    if "overall" in acc:
        ensure_sums({"_": acc["overall"]})

    overall    = acc.setdefault("overall", {})
    by_day     = acc.setdefault("byDay", {})
    by_horizon = acc.setdefault("byHorizon", {})
    by_hour    = acc.setdefault("byHourUTC", {})
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
            add_to_bucket(by_day,     day_key,             param, ae, err)
            add_to_bucket(by_horizon, horizon_h,           param, ae, err)
            add_to_bucket(by_hour,    str(rec["hourUTC"]), param, ae, err)
        if "wx" in rec:
            wx_overall["hits"]  += rec["wx"]["hit"]
            wx_overall["total"] += 1
            if day_key not in wx_by_day:
                wx_by_day[day_key] = {"hits": 0, "total": 0}
            wx_by_day[day_key]["hits"]  += rec["wx"]["hit"]
            wx_by_day[day_key]["total"] += 1

    def finalize(bucket_dict):
        result = {}
        for key, params in bucket_dict.items():
            result[key] = {}
            for param, s in params.items():
                n = s.get("n", 0)
                if n == 0:
                    continue
                result[key][param] = {
                    "mae":     round(s["sum_ae"] / n, 3),
                    "rmse":    round(math.sqrt(s["sum_sq"] / n), 3),
                    "bias":    round(s["sum_err"] / n, 3),
                    "n":       n,
                    "sum_ae":  round(s["sum_ae"], 4),
                    "sum_sq":  round(s["sum_sq"], 4),
                    "sum_err": round(s["sum_err"], 4),
                }
        return result

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

    # Скользящий bias: последние 14 дней из byDay
    cutoff_recent = (utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
    recent_sums = {}
    for dk, params in by_day.items():
        if dk < cutoff_recent:
            continue
        for param, s in params.items():
            if param not in recent_sums:
                recent_sums[param] = {"sum_ae": 0.0, "sum_sq": 0.0, "sum_err": 0.0, "n": 0}
            rs = recent_sums[param]
            rs["sum_ae"]  += s.get("sum_ae",  s.get("mae",  0) * s.get("n", 0))
            rs["sum_sq"]  += s.get("sum_sq",  (s.get("rmse", 0) ** 2) * s.get("n", 0))
            rs["sum_err"] += s.get("sum_err", s.get("bias", 0) * s.get("n", 0))
            rs["n"]       += s.get("n", 0)

    overall_recent = {}
    for param, s in recent_sums.items():
        n = s["n"]
        if n == 0:
            continue
        overall_recent[param] = {
            "mae":  round(s["sum_ae"] / n, 3),
            "rmse": round(math.sqrt(s["sum_sq"] / n), 3),
            "bias": round(s["sum_err"] / n, 3),
            "n":    n,
        }

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
            "pct":  round(w["hits"] / w["total"] * 100) if w["total"] > 0 else 0,
        }

    # Обновляем squeezed: добавляем новые ключи, чистим старше 5 суток
    squeezed = set(acc.get("squeezed", []))
    squeezed.update(new_processed_keys or set())
    cutoff_str = (utcnow() - timedelta(hours=120)).strftime("%Y-%m-%dT%H:%M")
    squeezed   = {k for k in squeezed if k[:16] >= cutoff_str}

    return {
        "updated":       utcnow().isoformat(),
        "squeezed":      sorted(squeezed),
        "overall":       overall_final,
        "overallRecent": overall_recent,
        "byDay":         finalize(by_day),
        "byHorizon":     finalize(by_horizon),
        "byHourUTC":     finalize(by_hour),
        "wx":            wx_final,
        "wxByDay":       wx_by_day_final,
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
        gist_log(f"  SYNOP {date_str} ...")
        text = fetch_synop_ogimet(day)
        if text:
            parsed = parse_synop_text(text)
            added_this_day = 0
            for rec in parsed:
                if rec["synopTime"] not in existing_synop_keys:
                    new_synop_lines.append(rec["txtLine"])
                    new_synop_parsed.append(rec)
                    existing_synop_keys.add(rec["synopTime"])
                    synop_obs_by_time[rec["synopTime"]] = rec["obs"]
                    added_this_day += 1
            gist_log(f"    → {len(parsed)} сводок от ogimet, из них новых: {added_this_day}")
        else:
            gist_log("    ✗ SYNOP недоступен")
        time.sleep(2)
        day += timedelta(days=1)

    if new_synop_lines:
        merged_txt = synop_text.rstrip() + "\n" + "\n".join(new_synop_lines) + "\n"
        _merged_txt = merged_txt
        synop_sha = gist_log_save(
            f"synop_{year}.txt сохранён (+{len(new_synop_lines)} строк)",
            lambda: gh_put(synop_path, _merged_txt, synop_sha,
                           f"synop {year}: +{len(new_synop_lines)} lines"),
            gh_path=synop_path)
    else:
        gist_log(f"  synop_{year}.txt актуален")

    # ── 2. Дописываем modelData в месячные файлы ────────────────────────────
    gist_log("--- 2. modelData ---")

    # Группируем новые сводки по месяцам
    by_month = {}
    for rec in new_synop_parsed:
        mk = f"modelData_{rec['synopTime'][:4]}_{rec['synopTime'][4:6]}"  # modelData_2026_05   
        by_month.setdefault(mk, []).append(rec)

    if not by_month:
        gist_log("  modelData актуален")
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
                gist_log(f"  Модели за {date_str} ...")
                hourly_by_model = {}
                if _om_guard.gate(probe_owner=False) == "skip":
                    gist_log("    Open-Meteo cooldown активен — бэкфилл за эту дату пропущен")
                    _om_log.log("update.py", "fetch_historical_model", endpoint="historical",
                                status="skip_gate", gate="skip")
                else:
                    for mid in [m["id"] for m in ENSEMBLE_MODELS]:
                        try:
                            h = fetch_historical_model(mid, date_str)
                            hourly_by_model[mid] = h
                            time.sleep(0.5)
                        except HTTPError as e:
                            if e.code == 429:
                                _om_guard.record_429()
                                log.warning("    ✗ %s: HTTP 429 — cooldown зафиксирован, останавливаю перебор моделей", mid)
                                hourly_by_model[mid] = None
                                break
                            log.warning("    ✗ %s: %s", mid, e)
                            hourly_by_model[mid] = None
                        except Exception as e:
                            log.warning("    ✗ %s: %s", mid, e)
                            hourly_by_model[mid] = None
                for rec in date_recs:
                    md_rec = build_model_record(rec, hourly_by_model)
                    if md_rec:
                        new_md_records.append(md_rec)

            if new_md_records:
                merged = sorted(month_data + new_md_records, key=lambda r: r["synopTime"])
                _merged = merged
                _md_sha = md_sha
                _md_path = md_path
                md_sha = gist_log_save(
                    f"{mk}.json сохранён (+{len(new_md_records)} записей)",
                    lambda: gh_save_json(_md_path, _merged, _md_sha,
                                         f"modelData {mk}: +{len(new_md_records)} records"),
                    gh_path=md_path)

    # ── 3. Свежий ансамблевый прогноз → снимки ──────────────────────────────
    gist_log("--- 3. Ансамблевый прогноз ---")

    ensemble_ready_time = fetch_ensemble_ready_time()
    gist_log(f"  Время готовности ансамбля: {ensemble_ready_time.isoformat() if ensemble_ready_time else 'неизвестно'}")

    snap_synop_path = "data/ensemble_snapshots_synop.json"
    snap_pws_path   = "data/ensemble_snapshots_pws.json"
    snaps_synop, snaps_synop_sha = gh_load_json(snap_synop_path, default=[])
    snaps_pws,   snaps_pws_sha   = gh_load_json(snap_pws_path,   default=[])
    if len(snaps_pws) > MAX_PWS_SNAPS:
        excess = len(snaps_pws) - MAX_PWS_SNAPS
        snaps_pws = snaps_pws[excess:]
        gist_log(f"  PWS: превентивно удалено {excess} старых снимков (лимит {MAX_PWS_SNAPS})")
    acc_pws_for_bias, _ = gh_load_json("data/ensemble_accuracy_pws.json", default=None)
    pws_bias_overall    = (acc_pws_for_bias or {}).get("overall", {})
    pws_bias_by_horizon = (acc_pws_for_bias or {}).get("byHorizon", {})

    model_bias_data, _  = gh_load_json("data/model_bias.json", default=None)
    model_bias_models   = (model_bias_data or {}).get("models", {})

    # Проверяем нужен ли новый снимок
    last_synop_run = parse_iso(snaps_synop[-1]["runTime"]) if snaps_synop and snaps_synop[-1].get("runTime") else None
    last_pws_run   = parse_iso(snaps_pws[-1]["runTime"])   if snaps_pws   and snaps_pws[-1].get("runTime")   else None

    need_synop = ensemble_ready_time is not None and (not last_synop_run or last_synop_run < ensemble_ready_time)
    need_pws   = ensemble_ready_time is not None and (not last_pws_run   or last_pws_run   < ensemble_ready_time)

    all_model_hours = {}
    succeeded = []
    model_run_times = {}   # для build_snapshot()::modelRunTimes — заполняется и из кэша, и из свежих фетчей
    if (need_synop or need_pws) and _om_guard.gate(probe_owner=False) == "skip":
        gist_log("  Open-Meteo cooldown активен — свежий ансамблевый прогноз пропущен")
        _om_log.log("update.py", "fetch_forecast_model", endpoint="forecast",
                    status="skip_gate", gate="skip")
    elif need_synop or need_pws:
        # [ПЕРЕПИСАНО 2026-09-12, OPEN_METEO_PER_MODEL_UPDATE_ARCHITECTURE_001,
        # GPT APPROVED] Раньше здесь был безусловный цикл по ВСЕМ 8 моделям —
        # 1 новый run любой модели вызывал 8 Forecast API запросов. Теперь:
        # Forecast API вызывается ТОЛЬКО для моделей, чей run_time в
        # model_runs_history.json разошёлся с cache.source_run_time
        # (data/model_forecast_cache.json). Для остальных моделей ансамбль
        # переиспользует их последние успешно сохранённые hours из кэша —
        # HTTP-запрос не делается вообще. need_synop/need_pws (агрегированный
        # max() по history) остаётся ВНЕШНИМ триггером "стоит ли вообще
        # пересматривать снимок" — не тронут (п.10: due-gate/discovery не
        # менять без необходимости), но КОЛИЧЕСТВО запросов внутри теперь
        # определяется per-model diff, а не фактом срабатывания триггера.
        cache, cache_sha = load_forecast_cache()
        cache_models = cache.setdefault("models", {})
        model_runs_history_data, _ = gh_load_json("data/model_runs_history.json", default={})
        changed_models, run_time_by_id = get_changed_models(model_runs_history_data, cache)
        cache_dirty = False

        gist_log(f"  Изменившиеся модели: {changed_models or '(нет)'}")

        for m in ENSEMBLE_MODELS:
            mid = m["id"]
            if mid in changed_models:
                log.info(f"  Загружаем прогноз {mid} (новый run)...")
                try:
                    h = fetch_forecast_model(mid, days=16)
                    if h:
                        parsed = parse_hourly(h)
                        all_model_hours[mid] = parsed
                        succeeded.append(mid)
                        run_time_iso = run_time_by_id.get(mid)
                        model_run_times[mid] = run_time_iso
                        # Кэш обновляем ТОЛЬКО при успехе (п.4 partial failure:
                        # при ошибке source_run_time/hours старые НЕ трогать).
                        cache_models[mid] = {
                            "source_run_time": run_time_iso,
                            "fetched_at": now.isoformat(),
                            "hours": parsed,
                        }
                        cache_dirty = True
                        gist_log(f"    ✓ {mid} (новый run, HTTP-запрос выполнен)")
                except HTTPError as e:
                    if e.code == 429:
                        _om_guard.record_429()
                        gist_log(f"    ✗ {mid}: HTTP 429 — cooldown зафиксирован, останавливаю перебор моделей")
                        break
                    gist_log(f"    ✗ {mid}: {e} (кэш не тронут, повтор в следующем цикле)")
                except Exception as e:
                    gist_log(f"    ✗ {mid}: {e} (кэш не тронут, повтор в следующем цикле)")
                time.sleep(0.5)
            else:
                # Модель не менялась — берём hours из кэша, БЕЗ HTTP-запроса.
                cached_entry = cache_models.get(mid)
                if cached_entry and cached_entry.get("hours"):
                    all_model_hours[mid] = cached_entry["hours"]
                    succeeded.append(mid)
                    model_run_times[mid] = cached_entry.get("source_run_time")
                    gist_log(f"    · {mid} (без изменений, из кэша, 0 запросов)")
                else:
                    gist_log(f"    · {mid} (без изменений, но кэш пуст — пропущена)")

        if cache_dirty:
            _cache = cache
            _cache_sha = cache_sha
            cache_sha = gist_log_save(
                f"model_forecast_cache.json обновлён ({len(changed_models)} моделей)",
                lambda: gh_save_json(MODEL_FORECAST_CACHE_PATH, _cache, _cache_sha,
                                     f"forecast cache: +{len(changed_models)} changed models",
                                     compact=True),
                gh_path=MODEL_FORECAST_CACHE_PATH)

        if succeeded:
            # Сохраняем сырые данные моделей ДО дебайасинга (для верификации)
            raw_model_hours = {mid: list(hours) for mid, hours in all_model_hours.items()}
            # Применяем per-model bias до усреднения
            if model_bias_models:
                cur_month = now.strftime("%m")
                for mid in succeeded:
                    all_model_hours[mid] = debias_model_hours(
                        mid, all_model_hours[mid], model_bias_models)
                gist_log(f"  Per-model bias применён для {len(succeeded)} моделей (месяц {cur_month})")
            _min_time = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
            ensemble_hours = merge_ensemble(all_model_hours, succeeded, min_time=_min_time)
            saved_at  = now.isoformat()
            run_time  = ensemble_ready_time.isoformat() if ensemble_ready_time else None

            # SYNOP-снимок (только в синоптические часы UTC: 0,3,6,9,12,15,18,21)
            synop_hour = (now.hour // 3) * 3  # ближайший прошедший синоптический час
            last_run = snaps_synop[-1].get("runTime") if snaps_synop else None
            same_run = last_run and run_time and parse_iso(last_run) == parse_iso(run_time)
            if need_synop and (now.hour - synop_hour) <= 2 and not same_run:
                snap = build_snapshot(ensemble_hours, saved_at, run_time, mode="synop",
                                     all_model_hours=raw_model_hours, succeeded=succeeded,
                                     model_run_times=model_run_times)
                snaps_synop.append(snap)
                _snaps_synop = snaps_synop
                _snaps_synop_sha = snaps_synop_sha
                snaps_synop_sha = gist_log_save(
                    f"SYNOP-снимок сохранён ({len(snap['hours'])} точек)",
                    lambda: gh_save_json(snap_synop_path, _snaps_synop, _snaps_synop_sha,
                                         f"ensemble synop snapshot {saved_at[:16]}", compact=True),
                    gh_path=snap_synop_path)
            elif need_synop:
                gist_log(f"  SYNOP-снимок пропущен (не синоптический час: {now.hour}h UTC)")

            last_run_pws = snaps_pws[-1].get("runTime") if snaps_pws else None
            same_run_pws = last_run_pws and run_time and parse_iso(last_run_pws) == parse_iso(run_time)
            if need_pws and not same_run_pws:
                snap = build_snapshot(ensemble_hours, saved_at, run_time, mode="pws",
                                     all_model_hours=raw_model_hours, succeeded=succeeded,
                                     model_run_times=model_run_times)
                snaps_pws.append(snap)
                _snaps_pws = snaps_pws
                _snaps_pws_sha = snaps_pws_sha
                snaps_pws_sha = gist_log_save(
                    f"PWS-снимок сохранён ({len(ensemble_hours)} часов)",
                    lambda: gh_save_json(snap_pws_path, _snaps_pws, _snaps_pws_sha,
                                         f"ensemble pws snapshot {saved_at[:16]}", compact=True),
                    gh_path=snap_pws_path)
        else:
            gist_log("  ✗ Ни одна модель не ответила")
    else:
        gist_log("  Снимки актуальны")

    # ── 4. Выжимка снимков → ensemble_accuracy.json ─────────────────────────
    gist_log("--- 4. Выжимка снимков ---")

    acc_synop_path = "data/ensemble_accuracy_synop.json"
    acc_pws_path   = "data/ensemble_accuracy_pws.json"
    acc_synop, acc_synop_sha = gh_load_json(acc_synop_path, default=None)
    acc_pws,   acc_pws_sha   = gh_load_json(acc_pws_path,   default=None)

    # SYNOP
    processed_synop = set(acc_synop.get("squeezed", [])) if acc_synop else set()
    new_recs_synop, remaining_synop, new_processed_synop, _unused_model_recs_synop = squeeze_snapshots(
        snaps_synop, synop_obs_by_time, mode="synop", processed_keys=processed_synop)
    gist_log(f"  SYNOP: выжато {len(new_recs_synop)} записей, осталось {len(remaining_synop)} снимков")

    if new_recs_synop:
        acc_synop = update_accuracy(acc_synop, new_recs_synop, new_processed_synop, mode="synop")
        _acc_synop     = acc_synop
        _acc_synop_sha = acc_synop_sha
        acc_synop_sha = gist_log_save(
            "ensemble_accuracy_synop.json обновлён",
            lambda: gh_save_json(acc_synop_path, _acc_synop, _acc_synop_sha,
                                  "ensemble accuracy synop update"),
            gh_path=acc_synop_path)

    if len(remaining_synop) < len(snaps_synop):
        _remaining_synop  = remaining_synop
        _snaps_synop_sha2 = snaps_synop_sha
        _removed_s        = len(snaps_synop) - len(remaining_synop)
        snaps_synop_sha = gist_log_save(
            f"ensemble_snapshots_synop.json очищен (-{_removed_s} снимков)",
            lambda: gh_save_json(snap_synop_path, _remaining_synop, _snaps_synop_sha2,
                                  f"cleanup synop snapshots: {_removed_s} removed",
                                  compact=True),
            gh_path=snap_synop_path)

    # PWS наблюдения для верификации — из pws_raw.json
    pws_raw, pws_raw_sha = gh_load_json("data/pws_raw.json", default=[])

    pws_groups_cfg, _ = gh_load_json("data/pws_groups.json", default=None)
    active_stations = None   # None = все станции
    param_stations  = {}     # field → set станций (composite-режим)

    if pws_groups_cfg:
        active_group = pws_groups_cfg.get("active", "all")
        groups       = pws_groups_cfg.get("groups", {})

        if active_group == "composite":
            composite = pws_groups_cfg.get("composite", {})
            for field in ("temp", "pressure", "wind", "windGust", "windDir", "humidity", "precip"):
                grp_name = composite.get(field)
                if grp_name is None and field == "windGust":
                    grp_name = composite.get("wind")   # windGust следует за wind
                if grp_name and grp_name in groups:
                    param_stations[field] = set(groups[grp_name])
            gist_log("  PWS: composite — " +
                     ", ".join(f"{f}→{composite.get(f, composite.get('wind','all'))}"
                               for f in ("temp","pressure","wind","windDir","humidity","precip")))
        else:
            active_stations = groups.get(active_group)
            if active_stations:
                gist_log(f"  PWS: группа «{active_group}» → {active_stations}")
            else:
                active_stations = None
                gist_log(f"  PWS: группа «{active_group}» не найдена, все станции")
    else:
        gist_log("  PWS: pws_groups.json не найден, все станции")

    pws_buckets = {}
    for rec in pws_raw:
        hk  = rec.get("hourKey", "")
        sid = rec.get("stationId", "")
        if not hk:
            continue
        if active_stations is not None and sid not in active_stations:
            continue
        try:
            dt      = datetime.strptime(hk, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            obs_key = dt.strftime("%Y%m%d%H00")
        except Exception:
            continue
        if obs_key not in pws_buckets:
            pws_buckets[obs_key] = {}
        for field in ("temp", "pressure", "wind", "windGust", "windDir", "humidity", "precip"):
            val = rec.get(field)
            if val is None:
                continue
            # Composite: фильтр по параметру
            if param_stations and field in param_stations and sid not in param_stations[field]:
                continue
            pws_buckets[obs_key].setdefault(field, []).append(val)

    pws_obs_by_time = {}
    for obs_key, fields in pws_buckets.items():
        entry = {}
        for field, vals in fields.items():
            if not vals:
                continue
            if field == "windDir":
                sx = sum(math.sin(v * math.pi / 180) for v in vals)
                sy = sum(math.cos(v * math.pi / 180) for v in vals)
                entry[field] = round((math.degrees(math.atan2(sx, sy)) + 360) % 360)
            else:
                entry[field] = round(sum(vals) / len(vals), 2)
        pws_obs_by_time[obs_key] = entry

    # PWS
    processed_pws = set(acc_pws.get("squeezed", [])) if acc_pws else set()
    new_recs_pws, remaining_pws, new_processed_pws, new_model_recs_pws = squeeze_snapshots(
        snaps_pws, pws_obs_by_time, mode="pws", processed_keys=processed_pws)
    gist_log(f"  PWS: выжато {len(new_recs_pws)} записей, осталось {len(remaining_pws)} снимков")

    if new_recs_pws:
        acc_pws = update_accuracy(acc_pws, new_recs_pws, new_processed_pws, mode="pws")
        _acc_pws     = acc_pws
        _acc_pws_sha = acc_pws_sha
        acc_pws_sha = gist_log_save(
            "ensemble_accuracy_pws.json обновлён",
            lambda: gh_save_json(acc_pws_path, _acc_pws, _acc_pws_sha,
                                  "ensemble accuracy pws update"),
            gh_path=acc_pws_path)

    if new_model_recs_pws:
        model_bias_pws_path = "data/model_bias_pws.json"
        model_bias_pws, model_bias_pws_sha = gh_load_json(model_bias_pws_path, default=None)
        model_bias_pws = update_model_bias_pws(model_bias_pws, new_model_recs_pws)
        _model_bias_pws     = model_bias_pws
        _model_bias_pws_sha = model_bias_pws_sha
        gist_log_save(
            f"model_bias_pws.json обновлён (+{len(new_model_recs_pws)} записей по моделям)",
            lambda: gh_save_json(model_bias_pws_path, _model_bias_pws, _model_bias_pws_sha,
                                  "model bias pws update"),
            gh_path=model_bias_pws_path)

    # Обрезаем если вдруг превысили лимит после добавления нового снимка
    if len(remaining_pws) > MAX_PWS_SNAPS:
        remaining_pws = remaining_pws[-MAX_PWS_SNAPS:]

    # Защита от полной очистки: если входных снимков было много — что-то пошло не так
    if len(remaining_pws) == 0 and len(snaps_pws) > 3:
        gist_log(f"  ⚠ PWS: предотвращена полная очистка (было {len(snaps_pws)} снимков)")
        remaining_pws = snaps_pws[-3:]

    if len(remaining_pws) < len(snaps_pws):
        _remaining_pws = remaining_pws
        _snaps_pws_sha2 = snaps_pws_sha
        _removed_p = len(snaps_pws) - len(remaining_pws)
        snaps_pws_sha = gist_log_save(
            f"ensemble_snapshots_pws.json очищен (-{_removed_p} снимков)",
            lambda: gh_save_json(snap_pws_path, _remaining_pws, _snaps_pws_sha2,
                                  f"cleanup pws snapshots: {_removed_p} removed",
                                  compact=True),   # ← тоже добавить compact=True
            gh_path=snap_pws_path)

    # ── 5. Чистка pws_raw.json ──────────────────────────────────────────────
    gist_log("--- 5. Чистка pws_raw.json ---")
    cutoff_pws = now - timedelta(days=PWS_KEEP_DAYS)
    pws_before = len(pws_raw)
    pws_raw = [r for r in pws_raw
               if datetime.strptime(r["hourKey"], "%Y-%m-%dT%H").replace(tzinfo=timezone.utc) >= cutoff_pws]
    if len(pws_raw) < pws_before:
        _pws_raw = pws_raw
        _pws_raw_sha = pws_raw_sha
        _removed_r = pws_before - len(pws_raw)
        pws_raw_sha = gist_log_save(
            f"pws_raw.json очищен (-{_removed_r} записей)",
            lambda: gh_save_json("data/pws_raw.json", _pws_raw, _pws_raw_sha,
                                  f"pws_raw cleanup: removed {_removed_r} old records"),
            gh_path="data/pws_raw.json")
    else:
        gist_log(f"  pws_raw.json актуален ({len(pws_raw)} записей)")

    # ── 6. model_weights.json ───────────────────────────────────────────────
    

    gist_log("=== Готово ===")

if __name__ == "__main__":
    main()
