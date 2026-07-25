"""
eumetsat_ir_motion.py — независимая оценка направления/скорости движения
облачности по ТЕПЛОВОМУ ИК-каналу (msg_fes:ir108, 10.8 мкм), а не по
бинарной Cloud Mask и НЕ по true-color GeoColour.

ПОЧЕМУ ИК, А НЕ GEOCOLOUR (естественный цвет):
Изначально для текстурного анализа использовался mtg_fd:rgb_geocolour
(true-color). Проблема обнаружилась ночью: GeoColour ночью показывает не
чёрный кадр, а огни городов (яркие неподвижные точки). Phase correlation —
это нормированная корреляция ПО ФАЗЕ, она инвариантна к амплитуде, поэтому
попытка просто размыть/обрезать яркость огней не помогает (проверено на
синтетике) — неподвижные огни всё равно "перетягивают" результат к
ложному "скорость ~0". Медианный фильтр (despeckle, см.
field_motion_common.py) частично лечит это, стирая точечные выбросы, но
это по-прежнему заплатка поверх физически "грязного" источника.

ИК-канал 10.8 мкм — это яркостная температура верхней границы облака
(тепловое излучение), а не отражённый видимый свет. Города физически не
светятся в этом диапазоне сколько-нибудь заметно на фоне облаков — весь
класс "точечные огни ночью" просто не существует как артефакт. Канал
работает одинаково днём и ночью (в этом весь смысл ИК-каналов на
метеоспутниках). Это же стандартный метод, которым метеослужбы официально
считают "Atmospheric Motion Vectors" — трекинг облачных структур по ИК
между последовательными кадрами геостационара.

despeckle (median_filter) в estimate_motion_continuous() оставлен как
общая защита от единичных шумовых пикселей матрицы — на ИК он не должен
почти ничего менять (нет точечных огней), но и не мешает.

N_FRAMES=4, шаг 10 мин (msg_fes:ir108 обновляется раз в 10 мин).

Пишет data/eumetsat_ir_motion.json.
"""

import json
import math
import os

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion_debug.json")

LAYER_IR108 = "msg_fes:ir108"
N_FRAMES = 4
STEP_MINUTES = 15  # ВАЖНО: msg_fes-семейство (как h60b/clm/cth) обновляется
                    # раз в 15 мин, НЕ 10 — 10 было скопировано с mtg_fd:rgb_geocolour
                    # при переключении слоя и не поправлено. При шаге 10 часть
                    # запрошенных таймстемпов (реальных сцен раз в 15 мин ещё нет)
                    # снэпилась сервером на ОДИН И ТОТ ЖЕ реальный снимок —
                    # отсюда были задублированные кадры и застрявший 0 км/ч,
                    # а вовсе не проблема ИК-канала как такового.
MIN_STD = 6.0  # порог контраста; требует калибровки по живым данным (см. геоколур-версию)


def main():
    debug = {}
    now = fc.datetime.now(fc.timezone.utc)
    times_iso = fc.build_time_steps(STEP_MINUTES, N_FRAMES)

    arrs = []
    for t_iso in times_iso:
        try:
            arrs.append(fc.fetch_tile(LAYER_IR108, t_iso))
        except Exception as e:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_ir_motion.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(arrs)
    debug["times_requested"] = times_iso

    gray_frames = [fc.to_grayscale_luminance(a) for a in arrs]
    stds = [round(float(g.std()), 1) for g in gray_frames]
    # диагностика: доля пикселей, совпадающих БУКВАЛЬНО (в пределах шума) между
    # соседними кадрами — если близко к 1.0, сервер отдал дважды один и тот же
    # реальный снимок (несовпадение запрошенного шага с реальной частотой сцен),
    # а не "движения нет" в физическом смысле
    identical_fractions = []
    for i in range(len(gray_frames) - 1):
        diff = fc.np.abs(gray_frames[i] - gray_frames[i + 1])
        identical_fractions.append(round(float((diff < 0.5).mean()), 3))
    debug["identical_fraction_between_frames"] = identical_fractions
    debug["frame_std"] = stds

    vx, vy, n_pairs = fc.estimate_motion_continuous(gray_frames, STEP_MINUTES, min_std=MIN_STD)

    if vx is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valid": False,
            "verdict": "недостаточно контраста для оценки (однородная облачность/безоблачно по всему окну)",
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
        f"Оценка по текстуре яркостной температуры msg_fes:ir108 (10.8мкм, {N_FRAMES} кадра, шаг "
        f"{STEP_MINUTES} мин, phase correlation + despeckle), НЕ по бинарной Cloud Mask и НЕ по "
        "true-color снимку — ИК-канал работает одинаково днём и ночью, городские огни в нём не "
        "видны (это тепловое излучение, не отражённый свет), поэтому нет ночного артефакта, который "
        "был у GeoColour. Направление/скорость облачного массива в целом над окном ~190км вокруг "
        "точки, не привязано к конкретному краю/просвету."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_ir_motion.py: {out.get('verdict', out.get('speed_kmh'))}")


if __name__ == "__main__":
    main()
