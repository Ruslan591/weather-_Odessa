"""
field_motion_common.py — общая геометрия/детекция края/движения для полей
EUMETSAT (Cloud Mask, осадки h60b, молнии li_afa). Вынесено из
eumetsat_cloud_forecast.py, чтобы не дублировать один и тот же алгоритм
в трёх местах (облачность/осадки/молния).

ВАЖНО про "presence"-поля (осадки, молния) в отличие от Cloud Mask:
для msg_fes:h60b и mtg_fd:li_afa прозрачный пиксель (alpha=0) в стиле
EUMETView ОЗНАЧАЕТ "значение 0/нет сигнала", а не "нет данных" — это не
то же самое, что no-data в Cloud Mask (там нужно было явно отличать
"нет данных" от "ясно"). Поэтому здесь valid=True почти everywhere, а
presence = alpha>0 и есть сама классификация.
"""

import io
import math
import os
import json
import time as _time

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
CENTER_LAT = 46.4406
CENTER_LON = 30.7703

HALF_WINDOW_DEG = 2.5
TILE_SIZE = 400
KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(CENTER_LAT))
KM_PER_PX_X = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LON) / TILE_SIZE
KM_PER_PX_Y = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LAT) / TILE_SIZE

AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02
MIN_SIGNIFICANT_BLOB_PX = 40
SIGNIFICANT_AREA_REF_KM2 = 1200.0

LOCAL_RADIUS_KM = 50.0

TIMEOUT = 25
COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def write_debug(path, payload):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch_tile(layer_name, time_iso=None, retries=2, delay=4):
    min_lon = CENTER_LON - HALF_WINDOW_DEG
    max_lon = CENTER_LON + HALF_WINDOW_DEG
    min_lat = CENTER_LAT - HALF_WINDOW_DEG
    max_lat = CENTER_LAT + HALF_WINDOW_DEG
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"  # CRS:84 = lon,lat

    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer_name,
        "styles": "",
        "crs": "CRS:84",
        "bbox": bbox,
        "width": TILE_SIZE,
        "height": TILE_SIZE,
        "format": "image/png",
        "transparent": "true",
    }
    if time_iso:
        params["time"] = time_iso

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(WMS_BASE, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return np.array(img)
        except Exception as e:
            last_err = e
            if attempt < retries:
                _time.sleep(delay)
    raise last_err


def classify_presence_by_alpha(arr):
    """presence = непрозрачный пиксель (значение > 0 по легенде продукта).
    valid = True почти везде — для этих продуктов alpha сам кодирует
    "0/нет сигнала", это не индикатор отсутствия данных."""
    presence = arr[:, :, 3] > 0
    valid = np.ones_like(presence, dtype=bool)
    return presence, valid


def pixel_to_km_offset(row, col):
    frac_x = col / (TILE_SIZE - 1)
    frac_y = row / (TILE_SIZE - 1)
    lon = CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


def local_area_mask():
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def bearing_compass(dx_km, dy_km):
    bearing = (math.degrees(math.atan2(dx_km, dy_km)) + 360) % 360
    idx = int(((bearing + 22.5) % 360) // 45)
    return bearing, COMPASS[idx]


def compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def nearest_of_type(mask, valid, want_true, min_blob_px=MIN_SIGNIFICANT_BLOB_PX):
    """Ближайшая к центру точка связной области >= min_blob_px, где
    mask==want_true (и valid==True). Возвращает (dx_km, dy_km, area_km2)
    или None, если значимых областей нет."""
    raw_target = mask if want_true else (~mask & valid)
    labeled, n = ndimage.label(raw_target)
    if n == 0:
        return None
    sizes = ndimage.sum(raw_target, labeled, range(1, n + 1))
    keep_labels = np.where(sizes >= min_blob_px)[0] + 1
    if len(keep_labels) == 0:
        return None
    filtered = np.isin(labeled, keep_labels)
    ys, xs = np.where(filtered)
    center_row = center_col = (TILE_SIZE - 1) / 2
    dist_px = np.sqrt((ys - center_row) ** 2 + (xs - center_col) ** 2)
    best_i = np.argmin(dist_px)
    row, col = int(ys[best_i]), int(xs[best_i])
    blob_label = labeled[row, col]
    blob_px = float(sizes[blob_label - 1])
    blob_area_km2 = blob_px * KM_PER_PX_X * KM_PER_PX_Y
    dx_km, dy_km = pixel_to_km_offset(row, col)
    return dx_km, dy_km, blob_area_km2


def phase_shift_px(mask_prev, mask_curr):
    win = np.outer(np.hanning(mask_prev.shape[0]), np.hanning(mask_prev.shape[1]))
    a = (mask_prev.astype(np.float64) - mask_prev.mean()) * win
    b = (mask_curr.astype(np.float64) - mask_curr.mean()) * win
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    r = fb * np.conj(fa)
    denom = np.abs(r)
    denom[denom < 1e-10] = 1e-10
    r = r / denom
    corr = np.fft.ifft2(r).real
    corr = np.fft.fftshift(corr)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    center = np.array(corr.shape) // 2
    dy_px, dx_px = (np.array(peak) - center).tolist()
    return dy_px, dx_px


def is_uniform(mask):
    frac = mask.mean()
    return min(frac, 1 - frac) < MIN_FRACTION_FOR_CORR


def estimate_motion(masks, dt_minutes):
    vx_list, vy_list = [], []
    dt_h = dt_minutes / 60.0
    for i in range(len(masks) - 1):
        m_prev, m_curr = masks[i], masks[i + 1]
        if is_uniform(m_prev) or is_uniform(m_curr):
            continue
        dy_px, dx_px = phase_shift_px(m_prev, m_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def change_probability(effective_distance_km, blob_area_km2, confidence):
    """Эвристическая (не физическая) оценка вероятности, что значимое поле
    достигнет точки наблюдения. См. подробности в eumetsat_cloud_forecast.py."""
    proximity = max(0.0, 1 - effective_distance_km / (AFFECT_THRESHOLD_KM * 4))
    size = min(1.0, blob_area_km2 / SIGNIFICANT_AREA_REF_KM2)
    score = 0.5 * proximity + 0.3 * size + 0.2 * confidence
    return int(round(max(5, min(95, 5 + 90 * score))))
