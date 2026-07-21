"""
nearby_precip.py — расстояние до ближайших осадков/грозы от Одессы.

Источник: Open-Meteo forecast API (уже используется в проекте, отдельного
ключа не нужно). Строим кольцевую сетку точек вокруг станции 33837
(46.4406, 30.7703 — та же точка, что и update.py) на нескольких радиусах
и по 8 направлениям, одним запросом (Open-Meteo поддерживает несколько
locations через запятую в latitude/longitude), current=precipitation,
rain, showers, weather_code.

Это НЕ радар (в отличие от RainViewer) — координаты и осадки берутся
из ансамблевой модели open-meteo (обычно ECMWF/GFS blend), с шагом сетки
~11км и часовым разрешением у current. Погрешность оценки расстояния —
порядка размера ячейки модели (5-15 км), для радара понадобится
отдельный источник (RainViewer/Blitzortung — см. "on the horizon").
Для быстрой оценки "далеко/близко" этого достаточно.

Определяем два расстояния:
  - nearest_precip       — ближайшая точка сетки с precipitation > 0.1 мм
  - nearest_thunderstorm — ближайшая точка с weather_code грозы (95/96/99)

Пишет один снимок (не историю) в data/nearby_precip.json:
  {
    "timestamp": ISO8601,
    "center": {"lat":.., "lon":.., "label": "Одесса (СИНОП 33837)"},
    "nearest_precip": {"distance_km":.., "lat":.., "lon":.., "bearing_deg":..,
                        "compass": "СЗ", "precipitation_mm": ..} | null,
    "nearest_thunderstorm": {...той же формы, "weather_code": 95} | null,
    "grid": {"radii_km": [...], "directions": 8, "points_checked": N},
    "source": "open-meteo forecast (модельная сетка, не радар)"
  }

Отладка — data/nearby_precip_debug.json (статус последнего запуска, видно
прямо в репозитории без доступа к логам Actions).
"""

import json
import math
import os
from datetime import datetime, timezone

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "nearby_precip.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "nearby_precip_debug.json")

# та же точка, что и STATION 33837 в update.py
CENTER_LAT = 46.4406
CENTER_LON = 30.7703
CENTER_LABEL = "Одесса (СИНОП 33837)"

RADII_KM = [10, 20, 35, 50, 75, 100, 150, 200]
N_DIRECTIONS = 8  # каждые 45°
EARTH_R_KM = 6371.0

PRECIP_THRESHOLD_MM = 0.1
THUNDER_CODES = {95, 96, 99}  # WMO weather_code: гроза

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 20

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


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


def _destination_point(lat, lon, bearing_deg, distance_km):
    """Точка на сфере на distance_km от (lat, lon) по азимуту bearing_deg."""
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brg = math.radians(bearing_deg)
    d_r = distance_km / EARTH_R_KM

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


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


def _build_grid():
    """Точки сетки: центр + кольца (radius, bearing)."""
    points = [(CENTER_LAT, CENTER_LON, 0.0, 0.0)]  # lat, lon, dist_km, bearing_deg
    for radius in RADII_KM:
        for i in range(N_DIRECTIONS):
            bearing = i * (360.0 / N_DIRECTIONS)
            plat, plon = _destination_point(CENTER_LAT, CENTER_LON, bearing, radius)
            points.append((plat, plon, radius, bearing))
    return points


def _fetch_grid(points, retries=3, delay=5):
    import time

    lats = ",".join(f"{p[0]:.4f}" for p in points)
    lons = ",".join(f"{p[1]:.4f}" for p in points)
    url = (
        f"{FORECAST_URL}?latitude={lats}&longitude={lons}"
        "&current=precipitation,rain,showers,weather_code&timezone=UTC"
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            # при одной точке open-meteo вернёт dict, а не list — приводим к списку
            if isinstance(data, dict):
                data = [data]
            return data
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay)
    raise last_err


def _nearest(points, results, predicate):
    best = None
    for (lat, lon, dist_km, bearing), res in zip(points, results):
        cur = (res or {}).get("current", {})
        if cur is None:
            continue
        if not predicate(cur):
            continue
        # расстояние — реальное haversine от центра (точнее, чем номинальный dist_km сетки)
        d = _haversine_km(CENTER_LAT, CENTER_LON, lat, lon)
        if best is None or d < best["distance_km"]:
            b = _bearing_km(CENTER_LAT, CENTER_LON, lat, lon)
            best = {
                "distance_km": round(d, 1),
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "bearing_deg": round(b, 0),
                "compass": _compass(b),
                "precipitation_mm": cur.get("precipitation"),
                "weather_code": cur.get("weather_code"),
            }
    return best


def main():
    points = _build_grid()
    try:
        results = _fetch_grid(points)
    except Exception as e:
        _write_debug("error", f"fetch failed: {e}")
        print(f"  [WARN] nearby_precip.py: fetch failed: {e}")
        return

    if len(results) != len(points):
        _write_debug(
            "warn",
            f"mismatch: {len(points)} points sent, {len(results)} results received",
        )
        print("  [WARN] nearby_precip.py: количество точек и ответов не совпадает")
        return

    nearest_precip = _nearest(
        points, results,
        lambda cur: (cur.get("precipitation") or 0) >= PRECIP_THRESHOLD_MM,
    )
    nearest_thunder = _nearest(
        points, results,
        lambda cur: cur.get("weather_code") in THUNDER_CODES,
    )
    # у грозовой точки precipitation_mm не нужен в выводе — убираем лишнее поле
    if nearest_precip:
        nearest_precip.pop("weather_code", None)
    if nearest_thunder:
        nearest_thunder.pop("precipitation_mm", None)

    out = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "center": {"lat": CENTER_LAT, "lon": CENTER_LON, "label": CENTER_LABEL},
        "nearest_precip": nearest_precip,
        "nearest_thunderstorm": nearest_thunder,
        "grid": {
            "radii_km": RADII_KM,
            "directions": N_DIRECTIONS,
            "points_checked": len(points),
        },
        "source": "open-meteo forecast (модельная сетка, не радар)",
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _write_debug(
        "ok",
        f"precip={'нет в радиусе' if not nearest_precip else str(nearest_precip['distance_km'])+'км'}, "
        f"thunder={'нет в радиусе' if not nearest_thunder else str(nearest_thunder['distance_km'])+'км'}",
        {"points_checked": len(points)},
    )
    if nearest_precip:
        precip_desc = f"{nearest_precip['distance_km']}km {nearest_precip['compass']}"
    else:
        precip_desc = "none"
    thunder_desc = f"{nearest_thunder['distance_km']}km" if nearest_thunder else "none"
    print(f"  [OK] nearby_precip.py: precip={precip_desc}, thunder={thunder_desc}")


if __name__ == "__main__":
    main()
