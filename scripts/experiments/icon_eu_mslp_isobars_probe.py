"""
scripts/experiments/icon_eu_mslp_isobars_probe.py

ИЗОЛИРОВАННЫЙ эксперимент (docs/ai/ICON_EU_MSLP_ISOBARS_EXPERIMENT.md).
НЕ трогает production detector/nearby.html/data/geo_config.json. Пишет
результаты только в data/experiments/icon_eu_mslp_isobars/ и docs/ai/.

=== ИЗМЕНЕНИЕ УСЛОВИЙ ЭКСПЕРИМЕНТА (решение Ruslan, зафиксировано в
    отчёте docs/ai/ICON_EU_MSLP_ISOBARS_EXPERIMENT.md, раздел "Изменение
    условий") ===
Первоначальное задание требовало: (а) момент 2026-09-21 15:00 UTC,
(б) источник поля MSLP — ТОЛЬКО Open-Meteo, opendata.dwd.de запрещён явно.
По факту прогона выяснилось: Open-Meteo даёт поле только через
batched-запрос нескольких точек (см. git-историю этого файла, версия до
этого изменения) — а такой запрос упирается в лимит длины URL (HTTP 414
подтверждён на практике при 1156 точках), что на практике ограничивает
сетку до ~11x11=121 точек с шагом ~0.5° (~55 км) — в ~8 раз грубее
нативного output-грида ICON-EU (0.0625°, ~7 км, официально по DWD).
Ruslan, узнав об этом ограничении, явно решил ИЗМЕНИТЬ условия:
  1. Момент эксперимента — САМЫЙ СВЕЖИЙ на момент прогона снимок
     EUMETSAT GeoColour (взят из production data/eumetsat_geocolour_motion.json,
     поле "timestamp"), а не искусственный 2026-09-21 15:00 UTC.
  2. Источник MSLP — opendata.dwd.de НАПРЯМУЮ (GRIB2, нативная сетка
     0.0625°/~7км), а не Open-Meteo — чтобы получить полное разрешение
     ICON-EU без интерполяции на стороне Open-Meteo.
Это ЯВНОЕ отступление от первоначального текста задания, принятое
пользователем осознанно после обсуждения технических ограничений — не
самовольная замена условий исполнителем.

MSLP парсится через eccodes.codes_grib_get_data(gid), которое в
установленной версии (pip eccodes==2.48, eccodeslib==2.49.0.30) возвращает
СПИСОК объектов Bunch(lat=..., lon=..., value=...) — по одному на точку
сетки (Ni*Nj ~ 904689 для полной области ICON-EU), а НЕ три плоских
массива (lats, lons, values), как ожидал более ранний, более старый
код (data/experiments/icon_eu_isobars/, там это и роняло скрипт с
"too many values to unpack (expected 3)"). Это версионная особенность
eccodes python-биндингов, установленных здесь именно через pip, а не
баг самого GRIB-файла.
"""
import bz2
import json
import math
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import field_motion_common as fc  # noqa: E402

# ---------------------------------------------------------------------------
# Константы эксперимента
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE_DIR, "data", "experiments", "icon_eu_mslp_isobars")
os.makedirs(OUT_DIR, exist_ok=True)

# Момент взят из production data/eumetsat_geocolour_motion.json ("timestamp")
# на момент запуска этого прогона — самый свежий доступный кадр GeoColour,
# по явному решению Ruslan (см. заголовок файла, "ИЗМЕНЕНИЕ УСЛОВИЙ").
TARGET_VALID_UTC = datetime(2026, 9, 23, 7, 0, 0, tzinfo=timezone.utc)
TARGET_LABEL = "2026-09-23_0700"

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

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
# Кандидаты run+lead, дающие ровно TARGET_VALID_UTC, от самого свежего
# run'а к самому старому (в порядке предпочтения). ICON-EU: run 00/12 UTC
# -> шаг до +78ч (часовой), run 06/18 UTC -> до +30ч.
RUN_CANDIDATES_HOURS = [0, 6, 12, 18]


def candidate_runs():
    """(run_datetime_utc, lead_hours, url, fname) для ровно TARGET_VALID_UTC,
    перебирая run-часы сегодняшних и вчерашних суток."""
    out = []
    for day_offset in (0, -1):
        for run_hour in RUN_CANDIDATES_HOURS:
            run_day = (TARGET_VALID_UTC + timedelta(days=day_offset)).date()
            run_dt = datetime(run_day.year, run_day.month, run_day.day, run_hour, tzinfo=timezone.utc)
            lead = (TARGET_VALID_UTC - run_dt).total_seconds() / 3600.0
            if lead < 0 or lead != int(lead):
                continue
            lead = int(lead)
            max_lead = 78 if run_hour in (0, 12) else 30
            if lead > max_lead:
                continue
            run_tag = run_dt.strftime("%Y%m%d%H")
            fname = f"icon-eu_europe_regular-lat-lon_single-level_{run_tag}_{lead:03d}_PMSL.grib2.bz2"
            url = f"{DWD_BASE}/{run_dt.hour:02d}/pmsl/{fname}"
            out.append({"run_utc": run_dt.isoformat(), "lead_hours": lead, "url": url, "fname": fname})
    # предпочитаем минимальный lead (самый свежий/точный run) сначала
    out.sort(key=lambda c: c["lead_hours"])
    return out


def try_download_icon_eu_mslp(log):
    attempts = []
    for cand in candidate_runs():
        try:
            r = requests.get(cand["url"], timeout=60)
            ok = r.status_code == 200 and len(r.content) > 1000
            attempts.append({**cand, "http_status": r.status_code, "bytes": len(r.content) if r.ok else 0})
            log.append(f"GET {cand['url']} -> {r.status_code} ({len(r.content)} bytes)")
            if ok:
                raw = bz2.decompress(r.content)
                return raw, cand, attempts
        except Exception as e:
            attempts.append({**cand, "error": str(e)})
            log.append(f"GET {cand['url']} -> EXC {e}")
    return None, None, attempts


def parse_grib_mslp(raw_bytes):
    """Читает первое GRIB2-сообщение (PMSL) и возвращает
    (grid_2d_hpa, lats_1d_asc, lons_1d_asc, meta_dict).

    eccodes.codes_grib_get_data(gid) в установленной здесь версии
    (pip eccodes==2.48 / eccodeslib==2.49.0.30) возвращает СПИСОК объектов
    Bunch(lat=.., lon=.., value=..) — по одному на точку сетки, а НЕ три
    плоских массива (lats, lons, values), как ожидал более старый код
    (data/experiments/icon_eu_isobars/) — отсюда и падение
    "too many values to unpack (expected 3)" в том прогоне. Здесь это
    учтено явно, без слепого unpack."""
    import eccodes

    tmp_path = os.path.join(OUT_DIR, "_scratch_pmsl.grib2")
    with open(tmp_path, "wb") as f:
        f.write(raw_bytes)

    with open(tmp_path, "rb") as f:
        gid = eccodes.codes_grib_new_from_file(f)
        if gid is None:
            raise RuntimeError("eccodes: не нашёл ни одного GRIB-сообщения в файле")
        meta = {
            "shortName": eccodes.codes_get(gid, "shortName"),
            "units": eccodes.codes_get(gid, "units"),
            "Ni": eccodes.codes_get(gid, "Ni"),
            "Nj": eccodes.codes_get(gid, "Nj"),
            "gridType": eccodes.codes_get(gid, "gridType"),
            "iDirectionIncrementInDegrees": eccodes.codes_get(gid, "iDirectionIncrementInDegrees"),
            "jDirectionIncrementInDegrees": eccodes.codes_get(gid, "jDirectionIncrementInDegrees"),
            "validityDate": eccodes.codes_get(gid, "validityDate"),
            "validityTime": eccodes.codes_get(gid, "validityTime"),
            "eccodes_get_data_return_type": None,
        }
        raw_data = eccodes.codes_grib_get_data(gid)
        eccodes.codes_release(gid)
    os.remove(tmp_path)

    meta["eccodes_get_data_return_type"] = f"{type(raw_data).__name__} of {len(raw_data)} " \
        f"{type(raw_data[0]).__name__ if raw_data else '?'} objects"

    # Обе формы поддержаны на случай другой версии eccodes на исполнителе:
    if isinstance(raw_data, tuple) and len(raw_data) == 3:
        lats, lons, values = (np.asarray(x) for x in raw_data)
    else:
        lats = np.array([d.lat for d in raw_data])
        lons = np.array([d.lon for d in raw_data])
        values = np.array([d.value for d in raw_data])

    uniq_lats = np.unique(lats)
    uniq_lons = np.unique(lons)
    meta["uniq_lat_count"] = int(len(uniq_lats))
    meta["uniq_lon_count"] = int(len(uniq_lons))

    lat_idx = {v: i for i, v in enumerate(uniq_lats)}
    lon_idx = {v: i for i, v in enumerate(uniq_lons)}
    grid = np.full((len(uniq_lats), len(uniq_lons)), np.nan, dtype=np.float64)
    li = np.array([lat_idx[v] for v in lats])
    lo = np.array([lon_idx[v] for v in lons])
    grid[li, lo] = values

    units = meta["units"]
    if units.lower() in ("pa", "pascal", "pascals"):
        grid_hpa = grid / 100.0
        meta["converted_units"] = "Pa -> hPa (/100)"
    elif units.lower() in ("hpa",):
        grid_hpa = grid
        meta["converted_units"] = "already hPa"
    else:
        grid_hpa = grid
        meta["converted_units"] = f"UNKNOWN units={units!r}, NOT converted"

    return grid_hpa, uniq_lats, uniq_lons, meta


def crop_bbox(grid, lats, lons, west, south, east, north):
    lat_mask = (lats >= south) & (lats <= north)
    lon_mask = (lons >= west) & (lons <= east)
    sub_grid = grid[np.ix_(lat_mask, lon_mask)]
    sub_lats = lats[lat_mask]
    sub_lons = lons[lon_mask]
    return sub_grid, sub_lats, sub_lons


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

    # --- 1. ICON-EU MSLP через opendata.dwd.de (нативная сетка 0.0625°) ---
    try:
        raw, chosen, attempts = try_download_icon_eu_mslp(log)
        manifest["icon_eu_download_attempts"] = attempts
        if raw is None:
            manifest["icon_eu_status"] = "NOT_FOUND"
            manifest["icon_eu_reason"] = (
                "Ни один run+lead, дающий валидное время ровно "
                f"{TARGET_VALID_UTC.isoformat()}, не найден на opendata.dwd.de "
                "(HTTP не-200/малый ответ на все кандидаты)."
            )
        else:
            manifest["icon_eu_status"] = "OK"
            manifest["icon_eu_chosen"] = chosen
            grid_hpa_full, lats_full, lons_full, grib_meta = parse_grib_mslp(raw)
            manifest["icon_eu_grib_meta"] = grib_meta
            manifest["icon_eu_valid_time_actual"] = (
                f"{grib_meta['validityDate']}T{grib_meta['validityTime']:04d}"
            )

            sub_grid, sub_lats, sub_lons = crop_bbox(grid_hpa_full, lats_full, lons_full,
                                                       WEST, SOUTH, EAST, NORTH)
            manifest["mslp_bbox_stats"] = {
                "min_hpa": float(np.nanmin(sub_grid)),
                "max_hpa": float(np.nanmax(sub_grid)),
                "mean_hpa": float(np.nanmean(sub_grid)),
                "n_points_total": int(sub_grid.size),
                "n_points_valid": int(np.isfinite(sub_grid).sum()),
                "shape_lat_lon": list(sub_grid.shape),
                "grid_spacing_deg": grib_meta["iDirectionIncrementInDegrees"],
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
