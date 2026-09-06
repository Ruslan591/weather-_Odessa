"""
open_meteo_frontal_confirm.py — подтверждение спутниковых кандидатов на
атмосферный фронт (eumetsat_frontal_track.json) через Open-Meteo.
Согласовано с пользователем 2026-09-06 (docs/topics/frontal_line_stations.md).

Логика:
  1. Спутник уже нашёл 1+ кандидата (персистентные треки с axis_deg/
     movement_bearing_deg/area_km2/aspect_ratio — geometry для сетки).
  2. Единый пул координат на ВСЕ кандидаты СРАЗУ, максимум MAX_POINTS
     суммарно (не на каждого) — бюджет делится между кандидатами поровну.
  3. Один batch-запрos на модель (5 моделей), только current= (без
     hourly/daily/forecast_days).
  4. 5 последовательных запросов с паузой REQUEST_INTERVAL между ними.
  5. Голосование: модель "подтверждает" кандидата, если хотя бы один из
     трёх сигналов (перепад temp/pressure/сдвиг ветра по сетке кандидата)
     превышает порог. Кандидат "подтверждён", если ЗА проголосовало
     большинство моделей (>=3 из 5).
  6. Запуск СОБЫТИЙНЫЙ: только если (а) есть хотя бы 1 кандидат И (б) с
     последнего прогона появился новый прогон хотя бы одной из 5
     отслеживаемых моделей — сверяется с data/model_runs_history.json
     (пишется на телефоне через check_model_runs.py, коммитится в git,
     VPS видит его через обычный git pull — НЕ отдельный источник данных).

ВАЖНО про модели: пользователь указал "arpege_europe" — это НЕ валидный
&models= идентификатор Open-Meteo. Правильный (подтверждён по реальному
рабочему вызову в update.py и check_model_runs.py) — "meteofrance_
arpege_europe". Использован он.

Пороги подтверждения (TEMP_GRAD_THRESHOLD/PRESSURE_GRAD_THRESHOLD/
WIND_SHIFT_THRESHOLD_DEG) — первая прикидка, НЕ откалиброваны по реальным
случаям прохождения фронта. Требуют проверки на практике, см. docs/topics/
frontal_line_stations.md.

Нагрузка на Open-Meteo проверена вживую пользователем через Termux
2026-09-06: 300 точек x 7 параметров x 5 моделей с паузой 30с — все 5
запросов 200 OK. Отдельно подтверждён burst-порог (500-600 точек в одном
запросе без пауз уже ловит 429, разряжается за ~5 минут) — 300 точек
одним запросом далеко от этого порога.

Пишет data/open_meteo_frontal_confirm.json.
Запуск: python3 scripts/open_meteo_frontal_confirm.py
"""
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTAL_TRACK_FILE = os.path.join(DATA_DIR, "eumetsat_frontal_track.json")
GEO_CONFIG_FILE = os.path.join(DATA_DIR, "geo_config.json")
MODEL_RUNS_HISTORY_FILE = os.path.join(DATA_DIR, "model_runs_history.json")
STATE_FILE = os.path.join(DATA_DIR, "_state_open_meteo_frontal_confirm.json")
OUT_FILE = os.path.join(DATA_DIR, "open_meteo_frontal_confirm.json")

# id для &models= -> label в model_runs_history.json (для событийного гейта)
MODELS = [
    ("ecmwf_ifs", "ECMWF IFS"),
    ("icon_eu", "ICON EU"),
    ("meteofrance_arpege_europe", "Arpège"),  # НЕ "arpege_europe" — см. докстринг
    ("ukmo_global_deterministic_10km", "UKMO"),
    ("gfs_global", "GFS"),
]

CURRENT_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "pressure_msl",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation",
]

MAX_POINTS = 300       # суммарно на ВСЕ кандидаты, не на каждого
REQUEST_INTERVAL = 30  # секунд между запросами моделей — проверено вживую 2026-09-06
GRID_STEP_KM = 35.0
MIN_GRID_SIDE = 3      # 3x3=9 точек — минимум для содержательного градиента

TEMP_GRAD_THRESHOLD = 2.0        # °C между соседними точками сетки
PRESSURE_GRAD_THRESHOLD = 1.0    # hPa между соседними точками сетки
WIND_SHIFT_THRESHOLD_DEG = 45.0  # градусов между "левым" и "правым" краем сетки
MIN_MODEL_VOTES = 3              # из 5 — подтверждено


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _latest_run_times():
    """{label: run_time} — последняя запись по каждой из 5 отслеживаемых
    моделей из model_runs_history.json (список записей на label, берём
    последнюю)."""
    history = _load_json(MODEL_RUNS_HISTORY_FILE, {})
    out = {}
    for _model_id, label in MODELS:
        entries = history.get(label)
        if entries:
            out[label] = entries[-1].get("run_time")
    return out


def _has_new_model_run(state):
    """Событийный гейт: True, если хотя бы у одной из 5 моделей run_time
    новее того, что сохранён в state с прошлого прогона."""
    latest = _latest_run_times()
    prev = state.get("last_run_times", {})
    for label, run_time in latest.items():
        if run_time and run_time != prev.get(label):
            return True, latest
    return False, latest


def _grid_side_for_budget(budget):
    """Ближайшая НЕЧЁТНАЯ сторона квадратной сетки side x side <= budget,
    минимум MIN_GRID_SIDE (даже если бюджет на кандидата после деления
    поровну меньше — жертвуем общим бюджетом ради содержательного
    градиента, см. докстринг main())."""
    side = int(math.isqrt(max(budget, MIN_GRID_SIDE * MIN_GRID_SIDE)))
    if side % 2 == 0:
        side -= 1
    return max(side, MIN_GRID_SIDE)


def build_pooled_points(tracks, center_lat, center_lon, km_per_deg_lat, km_per_deg_lon):
    """Единый пул точек на ВСЕ треки сразу, суммарно <= MAX_POINTS (с
    небольшим превышением возможным только если бюджета не хватает даже
    на MIN_GRID_SIDE x MIN_GRID_SIDE на кандидата — тогда бюджет по факту
    превышается, а не кандидаты обрезаются, т.к. потеря целого кандидата
    хуже небольшого перерасхода; при реалистичном числе кандидатов (1-3)
    это не должно происходить).

    Возвращает (flat_points, candidate_meta) где candidate_meta[track_id]
    = {"side": N, "point_indices": [...индексы в flat_points, по строкам
    сетки...], "axis_deg":, "dx_km":, "dy_km":}."""
    n = len(tracks)
    budget_each = MAX_POINTS // max(n, 1)
    side = _grid_side_for_budget(budget_each)
    half = side // 2

    flat_points = []
    candidate_meta = {}
    for t in tracks:
        axis_deg = t.get("axis_deg")
        rad = math.radians(axis_deg if axis_deg is not None else 90.0)
        ax_x, ax_y = math.sin(rad), math.cos(rad)
        pp_x, pp_y = math.cos(rad), -math.sin(rad)

        start_idx = len(flat_points)
        for i in range(-half, half + 1):
            for j in range(-half, half + 1):
                along_km, perp_km = i * GRID_STEP_KM, j * GRID_STEP_KM
                dx = t.get("dx_km", 0.0) + along_km * ax_x + perp_km * pp_x
                dy = t.get("dy_km", 0.0) + along_km * ax_y + perp_km * pp_y
                lon = center_lon + dx / km_per_deg_lon
                lat = center_lat + dy / km_per_deg_lat
                flat_points.append({"lat": round(lat, 4), "lon": round(lon, 4)})

        candidate_meta[str(t["track_id"])] = {
            "side": side,
            "start_idx": start_idx,
            "n_points": side * side,
            "axis_deg": axis_deg,
        }
    return flat_points, candidate_meta


def fetch_model_batch(model_id, flat_points, timeout=30, _retry=True):
    """Один batch-запрос current= для ВСЕХ точек пула. Ретрай 1 раз на
    HTTP 429 (см. Retry-After) — та же логика, что open_meteo_field_fetch.py."""
    lats = ",".join(str(p["lat"]) for p in flat_points)
    lons = ",".join(str(p["lon"]) for p in flat_points)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        f"&current={','.join(CURRENT_VARIABLES)}"
        f"&models={model_id}&wind_speed_unit=ms&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-odessa-frontal-confirm/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry:
            wait_s = 5
            try:
                wait_s = int(e.headers.get("Retry-After", "5"))
            except (TypeError, ValueError):
                pass
            time.sleep(min(wait_s, 30))
            return fetch_model_batch(model_id, flat_points, timeout=timeout, _retry=False)
        raise
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        cur = (d or {}).get("current") or {}
        out.append({v: cur.get(v) for v in CURRENT_VARIABLES})
    return out


def _grid_of(values, side):
    return np.array(values, dtype=float).reshape(side, side)


def _max_abs_gradient(grid):
    if np.isnan(grid).any():
        return None
    gy, gx = np.gradient(grid)
    return float(np.sqrt(gx ** 2 + gy ** 2).max())


def _wind_dir_shift(dir_grid):
    """Циркулярная разница между средним направлением ветра на левом и
    правом краю сетки (столбцы 0 и -1) — грубый признак сдвига ветра
    поперёк оси кандидата."""
    if np.isnan(dir_grid).any():
        return None
    left = math.radians(float(np.nanmean(dir_grid[:, 0])))
    right = math.radians(float(np.nanmean(dir_grid[:, -1])))
    diff = math.degrees(math.atan2(math.sin(right - left), math.cos(right - left)))
    return abs(diff)


def confirm_candidate(meta, model_results_by_id):
    """model_results_by_id: {model_id: [essentials_dict,...]} — ТОЛЬКО
    точки этого кандидата (уже вырезанные вызывающим кодом по start_idx/
    n_points). Возвращает {"confirmed":, "votes":, "per_model": {...}}."""
    side = meta["side"]
    per_model = {}
    votes = 0
    for model_id, results in model_results_by_id.items():
        temp_vals = [r.get("temperature_2m") for r in results]
        pres_vals = [r.get("pressure_msl") for r in results]
        wind_vals = [r.get("wind_direction_10m") for r in results]

        if any(v is None for v in temp_vals + pres_vals + wind_vals):
            per_model[model_id] = {"vote": False, "reason": "incomplete_data"}
            continue

        temp_grad = _max_abs_gradient(_grid_of(temp_vals, side))
        pres_grad = _max_abs_gradient(_grid_of(pres_vals, side))
        wind_shift = _wind_dir_shift(_grid_of(wind_vals, side))

        vote = (
            (temp_grad is not None and temp_grad >= TEMP_GRAD_THRESHOLD) or
            (pres_grad is not None and pres_grad >= PRESSURE_GRAD_THRESHOLD) or
            (wind_shift is not None and wind_shift >= WIND_SHIFT_THRESHOLD_DEG)
        )
        per_model[model_id] = {
            "vote": vote,
            "temp_grad": round(temp_grad, 2) if temp_grad is not None else None,
            "pressure_grad": round(pres_grad, 2) if pres_grad is not None else None,
            "wind_shift_deg": round(wind_shift, 1) if wind_shift is not None else None,
        }
        if vote:
            votes += 1

    return {"confirmed": votes >= MIN_MODEL_VOTES, "votes": votes, "n_models": len(model_results_by_id), "per_model": per_model}


def main():
    ft = _load_json(FRONTAL_TRACK_FILE, None)
    tracks = (ft or {}).get("tracks") or []
    if not tracks:
        print("  [SKIP] open_meteo_frontal_confirm: нет спутниковых кандидатов")
        return

    state = _load_json(STATE_FILE, {})
    has_new_run, latest_run_times = _has_new_model_run(state)
    if not has_new_run:
        print("  [SKIP] open_meteo_frontal_confirm: нет нового прогона моделей с прошлой проверки")
        return

    geo = _load_json(GEO_CONFIG_FILE, {})
    center_lat, center_lon = geo.get("center_lat"), geo.get("center_lon")
    if center_lat is None or center_lon is None:
        print("  [WARN] open_meteo_frontal_confirm: geo_config.json без center_lat/center_lon")
        return
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))

    flat_points, candidate_meta = build_pooled_points(tracks, center_lat, center_lon, km_per_deg_lat, km_per_deg_lon)
    print(f"  open_meteo_frontal_confirm: {len(tracks)} кандидат(ов), пул {len(flat_points)} точек")

    per_model_all = {}
    for i, (model_id, _label) in enumerate(MODELS):
        try:
            per_model_all[model_id] = fetch_model_batch(model_id, flat_points)
        except Exception as e:
            print(f"  [WARN] open_meteo_frontal_confirm: модель {model_id}: {e}")
        if i < len(MODELS) - 1:
            time.sleep(REQUEST_INTERVAL)

    out_candidates = {}
    for tid, meta in candidate_meta.items():
        s, e = meta["start_idx"], meta["start_idx"] + meta["n_points"]
        model_results_by_id = {mid: res[s:e] for mid, res in per_model_all.items() if len(res) >= e}
        out_candidates[tid] = {**confirm_candidate(meta, model_results_by_id), "axis_deg": meta["axis_deg"]}

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_run_times": latest_run_times,
        "candidates": out_candidates,
    }
    _save_json(OUT_FILE, out)
    state["last_run_times"] = latest_run_times
    _save_json(STATE_FILE, state)

    n_confirmed = sum(1 for c in out_candidates.values() if c["confirmed"])
    print(f"  [OK] open_meteo_frontal_confirm: {n_confirmed}/{len(out_candidates)} подтверждено")


if __name__ == "__main__":
    main()
