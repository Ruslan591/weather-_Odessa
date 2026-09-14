"""
calibration_ir_collect.py — сбор калибровочного датасета для ИК-канала
(mtg_fd:ir105_hrfi, self-relative контрастный классификатор
MIN_CLOUD_CONTRAST_SIGMA в field_motion_common.py) по историческим
SYNOP-срокам станции 33837.

Второй канал в очереди калибровки (после GeoColour день, закрыт
2026-08-11 — см. docs/topics/eumetsat.md). ИК НЕ различает день/ночь
(тепловой канал, а не отражённый свет) — используем ВСЕ 200 сроков из
data/calibration_geocolour_sample.json (та же стратифицированная выборка,
что и для GeoColour — годится без изменений, там просто N-октанты и
timestamp, ничего специфичного для GeoColour).

Метод self-relative контраста принципиально другой, чем HSV-анкеры
GeoColour: sigma = (яркость_пикселя - медиана_кадра) / std_кадра,
"облако" = sigma >= порог. Порог — единственный параметр (нет отдельного
S/V, как у GeoColour), поэтому радиус ROI и сам порог sigma сэмплируются
СРАЗУ ВМЕСТЕ в одном проходе (дёшево — матрица sigma считается один раз
на кадр, дальше просто разные маски/пороги поверх неё, доп. сетевых
запросов не требует).

Радиусы: 12/25/50/100км (та же сетка, что у GeoColour мультирадиуса).
Пороги sigma: 0.5/0.8/1.0/1.2(текущий production)/1.5/1.8/2.2.

Результат — data/calibration_ir_synop.jsonl: on каждый кадр — вложенный
by_radius_km -> by_sigma_threshold -> cloud_fraction.
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_ir_motion import LAYER_IR105, STYLE_IR105  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_ir_synop.jsonl")
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


def _load_done_timestamps_and_prune_stale_schema():
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
                if row.get("schema_version") == SCHEMA_VERSION:
                    done.add(row["synop_timestamp"])
                    kept_lines.append(line)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            for line in kept_lines:
                f.write(line + "\n")
    return done


def main():
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)  # все 200 — и день, и ночь, ИК не различает

    done = _load_done_timestamps_and_prune_stale_schema()
    masks_by_radius = {r: _radius_mask(r) for r in RADII_KM}

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in samples:
            ts = entry["timestamp"]
            if ts in done:
                skipped += 1
                continue

            try:
                arr = fc.fetch_tile(LAYER_IR105, ts, retries=2, delay=3, style=STYLE_IR105, crs="EPSG:4326")
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            alpha_valid = arr[:, :, 3] > 0
            if alpha_valid.sum() == 0:
                failed += 1
                print(f"  [FAIL] {ts}: пустой кадр (alpha=0 везде)")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            gray = fc.to_grayscale_luminance(arr[:, :, :3])
            # frame_median/frame_std — по ВСЕМУ кадру (валидным пикселям), та
            # же формула, что и в production (eumetsat_ir_motion.py,
            # frame_median/frame_std_now) — self-relative контраст
            # определяется относительно всего видимого тайла, не относительно
            # ROI.
            valid_gray = gray[alpha_valid]
            frame_median = float(np.median(valid_gray))
            frame_std = float(valid_gray.std()) or 1.0
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
                    str(th): round(float((sigma_roi >= th).mean()), 4) for th in SIGMA_THRESHOLDS
                }
                by_radius[str(r)] = {"valid_px": valid_px, "by_sigma_threshold": by_threshold}

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "is_day": entry["day"],
                "frame_median": round(frame_median, 1),
                "frame_std": round(frame_std, 1),
                "by_radius_km": by_radius,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            f12 = by_radius.get("12", {}).get("by_sigma_threshold", {}).get("1.2")
            print(f"  [OK] {ts} N={entry['n']} ({entry['bucket']}) day={entry['day']} frac[12км,σ1.2(текущий)]={f12}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
