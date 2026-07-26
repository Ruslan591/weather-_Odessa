"""
eumetsat_ir_motion.py — независимая оценка движения облачности по текстуре
ИК-канала (mtg_fd:ir105_hrfi, MTG FCI, 10.5 мкм, 1км), с ПОСТОЯННЫМ буфером
последних 6 кадров (60 минут истории), а не разовым скачиванием 4 кадров
на каждый прогон.

ЗАЧЕМ ПЕРСИСТЕНТНЫЙ БУФЕР (data/eumetsat_ir_buffer.npz):
Раньше каждый прогон качал 4 свежих кадра заново (T-30,T-20,T-10,T), хотя
3 из них уже скачивались 10 минут назад в прошлом прогоне — 3x лишней
нагрузки на WMS-сервер. Теперь буфер хранится между прогонами: обычный
прогон докачивает ТОЛЬКО один новый кадр ("сейчас"), добавляет его в конец,
самый старый кадр выпадает (FIFO, максимум 6 кадров = 60 минут). Полная
перезакачка всех 6 кадров происходит только при "бутстрапе" — буфера ещё
нет, повреждён, или пропущено слишком много прогонов (буфер протух).

ЗАЧЕМ ИМЕННО 6 КАДРОВ (не 4):
С 6 кадрами за 60 минут вместо 4 за 30 можно надёжно расщепить историю на
"раннее" (первая половина) и "позднее" (вторая половина) окна и сравнить
скорость/направление между ними — это даёт ускорение/замедление и поворот
траектории, а не только "текущую" скорость. Плюс более длинная история
устойчивее к случайному шуму одного кадра.

ЧТО СЧИТАЕТСЯ:
  - speed_kmh / direction_compass — как раньше, но усреднено по всем (до 5)
    парам кадров в буфере вместо 3.
  - acceleration_kmh, turning_deg — сравнение раннего окна (первая половина
    буфера) с поздним (вторая половина): "ускоряется"/"замедляется",
    "меняет направление"/"направление стабильно".
  - area_trend — доля пикселей "значимо холоднее" (порог — 60-й перцентиль
    самого старого кадра в буфере, фиксированный, чтобы сравнение было
    честным во времени) в локальном радиусе, отслеживается по всем 6
    кадрам: растёт (облачная система разрастается) / сокращается (распад).
  - temperature_trend — средняя яркость (проще говоря, средняя яркостная
    температура) в локальном радиусе по времени: рост яркости = похолодание
    верхней границы = часто усиление конвекции; падение = потепление =
    часто ослабление. Шкала НЕ калибрована в °C, это относительный тренд.
  - forecast_displacement — прогноз смещения через 30/60/120 минут:
    кинематика v*t + 0.5*a*t² с вектором ускорения из сравнения раннего/
    позднего окна. Это ЛИНЕЙНАЯ ЭКСТРАПОЛЯЦИЯ реального недавнего движения,
    не физическая модель атмосферы — годится как грубая нowcasting-оценка
    на ближайшие 1-2 часа, не как прогноз.

ПОЧЕМУ crs=EPSG:4326 И ВСЕГДА ЯВНЫЙ TIME (не time=None "latest"):
Раньше добор нового кадра каждый прогон запрашивал time=None ("отдай самый
свежий"). Из-за задержки публикации сцены (publication lag) это иногда
возвращало ТУ ЖЕ сцену, что и в прошлый прогон, но с чуть другим шумом —
is_duplicate_pair() (точное побайтовое сравнение) такую почти-копию не ловил
(найдено на живом буфере: пара кадров с корреляцией 0.98 и 83% идентичных
пикселей вместо típичных 0.7/35-40% для настоящего 10-минутного шага).
Теперь вместо "дай что есть" запрашивается КОНКРЕТНЫЙ ожидаемый следующий
слот (последний кадр буфера + STEP_MINUTES); если сцена ещё не опубликована,
сервер отдаёт 404/"cannot identify image file" — это ловится как штатный
SKIP (см. ниже), а не как дубль постфактум. crs=EPSG:4326 — подтверждённый
рабочий вариант для этого слоя; порядок осей в bbox для EPSG:4326 (lat,lon)
отличается от использовавшегося раньше CRS:84 (lon,lat) — см. fetch_tile()
в field_motion_common.py.

Пишет data/eumetsat_ir_motion.json (результат) и
data/eumetsat_ir_buffer.npz (персистентный буфер кадров).
"""

import json
import math
import os

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_ir_buffer.npz")

LAYER_IR105 = "mtg_fd:ir105_hrfi"
STYLE_IR105 = "mtg_fd:mtg_fd_ir105_hrfi_grayscale"
MAX_FRAMES = 6
STEP_MINUTES = 10
MIN_STD = 6.0
STALE_BUFFER_SECONDS = 25 * 60  # если последний кадр буфера старше — бутстрап заново
AREA_CHANGE_THRESHOLD = 0.10    # 10 п.п. — "существенное" изменение площади


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def main():
    now = fc.datetime.now(fc.timezone.utc)
    debug = {}

    times, frames = fc.load_frame_buffer(BUFFER_FILE)

    stale = True
    if times:
        try:
            last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
            stale = (now - last_t).total_seconds() > STALE_BUFFER_SECONDS
        except Exception:
            stale = True

    bootstrap = (not times) or (len(frames) < MAX_FRAMES) or stale
    debug["bootstrap"] = bootstrap
    debug["buffer_before"] = len(frames)

    if bootstrap:
        times_iso = fc.build_time_steps(STEP_MINUTES, MAX_FRAMES, latest_as_none=False)
        new_times, new_frames, failed = [], [], []
        for t_iso in times_iso:
            try:
                arr = fc.fetch_tile(LAYER_IR105, t_iso, style=STYLE_IR105, crs="EPSG:4326")
            except Exception as e:
                # Одиночный пропуск/ServiceException на конкретном историческом
                # слоте (реальный пробел в архиве EUMETSAT) — НЕ повод обрывать
                # весь прогон: пропускаем этот кадр, собираем остальные. Буфер
                # получится короче MAX_FRAMES в этот раз — это ок, следующие
                # инкрементальные прогоны его дозаполнят (или бутстрап повторится,
                # когда проблемный слот сам выйдет из скользящего окна).
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_ir_motion.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            new_times.append(t_iso or _fmt_time(now))
            new_frames.append(fc.to_grayscale_luminance(arr))

        if len(new_frames) < 2:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": "bootstrap", "failed": failed,
                                         "note": f"годных кадров {len(new_frames)}/{MAX_FRAMES} — недостаточно для оценки движения"})
            print(f"  [WARN] eumetsat_ir_motion.py: bootstrap провалился, годных кадров {len(new_frames)}/{MAX_FRAMES}")
            return

        if failed:
            debug["bootstrap_failed_frames"] = failed
        times, frames = new_times, new_frames
    else:
        last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
        next_t = last_t + fc.timedelta(minutes=STEP_MINUTES)
        next_t_iso = _fmt_time(next_t)
        try:
            arr = fc.fetch_tile(LAYER_IR105, next_t_iso, style=STYLE_IR105, crs="EPSG:4326")
        except Exception as e:
            # Явный TIME на ещё не опубликованный слот обычно даёт 404/"cannot
            # identify image file" — это ШТАТНАЯ ситуация (сцена появится через
            # 10 мин), а не ошибка пайплайна. Стабильный буфер важнее заполнения
            # любой ценой — просто ждём следующего прогона.
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            print(f"  [SKIP] eumetsat_ir_motion.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return
        gray_new = fc.to_grayscale_luminance(arr)
        if fc.is_duplicate_pair(frames[-1], gray_new):
            debug["skipped_duplicate"] = True
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра — задержка публикации)"})
            print("  [SKIP] eumetsat_ir_motion.py: новых данных ещё нет (дубль)")
            return
        times = (times + [next_t_iso])[-MAX_FRAMES:]
        frames = (frames + [gray_new])[-MAX_FRAMES:]

    fc.save_frame_buffer(BUFFER_FILE, times, frames, MAX_FRAMES)
    debug["buffer_size"] = len(frames)
    debug["buffer_times"] = list(times)
    debug["frame_std"] = [round(float(g.std()), 1) for g in frames]

    out = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buffer_size": len(frames),
        "buffer_span_minutes": (len(frames) - 1) * STEP_MINUTES,
    }

    vx, vy, n_pairs = fc.estimate_motion_continuous(frames, STEP_MINUTES, min_std=MIN_STD)

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

        # --- ускорение/поворот: раннее окно vs позднее окно ---
        if len(frames) >= 4:
            half = len(frames) // 2
            early = frames[:half + 1]  # +1 кадр нахлёста, чтобы в каждом окне была хотя бы одна пара
            late = frames[half:]
            vx_e, vy_e, n_e = fc.estimate_motion_continuous(early, STEP_MINUTES, min_std=MIN_STD)
            vx_l, vy_l, n_l = fc.estimate_motion_continuous(late, STEP_MINUTES, min_std=MIN_STD)

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

                # --- прогноз смещения на 30/60/120 мин: v*t + 0.5*a*t² ---
                dt_centers_h = (half * STEP_MINUTES) / 60.0  # разница между центрами окон, часы
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

    # --- рост/распад площади + тренд яркостной температуры ---
    if len(frames) >= 2:
        local_mask = fc.local_area_mask()
        baseline_vals = frames[0][local_mask]
        threshold = float(fc.np.percentile(baseline_vals, 60))

        area_fracs, mean_brightness = [], []
        for g in frames:
            local_vals = g[local_mask]
            area_fracs.append(float((local_vals > threshold).mean()))
            mean_brightness.append(float(local_vals.mean()))

        area_delta = area_fracs[-1] - area_fracs[0]
        if area_delta > AREA_CHANGE_THRESHOLD:
            area_verdict = "площадь значимой облачности растёт"
        elif area_delta < -AREA_CHANGE_THRESHOLD:
            area_verdict = "площадь значимой облачности сокращается"
        else:
            area_verdict = "площадь без существенных изменений"

        brightness_delta = mean_brightness[-1] - mean_brightness[0]
        brightness_scale = float(fc.np.mean(debug["frame_std"])) or 1.0
        if brightness_delta > 0.5 * brightness_scale:
            temp_verdict = "похолодание верхней границы (возможно усиление конвекции)"
        elif brightness_delta < -0.5 * brightness_scale:
            temp_verdict = "потепление верхней границы (возможно ослабление конвекции)"
        else:
            temp_verdict = "без существенных изменений яркостной температуры"

        out["area_fraction_over_time"] = [round(f, 3) for f in area_fracs]
        out["area_trend_delta"] = round(area_delta, 3)
        out["area_trend_verdict"] = area_verdict
        out["mean_brightness_over_time"] = [round(b, 1) for b in mean_brightness]
        out["brightness_trend_delta"] = round(brightness_delta, 1)
        out["temperature_trend_verdict"] = temp_verdict

    out["method_note"] = (
        f"Буфер {len(frames)}/{MAX_FRAMES} кадров mtg_fd:ir105_hrfi (10.5мкм, 1км, шаг {STEP_MINUTES} мин, "
        "crs=EPSG:4326, всегда явный TIME — не 'latest'), "
        "хранится персистентно между прогонами (FIFO) — обычный прогон докачивает только 1 новый кадр. "
        "Скорость/направление — phase correlation + despeckle по всем кадрам буфера. Ускорение/поворот — "
        "сравнение первой половины буфера со второй. Площадь/температура — доля пикселей теплее фикс. "
        "порога (60-й перцентиль самого старого кадра) и средняя яркость в радиусе "
        f"{round(fc.LOCAL_RADIUS_KM)}км, шкала НЕ калибрована в °C. Прогноз смещения — линейная "
        "экстраполяция v*t+0.5*a*t² по недавнему тренду, не физическая модель атмосферы, ошибка растёт "
        "с горизонтом (особенно на 120 мин)."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_ir_motion.py: {out.get('verdict', out.get('speed_kmh'))}")


if __name__ == "__main__":
    main()
