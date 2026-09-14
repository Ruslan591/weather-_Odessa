#!/usr/bin/env python3
"""
generate_ai_analysis.py — генерация синоптического анализа через Claude API.
Запрашивает open-meteo (ансамбль), агрегирует данные по дням,
отправляет в Claude, сохраняет data/forecast_analysis.json.
Вызывается из check_model_runs.py после run_pipeline().
"""

import json, os, urllib.request, urllib.error
import asyncio
import edge_tts
from datetime import datetime, timezone, timedelta
import hashlib
import verification

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE   = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
OUTPUT_FILE_GEMINI = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
GEMINI_MODEL  = "gemini-2.5-flash"
ENV_FILE      = os.path.join(BASE_DIR, ".env")
TIMEOUT       = 30

LAT, LON      = 46.43, 30.74
TIMEZONE      = "Europe/Kiev"

# ── Ключ из .env ──────────────────────────────────────────────────────────────

def load_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY")

def load_gemini_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("GEMINI_API_KEY")

def claude_enabled():
    """Проверяет флаг CLAUDE_ANALYSIS_ENABLED в .env, затем в os.environ (default: true)."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("CLAUDE_ANALYSIS_ENABLED="):
                    val = line.strip().split("=", 1)[1].lower()
                    return val not in ("0", "false", "no", "off")
    env_val = os.environ.get("CLAUDE_ANALYSIS_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() not in ("0", "false", "no", "off")
    return True

def gemini_enabled():
    """Проверяет флаг GEMINI_ANALYSIS_ENABLED в .env, затем в os.environ (default: false)."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("GEMINI_ANALYSIS_ENABLED="):
                    val = line.strip().split("=", 1)[1].lower()
                    return val not in ("0", "false", "no", "off")
    env_val = os.environ.get("GEMINI_ANALYSIS_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() not in ("0", "false", "no", "off")
    return False

def ai_enabled():
    """Проверяет флаг AI_ANALYSIS_ENABLED в .env (default: true)."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("AI_ANALYSIS_ENABLED="):
                    val = line.strip().split("=", 1)[1].lower()
                    return val not in ("0", "false", "no", "off")
    return True

# ── Запрос open-meteo ─────────────────────────────────────────────────────────

HOURLY_FIELDS = ",".join([
    "temperature_2m","apparent_temperature","dewpoint_2m",
    "relative_humidity_2m","precipitation","precipitation_probability",
    "weathercode","pressure_msl",
    "windspeed_10m","winddirection_10m","windgusts_10m",
    "windspeed_80m","winddirection_80m",
    "cloudcover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
    "cape","lifted_index","convective_inhibition",
    "freezinglevel_height","snowfall","visibility",
    "temperature_925hPa","temperature_850hPa","temperature_700hPa",
    "temperature_600hPa","temperature_500hPa","temperature_400hPa",
    "temperature_300hPa","temperature_250hPa","temperature_200hPa",
    "dewpoint_925hPa","dewpoint_850hPa","dewpoint_700hPa","dewpoint_500hPa",
    "geopotential_height_925hPa","geopotential_height_850hPa",
    "geopotential_height_700hPa","geopotential_height_600hPa",
    "geopotential_height_500hPa","geopotential_height_400hPa",
    "geopotential_height_300hPa","geopotential_height_250hPa",
    "geopotential_height_200hPa","geopotential_height_150hPa",
    "geopotential_height_100hPa","geopotential_height_50hPa",
    "geopotential_height_30hPa","geopotential_height_10hPa",
    "relative_humidity_925hPa","relative_humidity_850hPa",
    "relative_humidity_700hPa","relative_humidity_500hPa","relative_humidity_300hPa",
    "cloud_cover_925hPa","cloud_cover_850hPa","cloud_cover_700hPa",
    "cloud_cover_500hPa","cloud_cover_300hPa",
    "vertical_velocity_1000hPa","vertical_velocity_925hPa","vertical_velocity_850hPa",
    "vertical_velocity_700hPa","vertical_velocity_600hPa","vertical_velocity_500hPa",
    "vertical_velocity_400hPa","vertical_velocity_300hPa",
    "windspeed_925hPa","winddirection_925hPa",
    "windspeed_850hPa","winddirection_850hPa",
    "windspeed_700hPa","winddirection_700hPa",
    "windspeed_500hPa","winddirection_500hPa",
    "windspeed_300hPa","winddirection_300hPa",
    "windspeed_250hPa","winddirection_250hPa",
    "windspeed_200hPa","winddirection_200hPa",
    "windspeed_100hPa","winddirection_100hPa",
    "windspeed_50hPa","winddirection_50hPa",
    "windspeed_10hPa","winddirection_10hPa",
    "cloud_cover_10hPa","relative_humidity_10hPa",
    "temperature_50hPa","temperature_30hPa","temperature_10hPa",
])

FORECAST_MODELS = [
    "ecmwf_ifs025", "gfs_global", "icon_global", "icon_eu",
    "gem_global", "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe", "cma_grapes_global",
]

MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
    "?latitude=46.35&longitude=30.90"
    "&hourly=wave_height,wave_direction,wave_period,"
    "wind_wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature"
    "&timezone=Europe/Kiev&forecast_days=5"
)

def fetch_marine():
    try:
        req = urllib.request.Request(MARINE_URL, headers={"User-Agent": "weather-verifier/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
        h = data.get("hourly", {})
        if not h.get("time"): return None
        times = h["time"]
        result = []
        for i, t in enumerate(times):
            result.append({
                "time":                  t,
                "wave_height":           h.get("wave_height",             [None]*len(times))[i],
                "wave_direction":        h.get("wave_direction",          [None]*len(times))[i],
                "wave_period":           h.get("wave_period",             [None]*len(times))[i],
                "wind_wave_height":      h.get("wind_wave_height",        [None]*len(times))[i],
                "swell_wave_height":     h.get("swell_wave_height",       [None]*len(times))[i],
                "swell_wave_period":     h.get("swell_wave_period",       [None]*len(times))[i],
                "sea_surface_temp":      h.get("sea_surface_temperature", [None]*len(times))[i],
            })
        return result
    except Exception as e:
        print(f"  [AI] Marine API error: {e}")
        return None

def _aggregate_marine_one_day(day_recs):
    import math
    if not day_recs: return None

    def avg(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(sum(vals)/len(vals), 1) if vals else None

    def mx(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(max(vals), 1) if vals else None

    sst_vals = [r["sea_surface_temp"] for r in day_recs if r.get("sea_surface_temp") is not None]
    sst = round(sum(sst_vals)/len(sst_vals), 1) if sst_vals else None

    dir_vals = [r["wave_direction"] for r in day_recs if r.get("wave_direction") is not None]
    if dir_vals:
        sx = sum(math.sin(math.radians(d)) for d in dir_vals)
        sy = sum(math.cos(math.radians(d)) for d in dir_vals)
        wave_dir = round((math.degrees(math.atan2(sx, sy)) + 360) % 360)
        dirs = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"]
        wave_dir_str = dirs[int((wave_dir+22.5)/45)%8]
    else:
        wave_dir_str = "?"

    return {
        "sst":              sst,
        "wave_height_max":  mx("wave_height"),
        "wave_height_avg":  avg("wave_height"),
        "wave_dir":         wave_dir_str,
        "wave_period":      avg("wave_period"),
        "wind_wave_max":    mx("wind_wave_height"),
        "swell_height_max": mx("swell_wave_height"),
        "swell_period":     avg("swell_wave_period"),
    }

def aggregate_marine_days(marine_data, dates):
    """Агрегаты моря по каждой дате из dates (список 'YYYY-MM-DD'), дневные часы 06-21."""
    if not marine_data: return {}
    result = {}
    for date in dates:
        day_recs = [r for r in marine_data
                    if r["time"][:10] == date
                    and 6 <= int(r["time"][11:13]) <= 21]
        if not day_recs:
            day_recs = [r for r in marine_data if r["time"][:10] == date]
        agg = _aggregate_marine_one_day(day_recs)
        if agg: result[date] = agg
    return result

def _wave_str(val_m):
    """Высота волны: < 1м → сантиметры, иначе метры."""
    if val_m is None: return "?"
    if val_m < 1.0:
        return f"{round(val_m * 100)} см"
    return f"{val_m} м"

def _period_str(val_s):
    """Период волны → целые секунды."""
    if val_s is None: return "?"
    return f"{round(val_s)} с"

def fmt_marine(m, today_str=None):
    """Строки данных моря для промпта (один день)."""
    if not m: return ["  Данные недоступны"]
    lines = []
    if m.get("sst") is not None:
        lines.append(f"  Температура воды: {m['sst']}°C")
    wh = m.get("wave_height_max")
    wa = m.get("wave_height_avg")
    if wh is not None:
        lines.append(f"  Высота волны: макс {_wave_str(wh)}, ср {_wave_str(wa)}, направление {m.get('wave_dir','?')}, период {_period_str(m.get('wave_period'))}")
    if m.get("wind_wave_max") is not None:
        lines.append(f"  Ветровое волнение: {_wave_str(m['wind_wave_max'])}")
    if m.get("swell_height_max") is not None:
        lines.append(f"  Зыбь: {m['swell_height_max']}м, период {m.get('swell_period')}с")
    return lines

def load_real_sea_temp():
    """Реальные замеры температуры воды: ГМЦ ЧАМ (Telegram) + TikTok-каналы. Берём последние записи."""
    sources = []
    try:
        path = os.path.join(BASE_DIR, "data", "hmcbas_telegram_sea_temp.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data:
            last = data[-1]
            sources.append({
                "source": "ГМЦ ЧАМ (Telegram)",
                "date": (last.get("timestamp") or "")[:10],
                "temp": last.get("sea_temp"),
            })
    except Exception as e:
        print(f"  [AI] Реальные замеры (ГМЦ ЧАМ) недоступны: {e}")
    try:
        path = os.path.join(BASE_DIR, "data", "tiktok_sea_temp.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data:
            last = data[-1]
            beach = last.get("beach") or "пляж не указан"
            sources.append({
                "source": f"TikTok ({last.get('channel', '?')}, {beach})",
                "date": last.get("date") or (last.get("timestamp") or "")[:10],
                "temp": last.get("sea_temp"),
            })
    except Exception as e:
        print(f"  [AI] Реальные замеры (TikTok) недоступны: {e}")
    return sources

def fmt_real_sea_temp(sources, forecast_sst=None):
    """Строки промпта: реальные замеры температуры воды + сравнение с прогнозом модели.
    Если реальные замеры ниже прогноза — явно просим модель занизить прогноз на след. дни."""
    temps = [s["temp"] for s in sources if s.get("temp") is not None]
    if not temps:
        return []
    lines = ["РЕАЛЬНЫЕ ЗАМЕРЫ ТЕМПЕРАТУРЫ ВОДЫ (последние доступные, не модельные):"]
    for s in sources:
        if s.get("temp") is not None:
            lines.append(f"  {s['source']}, {s['date']}: {s['temp']}°C")
    real_avg = round(sum(temps) / len(temps), 1)
    if forecast_sst is not None:
        diff = round(real_avg - forecast_sst, 1)
        lines.append(f"  Модельный прогноз (Open-Meteo) на сегодня: {forecast_sst}°C")
        if diff <= -0.3:
            lines.append(
                f"  ВАЖНО: реальные замеры ниже модельного прогноза на {abs(diff)}°C. "
                f"Модель Open-Meteo систематически завышает температуру воды в такие периоды. "
                f"При описании ближайших дней делай поправку ВНИЗ примерно на эту величину "
                f"относительно прогнозных цифр ниже — не озвучивай прогноз модели буквально."
            )
        elif diff >= 0.3:
            lines.append(
                f"  Реальные замеры выше модельного прогноза на {diff}°C — "
                f"расхождение в другую сторону, но тоже учти при описании ближайших дней."
            )
        else:
            lines.append("  Реальные замеры согласуются с прогнозом модели — расхождений нет.")
    lines.append("")
    return lines

def fetch_one_model(model):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&current=temperature_2m"
        f"&models={model}"
        f"&forecast_days=7"
        f"&timezone={TIMEZONE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def fetch_ensemble():
    all_hourly = []
    times = None
    data_time = None
    for model in FORECAST_MODELS:
        try:
            data = fetch_one_model(model)
            h = data.get("hourly", {})
            if not h.get("time"): continue
            if times is None: times = h["time"]
            if data_time is None:
                cur = data.get("current", {})
                data_time = cur.get("time")
            all_hourly.append(h)
            print(f"  [AI] ok {model}")
        except Exception as e:
            print(f"  [AI] skip {model}: {e}")
    if not all_hourly:
        raise RuntimeError("Ни одна модель не ответила")
    print(f"  [AI] Усредняю {len(all_hourly)} моделей...")
    n = len(times)
    all_keys = set()
    for h in all_hourly: all_keys.update(h.keys())
    all_keys.discard("time")
    merged = {"time": times}
    for key in all_keys:
        cols = [h[key] for h in all_hourly if key in h and h[key] is not None]
        if not cols: merged[key] = [None]*n; continue
        avg = []
        for i in range(n):
            vals = [c[i] for c in cols if i < len(c) and c[i] is not None]
            avg.append(round(sum(vals)/len(vals), 2) if vals else None)
        merged[key] = avg
    return {"hourly": merged, "data_time": data_time}

# ── Агрегация по дням ─────────────────────────────────────────────────────────

def mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def rnd(v, d=1):
    return round(v, d) if v is not None else None

def aggregate_days(data):
    h = data.get("hourly", {})
    times = h.get("time", [])
    n = len(times)

    def col(key):
        arr = h.get(key, [])
        return [arr[i] if i < len(arr) else None for i in range(n)]

    T2m   = col("temperature_2m");   Tapp  = col("apparent_temperature")
    Td    = col("dewpoint_2m");       RH    = col("relative_humidity_2m")
    Prec  = col("precipitation");     PrecP = col("precipitation_probability")
    WC    = col("weathercode");       P     = col("pressure_msl")
    WS    = col("windspeed_10m");     WD    = col("winddirection_10m")
    WG    = col("windgusts_10m");     WS80  = col("windspeed_80m")
    CC    = col("cloudcover");        CAPE  = col("cape")
    LI    = col("lifted_index");      CIN   = col("convective_inhibition")
    VIS   = col("visibility");        FRZ   = col("freezinglevel_height")
    Snow  = col("snowfall")
    CCL   = col("cloud_cover_low");   CCM   = col("cloud_cover_mid")
    CCH   = col("cloud_cover_high")
    T925  = col("temperature_925hPa"); T850 = col("temperature_850hPa")
    T700  = col("temperature_700hPa"); T600 = col("temperature_600hPa")
    T500  = col("temperature_500hPa"); T400 = col("temperature_400hPa")
    T300  = col("temperature_300hPa"); T250 = col("temperature_250hPa")
    T200  = col("temperature_200hPa")
    T50   = col("temperature_50hPa"); T30  = col("temperature_30hPa")
    T10   = col("temperature_10hPa")
    Td925 = col("dewpoint_925hPa");   Td850 = col("dewpoint_850hPa")
    Td700 = col("dewpoint_700hPa");   Td500 = col("dewpoint_500hPa")
    Z925  = col("geopotential_height_925hPa"); Z850 = col("geopotential_height_850hPa")
    Z700  = col("geopotential_height_700hPa"); Z600 = col("geopotential_height_600hPa")
    Z500  = col("geopotential_height_500hPa"); Z400 = col("geopotential_height_400hPa")
    Z300  = col("geopotential_height_300hPa"); Z250 = col("geopotential_height_250hPa")
    Z200  = col("geopotential_height_200hPa"); Z150 = col("geopotential_height_150hPa")
    Z100  = col("geopotential_height_100hPa"); Z50  = col("geopotential_height_50hPa")
    Z30   = col("geopotential_height_30hPa");  Z10  = col("geopotential_height_10hPa")
    RH925 = col("relative_humidity_925hPa");   RH850 = col("relative_humidity_850hPa")
    RH700 = col("relative_humidity_700hPa");   RH500 = col("relative_humidity_500hPa")
    RH300 = col("relative_humidity_300hPa")
    CC925 = col("cloud_cover_925hPa"); CC850 = col("cloud_cover_850hPa")
    CC700 = col("cloud_cover_700hPa"); CC500 = col("cloud_cover_500hPa")
    CC300 = col("cloud_cover_300hPa")
    W1000 = col("vertical_velocity_1000hPa"); W925 = col("vertical_velocity_925hPa")
    W850  = col("vertical_velocity_850hPa");  W700 = col("vertical_velocity_700hPa")
    W600  = col("vertical_velocity_600hPa");  W500 = col("vertical_velocity_500hPa")
    W400  = col("vertical_velocity_400hPa");  W300 = col("vertical_velocity_300hPa")
    WS925 = col("windspeed_925hPa");  WD925 = col("winddirection_925hPa")
    WS850 = col("windspeed_850hPa");  WD850 = col("winddirection_850hPa")
    WS700 = col("windspeed_700hPa");  WD700 = col("winddirection_700hPa")
    WS500 = col("windspeed_500hPa");  WD500 = col("winddirection_500hPa")
    WS300 = col("windspeed_300hPa");  WD300 = col("winddirection_300hPa")
    WS250 = col("windspeed_250hPa");  WD250 = col("winddirection_250hPa")
    WS200 = col("windspeed_200hPa");  WD200 = col("winddirection_200hPa")
    WS100 = col("windspeed_100hPa");  WD100 = col("winddirection_100hPa")
    WS50  = col("windspeed_50hPa");   WD50  = col("winddirection_50hPa")
    WS10  = col("windspeed_10hPa");   WD10  = col("winddirection_10hPa")
    CC10  = col("cloud_cover_10hPa"); RH10  = col("relative_humidity_10hPa")

    # группировка по датам
    from collections import defaultdict
    days = defaultdict(list)
    for i, t in enumerate(times):
        date = t[:10]
        days[date].append(i)

    now_local = datetime.now(timezone.utc).astimezone()
    today_str = now_local.strftime("%Y-%m-%d")

    result = []
    for date, idxs in sorted(days.items()):
        # Только сегодня + 4 дня вперёд
        if date < today_str:
            continue
        if len(result) >= 5:
            break

        def v(arr): return [arr[i] for i in idxs]

        # Ночь/день/вечер разбивка по часам
        hours_of_day = [int(times[i][11:13]) for i in idxs]
        night_idx  = [idxs[j] for j,h in enumerate(hours_of_day) if h < 6 or h >= 21]
        day_idx    = [idxs[j] for j,h in enumerate(hours_of_day) if 6 <= h < 21]

        def sub(arr, sub_idx): return [arr[i] for i in sub_idx if arr[i] is not None]

        T_vals = v(T2m)
        T_valid = [x for x in T_vals if x is not None]

        prec_sum = sum(x for x in v(Prec) if x is not None)
        snow_sum = sum(x for x in v(Snow) if x is not None)

        # Доминантный weathercode
        wc_list = [x for x in v(WC) if x is not None]
        wc_dom = max(set(wc_list), key=wc_list.count) if wc_list else None

        # Омега — знак и величина
        w500_avg = mean(v(W500))
        w700_avg = mean(v(W700))
        w850_avg = mean(v(W850))

        # Ветер — средний и максимальный
        ws_vals = [x for x in v(WS) if x is not None]
        wg_vals = [x for x in v(WG) if x is not None]

        # Изотерма 0°C
        frz_vals = [x for x in v(FRZ) if x is not None]

        import math
        def wmd(ws_a, wd_a):
            pairs=[(ws_a[ii],wd_a[ii]) for ii in idxs if ws_a[ii] is not None and wd_a[ii] is not None]
            if not pairs: return None,None
            u=sum(s*math.sin(math.radians(d)) for s,d in pairs)/len(pairs)
            vv=sum(s*math.cos(math.radians(d)) for s,d in pairs)/len(pairs)
            return rnd(math.sqrt(u*u+vv*vv)),rnd((math.degrees(math.atan2(u,vv))+360)%360)
        ws925m,wd925m=wmd(WS925,WD925); ws850m,wd850m=wmd(WS850,WD850)
        ws700m,wd700m=wmd(WS700,WD700); ws500m,wd500m=wmd(WS500,WD500)
        ws300m,wd300m=wmd(WS300,WD300); ws250m,wd250m=wmd(WS250,WD250)
        ws200m,wd200m=wmd(WS200,WD200)
        ws100m,wd100m=wmd(WS100,WD100); ws50m,wd50m=wmd(WS50,WD50)
        ws10m,wd10m=wmd(WS10,WD10)
        day_data = {
            "date": date,
            "T": {
                "min": rnd(min(T_valid)) if T_valid else None,
                "max": rnd(max(T_valid)) if T_valid else None,
                "app_min": rnd(min((x for x in v(Tapp) if x is not None), default=None)),
                "app_max": rnd(max((x for x in v(Tapp) if x is not None), default=None)),
                "night_mean": rnd(mean(sub(T2m, night_idx))),
                "day_mean": rnd(mean(sub(T2m, day_idx))),
            },
            "Td_mean": rnd(mean(v(Td))), "RH_mean": rnd(mean(v(RH))),
            "vis_min": rnd(min((x for x in v(VIS) if x is not None), default=None)),
            "precip_mm": rnd(prec_sum, 1),
            "precip_prob_max": max((x for x in v(PrecP) if x is not None), default=None),
            "snow_cm": rnd(snow_sum, 1),
            "weathercode_dom": wc_dom, "pressure_mean": rnd(mean(v(P))),
            "wind": {
                "mean_kmh": rnd(mean(ws_vals)), "max_kmh": rnd(max(ws_vals)) if ws_vals else None,
                "gust_max_kmh": rnd(max(wg_vals)) if wg_vals else None,
                "spd80": rnd(mean([x for x in v(WS80) if x is not None])),
            },
            "cloud": {
                "total": rnd(mean(v(CC))), "low": rnd(mean(v(CCL))),
                "mid": rnd(mean(v(CCM))), "high": rnd(mean(v(CCH))),
                "c925": rnd(mean(v(CC925))), "c850": rnd(mean(v(CC850))),
                "c700": rnd(mean(v(CC700))), "c500": rnd(mean(v(CC500))),
                "c300": rnd(mean(v(CC300))), "c10": rnd(mean(v(CC10))),
            },
            "conv": {
                "CAPE_max": rnd(max((x for x in v(CAPE) if x is not None), default=None)),
                "CAPE_mean": rnd(mean(v(CAPE))),
                "LI_min": rnd(min((x for x in v(LI) if x is not None), default=None)),
                "CIN": rnd(mean(v(CIN))),
            },
            "tp": {
                "T925":rnd(mean(v(T925))),"T850":rnd(mean(v(T850))),"T700":rnd(mean(v(T700))),
                "T600":rnd(mean(v(T600))),"T500":rnd(mean(v(T500))),"T400":rnd(mean(v(T400))),
                "T300":rnd(mean(v(T300))),"T250":rnd(mean(v(T250))),"T200":rnd(mean(v(T200))),
                "Td925":rnd(mean(v(Td925))),"Td850":rnd(mean(v(Td850))),
                "Td700":rnd(mean(v(Td700))),"Td500":rnd(mean(v(Td500))),
                "def850":rnd((mean(v(T850)) or 0)-(mean(v(Td850)) or 0),1),
                "def700":rnd((mean(v(T700)) or 0)-(mean(v(Td700)) or 0),1),
                "T50":rnd(mean(v(T50))),"T30":rnd(mean(v(T30))),"T10":rnd(mean(v(T10))),
            },
            "gp": {
                "Z925":rnd(mean(v(Z925))),"Z850":rnd(mean(v(Z850))),"Z700":rnd(mean(v(Z700))),
                "Z600":rnd(mean(v(Z600))),"Z500":rnd(mean(v(Z500))),"Z400":rnd(mean(v(Z400))),
                "Z300":rnd(mean(v(Z300))),"Z250":rnd(mean(v(Z250))),"Z200":rnd(mean(v(Z200))),
                "Z150":rnd(mean(v(Z150))),"Z100":rnd(mean(v(Z100))),
                "Z50":rnd(mean(v(Z50))),"Z30":rnd(mean(v(Z30))),"Z10":rnd(mean(v(Z10))),
            },
            "rh": {
                "RH925":rnd(mean(v(RH925))),"RH850":rnd(mean(v(RH850))),
                "RH700":rnd(mean(v(RH700))),"RH500":rnd(mean(v(RH500))),
                "RH300":rnd(mean(v(RH300))),"RH10":rnd(mean(v(RH10))),
            },
            "omega": {
                "W1000":rnd(mean(v(W1000)),3),"W925":rnd(mean(v(W925)),3),
                "W850":rnd(mean(v(W850)),3),"W700":rnd(mean(v(W700)),3),
                "W600":rnd(mean(v(W600)),3),"W500":rnd(mean(v(W500)),3),
                "W400":rnd(mean(v(W400)),3),"W300":rnd(mean(v(W300)),3),
            },
            "wp": {
                "925":{"s":ws925m,"d":wd925m},"850":{"s":ws850m,"d":wd850m},
                "700":{"s":ws700m,"d":wd700m},"500":{"s":ws500m,"d":wd500m},
                "300":{"s":ws300m,"d":wd300m},"250":{"s":ws250m,"d":wd250m},
                "200":{"s":ws200m,"d":wd200m},
                "100":{"s":ws100m,"d":wd100m},"50":{"s":ws50m,"d":wd50m},
                "10":{"s":ws10m,"d":wd10m},
            },
            "freeze_level_m": rnd(mean(frz_vals)),
        }
        result.append(day_data)

    return result

# ── Хэш данных для проверки изменений ────────────────────────────────────────

def data_hash(days):
    # Хэш по ключевым полям — если не изменился, не перегенерируем
    key = json.dumps([{
        "date": d["date"],
        "T": d["T"],
        "precip_mm": d["precip_mm"],
        "gp_Z500": d.get("gp", {}).get("Z500"),
    } for d in days], sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]

# ── Промпт ────────────────────────────────────────────────────────────────────

WMO_CODES = {
    0:"ясно", 1:"преимущественно ясно", 2:"переменная облачность", 3:"пасмурно",
    45:"туман", 48:"изморозь", 51:"слабая морось", 53:"морось", 55:"сильная морось",
    61:"слабый дождь", 63:"дождь", 65:"сильный дождь",
    71:"слабый снег", 73:"снег", 75:"сильный снег", 77:"снежная крупа",
    80:"ливень", 81:"сильный ливень", 82:"очень сильный ливень",
    85:"снегопад", 86:"сильный снегопад",
    95:"гроза", 96:"гроза с градом", 99:"сильная гроза с градом",
}

MONTH_RU = ['января','февраля','марта','апреля','мая','июня',
            'июля','августа','сентября','октября','ноября','декабря']

def fmt_date(dt):
    return f"{dt.day} {MONTH_RU[dt.month-1]}"

def _get_mode(now_utc_hour):
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

def build_prompt(days, marine=None, data_time=None, verification_text=None, real_sea_temp=None):
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
    if tend_start >= tend_end:
        tend_block = f"## Тенденция, после {fmt_date(tend_end)}"
    elif tend_start.month == tend_end.month:
        tend_block = f"## Тенденция, {tend_start.day}–{fmt_date(tend_end)}"
    else:
        tend_block = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"
    # Если месяц одинаковый — компактный формат "9–11 июня"
    if next_start.month == next_end.month:
        next_block = f"## Последующие дни, {next_start.day}–{fmt_date(next_end)}"
    else:
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

    _cur_date_v, _cur_period_v, _, _ = verification.current_and_previous_period()
    _period_bounds = dict((p[0], (p[1], p[2])) for p in verification.PERIODS)
    _h_start, _h_end = _period_bounds[_cur_period_v]
    _cur_dt_v = datetime.strptime(_cur_date_v, "%Y-%m-%d")
    period_label_hint = (
        f"{_cur_dt_v.day:02d}.{_cur_dt_v.month:02d}, СТРОГО с {_h_start:02d}:00 до {_h_end:02d}:00 "
        f"по местному времени"
    )

    struct = []
    step = 1
    if verification_text:
        struct.append(f"{step}. ## 📊 Точность прогноза — кратко прокомментируй сверку прогноза с фактом ниже (1-2 предложения: насколько точен был прогноз, в чём разошёлся).")
        step += 1
    struct += [
        f"{step}. {block1} — {b1_desc}",
        f"{step+1}. {block2} — {b2_desc}",
        f"{step+2}. {next_block} — общий обзор, 3-4 предложения живым языком без цифр уровней атмосферы:",
        "   - Температурный фон днём и ночью",
        "   - Осадки: вероятность в %, когда и где",
        "   - Комфортность: влажность, ветер по-человечески",
        "   - Стратосферу не упоминать совсем в этом блоке",
        f"{step+3}. ## ⚠️ Предупреждения — только если есть реальные риски. Если рисков нет — пропусти.",
        f"{step+4}. ## 🌊 Море — блок для пляжников, 3-4 предложения живым языком:",
        "   - Температура воды: комфортно ли купаться, для кого (дети, взрослые)",
        "   - Волнение: не в метрах — а 'штиль', 'лёгкое волнение', 'умеренное'",
        "   - Общий вывод: идти на пляж или нет, лучшее время дня для купания",
        "   - Если есть медузы по сезону или апвеллинг — упомяни",
        "   - Никаких технических терминов, только человеческий язык",
        f"{step+5}. {tend_block} — 3-4 предложения живым языком, без цифр уровней атмосферы:",
        "   - Общий характер погоды: жара держится / идёт похолодание / нестабильность нарастает",
        "   - Когда и как изменится: плавно или резко, с чем связано (фронт, циклон, антициклон)",
        "   - Температурный фон: просто 'жарко', 'тепло', 'прохладно' — без геопотенциала",
        "   - Если стратосфера даёт сигнал на смену режима — скажи по-человечески: 'полярный вихрь устойчив, резких перемен не ожидается'",
        "   - Завершить одной фразой-прогнозом: когда следующая смена погоды",
    ]

    period_summary_instruction = (
        f"\n\nВ САМОМ КОНЦЕ ответа, ПОСЛЕ всех разделов выше, добавь ещё один служебный блок "
        f"(он не будет показан пользователю, не используй заголовок \"##\" для него) — "
        f"строго в таком формате:\n"
        f"<PERIOD_SUMMARY>\n"
        f"Краткое (1-2 предложения) описание погоды СТРОГО в интервале {period_label_hint} "
        f"(НЕ раньше и НЕ позже этого интервала, даже если в остальном тексте ты пишешь про другой период): "
        f"температура, осадки/явления, ветер. Только факты по существу, без вводных слов.\n"
        f"</PERIOD_SUMMARY>"
    )

    # Форматируем время данных open-meteo для промпта
    if data_time:
        try:
            dt_parsed = datetime.strptime(data_time[:16], "%Y-%m-%dT%H:%M")
            data_time_str = dt_parsed.strftime("%d.%m.%Y %H:%M местного")
        except Exception:
            data_time_str = data_time
    else:
        data_time_str = "неизвестно"

    lines = [
        f"Время генерации: {now_str}",
        f"Данные open-meteo обновлены: {data_time_str}",
        f"Место: Одесса, Украина (46.43°N, 30.74°E, побережье Чёрного моря)",
        "",
        "Ты — синоптик-коммуникатор. Твоя задача: написать прогноз ОДНОВРЕМЕННО понятный",
        "обычному человеку И информативный для специалиста.",
        "",
        "ГЛАВНЫЙ ПРИНЦИП: пиши как объясняешь другу, который спросил 'ну что там с погодой?'.",
        "Живые, образные формулировки. Не 'конвективная нестабильность' — а 'воздух перегрет,",
        "возможны грозы'. Не 'геопотенциал растёт' — а 'антициклон укрепляется, будет сухо'.",
        "Технические термины — только когда они добавляют смысл, не ради демонстрации.",
        "",
        "СТРУКТУРА КАЖДОГО ВРЕМЕННОГО БЛОКА:",
        "1. Сразу после заголовка — резюме одной строкой жирным: **Жарко, сухо, без осадков**",
        "   Это краткий ответ для тех, кто читает только первую строку.",
        "2. Основной текст 3-4 предложения живым языком:",
        "   - Температура: не просто цифры, а ощущения ('будет жарко', 'комфортная прохлада')",
        "   - Вероятность осадков: всегда в % ('вероятность дождя около 30%')",
        "   - Ощущаемая температура: упоминай если заметно отличается от реальной",
        "   - УФ-индекс: при малооблачной летней погоде обязательно ('УФ-индекс высокий, 7-8')",
        "   - Ветер: по-человечески ('лёгкий бриз', 'освежающий ветерок', 'порывистый ветер')",
        "   - Комфорт: точка росы выше 18°C — упомяни 'будет душно'; ниже 10°C — 'воздух сухой и комфортный'",
        "",
        "ВАЖНО: пиши строго в будущем времени — погода ещё не наступила, это прогноз.",
        "Не 'устанавливается', 'наблюдается', 'составляет' — а 'установится', 'ожидается', 'составит'.",
        "Сегодняшний день тоже прогноз, не факт — используй будущее время.",
        "Скорость ветра указывай ТОЛЬКО в м/с (метрах в секунду). Никаких км/ч.",
        "Также учитывай стратосферные параметры (геопотенциал и температура 150-10 гПа):",
        "если видна аномалия — упомяни влияние на среднесрочный прогноз.",
        "",
        "В САМОМ КОНЦЕ всего текста добавь технический блок для специалистов:",
        "## 🔬 Параметры анализа",
        "Одной строкой перечисли ВСЕ величины которые были переданы тебе для анализа —",
        "без значений, только названия параметров через запятую.",
        "Формат: 'Для анализа использовались: температура 2м, ощущаемая температура, точка росы, ...'",
        "Если упоминаешь конкретный уровень атмосферы в гПа (например, 700 гПа, 500 гПа,",
        "300 гПа и т.д.), указывай рядом примерную высоту в МЕТРАХ (целым числом, округли",
        "до десятков) из переданных данных геопотенциала (ГЕОПОТЕНЦИАЛ / Стратосфера Z),",
        "БЕЗ скобок и БЕЗ знака ~ — пиши слитной фразой, высоту указывай сокращённо \"м\",",
        "например: \"на уровне 700 гПа 3000 м\". Не указывай высоту в километрах.",
        "Старайся не перегружать текст цифрами в описании атмосферы (геопотенциал, давление,",
        "вертикальные скорости, влажность по уровням) — где точное число не критично для",
        "пользователя, используй качественное описание (например, 'воздух заметно проседает',",
        "'хребет высокого давления усиливается', 'влажность в среднем ярусе повышенная').",
        "ТЕМПЕРАТУРНЫЙ ХОД: при описании ночного периода — указывай когда ожидается минимум",
        "(середина ночи или предрассветные часы) и само значение. Если предрассветный минимум",
        "ниже ночного — упомяни оба: 'снижение до X°C в середине ночи, а в предрассветные часы до Y°C'.",
        "При описании дневного периода — указывай когда ожидается максимум (около полудня или",
        "во второй половине дня): 'температура достигнет X°C около 14-15 часов'.",
        "При описании дневного хода пиши: 'поднимется от X°C до Y°C, при средних дневных значениях около Z°C'.",
        "ПРОШЕДШИЕ ПЕРИОДЫ: если описываешь период который уже прошёл (ночь в утреннем выпуске,",
        "утро в дневном и т.д.) — используй прошедшее время без 'бы':",
        "'По прогнозу, ночью температура опускалась до X°C' (не 'опустилась бы').",
        "Для каждого дня в данных ниже указан день недели (например 'Пн', 'Вт') — "
        "используй ЕГО, не вычисляй и не угадывай день недели сам. Можно писать "
        "и день недели, и дату вместе ('в субботу, 21 июня') или просто день недели "
        "('в субботу') — но всегда строго тот, что указан в данных.",
    ]
    if mode_hint:
        lines.append(mode_hint)
    lines += [
        "",
        "ДАННЫЕ ПРОГНОЗА (ансамбль 8 моделей: ECMWF/GFS/ICON/GEM/UKMO/ARPEGE/CMA, агрегаты по дням):",
        "",
    ]

    day_labels = ["СЕГОДНЯ", "ЗАВТРА", "День +2", "День +3", "День +4"]
    WEEKDAY_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    for i, d in enumerate(days):
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        weekday_label = WEEKDAY_RU[dt.weekday()]
        label = day_labels[i] if i < len(day_labels) else f"День +{i}"
        wc_label = WMO_CODES.get(d.get("weathercode_dom"), f"код {d.get('weathercode_dom')}")
        tp=d.get("tp",{}); gp=d.get("gp",{}); rh=d.get("rh",{})
        om=d.get("omega",{}); wp=d.get("wp",{}); cv=d.get("conv",{})
        cl=d.get("cloud",{}); ws=d.get("wind",{})
        def wdir(deg):
            if deg is None: return "?"
            return ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"][int((deg+22.5)/45)%8]
        lines += [
            f"-- {label} ({dt.strftime('%d.%m')}, {weekday_label}) --",
            f"  T: {d['T']['min']}..{d['T']['max']}C  ощущ {d['T']['app_min']}..{d['T']['app_max']}C  день {d['T']['day_mean']}C  ночь {d['T']['night_mean']}C",
            f"  Td={d['Td_mean']}C  RH={d['RH_mean']}%  P={d['pressure_mean']}гПа  вид.мин={d.get('vis_min')}м",
            f"  Осадки: {d['precip_mm']}мм  вер.до {d['precip_prob_max']}%  снег {d['snow_cm']}см",
            f"  Погода: {wc_label}",
            f"  Ветер 10м: ср {ws.get('mean_kmh')} макс {ws.get('max_kmh')} пор {ws.get('gust_max_kmh')} км/ч  80м: {ws.get('spd80')} км/ч",
            f"  Облачность: общ {cl.get('total')}% низ {cl.get('low')}% ср {cl.get('mid')}% выс {cl.get('high')}%",
            f"  Облачность по уровням: 925={cl.get('c925')}% 850={cl.get('c850')}% 700={cl.get('c700')}% 500={cl.get('c500')}% 300={cl.get('c300')}% 10={cl.get('c10')}%",
            f"  Нулевая изотерма: {d['freeze_level_m']}м",
            f"  КОНВЕКЦИЯ: CAPE макс/ср={cv.get('CAPE_max')}/{cv.get('CAPE_mean')} Дж/кг  LI мин={cv.get('LI_min')}  CIN={cv.get('CIN')}",
            f"  ПРОФИЛЬ Т (C): 925={tp.get('T925')} 850={tp.get('T850')} 700={tp.get('T700')} 600={tp.get('T600')} 500={tp.get('T500')} 400={tp.get('T400')} 300={tp.get('T300')} 250={tp.get('T250')} 200={tp.get('T200')}",
            f"  Точка росы: 925={tp.get('Td925')} 850={tp.get('Td850')} 700={tp.get('Td700')} 500={tp.get('Td500')}  деф T-Td: 850={tp.get('def850')} 700={tp.get('def700')}",
            f"  Стратосфера T: 50={tp.get('T50')}C 30={tp.get('T30')}C 10={tp.get('T10')}C",
            f"  ГЕОПОТЕНЦИАЛ (м): 925={gp.get('Z925')} 850={gp.get('Z850')} 700={gp.get('Z700')} 600={gp.get('Z600')} 500={gp.get('Z500')} 400={gp.get('Z400')} 300={gp.get('Z300')} 250={gp.get('Z250')} 200={gp.get('Z200')} 150={gp.get('Z150')} 100={gp.get('Z100')}",
            f"  Стратосфера Z: 150={gp.get('Z150')} 100={gp.get('Z100')} 50={gp.get('Z50')} 30={gp.get('Z30')} 10={gp.get('Z10')}",
            f"  ВЛАЖНОСТЬ (%): 925={rh.get('RH925')} 850={rh.get('RH850')} 700={rh.get('RH700')} 500={rh.get('RH500')} 300={rh.get('RH300')} 10={rh.get('RH10')}",
            f"  ОМЕГА (Па/с, -=восх): 1000={om.get('W1000')} 925={om.get('W925')} 850={om.get('W850')} 700={om.get('W700')} 600={om.get('W600')} 500={om.get('W500')} 400={om.get('W400')} 300={om.get('W300')}",
            f"  ВЕТЕР: 925={wp.get('925',{}).get('s')}км/ч {wdir(wp.get('925',{}).get('d'))}  850={wp.get('850',{}).get('s')} {wdir(wp.get('850',{}).get('d'))}  700={wp.get('700',{}).get('s')} {wdir(wp.get('700',{}).get('d'))}  500={wp.get('500',{}).get('s')} {wdir(wp.get('500',{}).get('d'))}  300={wp.get('300',{}).get('s')} {wdir(wp.get('300',{}).get('d'))}  200={wp.get('200',{}).get('s')} {wdir(wp.get('200',{}).get('d'))}  100={wp.get('100',{}).get('s')} {wdir(wp.get('100',{}).get('d'))}  50={wp.get('50',{}).get('s')} {wdir(wp.get('50',{}).get('d'))}  10={wp.get('10',{}).get('s')} {wdir(wp.get('10',{}).get('d'))}",
            "",
        ]

    # Реальные замеры температуры воды (не модельные) — перед прогнозом по дням
    if real_sea_temp:
        forecast_sst_today = None
        if marine and days:
            m0 = marine.get(days[0]["date"])
            if m0:
                forecast_sst_today = m0.get("sst")
        lines += fmt_real_sea_temp(real_sea_temp, forecast_sst_today)

    # Marine данные в промпт (по дням, как и суша)
    if marine:
        lines += ["СОСТОЯНИЕ ЧЁРНОГО МОРЯ ПО ДНЯМ (точка 8 км от берега):", ""]
        for i, d in enumerate(days):
            m = marine.get(d["date"])
            if not m: continue
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            label = day_labels[i] if i < len(day_labels) else f"День +{i}"
            lines.append(f"-- {label} ({dt.strftime('%d.%m')}) --")
            lines += fmt_marine(m)
        lines.append("")

    if verification_text:
        lines += [verification_text, ""]

    lines += [
        "СТРУКТУРА ОТВЕТА (строго, используй точные заголовки):",
    ] + struct + [
        period_summary_instruction,
    ] + [
        f"N. ## 🌊 Море — температура воды, волнение, условия на море (1-2 предложения)",
        "",
        "Не используй таблицы. Не повторяй цифры из данных дословно — интерпретируй их синоптически.",
    ]

    return "\n".join(lines)

# ── Запрос к Claude API ───────────────────────────────────────────────────────

def preprocess_tts(text):
    import re
    # Аббревиатуры
    text = re.sub(r'(?i)индекс(\s+неустойчивости)?\s+LI\b', 'индекс неустойчивости', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    text = text.replace('CAPE', 'индекс конвективной доступной энергии')
    text = text.replace('CIN', 'конвективное торможение')
    # Единицы давления
    text = text.replace('гПа', 'гектопаскалей')
    # Тильда (приближение) и метры
    text = text.replace('~', 'около ')
    text = re.sub(r'(\d)\s?м(?!/с)\b', r'\1 метров', text)
    # Градусы со склонением
    def _grad(n):
        try: n = abs(int(float(str(n).replace(',','.')))) % 100
        except: return 'градусов'
        if 11 <= n <= 19: return 'градусов'
        r = n % 10
        if r == 1: return 'градус'
        if 2 <= r <= 4: return 'градуса'
        return 'градусов'
    text = re.sub(r'(-?\d+(?:[.,]\d+)?)\s*°C', lambda m: f"{m.group(1)} {_grad(m.group(1))}", text)
    text = text.replace('°C', 'градусов')
    # км (высота) — перед обработкой м/с
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*км(?!/)\b', r'\1 километра', text)
    # схлопываем повторные "м/с" в перечислениях: "3-5 м/с, с порывами до 7 м/с" -> "3-5, с порывами до 7 м/с"
    text = re.sub(r'(\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?)\s*м/с(?=[^.!?]*?м/с)', r'\1', text)
    # м/с
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*м/с', r'\1 метров в секунду', text)
    # мм осадков
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*мм', r'\1 миллиметра', text)
    # см (снег)
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*см\b', r'\1 сантиметра', text)
    # Дж/кг
    text = text.replace('Дж/кг', 'джоулей на килограмм')
    # Десятичные дроби
    def decimal_to_words(m):
        int_part = m.group(1)
        dec_part = m.group(2)
        if len(dec_part) == 1:
            words = {'1':'одна','2':'две','3':'три','4':'четыре',
                     '5':'пять','6':'шесть','7':'семь','8':'восемь','9':'девять','0':'ноль'}
            form = 'десятая' if dec_part == '1' else 'десятых'
            return f"{int_part} целых {words.get(dec_part, dec_part)} {form}"
        return f"{int_part} целых {dec_part} сотых"
    text = re.sub(r'(\d+)\.\s?(\d{1,2})\b', decimal_to_words, text)
    text = re.sub(r'(\d+),\s?(\d{1,2})\b', decimal_to_words, text)
    # % со склонением
    def _proc(n):
        try: n = abs(int(n)) % 100
        except: return 'процентов'
        if 11 <= n <= 19: return 'процентов'
        r = n % 10
        if r == 1: return 'процент'
        if 2 <= r <= 4: return 'процента'
        return 'процентов'
    text = re.sub(r'(\d+)\s*%', lambda m: f"{m.group(1)} {_proc(m.group(1))}", text)
    # Убрать решётки markdown
    text = re.sub(r'#+\s*', '', text)
    # Убрать ** *
    text = re.sub(r'\*+', '', text)
    return text

async def _generate_tts_async(text, out_path):
    text = preprocess_tts(text)
    communicate = edge_tts.Communicate(text, voice="ru-RU-SvetlanaNeural", rate="+0%")
    await communicate.save(out_path)

def generate_tts(text, out_path):
    try:
        asyncio.run(_generate_tts_async(text, out_path))
        size_kb = os.path.getsize(out_path) // 1024
        print(f"  [TTS] Сохранено: {out_path} ({size_kb} кб)")
    except Exception as e:
        print(f"  [TTS] Ошибка: {e}")

def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    return resp["content"][0]["text"]

GEMINI_STYLE_INSTRUCTION = (
    "Пиши как опытный синоптик: не перечисляй параметры, а объясняй синоптическую причину ситуации: "
    "откуда пришла воздушная масса, какой процесс управляет погодой (anticyclone, ложбина, фронт). "
    "Каждый параметр упоминай только если он объясняет погоду: например, не просто 'влажность 72%', "
    "а 'влажность на 850 гПа выросла до 72% — воздух ближается к насыщению, что повышает вероятность осадков'. "
    "Избегай монотонного повторения структуры 'ночь→день→уровни→ветер' в каждом блоке: "
    "объединяй близкие по смыслу параметры в одно связное предложение. "
    "Раздел 'Море' пиши с деталями: направление волн, ясно ли условия для купания/судоходства. "
    "В предупреждениях пиши конкретно: 'гроза возможна в вечерние часы', не 'средний уровень вероятности грозовой активности'. "
    "Каждый блок описывает строго свой период — не заглядывай в следующий: если блок называется 'Сегодня вечером', пиши только про вечер, ночные и утренние значения следующих суток — в следующем блоке. "
    "Стиль: профессионально, чётко, без канцелярита. Образные обороты допустимы если точны по смыслу. "
    "Числа: температура и ветер диапазоном (например, 18-19 градусов, 2-3 м/с), "
    "все значения целые. Уровни атмосферы: 850 гПа, 500 гПа, 10 гПа — без пояснений в скобках."
)

def call_gemini(prompt, api_key, model=GEMINI_MODEL):
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": GEMINI_STYLE_INSTRUCTION}]}
    }).encode()

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
        resp = json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"HTTP Error {e.code}: {e.reason} | {body[:300]}")
    return resp["candidates"][0]["content"]["parts"][0]["text"]

def generate_gemini_analysis(prompt, now_iso, current_hash, days, run_key, mode=None):
    api_key = load_gemini_api_key()
    if not api_key:
        print("  [AI-Gemini] GEMINI_API_KEY не найден -- пропускаю")
        return
    try:
        text = call_gemini(prompt, api_key)
        text, _period_summary = verification.extract_period_summary(text)
        if _period_summary:
            _verif_path = os.path.join(BASE_DIR, "data", "verification_snapshots.json")
            verification.save_current_period_summary(_verif_path, _period_summary)
            import subprocess as _sp3
            _sp3.run(["git", "-C", BASE_DIR, "add", "data/verification_snapshots.json"], capture_output=True)
    except Exception as e:
        print(f"  [AI-Gemini] Ошибка Gemini API: {e} -- сохраняю pending")
        _existing = {}
        if os.path.exists(OUTPUT_FILE_GEMINI):
            try:
                with open(OUTPUT_FILE_GEMINI, encoding="utf-8") as _f:
                    _existing = json.load(_f)
            except Exception:
                pass
        _existing["pending"] = True
        _existing["pending_run_key"] = run_key
        _existing["changed"] = False
        with open(OUTPUT_FILE_GEMINI, "w", encoding="utf-8") as _f:
            json.dump(_existing, _f, ensure_ascii=False, indent=2)
        return

    result = {
        "generated_at": now_iso,
        "last_checked": now_iso,
        "changed": True,
        "data_hash": current_hash,
        "days_count": len(days),
        "text": text,
        "last_run_key": run_key,
        "provider": "gemini",
        "mode": mode,
    }
    with open(OUTPUT_FILE_GEMINI, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  [AI-Gemini] ✅ Анализ сохранён ({len(text)} символов)")

# ── Расписание (data/ai_schedule.json) ─────────────────────────────────────────

SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "ai_schedule.json")

def load_schedule():
    default = {"time_points": [], "model_triggers": [], "tolerance_min": 20}
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            default.update(d)
        except Exception as e:
            print(f"  [AI] Ошибка чтения ai_schedule.json: {e}")
    return default

def _provider_match(entry_provider, provider):
    """Проверяет, входит ли provider в entry_provider (строка/список/отсутствует=все)."""
    if entry_provider is None:
        return True
    if isinstance(entry_provider, str):
        return entry_provider == provider
    return provider in entry_provider

def _matching_time_point(schedule, now_utc, provider):
    """Возвращает строку 'HH:MM' если сейчас попадаем в точку расписания для provider, иначе None."""
    tol = schedule.get("tolerance_min", 20) * 60
    weekday = (now_utc.weekday() + 1) % 7  # 0=Вс..6=Сб (как в ai_schedule.py)
    for tp in schedule.get("time_points", []):
        if not _provider_match(tp.get("provider"), provider):
            continue
        days = tp.get("days", list(range(7)))
        if weekday not in days:
            continue
        target = now_utc.replace(hour=tp["hour"], minute=tp["minute"], second=0, microsecond=0)
        if abs((now_utc - target).total_seconds()) <= tol:
            return f"{tp['hour']:02d}:{tp['minute']:02d}"
    return None

def cooldown_ok(existing, new_models=None, force=False, provider="claude"):
    if force:
        return True, "force"
    new_models = new_models or []
    schedule = load_schedule()
    now_utc = datetime.now(timezone.utc)

    tp = _matching_time_point(schedule, now_utc, provider)
    if tp:
        run_key = f"time:{now_utc.strftime('%Y-%m-%d')}:{tp}"
        if existing.get("last_run_key") == run_key:
            print(f"  [AI-{provider}] Точка расписания {tp} UTC уже выполнена сегодня, пропускаю")
        else:
            print(f"  [AI-{provider}] Точка расписания {tp} UTC активна -- генерирую")
            return True, run_key

    raw_triggers = schedule.get("model_triggers", [])
    trigger_models = set()
    for t in raw_triggers:
        if isinstance(t, str):
            if _provider_match(None, provider):
                trigger_models.add(t)
        else:
            if _provider_match(t.get("provider"), provider):
                trigger_models.add(t.get("model"))

    hit = trigger_models & set(new_models)
    if hit:
        run_key = f"model:{now_utc.strftime('%Y-%m-%dT%H:%M')}:{','.join(sorted(hit))}"
        print(f"  [AI-{provider}] Триггер по модели(ям) {', '.join(sorted(hit))} -- генерирую")
        return True, run_key

    print(f"  [AI-{provider}] Не попадаем в расписание (сейчас {now_utc.strftime('%H:%M')} UTC, "
          f"новые модели: {new_models or 'нет'}), пропускаю")
    return False, None

# ── Основная логика ───────────────────────────────────────────────────────────

def main(force=False, new_models=None, force_gemini=False):
    if not ai_enabled():
        print("  [AI] Анализ отключён (AI_ANALYSIS_ENABLED=false в .env)")
        return

    api_key = load_api_key()
    if claude_enabled() and not api_key:
        print("  [AI] ANTHROPIC_API_KEY не найден — Claude пропущен")

    print("\n  🤖 Генерация синоптического анализа...")

    # Загружаем текущий результат (если есть)
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing_gemini = {}
    if os.path.exists(OUTPUT_FILE_GEMINI):
        try:
            with open(OUTPUT_FILE_GEMINI, "r", encoding="utf-8") as f:
                existing_gemini = json.load(f)
        except Exception:
            pass

    ok_claude, run_key_claude = (False, None)
    if claude_enabled() and api_key:
        ok_claude, run_key_claude = cooldown_ok(existing, new_models=new_models, force=force, provider="claude")

    ok_gemini, run_key_gemini = (False, None)
    if gemini_enabled():
        ok_gemini, run_key_gemini = cooldown_ok(existing_gemini, new_models=new_models, force=(force or force_gemini), provider="gemini")

    if not ok_claude and not ok_gemini:
        return

    # Запрашиваем данные
    try:
        raw = fetch_ensemble()
    except Exception as e:
        print(f"  [AI] Ошибка open-meteo: {e}")
        return

    verification_text = None
    _verif_path = os.path.join(BASE_DIR, "data", "verification_snapshots.json")
    _year = datetime.now(timezone.utc).strftime("%Y")
    _synop_path = os.path.join(BASE_DIR, "data", f"synop_{_year}.txt")
    _synop_text = ""
    try:
        if os.path.exists(_synop_path):
            with open(_synop_path, "r", encoding="utf-8") as _sf:
                _synop_text = _sf.read()
            verification_text = verification.get_verification_prompt_block(_verif_path, _synop_text)
            # Сырые телеграммы SYNOP используются внутри verification_text
            # (см. verification.get_verification_prompt_block выше), но больше
            # не печатаются построчно в лог — только шумели.
    except Exception as _e:
        print(f"  [AI] Верификация: пропущена ({_e})")

    days = aggregate_days(raw)
    data_time = raw.get("data_time")
    if data_time:
        print(f"  [AI] Данные open-meteo: {data_time}")
    if not days:
        print("  [AI] Нет данных для анализа")
        return

    # Сохраняем агрегированные данные по дням
    _days_file = os.path.join(BASE_DIR, "data", "forecast_days.json")
    with open(_days_file, "w", encoding="utf-8") as _f:
        json.dump(days, _f, ensure_ascii=False, indent=2)
    import subprocess as _sp
    _sp.run(["git", "-C", BASE_DIR, "add", "data/forecast_days.json"], capture_output=True)

    # Marine данные
    marine_raw = fetch_marine()
    marine_dates = [d["date"] for d in days]
    marine = aggregate_marine_days(marine_raw, marine_dates)
    if marine:
        first_key = marine_dates[0]
        first = marine.get(first_key)
        if first:
            print(f"  [AI] Marine: SST={first.get('sst')}°C wave={first.get('wave_height_max')}м")

    # Реальные замеры температуры воды (ГМЦ ЧАМ Telegram + TikTok)
    real_sea_temp = load_real_sea_temp()
    if real_sea_temp:
        for s in real_sea_temp:
            print(f"  [AI] Real SST: {s['source']} {s['date']}: {s.get('temp')}°C")

    # Проверяем изменились ли данные
    current_hash = data_hash(days)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STALE_HOURS = 6

    def _is_fresh(existing_data):
        if current_hash != existing_data.get("data_hash", "") or not existing_data.get("text"):
            return False
        try:
            last_gen = datetime.fromisoformat(existing_data.get("generated_at", "").replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_gen).total_seconds() / 3600
        except Exception:
            age_hours = 999
        return age_hours < STALE_HOURS

    _current_mode = _get_mode(datetime.now(timezone.utc).hour)
    prompt = build_prompt(days, marine=marine, data_time=data_time, verification_text=verification_text, real_sea_temp=real_sea_temp)

    if ok_claude and _is_fresh(existing):
        existing["last_checked"] = now_iso
        existing["changed"] = False
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print("  [AI-claude] Данные не изменились, анализ свежий -- пропускаю")
        ok_claude = False

    if ok_gemini and _is_fresh(existing_gemini):
        existing_gemini["last_checked"] = now_iso
        existing_gemini["changed"] = False
        with open(OUTPUT_FILE_GEMINI, "w", encoding="utf-8") as f:
            json.dump(existing_gemini, f, ensure_ascii=False, indent=2)
        print("  [AI-gemini] Данные не изменились, анализ свежий -- пропускаю")
        ok_gemini = False

    if not ok_claude and not ok_gemini:
        return

    print(f"  [AI] Промпт: ~{len(prompt.split())} слов")

    if claude_enabled() and ok_claude:
        try:
            text = call_claude(prompt, api_key)
            text, _period_summary = verification.extract_period_summary(text)
            if _period_summary:
                verification.save_current_period_summary(_verif_path, _period_summary)
                import subprocess as _sp3
                _sp3.run(["git", "-C", BASE_DIR, "add", "data/verification_snapshots.json"], capture_output=True)
        except Exception as e:
            print(f"  [AI] Ошибка Claude API: {e}")
            return

        result = {
            "generated_at": now_iso,
            "last_checked": now_iso,
            "changed": True,
            "data_hash": current_hash,
            "days_count": len(days),
            "text": text,
            "last_run_key": run_key_claude,
            "mode": _current_mode,
        }
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"  [AI] ✅ Анализ сохранён ({len(text)} символов)")
    elif not claude_enabled():
        print("  [AI] Claude отключён (CLAUDE_ANALYSIS_ENABLED=false) -- пропускаю")

    if gemini_enabled() and ok_gemini:
        generate_gemini_analysis(prompt, now_iso, current_hash, days, run_key_gemini, mode=_current_mode)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-gemini", action="store_true")
    p.add_argument("--models", default="", help="Comma-separated list of models with new runs")
    a = p.parse_args()
    new_models = [m.strip() for m in a.models.split(",") if m.strip()]
    main(force=a.force, new_models=new_models, force_gemini=a.force_gemini)