"""
eumetsat_lightning_forecast.py — мини-прогноз движения грозовой активности
(mtg_fd:li_afa, Lightning Imager Accumulated Flash Area) для Одессы:
направление, скорость, ближайшая область с молниями, ETA, и (если сейчас
без гроз и рядом значимая грозовая ячейка) эвристическая вероятность.

Метод идентичен eumetsat_precip_forecast.py (presence по alpha), только шаг
5 мин — li_afa обновляется чаще (аккумуляция вспышек за последние 5 мин).
Грозовые ячейки мельче и быстрее осадков/облаков — оценка скорости чаще
будет "не удалось" (поле слишком разреженное для phase correlation), это
ожидаемо, не баг.

Пишет data/eumetsat_lightning_forecast.json.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_lightning_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_lightning_forecast_debug.json")

LAYER_LI_AFA = "mtg_fd:li_afa"
N_FRAMES = 4
STEP_MINUTES = 5
# Грозовые ячейки компактнее осадков/облаков — порог значимости ниже,
# иначе реальные, но небольшие очаги молний будут отбрасываться как шум.
MIN_BLOB_PX = 8


def main():
    debug = {}
    now = datetime.now(timezone.utc)
    times_iso = fc.build_time_steps(STEP_MINUTES, N_FRAMES)

    arrs = []
    for t_iso in times_iso:
        try:
            arrs.append(fc.fetch_tile(LAYER_LI_AFA, t_iso))
        except Exception as e:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": f"fetch {t_iso}", "error": str(e)})
            print(f"  [WARN] eumetsat_lightning_forecast.py: fetch failed ({t_iso}): {e}")
            return

    debug["frames_fetched"] = len(arrs)
    debug["times_requested"] = times_iso

    classified = [fc.classify_presence_by_alpha(a) for a in arrs]
    presence_frames = [c[0] for c in classified]
    valid_frames = [c[1] for c in classified]
    presence_now = presence_frames[-1]
    valid_now = valid_frames[-1]

    center_idx = int((fc.TILE_SIZE - 1) / 2)
    currently_storm = bool(presence_now[center_idx, center_idx])
    want_storm_target = not currently_storm
    target_type = "storm_mass" if want_storm_target else "clearing"

    nearest = fc.nearest_of_type(presence_now, valid_now, want_storm_target, min_blob_px=MIN_BLOB_PX)
    p_now = nearest[:2] if nearest is not None else None
    blob_area_km2 = nearest[2] if nearest is not None else None
    vx, vy, n_pairs = fc.estimate_motion(presence_frames, STEP_MINUTES)

    if p_now is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": "storm" if currently_storm else "no_storm",
            "target_type": target_type,
            "verdict": "гроз в радиусе ~{}км не обнаружено".format(
                round(fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LON)
            ) if want_storm_target else "молнии повсюду в радиусе (нетипично, проверить данные)",
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = fc.bearing_compass(*p_now)

        if vx is None:
            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "storm" if currently_storm else "no_storm",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "blob_area_km2": round(blob_area_km2, 0),
                "verdict": "скорость посчитать не удалось (ячейка слишком мала/разрежена для оценки)",
            }
            if target_type == "storm_mass":
                out["probability_percent"] = fc.change_probability(dist_now, blob_area_km2, confidence=0.2)
                out["probability_note"] = "эвристика (близость + размер очага), скорость не посчиталась"
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
                "current_state": "storm" if currently_storm else "no_storm",
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
            if target_type == "storm_mass":
                confidence = min(1.0, n_pairs / max(1, N_FRAMES - 1))
                out["probability_percent"] = fc.change_probability(cpa_km, blob_area_km2, confidence)
                out["probability_note"] = (
                    "эвристика (близость точки сближения + размер очага + уверенность в скорости), "
                    "не физическая модель грозовой активности"
                )

    out["method_note"] = (
        f"Скорость усреднена по {N_FRAMES} кадрам mtg_fd:li_afa (шаг {STEP_MINUTES} мин). Presence = "
        f"непрозрачный пиксель (накопленная площадь вспышек за 5 мин). Порог значимости снижен "
        f"до {MIN_BLOB_PX}px — грозовые ячейки компактнее осадков/облаков. Скорость часто не "
        "считается (поле слишком разреженное) — это ограничение метода, не ошибка."
    )

    # --- ROI-проверка: наблюдается ли гроза ИМЕННО в той массе, что выбрал
    # CLM (candidates[0] в cloud_forecast.json), а не глобально ближайшая
    # грозовая ячейка (см. выше nearest/p_now — отдельный независимый поиск).
    # Порог ниже, чем у precip (0.02 вместо 0.05) — грозовые ячейки li_afa ещё
    # компактнее осадочных пятен относительно площади облачной массы. Шаг 6
    # задуманного алгоритма (см. docs/topics/eumetsat.md, план от 2026-08-04).
    # Аддитивно.
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
                "reason": "ROI цели CLM вне окна li_afa-кадра или нет данных",
                "target_id": target["target_id"],
            }
        else:
            roi_lightning_fraction = float(roi_presence[roi_valid].mean()) if roi_valid.any() else 0.0
            confirmed = roi_lightning_fraction >= 0.02
            out["target_confirmation"] = {
                "confirmed": confirmed,
                "target_id": target["target_id"],
                "target_area_km2": target["area_km2"],
                "roi_lightning_fraction": round(roi_lightning_fraction, 3),
                "verdict": (
                    "Гроза наблюдается непосредственно в этой облачной массе"
                    if confirmed else
                    "Грозовой активности в этой конкретной массе не наблюдается"
                ),
            }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_lightning_forecast.py: {out.get('verdict')}")


if __name__ == "__main__":
    main()
