"""
scripts/icon_front_very_far_snapshot.py

Периодический (cron, каждые 15 мин, отдельный процесс — НЕ часть
vps_satellite_pipeline.py / vps_pipeline.py) снимок для тестовой страницы
front_test.html:
  - изобары ICON-EU PMSL на тайле very_far;
  - P_front (variant C + coastal + orography penalty) — эксперимент
    icon_front_v1 (см. docs/ai/ICON_EU_FRONT_DETECTOR_V1_OFFLINE_EXPERIMENT.md
    после коммита), впервые выведенный в production в виде тестовой карты;
  - EUMETSAT GeoColour на то же самое время (valid_time), для сравнения.

Каждый запуск сам решает, вышел ли новый час ICON-EU с прошлого успешного
снимка; если нет — ничего не делает и не тратит трафик. Хранится не более
KEEP_LAST снимков — старые файлы и записи манифеста удаляются.

НЕ трогает: nearby.html, существующие детекторы, data/geo_config.json,
существующие cron-пайплайны. Коммитит только data/icon_front_very_far/**
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
from scipy import ndimage
from scipy.ndimage import maximum_filter, minimum_filter
from skimage.morphology import skeletonize

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

REPO_DIR = "/opt/weather-pipeline/repo"
sys.path.insert(0, os.path.join(REPO_DIR, "scripts"))
import field_motion_common as fc  # noqa: E402

GIT_LOCK_FILE = "/tmp/vps_git.lock"
OWN_LOCK_FILE = "/tmp/icon_front_very_far.lock"

OUT_DIR = os.path.join(REPO_DIR, "data", "icon_front_very_far")
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")
LOG_PATH = os.path.join(OUT_DIR, "latest_log.txt")
KEEP_LAST = 5

WEST, SOUTH, EAST, NORTH = -10.0, 35.0, 32.0, 60.0  # тир very_far, data/geo_config.json
SAT_W, SAT_H = 800, 700  # ~4 км/px, как у production very_far (target_km_per_px=4.0)

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
G = 9.80665

LOG_LINES = []


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    LOG_LINES.append(line)
    print(line, flush=True)


# ---------------------------------------------------------------------------
# Скачивание / парсинг GRIB (та же логика, что в icon_front_v1_engine.py)
# ---------------------------------------------------------------------------

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

    lat_mask = (uniq_lats >= SOUTH) & (uniq_lats <= NORTH)
    lon_mask = (uniq_lons >= WEST) & (uniq_lons <= EAST)
    grid = grid[np.ix_(lat_mask, lon_mask)]
    uniq_lats = uniq_lats[lat_mask]
    uniq_lons = uniq_lons[lon_mask]

    return (grid, uniq_lats, uniq_lons), {"url": url, "units": units, "bytes": len(r.content)}


def find_latest_run_lead():
    """Ищет самый свежий run (00/06/12/18) с самым маленьким lead, для
    которого PMSL реально опубликован на opendata.dwd.de. Возвращает
    (run_dt, lead) или (None, None)."""
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
    # пробуем от самого свежего (максимальный run_dt, минимальный lead) к старым
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


def compute_pfront(fields, lats, lons):
    pmsl, fi500, fi1000 = fields["pmsl"], fields["fi500"], fields["fi1000"]
    u, v, rh = fields["u850"], fields["v850"], fields["relhum850"]

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

    # coastal penalty
    fr_land = fields.get("fr_land")
    if fr_land is not None:
        coast_grad, coast_dx, coast_dy = grad_mag_per_100km(fr_land, lats, lons)
        near_coast = coast_grad > np.nanpercentile(coast_grad, 80)
        denom = (np.sqrt(thick_dx**2 + thick_dy**2) * np.sqrt(coast_dx**2 + coast_dy**2)) + 1e-9
        align = np.abs((thick_dx * coast_dx + thick_dy * coast_dy) / denom)
        other_weak = 1.0 - np.clip((s_wshift + s_vort) / 2.0, 0, 1)
        p_c = p_c * (1 - 0.7 * align * other_weak * near_coast.astype(float))

    # orography penalty
    hsurf = fields.get("hsurf")
    if hsurf is not None:
        oro_grad, oro_dx, oro_dy = grad_mag_per_100km(hsurf, lats, lons)
        local_relief = maximum_filter(hsurf, size=5) - minimum_filter(hsurf, size=5)
        near_mountain = (oro_grad > np.nanpercentile(oro_grad, 80)) & (local_relief > 150.0)
        denom = (np.sqrt(thick_dx**2 + thick_dy**2) * np.sqrt(oro_dx**2 + oro_dy**2)) + 1e-9
        align = np.abs((thick_dx * oro_dx + thick_dy * oro_dy) / denom)
        other_weak = 1.0 - np.clip((s_wshift + s_vort) / 2.0, 0, 1)
        p_c = p_c * (1 - 0.7 * align * other_weak * near_mountain.astype(float))

    return p_c


# ---------------------------------------------------------------------------
# Рендер прозрачных слоёв, пиксель-в-пиксель совпадающих с geocolour
# ---------------------------------------------------------------------------

def render_transparent_isobars(pmsl, lats, lons, out_path):
    dpi = 100
    fig = plt.figure(figsize=(SAT_W / dpi, SAT_H / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(WEST, EAST); ax.set_ylim(SOUTH, NORTH)
    ax.axis("off")
    vmin, vmax = float(np.nanmin(pmsl)), float(np.nanmax(pmsl))
    levels = np.arange(math.floor(vmin / 2) * 2, math.ceil(vmax / 2) * 2 + 2, 2)
    cs = ax.contour(lons, lats, pmsl, levels=levels, colors="white", linewidths=1.4)
    try:
        cs.set_path_effects([pe.withStroke(linewidth=3.2, foreground="black")])
    except AttributeError:
        # старые версии matplotlib (<3.8): ContourSet — набор LineCollection
        for line in cs.collections:
            line.set_path_effects([pe.withStroke(linewidth=3.2, foreground="black")])
    clabels = ax.clabel(cs, inline=True, fontsize=7, fmt="%d", colors="yellow")
    for txt in clabels:
        txt.set_path_effects([pe.withStroke(linewidth=2.5, foreground="black")])
    fig.savefig(out_path, dpi=dpi, transparent=True)
    plt.close(fig)


def render_transparent_pfront(p_front, lats, lons, out_path):
    dpi = 100
    fig = plt.figure(figsize=(SAT_W / dpi, SAT_H / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(WEST, EAST); ax.set_ylim(SOUTH, NORTH)
    ax.axis("off")
    cmap = plt.get_cmap("inferno")
    rgba = cmap(p_front)
    rgba[..., 3] = np.clip(p_front, 0, 1)  # альфа = сила сигнала: слабый = прозрачный
    ax.imshow(rgba, extent=(lons.min(), lons.max(), lats.min(), lats.max()),
              origin="lower", aspect="auto")
    fig.savefig(out_path, dpi=dpi, transparent=True)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Git commit под общим локом (как остальные VPS-пайплайны)
# ---------------------------------------------------------------------------

def git_sync():
    """Синхронизация репозитория ПЕРЕД записью новых файлов — чтобы
    последующий commit/push не столкнулся с чужими изменениями, и чтобы
    коммит-шаг НЕ делал fetch/checkout повторно (иначе он мог бы затереть
    только что записанные, ещё не закоммиченные файлы)."""
    lock = open(GIT_LOCK_FILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        subprocess.run(["git", "-C", REPO_DIR, "fetch", "--depth", "20", "origin", "main", "--update-shallow"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "checkout", "-B", "main", "origin/main"], check=True)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def git_commit_push(paths, message):
    """Только add+commit+push — БЕЗ fetch/checkout (тот уже сделан в
    git_sync() до записи файлов), чтобы не затереть свежезаписанные,
    ещё не закоммиченные изменения сбросом ветки на origin."""
    lock = open(GIT_LOCK_FILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        subprocess.run(["git", "-C", REPO_DIR, "add"] + paths, check=True)
        r = subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", message])
        if r.returncode == 0:
            subprocess.run(["git", "-C", REPO_DIR, "push", "origin", "main"], check=True)
            return True
        return False
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    own_lock = open(OWN_LOCK_FILE, "w")
    try:
        fcntl.flock(own_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("другой экземпляр уже выполняется — выходим")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    log("Синхронизирую репозиторий перед чтением manifest.json...")
    try:
        git_sync()
    except Exception as e:
        log(f"git_sync не удался: {e} — продолжаю с локальной копией как есть")

    manifest = {"snapshots": []}
    if os.path.exists(MANIFEST_PATH):
        try:
            manifest = json.load(open(MANIFEST_PATH))
        except Exception:
            log("manifest.json повреждён, начинаем заново")

    log("Ищу самый свежий опубликованный run+lead ICON-EU...")
    run_dt, lead = find_latest_run_lead()
    if run_dt is None:
        log("Не нашёл ни одного опубликованного run+lead — выходим")
        write_log()
        git_commit_push(["data/icon_front_very_far/"], "icon_front_very_far: log update (no run found)")
        fcntl.flock(own_lock, fcntl.LOCK_UN)
        return
    valid_dt = run_dt + timedelta(hours=lead)
    valid_iso = valid_dt.isoformat()
    log(f"run={run_dt.isoformat()} lead={lead} valid_time={valid_iso}")

    if manifest["snapshots"] and manifest["snapshots"][-1]["valid_time"] == valid_iso:
        log("Уже есть свежий снимок на этот valid_time — новых данных нет, выходим")
        write_log()
        git_commit_push(["data/icon_front_very_far/"], "icon_front_very_far: log update (up to date)")
        fcntl.flock(own_lock, fcntl.LOCK_UN)
        return

    try:
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
                fields[key] = grid / 100.0  # Pa -> hPa
        log(f"Скачано всего ~{total_bytes/1e6:.2f} МБ")

        if fields["pmsl"] is None or fields["fi500"] is None:
            raise RuntimeError("нет обязательных полей (PMSL/FI500) — прерываю")

        log("Считаю P_front (variant C + coastal + orography)...")
        p_front = compute_pfront(fields, lats, lons)

        ts_label = valid_dt.strftime("%Y%m%dT%H%M%SZ")
        geocolour_path = os.path.join(OUT_DIR, f"{ts_label}_geocolour.png")
        isobars_path = os.path.join(OUT_DIR, f"{ts_label}_isobars.png")
        pfront_path = os.path.join(OUT_DIR, f"{ts_label}_pfront.png")

        log("Запрашиваю EUMETSAT GeoColour на то же valid_time...")
        t_iso = valid_dt.strftime("%Y-%m-%dT%H:%M:00Z")
        arr = fc.fetch_map_custom("mtg_fd:rgb_geocolour", (WEST, SOUTH, EAST, NORTH), SAT_W, SAT_H,
                                   time_iso=t_iso, retries=2, delay=5, style="", crs="CRS:84")
        Image.fromarray(arr).save(geocolour_path)

        log("Рендерю изобары (прозрачный слой)...")
        render_transparent_isobars(fields["pmsl"], lats, lons, isobars_path)

        log("Рендерю P_front (прозрачный слой)...")
        render_transparent_pfront(p_front, lats, lons, pfront_path)

        snapshot = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run": run_dt.isoformat(),
            "lead_hours": lead,
            "valid_time": valid_iso,
            "bbox": [WEST, SOUTH, EAST, NORTH],
            "width": SAT_W, "height": SAT_H,
            "files": {
                "geocolour": os.path.basename(geocolour_path),
                "isobars": os.path.basename(isobars_path),
                "pfront": os.path.basename(pfront_path),
            },
            "downloaded_mb": round(total_bytes / 1e6, 2),
            "pfront_mean": float(np.nanmean(p_front)),
            "pfront_max": float(np.nanmax(p_front)),
        }
        manifest["snapshots"].append(snapshot)

        # ротация: держим только KEEP_LAST
        while len(manifest["snapshots"]) > KEEP_LAST:
            old = manifest["snapshots"].pop(0)
            for fn in old["files"].values():
                p = os.path.join(OUT_DIR, fn)
                if os.path.exists(p):
                    os.remove(p)
            log(f"удалён старый снимок {old['valid_time']}")

        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        log("Готово, коммичу и пушу...")
        write_log()
        ok = git_commit_push(["data/icon_front_very_far/"],
                              f"icon_front_very_far: snapshot {valid_iso}")
        log(f"git push: {'OK' if ok else 'нечего коммитить'}")

    except Exception as e:
        log(f"ОШИБКА: {e}")
        log(traceback.format_exc())
        write_log()
    finally:
        fcntl.flock(own_lock, fcntl.LOCK_UN)


def write_log():
    try:
        with open(LOG_PATH, "w") as f:
            f.write("\n".join(LOG_LINES[-300:]))
    except Exception:
        pass


if __name__ == "__main__":
    main()
