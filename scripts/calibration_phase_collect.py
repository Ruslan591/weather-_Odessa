"""
calibration_phase_collect.py — сбор калибровочных данных для Phase RGB
(mtg_fd:rgb_cloudphase, _classify_phase() в eumetsat_cloud_phase_type.py).

Контекст: в отличие от GeoColour/ИК (детекторы ПРИСУТСТВИЯ облака,
достаточно стратификации по общей облачности N) и Type RGB (грубая
3-группная плотность/высота, тоже калибровалась по N — задним числом
признано неидеальным решением, см. docs/topics/eumetsat.md запись
"пробел — стратификация только по N не покрывает типы облаков"), Phase
RGB классифицирует именно ТИП/ФАЗУ облака (9 категорий, см.
PHASE_LABELS) — для этого нужен ground truth по ТИПУ, а не только по
доле покрытия. Источник — группа SYNOP-телеграммы `8NhCLCMCH`
(CL/CM/CH — коды ВМО таблиц 0513/0515/0509, жанр облаков по ярусам).

Парсер группы 8 портирован 1:1 с эталонной реализацией `synop.js`
(позиционный разбор: iRIXhVV/Nddff — фиксированные позиции сразу после
станции, пропускаются безусловно; группа 8 ищется по ведущей цифре в
основном теле, с fallback на секцию 333, если в основном теле её нет).
ВАЖНО (найдено при подготовке выборки): группа Nddff тоже может
начинаться с цифры '8', когда общая облачность N=8 октантов — наивный
regex-поиск любого токена "8dddd" даёт ложные срабатывания, позиционный
разбор обязателен.

Карта CL/CM/CH -> 9 категорий Phase RGB (PHASE_LABELS) построена по
таблицам ВМО 0513/0515/0509, приоритет: Cb (CL=3 калвус/CL=9
капилятус) выше любого яруса (вертикальная конвекция доминирует в кадре
независимо от CM/CH) > самый верхний непустой ярус (спутник видит
вершину облака, нижние ярусы визуально перекрыты). Категория 0
(безоблачно) НЕ выводится из CL=CM=CH=0 — при истинно ясном небе
наблюдатели обычно вообще не репортуют группу 8 (прочерк, а не "000"),
поэтому ground truth для "безоблачно" берётся из общей облачности N=0
(группа Nddff, всегда присутствует), не из группы 8.

Выборка — `data/calibration_phase_sample.json` (192 срока, 2023-2026,
только дневные по `fc.is_daytime()`, стратифицированы по итоговому
ordinal, ~20-25 на категорию где хватает данных; категории 3 [плотная
водяная, 20 доступно], 6 [смешанная фаза, всего 5 доступно], 8 [гроза,
17 доступно] — тоньше остальных, это реальный дефицит наблюдений в
архиве Одессы за 4 года, не баг выборки).

Метод сбора идентичен calibration_type_collect.py: WMS-тайл на момент
SYNOP, `_classify_phase()` без изменений, площадная статистика по
радиусам 12/25/50/100км — НЕ доля "облачно/не облачно" (как у Type), а
доля площади, совпавшей С ОЖИДАЕМЫМ ordinal (accuracy), плюс полное
распределение по всем 9 категориям (для анализа, куда именно "утекают"
ошибочные пиксели).
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_cloud_phase_type import _classify_phase, LAYER_PHASE, PHASE_LABELS  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_phase_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_phase_synop.jsonl")
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
        sample = json.load(f)

    done = _load_done()
    masks = {r: _radius_mask(r) for r in RADII_KM}

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in sample:
            ts = entry["synop_timestamp"]
            if ts in done:
                skipped += 1
                continue
            try:
                arr = fc.fetch_tile(LAYER_PHASE, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            ordinal, valid = _classify_phase(arr)

            by_radius = {}
            for r_km, mask in masks.items():
                roi_valid = valid & mask
                total = int(roi_valid.sum())
                if total == 0:
                    by_radius[str(r_km)] = {
                        "valid_px": 0, "total_alpha_px": int((arr[:, :, 3] > 0).sum()),
                        "accuracy": None, "ordinal_distribution": None,
                    }
                    continue
                roi_ord = ordinal[roi_valid]
                dist = {}
                for k in range(9):
                    frac = float((roi_ord == float(k)).mean())
                    if frac > 0:
                        dist[str(k)] = round(frac, 4)
                accuracy = dist.get(str(entry["expected_phase_ordinal"]), 0.0)
                by_radius[str(r_km)] = {
                    "valid_px": total,
                    "total_alpha_px": int((arr[:, :, 3] > 0).sum()),
                    "accuracy": round(accuracy, 4),
                    "ordinal_distribution": dist,
                }

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "expected_phase_ordinal": entry["expected_phase_ordinal"],
                "expected_phase_label": PHASE_LABELS[entry["expected_phase_ordinal"]],
                "source_codes": {"CL": entry.get("CL"), "CM": entry.get("CM"), "CH": entry.get("CH")},
                "by_radius_km": by_radius,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            acc25 = by_radius.get("25", {}).get("accuracy")
            print(f"  [OK] {ts} expected={entry['expected_phase_ordinal']}"
                  f"({PHASE_LABELS[entry['expected_phase_ordinal']]}) acc[25km]={acc25}")
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, пропущено={skipped}, ошибок={failed}")


if __name__ == "__main__":
    main()
