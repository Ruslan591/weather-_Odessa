"""
calibration_geocolour_collect.py — сбор калибровочного датасета для
GeoColour-классификатора (_classify_cloud() в eumetsat_geocolour_motion.py)
по историческим SYNOP-срокам станции 33837.

План согласован 2026-08-11 (см. docs/topics/eumetsat.md, раздел "решение —
калибровка по историческим SYNOP вместо накопления вживую"). GeoColour —
ПЕРВЫЙ канал в очереди (уже подтверждённый живой баг — 0% облачности при
явно облачном небе, см. запись 2026-08-11 про AND->OR фикс current_state).

Берёт список стратифицированных SYNOP-сроков из
data/calibration_geocolour_sample.json (200 сроков: N=0/1-2/3-5/6-7/8-9
октантов x день/ночь, по 20 каждая, отобраны из data/synop_2025.txt +
synop_2026.txt, парсинг группы Nddff после IIiii=33837). Для каждого срока:
  - тянет mtg_fd:rgb_geocolour на TIME=<срок> через fc.fetch_tile()
    (WMS nearestValue=1 сам подбирает ближайший доступный 10-минутный кадр,
    архив слоя подтверждён с 2024-09-23 — см. GetCapabilities, запрошено
    через Termux 2026-08-11)
  - применяет ТЕКУЩИЙ классификатор (_classify_cloud из
    eumetsat_geocolour_motion.py как есть, БЕЗ изменений) — датасет
    содержит решение старого порога, удобно сравнить до/после калибровки
  - сэмплирует RGB/HSV статистику и долю облачных пикселей текущего
    классификатора СРАЗУ НА НЕСКОЛЬКИХ РАДИУСАХ (12/25/50/100км) от
    станции, не только на фиксированных 12км (STATE_RADIUS_KM production-
    кода). Причина: SYNOP N — это доля купола неба, которую наблюдатель
    видит целиком (включая горизонт), а не узкое пятно прямо над головой —
    физически облако на высоте ~2км под углом 10° над горизонтом видно
    уже с ~11км, под 5° — с ~23км. Какой радиус реально коррелирует с N,
    заранее не очевидно (12км взят по инерции из другой задачи, см.
    docs/topics/eumetsat.md запись 2026-08-02 — там критерий был другой,
    "что видно на конкретном скриншоте", не сверка с SYNOP). Решаем это
    эмпирически на собранном датасете, не предположением.
  - дописывает строку в data/calibration_geocolour_synop.jsonl (append,
    idempotent — уже собранные timestamp с ТЕКУЩЕЙ версией схемы
    (schema_version=2, мультирадиус) пропускаются при повторном запуске;
    старые однорадиусные строки от первого прогона 2026-08-11
    автоматически пересобираются заново под новую схему)

Ручной запуск (workflow_dispatch, .github/workflows/calibration_geocolour.yml),
НЕ часть обычного пайплайна, не гейтится по времени. Вежливая пауза между
запросами — не долбить публичный WMS EUMETSAT пачкой из 200 запросов подряд.
"""

import json
import os
import sys
import time as _time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_geocolour_motion import _classify_cloud, _is_daytime, LAYER_GEOCOLOUR  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_synop.jsonl")
REQUEST_DELAY_SECONDS = 0.4
SCHEMA_VERSION = 2
RADII_KM = [12, 25, 50, 100]


def _radius_mask(radius_km):
    """Круглая маска вокруг станции произвольного радиуса — та же
    геометрия (центр/шаг), что и fc.station_area_mask()/local_area_mask(),
    просто не жёстко зашитая под один радиус."""
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _load_done_timestamps_and_prune_old_schema():
    """Строки с ТЕКУЩЕЙ версией схемы (мультирадиус) — уже готовы,
    пропускаем. Строки старой (однорадиусной) схемы от первого прогона
    2026-08-11 — выкидываем из файла целиком (переписываем файл начисто
    без них), чтобы не копить вперемешку две несовместимые по полям
    версии одной и той же строки на один timestamp."""
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

    done_timestamps = _load_done_timestamps_and_prune_old_schema()
    masks_by_radius = {r: _radius_mask(r) for r in RADII_KM}

    ok, skipped, failed = 0, 0, 0
    with open(OUT_FILE, "a", encoding="utf-8") as out_f:
        for entry in samples:
            ts = entry["timestamp"]
            if ts in done_timestamps:
                skipped += 1
                continue

            try:
                arr = fc.fetch_tile(LAYER_GEOCOLOUR, ts, retries=2, delay=3)
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {ts}: {e}")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            is_day = _is_daytime(ts)
            is_cloud, alpha_valid = _classify_cloud(arr, is_day)
            h, s, v = fc.rgb_to_hsv_vec(arr[:, :, :3])
            rgb = arr[:, :, :3]

            by_radius = {}
            any_valid = False
            for r, mask in masks_by_radius.items():
                valid_in_mask = alpha_valid[mask]
                valid_px = int(valid_in_mask.sum())
                if valid_px == 0:
                    by_radius[str(r)] = {"valid_px": 0}
                    continue
                any_valid = True
                # Та же формула, что и в production (station_state /
                # local trend в eumetsat_geocolour_motion.py) — is_cloud
                # уже включает alpha_valid внутри себя (_classify_cloud),
                # не фильтруем повторно.
                cloud_fraction = float(is_cloud[mask].mean())
                rgb_roi = rgb[mask][valid_in_mask]
                h_roi = h[mask][valid_in_mask]
                s_roi = s[mask][valid_in_mask]
                v_roi = v[mask][valid_in_mask]
                by_radius[str(r)] = {
                    "valid_px": valid_px,
                    "cloud_fraction_current_classifier": round(cloud_fraction, 4),
                    "rgb_mean": [round(float(rgb_roi[:, i].mean()), 1) for i in range(3)],
                    "hsv_mean": [
                        round(float(h_roi.mean()), 3),
                        round(float(s_roi.mean()), 3),
                        round(float(v_roi.mean()), 3),
                    ],
                }

            if not any_valid:
                failed += 1
                print(f"  [FAIL] {ts}: ни один радиус не дал валидных пикселей (alpha=0, вне охвата кадра)")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            row = {
                "schema_version": SCHEMA_VERSION,
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "is_day": is_day,
                "by_radius_km": by_radius,
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            frac_12 = by_radius.get("12", {}).get("cloud_fraction_current_classifier")
            frac_100 = by_radius.get("100", {}).get("cloud_fraction_current_classifier")
            print(
                f"  [OK] {ts} N={entry['n']} ({entry['bucket']}) day={is_day} "
                f"cloud_frac[12км]={frac_12} cloud_frac[100км]={frac_100}"
            )
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, уже было(пропущено)={skipped}, ошибок={failed}")
    if failed > len(samples) * 0.3:
        print("::warning::Больше 30% сроков не удалось получить — возможно, проблема с сетью/WMS")


if __name__ == "__main__":
    main()
