"""
eumetsat_cloud_forecast.py — мини-прогноз облачности для Одессы: движется ли
облачность/просвет к городу, с какой скоростью, когда дойдёт (или пройдёт
мимо на каком расстоянии).

МЕТОД (обновлено после обратной связи "2 кадра / 30 мин — слишком грубо"):
берём N_FRAMES кадров msg_fes:clm (Cloud Mask) с шагом PAST_STEP_MINUTES
(сейчас, -15, -30, -45 мин), классифицируем пиксели по 3 цветам легенды.
Между КАЖДОЙ парой соседних кадров считаем сдвиг ВСЕГО облачного поля через
FFT phase correlation (кросс-корреляция всей картинки, устойчивая к шуму
одного пикселя — та же техника, что теперь в nearby_precip.py для радара),
скорости по всем парам усредняем. Если в каком-то кадре поле однородное
(сплошная облачность/сплошное ясно — корреляция бессмысленна) — эта пара
пропускается.

Позицию ближайшей "противоположной" точки (просвет, если сейчас облачно;
облако, если сейчас ясно) берём с САМОГО СВЕЖЕГО кадра (это не изменилось —
там и раньше было точно), а вот скорость теперь усреднённая и устойчивая, а
не посчитанная по одной точке между двумя кадрами.

ВАЖНО — по-прежнему ограничения метода:
  - Линейная экстраполяция усреднённой скорости — всё ещё линейная модель,
    не учитывает вращение/деформацию/усиление конвекции. Годится на ~1 час.
  - Разрешение Cloud Mask ~8-10км/пиксель — мельче не увидеть.
  - CTH/li_afa сюда не входят, только Cloud Mask.

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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast_debug.json")

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
LAYER = "msg_fes:clm"

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
PAST_STEP_MINUTES = 15   # шаг реальных данных EUMETSAT для этого слоя
AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02  # доля пикселей "меньшего" класса, иначе поле однородное

TIMEOUT = 25

CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}
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


def _fetch_tile(time_iso, retries=2, delay=4):
    import time as _time

    min_lon = CENTER_LON - HALF_WINDOW_DEG
    max_lon = CENTER_LON + HALF_WINDOW_DEG
    min_lat = CENTER_LAT - HALF_WINDOW_DEG
    max_lat = CENTER_LAT + HALF_WINDOW_DEG
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": LAYER,
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
    """arr: (H,W,3) uint8 -> boolean mask где True = облако."""
    h, w, _ = arr.shape
    pixels = arr.reshape(-1, 3).astype(np.float32)
    anchors = np.array(list(CLM_ANCHORS.values()), dtype=np.float32)
    keys = list(CLM_ANCHORS.keys())
    dists = np.sum((pixels[:, None, :] - anchors[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    is_cloud = (np.array(keys)[nearest_idx] == "cloud").reshape(h, w)
    return is_cloud


def _pixel_to_km_offset(row, col):
    frac_x = col / (TILE_SIZE - 1)
    frac_y = row / (TILE_SIZE - 1)
    lon = CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


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
    """Сдвиг (dy_px, dx_px) поля от prev к curr через FFT phase correlation.
    Окно Ханнинга перед FFT — защита от вырожденных случаев (поле однородное
    вдоль одной оси, например почти прямая линия фронта через весь тайл)."""
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
    """masks: список bool-массивов (от старых к новым), одинаковый шаг dt_minutes.
    Возвращает (vx_kmh, vy_kmh, n_pairs) или (None, None, 0)."""
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


def main():
    debug = {}
    times_iso = []
    now = datetime.now(timezone.utc)
    for i in range(N_FRAMES - 1, -1, -1):
        if i == 0:
            times_iso.append(None)  # самый свежий кадр — без time (server default)
        else:
            t = now - timedelta(minutes=PAST_STEP_MINUTES * i)
            times_iso.append(t.strftime("%Y-%m-%dT%H:%M:00.000Z"))

    arrs = []
    for t_iso in times_iso:
        try:
            arr = _fetch_tile(t_iso)
            arrs.append(arr)
        except Exception as e:
            _write_debug({"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_cloud_forecast.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(arrs)
    debug["times_requested"] = times_iso

    is_cloud_frames = [_classify_cloud_mask(a) for a in arrs]
    is_cloud_now = is_cloud_frames[-1]

    center_idx = int((TILE_SIZE - 1) / 2)
    currently_cloudy = bool(is_cloud_now[center_idx, center_idx])
    want_cloud_target = not currently_cloudy
    target_type = "cloud_mass" if want_cloud_target else "clearing"

    p_now = _nearest_of_type(is_cloud_now, want_cloud_target)
    vx, vy, n_pairs = _estimate_motion(is_cloud_frames, PAST_STEP_MINUTES)

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

            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "verdict": verdict,
                "frame_pairs_used": n_pairs,
            }

    out["method_note"] = (
        f"Скорость усреднена по {N_FRAMES} кадрам Cloud Mask (шаг {PAST_STEP_MINUTES} мин, "
        "phase correlation всего поля, не трекинг одной точки). Линейная экстраполяция, "
        "годится на ~1 час вперёд."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _write_debug({"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_cloud_forecast.py: {out.get('verdict')}")


if __name__ == "__main__":
    main()
