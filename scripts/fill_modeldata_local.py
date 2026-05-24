#!/usr/bin/env python3
"""
fill_modeldata_local.py — заполняет пропущенные месяцы в data/modeldata/.
Аналог кнопки "Догрузить недостающие" из buildHistory.html.

Читает SYNOP из локальных data/synop_YYYY.txt,
запрашивает open-meteo (8 моделей),
сохраняет data/modeldata/modelData_YYYY_MM.json.
"""

import os, json, re, time, datetime, calendar, logging
import urllib.request

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS = [
    "ecmwf_ifs",
    "gfs_global",
    "icon_global",
    "icon_eu",
    "gem_global",
    "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe",
    "cma_grapes_global",
]

SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}
LAT  = 46.4406
LON  = 30.7703

FIELDS = (
    "temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,cloud_cover,precipitation,weather_code,"
    "visibility,dew_point_2m"
)

# ── SYNOP парсинг ──────────────────────────────────────────────────────────────

def _parse_synop_line(line, telegram_key):
    parts = line.strip().split()
    temp = pressure = wind = wind_dir = None
    cloudcover = precip = ww = visibility = dew = None

    try:
        aaxi = parts.index("AAXX")
    except ValueError:
        aaxi = -1

    # Nddff
    if aaxi >= 0 and len(parts) > aaxi + 4:
        wg = parts[aaxi + 4]
        if re.match(r'^\d{5}$', wg):
            N = int(wg[0])
            cloudcover = round(N / 8 * 100) if N <= 8 else None
            wind_dir   = int(wg[1:3]) * 10
            wind       = int(wg[3:5])

    # iRIXhVV — видимость
    if aaxi >= 0 and len(parts) > aaxi + 3:
        s = parts[aaxi + 3]
        if len(s) == 5 and '/' not in s[3:5]:
            vv = int(s[3:5])
            if   vv <= 50: visibility = vv * 100
            elif vv <= 80: visibility = (vv - 50) * 1000
            elif vv == 89: visibility = 70000

    # Основное тело (до секции 333)
    for g in parts[(aaxi + 5 if aaxi >= 0 else 0):]:
        g = g.rstrip('=')
        if g in ('333', '444', '555'):
            break
        if re.match(r'^1[01]\d{3}$', g):
            temp = (-1 if g[1] == '1' else 1) * int(g[2:]) / 10
        if re.match(r'^2[01]\d{3}$', g):
            dew  = (-1 if g[1] == '1' else 1) * int(g[2:]) / 10
        if re.match(r'^4\d{4}$', g):
            pressure = int(g[1:]) / 10          # просто val/10 — см. фикс давления
        if re.match(r'^6\d{4}$', g):
            rrr = int(g[1:4])
            precip = 0.1 if rrr >= 990 else (0 if rrr == 0 else rrr)
        if re.match(r'^7\d{4}$', g):
            ww = int(g[1:3])

    if temp is None:
        return None

    return {
        "synopTime": telegram_key,
        "temp": temp, "pressure": pressure,
        "wind": wind, "windDir": wind_dir,
        "cloudcover": cloudcover, "precip": precip,
        "ww": ww, "visibility": visibility, "dew": dew,
    }


def _load_synop_for_month(year, month):
    """Читает data/synop_YYYY.txt, возвращает список obs-записей за месяц."""
    path = os.path.join(BASE_DIR, "data", f"synop_{year}.txt")
    if not os.path.exists(path):
        return []

    prefix = f"{year}{month:02d}"
    result = []
    pat = re.compile(
        r'^33837,(\d{4}),(\d{2}),(\d{2}),(\d{2}),(\d{2}),(AAXX\s.+)$'
    )

    with open(path, encoding="utf-8") as f:
        for raw in f:
            m = pat.match(raw.strip())
            if not m:
                continue
            y, mo, dd, hh, mm, synop_line = m.groups()
            if "NILL" in synop_line:
                continue
            if int(hh) not in SYNOP_HOURS:
                continue
            tk = f"{y}{mo}{dd}{hh}{mm}"
            if not tk.startswith(prefix):
                continue
            parsed = _parse_synop_line(synop_line, tk)
            if parsed:
                result.append(parsed)

    return result

# ── Open-meteo ─────────────────────────────────────────────────────────────────

def _fetch_model_month(model, start_date, end_date, retries=3):
    url = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={FIELDS}"
        f"&models={model}"
        f"&start_date={start_date}&end_date={end_date}"
        "&timezone=UTC&wind_speed_unit=ms"
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read().decode())
            if "hourly" not in data:
                raise ValueError(data.get("reason", "no hourly"))
            return data["hourly"]
        except Exception as e:
            err = str(e)
            if "429" in err and attempt < retries - 1:
                log.warning("      %s: rate limit, пауза 15с...", model)
                time.sleep(15)
            elif attempt < retries - 1:
                time.sleep(3)
            else:
                log.warning("      ✗ %s: %s", model, e)
                return None
    return None

# ── Сборка записи ──────────────────────────────────────────────────────────────

def _build_record(obs, hourly_by_model, target_time):
    time_arr = next(
        (hourly_by_model[m]["time"] for m in MODELS if hourly_by_model.get(m)),
        None
    )
    if not time_arr:
        return None

    hi = next((i for i, t in enumerate(time_arr) if t.startswith(target_time)), -1)
    if hi == -1:
        return None

    models_data = {}
    for m in MODELS:
        h = hourly_by_model.get(m)
        if not h:
            continue
        wd = h.get("wind_direction_10m")
        models_data[m] = {
            "temp":        h["temperature_2m"][hi]   if h.get("temperature_2m")   else None,
            "pressure":    h["pressure_msl"][hi]     if h.get("pressure_msl")     else None,
            "wind":        h["wind_speed_10m"][hi]   if h.get("wind_speed_10m")   else None,
            "windDir":     round(wd[hi]/10)*10       if wd and wd[hi] is not None else None,
            "gusts":       h["wind_gusts_10m"][hi]   if h.get("wind_gusts_10m")   else None,
            "cloudcover":  h["cloud_cover"][hi]      if h.get("cloud_cover")      else None,
            "precip":      h["precipitation"][hi]    if h.get("precipitation")    else None,
            "weatherCode": h["weather_code"][hi]     if h.get("weather_code")     else None,
            "visibility":  h["visibility"][hi]       if h.get("visibility")       else None,
            "dewPoint":    h["dew_point_2m"][hi]     if h.get("dew_point_2m")     else None,
            "temp850":     None,
        }

    return {
        "synopTime":    obs["synopTime"],
        "forecastHour": None,
        "obs":          obs,
        "models":       models_data,
    }

# ── Главная функция ────────────────────────────────────────────────────────────

def fill_missing_months(changed_files: list, dry_run=False) -> int:
    """
    Сканирует data/modeldata/, находит пропущенные месяцы (2023-01 → прошлый месяц),
    генерирует и сохраняет их. Пути сохранённых файлов добавляет в changed_files.
    Возвращает количество добавленных месяцев.
    """
    modeldata_dir = os.path.join(BASE_DIR, "data", "modeldata")
    os.makedirs(modeldata_dir, exist_ok=True)

    # Существующие файлы
    existing = set()
    for fn in os.listdir(modeldata_dir):
        m = re.match(r'^modelData_(\d{4})_(\d{2})\.json$', fn)
        if m:
            existing.add((int(m.group(1)), int(m.group(2))))

    # Диапазон: 2023-01 → прошлый месяц
    today  = datetime.date.today()
    last   = (today.replace(day=1) - datetime.timedelta(days=1))
    end_y, end_m = last.year, last.month

    missing = []
    y, mo = 2023, 1
    while (y, mo) <= (end_y, end_m):
        if (y, mo) not in existing:
            missing.append((y, mo))
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1

    if not missing:
        log.info("  ✓ modeldata актуален, пропущенных месяцев нет")
        return 0

    log.info("  Пропущено месяцев: %d (%s — %s)",
             len(missing),
             f"{missing[0][1]:02d}.{missing[0][0]}",
             f"{missing[-1][1]:02d}.{missing[-1][0]}")

    added = 0
    for year, month in missing:
        label = f"{month:02d}.{year}"
        log.info("  → %s: читаю SYNOP...", label)

        synops = _load_synop_for_month(year, month)
        if not synops:
            log.warning("    %s: нет SYNOP-данных, пропуск", label)
            continue

        log.info("    %s: %d сводок, загружаю модели...", label, len(synops))
        start_date = f"{year}-{month:02d}-01"
        end_date   = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

        hourly_by_model = {}
        for model in MODELS:
            log.info("      %s...", model)
            hourly_by_model[model] = _fetch_model_month(model, start_date, end_date)
            time.sleep(0.5)

        records = []
        for obs in synops:
            tk     = obs["synopTime"]
            target = f"{tk[:4]}-{tk[4:6]}-{tk[6:8]}T{tk[8:10]}:00"
            rec    = _build_record(obs, hourly_by_model, target)
            if rec:
                records.append(rec)

        if not records:
            log.warning("    %s: записей не получилось, пропуск", label)
            continue

        out_path = os.path.join(modeldata_dir, f"modelData_{year}_{month:02d}.json")
        if not dry_run:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            rel = os.path.relpath(out_path, BASE_DIR)
            if rel not in changed_files:
                changed_files.append(rel)
            log.info("    ✓ %s: %d записей сохранено", label, len(records))
        else:
            log.info("    [dry-run] %s: %d записей (не записано)", label, len(records))

        added += 1
        time.sleep(2)

    return added
    
def update_current_month(changed_files: list) -> int:
    """
    Дополняет modelData_YYYY_MM.json за текущий месяц
    записями которых нет (сравнивает с synop_YYYY.txt).
    """
    today = datetime.date.today()
    year, month = today.year, today.month

    modeldata_dir = os.path.join(BASE_DIR, "data", "modeldata")
    out_path = os.path.join(modeldata_dir, f"modelData_{year}_{month:02d}.json")

    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    existing_keys = {r["synopTime"] for r in existing}
    synops = _load_synop_for_month(year, month)
    to_add = [s for s in synops if s["synopTime"] not in existing_keys]

    if not to_add:
        log.info("  modelData_%d_%02d.json актуален", year, month)
        return 0

    log.info("  modelData_%d_%02d.json: %d новых сводок, загружаем модели...",
             year, month, len(to_add))

    by_date = {}
    for obs in to_add:
        tk = obs["synopTime"]
        by_date.setdefault(f"{tk[:4]}-{tk[4:6]}-{tk[6:8]}", []).append(obs)

    new_records = []
    for date_str, date_obs in sorted(by_date.items()):
        log.info("    %s (%d сводок)...", date_str, len(date_obs))
        hourly_by_model = {}
        for model in MODELS:
            hourly_by_model[model] = _fetch_model_month(model, date_str, date_str)
            time.sleep(0.3)
        for obs in date_obs:
            tk     = obs["synopTime"]
            target = f"{tk[:4]}-{tk[4:6]}-{tk[6:8]}T{tk[8:10]}:00"
            rec    = _build_record(obs, hourly_by_model, target)
            if rec:
                new_records.append(rec)

    if new_records:
        merged = sorted(existing + new_records, key=lambda r: r["synopTime"])
        os.makedirs(modeldata_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        rel = os.path.relpath(out_path, BASE_DIR)
        if rel not in changed_files:
            changed_files.append(rel)
        log.info("  ✓ modelData_%d_%02d.json: +%d записей", year, month, len(new_records))

    return len(new_records)