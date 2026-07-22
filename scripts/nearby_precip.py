"""
nearby_precip.py — расстояние до ближайших осадков/грозы от Одессы + прогноз
движения (приближается/пройдёт мимо/ETA), на основе RainViewer радара.

Источник: RainViewer Weather Maps API (радар, реальное наблюдение, НЕ модель) —
https://api.rainviewer.com/public/weather-maps.json, бесплатно для
персонального/образовательного использования, без API-ключа. ToS RainViewer
требует атрибуцию "Weather data by RainViewer" там, где эти данные показываются
человеку — это забота фронтенда (страница с индикатором), не этого скрипта.

Тайл радара, центрированный на СИНОП 33837 (46.4406, 30.7703):
цветовая схема "Universal Blue" (color=2), БЕЗ сглаживания (options=0_0) —
это важно, сглаживание интерполирует цвета между dBZ-ступенями и портит
обратное сопоставление цвет→dBZ. zoom=6, size=512px:
  ground_width ≈ 40075016.686 / 2**zoom * cos(lat) ≈ 432 км (радиус ~216 км)
  ~0.84 км/пиксель.

ПРОГНОЗ ДВИЖЕНИЯ (по мотивам обратной связи: "2 кадра — слишком грубо"):
берём N_FRAMES последних кадров radar.past (обычно шаг 10 мин, но реальный
интервал считаем по факту из их же timestamp, не предполагаем фиксированным),
между каждой парой соседних кадров считаем сдвиг ВСЕГО поля через phase
correlation (FFT кросс-корреляция) — это устойчивая оценка сдвига всей
картинки целиком, а не шумный трекинг одной ближайшей точки между двумя
кадрами. Скорости по всем парам усредняем. Отдельно считаем для поля осадков
(mask_precip) и отдельно для поля грозового ядра (mask_thunder) — они могут
двигаться с разной скоростью/направлением (ядро часто быстрее общего фронта).
Если в каком-то кадре пикселей грозового ядра слишком мало для надёжной
корреляции — скорость грозы не считаем (null), но осадки считаем отдельно.

Даёт устойчивую скорость → экстраполируем ближайшую точку (уже найденную на
самом свежем кадре) вперёд по времени: строим CPA (closest point of approach)
и ETA, как и в eumetsat_cloud_forecast.py — то же уравнение движения.

Про Blitzortung (сознательно НЕ используется): их правила ограничивают
использование данных участниками сети (кто держит свой приёмник) или теми,
кому явно разрешили — это отдельно от и шире, чем просто запрет
коммерческого использования.

"Гроза" здесь — ПРОКСИ по отражаемости (>=45 dBZ), а НЕ детекция реального
разряда молнии.

Пишет data/nearby_precip.json + data/nearby_precip_debug.json.
"""

import io
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "nearby_precip.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "nearby_precip_debug.json")

# та же точка, что и STATION 33837 в update.py
CENTER_LAT = 46.4406
CENTER_LON = 30.7703
CENTER_LABEL = "Одесса (СИНОП 33837)"

WEATHER_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
TILE_COLOR = 2       # Universal Blue — единственная актуальная схема API
TILE_SIZE = 512
TILE_ZOOM = 6         # ground width ~432км при этой широте, radius ~216км
TILE_OPTIONS = "0_0"  # без сглаживания (smooth=0), без снега (snow=0)
TIMEOUT = 20

EARTH_R_KM = 6371.0
EARTH_CIRCUMFERENCE_M = 40075016.686

PRECIP_ALPHA_THRESHOLD = 200   # ~dBZ>=15 — граница "значимый сигнал" vs фоновый шум
THUNDER_DBZ_THRESHOLD = 45     # эмпирический порог конвективного ядра (прокси грозы)

N_FRAMES = 4              # сколько последних кадров past брать для оценки скорости
MIN_PIXELS_FOR_CORR = 20  # меньше — корреляция на почти пустом поле не считается надёжной
AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]

# Таблица цвет→dBZ схемы "Universal Blue" (color=2), только dBZ>=15
_DBZ_COLOR_HEX = {
    15: "88ddee", 16: "6cd1eb", 17: "51c5e8", 18: "36bae5", 19: "1baee2",
    20: "00a3e0", 21: "009ad5", 22: "0091ca", 23: "0088bf", 24: "007fb4",
    25: "0077aa", 26: "0070a3", 27: "00699c", 28: "006295", 29: "005b8e",
    30: "005588", 31: "005180", 32: "004e78", 33: "004a70", 34: "004768",
    35: "ffee00", 36: "ffe000", 37: "ffd200", 38: "ffc500", 39: "ffb700",
    40: "ffaa00", 41: "ff9f00", 42: "ff9500", 43: "ff8b00", 44: "ff8100",
    45: "ff4400", 46: "f23600", 47: "e62800", 48: "d91b00", 49: "cd0d00",
    50: "c10000", 51: "a80000", 52: "8f0000", 53: "760000", 54: "5d0000",
    55: "ffaaff", 56: "ff9fff", 57: "ff95ff", 58: "ff8bff", 59: "ff81ff",
    60: "ff77ff", 61: "ff6cff", 62: "ff62ff", 63: "ff58ff", 64: "ff4eff",
    65: "ffffff", 66: "ffffff", 67: "ffffff", 68: "ffffff", 69: "ffffff",
    70: "ffffff",
}
_DBZ_VALUES = np.array(sorted(_DBZ_COLOR_HEX.keys()))
_DBZ_RGB = np.array([
    [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
    for _, h in sorted(_DBZ_COLOR_HEX.items())
], dtype=np.float32)


def _write_debug(payload):
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1r, lon1r, lat2r, lon2r = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def _bearing_km(lat1, lon1, lat2, lon2):
    lat1r, lon1r, lat2r, lon2r = map(math.radians, (lat1, lon1, lat2, lon2))
    dlon = lon2r - lon1r
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def _fetch_weather_maps(retries=3, delay=5):
    import time
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(WEATHER_MAPS_URL, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay)
    raise last_err


def _fetch_tile(host, path, retries=3, delay=4):
    import time
    url = (
        f"{host}{path}/{TILE_SIZE}/{TILE_ZOOM}/{CENTER_LAT}/{CENTER_LON}/"
        f"{TILE_COLOR}/{TILE_OPTIONS}.png"
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return np.array(img), url
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay)
    raise last_err


def _meters_per_pixel():
    ground_width_m = (EARTH_CIRCUMFERENCE_M / (2 ** TILE_ZOOM)) * math.cos(math.radians(CENTER_LAT))
    return ground_width_m / TILE_SIZE


def _pixel_to_latlon(row, col, meters_per_px):
    dx_px = col - TILE_SIZE / 2.0
    dy_px = row - TILE_SIZE / 2.0  # растёт вниз по изображению = на юг
    dx_m = dx_px * meters_per_px
    dy_m = -dy_px * meters_per_px
    dlat = dy_m / 111320.0
    dlon = dx_m / (111320.0 * math.cos(math.radians(CENTER_LAT)))
    return CENTER_LAT + dlat, CENTER_LON + dlon


def _classify(arr):
    """arr: (H,W,4) uint8. Возвращает (mask_precip, dbz_est) формы (H,W)."""
    alpha = arr[:, :, 3].astype(np.int16)
    mask_precip = alpha >= PRECIP_ALPHA_THRESHOLD

    dbz_est = np.full(arr.shape[:2], -99, dtype=np.int16)
    ys, xs = np.where(mask_precip)
    if len(ys) > 0:
        rgb = arr[ys, xs, :3].astype(np.float32)
        dists = np.sum((rgb[:, None, :] - _DBZ_RGB[None, :, :]) ** 2, axis=2)
        nearest_idx = np.argmin(dists, axis=1)
        dbz_est[ys, xs] = _DBZ_VALUES[nearest_idx]
    return mask_precip, dbz_est


def _nearest_point(mask, meters_per_px):
    """Ближайший к центру пиксель, где mask=True. dict с lat/lon/dx_km/dy_km или None."""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return None
    dx_px = xs - TILE_SIZE / 2.0
    dy_px = ys - TILE_SIZE / 2.0
    dist_px = np.sqrt(dx_px ** 2 + dy_px ** 2)
    best_i = np.argmin(dist_px)
    row, col = int(ys[best_i]), int(xs[best_i])
    lat, lon = _pixel_to_latlon(row, col, meters_per_px)
    dist_km = _haversine_km(CENTER_LAT, CENTER_LON, lat, lon)
    bearing = _bearing_km(CENTER_LAT, CENTER_LON, lat, lon)
    # dx_km/dy_km в локальных плоских координатах (для CPA-экстраполяции)
    dx_km = float(dx_px[best_i]) * meters_per_px / 1000.0
    dy_km = -float(dy_px[best_i]) * meters_per_px / 1000.0
    return {
        "distance_km": round(dist_km, 1),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "bearing_deg": round(bearing, 0),
        "compass": _compass(bearing),
        "_dx_km": dx_km,
        "_dy_km": dy_km,
    }


def _phase_shift_px(mask_prev, mask_curr):
    """Сдвиг (dy_px, dx_px) поля от prev к curr через FFT phase correlation.
    Окно Ханнинга перед FFT — защита от вырожденных случаев (поле однородное
    вдоль одной оси, например узкая линия ливня через весь тайл)."""
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


def _estimate_motion(masks, times_unix, meters_per_px):
    """masks: список bool-массивов (от старых к новым), times_unix: их таймстемпы.
    Возвращает (vx_kmh, vy_kmh, n_pairs_used) или (None, None, 0)."""
    vx_list, vy_list = [], []
    for i in range(len(masks) - 1):
        m_prev, m_curr = masks[i], masks[i + 1]
        if m_prev.sum() < MIN_PIXELS_FOR_CORR or m_curr.sum() < MIN_PIXELS_FOR_CORR:
            continue
        dt_h = (times_unix[i + 1] - times_unix[i]) / 3600.0
        if dt_h <= 0:
            continue
        dy_px, dx_px = _phase_shift_px(m_prev, m_curr)
        dx_km = dx_px * meters_per_px / 1000.0
        dy_km = -dy_px * meters_per_px / 1000.0
        vx_list.append(dx_km / dt_h)
        vy_list.append(dy_km / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def _motion_forecast(point, vx_kmh, vy_kmh):
    """CPA/ETA для точки point (с _dx_km/_dy_km) при скорости (vx,vy) км/ч."""
    if point is None or vx_kmh is None:
        return None
    px, py = point["_dx_km"], point["_dy_km"]
    speed_kmh = math.hypot(vx_kmh, vy_kmh)

    dot_pv = px * vx_kmh + py * vy_kmh
    dot_vv = vx_kmh * vx_kmh + vy_kmh * vy_kmh
    t_cpa = max(0.0, -dot_pv / dot_vv) if dot_vv > 1e-6 else 0.0
    cpa_x = px + vx_kmh * t_cpa
    cpa_y = py + vy_kmh * t_cpa
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

    bearing_v = (math.degrees(math.atan2(vx_kmh, vy_kmh)) + 360) % 360
    return {
        "speed_kmh": round(speed_kmh, 1),
        "direction_compass": _compass(bearing_v),
        "cpa_km": round(cpa_km, 1),
        "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
        "verdict": verdict,
    }


def main():
    try:
        wm = _fetch_weather_maps()
    except Exception as e:
        _write_debug({"status": "error", "note": f"weather-maps.json fetch failed: {e}"})
        print(f"  [WARN] nearby_precip.py: weather-maps.json fetch failed: {e}")
        return

    past = (wm.get("radar") or {}).get("past") or []
    if not past:
        _write_debug({"status": "error", "note": "no radar.past frames"})
        print("  [WARN] nearby_precip.py: нет кадров radar.past")
        return

    frames_to_fetch = past[-N_FRAMES:] if len(past) >= N_FRAMES else past
    host = wm.get("host", "")

    arrs, times_unix, tile_urls = [], [], []
    for fr in frames_to_fetch:
        try:
            arr, url = _fetch_tile(host, fr["path"])
            arrs.append(arr)
            times_unix.append(fr["time"])
            tile_urls.append(url)
        except Exception as e:
            _write_debug({"status": "error", "note": f"tile fetch failed for frame {fr.get('time')}: {e}"})
            print(f"  [WARN] nearby_precip.py: tile fetch failed: {e}")
            return

    meters_per_px = _meters_per_pixel()

    masks_precip, masks_thunder, dbz_est_last = [], [], None
    for arr in arrs:
        mp, dbz = _classify(arr)
        masks_precip.append(mp)
        masks_thunder.append(mp & (dbz >= THUNDER_DBZ_THRESHOLD))
        dbz_est_last = dbz  # последний (самый свежий) кадр пригодится ниже

    mask_precip_now = masks_precip[-1]
    mask_thunder_now = masks_thunder[-1]

    nearest_precip = _nearest_point(mask_precip_now, meters_per_px)
    nearest_thunder = _nearest_point(mask_thunder_now, meters_per_px)

    vx_p, vy_p, n_pairs_p = _estimate_motion(masks_precip, times_unix, meters_per_px)
    vx_t, vy_t, n_pairs_t = _estimate_motion(masks_thunder, times_unix, meters_per_px)

    precip_motion = _motion_forecast(nearest_precip, vx_p, vy_p)
    thunder_motion = _motion_forecast(nearest_thunder, vx_t, vy_t)
    if precip_motion is not None:
        precip_motion["frame_pairs_used"] = n_pairs_p
    if thunder_motion is not None:
        thunder_motion["frame_pairs_used"] = n_pairs_t

    # служебные поля _dx_km/_dy_km наружу не отдаём
    for p in (nearest_precip, nearest_thunder):
        if p:
            p.pop("_dx_km", None)
            p.pop("_dy_km", None)

    radar_time = times_unix[-1]
    radar_dt = datetime.fromtimestamp(radar_time, tz=timezone.utc) if radar_time else None
    radar_age_min = None
    if radar_dt:
        radar_age_min = round((datetime.now(timezone.utc) - radar_dt).total_seconds() / 60, 1)

    out = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "center": {"lat": CENTER_LAT, "lon": CENTER_LON, "label": CENTER_LABEL},
        "nearest_precip": nearest_precip,
        "nearest_thunderstorm": nearest_thunder,
        "precip_motion": precip_motion,
        "thunderstorm_motion": thunder_motion,
        "radar_time": radar_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if radar_dt else None,
        "radar_age_min": radar_age_min,
        "coverage_radius_km": round(meters_per_px * TILE_SIZE / 2 / 1000, 0),
        "resolution_km_per_px": round(meters_per_px / 1000, 2),
        "frames_used": len(arrs),
        "source": "RainViewer радар (реальное наблюдение); гроза — прокси по отражаемости "
                  f">={THUNDER_DBZ_THRESHOLD}dBZ, не детекция молнии; скорость движения — "
                  "phase correlation по нескольким кадрам, усреднено",
        "attribution": "Weather data by RainViewer (https://www.rainviewer.com/) — "
                       "обязательна на странице, где эти данные показываются пользователю",
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    precip_desc = f"{nearest_precip['distance_km']}km {nearest_precip['compass']}" if nearest_precip else "none"
    thunder_desc = f"{nearest_thunder['distance_km']}km {nearest_thunder['compass']}" if nearest_thunder else "none"
    _write_debug({
        "status": "ok",
        "frames_fetched": len(arrs),
        "times_unix": times_unix,
        "precip_pairs_used": n_pairs_p,
        "thunder_pairs_used": n_pairs_t,
        "precip_motion": precip_motion,
        "thunder_motion": thunder_motion,
        "tile_urls": tile_urls,
    })
    print(f"  [OK] nearby_precip.py: precip={precip_desc}, thunder(proxy)={thunder_desc}, "
          f"precip_motion={precip_motion}, thunder_motion={thunder_motion}")


if __name__ == "__main__":
    main()
