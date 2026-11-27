# -*- coding: utf-8 -*-
"""Ансамбль прогноза для канала: Python-порт расчёта из js/fc-ensemble.js.

Те же модели (models.js, ensemble: true), та же точка (46.43, 30.74), те же шаги:
  1) почасовой прогноз каждой модели (Open-Meteo, м/с, местное время);
  2) поправка каждой модели (data/model_bias.json: byMonth -> overall);
  3) веса: консенсусный топ-3 по параметру (data/model_weights.json), обратно MAE;
  4) взвешенное среднее (направление ветра — векторное, weather_code — взвешенное большинство);
  5) поправка ансамбля по станции (data/ensemble_accuracy_synop.json:
     byHourUTC -> byHorizon (сглаженный) -> overall).
Результат: список часов {dt, T, P, W, G, D, R, C} (местное время Киева).
"""
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV = timezone(timedelta(hours=2))

LAT, LON = 46.43, 30.74
MODELS = ["ecmwf_ifs", "icon_eu", "icon_global", "ukmo_global_deterministic_10km",
          "meteofrance_arpege_europe", "gfs_global", "gem_global", "cma_grapes_global"]
RAW = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/"
HOURLY = ("temperature_2m,pressure_msl,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
          "precipitation,showers,weather_code")
MIN_MODELS = 3

FIELD_MAP = {"temperature_2m": "temp", "pressure_msl": "pressure", "wind_speed_10m": "wind",
             "wind_gusts_10m": "wind", "wind_direction_10m": "windDir"}
PARAM_FIELDS = {
    "temp": ["temperature_2m"],
    "pressure": ["pressure_msl"],
    "wind": ["wind_speed_10m", "wind_gusts_10m"],
    "windDir": ["wind_direction_10m"],
    "precip": ["rain", "showers"],
    "phenomena": ["weather_code"],
}
NUM_FIELDS = ["temperature_2m", "pressure_msl", "wind_speed_10m", "wind_gusts_10m", "rain", "showers"]


def jsround(x):
    return math.floor(x + 0.5)


def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "weather-tg/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_repo_json(name, cache_dir, max_age_min=60, log=print):
    """data/<name> из репозитория с дисковым кэшем (при сбое сети берём старый кэш)."""
    path = os.path.join(cache_dir, name)
    try:
        if time.time() - os.path.getmtime(path) < max_age_min * 60:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        d = _get_json(RAW + name, timeout=40)
        os.makedirs(cache_dir, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(path + ".tmp", path)
        return d
    except Exception as e:
        log("repo %s: %s" % (name, type(e).__name__))
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def fetch_model_hours(mid, log=print):
    """Почасовой прогноз одной модели в формате parseHourly (rain = precipitation)."""
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON, "hourly": HOURLY, "models": mid,
        "forecast_days": 5, "wind_speed_unit": "ms", "timezone": "auto"})
    try:
        d = _get_json(url)
        h = d["hourly"]
    except Exception as e:
        log("Open-Meteo %s: %s" % (mid, type(e).__name__))
        return None
    out = []
    for i, t in enumerate(h["time"]):
        out.append({
            "time": t,
            "temperature_2m": h["temperature_2m"][i],
            "pressure_msl": h["pressure_msl"][i],
            "wind_speed_10m": h["wind_speed_10m"][i],
            "wind_gusts_10m": h["wind_gusts_10m"][i],
            "wind_direction_10m": h["wind_direction_10m"][i],
            "rain": h["precipitation"][i] or 0,
            "showers": h["showers"][i] or 0,
            "weather_code": h["weather_code"][i],
        })
    return out


def debias_model(mid, hours, model_bias, month_key):
    mb = (model_bias or {}).get(mid)
    if not hours or not mb:
        return hours
    by_month = (mb.get("byMonth") or {}).get(month_key) or {}
    overall = mb.get("overall") or {}
    out = []
    for h in hours:
        hc = dict(h)
        for field, param in FIELD_MAP.items():
            val = hc.get(field)
            if val is None:
                continue
            e = by_month.get(param)
            if e is None:
                e = overall.get(param)
            b = (e or {}).get("bias")
            if b is None:
                continue
            if param == "windDir":
                hc[field] = ((val - b) % 360 + 360) % 360
            elif param == "wind":
                hc[field] = max(0, jsround((val - b) * 10) / 10.0)
            elif field == "visibility":
                hc[field] = max(0, jsround((val - b) * 10) / 10.0)
            else:
                hc[field] = jsround((val - b) * 10) / 10.0
        out.append(hc)
    return out


def season_keys(now_local):
    m, y = now_local.month, now_local.year
    s = "DJF" if (m == 12 or m <= 2) else "MAM" if m <= 5 else "JJA" if m <= 8 else "SON"
    sy = y + 1 if m == 12 else y
    return {"season": s, "seasonKey": "%d-%s" % (sy, s), "monthKey": "%d-%02d" % (y, m),
            "mm": "%02d" % m}


def _dig(d, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def consensus_top3(mw, param_key, succeeded, now_local):
    k = season_keys(now_local)
    sources = [
        _dig(mw, "allSeasons", k["season"], param_key),
        _dig(mw, "seasonal", k["seasonKey"], param_key),
        _dig(mw, "allMonths", k["mm"], param_key),
        _dig(mw, "monthly", k["monthKey"], param_key),
    ]
    sources = [s for s in sources if s]
    if not sources:
        return None
    scores = {m: {"score": 0.0, "count": 0, "mae": 0.0} for m in succeeded}
    for src in sources:
        for idx, entry in enumerate(src):
            if entry.get("model") not in succeeded:
                continue
            sc = scores[entry["model"]]
            sc["score"] += (len(src) - idx) / float(len(src))
            sc["mae"] += entry.get("mae") or 0.0
            sc["count"] += 1
    ranked = [m for m in succeeded if scores[m]["count"] > 0]
    ranked.sort(key=lambda m: -scores[m]["score"])  # сортировка устойчивая, как в JS
    ranked = ranked[:3]
    if not ranked:
        return None
    avg = {m: (scores[m]["mae"] / scores[m]["count"]) or 1.0 for m in ranked}
    wt = sum(1.0 / avg[m] for m in ranked)
    return {m: (1.0 / avg[m]) / wt for m in ranked}


def model_weights(mw, succeeded, now_local):
    equal = {m: 1.0 / len(succeeded) for m in succeeded}
    if not mw:
        return {"byParam": None, "equal": equal}
    by_param = {}
    for pk, fields in PARAM_FIELDS.items():
        top3 = consensus_top3(mw, pk, succeeded, now_local)
        for f in fields:
            by_param[f] = top3 or equal
    return {"byParam": by_param, "equal": equal}


def merge(all_hours, weights, models):
    base = all_hours[models[0]]
    bp = weights["byParam"]
    out = []
    for i, bh in enumerate(base):
        m = {"time": bh["time"]}
        for f in NUM_FIELDS:
            fw = (bp.get(f) if bp else None) or weights["equal"]
            s = w = 0.0
            for mid, wt in fw.items():
                mh = all_hours.get(mid)
                if not mh or i >= len(mh):
                    continue
                v = mh[i].get(f)
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    s += v * wt
                    w += wt
            m[f] = s / w if w > 0 else None
        dfw = (bp.get("wind_direction_10m") if bp else None) or weights["equal"]
        sx = sy = w2 = 0.0
        for mid, wt in dfw.items():
            mh = all_hours.get(mid)
            if not mh or i >= len(mh):
                continue
            d = mh[i].get("wind_direction_10m")
            if d is not None:
                r = math.radians(d)
                sx += math.sin(r) * wt
                sy += math.cos(r) * wt
                w2 += wt
        m["wind_direction_10m"] = ((math.degrees(math.atan2(sx / w2, sy / w2)) + 360) % 360) if w2 > 0 else None
        cfw = (bp.get("weather_code") if bp else None) or weights["equal"]
        counts = {}
        for mid, wt in cfw.items():
            mh = all_hours.get(mid)
            if not mh or i >= len(mh):
                continue
            c = mh[i].get("weather_code")
            if c is not None:
                counts[int(c)] = counts.get(int(c), 0.0) + wt
        best_code, best_w = 0, -1.0
        for c in sorted(counts):  # как Object.keys в JS: числовые ключи по возрастанию
            if counts[c] > best_w:
                best_w, best_code = counts[c], c
        m["weather_code"] = best_code
        out.append(m)
    return out


def smooth_by_horizon(by_h):
    nums = sorted(int(k) for k in by_h.keys())
    res = {}
    for i, h in enumerate(nums):
        res[str(h)] = {}
        src = by_h[str(h)]
        for key in src.keys():
            vals = []
            for di in range(-2, 3):
                ni = i + di
                if 0 <= ni < len(nums):
                    v = ((by_h[str(nums[ni])].get(key)) or {}).get("bias")
                    if v is not None:
                        vals.append(v)
            res[str(h)][key] = {"bias": (sum(vals) / len(vals)) if vals else None}
    return res


def apply_bias(value, key, overall, by_h, horizon_h, by_hour, hour_utc):
    if value is None:
        return value
    b = None
    if by_hour is not None and hour_utc is not None:
        h0 = (hour_utc // 3) * 3
        h1 = (h0 + 3) % 24
        b0 = ((by_hour.get(str(h0)) or {}).get(key) or {}).get("bias")
        b1 = ((by_hour.get(str(h1)) or {}).get(key) or {}).get("bias")
        if b0 is not None and b1 is not None:
            b = b0 + (b1 - b0) * ((hour_utc - h0) / 3.0)
        elif b0 is not None:
            b = b0
        elif b1 is not None:
            b = b1
    if b is None and by_h is not None and horizon_h is not None:
        hk = str(max(0, int(jsround(horizon_h))))
        b = ((by_h.get(hk) or {}).get(key) or {}).get("bias")
    if b is None:
        b = (overall.get(key) or {}).get("bias")
    if b is None:
        return value
    if key == "windDir":
        return ((value - b) % 360 + 360) % 360
    r = jsround((value - b) * 10) / 10.0
    if key in ("wind", "windGust", "visibility"):
        r = max(0, r)
    return r


def compute_ensemble(now_local, cache_dir, model_source=None, log=print):
    """Возвращает список часов ансамбля или None. model_source(mid) -> hours (для тестов)."""
    mw = load_repo_json("model_weights.json", cache_dir, log=log)
    mbias = (load_repo_json("model_bias.json", cache_dir, log=log) or {}).get("models") or {}
    acc = load_repo_json("ensemble_accuracy_synop.json", cache_dir, log=log) or {}
    bias = {"overall": acc.get("overall") or {}, "byHorizon": acc.get("byHorizon") or {},
            "byHourUTC": acc.get("byHourUTC") or {}}
    if bias["byHorizon"] and len(bias["byHorizon"]) > 2:
        bias["byHorizon"] = smooth_by_horizon(bias["byHorizon"])

    month_key = "%02d" % now_local.month
    all_hours = {}
    base_times = None
    src = model_source or (lambda mid: fetch_model_hours(mid, log))
    for mid in MODELS:
        hrs = src(mid)
        if not hrs:
            continue
        if base_times is None:
            base_times = [h["time"] for h in hrs]
        all_hours[mid] = debias_model(mid, hrs, mbias, month_key)
    succeeded = [m for m in MODELS if m in all_hours]
    if len(succeeded) < MIN_MODELS or not base_times:
        log("ансамбль: моделей %d (< %d)" % (len(succeeded), MIN_MODELS))
        return None
    weights = model_weights(mw, succeeded, now_local)
    merged = merge(all_hours, weights, succeeded)
    t0 = datetime.fromisoformat(base_times[0])
    out = []
    for i, h in enumerate(merged):
        if i >= len(base_times):
            break
        t = datetime.fromisoformat(base_times[i])
        horizon_h = (t - t0).total_seconds() / 3600.0
        hour_utc = t.replace(tzinfo=KYIV).astimezone(timezone.utc).hour
        def ab(v, key):
            return apply_bias(v, key, bias["overall"], bias["byHorizon"], horizon_h, bias["byHourUTC"], hour_utc)
        rain = h.get("rain")
        out.append({
            "dt": t.replace(tzinfo=KYIV),
            "T": ab(h["temperature_2m"], "temp"),
            "P": ab(h["pressure_msl"], "pressure"),
            "W": ab(h["wind_speed_10m"], "wind"),
            "G": ab(h["wind_gusts_10m"], "windGust"),
            "D": ab(h["wind_direction_10m"], "windDir"),
            "R": None if rain is None else round(rain, 2),
            "C": h["weather_code"],
        })
    return out
