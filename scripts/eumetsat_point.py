"""
eumetsat_point.py — значения EUMETSAT (облачность/высота облаков/молнии)
в точке Одессы (СИНОП 33837), для сравнения с RainViewer-прокси в блоке
"Осадки и гроза поблизости" на pws.html.

Источник: EUMETView WMS (view.eumetsat.int/geoserver/wms), бесплатно, без
регистрации. Запрашиваем GetFeatureInfo (не GetMap) в маленьком окне
вокруг точки — это даёт "сырое" значение пикселя растра, а не цвет.

ВАЖНО — ЭКСПЕРИМЕНТАЛЬНЫЙ СТАТУС: у нас нет проверенной живым запросом
таблицы "сырое значение -> категория/метры/число вспышек" (в отличие от
RainViewer, где есть официальный CSV с цветовой таблицей). Первый живой
прогон нужно свериться с debug-файлом и легендой на eumetsat.html, чтобы
откалибровать расшифровку. До калибровки на фронтенде показываем сырое
значение с пометкой "не откалибровано".

Слои и шаг обновления реальных данных на сервере:
  msg_fes:clm    — Cloud Mask, 15 мин
  msg_fes:cth    — Cloud Top Height, 15 мин
  mtg_fd:li_afa  — Lightning Accumulated Flash Area, 5 мин

Пишет data/eumetsat_point.json + data/eumetsat_point_debug.json (raw text
ответов GetFeatureInfo — по ним и будем калибровать в следующей итерации).
"""

import json
import os
import re
from datetime import datetime, timezone

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_point.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_point_debug.json")

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
CENTER_LAT = 46.4406
CENTER_LON = 30.7703
CENTER_LABEL = "Одесса (СИНОП 33837)"

# небольшое окно вокруг точки (~5-6 км), нечётные width/height чтобы
# I/J=50 точно попадали в центральный пиксель окна
HALF_WINDOW_DEG = 0.05
GRID = 101
CENTER_IJ = GRID // 2

LAYERS = {
    "clm": {"name": "msg_fes:clm", "step_minutes": 15},
    "cth": {"name": "msg_fes:cth", "step_minutes": 15},
    "li_afa": {"name": "mtg_fd:li_afa", "step_minutes": 5},
}

TIMEOUT = 20


def _nearest_step_iso(step_minutes):
    now = datetime.now(timezone.utc)
    step = step_minutes
    floored_minute = (now.minute // step) * step
    dt = now.replace(minute=0, second=0, microsecond=0)
    dt = dt.replace(minute=floored_minute) if floored_minute < 60 else dt
    # добавляем часы, если floored_minute переполнил (не должно, но на всякий)
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def _fetch_feature_info(layer_name, time_iso, retries=2, delay=3):
    import time as _time

    min_lon = CENTER_LON - HALF_WINDOW_DEG
    max_lon = CENTER_LON + HALF_WINDOW_DEG
    min_lat = CENTER_LAT - HALF_WINDOW_DEG
    max_lat = CENTER_LAT + HALF_WINDOW_DEG
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"  # CRS:84 = lon,lat порядок

    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": layer_name,
        "query_layers": layer_name,
        "styles": "",
        "crs": "CRS:84",
        "bbox": bbox,
        "width": GRID,
        "height": GRID,
        "i": CENTER_IJ,
        "j": CENTER_IJ,
        "info_format": "text/plain",
        "feature_count": 1,
        "time": time_iso,
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(WMS_BASE, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                _time.sleep(delay)
    raise last_err


def _extract_number(raw_text):
    """Best-effort: последнее число в ответе text/plain. Не откалибровано —
    просто чтобы было что показать до ручной проверки формата ответа."""
    if not raw_text:
        return None
    matches = re.findall(r"-?\d+\.?\d*", raw_text)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _write_debug(payload):
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    results = {}
    debug_raw = {}
    any_ok = False

    for key, cfg in LAYERS.items():
        time_iso = _nearest_step_iso(cfg["step_minutes"])
        try:
            raw = _fetch_feature_info(cfg["name"], time_iso)
            debug_raw[key] = {"time_requested": time_iso, "raw_response": raw[:2000]}
            results[key] = {
                "value_raw": _extract_number(raw),
                "time_requested": time_iso,
                "calibrated": False,
            }
            any_ok = True
        except Exception as e:
            debug_raw[key] = {"time_requested": time_iso, "error": str(e)}
            results[key] = {"value_raw": None, "time_requested": time_iso, "calibrated": False, "error": str(e)}

    out = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "point": {"lat": CENTER_LAT, "lon": CENTER_LON, "label": CENTER_LABEL},
        "layers": results,
        "note": "Сырые значения GetFeatureInfo, расшифровка (категория/метры/число вспышек) "
                "ещё не откалибрована по реальному ответу сервера — сверить с debug-файлом.",
        "source": "EUMETSAT EUMETView WMS (view.eumetsat.int)",
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    _write_debug({
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok" if any_ok else "error",
        "responses": debug_raw,
    })

    summary = ", ".join(f"{k}={v['value_raw']}" for k, v in results.items())
    print(f"  [OK] eumetsat_point.py: {summary}")


if __name__ == "__main__":
    main()
