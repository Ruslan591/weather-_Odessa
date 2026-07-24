"""
eumetsat_geocolour_motion.py — независимая оценка направления/скорости
движения облачности по ТЕКСТУРЕ настоящего HD-снимка (mtg_fd:rgb_geocolour,
"натуральный цвет", тот же слой, что на официальном EUMETView), а не по
бинарной Cloud Mask.

ЗАЧЕМ ЭТО ОТДЕЛЬНО ОТ eumetsat_cloud_forecast.py:
Cloud Mask (msg_fes:clm) — плоское бинарное поле (ясно/облачно). Под
сплошной облачностью весь кадр становится однородным "облако", и phase
correlation не может найти сдвиг вообще (см. частые "скорость посчитать
не удалось (поле слишком однородно)" в eumetsat_cloud_forecast.py и
eumetsat_precip_forecast.py). У true-color снимка внутри самого облачного
покрова есть настоящая текстура (яркостные вариации верхней границы,
тени, гряды) — там, где маска слепа, у текстуры всё ещё есть за что
"зацепиться". Это должно давать оценку именно в тех случаях, когда
маска-метод не срабатывает — и, возможно, более точную (плотнее сигнал
для FFT-корреляции), см. смоук-тест на синтетике при разработке.

ОГРАНИЧЕНИЕ — ночь/сумерки: GeoColour это натуральный цвет, собранный из
видимых+ближних ИК каналов днём; ночью либо контраст резко падает, либо
слой переключается на ИК-прокси без той же текстуры. Разработано защитное
условие: если у кадра стандартное отклонение яркости ниже MIN_STD, кадр
считается "недостаточно контрастным" и пара кадров пропускается (не
портит оценку выдумкой). Если ни одна пара не прошла — честно репортим
"недоступно" (день/ночь на момент прогона неизвестен заранее, поэтому
не проверяем время суток напрямую, а измеряем реальный контраст).

Пишет data/eumetsat_geocolour_motion.json (простое дополнение к оценке
из eumetsat_cloud_forecast.py, не замена — там же остаётся ночестойкий
метод по Cloud Mask).
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_motion.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_motion_debug.json")

LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"
N_FRAMES = 4
STEP_MINUTES = 10
MIN_STD = 6.0  # порог контраста, см. докстринг; требует калибровки по живым данным


def main():
    debug = {}
    now = datetime.now(timezone.utc)
    times_iso = []
    for i in range(N_FRAMES - 1, -1, -1):
        if i == 0:
            times_iso.append(None)
        else:
            t = now - timedelta(minutes=STEP_MINUTES * i)
            times_iso.append(t.strftime("%Y-%m-%dT%H:%M:00.000Z"))

    arrs = []
    for t_iso in times_iso:
        try:
            arrs.append(fc.fetch_tile(LAYER_GEOCOLOUR, t_iso))
        except Exception as e:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_geocolour_motion.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(arrs)
    debug["times_requested"] = times_iso

    gray_frames = [fc.to_grayscale_luminance(a) for a in arrs]
    stds = [round(float(g.std()), 1) for g in gray_frames]
    debug["frame_std"] = stds

    vx, vy, n_pairs = fc.estimate_motion_continuous(gray_frames, STEP_MINUTES, min_std=MIN_STD)

    if vx is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valid": False,
            "verdict": "недостаточно контраста для оценки (вероятно, ночь/сумерки/сплошная засветка)",
            "frame_std": stds,
        }
    else:
        speed_kmh = math.hypot(vx, vy)
        bearing_v = (math.degrees(math.atan2(vx, vy)) + 360) % 360
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valid": True,
            "speed_kmh": round(speed_kmh, 1),
            "direction_compass": fc.compass(bearing_v),
            "bearing_deg": round(bearing_v, 0),
            "frame_pairs_used": n_pairs,
            "frame_std": stds,
        }

    out["method_note"] = (
        f"Оценка по текстуре яркости mtg_fd:rgb_geocolour ({N_FRAMES} кадра, шаг {STEP_MINUTES} мин, "
        f"phase correlation), НЕ по бинарной Cloud Mask — независимый метод, работает и под сплошной "
        f"облачностью (в отличие от clm), но недоступен при низком контрасте (порог std={MIN_STD}, "
        "не откалиброван по живым ночным данным). Это направление/скорость облачного массива в целом "
        "над окном ~190км вокруг точки, не привязано к конкретному краю/просвету."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_geocolour_motion.py: {out.get('verdict', out.get('speed_kmh'))}")


if __name__ == "__main__":
    main()
