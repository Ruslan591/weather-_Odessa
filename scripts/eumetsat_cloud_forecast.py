"""
eumetsat_cloud_forecast.py — мини-прогноз облачности для Одессы:
  1) движение области облачности/просвета (приближается/пройдёт мимо/ETA)
  2) тренд ПЛОТНОСТИ (уплотняется/рассеивается) — доля облачных пикселей
     в локальной области вокруг города за последние кадры
  3) тренд ВЫСОТЫ (растут/опускаются вершины) — по Cloud Top Height,
     усреднённой ТОЛЬКО по облачным пикселям локальной области
  4) тренд ФОРМЫ (вытягивается/остаётся компактной) — аспект-рейшо
     bounding box крупнейшего облачного пятна в локальной области

МЕТОД ДВИЖЕНИЯ: N_FRAMES кадров msg_fes:clm (Cloud Mask) с шагом
PAST_STEP_MINUTES, классификация по 3 цветам легенды, сдвиг поля между
каждой парой кадров через FFT phase correlation (окно Ханнинга — защита от
вырожденных случаев вроде почти прямой линии фронта через весь тайл),
скорости усреднены по всем парам. Позиция ближайшей "противоположной" точки
(просвет, если сейчас облачно; облако, если ясно) берётся с самого свежего
кадра.

МЕТОД ПЛОТНОСТИ/ВЫСОТЫ/ФОРМЫ: сравниваем ПЕРВЫЙ и ПОСЛЕДНИЙ из N_FRAMES
кадров в локальной области (круг радиуса LOCAL_RADIUS_KM вокруг Одессы):
  - плотность = доля облачных пикселей в круге
  - высота = средний "ординальный индекс" по цветовой шкале CTH (НЕ метры —
    официальной таблицы цвет→высота у нас, в отличие от RainViewer, нет;
    анкеры цветов подобраны по виду легенды по возрастанию, только для
    ОТНОСИТЕЛЬНОГО тренда роста/понижения, не для абсолютных чисел),
    усреднённый ТОЛЬКО по пикселям, которые Cloud Mask в тот же момент
    считает облачными (иначе "нет данных/прозрачно" перепутается с "низкие
    облака", у обоих чёрный/тёмный цвет)
  - форма = aspect ratio (макс.сторона/мин.сторона bounding box) крупнейшей
    связной облачной области в круге (scipy.ndimage.label)

ВАЖНО — ограничения:
  - Линейная экстраполяция скорости, разрешение Cloud Mask/CTH ~8-10км/px.
  - Тренды плотности/высоты/формы — сравнение первого и последнего кадра
    (45 минут), не полноценная регрессия. Пороги для "существенно
    изменилось" подобраны эмпирически, не откалиброваны по историческим
    данным.
  - Высота — ординальный индекс по приближённым анкерам цвета, не метры.

Пишет data/eumetsat_cloud_forecast.json.
"""

import io
import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast_debug.json")

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
LAYER_CLM = "msg_fes:clm"
LAYER_CTH = "msg_fes:cth"

CENTER_LAT = 46.4406
CENTER_LON = 30.7703
CENTER_LABEL = "Одесса (СИНОП 33837)"

HALF_WINDOW_DEG = 2.5   # ~190км при этой широте
TILE_SIZE = 400
KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(CENTER_LAT))  # ~76.8 км/град
KM_PER_PX_X = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LON) / TILE_SIZE
KM_PER_PX_Y = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LAT) / TILE_SIZE

N_FRAMES = 4
PAST_STEP_MINUTES = 15
AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02

LOCAL_RADIUS_KM = 50.0           # область вокруг города для плотности/высоты/формы
DENSITY_CHANGE_THRESHOLD = 0.10  # 10 п.п. — считаем существенным изменением
HEIGHT_CHANGE_THRESHOLD = 0.6    # изменение среднего ординального индекса
ASPECT_CHANGE_THRESHOLD = 0.5    # изменение aspect ratio bounding box

TIMEOUT = 25

CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}

# Ординальные анкеры для CTH-рампы (приближённо, по виду легенды: чёрный
# внизу шкалы -> ... -> белый вверху). НЕ официальная таблица, только для
# относительного тренда роста/понижения индекса.
CTH_ORDINAL_ANCHORS = [
    (0, (0, 0, 0)),
    (1, (75, 0, 130)),
    (2, (0, 0, 255)),
    (3, (0, 255, 255)),
    (4, (0, 200, 0)),
    (5, (255, 255, 0)),
    (6, (255, 0, 0)),
    (7, (255, 255, 255)),
]
_CTH_IDX = np.array([a[0] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)
_CTH_RGB = np.array([a[1] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def _write_debug(payload):
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _bearing_compass(dx_km, dy_km):
    bearing = (math.degrees(math.atan2(dx_km, dy_km)) + 360) % 360
    idx = int(((bearing + 22.5) % 360) // 45)
    return bearing, COMPASS[idx]


def _compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def _fetch_tile(layer_name, time_iso, retries=2, delay=4):
    import time as _time

    min_lon = CENTER_LON - HALF_WINDOW_DEG
    max_lon = CENTER_LON + HALF_WINDOW_DEG
    min_lat = CENTER_LAT - HALF_WINDOW_DEG
    max_lat = CENTER_LAT + HALF_WINDOW_DEG
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer_name,
        "styles": "",
        "crs": "CRS:84",
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
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
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            return np.array(img)
        except Exception as e:
            last_err = e
            if attempt < retries:
                _time.sleep(delay)
    raise last_err


def _classify_cloud_mask(arr):
    h, w, _ = arr.shape
    pixels = arr.reshape(-1, 3).astype(np.float32)
    anchors = np.array(list(CLM_ANCHORS.values()), dtype=np.float32)
    keys = list(CLM_ANCHORS.keys())
    dists = np.sum((pixels[:, None, :] - anchors[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    is_cloud = (np.array(keys)[nearest_idx] == "cloud").reshape(h, w)
    return is_cloud


def _cth_ordinal_index(arr):
    """arr: (H,W,3) -> (H,W) float, ординальный индекс 0..7 (не метры)."""
    h, w, _ = arr.shape
    pixels = arr.reshape(-1, 3).astype(np.float32)
    dists = np.sum((pixels[:, None, :] - _CTH_RGB[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    return _CTH_IDX[nearest_idx].reshape(h, w)


def _pixel_to_km_offset(row, col):
    frac_x = col / (TILE_SIZE - 1)
    frac_y = row / (TILE_SIZE - 1)
    lon = CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


def _local_area_mask():
    """Булев (H,W) — True внутри LOCAL_RADIUS_KM от центра тайла."""
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def _nearest_of_type(is_cloud_mask, want_cloud):
    target = is_cloud_mask if want_cloud else ~is_cloud_mask
    ys, xs = np.where(target)
    if len(ys) == 0:
        return None
    center_row = center_col = (TILE_SIZE - 1) / 2
    dist_px = np.sqrt((ys - center_row) ** 2 + (xs - center_col) ** 2)
    best_i = np.argmin(dist_px)
    return _pixel_to_km_offset(int(ys[best_i]), int(xs[best_i]))


def _phase_shift_px(mask_prev, mask_curr):
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


def _is_uniform(mask):
    frac_cloud = mask.mean()
    return min(frac_cloud, 1 - frac_cloud) < MIN_FRACTION_FOR_CORR


def _estimate_motion(masks, dt_minutes):
    vx_list, vy_list = [], []
    dt_h = dt_minutes / 60.0
    for i in range(len(masks) - 1):
        m_prev, m_curr = masks[i], masks[i + 1]
        if _is_uniform(m_prev) or _is_uniform(m_curr):
            continue
        dy_px, dx_px = _phase_shift_px(m_prev, m_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def _largest_component_aspect(mask):
    """Aspect ratio (>=1) bounding box крупнейшей связной области True в mask, или None."""
    labeled, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    biggest_label = int(np.argmax(sizes)) + 1
    ys, xs = np.where(labeled == biggest_label)
    h = ys.max() - ys.min() + 1
    w = xs.max() - xs.min() + 1
    return max(h, w) / max(1, min(h, w))


def _density_height_shape_trend(is_cloud_frames, cth_index_frames, local_mask):
    first_cloud, last_cloud = is_cloud_frames[0], is_cloud_frames[-1]
    local_first = first_cloud & local_mask
    local_last = last_cloud & local_mask

    frac_first = local_first.sum() / max(1, local_mask.sum())
    frac_last = local_last.sum() / max(1, local_mask.sum())
    density_delta = frac_last - frac_first

    if density_delta > DENSITY_CHANGE_THRESHOLD:
        density_verdict = "уплотняется"
    elif density_delta < -DENSITY_CHANGE_THRESHOLD:
        density_verdict = "рассеивается"
    else:
        density_verdict = "без существенных изменений"

    # высота: средний ординальный индекс ТОЛЬКО по облачным пикселям локальной области
    height_verdict = None
    height_delta = None
    if local_first.sum() > 5 and local_last.sum() > 5:
        h_first = float(cth_index_frames[0][local_first].mean())
        h_last = float(cth_index_frames[-1][local_last].mean())
        height_delta = h_last - h_first
        if height_delta > HEIGHT_CHANGE_THRESHOLD:
            height_verdict = "вершины растут (возможно усиление)"
        elif height_delta < -HEIGHT_CHANGE_THRESHOLD:
            height_verdict = "вершины опускаются (возможно ослабление)"
        else:
            height_verdict = "без существенных изменений"

    # форма: aspect ratio крупнейшего пятна в локальной области
    shape_verdict = None
    aspect_delta = None
    aspect_first = _largest_component_aspect(local_first)
    aspect_last = _largest_component_aspect(local_last)
    if aspect_first is not None and aspect_last is not None:
        aspect_delta = aspect_last - aspect_first
        if aspect_delta > ASPECT_CHANGE_THRESHOLD:
            shape_verdict = "вытягивается (возможно формирование линии/фронта)"
        elif aspect_delta < -ASPECT_CHANGE_THRESHOLD:
            shape_verdict = "становится компактнее"
        else:
            shape_verdict = "форма существенно не меняется"

    return {
        "density_fraction_now": round(float(frac_last), 2),
        "density_delta": round(float(density_delta), 2),
        "density_verdict": density_verdict,
        "height_ordinal_delta": round(height_delta, 2) if height_delta is not None else None,
        "height_verdict": height_verdict,
        "shape_aspect_ratio_now": round(aspect_last, 2) if aspect_last is not None else None,
        "shape_aspect_delta": round(aspect_delta, 2) if aspect_delta is not None else None,
        "shape_verdict": shape_verdict,
    }


def main():
    debug = {}
    now = datetime.now(timezone.utc)
    times_iso = []
    for i in range(N_FRAMES - 1, -1, -1):
        if i == 0:
            times_iso.append(None)
        else:
            t = now - timedelta(minutes=PAST_STEP_MINUTES * i)
            times_iso.append(t.strftime("%Y-%m-%dT%H:%M:00.000Z"))

    clm_arrs, cth_arrs = [], []
    for t_iso in times_iso:
        try:
            clm_arrs.append(_fetch_tile(LAYER_CLM, t_iso))
            cth_arrs.append(_fetch_tile(LAYER_CTH, t_iso))
        except Exception as e:
            _write_debug({"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_cloud_forecast.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(clm_arrs)
    debug["times_requested"] = times_iso

    is_cloud_frames = [_classify_cloud_mask(a) for a in clm_arrs]
    cth_index_frames = [_cth_ordinal_index(a) for a in cth_arrs]
    is_cloud_now = is_cloud_frames[-1]

    center_idx = int((TILE_SIZE - 1) / 2)
    currently_cloudy = bool(is_cloud_now[center_idx, center_idx])
    want_cloud_target = not currently_cloudy
    target_type = "cloud_mass" if want_cloud_target else "clearing"

    p_now = _nearest_of_type(is_cloud_now, want_cloud_target)
    vx, vy, n_pairs = _estimate_motion(is_cloud_frames, PAST_STEP_MINUTES)

    local_mask = _local_area_mask()
    trend = _density_height_shape_trend(is_cloud_frames, cth_index_frames, local_mask)

    if p_now is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": "cloud" if currently_cloudy else "clear",
            "target_type": target_type,
            "verdict": "однородно в радиусе ~{}км, {} не найдено".format(
                round(HALF_WINDOW_DEG * KM_PER_DEG_LON),
                "просветов" if want_cloud_target else "облаков",
            ),
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = _bearing_compass(*p_now)

        if vx is None:
            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "verdict": "скорость посчитать не удалось (поле слишком однородно во всех кадрах)",
            }
        else:
            speed_kmh = math.hypot(vx, vy)
            dot_pv = p_now[0] * vx + p_now[1] * vy
            dot_vv = vx * vx + vy * vy
            t_cpa = max(0.0, -dot_pv / dot_vv) if dot_vv > 1e-6 else 0.0
            cpa_x = p_now[0] + vx * t_cpa
            cpa_y = p_now[1] + vy * t_cpa
            cpa_km = math.hypot(cpa_x, cpa_y)
            eta_min = round(t_cpa * 60, 0)

            if speed_kmh < STATIONARY_SPEED_KMH:
                verdict = "почти стоит на месте"
            elif cpa_km <= AFFECT_THRESHOLD_KM:
                verdict = "приближается" if eta_min > 5 else "уже у города"
            elif t_cpa <= 1e-6:
                verdict = "удаляется"
            else:
                verdict = "пройдёт мимо, город, скорее всего, не заденет"

            bearing_v = (math.degrees(math.atan2(vx, vy)) + 360) % 360

            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "direction_compass": _compass(bearing_v),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "verdict": verdict,
                "frame_pairs_used": n_pairs,
            }

    out["trend"] = trend
    out["method_note"] = (
        f"Скорость усреднена по {N_FRAMES} кадрам Cloud Mask (шаг {PAST_STEP_MINUTES} мин, "
        "phase correlation всего поля). Тренды плотности/высоты/формы — сравнение первого и "
        f"последнего кадра в радиусе {round(LOCAL_RADIUS_KM)}км. Высота — ординальный индекс "
        "по цвету (не метры, официальной таблицы нет). Линейная экстраполяция, годится на ~1 час."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _write_debug({"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_cloud_forecast.py: {out.get('verdict')}, trend={trend}")


if __name__ == "__main__":
    main()
