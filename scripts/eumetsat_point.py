"""
eumetsat_point.py — значения EUMETSAT (облачность/высота облаков/молнии)
в точке Одессы (СИНОП 33837), для сравнения с RainViewer-прокси в блоке
"Осадки и гроза поблизости" на pws.html.

Источник: EUMETView WMS (view.eumetsat.int/geoserver/wms), бесплатно, без
регистрации. Запрашиваем GetFeatureInfo в маленьком окне вокруг точки.

КАЛИБРОВКА (по итогам первого живого прогона, см. debug-файл):
GetFeatureInfo для этих "RGB with custom legend"-слоёв возвращает не
категорию/метры напрямую, а RGB-компоненты ОТРЕНДЕРЕННОГО цвета
(RED_BAND/GREEN_BAND/BLUE_BAND) — то есть тот же цвет, что и на карте.
Расшифровываем как и для RainViewer: сравниваем с цветами легенды.

  msg_fes:clm (Cloud Mask) — 3 цвета легенды, надёжно различимы:
      clear_water ~ синий, clear_land ~ зелёный, cloud = белый (255,255,255)
  msg_fes:cth (Cloud Top Height) — непрерывная радужная шкала 320-16000м,
      официальной цветовой таблицы (как CSV у RainViewer) у нас нет —
      показываем RGB и грубый качественный бакет по цвету (не метры).
  mtg_fd:li_afa (молнии) — аналогично, шкала 1...20+ вспышек/5мин,
      без калиброванной таблицы — показываем RGB + факт наличия сигнала
      (нетранспарентный пиксель = есть накопленная площадь вспышек).

TIME-параметр больше НЕ вычисляем сами (это ломало запрос — сервер несколько
раз отвечал "No nearest match found for time dimension"). Просто не передаём
time вовсе — WMS сам берёт свой актуальный "default" (см. GetCapabilities).

Пишет data/eumetsat_point.json + data/eumetsat_point_debug.json (raw text
ответов GetFeatureInfo — на случай дальнейшей калибровки cth/li_afa).
"""

import json
import math
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
    "clm": "msg_fes:clm",
    "cth": "msg_fes:cth",
    "li_afa": "mtg_fd:li_afa",
}

TIMEOUT = 20

# анкеры цветов легенды Cloud Mask (см. eumetsat.html скриншоты: чистые
# синий/зелёный/белый, без точных hex из официальной таблицы — но три
# категории максимально разнесены по цвету, так что приближённые анкеры
# всё равно классифицируют верно)
CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}


def _write_debug(payload):
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_feature_info(layer_name, retries=2, delay=3):
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
        # без time — пусть сервер берёт свой актуальный default
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


def _extract_rgb(raw_text):
    """Парсит 'RED_BAND = X\nGREEN_BAND = Y\nBLUE_BAND = Z' -> (r,g,b) int 0-255."""
    if not raw_text:
        return None
    m = re.search(
        r"RED_BAND\s*=\s*([\d.]+).*?GREEN_BAND\s*=\s*([\d.]+).*?BLUE_BAND\s*=\s*([\d.]+)",
        raw_text, re.DOTALL,
    )
    if not m:
        return None
    try:
        return tuple(round(float(m.group(i))) for i in (1, 2, 3))
    except ValueError:
        return None


def _nearest_anchor(rgb, anchors):
    if rgb is None:
        return None
    best_key, best_dist = None, None
    for key, anchor in anchors.items():
        dist = sum((a - b) ** 2 for a, b in zip(rgb, anchor))
        if best_dist is None or dist < best_dist:
            best_key, best_dist = key, dist
    return best_key


def _hue_bucket(rgb):
    """Грубая качественная привязка к позиции на радужной шкале (не метры,
    не число вспышек — просто 'где на шкале', калибровка на будущее)."""
    if rgb is None:
        return None
    r, g, b = (c / 255.0 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return "серый/чёрный (низ шкалы или нет сигнала)"
    h, s, v = 0.0, 0.0, mx
    d = mx - mn
    s = d / mx if mx else 0
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    h *= 60
    if v > 0.9 and s < 0.15:
        return "белый (верх шкалы)"
    if h < 20 or h >= 320:
        return "красный/бордовый (высокая часть шкалы)"
    if h < 70:
        return "жёлто-оранжевый (середина-верх шкалы)"
    if h < 170:
        return "зелёный (середина шкалы)"
    if h < 260:
        return "синий/голубой (низ-середина шкалы)"
    return "фиолетовый (низ шкалы)"


def main():
    results = {}
    debug_raw = {}
    any_ok = False

    for key, layer_name in LAYERS.items():
        try:
            raw = _fetch_feature_info(layer_name)
            debug_raw[key] = {"raw_response": raw[:2000]}
            rgb = _extract_rgb(raw)
            entry = {"rgb": rgb, "calibrated": False}
            if key == "clm":
                entry["category"] = _nearest_anchor(rgb, CLM_ANCHORS)
                entry["calibrated"] = True  # 3 цвета легенды надёжно различимы
            else:
                entry["hue_bucket"] = _hue_bucket(rgb)
            results[key] = entry
            any_ok = True
        except Exception as e:
            debug_raw[key] = {"error": str(e)}
            results[key] = {"rgb": None, "calibrated": False, "error": str(e)}

    out = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "point": {"lat": CENTER_LAT, "lon": CENTER_LON, "label": CENTER_LABEL},
        "layers": results,
        "note": "Cloud Mask (clm) откалиброван по 3 цветам легенды. Высота облаков (cth) "
                "и молнии (li_afa) — только RGB + грубая позиция на шкале, точных чисел "
                "(метры/кол-во вспышек) без официальной цветовой таблицы нет.",
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

    summary = ", ".join(f"{k}={v.get('rgb')}" for k, v in results.items())
    print(f"  [OK] eumetsat_point.py: {summary}")


if __name__ == "__main__":
    main()
