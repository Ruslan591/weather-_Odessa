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
  - сэмплирует RGB/HSV статистику в радиусе 12км от станции
    (fc.station_area_mask(), тот же радиус, что использует production-код
    для station_state/current_state)
  - дописывает строку в data/calibration_geocolour_synop.jsonl (append,
    idempotent — уже собранные timestamp пропускаются при повторном запуске)

Ручной запуск (workflow_dispatch, .github/workflows/calibration_geocolour.yml),
НЕ часть обычного пайплайна, не гейтится по времени. Вежливая пауза между
запросами — не долбить публичный WMS EUMETSAT пачкой из 200 запросов подряд.
"""

import json
import os
import sys
import time as _time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_geocolour_motion import _classify_cloud, _is_daytime, LAYER_GEOCOLOUR  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_sample.json")
OUT_FILE = os.path.join(BASE_DIR, "data", "calibration_geocolour_synop.jsonl")
REQUEST_DELAY_SECONDS = 0.4


def _load_done_timestamps():
    done = set()
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    done.add(row["synop_timestamp"])
                except Exception:
                    continue
    return done


def main():
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    done_timestamps = _load_done_timestamps()
    state_mask = fc.station_area_mask()

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

            valid_in_mask = alpha_valid[state_mask]
            valid_px = int(valid_in_mask.sum())
            if valid_px == 0:
                failed += 1
                print(f"  [FAIL] {ts}: ROI без валидных пикселей (alpha=0, вероятно, вне охвата кадра)")
                _time.sleep(REQUEST_DELAY_SECONDS)
                continue

            # Та же формула, что и в production (station_state в
            # eumetsat_geocolour_motion.py) — is_cloud уже включает
            # alpha_valid внутри себя (см. _classify_cloud), не фильтруем
            # повторно, чтобы число было 1-в-1 сравнимо с тем, что реально
            # показывалось бы на странице в этот момент.
            roi_cloud_fraction_current = float(is_cloud[state_mask].mean())

            # RGB/HSV статистика — только по валидным (непрозрачным)
            # пикселям ROI, иначе прозрачные пиксели (RGB обычно 0,0,0)
            # исказили бы средние цвета.
            rgb_roi_all = arr[:, :, :3][state_mask]
            rgb_roi = rgb_roi_all[valid_in_mask]
            h, s, v = fc.rgb_to_hsv_vec(arr[:, :, :3])
            h_roi = h[state_mask][valid_in_mask]
            s_roi = s[state_mask][valid_in_mask]
            v_roi = v[state_mask][valid_in_mask]

            row = {
                "synop_timestamp": ts,
                "synop_n": entry["n"],
                "synop_bucket": entry["bucket"],
                "is_day": is_day,
                "valid_px": valid_px,
                "roi_cloud_fraction_current_classifier": round(roi_cloud_fraction_current, 4),
                "rgb_mean": [round(float(rgb_roi[:, i].mean()), 1) for i in range(3)],
                "rgb_std": [round(float(rgb_roi[:, i].std()), 1) for i in range(3)],
                "hsv_mean": [
                    round(float(h_roi.mean()), 3),
                    round(float(s_roi.mean()), 3),
                    round(float(v_roi.mean()), 3),
                ],
            }
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            print(
                f"  [OK] {ts} N={entry['n']} ({entry['bucket']}) day={is_day} "
                f"cloud_frac(текущий классификатор)={row['roi_cloud_fraction_current_classifier']}"
            )
            _time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Готово: собрано={ok}, уже было(пропущено)={skipped}, ошибок={failed}")
    if failed > len(samples) * 0.3:
        print("::warning::Больше 30% сроков не удалось получить — возможно, проблема с сетью/WMS")


if __name__ == "__main__":
    main()
