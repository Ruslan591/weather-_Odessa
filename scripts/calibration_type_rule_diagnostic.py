"""
calibration_type_rule_diagnostic.py — диагностика: КАКОЕ ИМЕННО правило
каскада _classify_type() (см. eumetsat_cloud_phase_type.py) ложно
срабатывает на заведомо ясном небе.

Контекст: первый прогон calibration_type_collect.py (139/200 сроков)
показал слабую корреляцию с synop_n (Spearman rho~0.21-0.26 на всех
радиусах — заметно хуже GeoColour 0.66 и ИК 0.25) и, что важнее,
СИСТЕМАТИЧЕСКИЙ ложноположительный результат на N=0 (ясно): средняя доля
group>=1 ("облачно") на радиусе 25км — 0.319 (медиана 0.394), хотя должно
быть ~0. Первое правило каскада (v<0.22 -> group=0 "безоблачно, тёмное
море") НЕ ловит достаточно пикселей ясного неба — значит реальный цвет
ясного неба/моря в Cloud Type RGB композите ярче v=0.22 и утекает в одно
из последующих "облачных" правил. Нужно понять, в какое именно, чтобы
осмысленно двигать порог (не наугад, как в geocolour/ir sweep, где
менялся один скалярный порог, а тут сначала нужна атрибуция по правилам).

Метод: копирует каскад _classify_type() ПОШАГОВО (без изменений порогов),
но вместо единого group возвращает ID сработавшего правила (0..8) или -1
(ничего не подошло). Прогоняется ТОЛЬКО на N=0 срока (заведомо ясное небо
по SYNOP) из уже собранного data/calibration_type_synop.jsonl (41 штука) —
переиспользует те же timestamp'ы, повторный сетевой фетч тех же кадров
(дёшево, 41 запрос). Считает на радиусе 25км (тот же, что дал лучшую
корреляцию у GeoColour) долю каждого правила.

Результат — data/calibration_type_rule_diagnostic.jsonl, по одной строке
на срок: synop_timestamp, fired_rule_fraction (rule_id -> доля пикселей
ROI), dominant_rule (самое частое непустое правило).

Анализ (какое правило чаще всего ложно ловит ясное небо, и какой у него
реальный HSV-профиль на этих пикселях) — делается отдельно после сбора,
не в этом скрипте.
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
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_type_rule_diagnostic.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1
RADIUS_KM = 25

# Те же правила и тот же порядок, что в eumetsat_cloud_phase_type.py::_classify_type,
# просто с именем/id вместо прямого присвоения group — НИЧЕГО не меняем в порогах.
RULES = [
    ("dark_clear", lambda h, s, v: v < 0.22),
    ("white_dense", lambda h, s, v: (s < 0.18) & (v > 0.80)),
    ("violet_storm", lambda h, s, v: _in_hue_range(h, 265, 300) & (s > 0.25)),
    ("pink_convection", lambda h, s, v: _in_hue_range(h, 300, 345) & (s > 0.25)),
    ("bright_red_coldtop", lambda h, s, v: _in_hue_range(h, 345, 15) & (s > 0.4) & (v > 0.65)),
    ("blue_ice", lambda h, s, v: _in_hue_range(h, 215, 245) & (s > 0.25)),
    ("cyan_cirrus", lambda h, s, v: _in_hue_range(h, 180, 215) & (s >= 0.15) & (s <= 0.5)),
    ("yellow_mid", lambda h, s, v: _in_hue_range(h, 45, 65) & (s > 0.3)),
    ("green_low", lambda h, s, v: _in_hue_range(h, 80, 160) & (s > 0.2)),
    ("brown_land_clear", lambda h, s, v: _in_hue_range(h, 345, 45) & (s >= 0.15) & (v >= 0.2) & (v <= 0.65)),
]


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _classify_with_rule_id(rgba):
    alpha_valid = rgba[:, :, 3] > 0
    h_deg, s, v = _rgb_to_hsv_vec(rgba[:, :, :3])
    rule_id = np.full(h_deg.shape, -1, dtype=np.int16)
    matched = np.zeros(h_deg.shape, dtype=bool)
    for idx, (_name, fn) in enumerate(RULES):
        mask = fn(h_deg, s, v) & (~matched)
        rule_id = np.where(mask, idx, rule_id)
        matched = matched | mask
    return rule_id, alpha_valid, h_deg, s, v


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
        n0_timestamps = [
            json.loads(line)["synop_timestamp"]
            for line in f
            if line.strip() and json.loads(line)["expected_group"] == 0
        ]

    done = _load_done()
    mask = _radius_mask(RADIUS_KM)

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for ts in n0_timestamps:
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

            rule_id, alpha_valid, h_deg, s, v = _classify_with_rule_id(arr)
            roi_valid = alpha_valid & mask
            total = int(roi_valid.sum())
            if total == 0:
                failed += 1
                print(f"  [FAIL] {ts}: пустой ROI")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            roi_rule = rule_id[roi_valid]
            fired_fraction = {}
            for idx, (name, _fn) in enumerate(RULES):
                frac = float((roi_rule == idx).mean())
                if frac > 0:
                    fired_fraction[name] = round(frac, 4)
            unmatched_frac = float((roi_rule == -1).mean())
            if unmatched_frac > 0:
                fired_fraction["_unmatched"] = round(unmatched_frac, 4)

            dominant = max(fired_fraction, key=fired_fraction.get) if fired_fraction else None

            # HSV-профиль пикселей, попавших в самое частое ОБЛАЧНОЕ (не dark_clear/
            # brown_land_clear) правило — чтобы понять, куда реально сдвигать порог.
            cloud_rule_names = {name for name, _ in RULES} - {"dark_clear", "brown_land_clear"}
            cloud_mask = roi_valid.copy()
            cloud_mask &= np.isin(rule_id, [i for i, (n, _f) in enumerate(RULES) if n in cloud_rule_names])
            hsv_profile = None
            if cloud_mask.sum() > 0:
                hsv_profile = {
                    "h_mean": round(float(h_deg[cloud_mask].mean()), 1),
                    "s_mean": round(float(s[cloud_mask].mean()), 3),
                    "v_mean": round(float(v[cloud_mask].mean()), 3),
                    "px_count": int(cloud_mask.sum()),
                }

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "radius_km": RADIUS_KM,
                "total_roi_px": total,
                "fired_rule_fraction": fired_fraction,
                "dominant_rule": dominant,
                "false_cloud_hsv_profile": hsv_profile,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            print(f"  [OK] {ts} dominant={dominant} fractions={fired_fraction}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
