"""
eumetsat_geocolour_motion.py — независимая оценка движения и area-fraction
облачности по MTG Natural Colour / GeoColour RGB (mtg_fd:rgb_geocolour),
КРУГЛОСУТОЧНО (не только днём — см. обоснование ниже).

ПОЧЕМУ КРУГЛОСУТОЧНО: это не обычный "видимый свет" композит, а day/night
GeoColour-продукт (как GOES GeoColor у NOAA) — ночью в него подмешан ИК-канал,
и облака остаются отчётливо видны характерным ГОЛУБЫМ оттенком на фоне
чёрной земли/моря, а огни городов — отдельным жёлто-оранжевым каналом. Днём
облака — обычные бело-серые (обычная видимая рефлектация). Это подтверждено
визуально на реальном скриншоте слоя (см. обсуждение в чате), поэтому
классификация ниже — ДВЕ ветки (день: белое/яркое; ночь: голубое) плюс явное
ИСКЛЮЧЕНИЕ огней городов (жёлто-оранжевые яркие точки) — без него они бы
ложно засчитывались как "облако" и портили area_fraction/позицию.

ГИБРИДНАЯ АРХИТЕКТУРА (в отличие от eumetsat_ir_motion.py и
eumetsat_cloud_forecast.py по отдельности):
  - Motion-трекинг (скорость/направление/ускорение/прогноз смещения) — как в
    IR: phase correlation НА СЫРОЙ ЯРКОСТИ (fc.estimate_motion_continuous),
    не на бинарной маске. Городские огни — точечные яркие источники, их
    вычищает медианный despeckle-фильтр ДО корреляции (см. _despeckle в
    field_motion_common.py, docstring прямо упоминает этот случай) — поэтому
    для motion не нужен отдельный HSV-классификатор, сырой luma уже работает.
  - Area-fraction / позиция ближайшей массы (station_state, cloud_mass_*) —
    как в Cloud Mask: АБСОЛЮТНАЯ бинарная HSV-классификация "это пиксель
    облака или нет" (день ИЛИ ночь ветка, минус огни), а не относительный
    перцентиль-порог яркости (в отличие от IR, где нет физически осмысленного
    абсолютного порога — тут он есть, цвет облака узнаваем однозначно).

Буфер хранит ДВА канала на кадр: [0]=яркость (для motion), [1]=is_cloud
0/1 (для area-fraction/позиции) — тот же приём упаковки, что и в
eumetsat_cloud_forecast.py (CLM+CTH) и eumetsat_cloud_phase_type.py.

ВАЖНО — ограничения:
  - HSV-пороги (день/ночь/огни) — первая, не откалиброванная по реальным
    сценам версия (тот же класс ограничения, что и Cloud Phase/Type RGB —
    нет официальной легенды у RGB-композита). Ожидается калибровка.
  - Ночная "голубая" ветка может путать облака с яркой луной/бликами на
    воде в редких случаях — не проверялось на большом наборе сцен.
  - Прогноз смещения — линейная экстраполяция недавнего тренда, не
    физическая модель атмосферы (см. eumetsat_ir_motion.py).

Пишет data/eumetsat_geocolour_motion.json (результат) и
data/eumetsat_geocolour_buffer.npz (персистентный буфер, 2 канала).
"""

import json
import math
import os

import numpy as np
from PIL import Image

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_motion.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_motion_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_buffer.npz")
DEBUG_PREVIEW_FILE = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_debug_preview.png")

LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"
MAX_FRAMES = 6                   # 6*10мин = 60 минут истории, как в IR
MIN_FRAMES_FOR_INCREMENTAL = 2
STEP_MINUTES = 10
MIN_STD = 6.0
STALE_BUFFER_SECONDS = 25 * 60
AREA_CHANGE_THRESHOLD = 0.10


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def _in_hue_range(h_deg, lo, hi):
    if lo <= hi:
        return (h_deg >= lo) & (h_deg <= hi)
    return (h_deg >= lo) | (h_deg <= hi)


def _is_daytime(t_iso):
    """Грубая оценка дня/ночи по локальному часу — НЕ настоящий расчёт
    восхода/заката (без сезонной/DST-точности, UTC+3 — летнее время
    Одессы), но этого достаточно, чтобы СТРУКТУРНО развести ветки
    классификации, а не гадать по одному только цвету. Без этого разделения
    тёмно-синяя морская вода днём неотличима по HSV от бледно-голубого
    облака ночью (обе — умеренно-насыщенный синий, см. смоук-тест перед
    пушем) — с явным day/night-гейтом такой двусмысленности нет в принципе:
    в дневных кадрах морская вода просто не проверяется на "похоже на
    ночное облако", и наоборот."""
    dt = fc.datetime.strptime(t_iso, "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
    local_hour = (dt.hour + 3) % 24
    return 5 <= local_hour < 20


def _classify_cloud(rgba, is_day):
    """arr: (H,W,4) RGBA -> (is_cloud bool, valid bool). День: белое/яркое
    (низкая S, высокая V). Ночь: голубое (IR-подсветка). Огни городов
    (жёлто-оранжевые яркие точки) — явно ИСКЛЮЧЕНЫ в обеих ветках."""
    alpha_valid = rgba[:, :, 3] > 0
    h, s, v = fc.rgb_to_hsv_vec(rgba[:, :, :3])
    # Пороги скорректированы по реальному debug preview (data/
    # eumetsat_geocolour_debug_preview.png) — первая версия (уже вторая по
    # счёту) оказалась неверной в обе стороны сразу: огни городов ловились
    # как облако (city_light была слишком мягкой), а настоящие ночные облака
    # (на деле бледно-серо-голубые, менее насыщенные, чем предполагалось) —
    # почти не ловились (night_cloud была слишком строгой по S).
    city_light = _in_hue_range(h, 15, 70) & (s > 0.2) & (v > 0.25)

    if is_day:
        cloud = (s < 0.25) & (v > 0.55)
    else:
        cloud = _in_hue_range(h, 180, 260) & (s > 0.06) & (v > 0.10)

    is_cloud = cloud & (~city_light) & alpha_valid
    return is_cloud, alpha_valid


def _pack_frame(gray, is_cloud):
    return np.stack([gray.astype(np.float32), is_cloud.astype(np.float32)], axis=0)


def _unpack_frame(packed):
    return packed[0], packed[1] > 0.5


def _save_debug_preview(rgba, is_cloud):
    """Оверлей классифицированных 'облачных' пикселей поверх исходного
    кадра — чтобы КАЛИБРОВАТЬ пороги HSV по реальным данным, глядя на
    картинку, а не гадать по цифрам вслепую (см. обсуждение в чате —
    первая версия порогов дважды оказалась неверной)."""
    try:
        base = Image.fromarray(rgba[:, :, :3], mode="RGB").convert("RGB")
        overlay = np.array(base).copy()
        overlay[is_cloud] = [255, 0, 0]  # ярко-красным — что классифицировано как облако
        blended = (np.array(base).astype(np.float32) * 0.4 + overlay.astype(np.float32) * 0.6).astype(np.uint8)
        Image.fromarray(blended, mode="RGB").save(DEBUG_PREVIEW_FILE)
    except Exception as e:
        print(f"  [WARN] eumetsat_geocolour_motion.py: не удалось сохранить debug preview: {e}")


def main():
    now = fc.datetime.now(fc.timezone.utc)
    debug = {}

    times, packed_frames = fc.load_frame_buffer(BUFFER_FILE)

    stale = True
    if times:
        try:
            last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
            stale = (now - last_t).total_seconds() > STALE_BUFFER_SECONDS
        except Exception:
            stale = True

    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_GEOCOLOUR)
    debug["server_latest_time"] = server_latest_iso

    bootstrap = (not times) or (len(packed_frames) < MIN_FRAMES_FOR_INCREMENTAL) or stale
    debug["bootstrap"] = bootstrap
    debug["buffer_before"] = len(packed_frames)

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

        new_times, new_packed, failed = [], [], []
        for t_iso in times_iso:
            try:
                arr = fc.fetch_tile(LAYER_GEOCOLOUR, t_iso)
            except Exception as e:
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_geocolour_motion.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            gray = fc.to_grayscale_luminance(arr)
            is_cloud, _ = _classify_cloud(arr, _is_daytime(t_iso))
            new_times.append(t_iso or _fmt_time(now))
            new_packed.append(_pack_frame(gray, is_cloud))
            _save_debug_preview(arr, is_cloud)  # перезаписываем на каждой итерации — в конце останется последний (самый свежий) кадр

        if len(new_packed) < MIN_FRAMES_FOR_INCREMENTAL:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": "bootstrap", "failed": failed,
                                         "note": f"годных кадров {len(new_packed)}/{MAX_FRAMES} — недостаточно"})
            print(f"  [WARN] eumetsat_geocolour_motion.py: bootstrap провалился, годных {len(new_packed)}/{MAX_FRAMES}")
            return

        if failed:
            debug["bootstrap_failed_frames"] = failed
        times, packed_frames = new_times, new_packed
    else:
        last_t_min = fc._parse_iso_minutes(times[-1])
        if server_latest_iso:
            server_min = fc._parse_iso_minutes(server_latest_iso)
            if server_min <= last_t_min:
                fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                             "note": f"сервер ещё не объявил кадр новее {times[-1]}"})
                print("  [SKIP] eumetsat_geocolour_motion.py: новых кадров пока нет")
                return
            next_t_iso = server_latest_iso
        else:
            next_t = fc.datetime.fromtimestamp((last_t_min + STEP_MINUTES) * 60, tz=fc.timezone.utc)
            next_t_iso = _fmt_time(next_t)

        try:
            arr = fc.fetch_tile(LAYER_GEOCOLOUR, next_t_iso)
        except Exception as e:
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            print(f"  [SKIP] eumetsat_geocolour_motion.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return

        gray_new = fc.to_grayscale_luminance(arr)
        is_cloud_new, _ = _classify_cloud(arr, _is_daytime(next_t_iso))
        last_gray, _ = _unpack_frame(packed_frames[-1])
        if fc.is_duplicate_pair(last_gray, gray_new):
            debug["skipped_duplicate"] = True
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра)"})
            print("  [SKIP] eumetsat_geocolour_motion.py: новых данных ещё нет (дубль)")
            return

        new_packed = _pack_frame(gray_new, is_cloud_new)
        times = (times + [next_t_iso])[-MAX_FRAMES:]
        packed_frames = (packed_frames + [new_packed])[-MAX_FRAMES:]
        _save_debug_preview(arr, is_cloud_new)

    fc.save_frame_buffer(BUFFER_FILE, times, packed_frames, MAX_FRAMES)
    debug["buffer_size"] = len(packed_frames)
    debug["buffer_times"] = list(times)

    unpacked = [_unpack_frame(p) for p in packed_frames]
    gray_frames = [u[0] for u in unpacked]
    is_cloud_frames = [u[1] for u in unpacked]
    debug["frame_std"] = [round(float(g.std()), 1) for g in gray_frames]

    out = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buffer_size": len(packed_frames),
        "buffer_span_minutes": round((fc._parse_iso_minutes(times[-1]) - fc._parse_iso_minutes(times[0]))
                                      if len(times) >= 2 else 0),
        "observed_area": {
            "center_lat": fc.CENTER_LAT,
            "center_lon": fc.CENTER_LON,
            "motion_window_km": {
                "width": round(2 * fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LON),
                "height": round(2 * fc.HALF_WINDOW_DEG * fc.KM_PER_DEG_LAT),
            },
            "local_trend_radius_km": round(fc.LOCAL_RADIUS_KM),
        },
    }

    vx, vy, n_pairs = fc.estimate_motion_continuous(gray_frames, times, min_std=MIN_STD)

    if vx is None:
        out["valid"] = False
        out["verdict"] = "недостаточно контраста для оценки (вероятно, однородная сцена)"
    else:
        speed_kmh = math.hypot(vx, vy)
        bearing_v = (math.degrees(math.atan2(vx, vy)) + 360) % 360
        out["valid"] = True
        out["speed_kmh"] = round(speed_kmh, 1)
        out["direction_compass"] = fc.compass(bearing_v)
        out["bearing_deg"] = round(bearing_v, 1)
        out["frame_pairs_used"] = n_pairs

        if len(gray_frames) >= 4:
            half = len(gray_frames) // 2
            early, late = gray_frames[:half + 1], gray_frames[half:]
            early_times, late_times = times[:half + 1], times[half:]
            vx_e, vy_e, n_e = fc.estimate_motion_continuous(early, early_times, min_std=MIN_STD)
            vx_l, vy_l, n_l = fc.estimate_motion_continuous(late, late_times, min_std=MIN_STD)

            if vx_e is not None and vx_l is not None:
                speed_e = math.hypot(vx_e, vy_e)
                speed_l = math.hypot(vx_l, vy_l)
                bearing_e = (math.degrees(math.atan2(vx_e, vy_e)) + 360) % 360
                bearing_l = (math.degrees(math.atan2(vx_l, vy_l)) + 360) % 360
                accel = speed_l - speed_e
                turn = fc.circular_angle_diff(bearing_e, bearing_l)

                out["acceleration_kmh"] = round(accel, 1)
                out["turning_deg"] = round(turn, 1)
                out["acceleration_verdict"] = (
                    "ускоряется" if accel > 5 else "замедляется" if accel < -5 else "скорость стабильна"
                )
                if abs(turn) > 20:
                    out["turning_verdict"] = f"меняет направление ({'по часовой' if turn > 0 else 'против часовой'})"
                else:
                    out["turning_verdict"] = "направление стабильно"

                center_early_min = sum(fc._parse_iso_minutes(t) for t in early_times) / len(early_times)
                center_late_min = sum(fc._parse_iso_minutes(t) for t in late_times) / len(late_times)
                dt_centers_h = (center_late_min - center_early_min) / 60.0
                if dt_centers_h > 1e-6:
                    ax = (vx_l - vx_e) / dt_centers_h
                    ay = (vy_l - vy_e) / dt_centers_h
                else:
                    ax = ay = 0.0

                forecasts = {}
                for label, t_min in [("30min", 30), ("60min", 60), ("120min", 120)]:
                    t_h = t_min / 60.0
                    dx = vx_l * t_h + 0.5 * ax * t_h ** 2
                    dy = vy_l * t_h + 0.5 * ay * t_h ** 2
                    dist = math.hypot(dx, dy)
                    bearing_f = (math.degrees(math.atan2(dx, dy)) + 360) % 360
                    forecasts[label] = {
                        "distance_km": round(dist, 1),
                        "bearing_deg": round(bearing_f, 0),
                        "compass": fc.compass(bearing_f),
                    }
                out["forecast_displacement"] = forecasts

    # --- area-fraction/station_state/cloud_mass — АБСОЛЮТНАЯ HSV-маска
    # is_cloud, не относительный перцентиль-порог (см. докстринг модуля) ---
    if len(packed_frames) >= 2:
        local_mask = fc.local_area_mask()
        area_fracs = [float(is_cloud[local_mask].mean()) for is_cloud in is_cloud_frames]

        area_delta = area_fracs[-1] - area_fracs[0]
        if area_delta > AREA_CHANGE_THRESHOLD:
            area_verdict = "растёт"
        elif area_delta < -AREA_CHANGE_THRESHOLD:
            area_verdict = "сокращается"
        else:
            area_verdict = "без существенных изменений"

        out["area_fraction_over_time"] = [round(f, 3) for f in area_fracs]
        out["area_trend_delta"] = round(area_delta, 3)
        out["area_trend_verdict"] = area_verdict

        latest_area_frac = area_fracs[-1]
        if latest_area_frac < 0.15:
            out["station_state"] = "clear"
        elif latest_area_frac < 0.70:
            out["station_state"] = "variable"
        else:
            out["station_state"] = "cloud"
        out["station_area_fraction"] = round(latest_area_frac, 3)

        valid_all = np.ones_like(is_cloud_frames[-1], dtype=bool)
        blob = fc.nearest_of_type(is_cloud_frames[-1], valid_all, True)
        if blob is not None:
            dx_km, dy_km, area_km2 = blob
            bearing_deg, compass_dir = fc.bearing_compass(dx_km, dy_km)
            out["cloud_mass_distance_km"] = round(math.hypot(dx_km, dy_km), 1)
            out["cloud_mass_bearing_deg"] = round(bearing_deg, 0)
            out["cloud_mass_compass"] = compass_dir
            out["cloud_mass_area_km2"] = round(area_km2)
        else:
            out["cloud_mass_distance_km"] = None

    out["method_note"] = (
        f"Буфер {len(packed_frames)}/{MAX_FRAMES} кадров mtg_fd:rgb_geocolour (шаг {STEP_MINUTES} мин), "
        "круглосуточно (day/night GeoColour-композит, ночью облака синие от подсветки ИК, "
        "огни городов жёлтые — явно исключены из классификации облачности). Скорость/направление — "
        "phase correlation по сырой яркости с despeckle (огни городов вычищаются как точечные источники "
        "перед корреляцией). Area-fraction/позиция — АБСОЛЮТНАЯ HSV-классификация (не относительный "
        "перцентиль, как в ИК) — первая, не откалиброванная по реальным сценам версия. "
        "Прогноз смещения — линейная экстраполяция, не физическая модель атмосферы."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_geocolour_motion.py: {out.get('verdict', out.get('speed_kmh'))}")


if __name__ == "__main__":
    main()
