"""
eumetsat_far_watch.py — дальний/очень дальний контроль крупных облачных
систем (тиры "far" ≈1000км и "very_far" ≈2500км из data/geo_config.json).

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ (не расширение *_motion.py): на дистанции 1000-2500км
за интервал 30мин-4ч смещение фронта/циклона между кадрами — единицы
процентов от размера окна, векторный трекинг (FFT phase correlation, как в
eumetsat_ir_motion.py/eumetsat_cloud_forecast.py) на таком масштабе даёт шум,
а не сигнал. Поэтому здесь НЕТ скорости/направления смещения — вместо этого:
  1) есть ли в каждом из 8 секторов (компас, относительно Одессы) заметная
     облачная масса прямо сейчас (доля облачных пикселей в секторе)
  2) грубая "высота/тяжесть" системы в секторе (ординальный CTH-индекс,
     тот же приём, что в eumetsat_cloud_forecast.py — не физические метры,
     только для сравнения между прогонами)
  3) тренд РОСТА/УБЫВАНИЯ доли облачности в секторе по сравнению с прошлым
     сохранённым снимком (не с предыдущим кадром через 10 мин, а с прошлым
     прогоном ЭТОГО скрипта — 30-60 мин для far, 2-4ч для very_far, частота
     задаётся расписанием в .github/workflows/far_watch.yml, не самим кодом)

ДЕКОДИРОВАНИЕ CLM/CTH: переиспользую те же цветовые якоря (CLM_ANCHORS,
CTH_ORDINAL_ANCHORS), что уже проверены в eumetsat_cloud_forecast.py — не
изобретаю новую классификацию.

ПОЧЕМУ НЕ geocolour ДЛЯ АВТО-ДЕТЕКТА: geocolour — RGB-композит "как выглядит
из космоса", у него нет устойчивого порога "это облако/не облако" (в отличие
от clm, который явно закодирован 3 цветами легенды). Для автоматического
обнаружения годится только clm(+cth), поэтому оба тира (far И very_far)
считаются по ним. Это отличается от изначального плана "1 слой (geocolour)
для very_far" — geocolour там был для ВИЗУАЛА, а не для детектора; сам
детектор в обоих тирах на clm/cth. Картинку geocolour для very_far можно
добавить отдельно как чисто визуальный элемент (не влияет на verdict) —
сейчас не делаю, чтобы не путать источник вердикта с источником картинки.

БЕЗ ПЕРСИСТЕНТНОГО БУФЕРА КАДРОВ (в отличие от *_motion.py/cloud_forecast.py):
там буфер нужен для векторного трекинга по нескольким кадрам подряд. Здесь
достаточно сравнить ТЕКУЩИЙ снимок с ОДНИМ предыдущим (компактный JSON, не
npz с полными полями) — не оптический поток, а просто "сектор был 8%, стал
15% -> растёт".

Запуск: python eumetsat_far_watch.py far|very_far
"""

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LAYER_CLM = "msg_fes:clm"
LAYER_CTH = "msg_fes:cth"
LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"  # только для ВИЗУАЛА (см. докстринг выше — не для авто-детекта)
ANIM_DIR = os.path.join(BASE_DIR, "data", "anim")  # тот же каталог, что и у eumetsat_anim_render.py — уже покрыт фиксом git_push_satellite() "git add data/anim" (2026-08-03)

CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}

CTH_ORDINAL_ANCHORS = [
    (0, (0, 0, 0)),
    (1, (75, 0, 130)),
    (2, (0, 0, 255)),
    (3, (0, 255, 255)),
    (4, (0, 200, 0)),
    (5, (255, 255, 0)),
    (6, (255, 128, 0)),
    (7, (255, 255, 255)),
]
_CTH_IDX = np.array([a[0] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)
_CTH_RGB = np.array([a[1] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)

# Минимум валидных пикселей в секторе, чтобы вообще публиковать по нему
# цифры — иначе на краю очень-дальнего окна (мало данных сцены/угол обзора
# спутника) можно получить "cloud_fraction=1.0" по 3 пикселям и решить, что
# там ураган.
MIN_VALID_PX_FOR_SECTOR = 200

# Порог изменения доли облачности между прогонами для "растёт"/"убывает" —
# ниже этого считаем "стабильно" (шум классификации, не реальная динамика).
TREND_THRESHOLD = 0.03

TIERS = {
    "far": {
        "radius_label_km": 1000,
        "out_file": "eumetsat_far_watch.json",
        "state_file": "eumetsat_far_watch_state.json",
        "debug_file": "eumetsat_far_watch_debug.json",
    },
    "very_far": {
        "radius_label_km": 2500,
        "out_file": "eumetsat_very_far_watch.json",
        "state_file": "eumetsat_very_far_watch_state.json",
        "debug_file": "eumetsat_very_far_watch_debug.json",
    },
}


def _classify_cloud_mask(arr):
    """Как в eumetsat_cloud_forecast.py — (is_cloud, valid) по 3 цветам
    легенды msg_fes:clm, valid=False на прозрачных (нет данных) пикселях."""
    h, w, _ = arr.shape
    rgb = arr[:, :, :3].reshape(-1, 3).astype(np.float32)
    alpha = arr[:, :, 3].reshape(-1)
    valid = alpha > 0
    anchors = np.array(list(CLM_ANCHORS.values()), dtype=np.float32)
    keys = list(CLM_ANCHORS.keys())
    dists = np.sum((rgb[:, None, :] - anchors[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    is_cloud = (np.array(keys)[nearest_idx] == "cloud").reshape(h, w)
    valid = valid.reshape(h, w)
    is_cloud = is_cloud & valid
    return is_cloud, valid


def _cth_ordinal_index(arr):
    """Как в eumetsat_cloud_forecast.py — ординальный индекс 0..7 (не метры,
    только для сравнения между прогонами)."""
    h, w = arr.shape[:2]
    pixels = arr[:, :, :3].reshape(-1, 3).astype(np.float32)
    dists = np.sum((pixels[:, None, :] - _CTH_RGB[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    return _CTH_IDX[nearest_idx].reshape(h, w)


def _pixel_grid_bearing_km(bbox, width, height):
    """Для КАЖДОГО пикселя (H,W) — (dist_km, bearing_deg) от fc.CENTER_LAT/LON.
    Обобщённая версия fc.pixel_to_km_offset()/local_area_mask() для
    произвольного bbox/width/height (те завязаны на TILE_SIZE/HALF_WINDOW_DEG
    малого моторного окна и здесь не подходят). Конвенция pixel-as-area:
    центр пикселя, не край (тот же принцип, что и в fc.pixel_to_km_offset,
    см. её докстринг про инцидент 2026-08-02)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    rows, cols = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    lon = min_lon + (cols + 0.5) * (max_lon - min_lon) / width
    lat = max_lat - (rows + 0.5) * (max_lat - min_lat) / height  # row 0 = верх изображения = север
    dx_km = (lon - fc.CENTER_LON) * fc.KM_PER_DEG_LON
    dy_km = (lat - fc.CENTER_LAT) * fc.KM_PER_DEG_LAT
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    bearing_deg = (np.degrees(np.arctan2(dx_km, dy_km)) + 360) % 360
    return dist_km, bearing_deg


def _sector_index(bearing_deg):
    """8 секторов компаса, как fc.compass()/fc.COMPASS, но векторно по всей
    сетке сразу вместо поточечного вызова (производительность на больших
    полях far/very_far, до ~1000×700px)."""
    return (((bearing_deg + 22.5) % 360) // 45).astype(int)


def _fmt_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00.000Z")


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def run_tier(tier_key):
    cfg = TIERS[tier_key]
    bbox = fc.FAR_BBOX if tier_key == "far" else fc.VERY_FAR_BBOX
    target_km_per_px = fc.FAR_TARGET_KM_PER_PX if tier_key == "far" else fc.VERY_FAR_TARGET_KM_PER_PX

    from eumetsat_anim_render import _bbox_dimensions  # переиспользуем ту же формулу WIDTH/HEIGHT из bbox — не дублируем
    width, height = _bbox_dimensions(bbox, target_km_per_px)

    out_path = os.path.join(BASE_DIR, "data", cfg["out_file"])
    state_path = os.path.join(BASE_DIR, "data", cfg["state_file"])
    debug_path = os.path.join(BASE_DIR, "data", cfg["debug_file"])

    server_time, _ = fc.get_layer_latest_time(LAYER_CLM)
    prev_state = _load_json(state_path)
    if prev_state and server_time and prev_state.get("timestamp") == server_time:
        fc.write_debug(debug_path, {"status": "skipped", "tier": tier_key,
                                     "note": f"сервер ещё не объявил кадр новее {server_time}"})
        print(f"  [SKIP] eumetsat_far_watch.py: {tier_key} — новых данных пока нет ({server_time})")
        return

    time_iso = server_time  # None ок — fetch_map_custom сам запросит "текущее" (без TIME) в этом случае
    try:
        clm_arr = fc.fetch_map_custom(LAYER_CLM, bbox, width, height, time_iso=time_iso)
        cth_arr = fc.fetch_map_custom(LAYER_CTH, bbox, width, height, time_iso=time_iso)
    except Exception as e:
        fc.write_debug(debug_path, {"status": "error", "tier": tier_key, "error": str(e)})
        print(f"  [WARN] eumetsat_far_watch.py: {tier_key} — недоступно: {e}")
        return

    is_cloud, valid = _classify_cloud_mask(clm_arr)
    cth_idx = _cth_ordinal_index(cth_arr)
    dist_km, bearing_deg = _pixel_grid_bearing_km(bbox, width, height)
    sector_idx = _sector_index(bearing_deg)

    overall_valid_px = int(valid.sum())
    overall_cloud_frac = float(is_cloud.sum() / overall_valid_px) if overall_valid_px else None

    prev_sectors = (prev_state or {}).get("sectors", {})
    sectors_out = {}
    for i, name in enumerate(fc.COMPASS):
        sect_mask = (sector_idx == i)
        sect_valid = int((sect_mask & valid).sum())
        if sect_valid < MIN_VALID_PX_FOR_SECTOR:
            sectors_out[name] = {"cloud_fraction": None, "mean_cth_index": None,
                                  "trend": None, "note": "недостаточно валидных пикселей"}
            continue
        sect_cloud = sect_mask & valid & is_cloud
        frac = float(sect_cloud.sum() / sect_valid)
        mean_cth = float(cth_idx[sect_cloud].mean()) if sect_cloud.sum() else None

        trend = None
        prev_frac = prev_sectors.get(name, {}).get("cloud_fraction")
        if prev_frac is not None:
            delta = frac - prev_frac
            if delta > TREND_THRESHOLD:
                trend = "растёт"
            elif delta < -TREND_THRESHOLD:
                trend = "убывает"
            else:
                trend = "стабильно"

        sectors_out[name] = {"cloud_fraction": round(frac, 3),
                              "mean_cth_index": round(mean_cth, 2) if mean_cth is not None else None,
                              "trend": trend}

    # Вердикт: 1-2 сектора с наибольшей и/или растущей облачностью
    ranked = sorted(
        [(name, s) for name, s in sectors_out.items() if s["cloud_fraction"] is not None],
        key=lambda kv: kv[1]["cloud_fraction"], reverse=True,
    )
    if not ranked:
        verdict = "недостаточно данных для оценки"
    else:
        top = ranked[0]
        if top[1]["cloud_fraction"] < 0.1:
            verdict = f"значимых облачных систем в радиусе ≈{cfg['radius_label_km']}км не обнаружено"
        else:
            bits = [f"{top[0]}: {round(top[1]['cloud_fraction']*100)}%"]
            if top[1]["trend"]:
                bits.append(top[1]["trend"])
            growing = [n for n, s in ranked[1:3] if s.get("trend") == "растёт" and s["cloud_fraction"] >= 0.1]
            verdict = f"основная масса — {', '.join(bits)}"
            if growing:
                verdict += f"; также растёт: {', '.join(growing)}"

    payload = {
        "tier": tier_key,
        "timestamp": time_iso or _fmt_now(),
        "valid": True,
        "observed_area": {
            "center_lat": fc.CENTER_LAT, "center_lon": fc.CENTER_LON,
            "bbox": list(bbox), "radius_label_km": cfg["radius_label_km"],
            "geocolour_image": f"data/anim/{tier_key}_geocolour.png",
        },
        "overall_cloud_fraction": round(overall_cloud_frac, 3) if overall_cloud_frac is not None else None,
        "sectors": sectors_out,
        "verdict": verdict,
    }
    _save_json(out_path, payload)
    _save_json(state_path, {"timestamp": payload["timestamp"], "sectors": sectors_out})
    fc.write_debug(debug_path, {"status": "ok", "tier": tier_key, "timestamp": payload["timestamp"]})
    print(f"  [OK] eumetsat_far_watch.py: {tier_key} — {verdict}")

    # Визуальный снимок (geocolour) — ОТДЕЛЬНО от детектора выше (clm/cth),
    # см. докстринг в начале файла про "почему не geocolour для авто-детекта".
    # Best-effort: сбой здесь НЕ должен портить уже сохранённый payload —
    # текстовый анализ ценнее картинки, поэтому свой try/except и просто WARN.
    try:
        from eumetsat_anim_render import _composite_frame  # тот же способ подложки, что у mp4/png слоёв
        geo_arr = fc.fetch_map_custom(LAYER_GEOCOLOUR, bbox, width, height, time_iso=time_iso)
        frame = _composite_frame(geo_arr)
        os.makedirs(ANIM_DIR, exist_ok=True)
        out_img = os.path.join(ANIM_DIR, f"{tier_key}_geocolour.png")
        tmp_img = out_img.replace(".png", ".tmp.png")  # см. баг 2026-08-03 про расширение у tmp-файла в eumetsat_anim_render.py — тот же приём
        frame.save(tmp_img)
        os.replace(tmp_img, out_img)
        print(f"  [OK] eumetsat_far_watch.py: {tier_key}_geocolour.png сохранён")
    except Exception as e:
        print(f"  [WARN] eumetsat_far_watch.py: {tier_key} geocolour-снимок не удался: {e}")


def main():
    # Коммит/пуш НЕ делается здесь — вызывается из gh_satellite_pipeline.py
    # (git_push_satellite(), единый пуш на весь спутниковый прогон), который
    # запускает этот скрипт как под-шаг через check_eumetsat_far_watch()/
    # check_eumetsat_very_far_watch(). Раньше был отдельный git_push_far_watch()
    # + свой workflow far_watch.yml со своим cron — отказались (см. чат
    # 2026-08-03): лишняя независимая цепочка вместо переиспользования уже
    # работающей (телефон → full_pipeline → satellite_pipeline, workflow_run).
    if len(sys.argv) < 2 or sys.argv[1] not in TIERS:
        print("Использование: python eumetsat_far_watch.py far|very_far")
        sys.exit(1)
    run_tier(sys.argv[1])


if __name__ == "__main__":
    main()
