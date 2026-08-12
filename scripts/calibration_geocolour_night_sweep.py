"""
calibration_geocolour_night_sweep.py — перебор порогов (v_min, s_max) для
НОЧНОЙ ветки _classify_cloud() (mtg_fd:rgb_geocolour):

    cloud = _in_hue_range(h, 180, 260) & (s > 0.06) & (v > 0.10)

Контекст (2026-08-12): в уже собранном data/calibration_geocolour_synop.jsonl
(197 сроков, мультирадиус, собран для дневной калибровки) оказалось 73
ночных строки (is_day=False, вычислено production fc.is_daytime — с
поправкой на UTC+3 Одессы, актуальной ошибке "день/ночь без +3ч" тут
взяться неоткуда). Анализ этих строк на r=25км (лучшая корреляция) дал:
  - mean cloud_fraction ТЕКУЩЕГО классификатора на N=0 (заведомо ясно) =
    0.40 — массовые ложные срабатывания, ночной порог слишком мягкий.
  - Средний V (яркость) в ROI монотонно растёт с N: 0.25 (N=0) -> 0.48
    (N=8-9). Средний S монотонно падает: 0.28 (N=0) -> 0.16 (N=8-9).
  - Средний H стабильно в диапазоне 178-190 (внутри текущего hue-фильтра
    180-260 почти всегда) — hue сам по себе не разделяет.
Значит V и S (в обратную сторону, верхняя граница) — рабочие рычаги, hue
трогать не нужно.

Метод (как и в дневной калибровке/type-свипе): для КАЖДОГО из 73 ночных
сроков (список — ночная часть data/calibration_geocolour_sample.json,
определяется через fc.is_daytime(ts), не через поле "day" в файле — то
поле использовалось только для ПЕРВОНАЧАЛЬНОЙ стратификации выборки и
теоретически могло быть неточным, см. docs/topics/eumetsat.md про баг
день/ночь без +3ч; is_day для АНАЛИЗА всегда пересчитывается заново
текущей production-функцией) тянет mtg_fd:rgb_geocolour ОДИН раз, считает
ПОЛНУЮ (ROI r=25км, площадную) cloud_fraction для сетки (v_min x s_max),
hue-фильтр и city_light-исключение — без изменений от production.

Результат — data/calibration_geocolour_night_sweep.jsonl, по строке на
срок: synop_n, synop_bucket, fractions по каждой комбинации (v_min,s_max).
Анализ (выбор итоговых порогов) — отдельно, не в этом скрипте.
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_geocolour_motion import _in_hue_range, LAYER_GEOCOLOUR  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_night_sweep.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 1
RADIUS_KM = 25

V_MIN_GRID = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]  # 0.10 = текущий production
S_MAX_GRID = [None, 0.30, 0.25, 0.20]  # None = текущий production (без верхней границы)


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _night_cloud_with_thresholds(rgba, v_min, s_max):
    """Копия ночной ветки _classify_cloud() — hue-диапазон и
    исключение городских огней (city_light) БЕЗ ИЗМЕНЕНИЙ, меняются
    только v_min (нижняя граница V) и s_max (новая верхняя граница S,
    если задана)."""
    alpha_valid = rgba[:, :, 3] > 0
    h, s, v = fc.rgb_to_hsv_vec(rgba[:, :, :3])

    city_light = _in_hue_range(h, 15, 70) & (s > 0.2) & (v > 0.25)

    cloud = _in_hue_range(h, 180, 260) & (s > 0.06) & (v > v_min)
    if s_max is not None:
        cloud = cloud & (s <= s_max)

    is_cloud = cloud & (~city_light) & alpha_valid
    return is_cloud, alpha_valid


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


def _grid_key(v_min, s_max):
    s_part = "none" if s_max is None else str(s_max)
    return f"v{v_min}_s{s_part}"


def main():
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    # is_day пересчитывается заново текущей production-функцией (с +3ч),
    # не берётся из поля "day" в файле выборки — см. докстринг выше.
    night_samples = [e for e in samples if not fc.is_daytime(e["timestamp"])]
    print(f"Ночных сроков в выборке: {len(night_samples)} из {len(samples)}")

    done = _load_done()
    mask = _radius_mask(RADIUS_KM)

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in night_samples:
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

            fractions = {}
            any_valid = False
            for v_min in V_MIN_GRID:
                for s_max in S_MAX_GRID:
                    is_cloud, alpha_valid = _night_cloud_with_thresholds(arr, v_min, s_max)
                    roi_valid = alpha_valid & mask
                    total = int(roi_valid.sum())
                    key = _grid_key(v_min, s_max)
                    if total == 0:
                        fractions[key] = None
                        continue
                    any_valid = True
                    fractions[key] = round(float(is_cloud[roi_valid].mean()), 4)

            if not any_valid:
                failed += 1
                print(f"  [FAIL] {ts}: пустой ROI")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "fractions": fractions,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            base_key = _grid_key(0.10, None)
            print(f"  [OK] {ts} N={entry['n']} ({entry['bucket']}) baseline={fractions.get(base_key)}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, уже было(пропущено)={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
