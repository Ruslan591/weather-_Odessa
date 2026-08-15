"""
eumetsat_frontal_track.py — трекинг фронтоподобных систем во времени
(см. docs/topics/eumetsat.md, план "Отслеживание фронтов", шаг 3, 2026-08-14).

Читает ТОЛЬКО data/eumetsat_cloud_forecast.json (candidates с class="system",
frontlike=True, window_spanning=False — ненадёжные по площади/форме объекты
в трек не берём, см. шаг 1 плана). WMS/сеть не трогает, чистая локальная
обработка уже посчитанных полей — дёшево, гейта по времени не требует, но
идемпотентно: если cloud_forecast.json не обновился с прошлого запуска
(тот сам гейтится 15 мин, а этот скрипт может быть вызван чаще), просто
ничего не делает — иначе один и тот же кадр учтётся как "новая точка" с
dt≈0 и заведомо мусорной скоростью.

Персистентное состояние: data/eumetsat_frontal_track_state.json — полная
история точек по каждому треку (ограничена MAX_POINTS_PER_TRACK), плюс
счётчик track_id (монотонный, не переиспользуется, чтобы id не путались
между разными физическими системами).

Публичный выход: data/eumetsat_frontal_track.json — сводка по активным
трекам (только что подтверждённым в этом цикле) для потребителей
(target_summary/фронтенд — подключение отдельным шагом, не в этом файле).

Сопоставление кадр-к-кадру (matching) — простое "жадное ближайший сосед"
(не Hungarian): при обычно 0-6 фронтоподобных объектов за цикл разница
пренебрежима, а код на порядок проще. max_dist_km растёт с dt (реальные
фронты движутся быстро) + минимальный пол на джиттер измерения:
  max_dist_km = JITTER_FLOOR_KM + SPEED_CAP_KMH * dt_hours
SPEED_CAP_KMH=100 — щедрый потолок (типичный холодный фронт 20-50км/ч,
с запасом на редкие быстрые случаи и на неточность самого centroid при
объединении/разделении пятен между кадрами).
"""

import json
import math
import os
from datetime import datetime, timezone

from ground_station_selector import select_ahead_behind

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CLOUD_FORECAST_FILE = os.path.join(DATA_DIR, "eumetsat_cloud_forecast.json")
STATE_FILE = os.path.join(DATA_DIR, "eumetsat_frontal_track_state.json")
OUT_FILE = os.path.join(DATA_DIR, "eumetsat_frontal_track.json")

PRECIP_FORECAST_FILE = os.path.join(DATA_DIR, "eumetsat_precip_forecast.json")
LIGHTNING_FORECAST_FILE = os.path.join(DATA_DIR, "eumetsat_lightning_forecast.json")
GEO_CONFIG_FILE = os.path.join(DATA_DIR, "geo_config.json")
GROUND_STATIONS_FILE = os.path.join(DATA_DIR, "ground_stations.json")

# CENTER_LAT/CENTER_LON/KM_PER_DEG_* — та же геометрия, что в
# field_motion_common.py (единый источник правды — geo_config.json), но
# читаем geo_config.json НАПРЯМУЮ, а не импортируем field_motion_common —
# он тянет numpy/PIL/scipy/requests, а этот скрипт по замыслу лёгкий и
# сеть/тяжёлые зависимости не трогает (см. докстринг модуля выше).
with open(GEO_CONFIG_FILE, "r", encoding="utf-8") as _f:
    _GEO = json.load(_f)
CENTER_LAT = _GEO["center_lat"]
CENTER_LON = _GEO["center_lon"]
KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(CENTER_LAT))

MAX_POINTS_PER_TRACK = 12     # ~2-3ч истории при обычном шаге 10-15 мин
STALE_TRACK_MINUTES = 90      # трек без новых точек дольше этого — удаляется
JITTER_FLOOR_KM = 40          # допуск на шум centroid даже при dt->0
SPEED_CAP_KMH = 100           # потолок правдоподобной скорости движения фронта
MIN_POINTS_FOR_VELOCITY = 3   # меньше — публикуем трек, но без velocity (шумно)

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def _compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def _bearing_compass(dx_km, dy_km):
    bearing = (math.degrees(math.atan2(dx_km, dy_km)) + 360) % 360
    return bearing, _compass(bearing)


def _axis_angle_diff(a_deg, b_deg):
    """Кратчайшая разница между двумя ОСЕВЫМИ (0..180, линия, не вектор)
    углами — например 5° и 175° отличаются на 10°, не на 170°."""
    d = abs(a_deg - b_deg) % 180
    return min(d, 180 - d)


def _parse_ts(ts_str):
    return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in ts_str
                              else "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _by_target_id(path, key_name="system_analysis_all"):
    """Тот же приём, что в eumetsat_target_summary.py — читаем ГОТОВЫЙ
    анализ по каждому target_id из precip_forecast/lightning_forecast (сами
    ничего не пересчитываем). Не импортируем target_summary.py напрямую —
    оба модуля читают эти файлы независимо и параллельно, тот же паттерн,
    что уже принят в проекте (cloud_phase_type/precip_forecast/
    lightning_forecast все пишут в общий формат, а не завязаны друг на
    друга)."""
    data = _load_json(path, None)
    rows = (data or {}).get(key_name) or []
    return {r["target_id"]: r for r in rows}


def main():
    cf = _load_json(CLOUD_FORECAST_FILE, None)
    if not cf or "timestamp" not in cf:
        print("  [WARN] eumetsat_frontal_track: eumetsat_cloud_forecast.json недоступен/пуст")
        return

    cf_ts_str = cf["timestamp"]
    cf_ts = _parse_ts(cf_ts_str)

    state = _load_json(STATE_FILE, {"last_processed_timestamp": None, "next_track_id": 0, "tracks": []})

    # Идемпотентность — cloud_forecast.py не обновлялся с прошлого запуска
    # (собственный гейт 15 мин), нет смысла и вредно считать это новым кадром.
    if state.get("last_processed_timestamp") == cf_ts_str:
        return

    frontlike_now = [
        c for c in cf.get("candidates", [])
        if c.get("class") == "system" and c.get("frontlike") is True
        and not c.get("window_spanning", False)
    ]

    tracks = state.get("tracks", [])
    next_track_id = state.get("next_track_id", 0)

    # Гейт устаревания — трек без новых точек дольше STALE_TRACK_MINUTES
    # считается распавшимся/ушедшим из окна обзора, удаляем, чтобы не расти
    # бесконечно и не путать будущий matching с призраками.
    fresh_tracks = []
    for t in tracks:
        last_pt = t["points"][-1]
        last_ts = _parse_ts(last_pt["ts"])
        age_min = (cf_ts - last_ts).total_seconds() / 60.0
        if age_min <= STALE_TRACK_MINUTES:
            fresh_tracks.append(t)
    tracks = fresh_tracks

    # Matching: жадный ближайший сосед, каждый трек и каждый текущий
    # кандидат используются не больше одного раза.
    used_track_idx = set()
    used_cand_idx = set()
    pairs = []  # (dist_km, track_idx, cand_idx)
    for ti, t in enumerate(tracks):
        last_pt = t["points"][-1]
        last_ts = _parse_ts(last_pt["ts"])
        dt_hours = max((cf_ts - last_ts).total_seconds() / 3600.0, 1e-6)
        max_dist_km = JITTER_FLOOR_KM + SPEED_CAP_KMH * dt_hours
        for ci, c in enumerate(frontlike_now):
            dist_km = math.hypot(
                c["centroid_dx_km"] - last_pt["dx_km"],
                c["centroid_dy_km"] - last_pt["dy_km"],
            )
            if dist_km <= max_dist_km:
                pairs.append((dist_km, ti, ci))
    pairs.sort(key=lambda p: p[0])
    for dist_km, ti, ci in pairs:
        if ti in used_track_idx or ci in used_cand_idx:
            continue
        used_track_idx.add(ti)
        used_cand_idx.add(ci)
        c = frontlike_now[ci]
        tracks[ti]["points"].append({
            "ts": cf_ts_str,
            "dx_km": c["centroid_dx_km"],
            "dy_km": c["centroid_dy_km"],
            "axis_deg": c.get("elongation_axis_deg"),
            "aspect_ratio": c.get("elongation_aspect_ratio"),
            "area_km2": c.get("area_km2"),
            "target_id": c.get("target_id"),
        })
        tracks[ti]["points"] = tracks[ti]["points"][-MAX_POINTS_PER_TRACK:]
        tracks[ti]["last_seen"] = cf_ts_str

    # Непойманные кандидаты этого кадра — новые треки.
    for ci, c in enumerate(frontlike_now):
        if ci in used_cand_idx:
            continue
        tracks.append({
            "track_id": next_track_id,
            "first_seen": cf_ts_str,
            "last_seen": cf_ts_str,
            "points": [{
                "ts": cf_ts_str,
                "dx_km": c["centroid_dx_km"],
                "dy_km": c["centroid_dy_km"],
                "axis_deg": c.get("elongation_axis_deg"),
                "aspect_ratio": c.get("elongation_aspect_ratio"),
                "area_km2": c.get("area_km2"),
                "target_id": c.get("target_id"),
            }],
        })
        next_track_id += 1

    state = {
        "last_processed_timestamp": cf_ts_str,
        "next_track_id": next_track_id,
        "tracks": tracks,
    }
    _save_json(STATE_FILE, state)

    # Публичный выход — только треки, ПОЙМАННЫЕ в ЭТОМ кадре (last_seen ==
    # текущий timestamp); устаревшие треки в состоянии остаются (для
    # будущего matching), но наружу как "активные" не показываем.
    # Осадки/гроза — по запросу 2026-08-14 ("подключи осадки и грозы в
    # таблицу"): смотрим по target_id ПОСЛЕДНЕЙ точки трека (тот кандидат
    # cloud_forecast, к которому трек привязан ПРЯМО СЕЙЧАС) — если этот
    # target_id уже не встречается в свежих precip/lightning-файлах (они
    # сами гейтятся по своим интервалам, могут немного отставать от
    # cloud_forecast) — оба поля None (не False!), это "не проверено в
    # этом кадре", не "точно нет". None рисуется на фронтенде как "?", не
    # как "—", чтобы это различие было видно.
    precip_by_id = _by_target_id(PRECIP_FORECAST_FILE)
    lightning_by_id = _by_target_id(LIGHTNING_FORECAST_FILE)

    # База наземных станций — план шага 5, пункт 2/4 (2026-08-15). Читается
    # один раз на весь запуск (140 станций, копеечный файл), не в цикле по
    # трекам. Если файла нет (ещё не сгенерирован) — ahead_station/
    # behind_station будут None у всех треков, остальной вывод не ломается.
    ground_stations = _load_json(GROUND_STATIONS_FILE, [])

    out_tracks = []
    for t in tracks:
        if t["last_seen"] != cf_ts_str:
            continue
        pts = t["points"]
        latest = pts[-1]
        entry = {
            "track_id": t["track_id"],
            "first_seen": t["first_seen"],
            "last_seen": t["last_seen"],
            "points_count": len(pts),
            "age_minutes": round((cf_ts - _parse_ts(t["first_seen"])).total_seconds() / 60.0, 1),
            "distance_from_odessa_km": round(math.hypot(latest["dx_km"], latest["dy_km"]), 1),
            # Точные координаты (не только округлённое расстояние + 8-секторное
            # направление) — нужны для точной отрисовки на снимке GeoColour
            # (см. field_motion_common.draw_frontal_tracks_overlay(), запрос
            # 2026-08-14 "подсветить найденные фронты"). Та же система
            # координат, что везде в проекте (km от центра Одессы, dx=восток,
            # dy=север) — см. fc.pixel_to_km_offset().
            "dx_km": round(latest["dx_km"], 2),
            "dy_km": round(latest["dy_km"], 2),
            "area_km2": round(latest["area_km2"], 1) if latest.get("area_km2") is not None else None,
            "axis_deg": latest.get("axis_deg"),
            "aspect_ratio": latest.get("aspect_ratio"),
            "velocity_kmh": None,
            "movement_bearing_deg": None,
            "movement_bearing_compass": None,
            "axis_rotation_deg": None,
            # Станция "впереди"/"позади" вдоль оси движения трека (план
            # шага 5, пункт 4, 2026-08-15) — заполняются ниже, только если
            # movement_bearing_deg известен (нужна скорость/направление,
            # см. select_ahead_behind: без bearing выбор станции "по
            # курсу" не имеет смысла). Пока None по умолчанию.
            "ahead_station": None,
            "behind_station": None,
        }
        _, entry["direction_compass"] = _bearing_compass(latest["dx_km"], latest["dy_km"])

        latest_tid = latest.get("target_id")
        pr = precip_by_id.get(latest_tid) if latest_tid is not None else None
        lt = lightning_by_id.get(latest_tid) if latest_tid is not None else None
        entry["has_precip"] = pr.get("has_precip") if pr else None
        entry["has_lightning"] = lt.get("has_lightning") if lt else None

        if len(pts) >= MIN_POINTS_FOR_VELOCITY:
            first = pts[0]
            dt_hours = (cf_ts - _parse_ts(first["ts"])).total_seconds() / 3600.0
            if dt_hours > 1e-6:
                ddx = latest["dx_km"] - first["dx_km"]
                ddy = latest["dy_km"] - first["dy_km"]
                dist_km = math.hypot(ddx, ddy)
                entry["velocity_kmh"] = round(dist_km / dt_hours, 1)
                bearing, compass = _bearing_compass(ddx, ddy)
                entry["movement_bearing_deg"] = round(bearing, 1)
                entry["movement_bearing_compass"] = compass
                if first.get("axis_deg") is not None and latest.get("axis_deg") is not None:
                    entry["axis_rotation_deg"] = round(
                        _axis_angle_diff(first["axis_deg"], latest["axis_deg"]), 1
                    )

                # Станции вдоль курса трека — план шага 5, пункт 4. Только
                # чистая геометрия (см. ground_station_selector.py), сеть
                # НЕ трогается — реальные наблюдения (SYNOP) по выбранным
                # станциям забирает отдельный скрипт
                # eumetsat_ground_station_verify.py (тот же паттерн
                # разделения, что precip_forecast/lightning_forecast:
                # отдельный файл, читается здесь по id, не по прямому
                # вызову сети).
                if ground_stations:
                    selection = select_ahead_behind(
                        entry["dx_km"], entry["dy_km"], entry["movement_bearing_deg"],
                        ground_stations, CENTER_LAT, CENTER_LON,
                        KM_PER_DEG_LAT, KM_PER_DEG_LON,
                    )
                    entry["ahead_station"] = selection["ahead"]
                    entry["behind_station"] = selection["behind"]
        out_tracks.append(entry)

    out = {
        "timestamp": cf_ts_str,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tracks": out_tracks,
    }
    _save_json(OUT_FILE, out)
    print(f"  [OK] eumetsat_frontal_track: {len(out_tracks)} активных трек(ов) "
          f"из {len(frontlike_now)} frontlike-кандидатов кадра")


if __name__ == "__main__":
    main()
