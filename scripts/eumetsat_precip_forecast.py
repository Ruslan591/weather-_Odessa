"""
eumetsat_precip_forecast.py — мини-прогноз движения области ОСАДКОВ
(msg_fes:h60b, Blended SEVIRI/LEO MW precipitation) для Одессы: направление,
скорость, ближайший край (осадки/просвет), ETA, и (если сейчас без осадков и
рядом значимое поле) эвристическая вероятность, что оно принесёт осадки.

Метод идентичен eumetsat_cloud_forecast.py (см. field_motion_common.py),
только presence-классификация по прозрачности пикселя (alpha>0 = есть
осадки), а не по цветовым анкерам — у h60b нет 3 чётких цветов легенды,
но "0 осадков" в этом стиле рендерится прозрачным.

N_FRAMES=4, шаг 15 мин (msg_fes:h60b обновляется раз в 15 мин, как clm/cth).

Пишет data/eumetsat_precip_forecast.json.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_precip_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_precip_forecast_debug.json")

LAYER_H60B = "msg_fes:h60b"
N_FRAMES = 4
STEP_MINUTES = 15


def main():
    debug = {}
    now = datetime.now(timezone.utc)
    times_iso = fc.build_time_steps(STEP_MINUTES, N_FRAMES)

    arrs = []
    for t_iso in times_iso:
        try:
            arrs.append(fc.fetch_tile(LAYER_H60B, t_iso))
        except Exception as e:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_precip_forecast.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(arrs)
    debug["times_requested"] = times_iso

    classified = [fc.classify_presence_by_alpha(a) for a in arrs]
    presence_frames = [c[0] for c in classified]
    valid_frames = [c[1] for c in classified]
    presence_now = presence_frames[-1]
    valid_now = valid_frames[-1]

    center_idx = int((fc.TILE_SIZE - 1) / 2)
    currently_precip = bool(presence_now[center_idx, center_idx])
    want_precip_target = not currently_precip
    target_type = "precip_mass" if want_precip_target else "clearing"

    nearest = fc.nearest_of_type(presence_now, valid_now, want_precip_target)
    p_now = nearest[:2] if nearest is not None else None
    blob_area_km2 = nearest[2] if nearest is not None else None
    vx, vy, n_pairs = fc.estimate_motion(presence_frames, STEP_MINUTES)

    if p_now is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": "precip" if currently_precip else "no_precip",
            "target_type": target_type,
            "verdict": "однородно в радиусе ~{}км, {} не найдено".format(
                round(fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LON),
                "осадков" if want_precip_target else "просветов",
            ),
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = fc.bearing_compass(*p_now)

        if vx is None:
            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "precip" if currently_precip else "no_precip",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "blob_area_km2": round(blob_area_km2, 0),
                "verdict": "скорость посчитать не удалось (поле слишком однородно во всех кадрах)",
            }
            if target_type == "precip_mass":
                out["probability_percent"] = fc.change_probability(dist_now, blob_area_km2, confidence=0.25)
                out["probability_note"] = "эвристика (близость + размер поля), скорость не посчиталась"
        else:
            speed_kmh = math.hypot(vx, vy)
            dot_pv = p_now[0] * vx + p_now[1] * vy
            dot_vv = vx * vx + vy * vy
            t_cpa = max(0.0, -dot_pv / dot_vv) if dot_vv > 1e-6 else 0.0
            cpa_x = p_now[0] + vx * t_cpa
            cpa_y = p_now[1] + vy * t_cpa
            cpa_km = math.hypot(cpa_x, cpa_y)
            eta_min = round(t_cpa * 60, 0)

            if speed_kmh < fc.STATIONARY_SPEED_KMH:
                verdict = "почти стоит на месте"
            elif cpa_km <= fc.AFFECT_THRESHOLD_KM:
                verdict = "приближается" if eta_min > 5 else "уже у города"
            elif t_cpa <= 1e-6:
                verdict = "удаляется"
            else:
                verdict = "пройдёт мимо, город, скорее всего, не заденет"

            bearing_v = (math.degrees(math.atan2(vx, vy)) + 360) % 360

            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "precip" if currently_precip else "no_precip",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "direction_compass": fc.compass(bearing_v),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "blob_area_km2": round(blob_area_km2, 0),
                "verdict": verdict,
                "frame_pairs_used": n_pairs,
            }
            if target_type == "precip_mass":
                confidence = min(1.0, n_pairs / max(1, N_FRAMES - 1))
                out["probability_percent"] = fc.change_probability(cpa_km, blob_area_km2, confidence)
                out["probability_note"] = (
                    "эвристика (близость точки сближения + размер поля + уверенность в скорости), "
                    "не физическая модель осадков"
                )

    out["method_note"] = (
        f"Скорость усреднена по {N_FRAMES} кадрам msg_fes:h60b (шаг {STEP_MINUTES} мин, phase "
        f"correlation). Presence = непрозрачный пиксель. Край ищется только среди связных "
        f"областей >= {fc.MIN_SIGNIFICANT_BLOB_PX}px (~{round(fc.MIN_SIGNIFICANT_BLOB_PX*fc.KM_PER_PX_X*fc.KM_PER_PX_Y)}км²). "
        "Линейная экстраполяция, годится на ~1 час."
    )

    # --- ROI-проверка: идут ли осадки ИМЕННО из той массы, что выбрал CLM
    # (candidates[0] в cloud_forecast.json), а не глобально ближайшее пятно
    # в h60b (см. выше nearest/p_now — это отдельный независимый поиск).
    # Порог ниже, чем у остальных target_confirmation (0.05 вместо 0.5) —
    # осадки типично покрывают лишь часть площади облачной массы, а не
    # большинство её пикселей, majority-порог тут дал бы много ложных "нет".
    # Шаг 5 задуманного алгоритма (см. docs/topics/eumetsat.md, план от
    # 2026-08-04). Аддитивно.
    target, target_reason = fc.load_primary_target()
    if target is None:
        out["target_confirmation"] = {"confirmed": None, "reason": target_reason}
    else:
        roi_mask = fc.km_bbox_to_pixel_mask(target["bbox_km"], pad_km=2.0)
        roi_valid = valid_now[roi_mask]
        roi_presence = presence_now[roi_mask]
        if roi_valid.sum() == 0:
            out["target_confirmation"] = {
                "confirmed": None,
                "reason": "ROI цели CLM вне окна h60b-кадра или нет данных",
                "target_id": target["target_id"],
            }
        else:
            roi_precip_fraction = float(roi_presence[roi_valid].mean()) if roi_valid.any() else 0.0
            confirmed = roi_precip_fraction >= 0.05
            out["target_confirmation"] = {
                "confirmed": confirmed,
                "target_id": target["target_id"],
                "target_area_km2": target["area_km2"],
                "roi_precip_fraction": round(roi_precip_fraction, 3),
                "verdict": (
                    "Осадки наблюдаются непосредственно из этой облачной массы"
                    if confirmed else
                    "Осадков из этой конкретной массы не наблюдается (сухое облако либо осадки не достигают земли)"
                ),
            }

    # --- Обогащающий (не voting) анализ осадков внутри крупной системы
    # синоптического масштаба, если CLM её отметил (class=="system"). Не
    # confirmed/not_confirmed — система и так очевидно реальна при такой
    # площади, вопрос не "существует ли", а "есть ли внутри неё осадки"
    # (см. docs/topics/eumetsat.md, обсуждение 2026-08-06). Тот же порог
    # 0.05, что и у target_confirmation выше — семантика идентична, только
    # цель другая.
    sys_target, sys_reason = fc.load_system_target()
    if sys_target is None:
        out["system_analysis"] = {"available": False, "reason": sys_reason}
    else:
        sys_roi_mask = fc.km_bbox_to_pixel_mask(sys_target["bbox_km"], pad_km=2.0)
        sys_roi_valid = valid_now[sys_roi_mask]
        sys_roi_presence = presence_now[sys_roi_mask]
        if sys_roi_valid.sum() == 0:
            out["system_analysis"] = {
                "available": False,
                "reason": "ROI системы вне окна h60b-кадра или нет данных",
                "target_id": sys_target["target_id"],
            }
        else:
            sys_precip_fraction = float(sys_roi_presence[sys_roi_valid].mean()) if sys_roi_valid.any() else 0.0
            out["system_analysis"] = {
                "available": True,
                "target_id": sys_target["target_id"],
                "area_km2": sys_target["area_km2"],
                "roi_precip_fraction": round(sys_precip_fraction, 3),
                "has_precip": sys_precip_fraction >= 0.05,
            }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_precip_forecast.py: {out.get('verdict')}")


if __name__ == "__main__":
    main()
