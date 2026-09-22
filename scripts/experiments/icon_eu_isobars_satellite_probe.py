"""
scripts/experiments/icon_eu_isobars_satellite_probe.py

ИЗОЛИРОВАННЫЙ эксперимент (docs/ai/ICON_EU_ISOBARS_SATELLITE_EXPERIMENT.md).
НЕ трогает production detector/nearby.html/data/geo_config.json. Запускается
ТОЛЬКО через .github/workflows/experiment_icon_eu_isobars.yml
(workflow_dispatch), пишет результаты в data/experiments/icon_eu_isobars/ и
docs/ai/.

Цель: взять ОДНУ модель (ICON-EU), ОДИН момент (2026-09-21 15:00 UTC), её поле
MSLP -> изобары -> наложить на EUMETSAT (GeoColour, IR105) того же bbox/момента
и сравнить пространственную структуру. Диагностика, не production-фича.

Источники (проверено разведкой репозитория перед написанием этого файла):
  - Готовой инфраструктуры чтения гридованных полей ICON-EU в репозитории
    НЕТ. Единственный существующий доступ к ICON-EU — scripts/open_meteo_field_fetch.py
    (точечные current= запросы к Open-Meteo, НЕ гридовое поле MSLP). По
    условию задания Open-Meteo здесь использовать нельзя, поэтому MSLP
    берётся напрямую с open data DWD (opendata.dwd.de/weather/nwp/icon-eu/grib/),
    который НЕ является Open-Meteo и не входит ни в один существующий
    production-пайплайн проекта.
  - EUMETSAT: переиспользован существующий механизм
    scripts/field_motion_common.py::fetch_map_custom() (WMS GetMap,
    view.eumetsat.int/geoserver/wms) — тот же слой/сервер, что во всём
    production satellite pipeline. Слои те же константы, что в
    scripts/eumetsat_west_watch.py: LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour",
    LAYER_IR105 = "mtg_fd:ir105_hrfi" (style "mtg_fd:mtg_fd_ir105_hrfi_grayscale").
  - bbox: тот же центральный (near-tier) production bbox, что в
    data/geo_config.json -> motion_window (CENTER_LAT/LON, half_window_deg=2.5),
    прочитанный ЧЕРЕЗ field_motion_common (fc.CENTER_LAT и т.п.), а не
    задублированный литералом.
"""
import bz2
import io
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
import field_motion_common as fc  # noqa: E402  (репозиторный модуль, путь добавлен выше)

# ---------------------------------------------------------------------------
# Константы эксперимента
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE_DIR, "data", "experiments", "icon_eu_isobars")
os.makedirs(OUT_DIR, exist_ok=True)

TARGET_VALID_UTC = datetime(2026, 9, 21, 15, 0, 0, tzinfo=timezone.utc)
TARGET_LABEL = "2026-09-21_1500"

# bbox — читается через field_motion_common, НЕ задублирован литералом
# (fc.CENTER_LAT/LON/HALF_WINDOW_DEG сами берутся из data/geo_config.json).
BBOX = (fc.CENTER_LON - fc.HALF_WINDOW_DEG, fc.CENTER_LAT - fc.HALF_WINDOW_DEG,
        fc.CENTER_LON + fc.HALF_WINDOW_DEG, fc.CENTER_LAT + fc.HALF_WINDOW_DEG)
WEST, SOUTH, EAST, NORTH = BBOX

SAT_WIDTH = SAT_HEIGHT = 900  # крупнее production TILE_SIZE=400 — для диагностики

LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"
LAYER_IR105 = "mtg_fd:ir105_hrfi"
STYLE_IR105 = "mtg_fd:mtg_fd_ir105_hrfi_grayscale"

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"

# Кандидаты run+lead, дающие ровно валидное время TARGET_VALID_UTC, в порядке
# предпочтения (сначала минимальный lead = максимальная свежесть/точность).
# ICON-EU: run 00/12 UTC -> часовой шаг до +78ч; run 06/18 UTC -> до +30ч.
RUN_CANDIDATES_HOURS = [12, 6, 0, 18]  # 18 = предыдущие сутки


def candidate_runs():
    """Возвращает список (run_datetime_utc, lead_hours, url) для попытки
    получить ровно TARGET_VALID_UTC, от самого свежего run'а к самому
    старому. НЕ округляет валидное время — либо ровно TARGET_VALID_UTC,
    либо кандидат не порождается вообще."""
    out = []
    for run_hour in RUN_CANDIDATES_HOURS:
        run_day = TARGET_VALID_UTC.date()
        run_dt = datetime(run_day.year, run_day.month, run_day.day, run_hour, tzinfo=timezone.utc)
        if run_hour == 18:
            run_dt = run_dt - timedelta(days=1)
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
    return out


def try_download_icon_eu_mslp(log):
    """Пробует все кандидаты run+lead по очереди. Возвращает
    (grib_bytes, chosen_candidate) или (None, attempts_log) если ничего
    не найдено (архив opendata.dwd.de хранит только недавние runs —
    честно фиксируем, если конкретный requested run уже вычищен)."""
    attempts = []
    for cand in candidate_runs():
        try:
            r = requests.get(cand["url"], timeout=60)
            attempts.append({**cand, "http_status": r.status_code, "bytes": len(r.content) if r.ok else 0})
            log.append(f"GET {cand['url']} -> {r.status_code}")
            if r.status_code == 200 and len(r.content) > 1000:
                raw = bz2.decompress(r.content)
                return raw, cand, attempts
        except Exception as e:
            attempts.append({**cand, "error": str(e)})
            log.append(f"GET {cand['url']} -> EXC {e}")
    return None, None, attempts


def find_fallback_run(probe_info, log):
    """Если requested valid time недоступен (rolling retention DWD вычистила
    его), НЕ округляем requested время молча — вместо этого явно ищем
    САМЫЙ РАННИЙ реально доступный run (lead=000, т.е. valid time = сам run)
    среди директорий 00/06/12/18, и возвращаем его как отдельный,
    промаркированный 'illustrative/fallback' результат, НЕ подменяющий
    основной NOT_FOUND для requested time."""
    import re
    candidates = []
    for hh, info in probe_info.items():
        files = info.get("sample_files", [])
        m = re.match(r"icon-eu_europe_regular-lat-lon_single-level_(\d{10})_(\d{3})_PMSL\.grib2\.bz2", files[0]) if files else None
        if m:
            run_tag, lead = m.group(1), int(m.group(2))
            run_dt = datetime.strptime(run_tag, "%Y%m%d%H").replace(tzinfo=timezone.utc)
            valid_dt = run_dt + timedelta(hours=lead)
            candidates.append({"run_tag": run_tag, "run_hour_dir": hh, "lead": lead, "valid_dt": valid_dt})
    if not candidates:
        return None
    # самый РАННИЙ (минимальный) valid_dt среди всех директорий = самая
    # старая ещё не вычищенная точка данных = ближайшая к requested (которое
    # уже в прошлом относительно всех текущих run'ов).
    best = min(candidates, key=lambda c: c["valid_dt"])
    fname = f"icon-eu_europe_regular-lat-lon_single-level_{best['run_tag']}_{best['lead']:03d}_PMSL.grib2.bz2"
    url = f"{DWD_BASE}/{best['run_hour_dir']}/pmsl/{fname}"
    log.append(f"FALLBACK candidate: {url} (valid={best['valid_dt'].isoformat()})")
    return {"run_utc": (best['valid_dt'] - timedelta(hours=best['lead'])).isoformat(),
            "lead_hours": best["lead"], "url": url, "fname": fname,
            "valid_utc": best["valid_dt"].isoformat()}


def probe_available_runs(log):
    """Диагностика: какие run'ы СЕЙЧАС реально выложены на opendata.dwd.de
    для icon-eu/pmsl (директории по часам запуска). Не является заменой
    requested-времени — только для честного объяснения, если requested run
    уже недоступен."""
    info = {}
    for hh in ("00", "06", "12", "18"):
        url = f"{DWD_BASE}/{hh}/pmsl/"
        try:
            r = requests.get(url, timeout=30)
            info[hh] = {"http_status": r.status_code, "listing_len": len(r.text) if r.ok else 0}
            if r.ok:
                # Быстрая грубая выборка имён файлов из HTML-листинга Apache
                import re
                names = re.findall(r'href="([^"]+_PMSL\.grib2\.bz2)"', r.text)
                info[hh]["sample_files"] = names[:3] + (["..."] if len(names) > 3 else [])
                info[hh]["file_count"] = len(names)
        except Exception as e:
            info[hh] = {"error": str(e)}
        log.append(f"LIST {url} -> {info[hh]}")
    return info


# ---------------------------------------------------------------------------
# GRIB2 -> регулярная сетка
# ---------------------------------------------------------------------------

def parse_grib_mslp(raw_bytes):
    """Читает первое GRIB2-сообщение (PMSL) и возвращает
    (grid_2d_hpa, lats_1d_asc, lons_1d_asc, meta_dict).
    Использует eccodes напрямую (codes_grib_get_data) — не полагается на
    предположение о порядке сканирования строк, берёт lat/lon/value как
    сопоставленные тройки и сам строит регулярную сетку."""
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
            "dataDate": eccodes.codes_get(gid, "dataDate"),
            "dataTime": eccodes.codes_get(gid, "dataTime"),
            "forecastTime": eccodes.codes_get(gid, "forecastTime"),
        }
        lats, lons, values = eccodes.codes_grib_get_data(gid)
        eccodes.codes_release(gid)
    os.remove(tmp_path)

    lats = np.asarray(lats)
    lons = np.asarray(lons)
    values = np.asarray(values)

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
        # Не молчим про неожиданные единицы — фиксируем как есть, PMSL в
        # GRIB2 DWD практически всегда Pa, но не предполагаем это вслепую.
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
# Градиент MSLP (для количественного анализа, п.9 задания)
# ---------------------------------------------------------------------------

def mslp_gradient_hpa_per_100km(grid_hpa, lats, lons):
    """|grad MSLP| в hPa/100km, векторно, через np.gradient с реальным шагом
    в метрах (km_per_deg по широте/долготе, долгота с косинус-поправкой)."""
    km_per_deg_lat = 111.32
    mean_lat = float(np.mean(lats))
    km_per_deg_lon = 111.32 * math.cos(math.radians(mean_lat))

    dlat = np.gradient(lats) * km_per_deg_lat  # km per grid step, per row
    dlon = np.gradient(lons) * km_per_deg_lon

    dPdy, dPdx = np.gradient(grid_hpa, dlat.mean(), dlon.mean())
    # dPdy соответствует изменению вдоль оси lats (строки), dPdx вдоль lons (столбцы)
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
    ax.set_title(f"ICON-EU MSLP (hPa), valid {TARGET_VALID_UTC.isoformat()}")
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.colorbar(im, ax=ax, label="hPa")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return {"vmin": vmin, "vmax": vmax, "levels": levels.tolist()}


def render_overlay(sat_rgba, grid_hpa, lats, lons, title, out_path, levels):
    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=130)
    ax.imshow(sat_rgba, extent=(WEST, EAST, SOUTH, NORTH), origin="upper", aspect="auto")
    cs = ax.contour(lons, lats, grid_hpa, levels=levels, colors="red", linewidths=1.3)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%d", colors="yellow")
    ax.plot(fc.CENTER_LON, fc.CENTER_LAT, marker="*", color="cyan", markersize=16,
            markeredgecolor="black", zorder=5, label=fc.STATION_LABEL)
    # рамка центрального окна
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "ICON-EU MSLP isobars over EUMETSAT (single model, single time, isolated)",
        "target_valid_utc_requested": TARGET_VALID_UTC.isoformat(),
        "bbox_lonlat_crs84": list(BBOX),
        "sat_width": SAT_WIDTH, "sat_height": SAT_HEIGHT,
        "production_modified": False,
        "log": [],
        "errors": [],
    }
    log = manifest["log"]
    sub_grid = sub_lats = sub_lons = None

    # --- 1. ICON-EU MSLP ---
    try:
        raw, chosen, attempts = try_download_icon_eu_mslp(log)
        manifest["icon_eu_download_attempts"] = attempts
        is_fallback = False
        if raw is None:
            manifest["icon_eu_status"] = "NOT_FOUND"
            probe_info = probe_available_runs(log)
            manifest["icon_eu_available_runs_probe"] = probe_info
            manifest["icon_eu_reason"] = (
                "Ни один run+lead, дающий валидное время ровно "
                f"{TARGET_VALID_UTC.isoformat()}, не найден на opendata.dwd.de "
                "(HTTP 404 на все кандидаты). opendata.dwd.de хранит только "
                "недавние прогоны ICON-EU (rolling retention), запрошенный "
                "момент (вчерашние сутки относительно запуска эксперимента) "
                "мог уже быть вычищен более новыми run'ами."
            )
            fb = find_fallback_run(probe_info, log)
            if fb is not None:
                try:
                    r = requests.get(fb["url"], timeout=60)
                    log.append(f"FALLBACK GET {fb['url']} -> {r.status_code}")
                    if r.status_code == 200 and len(r.content) > 1000:
                        raw = bz2.decompress(r.content)
                        chosen = fb
                        is_fallback = True
                        manifest["icon_eu_fallback_used"] = True
                        manifest["icon_eu_fallback_deviation_hours"] = round(
                            (datetime.fromisoformat(fb["valid_utc"]) - TARGET_VALID_UTC).total_seconds() / 3600.0, 2
                        )
                        manifest["icon_eu_fallback_note"] = (
                            "ВНИМАНИЕ: это НЕ requested время (2026-09-21 15:00 UTC), а "
                            "ближайшее РЕАЛЬНО доступное на opendata.dwd.de на момент запуска "
                            "эксперимента — " + fb["valid_utc"] + ". Используется отдельно, "
                            "как иллюстративный/резервный результат, requested-результат выше "
                            "остаётся NOT_FOUND и не подменяется."
                        )
                    else:
                        manifest["icon_eu_fallback_used"] = False
                        manifest["icon_eu_fallback_error"] = f"HTTP {r.status_code}"
                except Exception as e:
                    manifest["icon_eu_fallback_used"] = False
                    manifest["icon_eu_fallback_error"] = str(e)
            else:
                manifest["icon_eu_fallback_used"] = False
                manifest["icon_eu_fallback_error"] = "no candidate parsed from probe listing"

        if raw is not None:
            manifest["icon_eu_status"] = "FALLBACK_OK" if is_fallback else "OK"
            manifest["icon_eu_chosen"] = chosen
            grid_hpa, lats, lons, grib_meta = parse_grib_mslp(raw)
            manifest["icon_eu_grib_meta"] = grib_meta
            manifest["icon_eu_valid_time_actual"] = (
                f"{grib_meta['validityDate']}T{grib_meta['validityTime']:04d}"
            )

            sub_grid, sub_lats, sub_lons = crop_bbox(grid_hpa, lats, lons, WEST, SOUTH, EAST, NORTH)
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

            # промежуточное поле (npz) сохраняем всегда, под TARGET_LABEL
            # (имя файла про requested-момент эксперимента как таковой, не
            # про то, что в него попало) — компактно, для последующей
            # диагностики без повторного скачивания GRIB.
            np.savez_compressed(os.path.join(OUT_DIR, f"icon_eu_mslp_{TARGET_LABEL}.npz"),
                                 grid_hpa=sub_grid, lats=sub_lats, lons=sub_lons)
            manifest["files_written"] = manifest.get("files_written", []) + [
                f"data/experiments/icon_eu_isobars/icon_eu_mslp_{TARGET_LABEL}.npz"
            ]

            if not is_fallback:
                mslp_png = os.path.join(OUT_DIR, f"icon_eu_mslp_{TARGET_LABEL}.png")
                render_info = render_mslp_only(sub_grid, sub_lats, sub_lons, mslp_png)
                manifest["mslp_render"] = render_info
                manifest["files_written"].append(
                    f"data/experiments/icon_eu_isobars/icon_eu_mslp_{TARGET_LABEL}.png"
                )
    except Exception as e:
        manifest["icon_eu_status"] = "ERROR"
        manifest["errors"].append({"stage": "icon_eu", "error": str(e), "traceback": traceback.format_exc()})
        sub_grid = None

    # --- 2. EUMETSAT (всегда на REQUESTED время — нужно для честного
    #     сравнения requested satellite time vs фактически то, что сервер
    #     отдал, независимо от того, нашёлся ли ICON-EU на 15:00) ---
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
                "raw_file": f"data/experiments/icon_eu_isobars/eumetsat_{key}_{TARGET_LABEL}_raw.png",
                "note": "WMS GetMap не возвращает фактический timestamp кадра в теле ответа; "
                        "фактическое время не может быть подтверждено помимо requested_time_utc "
                        "без отдельного GetFeatureInfo/GetCapabilities-запроса по историческому времени.",
            }
            log.append(f"EUMETSAT {key} OK (requested time), shape={arr.shape}")
        except Exception as e:
            manifest.setdefault("eumetsat", {})[key] = {"status": "ERROR", "error": str(e)}
            manifest["errors"].append({"stage": f"eumetsat_{key}", "error": str(e)})
            sat_requested[key] = None
            log.append(f"EUMETSAT {key} FAILED (requested time): {e}")

    # --- 3. Наложение на REQUESTED satellite time (только если ICON-EU
    #     реально дал поле НА requested время, т.е. is_fallback=False) ---
    if sub_grid is not None and not is_fallback:
        levels = np.arange(
            math.floor(manifest["mslp_bbox_stats"]["min_hpa"] / 2.0) * 2.0,
            math.ceil(manifest["mslp_bbox_stats"]["max_hpa"] / 2.0) * 2.0 + 2.0,
            2.0,
        )
        for key in ("geocolour", "ir105"):
            if sat_requested.get(key) is not None:
                out_path = os.path.join(OUT_DIR, f"icon_eu_isobars_{key}_{TARGET_LABEL}.png")
                title = f"ICON-EU MSLP isobars + EUMETSAT {key.upper()}, valid {TARGET_VALID_UTC.isoformat()}"
                render_overlay(sat_requested[key], sub_grid, sub_lats, sub_lons, title, out_path, levels)
                manifest["files_written"] = manifest.get("files_written", []) + [
                    f"data/experiments/icon_eu_isobars/icon_eu_isobars_{key}_{TARGET_LABEL}.png"
                ]
                log.append(f"overlay {key} written (requested time)")

    # --- 4. Если ICON-EU получен только через FALLBACK (другое валидное
    #     время, НЕ requested) — отдельный, ЯВНО помеченный набор: EUMETSAT
    #     ЗАНОВО запрашивается на fallback valid time (иначе изобары и
    #     спутник были бы рассинхронизированы по времени), с отдельными
    #     именами файлов, не пересекающимися с requested-результатом выше. ---
    if sub_grid is not None and is_fallback:
        fb_valid_dt = datetime.fromisoformat(manifest["icon_eu_chosen"]["valid_utc"])
        fb_label = fb_valid_dt.strftime("%Y-%m-%d_%H%M") + "_FALLBACK"
        t_iso_fb = fb_valid_dt.strftime("%Y-%m-%dT%H:%M:00Z")
        sat_fb = {}
        for key, (layer, style) in {
            "geocolour": (LAYER_GEOCOLOUR, ""),
            "ir105": (LAYER_IR105, STYLE_IR105),
        }.items():
            try:
                arr = fc.fetch_map_custom(layer, BBOX, SAT_WIDTH, SAT_HEIGHT, time_iso=t_iso_fb,
                                           retries=2, delay=5, style=style, crs="CRS:84")
                sat_fb[key] = arr
                snap_path = os.path.join(OUT_DIR, f"eumetsat_{key}_{fb_label}_raw.png")
                Image.fromarray(arr).save(snap_path)
                manifest.setdefault("eumetsat_fallback", {})[key] = {
                    "status": "OK", "requested_time_utc": t_iso_fb, "layer": layer,
                    "raw_file": f"data/experiments/icon_eu_isobars/eumetsat_{key}_{fb_label}_raw.png",
                }
                log.append(f"EUMETSAT {key} OK (fallback time {t_iso_fb}), shape={arr.shape}")
            except Exception as e:
                manifest.setdefault("eumetsat_fallback", {})[key] = {"status": "ERROR", "error": str(e)}
                manifest["errors"].append({"stage": f"eumetsat_fallback_{key}", "error": str(e)})
                sat_fb[key] = None
                log.append(f"EUMETSAT {key} FAILED (fallback time): {e}")

        mslp_png_fb = os.path.join(OUT_DIR, f"icon_eu_mslp_{fb_label}.png")
        render_info_fb = render_mslp_only(sub_grid, sub_lats, sub_lons, mslp_png_fb)
        manifest["mslp_render_fallback"] = render_info_fb
        manifest["files_written"] = manifest.get("files_written", []) + [
            f"data/experiments/icon_eu_isobars/icon_eu_mslp_{fb_label}.png"
        ]
        levels_fb = np.arange(
            math.floor(manifest["mslp_bbox_stats"]["min_hpa"] / 2.0) * 2.0,
            math.ceil(manifest["mslp_bbox_stats"]["max_hpa"] / 2.0) * 2.0 + 2.0,
            2.0,
        )
        for key in ("geocolour", "ir105"):
            if sat_fb.get(key) is not None:
                out_path = os.path.join(OUT_DIR, f"icon_eu_isobars_{key}_{fb_label}.png")
                title = (f"[FALLBACK, NOT requested time] ICON-EU MSLP isobars + EUMETSAT "
                         f"{key.upper()}, valid {fb_valid_dt.isoformat()}")
                render_overlay(sat_fb[key], sub_grid, sub_lats, sub_lons, title, out_path, levels_fb)
                manifest["files_written"] = manifest.get("files_written", []) + [
                    f"data/experiments/icon_eu_isobars/icon_eu_isobars_{key}_{fb_label}.png"
                ]
                log.append(f"overlay {key} written (fallback time)")

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({k: v for k, v in manifest.items() if k not in ("log",)}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
