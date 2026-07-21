"""
nearby_precip.py — расстояние до ближайших осадков и признаков грозы от Одессы.

Источник: RainViewer Weather Maps API (радар, реальное наблюдение, НЕ модель) —
https://api.rainviewer.com/public/weather-maps.json, бесплатно для
персонального/образовательного использования, без API-ключа. ToS RainViewer
требует атрибуцию "Weather data by RainViewer" там, где эти данные показываются
человеку — это забота фронтенда (страница с индикатором), не этого скрипта.

Тянем один тайл радара, центрированный на СИНОП 33837 (46.4406, 30.7703):
цветовая схема "Universal Blue" (color=2), БЕЗ сглаживания (options=0_0) —
это важно, сглаживание интерполирует цвета между dBZ-ступенями и портит
обратное сопоставление цвет→dBZ. zoom=6, size=512px:
  ground_width ≈ 40075016.686 / 2**zoom * cos(lat) ≈ 432 км (радиус ~216 км)
  ~0.84 км/пиксель — с запасом покрывает те же 200 км, что и в прежней
  Open-Meteo-версии, но это уже фактическое наблюдение, а не модель.

Про Blitzortung (сознательно НЕ используется): их правила ограничивают
использование данных участниками сети (кто держит свой приёмник) или теми,
кому явно разрешили — это отдельно от и шире, чем просто запрет
коммерческого использования. Наш случай (личный проект, не участник,
разрешения не спрашивали) под их условия не попадает, даже без всякой
коммерции.

"Гроза" здесь — ПРОКСИ по отражаемости (>=45 dBZ, эмпирический порог
конвективного ядра), а НЕ детекция реального разряда молнии. У порога есть
и ложные срабатывания (сильный ливень без грозы даёт те же dBZ), и пропуски
(отдельные грозы с более низкой отражаемостью). Настоящая детекция молний
(EUMETSAT MTG Lightning Imager — спутник, легально и бесплатно после
регистрации) — вариант на будущее, сильно дороже по интеграции (netCDF
через EUMETSAT Data Store, а не JSON), см. "on the horizon" в памяти проекта.

Пишет один снимок (не историю) в data/nearby_precip.json — та же форма
полей, что и в предыдущей Open-Meteo-версии (nearest_precip,
nearest_thunderstorm), плюс radar_time/radar_age_min для видимости
свежести радарного кадра. Отладка — data/nearby_precip_debug.json.
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

PRECIP_ALPHA_THRESHOLD = 200   # ~dBZ>=15 в таблице ниже — граница "значимый сигнал" vs фоновый шум
THUNDER_DBZ_THRESHOLD = 45     # эмпирический порог конвективного ядра (прокси грозы, не факт молнии)

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]

# Таблица цвет→dBZ схемы "Universal Blue" (color=2), только dBZ>=15, где
# пиксели полностью непрозрачны (alpha=255) — см. докстринг про PRECIP_ALPHA_THRESHOLD.
# Источник: https://www.rainviewer.com/files/rainviewer_api_colors_table.csv
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


def _write_debug(status, note, extra=None):
    try:
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status,
            "note": note,
        }
        if extra:
            payload.update(extra)
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


def _fetch_tile(host, path, retries=3, delay=5):
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
    """arr: (H,W,4) uint8. Возвращает (mask_precip, dbz_est) обеих формы (H,W)."""
    alpha = arr[:, :, 3].astype(np.int16)
    mask_precip = alpha >= PRECIP_ALPHA_THRESHOLD

    dbz_est = np.full(arr.shape[:2], -99, dtype=np.int16)
    ys, xs = np.where(mask_precip)
    if len(ys) > 0:
        rgb = arr[ys, xs, :3].astype(np.float32)
        # nearest-neighbor по RGB-таблице dBZ>=15 (все непрозрачные значения)
        dists = np.sum((rgb[:, None, :] - _DBZ_RGB[None, :, :]) ** 2, axis=2)
        nearest_idx = np.argmin(dists, axis=1)
        dbz_est[ys, xs] = _DBZ_VALUES[nearest_idx]
    return mask_precip, dbz_est


def _nearest_point(mask, meters_per_px):
    """Находит ближайший к центру пиксель, где mask=True. Возвращает dict или None."""
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
    return {
        "distance_km": round(dist_km, 1),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "bearing_deg": round(bearing, 0),
        "compass": _compass(bearing),
    }


def main():
    try:
        wm = _fetch_weather_maps()
    except Exception as e:
        _write_debug("error", f"weather-maps.json fetch failed: {e}")
        print(f"  [WARN] nearby_precip.py: weather-maps.json fetch failed: {e}")
        return

    past = (wm.get("radar") or {}).get("past") or []
    if not past:
        _write_debug("error", "no radar.past frames in weather-maps.json")
        print("  [WARN] nearby_precip.py: нет кадров radar.past")
        return

    frame = past[-1]
    host = wm.get("host", "")
    radar_time = frame.get("time")

    try:
        arr, tile_url = _fetch_tile(host, frame["path"])
    except Exception as e:
        _write_debug("error", f"tile fetch failed: {e}", {"tile_url_attempted": True})
        print(f"  [WARN] nearby_precip.py: tile fetch failed: {e}")
        return

    meters_per_px = _meters_per_pixel()
    mask_precip, dbz_est = _classify(arr)
    mask_thunder = mask_precip & (dbz_est >= THUNDER_DBZ_THRESHOLD)

    nearest_precip = _nearest_point(mask_precip, meters_per_px)
    nearest_thunder = _nearest_point(mask_thunder, meters_per_px)

    radar_dt = datetime.fromtimestamp(radar_time, tz=timezone.utc) if radar_time else None
    radar_age_min = None
    if radar_dt:
        radar_age_min = round((datetime.now(timezone.utc) - radar_dt).total_seconds() / 60, 1)

    out = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "center": {"lat": CENTER_LAT, "lon": CENTER_LON, "label": CENTER_LABEL},
        "nearest_precip": nearest_precip,
        "nearest_thunderstorm": nearest_thunder,
        "radar_time": radar_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if radar_dt else None,
        "radar_age_min": radar_age_min,
        "coverage_radius_km": round(meters_per_px * TILE_SIZE / 2 / 1000, 0),
        "resolution_km_per_px": round(meters_per_px / 1000, 2),
        "source": "RainViewer радар (реальное наблюдение); гроза — прокси по отражаемости "
                  f">={THUNDER_DBZ_THRESHOLD}dBZ, не детекция молнии",
        "attribution": "Weather data by RainViewer (https://www.rainviewer.com/) — "
                       "обязательна на странице, где эти данные показываются пользователю",
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    precip_desc = (
        f"{nearest_precip['distance_km']}km {nearest_precip['compass']}"
        if nearest_precip else "none"
    )
    thunder_desc = (
        f"{nearest_thunder['distance_km']}km {nearest_thunder['compass']}"
        if nearest_thunder else "none"
    )
    _write_debug(
        "ok",
        f"precip={precip_desc}, thunder(proxy)={thunder_desc}, radar_age={radar_age_min}min",
        {"tile_url": tile_url},
    )
    print(f"  [OK] nearby_precip.py: precip={precip_desc}, thunder(proxy)={thunder_desc}")


if __name__ == "__main__":
    main()
