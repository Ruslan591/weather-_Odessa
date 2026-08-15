"""
eumetsat_ground_station_verify.py — реальные наблюдения (SYNOP) по
станциям "впереди"/"позади" активных треков фронтов (план шага 5, пункт 4,
2026-08-15, продолжение).

Читает data/eumetsat_frontal_track.json (поля ahead_station/behind_station,
уже посчитанные там geometry-функцией select_ahead_behind — см.
eumetsat_frontal_track.py). Для каждой станции с известным wmo_synop_id
дёргает ogimet через ground_station_obs_fetch.fetch_latest_obs() — ЭТО
единственный скрипт в цепочке шага 5, который трогает сеть, специально
вынесен из eumetsat_frontal_track.py (тот остаётся "чистой локальной
обработкой", как и был задуман изначально, см. докстринг там).

Пишет data/eumetsat_ground_station_verify.json — {"track_id": {ahead_obs,
behind_obs}}. eumetsat_frontal_track.py читает этот файл НА СЛЕДУЮЩЕМ
цикле и подмешивает в свой публичный вывод — тот же паттерн лага в один
цикл, что уже есть у precip_by_id/lightning_by_id (см. комментарий в
eumetsat_frontal_track.py про "могут немного отставать").

Гейт по времени (STALE_MINUTES) — SYNOP реально обновляется раз в 3ч,
дёргать ogimet каждый 15-минутный цикл пайплайна бессмысленно и рискованно
для рейт-лимитов ogimet/прокси. Если для данной станции уже есть
достаточно свежий fetch (моложе STALE_MINUTES) — не перезапрашиваем,
переиспользуем прошлый результат из уже существующего файла.
"""

import json
import os
from datetime import datetime, timezone

from ground_station_obs_fetch import fetch_latest_obs

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FRONTAL_TRACK_FILE = os.path.join(DATA_DIR, "eumetsat_frontal_track.json")
OUT_FILE = os.path.join(DATA_DIR, "eumetsat_ground_station_verify.json")

STALE_MINUTES = 45  # не перезапрашивать станцию, если fetch моложе этого


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


def _parse_iso(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fresh_enough(fetched_at_str, now):
    fetched_at = _parse_iso(fetched_at_str)
    if fetched_at is None:
        return False
    age_min = (now - fetched_at).total_seconds() / 60.0
    return age_min < STALE_MINUTES


def _get_or_fetch(existing_entry, wmo_synop_id, now):
    """existing_entry — прошлый результат для ЭТОЙ ЖЕ станции (или None).
    Возвращает (obs_dict_или_None, fetched_at_str, from_cache_bool)."""
    if existing_entry and existing_entry.get("wmo_synop_id") == wmo_synop_id:
        if _fresh_enough(existing_entry.get("fetched_at"), now):
            return existing_entry.get("obs"), existing_entry.get("fetched_at"), True

    obs = fetch_latest_obs(wmo_synop_id)
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return obs, fetched_at, False


def main():
    ft = _load_json(FRONTAL_TRACK_FILE, None)
    if not ft or "tracks" not in ft:
        print("  [WARN] eumetsat_ground_station_verify: eumetsat_frontal_track.json недоступен/пуст")
        return

    prev = _load_json(OUT_FILE, {"tracks": {}})
    prev_tracks = prev.get("tracks", {})

    now = datetime.now(timezone.utc)
    out_tracks = {}
    n_fetched = n_cached = n_skipped = 0

    for t in ft["tracks"]:
        track_id = str(t["track_id"])
        prev_entry = prev_tracks.get(track_id, {})
        result = {"ahead_obs": None, "behind_obs": None,
                  "ahead_wmo_synop_id": None, "behind_wmo_synop_id": None,
                  "ahead_fetched_at": None, "behind_fetched_at": None}

        for side in ("ahead", "behind"):
            station = t.get(f"{side}_station")
            if not station or not station.get("wmo_synop_id"):
                n_skipped += 1
                continue
            wmo_id = station["wmo_synop_id"]
            prev_side = prev_entry.get(f"{side}_raw")
            obs, fetched_at, from_cache = _get_or_fetch(prev_side, wmo_id, now)
            if from_cache:
                n_cached += 1
            else:
                n_fetched += 1
            result[f"{side}_obs"] = obs
            result[f"{side}_wmo_synop_id"] = wmo_id
            result[f"{side}_fetched_at"] = fetched_at
            # Сохраняем "сырую" версию для кеша следующего цикла (с той же
            # структурой, что читает _get_or_fetch).
            result[f"{side}_raw"] = {"wmo_synop_id": wmo_id, "obs": obs, "fetched_at": fetched_at}

        out_tracks[track_id] = result

    out = {
        "timestamp": ft.get("timestamp"),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tracks": out_tracks,
    }
    _save_json(OUT_FILE, out)
    print(f"  [OK] eumetsat_ground_station_verify: {len(out_tracks)} трек(ов), "
          f"fetch={n_fetched} cache={n_cached} skip(нет станции)={n_skipped}")


if __name__ == "__main__":
    main()
