"""
open_meteo_field_fetch.py — шаг 3 плана (docs/topics/frontal_line_stations.md):
плотная СЕТКА точек вокруг УЖЕ найденного near-tier трека
(eumetsat_frontal_track.json), для каждой из 8 моделей проекта (те же ID,
что update.py::ENSEMBLE_MODELS) — снапшот temperature_2m/wind_*_10m через
`current=` (не hourly — тут нужен только "сейчас", не таймсерия). Батчами
по lat/lon (Open-Meteo поддерживает до 100 точек в одном запросе) — 1
запрос на модель, не 1 на точку.

Сетка строится в dx/dy км вдоль оси трека (axis_deg) и поперёк
(perp) — то же геометрическое пространство, что generate_axis_samples() в
ground_station_selector.py, но 2D-сетка, а не 1D-линия точек. Значения
сразу лежат по сетке (не станции вразнобой) — градиент считается
np.gradient() напрямую, интерполяция (scipy) не нужна.

Это ЧЕРНОВАЯ линия — мнение МОДЕЛИ, не истина (см. "Смена архитектуры" в
frontal_line_stations.md). Проверка реальностью — отдельный шаг 4
(ground_station_field_fetch.py, уже готов).

Пишет data/open_meteo_field.json: по каждой модели — сетка temp/ветра,
градиент, черновая линия (для каждой строки сетки — точка с макс.
градиентом поперёк оси).

Запуск: python3 scripts/open_meteo_field_fetch.py
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
OUT_FILE = os.path.join(DATA_DIR, "open_meteo_field.json")

# те же 8 моделей, что update.py::ENSEMBLE_MODELS[i]["id"] — ПРОВЕРЕНО
# по фактическому вызову fetch_forecast_model(m["id"]) в update.py, НЕ
# metaId (тот используется только для отдельного /data/{metaId}/static/
# meta.json — другой эндпоинт, не models= параметр здесь).
MODEL_IDS = [
    "ecmwf_ifs", "icon_eu", "icon_global",
    "ukmo_global_deterministic_10km", "meteofrance_arpege_europe",
    "gfs_global", "gem_global", "cma_grapes_global",
]

CURRENT_FIELDS = "temperature_2m,wind_speed_10m,wind_direction_10m,dew_point_2m"

GRID_STEP_KM = 40.0
PERP_HALF_KM = 160.0        # поперёк оси — по 160км в каждую сторону
AXIS_MIN_HALF_KM = 60.0
AXIS_MAX_HALF_KM = 220.0    # чуть меньше станционного (300), чтобы сетка не превысила 100 точек/модель
MAX_POINTS_PER_BATCH = 100  # лимит Open-Meteo


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


def build_grid(track_dx_km, track_dy_km, axis_deg, area_km2, aspect_ratio,
                center_lat, center_lon, km_per_deg_lat, km_per_deg_lon):
    """Строит 2D-сетку (n_along x n_perp) точек (lat, lon, along_km,
    perp_km) вокруг трека. along — вдоль axis_deg, perp — перпендикулярно.
    Половина длины вдоль оси — та же оценка по area/aspect, что
    generate_axis_samples(), зажата в [AXIS_MIN_HALF_KM, AXIS_MAX_HALF_KM].
    Если axis_deg is None — ось считается направленной на восток (90°),
    сетка всё равно строится (просто не выровнена по реальной вытянутости
    системы)."""
    if area_km2 and aspect_ratio and area_km2 > 0 and aspect_ratio > 0:
        half_along = math.sqrt(area_km2 * aspect_ratio / math.pi) * 1.3
    else:
        half_along = AXIS_MIN_HALF_KM
    half_along = max(AXIS_MIN_HALF_KM, min(AXIS_MAX_HALF_KM, half_along))

    axis_rad = math.radians(axis_deg if axis_deg is not None else 90.0)
    ax_x, ax_y = math.sin(axis_rad), math.cos(axis_rad)      # вдоль оси
    pp_x, pp_y = math.cos(axis_rad), -math.sin(axis_rad)     # перпендикуляр (поворот на 90°)

    n_along = max(1, int(round(half_along / GRID_STEP_KM)))
    n_perp = max(1, int(round(PERP_HALF_KM / GRID_STEP_KM)))

    grid = []
    for i in range(-n_along, n_along + 1):
        row = []
        along_km = i * GRID_STEP_KM
        for j in range(-n_perp, n_perp + 1):
            perp_km = j * GRID_STEP_KM
            dx = track_dx_km + along_km * ax_x + perp_km * pp_x
            dy = track_dy_km + along_km * ax_y + perp_km * pp_y
            lon = center_lon + dx / km_per_deg_lon
            lat = center_lat + dy / km_per_deg_lat
            row.append({"along_km": along_km, "perp_km": perp_km,
                        "lat": round(lat, 4), "lon": round(lon, 4)})
        grid.append(row)

    n_points = (2 * n_along + 1) * (2 * n_perp + 1)
    if n_points > MAX_POINTS_PER_BATCH:
        raise ValueError(f"Сетка {n_points} точек > лимита {MAX_POINTS_PER_BATCH} — уменьшить GRID_STEP_KM/PERP_HALF_KM/AXIS_MAX_HALF_KM")
    return grid


def fetch_model_current(model_id, flat_points, timeout=25, _retry=True):
    """Один батч-запрос current= для ВСЕХ точек сетки сразу (Open-Meteo
    принимает списки latitude/longitude через запятую — до 100 точек).
    flat_points — плоский список {"lat":, "lon":} (порядок сохраняется,
    важно для последующей сборки обратно в сетку). Возвращает список
    dict той же длины и порядка, что flat_points, или None при ошибке.

    [ДОБАВЛЕНО 2026-09-05] На 429 (Too Many Requests) — ОДИН повторный
    запрос после паузы (см. Retry-After, если есть, иначе 5с). Найдено
    вживую: open_meteo_very_far_line.py упал именно на 429 — вероятно
    совокупная нагрузка ЭТОГО скрипта (до 8 моделей × N треков КАЖДЫЙ
    5-минутный цикл VPS) вместе с ним. Только 1 повтор — не бороться со
    стеной, а быстро сдаться и залогировать (см. вызывающий код)."""
    lats = ",".join(str(p["lat"]) for p in flat_points)
    lons = ",".join(str(p["lon"]) for p in flat_points)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        f"&current={CURRENT_FIELDS}"
        f"&models={model_id}&wind_speed_unit=ms&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-odessa-frontal-line/1.0"})
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
            return fetch_model_current(model_id, flat_points, timeout=timeout, _retry=False)
        raise
    # Множественные локации -> Open-Meteo возвращает СПИСОК объектов
    # (по одному на точку), а не единый current-объект как для одной точки.
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        cur = (d or {}).get("current") or {}
        out.append({
            "temp": cur.get("temperature_2m"),
            "wind_speed_ms": cur.get("wind_speed_10m"),
            "wind_dir_deg": cur.get("wind_direction_10m"),
            "dewpoint": cur.get("dew_point_2m"),
        })
    return out


def _gradient_ridge(temp_grid):
    """temp_grid — 2D numpy array (along x perp). Возвращает (grad_mag,
    ridge) где ridge[i] = индекс perp-столбца с макс. градиентом в строке
    i (простейшая черновая линия — по одной точке на каждую along-строку,
    БЕЗ сглаживания/фильтрации шума; это первая версия, см. докстринг
    файла и открытые вопросы в frontal_line_stations.md)."""
    gy, gx = np.gradient(temp_grid)
    grad_mag = np.sqrt(gx ** 2 + gy ** 2)
    ridge = np.nanargmax(grad_mag, axis=1) if grad_mag.size else np.array([])
    return grad_mag, ridge


def main():
    ft = _load_json(FRONTAL_TRACK_FILE, None)
    if not ft or not ft.get("tracks"):
        print("  [WARN] open_meteo_field_fetch: eumetsat_frontal_track.json недоступен/пуст")
        return

    geo = _load_json(GEO_CONFIG_FILE, {})
    center_lat, center_lon = geo.get("center_lat"), geo.get("center_lon")
    if center_lat is None or center_lon is None:
        print("  [WARN] open_meteo_field_fetch: geo_config.json без center_lat/center_lon")
        return
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))

    now = datetime.now(timezone.utc)
    out_tracks = {}

    for t in ft["tracks"]:
        try:
            grid = build_grid(t.get("dx_km", 0.0), t.get("dy_km", 0.0), t.get("axis_deg"),
                               t.get("area_km2"), t.get("aspect_ratio"),
                               center_lat, center_lon, km_per_deg_lat, km_per_deg_lon)
        except ValueError as e:
            print(f"  [WARN] open_meteo_field_fetch: трек {t.get('track_id')}: {e}")
            continue

        n_along, n_perp = len(grid), len(grid[0])
        flat = [p for row in grid for p in row]

        models_out = {}
        for model_id in MODEL_IDS:
            try:
                vals = fetch_model_current(model_id, flat)
            except Exception as e:
                print(f"  [WARN] open_meteo_field_fetch: модель {model_id} трек {t.get('track_id')}: {e}")
                continue
            if not vals or len(vals) != len(flat):
                print(f"  [WARN] open_meteo_field_fetch: модель {model_id} — неожиданный размер ответа")
                continue

            temp_grid = np.array([v["temp"] for v in vals], dtype=float).reshape(n_along, n_perp)
            grad_mag, ridge = _gradient_ridge(temp_grid)

            models_out[model_id] = {
                "temp_grid": temp_grid.tolist(),
                "grad_mag_grid": grad_mag.tolist(),
                "ridge_perp_index": ridge.tolist(),
                "along_km": [row[0]["along_km"] for row in grid],
                "perp_km": [p["perp_km"] for p in grid[0]],
            }

        out_tracks[str(t["track_id"])] = {
            "axis_deg": t.get("axis_deg"),
            "grid_shape": [n_along, n_perp],
            "models": models_out,
        }

    out = {
        "timestamp": ft.get("timestamp"),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tracks": out_tracks,
    }
    _save_json(OUT_FILE, out)
    n_models_ok = sum(len(v["models"]) for v in out_tracks.values())
    print(f"  [OK] open_meteo_field_fetch: {len(out_tracks)} трек(ов), "
          f"успешных ответов моделей суммарно={n_models_ok}")


if __name__ == "__main__":
    main()
