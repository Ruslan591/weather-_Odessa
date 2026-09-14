"""
eumetsat_precip_motion.py — анализ движения области ОСАДКОВ (mtg_fd:h40b,
Blended FCI/LEO MW precipitation, MTG, 10 мин) с персистентным буфером
кадров — для Одессы: направление, скорость, ближайший край (осадки/просвет),
CPA/ETA, эвристическая вероятность выпадения осадков.

Инфраструктура идентична eumetsat_ir_motion.py (см. подробные комментарии
там же — здесь только отличия):
  - Персистентный буфер MAX_FRAMES=6 кадров в data/eumetsat_precip_buffer.npz,
    обычный прогон докачивает 1 новый кадр, а не все 6 заново.
  - crs=EPSG:4326 (порядок осей lat,lon).
  - Время всегда явное — из GetCapabilities (fc.get_layer_latest_time),
    а не time=None/floor(now); откат на floor(now)/last+STEP, если сам
    GetCapabilities недоступен.
  - Bootstrap устойчив к единичному пропуску исторического слота (не
    обрывает весь прогон); bootstrap-триггер по MIN_FRAMES_FOR_INCREMENTAL,
    а не MAX_FRAMES — иначе застрявший короче 6 буфер пересобирался бы
    заново каждый прогон.
  - Скорость считается из РЕАЛЬНЫХ таймстемпов буфера (fc.estimate_motion_dt),
    а не фиксированного шага — буфер может иметь неравномерные интервалы.

ОТЛИЧИЕ ОТ IR: presence-классификация по прозрачности пикселя
(fc.classify_presence_by_alpha — непрозрачный = есть осадки), а не
непрерывная яркость — у h40b нет чёткой моно-шкалы вроде яркостной
температуры IR, зато "0 осадков" в этом стиле рендерится прозрачным
(тот же приём, что уже работает в eumetsat_precip_forecast.py для
msg_fes:h60b). Буфер хранит бинарные маски (bool, как float32 0/1), а не
градации серого — поэтому используется estimate_motion_dt (бинарный
вариант с реальным dt), а не estimate_motion_continuous.

ВЫВОД: домен-логика (target_type precip_mass/clearing, CPA, ETA,
эвристическая probability_percent) взята из уже работающего
eumetsat_precip_forecast.py — это осмысленнее для осадков, чем метрики
area_trend/brightness_trend из IR-блока (те про форму облачности вообще,
а для осадков важнее конкретно "долетит ли до станции и когда").

Пишет data/eumetsat_precip_motion.json (результат),
data/eumetsat_precip_motion_debug.json (диагностика) и
data/eumetsat_precip_buffer.npz (персистентный буфер масок).
"""

import json
import math
import os
from datetime import datetime, timezone

import numpy as np

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_precip_motion.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_precip_motion_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_precip_buffer.npz")

LAYER_H40B = "mtg_fd:h40b"
STYLE_H40B = "mtg_fd:mtg_h40b_default"
MAX_FRAMES = 6
MIN_FRAMES_FOR_INCREMENTAL = 2
STEP_MINUTES = 10
STALE_BUFFER_SECONDS = 25 * 60


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def main():
    debug = {}
    now = datetime.now(fc.timezone.utc)

    times, masks_f32 = fc.load_frame_buffer(BUFFER_FILE)
    masks = [m.astype(bool) for m in masks_f32]

    stale = True
    if times:
        try:
            last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
            stale = (now - last_t).total_seconds() > STALE_BUFFER_SECONDS
        except Exception:
            stale = True

    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_H40B)
    debug["server_latest_time"] = server_latest_iso

    bootstrap = (not times) or (len(masks) < MIN_FRAMES_FOR_INCREMENTAL) or stale
    debug["bootstrap"] = bootstrap
    debug["buffer_before"] = len(masks)

    if bootstrap:
        if server_latest_iso:
            latest_min = fc._parse_iso_minutes(server_latest_iso)
            times_iso = [
                fc.datetime.fromtimestamp((latest_min - STEP_MINUTES * i) * 60, tz=fc.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:00.000Z")
                for i in range(MAX_FRAMES - 1, -1, -1)
            ]
        else:
            times_iso = fc.build_time_steps(STEP_MINUTES, MAX_FRAMES, latest_as_none=False)

        new_times, new_masks, failed = [], [], []
        for t_iso in times_iso:
            try:
                arr = fc.fetch_tile(LAYER_H40B, t_iso, style=STYLE_H40B, crs="EPSG:4326")
            except Exception as e:
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_precip_motion.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            presence, _valid = fc.classify_presence_by_alpha(arr)
            new_times.append(t_iso or _fmt_time(now))
            new_masks.append(presence)

        if len(new_masks) < 2:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": "bootstrap", "failed": failed,
                                         "note": f"годных кадров {len(new_masks)}/{MAX_FRAMES} — недостаточно для оценки движения"})
            print(f"  [WARN] eumetsat_precip_motion.py: bootstrap провалился, годных кадров {len(new_masks)}/{MAX_FRAMES}")
            return

        if failed:
            debug["bootstrap_failed_frames"] = failed
        times, masks = new_times, new_masks
    else:
        last_t_min = fc._parse_iso_minutes(times[-1])
        if server_latest_iso:
            server_min = fc._parse_iso_minutes(server_latest_iso)
            if server_min <= last_t_min:
                fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                             "note": f"сервер ещё не объявил кадр новее {times[-1]} (default={server_latest_iso})"})
                fc.log_skip_event("eumetsat_precip_motion.py", "source_stale",
                                   layer=LAYER_H40B, server_latest_time=server_latest_iso,
                                   extra={"last_known_frame": times[-1]})
                fc.record_pipeline_health("eumetsat_precip_motion.py", ok=False)
                print(f"  [SKIP] eumetsat_precip_motion.py: новых кадров пока нет (server default={server_latest_iso})")
                return
            next_t_iso = server_latest_iso
        else:
            next_t = fc.datetime.fromtimestamp((last_t_min + STEP_MINUTES) * 60, tz=fc.timezone.utc)
            next_t_iso = _fmt_time(next_t)
        try:
            arr = fc.fetch_tile(LAYER_H40B, next_t_iso, style=STYLE_H40B, crs="EPSG:4326")
        except Exception as e:
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            fc.log_skip_event("eumetsat_precip_motion.py", "next_frame_not_ready",
                               layer=LAYER_H40B, server_latest_time=server_latest_iso,
                               extra={"awaited_time": next_t_iso, "error": str(e)})
            print(f"  [SKIP] eumetsat_precip_motion.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return
        presence_new, _valid = fc.classify_presence_by_alpha(arr)
        if np.array_equal(masks[-1], presence_new):
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра — задержка публикации)"})
            fc.log_skip_event("eumetsat_precip_motion.py", "duplicate_frame",
                               layer=LAYER_H40B, server_latest_time=server_latest_iso)
            fc.record_pipeline_health("eumetsat_precip_motion.py", ok=False)
            print("  [SKIP] eumetsat_precip_motion.py: новых данных ещё нет (дубль)")
            return
        times = (times + [next_t_iso])[-MAX_FRAMES:]
        masks = (masks + [presence_new])[-MAX_FRAMES:]

    fc.save_frame_buffer(BUFFER_FILE, times, [m.astype(np.float32) for m in masks], max_frames=MAX_FRAMES)
    debug["buffer_after"] = len(masks)
    debug["buffer_times"] = list(times)

    presence_now = masks[-1]
    valid_now = np.ones_like(presence_now, dtype=bool)
    center_idx = int((fc.TILE_SIZE - 1) / 2)
    currently_precip = bool(presence_now[center_idx, center_idx])
    want_precip_target = not currently_precip
    target_type = "precip_mass" if want_precip_target else "clearing"

    nearest = fc.nearest_of_type(presence_now, valid_now, want_precip_target)
    p_now = nearest[:2] if nearest is not None else None
    blob_area_km2 = nearest[2] if nearest is not None else None
    vx, vy, n_pairs = fc.estimate_motion_dt(masks, times) if len(masks) >= 2 else (None, None, 0)

    out = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buffer_size": len(masks),
        "buffer_span_minutes": round((fc._parse_iso_minutes(times[-1]) - fc._parse_iso_minutes(times[0]))
                                      if len(times) >= 2 else 0),
        "observed_area": {
            "center_lat": fc.CENTER_LAT,
            "center_lon": fc.CENTER_LON,
            "motion_window_km": {
                "width": round(2 * fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LON),
                "height": round(2 * fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LAT),
            },
        },
        "current_state": "precip" if currently_precip else "no_precip",
        "target_type": target_type,
    }

    if p_now is None:
        out["verdict"] = "однородно в радиусе ~{}км, {} не найдено".format(
            round(fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LON),
            "осадков" if want_precip_target else "просветов",
        )
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = fc.bearing_compass(*p_now)
        out["distance_km_now"] = round(dist_now, 1)
        out["bearing_deg"] = round(bearing_now, 0)
        out["compass"] = compass_now
        out["blob_area_km2"] = round(blob_area_km2, 0)

        if vx is None:
            out["verdict"] = "скорость посчитать не удалось (поле слишком однородно во всех кадрах)"
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

            out["speed_kmh"] = round(speed_kmh, 1)
            out["direction_compass"] = fc.compass(bearing_v)
            out["cpa_km"] = round(cpa_km, 1)
            out["eta_min"] = eta_min if verdict in ("приближается", "уже у города") else None
            out["verdict"] = verdict
            out["frame_pairs_used"] = n_pairs

            if target_type == "precip_mass":
                confidence = min(1.0, n_pairs / max(1, MAX_FRAMES - 1))
                out["probability_percent"] = fc.change_probability(cpa_km, blob_area_km2, confidence)
                out["probability_note"] = (
                    "эвристика (близость точки сближения + размер поля + уверенность в скорости), "
                    "не физическая модель осадков"
                )

    out["method_note"] = (
        f"Буфер {len(masks)}/{MAX_FRAMES} масок mtg_fd:h40b (шаг {STEP_MINUTES} мин, crs=EPSG:4326, "
        "всегда явный TIME из GetCapabilities — не floor(now)), хранится персистентно между прогонами "
        "(FIFO) — обычный прогон докачивает только 1 новый кадр. Presence = непрозрачный пиксель. "
        f"Край ищется только среди связных областей >= {fc.MIN_SIGNIFICANT_BLOB_PX}px "
        f"(~{round(fc.MIN_SIGNIFICANT_BLOB_PX*fc.KM_PER_PX_X*fc.KM_PER_PX_Y)}км²). Скорость — из реальных "
        "интервалов буфера (не фиксированный шаг). Линейная экстраполяция, годится на ~1 час."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    fc.record_pipeline_health("eumetsat_precip_motion.py", ok=True)
    print(f"  [OK] eumetsat_precip_motion.py: {out.get('verdict')}")


if __name__ == "__main__":
    main()

