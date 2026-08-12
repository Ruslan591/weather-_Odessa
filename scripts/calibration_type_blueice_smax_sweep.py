"""
calibration_type_blueice_smax_sweep.py — перебор верхнего порога Saturation
(s_max) для правила "blue_ice" каскада _classify_type() (сейчас:
Hue 215-245 & S>0.25, БЕЗ верхнего порога по S).

Контекст: диагностика (2026-08-12) нашла, что blue_ice — главный источник
ложных срабатываний на ясном небе (N=0), а сравнение record-level
HSV-профилей ясных vs облачных сроков в этом Hue-диапазоне показало: у
ложных "облаков" (чистое море) Saturation в среднем ВЫШЕ (медиана ~0.68),
чем у настоящих высоких/ледяных облаков (медиана ~0.53) — то есть верхний
порог по S может отсечь пересыщенное синее море, оставив менее насыщенное
реальное облако. V (яркость) для этого не годится — распределения
почти полностью перекрываются (см. предыдущий шаг, calibration_type_
blueice_cloudy_profile.py).

Метод: для КАЖДОГО srока — и N=0 (заведомо ясно), и expected_group=2
(заведомо облачно/высокая) — тянет mtg_fd:rgb_cloudtype ОДИН раз, считает
ПОЛНЫЙ (ROI-площадный, не record-mean-прокси) group_ge1_fraction на
r=25км для сетки s_max-кандидатов в правиле blue_ice, ОСТАЛЬНОЙ каскад
БЕЗ ИЗМЕНЕНИЙ. Отдельно — baseline (текущее production-правило, без
s_max, эквивалент s_max=1.0/бесконечность) для сравнения.

Результат — data/calibration_type_blueice_smax_sweep.jsonl, по строке на
срок (group=clear/cloudy, group_ge1_fraction для каждого s_max-кандидата).
Анализ — отдельно, не в этом скрипте.
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_cloud_phase_type import _rgb_to_hsv_vec, _in_hue_range, LAYER_TYPE  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_FILE = os.path.join(BASE_DIR, "data", "calibration_type_synop.jsonl")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_type_blueice_smax_sweep.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1
RADIUS_KM = 25
S_MAX_GRID = [0.45, 0.50, 0.55, 0.60, 0.65, None]  # None = baseline, без верхнего порога


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _classify_type_with_blueice_smax(rgba, s_max):
    """Копия каскада _classify_type(), ЕДИНСТВЕННОЕ изменение — у правила
    blue_ice добавлен верхний порог по S (если s_max задан)."""
    alpha_valid = rgba[:, :, 3] > 0
    h_deg, s, v = _rgb_to_hsv_vec(rgba[:, :, :3])

    group = np.full(h_deg.shape, -1.0, dtype=np.float32)
    matched = np.zeros(h_deg.shape, dtype=bool)

    def _set(mask, value):
        nonlocal group, matched
        new = mask & (~matched)
        group = np.where(new, value, group)
        matched = matched | new

    _set(v < 0.22, 0.0)
    _set((s < 0.18) & (v > 0.80), 2.0)
    _set(_in_hue_range(h_deg, 265, 300) & (s > 0.25), 2.0)
    _set(_in_hue_range(h_deg, 300, 345) & (s > 0.25), 2.0)
    _set(_in_hue_range(h_deg, 345, 15) & (s > 0.4) & (v > 0.65), 2.0)
    if s_max is None:
        blue_ice_mask = _in_hue_range(h_deg, 215, 245) & (s > 0.25)
    else:
        blue_ice_mask = _in_hue_range(h_deg, 215, 245) & (s > 0.25) & (s <= s_max)
    _set(blue_ice_mask, 2.0)
    _set(_in_hue_range(h_deg, 180, 215) & (s >= 0.15) & (s <= 0.5), 2.0)
    _set(_in_hue_range(h_deg, 45, 65) & (s > 0.3), 1.0)
    _set(_in_hue_range(h_deg, 80, 160) & (s > 0.2), 1.0)
    _set(_in_hue_range(h_deg, 345, 45) & (s >= 0.15) & (v >= 0.2) & (v <= 0.65), 0.0)

    valid = alpha_valid & matched
    return group, valid


def _load_done():
    done = set()
    kept = []
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
                if row.get("schema_version") == SCHEMA_VERSION:
                    done.add(row["synop_timestamp"])
                    kept.append(line)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
    return done


def main():
    with open(IN_FILE, "r", encoding="utf-8") as f:
        all_entries = [json.loads(line) for line in f if line.strip()]
    entries = [e for e in all_entries if e["expected_group"] in (0, 2)]

    done = _load_done()
    mask = _radius_mask(RADIUS_KM)

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in entries:
            ts = entry["synop_timestamp"]
            if ts in done:
                skipped += 1
                continue
            try:
                arr = fc.fetch_tile(LAYER_TYPE, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            fractions = {}
            any_valid = False
            for s_max in S_MAX_GRID:
                group, valid = _classify_type_with_blueice_smax(arr, s_max)
                roi_valid = valid & mask
                total = int(roi_valid.sum())
                key = "baseline" if s_max is None else str(s_max)
                if total == 0:
                    fractions[key] = None
                    continue
                any_valid = True
                fractions[key] = round(float((group[roi_valid] >= 1).mean()), 4)

            if not any_valid:
                failed += 1
                print(f"  [FAIL] {ts}: пустой ROI")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "expected_group": entry["expected_group"],
                "fractions_by_smax": fractions,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            print(f"  [OK] {ts} expected={entry['expected_group']} fractions={fractions}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
