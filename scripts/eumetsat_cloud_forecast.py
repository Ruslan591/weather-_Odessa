"""
eumetsat_cloud_forecast.py — мини-прогноз облачности для Одессы: движется ли
облачность/просвет к городу, с какой скоростью, когда дойдёт (или пройдёт
мимо на каком расстоянии).

Метод: берём два кадра msg_fes:clm (Cloud Mask) — сейчас и 30 минут назад —
в виде GetMap-тайла (не GetFeatureInfo, чтобы получить целую область, а не
одну точку), классифицируем пиксели по 3 цветам легенды (как в
eumetsat_point.py). Если над Одессой сейчас облачно — ищем ближайший
"просвет" (ближайший ясный пиксель) в обоих кадрах; если ясно — ищем
ближайшее облачное пятно. По смещению этой ближайшей точки за 30 минут
считаем вектор скорости (км/ч) и экстраполируем линейно вперёд:
  - если экстраполированная траектория проходит близко от города (CPA —
    closest point of approach — меньше AFFECT_THRESHOLD_KM) — это ETA;
  - если CPA больше порога — считаем, что мимо, с указанием минимального
    расстояния сближения.

ВАЖНО — ограничения метода:
  - Линейная экстраполяция по ОДНОМУ 30-минутному интервалу — грубая модель.
    Не учитывает вращение, деформацию, усиление/ослабление конвекции.
    Годится как оценка на следующий ~час, дальше — ненадёжно.
  - "Ближайшая точка перехода" может быть шумной (границы Cloud Mask рваные
    по пикселям ~8-10км) — скорость и ETA стоит воспринимать как порядок
    величины, не точное время.
  - Данные CTH/li_afa сюда не входят, только сама Cloud Mask.

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

PAST_MINUTES = 30
AFFECT_THRESHOLD_KM = 15.0  # CPA меньше этого — считаем, что город заденет
STATIONARY_SPEED_KMH = 3.0  # медленнее — считаем "почти стоит на месте"

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
    """row,col (0-based, 0,0 = top-left) -> (dx_km, dy_km) относительно центра."""
    frac_x = col / (TILE_SIZE - 1)  # 0..1 слева направо
    frac_y = row / (TILE_SIZE - 1)  # 0..1 сверху вниз
    lon = CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


def _nearest_of_type(is_cloud_mask, want_cloud):
    """Ищет ближайший к центру пиксель нужного типа. Возвращает (dx_km, dy_km) или None."""
    target = is_cloud_mask if want_cloud else ~is_cloud_mask
    ys, xs = np.where(target)
    if len(ys) == 0:
        return None
    center_row = center_col = (TILE_SIZE - 1) / 2
    dist_px = np.sqrt((ys - center_row) ** 2 + (xs - center_col) ** 2)
    best_i = np.argmin(dist_px)
    return _pixel_to_km_offset(int(ys[best_i]), int(xs[best_i]))


def main():
    debug = {}
    try:
        arr_now = _fetch_tile(time_iso=None)
        debug["now_shape"] = list(arr_now.shape)
    except Exception as e:
        _write_debug({"status": "error", "stage": "fetch_now", "error": str(e)})
        print(f"  [WARN] eumetsat_cloud_forecast.py: fetch now failed: {e}")
        return

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=PAST_MINUTES)
    past_iso = past_dt.strftime("%Y-%m-%dT%H:%M:00.000Z")
    try:
        arr_past = _fetch_tile(time_iso=past_iso)
        debug["past_shape"] = list(arr_past.shape)
    except Exception as e:
        _write_debug({"status": "error", "stage": "fetch_past", "error": str(e), "past_iso": past_iso})
        print(f"  [WARN] eumetsat_cloud_forecast.py: fetch past failed: {e}")
        return

    is_cloud_now = _classify_cloud_mask(arr_now)
    is_cloud_past = _classify_cloud_mask(arr_past)

    center_idx = int((TILE_SIZE - 1) / 2)
    currently_cloudy = bool(is_cloud_now[center_idx, center_idx])
    want_cloud_target = not currently_cloudy  # ищем противоположное текущему состоянию

    p_now = _nearest_of_type(is_cloud_now, want_cloud_target)
    p_past = _nearest_of_type(is_cloud_past, want_cloud_target)

    target_type = "cloud_mass" if want_cloud_target else "clearing"

    if p_now is None:
        # весь кадр однороден (либо сплошная облачность, либо сплошное ясно) —
        # нечего отслеживать в радиусе HALF_WINDOW_DEG
        out = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": "cloud" if currently_cloudy else "clear",
            "verdict": "однородно в радиусе ~{}км, {} не найдено".format(
                round(HALF_WINDOW_DEG * KM_PER_DEG_LON),
                "просветов" if want_cloud_target else "облаков",
            ),
            "target_type": target_type,
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = _bearing_compass(*p_now)

        if p_past is None:
            # в прошлом кадре искомого типа не было вовсе рядом — не можем посчитать скорость
            out = {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "verdict": "появилось недавно, скорость движения посчитать не удалось",
            }
        else:
            # вектор скорости (км/ч) движения ближайшей точки нужного типа
            vx = (p_now[0] - p_past[0]) / (PAST_MINUTES / 60.0)
            vy = (p_now[1] - p_past[1]) / (PAST_MINUTES / 60.0)
            speed_kmh = math.hypot(vx, vy)

            # CPA: минимизируем |P_now + V*t|^2 по t >= 0
            dot_pv = p_now[0] * vx + p_now[1] * vy
            dot_vv = vx * vx + vy * vy
            if dot_vv > 1e-6:
                t_cpa = max(0.0, -dot_pv / dot_vv)
            else:
                t_cpa = 0.0
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
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "verdict": verdict,
            }

    out["method_note"] = (
        "Линейная экстраполяция по одному 30-минутному интервалу Cloud Mask (EUMETSAT). "
        "Грубая оценка на ~1 час вперёд, не учитывает деформацию/усиление системы."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _write_debug({"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_cloud_forecast.py: {out.get('verdict')}")


if __name__ == "__main__":
    main()
