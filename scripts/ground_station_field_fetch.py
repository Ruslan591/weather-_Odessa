"""
ground_station_field_fetch.py — исследование УЖЕ НАЙДЕННОГО спутником
фронта/системы (data/eumetsat_frontal_track.json) через сеть наземных
станций: несколько точек вдоль оси вытянутости (elongation axis) трека
(см. ground_station_selector.py::generate_axis_samples), в каждой —
станция "впереди"/"позади" по направлению движения (select_ahead_behind,
та же геометрия, что уже используется для одиночной ahead/behind-пары в
eumetsat_ground_station_verify.py), сравнение их обсервов.

Решение и план — docs/topics/frontal_line_stations.md. Ключевое отличие
от eumetsat_ground_station_verify.py:
  1. Несколько точек вдоль оси, не одна пара в центре трека — цель
     собрать в итоге кривую вдоль фронта, а не одну точку.
  2. Порядок источников ОБРАТНЫЙ: BUFR (Meteomanz, fetch_bufr_obs.py)
     ПЕРВЫМ — многие европейские станции шлют его автоматически
     почасово; SYNOP (ogimet) — фолбэк, и то только если BUFR пуст И
     сейчас достаточно близко к синоптическому сроку (00/03/06/09/12/
     15/18/21 UTC ± окно публикации). В eumetsat_ground_station_verify.py
     порядок наоборот (SYNOP первым) — это сделано СОЗНАТЕЛЬНО и НЕ
     меняется, та узкая ahead/behind-верификация — отдельная, более
     старая задача, см. docs/topics/frontal_line_stations.md, раздел
     "ВАЖНО, чтобы не перепутать с существующим кодом".

Кэш обсервов — ПО СТАНЦИИ (wmo_synop_id), не по сэмплу/треку: одна и та
же станция может оказаться ближайшей ahead/behind сразу для нескольких
точек вдоль оси (шаг сэмплирования 60км при MAX_PERP_KM=80 в
select_ahead_behind — соседние сэмплы вполне могут "зацепить" одну и ту
же станцию) и/или для нескольких треков — дважды её не дёргаем. TTL тот
же принцип, что STALE_MINUTES в eumetsat_ground_station_verify.py.

Это ТОЛЬКО шаг сбора данных (пункт 1 плана в frontal_line_stations.md).
Интерполяция/градиент/сборка итоговой линии фронта из этих точек — ещё НЕ
реализованы, следующий шаг после того, как станет ясно на реальных
данных, что покрытие станций вообще достаточное для содержательного
сравнения (см. "Открытые вопросы" в том же файле). Пока каждый сэмпл несёт
только сырое сравнение ahead/behind (temp/ветер/давление) — простую
диагностику, не геометрическую точку пересечения линии.

Пишет data/ground_station_field.json.

Запуск: python3 scripts/ground_station_field_fetch.py
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone

from fetch_bufr_obs import fetch_latest_bufr_essentials
from ground_station_obs_fetch import fetch_latest_obs
from ground_station_selector import generate_axis_samples, select_ahead_behind

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTAL_TRACK_FILE = os.path.join(DATA_DIR, "eumetsat_frontal_track.json")
STATIONS_FILE = os.path.join(DATA_DIR, "ground_stations.json")
GEO_CONFIG_FILE = os.path.join(DATA_DIR, "geo_config.json")
OUT_FILE = os.path.join(DATA_DIR, "ground_station_field.json")

STALE_MINUTES = 45  # тот же TTL, что в eumetsat_ground_station_verify.py — не дёргать станцию чаще
SYNOP_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
SYNOP_WINDOW_MIN_AFTER = 50  # ogimet обычно публикует срок в течение ~30-50 минут после него

SAMPLE_STEP_KM = 60.0
MIN_HALF_LEN_KM = 60.0
MAX_HALF_LEN_KM = 300.0


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


def _minutes_since_last_synoptic_hour(now):
    """Минут с БЛИЖАЙШЕГО прошедшего синоптического срока (ищет среди
    сегодняшних и вчерашних часов из SYNOP_HOURS, чтобы корректно
    обработать переход через полночь — например now=00:10 должно найти
    вчерашние 21:00, а не только сегодняшние часы)."""
    best = None
    for days_back in (0, 1):
        day = (now - timedelta(days=days_back)).replace(minute=0, second=0, microsecond=0)
        for h in SYNOP_HOURS:
            candidate = day.replace(hour=h)
            if candidate <= now:
                diff_min = (now - candidate).total_seconds() / 60.0
                if best is None or diff_min < best:
                    best = diff_min
    return best


def _near_synoptic_hour(now):
    m = _minutes_since_last_synoptic_hour(now)
    return m is not None and m <= SYNOP_WINDOW_MIN_AFTER


def _fresh_enough(fetched_at_str, now):
    if not fetched_at_str:
        return False
    try:
        fetched_at = datetime.strptime(fetched_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (now - fetched_at).total_seconds() / 60.0 < STALE_MINUTES


def _get_or_fetch_station(wmo_id, cache, now):
    """BUFR-first / SYNOP-fallback-у-синоптического-срока (порядок
    ОБРАТНЫЙ относительно eumetsat_ground_station_verify.py — см.
    докстринг файла). cache — словарь {wmo_id: {"obs":..., "fetched_at":
    ...}}, мутируется на месте и возвращается вызывающим кодом целиком в
    выходной JSON (переиспользуется как кэш на следующем прогоне)."""
    cached = cache.get(wmo_id)
    if cached and _fresh_enough(cached.get("fetched_at"), now):
        return cached

    obs = None
    try:
        obs = fetch_latest_bufr_essentials(wmo_id)
    except Exception as e:
        print(f"  [WARN] ground_station_field_fetch: BUFR для {wmo_id} не сработал: {e}")

    if obs is None and _near_synoptic_hour(now):
        try:
            obs = fetch_latest_obs(wmo_id)
        except Exception as e:
            print(f"  [WARN] ground_station_field_fetch: SYNOP-фолбэк для {wmo_id} не сработал: {e}")

    entry = {"obs": obs, "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    cache[wmo_id] = entry
    return entry


def _diagnostics(ahead_obs, behind_obs):
    """Сырое сравнение ahead/behind — перепад temp/ветра/давления. НЕ
    геометрическая точка пересечения линии фронта (это следующий шаг
    плана, см. докстринг файла) — здесь только числа для последующего
    анализа/визуальной проверки на реальных данных."""
    if not ahead_obs or not behind_obs:
        return None
    d = {}
    if ahead_obs.get("temp") is not None and behind_obs.get("temp") is not None:
        d["temp_diff_behind_minus_ahead"] = round(behind_obs["temp"] - ahead_obs["temp"], 1)
    if ahead_obs.get("wind_dir_deg") is not None and behind_obs.get("wind_dir_deg") is not None:
        # нормализация в [-180, 180] — кратчайший угол поворота ahead->behind
        diff = (behind_obs["wind_dir_deg"] - ahead_obs["wind_dir_deg"] + 180) % 360 - 180
        d["wind_dir_shift_deg"] = round(diff, 0)
    if ahead_obs.get("station_pressure") is not None and behind_obs.get("station_pressure") is not None:
        d["pressure_diff_behind_minus_ahead"] = round(behind_obs["station_pressure"] - ahead_obs["station_pressure"], 1)
    return d or None


def main():
    ft = _load_json(FRONTAL_TRACK_FILE, None)
    if not ft or not ft.get("tracks"):
        print("  [WARN] ground_station_field_fetch: eumetsat_frontal_track.json недоступен/пуст")
        return

    stations = _load_json(STATIONS_FILE, [])
    if not stations:
        print("  [WARN] ground_station_field_fetch: ground_stations.json недоступен/пуст")
        return

    geo = _load_json(GEO_CONFIG_FILE, {})
    center_lat, center_lon = geo.get("center_lat"), geo.get("center_lon")
    if center_lat is None or center_lon is None:
        print("  [WARN] ground_station_field_fetch: geo_config.json без center_lat/center_lon")
        return
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))

    prev = _load_json(OUT_FILE, {"station_cache": {}})
    cache = prev.get("station_cache", {})

    now = datetime.now(timezone.utc)
    out_tracks = {}
    n_samples_total = n_fetched_before = 0
    n_fetched_before = len(cache)

    for t in ft["tracks"]:
        movement_bearing = t.get("movement_bearing_deg")
        if movement_bearing is None:
            # без направления движения ahead/behind геометрически не
            # определить (см. select_ahead_behind) — трек пропускаем целиком
            continue

        samples = generate_axis_samples(
            t.get("dx_km", 0.0), t.get("dy_km", 0.0), t.get("axis_deg"),
            t.get("area_km2"), t.get("aspect_ratio"),
            step_km=SAMPLE_STEP_KM, min_half_km=MIN_HALF_LEN_KM, max_half_km=MAX_HALF_LEN_KM,
        )

        sample_results = []
        for offset_km, dx, dy in samples:
            sel = select_ahead_behind(dx, dy, movement_bearing, stations,
                                       center_lat, center_lon, km_per_deg_lat, km_per_deg_lon)
            ahead_st, behind_st = sel["ahead"], sel["behind"]
            ahead_obs = behind_obs = None
            if ahead_st and ahead_st.get("wmo_synop_id"):
                ahead_obs = _get_or_fetch_station(ahead_st["wmo_synop_id"], cache, now)["obs"]
            if behind_st and behind_st.get("wmo_synop_id"):
                behind_obs = _get_or_fetch_station(behind_st["wmo_synop_id"], cache, now)["obs"]

            sample_results.append({
                "offset_km": offset_km,
                "dx_km": dx, "dy_km": dy,
                "ahead_station": ahead_st, "behind_station": behind_st,
                "ahead_obs": ahead_obs, "behind_obs": behind_obs,
                "diagnostics": _diagnostics(ahead_obs, behind_obs),
            })
            n_samples_total += 1

        out_tracks[str(t["track_id"])] = {
            "axis_deg": t.get("axis_deg"),
            "movement_bearing_deg": movement_bearing,
            "samples": sample_results,
        }

    out = {
        "timestamp": ft.get("timestamp"),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tracks": out_tracks,
        "station_cache": cache,
    }
    _save_json(OUT_FILE, out)
    n_new = len(cache) - n_fetched_before
    print(f"  [OK] ground_station_field_fetch: {len(out_tracks)} трек(ов), "
          f"{n_samples_total} сэмплов, станций в кэше={len(cache)} (новых в этом прогоне ~{max(n_new,0)})")


if __name__ == "__main__":
    main()
