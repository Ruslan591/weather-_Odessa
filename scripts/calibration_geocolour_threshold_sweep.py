"""
calibration_geocolour_threshold_sweep.py — перебор сетки дневных
HSV-порогов _classify_cloud() (сейчас: s < 0.25 & v > 0.55) на тех же 200
исторических SYNOP-кадрах, что и calibration_geocolour_collect.py.

Контекст: первый прогон (schema_version=2, мультирадиус) показал, что
день-корреляция cloud_fraction vs synop_n лучше всего на r=25-50км
(Spearman rho~0.62-0.66), НО медианная cloud_fraction даже при N=8-9
(почти сплошная облачность) — всего 0.1-0.43, то есть систематическое
недодетектирование. ROI-усреднённый V при N=8-9 (0.536) впритык к порогу
v>0.55 — предположительно порог слишком строгий и режет реальные облачные
пиксели. Ночная ветка НЕ трогается (отдельная, более приоритетная
проблема с ночной классификацией уже задокументирована, calibration по
ночи — следующий шаг после дня).

Метод: для каждого дневного кадра, ОДИН раз выкачанного по сети, считает
cloud_fraction на радиусе 25км (лучший из мультирадиус-анализа для дня)
для СЕТКИ кандидатов (s_max, v_min) — без повторных сетевых запросов,
только пересчёт по уже загруженному RGBA-массиву. city_light-исключение
держится КАК ЕСТЬ (не часть этого перебора — отдельный вопрос).

Результат — data/calibration_geocolour_threshold_sweep.jsonl: на каждый
кадр строка с cloud_fraction для всех комбинаций сетки. Анализ (какая
комбинация лучше сближает bucket-mean-fraction с ожидаемой серединой
октanta N/8) делается отдельно, не в этом скрипте.
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_geocolour_motion import _is_daytime, _in_hue_range, LAYER_GEOCOLOUR  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_threshold_sweep.jsonl")
REQUEST_DELAY_SECONDS = 0.4

RADIUS_KM = 25  # лучший день-radius из мультирадиус-анализа 2026-08-11
GRID_VERSION = 2  # v1 (2026-08-11, первый прогон): s_max упирался в
# v_min=0.45 — это был КРАЙ сетки, лучший результат сел на границу, значит
# оптимум ниже. v2: расширяем v_min вниз (0.30-0.55), s_max почти не влиял
# на результат в v1 (0.15-0.35 давали почти одинаково) — оставляем всего
# 2 значения, чтобы не раздувать датасет.
S_MAX_GRID = [0.25, 0.35]
V_MIN_GRID = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _load_done_timestamps_and_prune_stale_grid():
    """Строки с ТЕКУЩЕЙ версией сетки — готовы, пропускаем. Строки старой
    версии сетки (другой набор комбинаций s_max/v_min) — выкидываем из
    файла целиком и пересобираем заново, чтобы не мешать несовместимые
    наборы ключей 'fractions' для одного и того же timestamp."""
    done = set()
    kept_lines = []
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("grid_version") == GRID_VERSION:
                    done.add(row["synop_timestamp"])
                    kept_lines.append(line)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            for line in kept_lines:
                f.write(line + "\n")
    return done


def main():
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = [s for s in json.load(f) if s["day"]]  # только дневные — ночь не в этом переборе
    print(f"дневных сроков в выборке: {len(samples)}")

    done = _load_done_timestamps_and_prune_stale_grid()
    mask = _radius_mask(RADIUS_KM)

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in samples:
            ts = entry["timestamp"]
            if ts in done:
                skipped += 1
                continue
            try:
                arr = fc.fetch_tile(LAYER_GEOCOLOUR, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            alpha_valid = arr[:, :, 3] > 0
            h, s, v = fc.rgb_to_hsv_vec(arr[:, :, :3])
            city_light = _in_hue_range(h, 15, 70) & (s > 0.2) & (v > 0.25)

            valid_in_mask = alpha_valid[mask]
            if valid_in_mask.sum() == 0:
                failed += 1
                print(f"  [FAIL] {ts}: нет валидных пикселей в ROI")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            s_roi = s[mask]
            v_roi = v[mask]
            city_roi = city_light[mask]
            alpha_roi = alpha_valid[mask]

            fractions = {}
            for s_max in S_MAX_GRID:
                for v_min in V_MIN_GRID:
                    cloud = (s_roi < s_max) & (v_roi > v_min)
                    is_cloud = cloud & (~city_roi) & alpha_roi
                    key = f"s{s_max}_v{v_min}"
                    fractions[key] = round(float(is_cloud.mean()), 4)

            row = {
                "grid_version": GRID_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "radius_km": RADIUS_KM,
                "fractions": fractions,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            print(f"  [OK] {ts} N={entry['n']} ({entry['bucket']})")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
