"""
calibration_type_collect.py — сбор калибровочного датасета для Cloud Type
RGB (mtg_fd:rgb_cloudtype, _classify_type() в eumetsat_cloud_phase_type.py)
по историческим SYNOP-срокам станции 33837.

Третий канал в очереди калибровки (после GeoColour день и ИК, оба закрыты
2026-08-11). ПРИОРИТЕТ Type перед Phase обоснован: `confirmed` в
target_confirmation считается по Type (`roi_type > 0`), а Phase сейчас
чисто описательное поле, на голосование не влияет (см.
docs/topics/eumetsat.md).

Выборка (data/calibration_type_sample.json) — ОТДЕЛЬНАЯ от
calibration_geocolour_sample.json (та была стратифицирована по N,
непригодна для калибровки типа — см. запись "пробел — стратификация
только по N не покрывает типы облаков"). Здесь — 200 сроков,
стратифицированных по ОЖИДАЕМОЙ группе Type (0/1/2), выведенной из
SYNOP CL/CM/CH:
  - expected_group=0 (безоблачно): N==0
  - expected_group=2 (плотная/высокая): CH>=1 (любое высокое облако, вкл.
    тонкие перистые — таково же намерение production-кода, там
    "голубовато-белый: перистые" маппится в group=2.0), ИЛИ CL in {3,9}
    (кучево-дождевые), ИЛИ CM==2 (слоисто-дождевые/плотные высоко-слоистые)
  - expected_group=1 (низкая-средняя): остальное (N>0, но без признаков
    высокой/плотной облачности)
Внутри group1/group2 — round-robin по коду CL, чтобы не перекоситься на
самый частый код. Только ДНЕВНЫЕ сроки (Type RGB работает только днём,
ночью production переключается на Fog/Dust — другой слой/логика, не
здесь).

Для каждого срока:
  - тянет mtg_fd:rgb_cloudtype на TIME=<срок>
  - применяет ТЕКУЩИЙ каскад HSV-правил (_classify_type, БЕЗ изменений)
  - сэмплирует на нескольких радиусах (12/25/50/100км, тот же паттерн,
    что и у GeoColour) — какая доля пикселей ROI получила group>=1
    (облачно вообще) и group==2 (плотная/высокая), плюс
    unclassified_fraction (сколько пикселей не попало ни в одно правило —
    диагностика качества самих анкеров, из докстринга production-кода)
  - дописывает строку в data/calibration_type_synop.jsonl (append,
    idempotent)
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_cloud_phase_type import _classify_type, LAYER_TYPE  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_type_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_type_synop.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1
RADII_KM = [12, 25, 50, 100]


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
        samples = json.load(f)

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
                arr = fc.fetch_tile(LAYER_TYPE, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            group, matched_valid = _classify_type(arr)

            by_radius = {}
            any_valid = False
            for r, mask in masks_by_radius.items():
                valid_in_mask = matched_valid[mask]
                valid_px = int(valid_in_mask.sum())
                total_alpha_px = int((arr[:, :, 3][mask] > 0).sum())
                if total_alpha_px == 0:
                    by_radius[str(r)] = {"valid_px": 0}
                    continue
                any_valid = True
                group_roi = group[mask][valid_in_mask]
                by_radius[str(r)] = {
                    "valid_px": valid_px,
                    "total_alpha_px": total_alpha_px,
                    "unclassified_fraction": round(1 - valid_px / total_alpha_px, 4),
                    "group_ge1_fraction": round(float((group_roi >= 1).mean()), 4) if valid_px else None,
                    "group_eq2_fraction": round(float((group_roi == 2).mean()), 4) if valid_px else None,
                }

            if not any_valid:
                failed += 1
                print(f"  [FAIL] {ts}: пустой кадр (alpha=0 везде)")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_cl": entry["cl"],
                "synop_cm": entry["cm"],
                "synop_ch": entry["ch"],
                "expected_group": entry["expected_group"],
                "by_radius_km": by_radius,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            r25 = by_radius.get("25", {})
            print(
                f"  [OK] {ts} expected={entry['expected_group']} (CL={entry['cl']},CH={entry['ch']}) "
                f"ge1[25км]={r25.get('group_ge1_fraction')} eq2[25км]={r25.get('group_eq2_fraction')} "
                f"unclass={r25.get('unclassified_fraction')}"
            )
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
