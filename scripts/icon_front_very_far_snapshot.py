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
from scipy.ndimage import maximum_filter, minimum_filter, gaussian_filter, binary_closing, binary_dilation

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
FORCE_REGEN = os.environ.get("ICON_FRONT_FORCE") == "1"  # пересобрать текущий valid_time, не трогая историю
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


TERRAIN_MASK_M = 800.0     # выше этой высоты рельефа изобары не рисуем (PMSL там — артефакт приведения)
MIN_CLOSED_LOOP_PX = 120   # замкнутые петли короче — выбрасываем (мелкие «пятна» у гор)
MIN_OPEN_SEG_PX = 90       # открытые обрывки короче (остаются между замаскированными зонами) — тоже
# контур считаем на поле чуть шире видимого тайла и обрезаем уже готовую картинку осями (ax.set_xlim/
# ylim ниже) — иначе кольцо изобары вокруг центра у самого края тайла упирается в границу МАССИВА
# ДАННЫХ и рисуется как разомкнутая дуга, хотя в реальности петля замкнута, просто чуть шире кадра.
# Ограничено тем, что реально скачано (PAD_DEG за пределами САМОГО ШИРОКОГО тира, см. выше) — для
# very_far запас меньше, чем для near/far, т.к. для него самого расширять уже особо некуда.
ISOBAR_CONTOUR_PAD_DEG = float(os.environ.get("ICON_ISOBAR_CONTOUR_PAD_DEG", "3.0"))


def _fill_masked_laplace(field, mask):
    """Гармоническое (лапласово) заполнение клеток mask значениями по их границе: внутри маски
    нет локальных экстремумов, изолинии проходят насквозь плавно, без дырок и «пятен».
    Возвращает новый массив или None, если заполнить нельзя (тогда вызывающий код делает fallback)."""
    from scipy.sparse import coo_matrix, diags
    from scipy.sparse.linalg import spsolve
    mask = np.asarray(mask, dtype=bool)
    n = int(mask.sum())
    if n == 0:
        return field.copy()
    if n == mask.size or not np.all(np.isfinite(field[~mask])):
        return None
    ni, nj = field.shape
    idx = -np.ones(field.shape, dtype=np.int64)
    idx[mask] = np.arange(n)
    ii, jj = np.where(mask)
    me = np.arange(n)
    diag = np.zeros(n)
    rhs = np.zeros(n)
    rows, cols, vals = [], [], []
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ti, tj = ii + di, jj + dj
        inb = (ti >= 0) & (ti < ni) & (tj >= 0) & (tj < nj)
        diag[inb] += 1.0
        t_idx = np.full(n, -1, dtype=np.int64)
        t_idx[inb] = idx[ti[inb], tj[inb]]
        m = t_idx >= 0                      # сосед тоже внутри маски -> неизвестная
        rows.append(me[m]); cols.append(t_idx[m]); vals.append(-np.ones(int(m.sum())))
        known = inb & (t_idx < 0)           # сосед известен -> в правую часть
        rhs[known] += field[ti[known], tj[known]]
    a = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)) + diags(diag)
    x = spsolve(a.tocsr(), rhs)
    if not np.all(np.isfinite(x)):
        return None
    out = field.copy()
    out[mask] = x
    return out


def render_transparent_isobars(pmsl, hsurf, lats, lons, out_path, bbox, px, centers=None):
    """Изобары без «неподвижного мусора»: приведение давления к уровню моря
    над высоким рельефом (Альпы, Пиренеи, Балканы, Анатолия, Атлас…) даёт
    мелкие замкнутые петли, привязанные к рельефу — а рельеф не меняется,
    поэтому эти петли стоят на месте при любой погоде. Их не рисуем:
    (1) не рисуем изобары там, где сглаженный HSURF > TERRAIN_MASK_M;
    (2) выбрасываем мелкие замкнутые петли и короткие обрывки (в пикселях,
    чтобы порог был одинаков для всех тиров)."""
    from contourpy import contour_generator, LineType

    west, south, east, north = bbox
    sat_w, sat_h = px
    # Над высоким рельефом PMSL — артефакт приведения. Раньше там ставили NaN, и изобары получали
    # дырки. Теперь значения в этих клетках заменяются гармоническим продолжением с границы (см.
    # _fill_masked_laplace): линии остаются непрерывными и сплошными.
    terrain = None
    pmsl_src = pmsl
    if hsurf is not None:
        terrain = gaussian_filter(hsurf, 2.0) > TERRAIN_MASK_M
        if terrain.any():
            try:
                filled = _fill_masked_laplace(pmsl, terrain)
            except Exception as e:
                log(f"изобары: заполнение над горами не удалось ({e!r}), fallback на маску")
                filled = None
            if filled is None:
                pmsl_src = np.where(terrain, np.nan, pmsl)
                terrain = None
            else:
                pmsl_src = filled
                log(f"изобары: над рельефом (>{TERRAIN_MASK_M:.0f} м) продолжено {int(terrain.sum())} клеток")
    pmsl_smooth = gaussian_filter(pmsl_src, 4.0)
    pad = ISOBAR_CONTOUR_PAD_DEG
    pmsl_vis, lats_vis, lons_vis = crop_to_bbox(pmsl_smooth, lats, lons,
                                                 west - pad, south - pad, east + pad, north + pad)
    z = np.ma.masked_invalid(pmsl_vis)
    terrain_vis = None
    if terrain is not None:
        terrain_vis = crop_to_bbox(terrain.astype(float), lats, lons,
                                   west - pad, south - pad, east + pad, north + pad)[0] > 0.5

    dpi = 100
    fig = plt.figure(figsize=(sat_w / dpi, sat_h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(west, east); ax.set_ylim(south, north)
    ax.axis("off")

    px_per_lon = sat_w / (east - west)
    px_per_lat = sat_h / (north - south)

    valid = pmsl_vis[np.isfinite(pmsl_vis)]
    if valid.size == 0:
        fig.savefig(out_path, dpi=dpi, transparent=True)
        plt.close(fig)
        return
    vmin, vmax = float(valid.min()), float(valid.max())
    levels = np.arange(math.floor(vmin / 2) * 2, math.ceil(vmax / 2) * 2 + 2, 2)

    cg = contour_generator(lons_vis, lats_vis, z, name="serial", line_type=LineType.Separate)
    halo_line = [pe.withStroke(linewidth=3.2, foreground="black")]
    halo_text = [pe.withStroke(linewidth=2.5, foreground="black")]
    kept = dropped = 0
    for level in levels:
        for seg in cg.lines(float(level)):
            if len(seg) < 2:
                continue
            dxp = np.diff(seg[:, 0]) * px_per_lon
            dyp = np.diff(seg[:, 1]) * px_per_lat
            length_px = float(np.sum(np.hypot(dxp, dyp)))
            closed = bool(np.allclose(seg[0], seg[-1]))
            if length_px < (MIN_CLOSED_LOOP_PX if closed else MIN_OPEN_SEG_PX):
                dropped += 1
                continue
            kept += 1
            flags = np.zeros(len(seg), dtype=bool)
            if terrain_vis is not None and len(lats_vis) > 1 and len(lons_vis) > 1:
                ti = np.clip(np.round((seg[:, 1] - lats_vis[0]) / (lats_vis[1] - lats_vis[0])).astype(int), 0, len(lats_vis) - 1)
                tj = np.clip(np.round((seg[:, 0] - lons_vis[0]) / (lons_vis[1] - lons_vis[0])).astype(int), 0, len(lons_vis) - 1)
                flags = terrain_vis[ti, tj]
            # линия сплошная по всей длине (над рельефом — тоже); flags нужны только чтобы не
            # ставить подпись давления на продолженный участок
            ax.plot(seg[:, 0], seg[:, 1], color="white", linewidth=1.4,
                    solid_capstyle="round", path_effects=halo_line)
            free = np.flatnonzero(~flags)
            if length_px > 140 and len(free) > 0:
                mid = int(free[np.argmin(np.abs(free - len(seg) // 2))])
                x0, y0 = seg[mid]
                px_x = (x0 - west) * px_per_lon
                px_y = (north - y0) * px_per_lat
                if 14 < px_x < sat_w - 14 and 14 < px_y < sat_h - 14:
                    i0, i1 = max(mid - 2, 0), min(mid + 2, len(seg) - 1)
                    ang = math.degrees(math.atan2((seg[i1, 1] - seg[i0, 1]) * px_per_lat,
                                                  (seg[i1, 0] - seg[i0, 0]) * px_per_lon))
                    if ang > 90: ang -= 180
                    if ang < -90: ang += 180
                    ax.text(x0, y0, f"{int(level)}", color="yellow", fontsize=7,
                            rotation=ang, rotation_mode="anchor", ha="center", va="center",
                            path_effects=halo_text,
                            bbox=dict(boxstyle="round,pad=0.12", fc="black", ec="none", alpha=0.55))
    log(f"изобары: оставлено {kept} линий, отброшено {dropped} мелких/над-горных фрагментов")
    if centers:
        n_hl = draw_pressure_centers(ax, centers, bbox, px)
        log(f"L/H: нарисовано {n_hl} центров")
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



def save_testcase(path, fields, lats, lons, run_dt, lead):
    """Замороженный снимок реально скачанных полей — чтобы подбирать пороги ICON_FRONT_*/
    ICON_ISOBAR_* офлайн, на одном и том же случае, без повторного скачивания и без того, что
    погода успела смениться между попытками. Сохраняет только сырые массивы (не _centers/_fronts —
    их каждый раз считает заново тот, кто грузит снимок, уже с новыми параметрами)."""
    arrays = {"lats": lats, "lons": lons,
              "run_dt": np.array(run_dt.isoformat()), "lead": np.array(lead)}
    for k, v in fields.items():
        if isinstance(v, np.ndarray):
            arrays[k] = v
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    np.savez_compressed(path, **arrays)


def load_testcase(path):
    d = np.load(path, allow_pickle=False)
    lats = d["lats"]
    lons = d["lons"]
    run_dt = datetime.fromisoformat(str(d["run_dt"]))
    lead = int(d["lead"])
    fields = {k: d[k] for k in d.files if k not in ("lats", "lons", "run_dt", "lead")}
    return fields, lats, lons, run_dt, lead


# ---------- L/H центры давления ----------
# Циклоны у нас обычно компактные и глубокие — за 500 км давление вокруг них успевает
# заметно вырасти, узкое окно легко ловит их выделенность. Антициклоны в этом регионе чаще
# широкие пологие купола континентального масштаба: при том же 500-километровом окне оно
# целиком лежит внутри самого гребня, даже в истинном пике локальное среднее почти равно
# самому пику (проверено на синтетике: широкий гребень при окне 500км даёт выделенность
# всего ~0.3 гПа — ниже почти любого разумного порога). Окно нужно РАСШИРИТЬ, чтобы оно
# доставало до настоящего фона за пределами гребня — тогда даже тем же порядком порога
# выделенность растёт кратно (на той же синтетике: 500км→0.34, 800км→0.85, 1200км→2.08 гПа).
# Поэтому у L и H — разные окна и разные пороги, настраиваются независимо.
HL_WINDOW_KM_L = float(os.environ.get("ICON_HL_WINDOW_KM_L", "500"))
HL_WINDOW_KM_H = float(os.environ.get("ICON_HL_WINDOW_KM_H", "1200"))
HL_PROMINENCE_HPA_L = float(os.environ.get("ICON_HL_PROMINENCE_HPA_L", "1.5"))
HL_PROMINENCE_HPA_H = float(os.environ.get("ICON_HL_PROMINENCE_HPA_H", "1.0"))


def find_pressure_centers(pmsl, hsurf, lats, lons, debug_log=None):
    """Список (lat, lon, 'L'|'H', hPa) по всей скачанной области."""
    from scipy.ndimage import uniform_filter
    dy_km, dx_km = km_scale(lats, lons)
    p = gaussian_filter(pmsl, 5.0)
    hs = gaussian_filter(hsurf, 2.0) if hsurf is not None else np.zeros_like(p)
    ok = (hs <= TERRAIN_MASK_M)
    out = []
    for kind, win_km, prom_hpa in (("L", HL_WINDOW_KM_L, HL_PROMINENCE_HPA_L),
                                    ("H", HL_WINDOW_KM_H, HL_PROMINENCE_HPA_H)):
        wy = max(3, min(p.shape[0] - 1, int(round(win_km / abs(dy_km))) | 1))
        wx = max(3, min(p.shape[1] - 1, int(round(win_km / abs(dx_km))) | 1))
        mean = uniform_filter(p, size=(wy, wx), mode="nearest")
        if kind == "H":
            mx = maximum_filter(p, size=(wy, wx), mode="nearest")
            mask = (p == mx) & (p > mean + prom_hpa)
            prom = mx - mean
        else:
            mn = minimum_filter(p, size=(wy, wx), mode="nearest")
            mask = (p == mn) & (p < mean - prom_hpa)
            prom = mean - mn
        for i, j in zip(*np.where(mask & ok)):
            out.append((float(lats[i]), float(lons[j]), kind, float(p[i, j])))
        if debug_log is not None:
            # выделенность по всей области, даже там, где порог не пройден — чтобы было видно,
            # насколько близко/далеко реальные пики от текущего порога, без гадания вслепую
            debug_log(f"L/H диагностика [{kind}]: окно {win_km:.0f}км, порог {prom_hpa} гПа, "
                      f"выделенность p50={float(np.nanpercentile(prom,50)):.2f} "
                      f"p90={float(np.nanpercentile(prom,90)):.2f} "
                      f"p99={float(np.nanpercentile(prom,99)):.2f} "
                      f"max={float(np.nanmax(prom)):.2f}, найдено {(mask & ok).sum()}")
    return out


def draw_pressure_centers(ax, centers, bbox, px):
    west, south, east, north = bbox
    sat_w, sat_h = px
    halo = [pe.withStroke(linewidth=3.5, foreground="black")]
    n = 0
    for lat, lon, kind, val in centers:
        if not (west < lon < east and south < lat < north):
            continue
        fx = (lon - west) / (east - west) * sat_w
        fy = (north - lat) / (north - south) * sat_h
        if not (22 < fx < sat_w - 22 and 30 < fy < sat_h - 30):
            continue
        col = "#ff5a5a" if kind == "L" else "#5ab0ff"
        ax.text(lon, lat, kind, color=col, fontsize=22, fontweight="bold",
                ha="center", va="center", path_effects=halo, zorder=6)
        ax.text(lon, lat - (north - south) * 0.028, f"{val:.0f}", color=col,
                fontsize=8, fontweight="bold", ha="center", va="center", path_effects=halo, zorder=6)
        n += 1
    return n


# ---------- линейные фронты (Renard–Clarke по θe на 850 гПа) ----------
# Порог не фиксированный: сила фронтов у нас от прогона к прогону разная (тихая погода —
# все градиенты слабые; выраженный циклон — сильные). Берём верхний процентиль распределения
# градиента в ЭТОМ прогоне (адаптивно), но не ниже абсолютного пола, чтобы в тихую погоду
# не рисовать фронты из чистого шума полей.
FRONT_GRAD_PERCENTILE = float(os.environ.get("ICON_FRONT_GRAD_PERCENTILE", "88"))
FRONT_GRAD_FLOOR = float(os.environ.get("ICON_FRONT_GRAD_FLOOR", "4.0"))   # K/100км, абсолютный пол
FRONT_GRAD_LOW_FRAC = float(os.environ.get("ICON_FRONT_GRAD_LOW_FRAC", "1.0"))  # <1 включает гистерезис (доля основного порога)
FRONT_MIN_KM = float(os.environ.get("ICON_FRONT_MIN_KM", "300"))
FRONT_MIN_STRAIGHTNESS = float(os.environ.get("ICON_FRONT_MIN_STRAIGHTNESS", "0.12"))  # было 0.08 — слишком тонкие шумовые зигзаги проходили
# прямолинейность считается по всей линии целиком и не ловит "крючок" — резкий излом на одном
# конце линии, когда всё остальное вполне ровное. Ловим его отдельно: пересэмплируем линию с
# равным шагом по расстоянию (чтобы не зависеть от того, насколько густо contourpy расставил
# точки) и смотрим на максимальный угол поворота между соседними отрезками.
FRONT_MAX_TURN_DEG = float(os.environ.get("ICON_FRONT_MAX_TURN_DEG", "40"))  # ~радиус разворота <30км режем, >40км пропускаем
FRONT_TURN_STEP_KM = float(os.environ.get("ICON_FRONT_TURN_STEP_KM", "12"))  # близко к разрешению сетки ICON-EU (~7км)


def _resample_by_arclen(seg, kx, step_km):
    d = np.hypot(np.diff(seg[:, 0]) * kx, np.diff(seg[:, 1]) * 111.32)
    cum = np.concatenate([[0.0], np.cumsum(d)])
    total = cum[-1]
    if total < step_km * 2:
        return seg
    n = max(3, int(total / step_km))
    new_cum = np.linspace(0.0, total, n)
    lon_r = np.interp(new_cum, cum, seg[:, 0])
    lat_r = np.interp(new_cum, cum, seg[:, 1])
    return np.column_stack([lon_r, lat_r])


def _max_turn_deg(seg):
    if len(seg) < 3:
        return 0.0
    v = np.diff(seg, axis=0)
    ang = np.arctan2(v[:, 1], v[:, 0])
    dang = np.diff(ang)
    dang = (dang + np.pi) % (2 * np.pi) - np.pi
    return float(np.degrees(np.max(np.abs(dang)))) if len(dang) else 0.0
# --- обрезка крючков (01.10): мелкий порог по одному шагу ловит только шумовые разворота <30км;
# крючок радиусом ~100км (U-образный хвост линии) по одному шагу даёт ~12° и проходит. Поэтому
# смотрим на СУММАРНЫЙ поворот курса на окне FRONT_HOOK_WINDOW_KM; где он больше порога —
# вырезаем участок и оставляем куски линии (а не выбрасываем весь фронт).
FRONT_HOOK_WINDOW_KM = float(os.environ.get("ICON_FRONT_HOOK_WINDOW_KM", "150"))
FRONT_HOOK_MAX_TURN_DEG = float(os.environ.get("ICON_FRONT_HOOK_MAX_TURN_DEG", "55"))  # ~радиус кривизны <150км
# минимальная длина одного типа (cold/warm/stat) вдоль линии: более короткие куски поглощаются
# соседним — иначе тип «мигает» там, где нормальная компонента ветра переходит через ноль.
FRONT_KIND_MIN_RUN_KM = float(os.environ.get("ICON_FRONT_KIND_MIN_RUN_KM", "250"))


def _split_hooks(seg, kx, step_km):
    """Пересэмплирует линию и режет её по крючкам. Возвращает список кусков (массивы lon/lat)."""
    r = _resample_by_arclen(seg, kx, step_km)
    if len(r) < 4:
        return [r]
    v = np.diff(r, axis=0)
    h = np.unwrap(np.arctan2(v[:, 1], v[:, 0]))
    kw = max(2, int(round(FRONT_HOOK_WINDOW_KM / step_km)))
    bad = np.zeros(len(r), dtype=bool)
    # резкий излом на одном шаге
    d1 = np.abs(np.degrees(np.diff(h)))
    for i in np.where(d1 > FRONT_MAX_TURN_DEG)[0]:
        bad[i:i + 3] = True
    # суммарный поворот на окне
    if len(h) > kw:
        w = np.abs(np.degrees(h[kw:] - h[:-kw]))
        for i in np.where(w > FRONT_HOOK_MAX_TURN_DEG)[0]:
            bad[i:i + kw + 2] = True
    pieces, start = [], None
    for i, b in enumerate(bad):
        if not b and start is None:
            start = i
        if b and start is not None:
            if i - start >= 3:
                pieces.append(r[start:i])
            start = None
    if start is not None and len(r) - start >= 3:
        pieces.append(r[start:])
    return pieces


def _merge_short_kind_runs(kind, step_km_arr, min_run_km):
    """kind — массив строк по точкам линии, step_km_arr — длина шага до следующей точки.
    Куски короче min_run_km отдаются соседу (более длинному)."""
    kind = np.array(kind, dtype=object)
    n = len(kind)
    if n < 2:
        return kind
    for _ in range(10):
        runs = []
        s = 0
        for i in range(1, n + 1):
            if i == n or kind[i] != kind[s]:
                runs.append([s, i, float(np.sum(step_km_arr[s:min(i, len(step_km_arr))]))])
                s = i
        if len(runs) <= 1:
            break
        short = [r for r in runs if r[2] < min_run_km]
        if not short:
            break
        r = min(short, key=lambda x: x[2])
        k = runs.index(r)
        left = runs[k - 1] if k > 0 else None
        right = runs[k + 1] if k < len(runs) - 1 else None
        if left is None:
            new = kind[right[0]]
        elif right is None:
            new = kind[left[0]]
        else:
            new = kind[left[0]] if left[2] >= right[2] else kind[right[0]]
        kind[r[0]:r[1]] = new
    return kind

# после фильтров всё ещё остаются почти-дубли: соседние параллельные обрывки одной и той же
# зоны градиента (контур цепляет её с двух сторон) — убираем не-максимальным подавлением по
# расстоянию, оставляя более длинный из пары.
FRONT_DEDUP_RADIUS_KM = float(os.environ.get("ICON_FRONT_DEDUP_RADIUS_KM", "80"))
FRONT_MAX_SEGMENTS = int(os.environ.get("ICON_FRONT_MAX_SEGMENTS", "12"))  # на всю область сразу
# подавление у берега/гор (как у P_front) — доля выбранного градиента, которая срезается там, где
# градиент θe идёт вдоль берега/склона, и пороги "мы точно рядом с берегом/горой"
FRONT_COAST_MOUNTAIN_WEIGHT = float(os.environ.get("ICON_FRONT_COAST_MOUNTAIN_WEIGHT", "0.7"))
FRONT_COAST_MOUNTAIN_PERCENTILE = float(os.environ.get("ICON_FRONT_COAST_MOUNTAIN_PERCENTILE", "80"))
FRONT_MOUNTAIN_RELIEF_M = float(os.environ.get("ICON_FRONT_MOUNTAIN_RELIEF_M", "150.0"))
# требуем циклоническую завихренность на линии фронта — отсекает случаи, когда сильный градиент
# θe есть, но он лежит поперёк гладкого антициклона, а не в барической ложбине/у циклона
FRONT_REQUIRE_CYCLONIC_VORTICITY = os.environ.get("ICON_FRONT_REQUIRE_VORTICITY", "1") == "1"
# окно смыкания разрывов маски "циклоническая завихренность" (в ячейках сетки) — шире, чем
# для градиента (3), потому что провалы ζ<0 вдоль длинной дуги бывают протяжённее по времени/
# пространству, чем мгновенный проседания градиента θe
FRONT_VORTICITY_BRIDGE_CELLS = int(os.environ.get("ICON_FRONT_VORTICITY_BRIDGE_CELLS", "7"))
# если конец линии обрывается не дальше этого расстояния от центра L — мягко дотягиваем до него
FRONT_ATTRACT_TO_LOW_KM = float(os.environ.get("ICON_FRONT_ATTRACT_TO_LOW_KM", "300.0"))
# отношение (расстояние между концами) / (длина линии). Настоящий фронт тянется через
# карту более-менее в одну сторону; шумовая петля вокруг локального пятна градиента
# извивается на месте и почти возвращается к себе — у неё это отношение близко к 0.
FRONT_SMOOTH_CELLS = 8.0   # ~50 км на сетке ICON-EU 0.0625° — жёстче гасим мелкий шум поля
STATIONARY_MS = 1.5        # |нормальная к фронту скорость ветра 850| меньше — стационарный
FRONT_COLORS = {"cold": "#3d8bff", "warm": "#ff4545", "stat": "#c07bff"}  # "stat" рисуется чередованием cold/warm
STAT_DASH_PX = 28.0


def theta_e_bolton(t_k, rh_pct, p_hpa):
    tc = t_k - 273.15
    es = 6.112 * np.exp(17.67 * tc / (tc + 243.5))
    e = np.clip(rh_pct, 1.0, 100.0) / 100.0 * es
    r = 0.622 * e / (p_hpa - e)
    tl = 2840.0 / (3.5 * np.log(t_k) - np.log(e) - 4.805) + 55.0
    return t_k * (1000.0 / p_hpa) ** (0.2854 * (1 - 0.28 * r)) * \
        np.exp((3.376 / tl - 0.00254) * r * 1000.0 * (1 + 0.81 * r))


def compute_fronts(fields, lats, lons, centers=None):
    """Линии фронтов по всей области: нули TFP = -∇|∇θ|·∇θ/|∇θ| там, где градиент θe
    значим и достигает максимума поперёк линии. Тип — по знаку нормальной к фронту
    компоненты ветра 850: в сторону тёплого воздуха → холодный, в сторону холодного →
    тёплый, мало → стационарный. Возвращает (segments, stats)."""
    from contourpy import contour_generator, LineType
    th = theta_e_bolton(fields["t850"], fields["relhum850"], 850.0)
    th = gaussian_filter(th, FRONT_SMOOTH_CELLS)
    u = gaussian_filter(fields["u850"], FRONT_SMOOTH_CELLS)
    v = gaussian_filter(fields["v850"], FRONT_SMOOTH_CELLS)
    dy_km, dx_km = km_scale(lats, lons)
    gy, gx = np.gradient(th, dy_km, dx_km)
    gm = np.hypot(gx, gy)
    gmy, gmx = np.gradient(gm, dy_km, dx_km)
    eps = 1e-9
    nx, ny = gx / (gm + eps), gy / (gm + eps)   # n смотрит в сторону более тёплого воздуха
    tfp = gaussian_filter(-(gmx * nx + gmy * ny), 2.0)
    tfy, tfx = np.gradient(tfp, dy_km, dx_km)
    across = tfx * nx + tfy * ny                 # >0 ⇒ вдоль n градиент проходит максимум
    grad100 = gm * 100.0

    # подавление у берега и в горах — то же самое, что уже сделано для P_front: линия θe850
    # хорошо ловит границу суша/море и подветренный перепад в горах, это не фронт, а рельеф/берег.
    # Гасим там, где градиент θe идёт вдоль градиента доли суши (fr_land) или орографии.
    fr_land = fields.get("fr_land")
    if fr_land is not None:
        coast_grad, coast_dx, coast_dy = grad_mag_per_100km(fr_land, lats, lons)
        near_coast = coast_grad > np.nanpercentile(coast_grad, FRONT_COAST_MOUNTAIN_PERCENTILE)
        denom = (gm * np.hypot(coast_dx, coast_dy)) + eps
        align = np.abs((gx * coast_dx + gy * coast_dy) / denom)
        grad100 = grad100 * (1 - FRONT_COAST_MOUNTAIN_WEIGHT * align * near_coast.astype(float))
    hsurf_raw = fields.get("hsurf")
    if hsurf_raw is not None:
        oro_grad, oro_dx, oro_dy = grad_mag_per_100km(hsurf_raw, lats, lons)
        local_relief = maximum_filter(hsurf_raw, size=5) - minimum_filter(hsurf_raw, size=5)
        near_mountain = (oro_grad > np.nanpercentile(oro_grad, FRONT_COAST_MOUNTAIN_PERCENTILE)) & \
            (local_relief > FRONT_MOUNTAIN_RELIEF_M)
        denom = (gm * np.hypot(oro_dx, oro_dy)) + eps
        align = np.abs((gx * oro_dx + gy * oro_dy) / denom)
        grad100 = grad100 * (1 - FRONT_COAST_MOUNTAIN_WEIGHT * align * near_mountain.astype(float))

    grad_thresh = max(FRONT_GRAD_FLOOR, float(np.nanpercentile(grad100, FRONT_GRAD_PERCENTILE)))
    strong = grad100 > grad_thresh
    if FRONT_GRAD_LOW_FRAC < 0.999:
        # гистерезис (как в Canny): зёрна — клетки выше основного порога; линия продолжается
        # через более слабый градиент (выше FRONT_GRAD_LOW_FRAC * порога), если он связан с зерном.
        # Реальный фронт ослабевает вдоль своей длины; один порог рвёт его на обрывки.
        from scipy.ndimage import label as _label
        weak = grad100 > grad_thresh * FRONT_GRAD_LOW_FRAC
        lab, nlab = _label(weak, structure=np.ones((3, 3)))
        if nlab:
            keep = np.zeros(nlab + 1, dtype=bool)
            keep[np.unique(lab[strong & weak])] = True
            keep[0] = False
            strong = keep[lab]
    # смыкаем разрывы в 1-2 ячейки (~10-15км) вдоль почти непрерывной зоны сильного градиента —
    # иначе контур рвётся на обрывки там, где градиент на мгновение чуть просел ниже порога
    strong_bridged = binary_closing(strong, structure=np.ones((3, 3)))
    valid = strong_bridged & (across > 0) & np.isfinite(tfp)
    if FRONT_REQUIRE_CYCLONIC_VORTICITY:
        # относительная завихренность на 850 гПа (не пересчитываем u/v — те же сглаженные поля,
        # что уже использованы для градиента θe и для определения типа фронта по ветру):
        # ζ = dv/dx - du/dy, из (м/с)/км в 1/с делим на 1000. >0 — циклонический изгиб (СШ) —
        # фронт должен лежать в барической ложбине/у циклона, а не поперёк гладкого антициклона.
        dudy, dudx = np.gradient(u, dy_km, dx_km)
        dvdy, dvdx = np.gradient(v, dy_km, dx_km)
        vorticity = (dvdx - dudy) / 1000.0
        vort_ok = vorticity > 0
        # то же смыкание разрывов, что и для градиента — иначе длинный, в целом циклонический
        # фронт (особенно вдоль дуги атлантического циклона) рвётся на куски там, где
        # завихренность на мгновение чуть проседает ниже нуля вдоль в целом верной дуги
        vort_bridged = binary_closing(vort_ok, structure=np.ones((FRONT_VORTICITY_BRIDGE_CELLS,
                                                                    FRONT_VORTICITY_BRIDGE_CELLS)))
        valid &= vort_bridged
    hsurf = fields.get("hsurf")
    if hsurf is not None:
        valid &= gaussian_filter(hsurf, 2.0) <= TERRAIN_MASK_M
    stats = {"grad100_p50": float(np.nanpercentile(grad100, 50)),
             "grad100_p90": float(np.nanpercentile(grad100, 90)),
             "grad100_p99": float(np.nanpercentile(grad100, 99)),
             "grad100_max": float(np.nanmax(grad100)),
             "threshold_used": grad_thresh,
             "valid_frac": float(valid.mean())}
    z = np.ma.masked_where(~valid, tfp)
    cg = contour_generator(lons, lats, z, name="serial", line_type=LineType.Separate)
    dlat = float(lats[1] - lats[0]); dlon = float(lons[1] - lons[0])
    candidates = []
    for seg in cg.lines(0.0):
        if len(seg) < 6:
            continue
        mlat = float(np.mean(seg[:, 1]))
        kx = 111.32 * math.cos(math.radians(mlat))
        length_km = float(np.sum(np.hypot(np.diff(seg[:, 0]) * kx, np.diff(seg[:, 1]) * 111.32)))
        if length_km < FRONT_MIN_KM:
            continue
        span_km = float(np.hypot((seg[-1, 0] - seg[0, 0]) * kx, (seg[-1, 1] - seg[0, 1]) * 111.32))
        if span_km / length_km < FRONT_MIN_STRAIGHTNESS:
            continue  # шумовая петля/завиток, а не протяжённая линия
        # крючки не выбрасывают линию целиком, а вырезаются; остаются гладкие куски
        for piece in _split_hooks(seg, kx, FRONT_TURN_STEP_KM):
            if len(piece) < 4:
                continue
            p_len = float(np.sum(np.hypot(np.diff(piece[:, 0]) * kx, np.diff(piece[:, 1]) * 111.32)))
            if p_len < FRONT_MIN_KM:
                continue
            ii = np.clip(np.round((piece[:, 1] - lats[0]) / dlat).astype(int), 0, len(lats) - 1)
            jj = np.clip(np.round((piece[:, 0] - lons[0]) / dlon).astype(int), 0, len(lons) - 1)
            candidates.append((p_len, piece, ii, jj))

    # неMax-подавление: сортируем по длине, длинную линию принимаем и «застолбливаем» полосу
    # вокруг неё; более короткую, которая почти целиком лежит в уже застолблённой полосе —
    # выбрасываем как дубль/обрывок той же зоны градиента, а не отдельный фронт.
    dedup_cells = max(1, int(round(FRONT_DEDUP_RADIUS_KM / abs(dx_km))))
    occupied = np.zeros(gm.shape, dtype=bool)
    candidates.sort(key=lambda c: -c[0])
    segs = []
    for length_km, seg, ii, jj in candidates:
        if len(segs) >= FRONT_MAX_SEGMENTS:
            break
        if occupied[ii, jj].mean() > 0.5:
            continue
        m = np.zeros(gm.shape, dtype=bool)
        m[ii, jj] = True
        m = binary_dilation(m, iterations=dedup_cells)
        occupied |= m
        c = u[ii, jj] * nx[ii, jj] + v[ii, jj] * ny[ii, jj]
        k = min(max(3, int(round(FRONT_KIND_MIN_RUN_KM / FRONT_TURN_STEP_KM)) | 1), len(c) | 1)
        c = np.convolve(np.pad(c, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
        kind = np.where(c > STATIONARY_MS, "cold", np.where(c < -STATIONARY_MS, "warm", "stat"))
        kind = _merge_short_kind_runs(kind, np.full(max(len(kind) - 1, 1), FRONT_TURN_STEP_KM), FRONT_KIND_MIN_RUN_KM)
        segs.append({"xy": seg, "kind": kind, "nx": nx[ii, jj], "ny": ny[ii, jj], "km": length_km})
    stats["n_segments"] = len(segs)
    stats["km_total"] = float(sum(s["km"] for s in segs))

    # притягиваем обрывающийся конец линии к ближайшему центру L, если он рядом (по умолчанию
    # ближе 300 км) — иначе фронт визуально "не доходит" до своего циклона на пару ячеек сетки,
    # хотя физически он именно туда и идёт. Достраиваем xy ПРЯМОЙ линией до центра и синхронно
    # растягиваем kind/nx/ny той же длины — иначе покраска и значки на новых точках разъедутся.
    centers_L = [(lat, lon) for lat, lon, kind, _ in (centers or []) if kind == "L"]
    if centers_L:
        for s in segs:
            for end_idx in (0, -1):
                x_end, y_end = s["xy"][end_idx]
                best = min(centers_L, key=lambda c: math.hypot(
                    (x_end - c[1]) * 111.32 * math.cos(math.radians((y_end + c[0]) / 2.0)),
                    (y_end - c[0]) * 111.32))
                l_lat, l_lon = best
                mlat = (y_end + l_lat) / 2.0
                kx = 111.32 * math.cos(math.radians(mlat))
                dist_km = math.hypot((x_end - l_lon) * kx, (y_end - l_lat) * 111.32)
                if dist_km >= FRONT_ATTRACT_TO_LOW_KM:
                    continue
                n_steps = max(2, int(dist_km / 15.0))
                lons_ext = np.linspace(x_end, l_lon, n_steps)[1:]
                lats_ext = np.linspace(y_end, l_lat, n_steps)[1:]
                if len(lons_ext) == 0:
                    continue
                ext_pts = np.column_stack([lons_ext, lats_ext])
                n_new = len(ext_pts)
                pad_kind = np.full(n_new, s["kind"][end_idx])
                pad_nx = np.full(n_new, s["nx"][end_idx])
                pad_ny = np.full(n_new, s["ny"][end_idx])
                if end_idx == 0:
                    s["xy"] = np.vstack([ext_pts[::-1], s["xy"]])
                    s["kind"] = np.concatenate([pad_kind, s["kind"]])
                    s["nx"] = np.concatenate([pad_nx, s["nx"]])
                    s["ny"] = np.concatenate([pad_ny, s["ny"]])
                else:
                    s["xy"] = np.vstack([s["xy"], ext_pts])
                    s["kind"] = np.concatenate([s["kind"], pad_kind])
                    s["nx"] = np.concatenate([s["nx"], pad_nx])
                    s["ny"] = np.concatenate([s["ny"], pad_ny])
                s["km"] += dist_km

    return segs, stats


def render_transparent_fronts(segs, hl_centers, out_path, bbox, px):
    from matplotlib.collections import LineCollection
    west, south, east, north = bbox
    sat_w, sat_h = px
    dpi = 100
    fig = plt.figure(figsize=(sat_w / dpi, sat_h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(west, east); ax.set_ylim(south, north); ax.axis("off")
    pxl = sat_w / (east - west); pyl = sat_h / (north - south)
    try:
        from matplotlib.markers import MarkerStyle
        from matplotlib.transforms import Affine2D
        from matplotlib.path import Path as MPath
        can_sym = True
    except Exception:
        can_sym = False
    drawn = 0
    for s in segs:
        xy, kind = s["xy"], s["kind"]
        if not (xy[:, 0].max() > west and xy[:, 0].min() < east and xy[:, 1].max() > south and xy[:, 1].min() < north):
            continue
        drawn += 1
        pts = xy.reshape(-1, 1, 2)
        pieces = np.concatenate([pts[:-1], pts[1:]], axis=1)
        dpx = np.hypot(np.diff(xy[:, 0]) * pxl, np.diff(xy[:, 1]) * pyl)
        cum = np.concatenate([[0], np.cumsum(dpx)])
        # стационарный фронт — как на синоптических картах: чередование синего и красного
        cols = [(FRONT_COLORS["cold"] if int(cum[i] // STAT_DASH_PX) % 2 == 0 else FRONT_COLORS["warm"])
                if k == "stat" else FRONT_COLORS[k] for i, k in enumerate(kind[:-1])]
        ax.add_collection(LineCollection(pieces, colors="black", linewidths=5.0, alpha=0.65, capstyle="round", zorder=4))
        ax.add_collection(LineCollection(pieces, colors=cols, linewidths=2.6, capstyle="round", zorder=5))
        if not can_sym:
            continue
        # значки каждые ~55 px: треугольник (холодный) / полукруг (тёплый) в сторону движения
        for m_, d in enumerate(np.arange(30.0, cum[-1], 55.0)):
            i = int(np.searchsorted(cum, d))
            i = min(i, len(xy) - 1)
            k = kind[i]
            if k == "stat":   # чередуем: треугольник холодного с одной стороны, полукруг тёплого с другой
                k = "cold" if m_ % 2 == 0 else "warm"
            sgn = 1.0 if k == "cold" else -1.0
            mx_, my_ = sgn * s["nx"][i], sgn * s["ny"][i]
            ang = math.degrees(math.atan2(my_ * pyl, mx_ * pxl))
            x, y = xy[i]
            if not (west + 0.05 < x < east - 0.05 and south + 0.05 < y < north - 0.05):
                continue
            base = "^" if k == "cold" else MPath.arc(0, 180)
            try:
                ms = MarkerStyle(base, transform=Affine2D().rotate_deg(ang - 90))
            except Exception:
                continue
            ax.plot([x + mx_ * 7 / pxl], [y + my_ * 7 / pyl], linestyle="none", marker=ms,
                    markersize=12, markerfacecolor=FRONT_COLORS[k], markeredgecolor="black",
                    markeredgewidth=0.6, zorder=6)
    fig.savefig(out_path, dpi=dpi, transparent=True)
    plt.close(fig)
    return drawn


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
    if FORCE_REGEN and manifest["snapshots"] and manifest["snapshots"][-1]["valid_time"] == valid_iso:
        stale = manifest["snapshots"].pop()
        for fn in stale["files"].values():
            p = os.path.join(out_dir, fn)
            if os.path.exists(p):
                os.remove(p)
        log(f"[{tier_key}] FORCE: пересобираю снимок {valid_iso}, история остальных сохранена")
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
    # по статистике прогонов EUMETSAT ни разу не публикует кадр на :00 и почти никогда на :55 —
    # кадр на :50 (-10 мин) есть практически всегда, поэтому пробуем его первым и экономим запросы
    for back_min in (10, 15, 5, 20, 25, 0, 30):
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
    render_transparent_isobars(fields["pmsl"], fields.get("hsurf"), lats, lons, isobars_path, bbox, px,
                               centers=fields.get("_centers"))
    render_transparent_pfront(p_front, p_lats, p_lons, pfront_path, bbox, px)
    fronts_name = None
    if fields.get("_fronts") is not None:
        try:
            fronts_name = f"{ts_label}_fronts.png"
            n_fr = render_transparent_fronts(fields["_fronts"], fields.get("_centers"),
                                             os.path.join(out_dir, fronts_name), bbox, px)
            log(f"[{tier_key}] фронты: {n_fr} линий в кадре")
        except Exception as e:
            log(f"[{tier_key}] фронты не отрисованы: {e}")
            fronts_name = None

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
    if fronts_name:
        snapshot["files"]["fronts"] = fronts_name
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
            needs_update[tier_key] = FORCE_REGEN or (last_valid != valid_dt.isoformat())

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
            "t850": ("t", "pressure-level", 850, "T", lead),
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

        testcase_path = os.environ.get("ICON_FRONT_SAVE_TESTCASE")
        if testcase_path:
            try:
                save_testcase(testcase_path, fields, lats, lons, run_dt, lead)
                log(f"тестовый снимок сохранён: {testcase_path} "
                    f"(дальше можно гонять scripts/icon_front_replay.py офлайн, без скачивания)")
            except Exception as e:
                log(f"не удалось сохранить тестовый снимок: {e}")

        try:
            fields["_centers"] = find_pressure_centers(fields["pmsl"], fields.get("hsurf"), lats, lons, debug_log=log)
            log(f"L/H: найдено {len(fields['_centers'])} центров в области")
        except Exception as e:
            log(f"L/H не посчитаны: {e}"); fields["_centers"] = None
        fields["_fronts"] = None
        if all(fields.get(k) is not None for k in ("t850", "relhum850", "u850", "v850")):
            try:
                fields["_fronts"], fst = compute_fronts(fields, lats, lons, centers=fields.get("_centers"))
                log(f"фронты: сегментов {fst['n_segments']}, суммарно {fst['km_total']:.0f} км; "
                    f"|∇θe850| К/100км p50={fst['grad100_p50']:.2f} p90={fst['grad100_p90']:.2f} max={fst['grad100_max']:.2f}; "
                    f"порог(адапт.) {fst['threshold_used']:.2f} (перцентиль {FRONT_GRAD_PERCENTILE}, "
                    f"p99={fst['grad100_p99']:.2f}), валидных точек {fst['valid_frac']*100:.1f}%")
            except Exception as e:
                log(f"фронты не посчитаны: {e}"); log(traceback.format_exc())
        else:
            log("нет T850/RH/U/V — фронты пропущены")

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
