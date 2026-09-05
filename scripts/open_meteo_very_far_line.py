"""
open_meteo_very_far_line.py — ЭКСПЕРИМЕНТ (2026-09-03, по прямому запросу
пользователя): та же схема, что near-tier (детект карты -> запрос
Open-Meteo), но на very_far (~2500км) снимке, ТОЛЬКО по Open-Meteo, БЕЗ
подтверждения станциями (их там физически нет с нужной плотностью).

Сетка 10x10 по всему bbox very_far_window (geo_config.json), 1 модель
(ecmwf_ifs, для эксперимента без ансамбля), градиент по сетке, ridge
(argmax градиента в каждой строке) — линия рисуется прямо на
data/anim/very_far_geocolour.png.

Пишет поверх того же PNG (перезаписывает).
Запуск: python3 scripts/open_meteo_very_far_line.py
"""
import json
import os
import traceback

import numpy as np
from PIL import Image, ImageDraw

from open_meteo_field_fetch import fetch_model_current, _gradient_ridge

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_CONFIG_FILE = os.path.join(BASE_DIR, "data", "geo_config.json")
IMG_FILE = os.path.join(BASE_DIR, "data", "anim", "very_far_geocolour.png")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_very_far_line_debug.json")

GRID_N = 10  # 10x10=100 точек — лимит батча Open-Meteo
MODEL_ID = "ecmwf_ifs"


def _write_debug(status, **extra):
    """Логи Actions/VPS недоступны из песочницы Claude — пишем в
    коммитящийся файл, чтобы диагностировать сбой по факту следующего
    прогона (тот же приём, что для GitHub Actions job logs, см.
    docs/topics/hosting_migration.md)."""
    payload = {"status": status, **extra}
    tmp = DEBUG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DEBUG_FILE)


def main():
    try:
        with open(GEO_CONFIG_FILE, "r", encoding="utf-8") as f:
            geo = json.load(f)
        min_lon, min_lat, max_lon, max_lat = geo["very_far_window"]["bbox"]

        lats = np.linspace(max_lat, min_lat, GRID_N)
        lons = np.linspace(min_lon, max_lon, GRID_N)
        flat = [{"lat": round(float(la), 3), "lon": round(float(lo), 3)} for la in lats for lo in lons]

        vals = fetch_model_current(MODEL_ID, flat)
        if not vals or len(vals) != len(flat):
            _write_debug("bad_response_len", n_expected=len(flat), n_got=len(vals) if vals else 0)
            print(f"  [WARN] open_meteo_very_far_line: неожиданный размер ответа ({len(vals) if vals else 0} из {len(flat)})")
            return

        n_none = sum(1 for v in vals if v.get("temp") is None)
        if n_none:
            _write_debug("some_temps_none", n_none=n_none, sample=vals[:3])

        temp_grid = np.array([v["temp"] if v["temp"] is not None else np.nan for v in vals], dtype=float).reshape(GRID_N, GRID_N)
        if np.isnan(temp_grid).any():
            _write_debug("nan_in_grid", n_nan=int(np.isnan(temp_grid).sum()))
            print("  [WARN] open_meteo_very_far_line: в сетке есть NaN, пропуск")
            return

        _grad, ridge = _gradient_ridge(temp_grid)

        img = Image.open(IMG_FILE).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)
        pts = []
        for row in range(GRID_N):
            px = ridge[row] / (GRID_N - 1) * (w - 1)
            py = row / (GRID_N - 1) * (h - 1)
            pts.append((px, py))
        draw.line(pts, fill=(255, 0, 255), width=4)
        img.save(IMG_FILE)
        _write_debug("ok", ridge=ridge.tolist())
        print(f"  [OK] open_meteo_very_far_line: линия по {MODEL_ID} нарисована на {IMG_FILE}")
    except Exception as e:
        _write_debug("exception", error=str(e), traceback=traceback.format_exc())
        print(f"  [WARN] open_meteo_very_far_line: {e}")
        raise


if __name__ == "__main__":
    main()
