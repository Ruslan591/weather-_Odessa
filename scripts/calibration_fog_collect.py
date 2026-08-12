"""
calibration_fog_collect.py — сбор калибровочного датасета для Fog RGB
(mtg_fd:rgb_fog, LAYER_NIGHT_A в eumetsat_cloud_phase_type.py, ночная
замена Phase RGB, self-relative контрастный классификатор
_classify_contrast()) по историческим SYNOP-срокам станции 33837.

Пятый канал в очереди калибровки (после GeoColour день/ИК/Type RGB/
GeoColour ночь — все закрыты, см. docs/topics/eumetsat.md). Решение
2026-08-12: калибруем Fog раньше Dust — более общий канал (по описанию
EUMETSAT несёт cloud top temperature/optical thickness/phase, не только
туман), плюс уже частично копится отдельный append-only лог
(data/fog_calibration_log.jsonl, с 2026-08-04).

Метод (_classify_contrast в eumetsat_cloud_phase_type.py) — ТОТ ЖЕ self-
relative контраст, что уже откалиброван для ИК, но СИММЕТРИЧНЫЙ (|sigma|,
не sigma) и на другой формуле яркости (среднее RGB/255, не luminance-
взвешенная, как у ИК/to_grayscale_luminance):
    gray = mean(R,G,B)/255; sigma = (gray - median_кадра) / std_кадра
    "сигнал" = |sigma| >= порог
Единственный параметр — sigma_threshold (production сейчас: 1.0,
подобран без калибровки). Только НОЧНАЯ часть выборки (Fog RGB —
ночная замена, днём канал не используется в этой роли) — используется
ночной срез data/calibration_geocolour_sample.json, is_day пересчитывается
заново через fc.is_daytime() (та же практика, что и в ночном GeoColour-
свипе 2026-08-12 — НЕ берём поле "day" из файла напрямую).

Радиусы: 12/25/50/100км (та же сетка, что у остальных калибровок).
Пороги sigma: 0.5/0.8/1.0(текущий production)/1.2/1.5/1.8/2.2.

Результат — data/calibration_fog_synop.jsonl: on каждый кадр — вложенный
by_radius_km -> by_sigma_threshold -> cloud_fraction (доля |sigma>=порог|
пикселей в ROI).
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_cloud_phase_type import LAYER_NIGHT_A  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_fog_synop.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1

RADII_KM = [12, 25, 50, 100]
SIGMA_THRESHOLDS = [0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2]


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
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    # is_day пересчитывается заново текущей production-функцией (с +3ч
    # Одессы) — не берём поле "day" из файла, та же практика, что и в
    # ночном GeoColour-свипе 2026-08-12.
    night_samples = [e for e in samples if not fc.is_daytime(e["timestamp"])]
    print(f"Ночных сроков в выборке: {len(night_samples)} из {len(samples)}")

    done = _load_done()
    masks_by_radius = {r: _radius_mask(r) for r in RADII_KM}

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in night_samples:
            ts = entry["timestamp"]
            if ts in done:
                skipped += 1
                continue

            try:
                arr = fc.fetch_tile(LAYER_NIGHT_A, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            alpha_valid = arr[:, :, 3] > 0
            if alpha_valid.sum() < 10:
                failed += 1
                print(f"  [FAIL] {ts}: пустой/почти пустой кадр (alpha)")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            # Та же формула, что в _classify_contrast() production-кода —
            # среднее RGB/255, НЕ luminance-взвешенная яркость ИК.
            gray = arr[:, :, :3].astype(np.float32).mean(axis=2) / 255.0
            valid_gray = gray[alpha_valid]
            frame_median = float(np.median(valid_gray))
            frame_std = float(valid_gray.std()) or 1e-6
            sigma_map = (gray - frame_median) / frame_std

            by_radius = {}
            for r, mask in masks_by_radius.items():
                valid_in_mask = alpha_valid[mask]
                valid_px = int(valid_in_mask.sum())
                if valid_px == 0:
                    by_radius[str(r)] = {"valid_px": 0}
                    continue
                sigma_roi = sigma_map[mask][valid_in_mask]
                by_threshold = {
                    str(th): round(float((np.abs(sigma_roi) >= th).mean()), 4)
                    for th in SIGMA_THRESHOLDS
                }
                by_radius[str(r)] = {"valid_px": valid_px, "by_sigma_threshold": by_threshold}

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "frame_median": round(frame_median, 4),
                "frame_std": round(frame_std, 4),
                "by_radius_km": by_radius,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            f25 = by_radius.get("25", {}).get("by_sigma_threshold", {}).get("1.0")
            print(f"  [OK] {ts} N={entry['n']} ({entry['bucket']}) frac[25км,σ1.0(текущий)]={f25}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, уже было(пропущено)={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
