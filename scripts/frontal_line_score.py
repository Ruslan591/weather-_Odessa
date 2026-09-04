"""
frontal_line_score.py — шаг 4 плана (docs/topics/frontal_line_stations.md):
сверка ЧЕРНОВОЙ линии/поля Open-Meteo (open_meteo_field.json) с РЕАЛЬНЫМИ
обсервами станций (ground_station_field.json). Обе системы уже в ОДНОЙ
системе координат (along_km/perp_km относительно оси трека axis_deg) —
along_km у ground_station_field.json samples совпадает по построению с
along_km строк сетки Open-Meteo (обе используют offset вдоль axis_deg от
центра трека), поэтому сверка — это прямой lookup по ближайшей ячейке
сетки, без интерполяции.

Идея: для каждой пары ahead/behind станций (offset вдоль оси) берём их
РЕАЛЬНЫЙ перепад temp (diagnostics.temp_diff_behind_minus_ahead из
ground_station_field.json). Для каждой из 8 моделей — какой перепад temp
МОДЕЛЬ предсказывает МЕЖДУ ЭТИМИ ЖЕ ДВУМЯ ТОЧКАМИ (ближайшие ячейки сетки
к позиции ahead и к позиции behind). Модель с наименьшей ошибкой
(|предсказанный - реальный|), усреднённой по всем чекпоинтам трека —
считается точнее положившей фронт для ЭТОГО трека и momента.

Это НЕ окончательная линия фронта — это скоринг, какая модель ей ближе.
Итоговая отрисовка (три слоя: спутник/модель/станции) — шаг 5, ещё не
сделан.

Пишет data/frontal_line_score.json.

Запуск: python3 scripts/frontal_line_score.py
"""
import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OPEN_METEO_FIELD_FILE = os.path.join(DATA_DIR, "open_meteo_field.json")
GROUND_STATION_FIELD_FILE = os.path.join(DATA_DIR, "ground_station_field.json")
OUT_FILE = os.path.join(DATA_DIR, "frontal_line_score.json")


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


def _nearest_index(values, target):
    """Индекс элемента values, ближайшего к target. values — обычный
    список чисел (along_km или perp_km сетки), не numpy — сетки тут
    маленькие (≤~15 элементов), линейный поиск оправдан, без scipy."""
    return min(range(len(values)), key=lambda i: abs(values[i] - target))


def _model_temp_at(model_data, along_km, perp_km):
    """Значение temp_grid модели в ближайшей ячейке к (along_km, perp_km).
    Возвращает None, если модель не отдала эту точку (temp is None —
    Open-Meteo иногда отдаёт null для отдельных точек батча)."""
    ai = _nearest_index(model_data["along_km"], along_km)
    pi = _nearest_index(model_data["perp_km"], perp_km)
    return model_data["temp_grid"][ai][pi]


def score_track(om_track, gs_track):
    """Возвращает {model_id: {"mean_abs_error": .., "n_checkpoints": ..}}
    и best_model (мин. mean_abs_error среди моделей с >=1 чекпоинтом)."""
    models = om_track.get("models", {})
    per_model_errors = {mid: [] for mid in models}

    checkpoints = []
    for sample in gs_track.get("samples", []):
        diag = sample.get("diagnostics")
        ahead_st, behind_st = sample.get("ahead_station"), sample.get("behind_station")
        if not diag or diag.get("temp_diff_behind_minus_ahead") is None:
            continue
        if not ahead_st or not behind_st:
            continue
        real_diff = diag["temp_diff_behind_minus_ahead"]
        cp = {"offset_km": sample["offset_km"], "real_diff": real_diff, "model_predicted": {}}
        for mid, mdata in models.items():
            t_ahead = _model_temp_at(mdata, ahead_st["along_km"], ahead_st["perp_km"])
            t_behind = _model_temp_at(mdata, behind_st["along_km"], behind_st["perp_km"])
            if t_ahead is None or t_behind is None:
                continue
            predicted_diff = t_behind - t_ahead
            cp["model_predicted"][mid] = round(predicted_diff, 2)
            per_model_errors[mid].append(abs(predicted_diff - real_diff))
        checkpoints.append(cp)

    model_scores = {}
    for mid, errors in per_model_errors.items():
        if errors:
            model_scores[mid] = {
                "mean_abs_error": round(sum(errors) / len(errors), 2),
                "n_checkpoints": len(errors),
            }
    best_model = min(model_scores, key=lambda m: model_scores[m]["mean_abs_error"]) if model_scores else None

    return {
        "checkpoints": checkpoints,
        "model_scores": model_scores,
        "best_model": best_model,
    }


def main():
    om_data = _load_json(OPEN_METEO_FIELD_FILE, None)
    gs_data = _load_json(GROUND_STATION_FIELD_FILE, None)
    if not om_data or not gs_data:
        print("  [WARN] frontal_line_score: open_meteo_field.json/ground_station_field.json недоступны")
        return

    om_tracks = om_data.get("tracks", {})
    gs_tracks = gs_data.get("tracks", {})
    common_ids = set(om_tracks) & set(gs_tracks)

    out_tracks = {}
    for tid in common_ids:
        out_tracks[tid] = score_track(om_tracks[tid], gs_tracks[tid])

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "om_timestamp": om_data.get("timestamp"),
        "gs_timestamp": gs_data.get("timestamp"),
        "tracks": out_tracks,
    }
    _save_json(OUT_FILE, out)
    n_scored = sum(1 for t in out_tracks.values() if t["best_model"])
    print(f"  [OK] frontal_line_score: {len(out_tracks)} общих трек(ов), "
          f"{n_scored} с достаточными данными для скоринга")


if __name__ == "__main__":
    main()
