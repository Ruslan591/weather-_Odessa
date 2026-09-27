"""
scripts/icon_front_very_far_snapshot.py

Периодический (cron, раз в час в :06, отдельный процесс — НЕ часть
vps_satellite_pipeline.py / vps_pipeline.py) снимок для тестовых страниц:
  - изобары ICON-EU PMSL;
  - P_front (variant C + coastal + orography penalty) — эксперимент
    icon_front_v1 (см. docs/ai/ICON_EU_FRONT_DETECTOR_V1_OFFLINE_EXPERIMENT.md);
  - EUMETSAT GeoColour на то же самое время (valid_time), для сравнения.

Несмотря на имя файла (осталось от первой версии, где был только тир
very_far) — теперь считает все три тира разом: near (центральный тайл,
±2.5°), far (~1000км, ±13°), very_far (Испания/Италия/Британия/Балканы).
GRIB-поля скачиваются РОВНО ОДИН РАЗ на объединённый bbox всех трёх тиров
(GRIB с opendata.dwd.de — это всегда весь домен ICON-EU целиком, поэтому
более узкий/широкий bbox не меняет объём скачивания) и переиспользуются
для всех тиров — добавление ещё двух тиров не увеличивает трафик по
GRIB, только по EUMETSAT (свой WMS-запрос на тир).

Каждый тир сам решает, вышел ли новый час ICON-EU с прошлого успешного
снимка ИМЕННО ДЛЯ ЭТОГО ТИРА; если для всех трёх новых данных нет —
скрипт вообще не скачивает GRIB. Хранится не более KEEP_LAST снимков на
тир — старые файлы и записи манифеста удаляются.

НЕ трогает: nearby.html, существующие детекторы, data/geo_config.json,
существующие cron-пайплайны. Коммитит только data/icon_front_<tier>/**
под тем же GIT_LOCK_FILE, что и остальные VPS-пайплайны.
"""
import bz2
import fcntl
import json
import math
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import maximum_filter, minimum_filter, gaussian_filter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

REPO_DIR = "/opt/weather-pipeline/repo"
sys.path.insert(0, os.path.join(REPO_DIR, "scripts"))
import field_motion_common as fc  # noqa: E402

GIT_LOCK_FILE = "/tmp/vps_git.lock"
OWN_LOCK_FILE = "/tmp/icon_front_very_far.lock"

KEEP_LAST = 5
PAD_DEG = 1.5  # запас за пределами видимого bbox для сглаживания без edge-артефактов
DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
G = 9.80665

CENTER_LAT, CENTER_LON = fc.CENTER_LAT, fc.CENTER_LON
TIERS = {
    "near": {
        "bbox": (CENTER_LON - 2.5, CENTER_LAT - 2.5, CENTER_LON + 2.5, CENTER_LAT + 2.5),
        "px": (400, 600),
        "out_dir": os.path.join(REPO_DIR, "data", "icon_front_near"),
        "label": "Центральный тайл (±2.5°)",
    },
    "far": {
        "bbox": (CENTER_LON - 13.0, CENTER_LAT - 13.0, CENTER_LON + 13.0, CENTER_LAT + 13.0),
        "px": (700, 950),
        "out_dir": os.path.join(REPO_DIR, "data", "icon_front_far"),
        "label": "Дальний контроль (~1000км)",
    },
    "very_far": {
        "bbox": (-10.0, 35.0, 32.0, 60.0),
        "px": (800, 700),
        "out_dir": os.path.join(REPO_DIR, "data", "icon_front_very_far"),
        "label": "Very far (Испания/Италия/Британия/Балканы)",
    },
}

_all_wests = [t["bbox"][0] for t in TIERS.values()]
_all_souths = [t["bbox"][1] for t in TIERS.values()]
_all_easts = [t["bbox"][2] for t in TIERS.values()]
_all_norths = [t["bbox"][3] for t in TIERS.values()]
DL_WEST, DL_SOUTH = min(_all_wests) - PAD_DEG, min(_all_souths) - PAD_DEG
DL_EAST, DL_NORTH = max(_all_easts) + PAD_DEG, max(_all_norths) + PAD_DEG

LOG_LINES = []


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    LOG_LINES.append(line)
    print(line, flush=True)


def build_url(run_dt, lead_hours, param_dir, level_type, level, param_upper):
    run_tag = run_dt.strftime("%Y%m%d%H")
    if level_type == "single-level":
        fname = f"icon-eu_europe_regular-lat-lon_single-level_{run_tag}_{lead_hours:03d}_{param_upper}.grib2.bz2"
    elif level_type == "pressure-level":
        fname = f"icon-eu_europe_regular-lat-lon_pressure-level_{run_tag}_{lead_hours:03d}_{level}_{param_upper}.grib2.bz2"
    elif level_type == "time-invariant":
        fname = f"icon-eu_europe_regular-lat-lon_time-invariant_{run_tag}_{param_upper}.grib2.bz2"
    else:
        raise ValueError(level_type)
    return f"{DWD_BASE}/{run_dt.hour:02d}/{param_dir}/{fname}"


def download_and_parse(url, scratch_name):
    r = requests.get(url, timeout=60)
    if r.status_code != 200 or len(r.content) < 1000:
        return None, {"url": url, "http_status": r.status_code}
    raw = bz2.decompress(r.content)
    scratch_path = f"/tmp/_scratch_ifvf_{scratch_name}.grib2"
    with open(scratch_path, "wb") as f:
        f.write(raw)
    del raw
    import eccodes
    with open(scratch_path, "rb") as f:
        gid = eccodes.codes_grib_new_from_file(f)
        if gid is None:
            os.remove(scratch_path)
            return None, {"url": url, "error": "no GRIB message"}
        units = eccodes.codes_get(gid, "units")
        raw_data = eccodes.codes_grib_get_data(gid)
        eccodes.codes_release(gid)
    os.remove(scratch_path)

    if isinstance(raw_data, tuple) and len(raw_data) == 3:
        lats, lons, values = (np.asarray(x) for x in raw_data)
    else:
        lats = np.array([d.lat for d in raw_data])
        lons = np.array([d.lon for d in raw_data])
        values = np.array([d.value for d in raw_data])

    uniq_lats = np.unique(lats)
    uniq_lons = np.unique(lons)
    lat_idx = {v: i for i, v in enumerate(uniq_lats)}
    lon_idx = {v: i for i, v in enumerate(uniq_lons)}
    grid = np.full((len(uniq_lats), len(uniq_lons)), np.nan, dtype=np.float64)
    li = np.array([lat_idx[v] for v in lats])
    lo = np.array([lon_idx[v] for v in lons])
    grid[li, lo] = values

    lat_mask = (uniq_lats >= DL_SOUTH) & (uniq_lats <= DL_NORTH)
    lon_mask = (uniq_lons >= DL_WEST) & (uniq_lons <= DL_EAST)
    grid = grid[np.ix_(lat_mask, lon_mask)]
    uniq_lats = uniq_lats[lat_mask]
    uniq_lons = uniq_lons[lon_mask]

    return (grid, uniq_lats, uniq_lons), {"url": url, "units": units, "bytes": len(r.content)}


def crop_to_bbox(field, lats, lons, west, south, east, north):
    lat_mask = (lats >= south) & (lats <= north)
    lon_mask = (lons >= west) & (lons <= east)
    return field[np.ix_(lat_mask, lon_mask)], lats[lat_mask], lons[lon_mask]


def find_latest_run_lead():
    now = datetime.now(timezone.utc)
    candidates = []
    for day_offset in (0, -1):
        day = (now + timedelta(days=day_offset)).date()
        for hour in (18, 12, 6, 0):
            run_dt = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
            if run_dt > now:
                continue
            lead = int((now - run_dt).total_seconds() // 3600)
            max_lead = 78 if hour in (0, 12) else 30
            lead = min(lead, max_lead)
            if lead < 0:
                continue
            candidates.append((run_dt, lead))
    candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    for run_dt, lead in candidates:
        url = build_url(run_dt, lead, "pmsl", "single-level", None, "PMSL")
        try:
            r = requests.head(url, timeout=15)
            if r.status_code == 200:
                return run_dt, lead
        except Exception:
            continue
    return None, None


def km_scale(lats, lons):
    km_per_deg_lat = 111.32
    mean_lat = float(np.nanmean(lats))
    km_per_deg_lon = 111.32 * math.cos(math.radians(mean_lat))
    dlat_deg = float(np.mean(np.diff(lats))) if len(lats) > 1 else 1.0
    dlon_deg = float(np.mean(np.diff(lons))) if len(lons) > 1 else 1.0
    return dlat_deg * km_per_deg_lat, dlon_deg * km_per_deg_lon


def grad_mag_per_100km(field, lats, lons):
    dy_km, dx_km = km_scale(lats, lons)
    dFdy, dFdx = np.gradient(field, dy_km, dx_km)
    return np.sqrt(dFdx**2 + dFdy**2) * 100.0, dFdx, dFdy


def normalize_percentile(field, p_lo=5, p_hi=95):
    lo, hi = np.nanpercentile(field, [p_lo, p_hi])
    if hi <= lo:
        return np.zeros_like(field)
    return np.clip((field - lo) / (hi - lo), 0.0, 1.0)


def compute_pfront(fields, lats, lons, bbox):
    SIGMA = 2.0
    fi500 = gaussian_filter(fields["fi500"], SIGMA)
    fi1000 = gaussian_filter(fields["fi1000"], SIGMA)
    u = gaussian_filter(fields["u850"], SIGMA)
    v = gaussian_filter(fields["v850"], SIGMA)
    rh = gaussian_filter(fields["relhum850"], SIGMA)

    thickness_m = (fi500 - fi1000) / G
    thick_grad, thick_dx, thick_dy = grad_mag_per_100km(thickness_m, lats, lons)

    dy_km, dx_km = km_scale(lats, lons)
    dudy, dudx = np.gradient(u, dy_km, dx_km)
    dvdy, dvdx = np.gradient(v, dy_km, dx_km)
    convergence = -(dudx + dvdy) / 1000.0
    vorticity = (dvdx - dudy) / 1000.0

    speed = np.maximum(np.sqrt(u**2 + v**2), 0.1)
    cos_d, sin_d = u / speed, v / speed
    dcos_dy, dcos_dx = np.gradient(cos_d, dy_km, dx_km)
    dsin_dy, dsin_dx = np.gradient(sin_d, dy_km, dx_km)
    wind_dir_shift = np.sqrt(dcos_dx**2 + dcos_dy**2 + dsin_dx**2 + dsin_dy**2) * 100.0

    rh_grad, _, _ = grad_mag_per_100km(rh, lats, lons)

    s_thick = normalize_percentile(thick_grad)
    s_conv = normalize_percentile(np.abs(convergence))
    s_vort = normalize_percentile(np.abs(vorticity))
    s_rh = normalize_percentile(rh_grad)
    s_wshift = normalize_percentile(wind_dir_shift)

    core = np.mean(np.stack([s_thick, s_wshift]), axis=0)
    support = np.mean(np.stack([s_rh, s_conv, s_vort]), axis=0)
    p_c = core * (0.5 + 0.5 * support)

    fr_land = fields.get("fr_land")
    if fr_land is not None:
        coast_grad, coast_dx, coast_dy = grad_mag_per_100km(fr_land, lats, lons)
        near_coast = coast_grad > np.nanpercentile(coast_grad, 80)
        denom = (np.sqrt(thick_dx**2 + thick_dy**2) * np.sqrt(coast_dx**2 + coast_dy**2)) + 1e-9
        align = np.abs((thick_dx * coast_dx + thick_dy * coast_dy) / denom)
        other_weak = 1.0 - np.clip((s_wshift + s_vort) / 2.0, 0, 1)
        p_c = p_c * (1 - 0.7 * align * other_weak * near_coast.astype(float))

    hsurf = fields.get("hsurf")
    if hsurf is not None:
        oro_grad, oro_dx, oro_dy = grad_mag_per_100km(hsurf, lats, lons)
        local_relief = maximum_filter(hsurf, size=5) - minimum_filter(hsurf, size=5)
        near_mountain = (oro_grad > np.nanpercentile(oro_grad, 80)) & (local_relief > 150.0)
        denom = (np.sqrt(thick_dx**2 + thick_dy**2) * np.sqrt(oro_dx**2 + oro_dy**2)) + 1e-9
        align = np.abs((thick_dx * oro_dx + thick_dy * oro_dy) / denom)
        other_weak = 1.0 - np.clip((s_wshift + s_vort) / 2.0, 0, 1)
        p_c = p_c * (1 - 0.7 * align * other_weak * near_mountain.astype(float))

    west, south, east, north = bbox
    return crop_to_bbox(p_c, lats, lons, west, south, east, north)


def render_transparent_isobars(pmsl, lats, lons, out_path, bbox, px):
    west, south, east, north = bbox
    sat_w, sat_h = px
    pmsl_smooth = gaussian_filter(pmsl, 4.0)
    pmsl_vis, lats_vis, lons_vis = crop_to_bbox(pmsl_smooth, lats, lons, west, south, east, north)

    dpi = 100
    fig = plt.figure(figsize=(sat_w / dpi, sat_h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(west, east); ax.set_ylim(south, north)
    ax.axis("off")
    vmin, vmax = float(np.nanmin(pmsl_vis)), float(np.nanmax(pmsl_vis))
    levels = np.arange(math.floor(vmin / 2) * 2, math.ceil(vmax / 2) * 2 + 2, 2)
    cs = ax.contour(lons_vis, lats_vis, pmsl_vis, levels=levels, colors="white", linewidths=1.4)
    try:
        cs.set_path_effects([pe.withStroke(linewidth=3.2, foreground="black")])
    except AttributeError:
        for line in cs.collections:
            line.set_path_effects([pe.withStroke(linewidth=3.2, foreground="black")])
    clabels = ax.clabel(cs, inline=True, fontsize=7, fmt="%d", colors="yellow")
    for txt in clabels:
        txt.set_path_effects([pe.withStroke(linewidth=2.5, foreground="black")])
    fig.savefig(out_path, dpi=dpi, transparent=True)
    plt.close(fig)


def render_transparent_pfront(p_front, lats, lons, out_path, bbox, px):
    west, south, east, north = bbox
    sat_w, sat_h = px
    dpi = 100
    fig = plt.figure(figsize=(sat_w / dpi, sat_h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(west, east); ax.set_ylim(south, north)
    ax.axis("off")
    cmap = plt.get_cmap("inferno")
    rgba = cmap(p_front)
    rgba[..., 3] = np.clip(0.25 + 0.75 * p_front, 0, 1)
    ax.imshow(rgba, extent=(lons.min(), lons.max(), lats.min(), lats.max()),
              origin="lower", aspect="auto")
    fig.savefig(out_path, dpi=dpi, transparent=True)
    plt.close(fig)


def git_sync():
    lock = open(GIT_LOCK_FILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        subprocess.run(["git", "-C", REPO_DIR, "fetch", "--depth", "20", "origin", "main", "--update-shallow"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "checkout", "-B", "main", "origin/main"], check=True)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def git_commit_push(paths, message):
    lock = open(GIT_LOCK_FILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        subprocess.run(["git", "-C", REPO_DIR, "add"] + paths, check=True)
        r = subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", message])
        if r.returncode != 0:
            return False
        for attempt in range(3):
            push = subprocess.run(["git", "-C", REPO_DIR, "push", "origin", "main"])
            if push.returncode == 0:
                return True
            log(f"push не прошёл (попытка {attempt+1}/3), делаю fetch+rebase и повторяю...")
            subprocess.run(["git", "-C", REPO_DIR, "fetch", "--depth", "20", "origin", "main", "--update-shallow"], check=True)
            rebase = subprocess.run(["git", "-C", REPO_DIR, "rebase", "origin/main"])
            if rebase.returncode != 0:
                subprocess.run(["git", "-C", REPO_DIR, "rebase", "--abort"])
                log("rebase не удался, прерываю попытки push")
                return False
        return False
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def process_tier(tier_key, tier_cfg, fields, lats, lons, run_dt, lead, valid_dt):
    bbox = tier_cfg["bbox"]
    px = tier_cfg["px"]
    out_dir = tier_cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")
    log_path = os.path.join(out_dir, "latest_log.txt")

    manifest = {"snapshots": []}
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path))
        except Exception:
            log(f"[{tier_key}] manifest.json повреждён, начинаем заново")

    valid_iso = valid_dt.isoformat()
    if manifest["snapshots"] and manifest["snapshots"][-1]["valid_time"] == valid_iso:
        log(f"[{tier_key}] уже есть снимок на {valid_iso} — пропускаю")
        with open(log_path, "w") as f:
            f.write("\n".join(LOG_LINES[-300:]))
        return False

    log(f"[{tier_key}] считаю P_front...")
    p_front, p_lats, p_lons = compute_pfront(fields, lats, lons, bbox)

    ts_label = valid_dt.strftime("%Y%m%dT%H%M%SZ")
    geocolour_path = os.path.join(out_dir, f"{ts_label}_geocolour.png")
    isobars_path = os.path.join(out_dir, f"{ts_label}_isobars.png")
    pfront_path = os.path.join(out_dir, f"{ts_label}_pfront.png")

    log(f"[{tier_key}] запрашиваю EUMETSAT GeoColour...")
    arr = None
    eumetsat_actual_iso = None
    for back_min in (0, 5, 10, 15, 20, 25, 30):
        t_try = valid_dt - timedelta(minutes=back_min)
        t_iso = t_try.strftime("%Y-%m-%dT%H:%M:00Z")
        try:
            arr = fc.fetch_map_custom("mtg_fd:rgb_geocolour", bbox, px[0], px[1],
                                       time_iso=t_iso, retries=1, delay=3, style="", crs="CRS:84")
            eumetsat_actual_iso = t_iso
            if back_min > 0:
                log(f"[{tier_key}]  точного кадра не было, использован ближайший: {t_iso} (-{back_min} мин)")
            break
        except Exception as e:
            log(f"[{tier_key}]  {t_iso} недоступен ({e}); пробую раньше")
    if arr is None:
        log(f"[{tier_key}] EUMETSAT недоступен даже с fallback — пропускаю тир на этот цикл")
        with open(log_path, "w") as f:
            f.write("\n".join(LOG_LINES[-300:]))
        return False
    Image.fromarray(arr).save(geocolour_path)

    log(f"[{tier_key}] рендерю изобары и P_front...")
    render_transparent_isobars(fields["pmsl"], lats, lons, isobars_path, bbox, px)
    render_transparent_pfront(p_front, p_lats, p_lons, pfront_path, bbox, px)

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": run_dt.isoformat(),
        "lead_hours": lead,
        "valid_time": valid_iso,
        "bbox": list(bbox),
        "width": px[0], "height": px[1],
        "files": {
            "geocolour": os.path.basename(geocolour_path),
            "isobars": os.path.basename(isobars_path),
            "pfront": os.path.basename(pfront_path),
        },
        "pfront_mean": float(np.nanmean(p_front)),
        "pfront_max": float(np.nanmax(p_front)),
        "eumetsat_requested_time": valid_iso,
        "eumetsat_actual_time": eumetsat_actual_iso,
    }
    manifest["snapshots"].append(snapshot)

    while len(manifest["snapshots"]) > KEEP_LAST:
        old = manifest["snapshots"].pop(0)
        for fn in old["files"].values():
            p = os.path.join(out_dir, fn)
            if os.path.exists(p):
                os.remove(p)
        log(f"[{tier_key}] удалён старый снимок {old['valid_time']}")

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    with open(log_path, "w") as f:
        f.write("\n".join(LOG_LINES[-300:]))
    return True


def main():
    own_lock = open(OWN_LOCK_FILE, "w")
    try:
        fcntl.flock(own_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("другой экземпляр уже выполняется — выходим")
        return

    try:
        log("Синхронизирую репозиторий...")
        try:
            git_sync()
        except Exception as e:
            log(f"git_sync не удался: {e} — продолжаю с локальной копией как есть")

        log("Ищу самый свежий опубликованный run+lead ICON-EU...")
        run_dt, lead = find_latest_run_lead()
        if run_dt is None:
            log("Не нашёл ни одного опубликованного run+lead — выходим")
            return
        valid_dt = run_dt + timedelta(hours=lead)
        log(f"run={run_dt.isoformat()} lead={lead} valid_time={valid_dt.isoformat()}")

        needs_update = {}
        for tier_key, tier_cfg in TIERS.items():
            manifest_path = os.path.join(tier_cfg["out_dir"], "manifest.json")
            last_valid = None
            if os.path.exists(manifest_path):
                try:
                    m = json.load(open(manifest_path))
                    if m["snapshots"]:
                        last_valid = m["snapshots"][-1]["valid_time"]
                except Exception:
                    pass
            needs_update[tier_key] = (last_valid != valid_dt.isoformat())

        if not any(needs_update.values()):
            log("Все три тира уже на этом valid_time — новых данных нет, выходим")
            return

        log(f"Тиры к обновлению: {[k for k, v in needs_update.items() if v]}")

        specs = {
            "pmsl": ("pmsl", "single-level", None, "PMSL", lead),
            "fi500": ("fi", "pressure-level", 500, "FI", lead),
            "fi1000": ("fi", "pressure-level", 1000, "FI", lead),
            "u850": ("u", "pressure-level", 850, "U", lead),
            "v850": ("v", "pressure-level", 850, "V", lead),
            "relhum850": ("relhum", "pressure-level", 850, "RELHUM", lead),
            "fr_land": ("fr_land", "time-invariant", None, "FR_LAND", 0),
            "fr_lake": ("fr_lake", "time-invariant", None, "FR_LAKE", 0),
            "hsurf": ("hsurf", "time-invariant", None, "HSURF", 0),
        }
        fields = {}
        lats = lons = None
        total_bytes = 0
        for key, (param_dir, level_type, level, upper, lh) in specs.items():
            url = build_url(run_dt, lh, param_dir, level_type, level, upper)
            log(f"скачиваю {key}: {url}")
            result, meta = download_and_parse(url, key)
            total_bytes += meta.get("bytes", 0)
            if result is None:
                log(f"  НЕ УДАЛОСЬ: {meta}")
                fields[key] = None
                continue
            grid, la, lo = result
            if lats is None:
                lats, lons = la, lo
            fields[key] = grid
            if key == "pmsl":
                fields[key] = grid / 100.0
        log(f"Скачано всего ~{total_bytes/1e6:.2f} МБ (на все три тира сразу)")

        if fields["pmsl"] is None or fields["fi500"] is None:
            raise RuntimeError("нет обязательных полей (PMSL/FI500) — прерываю")

        touched_dirs = []
        for tier_key, tier_cfg in TIERS.items():
            if not needs_update[tier_key]:
                log(f"[{tier_key}] уже свежий — пропускаю")
                continue
            try:
                if process_tier(tier_key, tier_cfg, fields, lats, lons, run_dt, lead, valid_dt):
                    touched_dirs.append(f"data/{os.path.basename(tier_cfg['out_dir'])}/")
            except Exception as e:
                log(f"[{tier_key}] ОШИБКА: {e}")
                log(traceback.format_exc())

        if touched_dirs:
            log(f"Коммичу и пушу: {touched_dirs}")
            ok = git_commit_push(touched_dirs, f"icon_front: snapshot {valid_dt.isoformat()} ({', '.join(touched_dirs)})")
            log(f"git push: {'OK' if ok else 'нечего коммитить/не удалось'}")
        else:
            log("Ни один тир не обновился — коммитить нечего")

    except Exception as e:
        log(f"ОШИБКА (main): {e}")
        log(traceback.format_exc())
    finally:
        fcntl.flock(own_lock, fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
