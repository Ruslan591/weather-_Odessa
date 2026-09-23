"""
scripts/experiments/icon_eu_mslp_isobars_probe.py

ИЗОЛИРОВАННЫЙ эксперимент (docs/ai/ICON_EU_MSLP_ISOBARS_EXPERIMENT.md).
НЕ трогает production detector/nearby.html/data/geo_config.json. Пишет
результаты только в data/experiments/icon_eu_mslp_isobars/ и docs/ai/.

Отличие от более раннего data/experiments/icon_eu_isobars (см. тот прогон):
там ICON-EU MSLP брался напрямую с opendata.dwd.de (в обход Open-Meteo) и
падал на парсинге GRIB2 через eccodes. По условию ЭТОГО задания
opendata.dwd.de использовать нельзя вообще — источник поля ТОЛЬКО
Open-Meteo. Здесь MSLP получается через обычный Open-Meteo Forecast API
(api.open-meteo.com/v1/forecast) с models=icon_eu и start_date/end_date,
охватывающими requested момент (для недавнего прошлого forecast-эндпоинт
отдаёт данные из своего rolling-архива без отдельного archive-эндпоинта
для ICON-EU — archive-api.open-meteo.com/v1/archive обслуживает только
ERA5-реанализ, ICON-EU там не модель). Это диагностический факт, а не
предположение — фиксируется в манифесте как он есть по факту ответа API.

Пространственное поле строится batched-запросом с несколькими
latitude/longitude (comma-separated) в ОДНОМ HTTP-запросе — единственный
способ получить не-точечные данные из Open-Meteo. Это ВСЕГДА билинейная
интерполяция с нативной сетки модели на запрошенные координаты на стороне
Open-Meteo — то есть "фактическая сетка" в этом эксперименте определяется
тем, какие точки МЫ запросили, а не нативной сеткой ICON-EU. Это отдельно
и явно указывается в отчёте (п.3 задания).

Все обращения идут только через scripts/open_meteo_guard.py
(reserve_request/report_request_result), как того требует стандарт
проекта для любых Open-Meteo запросов.
"""
import json
import math
import os
import sys
import traceback
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import field_motion_common as fc  # noqa: E402
import open_meteo_guard as omg  # noqa: E402

# ---------------------------------------------------------------------------
# Константы эксперимента
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE_DIR, "data", "experiments", "icon_eu_mslp_isobars")
os.makedirs(OUT_DIR, exist_ok=True)

TARGET_VALID_UTC = datetime(2026, 9, 21, 15, 0, 0, tzinfo=timezone.utc)
TARGET_LABEL = "2026-09-21_1500"
TARGET_DATE = TARGET_VALID_UTC.strftime("%Y-%m-%d")
TARGET_HOUR_INDEX = TARGET_VALID_UTC.hour  # 15 -> индекс в hourly[] за этот день

# bbox — тот же центральный (near-tier) production bbox, что и в первом
# прогоне этого эксперимента, читается через field_motion_common, НЕ
# задублирован литералом.
BBOX = (fc.CENTER_LON - fc.HALF_WINDOW_DEG, fc.CENTER_LAT - fc.HALF_WINDOW_DEG,
        fc.CENTER_LON + fc.HALF_WINDOW_DEG, fc.CENTER_LAT + fc.HALF_WINDOW_DEG)
WEST, SOUTH, EAST, NORTH = BBOX

SAT_WIDTH = SAT_HEIGHT = 900

LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"
LAYER_IR105 = "mtg_fd:ir105_hrfi"
STYLE_IR105 = "mtg_fd:mtg_fd_ir105_hrfi_grayscale"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MODEL = "icon_eu"

# Шаг сетки запроса. 0.25 deg ~ 27 x 21 = ~перебор ниже подбирает под лимит
# точек на один batched-запрос; попытки идут от мелкого шага к крупному.
GRID_STEP_CANDIDATES_DEG = [0.15, 0.25, 0.5]
MAX_LOCATIONS_PER_REQUEST = 100  # консервативный потолок free-tier batch


def build_grid_points(step_deg):
    lons = np.round(np.arange(WEST, EAST + 1e-9, step_deg), 6)
    lats = np.round(np.arange(SOUTH, NORTH + 1e-9, step_deg), 6)
    return lats, lons


def fetch_open_meteo_mslp_grid(log):
    """Пытается получить пространственное поле MSLP ICON-EU через
    Open-Meteo Forecast API батч-запросом нескольких точек. Возвращает
    (grid_hpa_2d | None, lats_1d | None, lons_1d | None, meta_dict).
    Ничего не придумывает про недоступные данные — фиксирует фактический
    HTTP-статус/тело ответа."""
    meta = {
        "endpoint_used": OPEN_METEO_FORECAST_URL,
        "model_param": OPEN_METEO_MODEL,
        "attempts": [],
        "note_archive_api": (
            "archive-api.open-meteo.com/v1/archive (Open-Meteo Historical "
            "Weather API) обслуживает ТОЛЬКО реанализ ERA5/ERA5-Land, "
            "models=icon_eu там не поддерживается. Для недавнего прошлого "
            "(в пределах rolling-окна модели) фактический источник — "
            "обычный /v1/forecast с start_date/end_date, models=icon_eu."
        ),
    }

    for step_deg in GRID_STEP_CANDIDATES_DEG:
        lats, lons = build_grid_points(step_deg)
        n_points = len(lats) * len(lons)
        attempt = {"step_deg": step_deg, "n_lat": len(lats), "n_lon": len(lons), "n_points": n_points}
        if n_points > MAX_LOCATIONS_PER_REQUEST:
            attempt["skipped"] = f"n_points={n_points} > MAX_LOCATIONS_PER_REQUEST={MAX_LOCATIONS_PER_REQUEST}"
            meta["attempts"].append(attempt)
            log.append(f"open-meteo grid step={step_deg} SKIPPED ({attempt['skipped']})")
            continue

        lat_list = []
        lon_list = []
        for la in lats:
            for lo in lons:
                lat_list.append(f"{la:.4f}")
                lon_list.append(f"{lo:.4f}")

        params = {
            "latitude": ",".join(lat_list),
            "longitude": ",".join(lon_list),
            "hourly": "pressure_msl",
            "models": OPEN_METEO_MODEL,
            "start_date": TARGET_DATE,
            "end_date": TARGET_DATE,
            "timezone": "UTC",
        }

        decision = omg.reserve_request("forecast_or_archive")
        attempt["guard_decision"] = decision
        if decision == "skip":
            meta["attempts"].append(attempt)
            log.append(f"open-meteo grid step={step_deg} SKIPPED by open_meteo_guard (rate limit)")
            continue

        try:
            r = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=60)
            attempt["http_status"] = r.status_code
            attempt["url_sample"] = r.url[:300]
            if r.status_code != 200:
                omg.report_request_result("forecast_or_archive", "error" if r.status_code != 429 else "429")
                attempt["error_body"] = r.text[:500]
                meta["attempts"].append(attempt)
                log.append(f"open-meteo grid step={step_deg} HTTP {r.status_code}: {r.text[:200]}")
                continue
            omg.report_request_result("forecast_or_archive", "success")
            data = r.json()
            # Ответ на N локаций: список объектов (при multi-location) либо
            # один объект (при single-location). Фиксируем фактическую форму.
            if isinstance(data, dict) and "hourly" in data:
                results = [data]
                attempt["response_shape"] = "single_object"
            elif isinstance(data, list):
                results = data
                attempt["response_shape"] = f"list_of_{len(data)}"
            else:
                attempt["error"] = f"unexpected response shape: keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
                meta["attempts"].append(attempt)
                log.append(f"open-meteo grid step={step_deg} unexpected shape")
                continue

            if len(results) != n_points:
                attempt["warning"] = f"expected {n_points} results, got {len(results)}"
                log.append(f"open-meteo grid step={step_deg} WARNING {attempt['warning']}")

            grid = np.full((len(lats), len(lons)), np.nan, dtype=np.float64)
            hourly_units = None
            returned_times_sample = None
            missing = 0
            for idx, item in enumerate(results):
                if idx >= n_points:
                    break
                ilat, ilon = divmod(idx, len(lons))
                try:
                    hourly = item["hourly"]
                    times = hourly["time"]
                    values = hourly["pressure_msl"]
                    if returned_times_sample is None:
                        returned_times_sample = times[:3]
                        hourly_units = item.get("hourly_units", {}).get("pressure_msl")
                    # найти индекс времени, точно равного requested часу
                    target_iso = TARGET_VALID_UTC.strftime("%Y-%m-%dT%H:00")
                    if target_iso in times:
                        tidx = times.index(target_iso)
                        grid[ilat, ilon] = values[tidx]
                    else:
                        missing += 1
                except Exception:
                    missing += 1
            attempt["missing_points"] = missing
            attempt["hourly_units_pressure_msl"] = hourly_units
            attempt["returned_times_sample"] = returned_times_sample
            attempt["generationtime_ms"] = results[0].get("generationtime_ms") if results else None
            attempt["model_elevation_first_point"] = results[0].get("elevation") if results else None
            meta["attempts"].append(attempt)

            n_valid = int(np.isfinite(grid).sum())
            log.append(f"open-meteo grid step={step_deg} OK n_points={n_points} n_valid={n_valid} missing={missing}")

            if n_valid == 0:
                continue

            # единицы: Open-Meteo обычно отдаёт pressure_msl уже в hPa
            if hourly_units and "hpa" in str(hourly_units).lower():
                grid_hpa = grid
                meta["units_conversion"] = f"already {hourly_units}, no conversion"
            else:
                grid_hpa = grid
                meta["units_conversion"] = f"units field = {hourly_units!r}; assumed already comparable to hPa, NOT blindly converted"

            meta["chosen_step_deg"] = step_deg
            meta["chosen_n_points"] = n_points
            return grid_hpa, lats, lons, meta

        except Exception as e:
            attempt["exception"] = str(e)
            attempt["traceback"] = traceback.format_exc()
            meta["attempts"].append(attempt)
            log.append(f"open-meteo grid step={step_deg} EXCEPTION {e}")
            try:
                omg.report_request_result("forecast_or_archive", "error")
            except Exception:
                pass
            continue

    return None, None, None, meta


# ---------------------------------------------------------------------------
# Градиент MSLP
# ---------------------------------------------------------------------------

def mslp_gradient_hpa_per_100km(grid_hpa, lats, lons):
    km_per_deg_lat = 111.32
    mean_lat = float(np.nanmean(lats))
    km_per_deg_lon = 111.32 * math.cos(math.radians(mean_lat))

    dlat_deg = float(np.mean(np.diff(lats))) if len(lats) > 1 else 1.0
    dlon_deg = float(np.mean(np.diff(lons))) if len(lons) > 1 else 1.0
    dy_km = dlat_deg * km_per_deg_lat
    dx_km = dlon_deg * km_per_deg_lon

    dPdy, dPdx = np.gradient(grid_hpa, dy_km, dx_km)
    grad_mag_per_km = np.sqrt(dPdx**2 + dPdy**2)
    grad_mag_per_100km = grad_mag_per_km * 100.0
    grad_dir_deg = (np.degrees(np.arctan2(dPdy, dPdx))) % 360.0
    return grad_mag_per_100km, grad_dir_deg


# ---------------------------------------------------------------------------
# Рендер
# ---------------------------------------------------------------------------

def render_mslp_only(grid_hpa, lats, lons, out_path):
    vmin, vmax = float(np.nanmin(grid_hpa)), float(np.nanmax(grid_hpa))
    levels = np.arange(math.floor(vmin / 2.0) * 2.0, math.ceil(vmax / 2.0) * 2.0 + 2.0, 2.0)
    fig, ax = plt.subplots(figsize=(7, 7), dpi=120)
    im = ax.imshow(grid_hpa, extent=(lons.min(), lons.max(), lats.min(), lats.max()),
                    origin="lower", cmap="viridis", aspect="auto")
    cs = ax.contour(lons, lats, grid_hpa, levels=levels, colors="white", linewidths=1.0)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%d")
    ax.plot(fc.CENTER_LON, fc.CENTER_LAT, marker="*", color="red", markersize=14,
            markeredgecolor="black", label=fc.STATION_LABEL)
    ax.set_title(f"ICON-EU (Open-Meteo) MSLP hPa, valid {TARGET_VALID_UTC.isoformat()}")
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.colorbar(im, ax=ax, label="hPa")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return {"vmin": vmin, "vmax": vmax, "levels": levels.tolist()}


def render_gradient_only(grad_mag, lats, lons, out_path):
    fig, ax = plt.subplots(figsize=(7, 7), dpi=120)
    im = ax.imshow(grad_mag, extent=(lons.min(), lons.max(), lats.min(), lats.max()),
                    origin="lower", cmap="magma", aspect="auto")
    ax.plot(fc.CENTER_LON, fc.CENTER_LAT, marker="*", color="cyan", markersize=14,
            markeredgecolor="black", label=fc.STATION_LABEL)
    ax.set_title(f"|grad MSLP| hPa/100km, valid {TARGET_VALID_UTC.isoformat()}")
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.colorbar(im, ax=ax, label="hPa/100km")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def render_overlay(sat_rgba, grid_hpa, lats, lons, title, out_path, levels):
    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=130)
    ax.imshow(sat_rgba, extent=(WEST, EAST, SOUTH, NORTH), origin="upper", aspect="auto")
    cs = ax.contour(lons, lats, grid_hpa, levels=levels, colors="red", linewidths=1.3)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%d", colors="yellow")
    ax.plot(fc.CENTER_LON, fc.CENTER_LAT, marker="*", color="cyan", markersize=16,
            markeredgecolor="black", zorder=5, label=fc.STATION_LABEL)
    ax.add_patch(plt.Rectangle((WEST, SOUTH), EAST - WEST, NORTH - SOUTH,
                                fill=False, edgecolor="lime", linewidth=1.5, linestyle="--"))
    ax.set_xlim(WEST, EAST)
    ax.set_ylim(SOUTH, NORTH)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def render_gradient_overlay(sat_rgba, grad_mag, lats, lons, title, out_path):
    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=130)
    ax.imshow(sat_rgba, extent=(WEST, EAST, SOUTH, NORTH), origin="upper", aspect="auto")
    im = ax.imshow(grad_mag, extent=(lons.min(), lons.max(), lats.min(), lats.max()),
                    origin="lower", cmap="magma", alpha=0.45, aspect="auto")
    ax.plot(fc.CENTER_LON, fc.CENTER_LAT, marker="*", color="cyan", markersize=16,
            markeredgecolor="black", zorder=5, label=fc.STATION_LABEL)
    ax.set_xlim(WEST, EAST)
    ax.set_ylim(SOUTH, NORTH)
    ax.set_title(title, fontsize=10)
    fig.colorbar(im, ax=ax, label="hPa/100km", shrink=0.7)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "ICON-EU MSLP (via Open-Meteo) isobars over EUMETSAT (single model, single time, isolated)",
        "target_valid_utc_requested": TARGET_VALID_UTC.isoformat(),
        "bbox_lonlat_crs84": list(BBOX),
        "sat_width": SAT_WIDTH, "sat_height": SAT_HEIGHT,
        "production_modified": False,
        "log": [],
        "errors": [],
        "files_written": [],
    }
    log = manifest["log"]
    sub_grid = sub_lats = sub_lons = None

    # --- 1. ICON-EU MSLP через Open-Meteo ---
    try:
        grid_hpa, lats, lons, om_meta = fetch_open_meteo_mslp_grid(log)
        manifest["open_meteo"] = om_meta
        if grid_hpa is None:
            manifest["icon_eu_status"] = "NOT_FOUND"
        else:
            manifest["icon_eu_status"] = "OK"
            sub_grid, sub_lats, sub_lons = grid_hpa, lats, lons
            manifest["mslp_bbox_stats"] = {
                "min_hpa": float(np.nanmin(sub_grid)),
                "max_hpa": float(np.nanmax(sub_grid)),
                "mean_hpa": float(np.nanmean(sub_grid)),
                "n_points_total": int(sub_grid.size),
                "n_points_valid": int(np.isfinite(sub_grid).sum()),
                "shape_lat_lon": list(sub_grid.shape),
                "grid_step_deg_requested": om_meta.get("chosen_step_deg"),
            }
            grad_mag, grad_dir = mslp_gradient_hpa_per_100km(sub_grid, sub_lats, sub_lons)
            manifest["mslp_gradient_stats"] = {
                "max_hpa_per_100km": float(np.nanmax(grad_mag)),
                "mean_hpa_per_100km": float(np.nanmean(grad_mag)),
                "argmax_lat": float(sub_lats[np.unravel_index(np.nanargmax(grad_mag), grad_mag.shape)[0]]),
                "argmax_lon": float(sub_lons[np.unravel_index(np.nanargmax(grad_mag), grad_mag.shape)[1]]),
            }

            np.savez_compressed(os.path.join(OUT_DIR, f"icon_eu_mslp_{TARGET_LABEL}.npz"),
                                 grid_hpa=sub_grid, lats=sub_lats, lons=sub_lons)
            manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/icon_eu_mslp_{TARGET_LABEL}.npz")

            mslp_png = os.path.join(OUT_DIR, f"icon_eu_mslp_{TARGET_LABEL}.png")
            manifest["mslp_render"] = render_mslp_only(sub_grid, sub_lats, sub_lons, mslp_png)
            manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/icon_eu_mslp_{TARGET_LABEL}.png")

            grad_png = os.path.join(OUT_DIR, f"icon_eu_mslp_gradient_{TARGET_LABEL}.png")
            render_gradient_only(grad_mag, sub_lats, sub_lons, grad_png)
            manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/icon_eu_mslp_gradient_{TARGET_LABEL}.png")
    except Exception as e:
        manifest["icon_eu_status"] = "ERROR"
        manifest["errors"].append({"stage": "icon_eu", "error": str(e), "traceback": traceback.format_exc()})
        sub_grid = None

    # --- 2. EUMETSAT на requested время ---
    t_iso_requested = TARGET_VALID_UTC.strftime("%Y-%m-%dT%H:%M:00Z")
    sat_requested = {}
    for key, (layer, style) in {
        "geocolour": (LAYER_GEOCOLOUR, ""),
        "ir105": (LAYER_IR105, STYLE_IR105),
    }.items():
        try:
            arr = fc.fetch_map_custom(layer, BBOX, SAT_WIDTH, SAT_HEIGHT, time_iso=t_iso_requested,
                                       retries=2, delay=5, style=style, crs="CRS:84")
            sat_requested[key] = arr
            snap_path = os.path.join(OUT_DIR, f"eumetsat_{key}_{TARGET_LABEL}_raw.png")
            Image.fromarray(arr).save(snap_path)
            manifest.setdefault("eumetsat", {})[key] = {
                "status": "OK", "requested_time_utc": t_iso_requested, "layer": layer,
                "raw_file": f"data/experiments/icon_eu_mslp_isobars/eumetsat_{key}_{TARGET_LABEL}_raw.png",
                "note": "WMS GetMap не возвращает фактический timestamp кадра в теле ответа; "
                        "фактическое время не подтверждено сверх requested_time_utc.",
            }
            manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/eumetsat_{key}_{TARGET_LABEL}_raw.png")
            log.append(f"EUMETSAT {key} OK (requested time), shape={arr.shape}")
        except Exception as e:
            manifest.setdefault("eumetsat", {})[key] = {"status": "ERROR", "error": str(e)}
            manifest["errors"].append({"stage": f"eumetsat_{key}", "error": str(e)})
            sat_requested[key] = None
            log.append(f"EUMETSAT {key} FAILED: {e}")

    # --- 3. Наложения ---
    if sub_grid is not None:
        levels = np.arange(
            math.floor(manifest["mslp_bbox_stats"]["min_hpa"] / 2.0) * 2.0,
            math.ceil(manifest["mslp_bbox_stats"]["max_hpa"] / 2.0) * 2.0 + 2.0,
            2.0,
        )
        grad_mag, _ = mslp_gradient_hpa_per_100km(sub_grid, sub_lats, sub_lons)
        for key in ("geocolour", "ir105"):
            if sat_requested.get(key) is not None:
                out_path = os.path.join(OUT_DIR, f"icon_eu_isobars_{key}_{TARGET_LABEL}.png")
                title = f"ICON-EU (Open-Meteo) MSLP isobars + EUMETSAT {key.upper()}, valid {TARGET_VALID_UTC.isoformat()}"
                render_overlay(sat_requested[key], sub_grid, sub_lats, sub_lons, title, out_path, levels)
                manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/icon_eu_isobars_{key}_{TARGET_LABEL}.png")
                log.append(f"overlay {key} written")

        if sat_requested.get("geocolour") is not None:
            grad_overlay_path = os.path.join(OUT_DIR, f"icon_eu_mslp_gradient_geocolour_{TARGET_LABEL}.png")
            render_gradient_overlay(sat_requested["geocolour"], grad_mag, sub_lats, sub_lons,
                                     f"MSLP gradient + EUMETSAT GeoColour, valid {TARGET_VALID_UTC.isoformat()}",
                                     grad_overlay_path)
            manifest["files_written"].append(f"data/experiments/icon_eu_mslp_isobars/icon_eu_mslp_gradient_geocolour_{TARGET_LABEL}.png")
            log.append("gradient overlay (geocolour) written")

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({k: v for k, v in manifest.items() if k not in ("log",)}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
