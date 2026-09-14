"""
calibration_type_blueice_cloudy_profile.py — HSV-профиль пикселей,
попавших в правило "blue_ice" (Hue 215-245, S>0.25) КАСКАДА
_classify_type(), но на срока с РЕАЛЬНОЙ высокой/ледяной облачностью
(expected_group=2, из calibration_type_sample.json) — для сравнения с
уже полученным профилем ложных срабатываний на ясном небе (N=0, см.
calibration_type_rule_diagnostic.py / docs/topics/eumetsat.md).

Контекст: диагностика на N=0 (2026-08-12) показала, что правило blue_ice
— главный источник ложных срабатываний (unconditional mean 0.201 площади
ROI на ЯСНОМ небе), профиль ложных пикселей: Hue~227-243°, S~0.49-0.77,
V~0.24-0.54 (медиана V=0.357). У правила blue_ice в production-коде НЕТ
нижнего порога по V — ловит любой насыщенный синий, включая тёмное синее
море. Гипотеза: настоящие высокие/ледяные облака в этом же Hue-диапазоне
ЯРЧЕ (выше V), чем тёмное синее море — если так, можно добавить v_min в
правило blue_ice и разделить два случая по яркости, не трогая Hue/S.

Метод: берёт expected_group=2 сроки из calibration_type_synop.jsonl (уже
собраны), для каждого — рассчитывает HSV, находит пиксели, подходящие
именно под blue_ice-условие (Hue 215-245 & S>0.25, БЕЗ учёта порядка
каскада — на этих сроках интересен именно этот диапазон, не итоговый
group), считает их H/S/V статистику в ROI 25км. Пишет
data/calibration_type_blueice_cloudy_profile.jsonl.
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
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_type_blueice_cloudy_profile.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1
RADIUS_KM = 25


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


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
        g2_entries = [
            json.loads(line)
            for line in f
            if line.strip() and json.loads(line)["expected_group"] == 2
        ]

    done = _load_done()
    mask = _radius_mask(RADIUS_KM)

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in g2_entries:
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

            alpha_valid = arr[:, :, 3] > 0
            h_deg, s, v = _rgb_to_hsv_vec(arr[:, :, :3])
            blue_mask = _in_hue_range(h_deg, 215, 245) & (s > 0.25) & alpha_valid & mask

            roi_valid_total = int((alpha_valid & mask).sum())
            if roi_valid_total == 0:
                failed += 1
                print(f"  [FAIL] {ts}: пустой ROI")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            blue_count = int(blue_mask.sum())
            profile = None
            if blue_count > 0:
                profile = {
                    "h_mean": round(float(h_deg[blue_mask].mean()), 1),
                    "s_mean": round(float(s[blue_mask].mean()), 3),
                    "v_mean": round(float(v[blue_mask].mean()), 3),
                    "v_median": round(float(np.median(v[blue_mask])), 3),
                    "px_count": blue_count,
                }

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "radius_km": RADIUS_KM,
                "synop_cl": entry.get("synop_cl"),
                "synop_cm": entry.get("synop_cm"),
                "synop_ch": entry.get("synop_ch"),
                "roi_valid_total": roi_valid_total,
                "blue_ice_rule_fraction": round(blue_count / roi_valid_total, 4),
                "blue_ice_hsv_profile": profile,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            print(f"  [OK] {ts} CH={entry.get('synop_ch')} blue_frac={row['blue_ice_rule_fraction']} profile={profile}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
