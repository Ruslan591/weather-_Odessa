"""
europe_windshift_probe.py — РАЗОВЫЙ офлайн A/B эксперимент, НЕ production.

A — РЕАЛЬНЫЙ production baseline: detect_europe_fronts() + extract_europe_
    segments() импортируются НЕИЗМЕНЁННЫМИ из open_meteo_frontal_confirm.py.
B — тот же consensus score + wind-shift член (circular difference
    wind_direction_10m), в ОТДЕЛЬНОЙ функции этого файла — production не
    трогается. Ridge extraction (extract_europe_segments) для B — ТА ЖЕ
    самая импортированная функция, что для A, применённая к другому полю.

WIND_SHIFT_THRESHOLD_DEG=45.0 — НЕ подобран под этот эпизод. Источник:
docs/topics/frontal_line_stations.md, запись 2026-09-06 (до этого
эксперимента), тот же уровень строгости ("первая прикидка, не
откалибрована"), что уже принят для EUROPE_TEMP_GRAD_THRESHOLD/
EUROPE_PRESSURE_GRAD_THRESHOLD в самой production.

Сеть: ровно 5 запросов к Open-Meteo (1 батч на модель, 266 точек, та же
сетка/bbox, что production), через тот же open_meteo_guard.reserve_request
(общий token-bucket лимитер с production). Плюс отдельно 3 GitHub HTTPS GET
(open_meteo_frontal_confirm.py, open_meteo_guard.py, geo_config.json —
свежие с main, не git) и 1 GET существующего very_far_geocolour.png (для
overlay, уже опубликованный production-артефакт, не новый расчёт).

НИЧЕГО не пишет в data/, не коммитит, не трогает production-файлы.
Результат — только /tmp/eumetsat_europe_windshift_probe/.
"""

import io
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image, ImageDraw

TMP_DIR = "/tmp/eumetsat_europe_windshift_probe"
LIBS_DIR = os.path.join(TMP_DIR, "_repo_snapshot")
RAW_BASE = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa"
GITHUB_FETCH_TIMEOUT = 15

DEPENDENCY_FILES = [
    ("main", "scripts/open_meteo_frontal_confirm.py", os.path.join(LIBS_DIR, "scripts", "open_meteo_frontal_confirm.py")),
    ("main", "scripts/open_meteo_guard.py", os.path.join(LIBS_DIR, "scripts", "open_meteo_guard.py")),
    ("main", "scripts/open_meteo_request_log.py", os.path.join(LIBS_DIR, "scripts", "open_meteo_request_log.py")),
    ("main", "data/geo_config.json", os.path.join(LIBS_DIR, "data", "geo_config.json")),
]


def fetch_dependencies():
    for ref, repo_path, local_path in DEPENDENCY_FILES:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        url = f"{RAW_BASE}/{ref}/{repo_path}"
        r = requests.get(url, timeout=GITHUB_FETCH_TIMEOUT)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(r.content)
        print(f"[DEPS] {repo_path} <- {ref} ({len(r.content)} bytes)")


fetch_dependencies()
sys.path.insert(0, os.path.join(LIBS_DIR, "scripts"))

# Импорт РЕАЛЬНЫХ production-функций как есть — НЕ копирую их логику.
import open_meteo_guard as _om_guard  # noqa: E402
import open_meteo_frontal_confirm as _ofc  # noqa: E402

WIND_SHIFT_THRESHOLD_DEG = 45.0  # источник: frontal_line_stations.md, 2026-09-06 — см. докстринг файла

with open(os.path.join(LIBS_DIR, "data", "geo_config.json"), "r", encoding="utf-8") as f:
    GEO = json.load(f)


def circular_diff_deg(a, b):
    """((a-b+180) mod 360) - 180 — корректная кратчайшая круговая разность."""
    return ((a - b + 180.0) % 360.0) - 180.0


def wind_shift_grid(wind_dir_arr, rows, cols):
    """Аналог np.gradient, но с circular-корректной разностью соседей.
    Использует central difference там, где есть оба соседа, иначе
    forward/backward — та же схема, что np.gradient по краям."""
    shift_row = np.full((rows, cols), np.nan)
    shift_col = np.full((rows, cols), np.nan)
    for r in range(rows):
        for c in range(cols):
            if math.isnan(wind_dir_arr[r, c]):
                continue
            # строки (вдоль широты)
            if r > 0 and r < rows - 1 and not math.isnan(wind_dir_arr[r - 1, c]) and not math.isnan(wind_dir_arr[r + 1, c]):
                shift_row[r, c] = circular_diff_deg(wind_dir_arr[r + 1, c], wind_dir_arr[r - 1, c]) / 2.0
            elif r > 0 and not math.isnan(wind_dir_arr[r - 1, c]):
                shift_row[r, c] = circular_diff_deg(wind_dir_arr[r, c], wind_dir_arr[r - 1, c])
            elif r < rows - 1 and not math.isnan(wind_dir_arr[r + 1, c]):
                shift_row[r, c] = circular_diff_deg(wind_dir_arr[r + 1, c], wind_dir_arr[r, c])
            # столбцы (вдоль долготы)
            if c > 0 and c < cols - 1 and not math.isnan(wind_dir_arr[r, c - 1]) and not math.isnan(wind_dir_arr[r, c + 1]):
                shift_col[r, c] = circular_diff_deg(wind_dir_arr[r, c + 1], wind_dir_arr[r, c - 1]) / 2.0
            elif c > 0 and not math.isnan(wind_dir_arr[r, c - 1]):
                shift_col[r, c] = circular_diff_deg(wind_dir_arr[r, c], wind_dir_arr[r, c - 1])
            elif c < cols - 1 and not math.isnan(wind_dir_arr[r, c + 1]):
                shift_col[r, c] = circular_diff_deg(wind_dir_arr[r, c + 1], wind_dir_arr[r, c])
    return np.sqrt(shift_row ** 2 + shift_col ** 2)


def detect_europe_fronts_with_wind(model_results_by_id, rows, cols):
    """ЭКСПЕРИМЕНТАЛЬНАЯ функция (не в production). Та же структура, что
    _ofc.detect_europe_fronts(), + третий член max() — wind_shift/THRESH.
    MIN_MODEL_VOTES импортирован из production (не переопределяю)."""
    votes_grid = np.zeros((rows, cols), dtype=int)
    n_valid_grid = np.zeros((rows, cols), dtype=int)
    score_stack = []
    wind_shift_all = []  # для отчёта по распределению (диагностика, не влияет на порог)
    for model_id, results in model_results_by_id.items():
        if len(results) != rows * cols:
            continue
        temp_arr = np.array([r.get("temperature_2m") for r in results], dtype=float).reshape(rows, cols)
        pres_arr = np.array([r.get("pressure_msl") for r in results], dtype=float).reshape(rows, cols)
        wind_arr = np.array([r.get("wind_direction_10m") for r in results], dtype=float).reshape(rows, cols)
        valid = ~np.isnan(temp_arr) & ~np.isnan(pres_arr) & ~np.isnan(wind_arr)
        n_valid_grid += valid.astype(int)

        gy_t, gx_t = np.gradient(temp_arr)
        grad_t = np.sqrt(gx_t ** 2 + gy_t ** 2)
        gy_p, gx_p = np.gradient(pres_arr)
        grad_p = np.sqrt(gx_p ** 2 + gy_p ** 2)
        w_shift = wind_shift_grid(wind_arr, rows, cols)
        wind_shift_all.append(w_shift[valid])

        score = np.maximum(
            np.maximum(grad_t / _ofc.EUROPE_TEMP_GRAD_THRESHOLD, grad_p / _ofc.EUROPE_PRESSURE_GRAD_THRESHOLD),
            w_shift / WIND_SHIFT_THRESHOLD_DEG,
        )
        score = np.where(valid, score, np.nan)
        front_like = (score > 1.0) & valid
        votes_grid += front_like.astype(int)
        score_stack.append(score)

    confirmed = (votes_grid >= _ofc.MIN_MODEL_VOTES) & (n_valid_grid >= _ofc.MIN_MODEL_VOTES)
    if score_stack:
        stacked = np.stack(score_stack, axis=0)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            consensus_score_grid = np.nanmedian(stacked, axis=0)
    else:
        consensus_score_grid = np.full((rows, cols), np.nan)

    wind_shift_flat = np.concatenate(wind_shift_all) if wind_shift_all else np.array([])
    wind_shift_stats = {
        "n": int(wind_shift_flat.size),
        "mean": float(np.mean(wind_shift_flat)) if wind_shift_flat.size else None,
        "median": float(np.median(wind_shift_flat)) if wind_shift_flat.size else None,
        "p90": float(np.percentile(wind_shift_flat, 90)) if wind_shift_flat.size else None,
        "max": float(np.max(wind_shift_flat)) if wind_shift_flat.size else None,
        "frac_above_threshold": float(np.mean(wind_shift_flat > WIND_SHIFT_THRESHOLD_DEG)) if wind_shift_flat.size else None,
    }
    return votes_grid, n_valid_grid, confirmed, consensus_score_grid, wind_shift_stats


def draw_segments(img, segments, color, geo):
    segs_px, _far_wh, _vf_wh = _ofc._attach_pixel_coords_to_segments(segments, geo)
    draw = ImageDraw.Draw(img)
    for seg in segs_px:
        pts = [tuple(p["px_very_far"]) for p in seg["path"] if p.get("px_very_far")]
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=4)
    return img


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "wind_shift_threshold_deg": WIND_SHIFT_THRESHOLD_DEG,
              "wind_shift_threshold_source": "docs/topics/frontal_line_stations.md, 2026-09-06 (до эксперимента)"}

    bbox = _ofc._europe_grid_bbox(GEO)
    points, rows, cols, lats, lons = _ofc.build_europe_grid(bbox)
    result["bbox"] = list(bbox)
    result["grid"] = {"rows": rows, "cols": cols, "n_points": len(points)}
    print(f"[GRID] {rows}x{cols} = {len(points)} точек, bbox={bbox}")

    model_results_by_id = {}
    request_log = []
    for i, (model_id, label) in enumerate(_ofc.MODELS):
        decision = _om_guard.reserve_request("forecast_or_archive")
        t0 = time.monotonic()
        entry = {"model": model_id, "gate_decision": decision}
        if decision == "skip":
            print(f"[SKIP] {model_id}: guard вернул skip (общий лимитер занят) — цикл прерван, повторов нет")
            request_log.append(entry)
            break
        try:
            vals = _ofc.fetch_model_batch(model_id, points)
            _om_guard.report_request_result("forecast_or_archive", "success")
            entry["status"] = "ok"
            entry["elapsed_sec"] = round(time.monotonic() - t0, 2)
            entry["n_results"] = len(vals) if vals else 0
            model_results_by_id[model_id] = vals
            print(f"[OK] {model_id}: {entry['n_results']} точек, {entry['elapsed_sec']}с")
        except Exception as e:
            entry["status"] = f"error: {e}"
            print(f"[ERROR] {model_id}: {e}")
        request_log.append(entry)
        if i < len(_ofc.MODELS) - 1:
            time.sleep(_ofc.REQUEST_INTERVAL)

    result["request_log"] = request_log
    result["n_models_ok"] = len(model_results_by_id)

    # Сохраняю сырые ответы ОДИН раз (не по копии на A и на B) — оба
    # варианта считаются из этого же словаря ниже.
    with open(os.path.join(TMP_DIR, "raw_model_results.json"), "w", encoding="utf-8") as f:
        json.dump(model_results_by_id, f)

    if not model_results_by_id:
        result["error"] = "ни одна модель не ответила успешно"
        with open(os.path.join(TMP_DIR, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("[STOP] нет данных ни от одной модели")
        return

    # --- A: РЕАЛЬНЫЙ production baseline, функции не изменены ---
    votes_A, n_valid_A, confirmed_A, score_A = _ofc.detect_europe_fronts(model_results_by_id, rows, cols)
    segments_A, n_components_A, n_ridge_A = _ofc.extract_europe_segments(score_A, confirmed_A, lats, lons)

    # --- B: baseline + wind-shift, ТА ЖЕ extract_europe_segments ---
    votes_B, n_valid_B, confirmed_B, score_B, wind_stats = detect_europe_fronts_with_wind(model_results_by_id, rows, cols)
    segments_B, n_components_B, n_ridge_B = _ofc.extract_europe_segments(score_B, confirmed_B, lats, lons)

    def summarize(segments, n_components, n_ridge, confirmed):
        lengths = [s["path_length"] for s in segments]
        scores = [s["avg_score"] for s in segments if s["avg_score"] is not None]
        return {
            "n_confirmed_cells": int(confirmed.sum()),
            "n_ridge_cells": n_ridge,
            "n_components": n_components,
            "n_segments_after_filters": len(segments),
            "segment_lengths": lengths,
            "segment_avg_scores": scores,
            "mean_segment_score": float(np.mean(scores)) if scores else None,
            "median_segment_score": float(np.median(scores)) if scores else None,
        }

    result["A_baseline"] = summarize(segments_A, n_components_A, n_ridge_A, confirmed_A)
    result["A_baseline"]["segments"] = segments_A
    result["B_wind_shift"] = summarize(segments_B, n_components_B, n_ridge_B, confirmed_B)
    result["B_wind_shift"]["segments"] = segments_B
    result["wind_shift_distribution"] = wind_stats

    # --- Overlay на существующий (не новый) very_far_geocolour.png ---
    try:
        geocolour_url = f"{RAW_BASE}/main/data/anim/very_far_geocolour.png"
        r = requests.get(geocolour_url, timeout=GITHUB_FETCH_TIMEOUT)
        r.raise_for_status()
        img_A = Image.open(io.BytesIO(r.content)).convert("RGB")
        img_B = img_A.copy()
        img_both = img_A.copy()
        draw_segments(img_A, segments_A, (255, 0, 255), GEO)       # magenta = A
        draw_segments(img_B, segments_B, (0, 255, 255), GEO)       # cyan = B
        draw_segments(img_both, segments_A, (255, 0, 255), GEO)
        draw_segments(img_both, segments_B, (0, 255, 255), GEO)
        img_A.save(os.path.join(TMP_DIR, "overlay_A_baseline.png"))
        img_B.save(os.path.join(TMP_DIR, "overlay_B_windshift.png"))
        img_both.save(os.path.join(TMP_DIR, "overlay_A_and_B.png"))
        result["overlay_saved"] = True
    except Exception as e:
        result["overlay_saved"] = False
        result["overlay_error"] = str(e)

    with open(os.path.join(TMP_DIR, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[A] components={n_components_A} ridge_cells={n_ridge_A} segments={len(segments_A)} lengths={[s['path_length'] for s in segments_A]}")
    print(f"[B] components={n_components_B} ridge_cells={n_ridge_B} segments={len(segments_B)} lengths={[s['path_length'] for s in segments_B]}")
    print(f"[wind_shift] mean={wind_stats['mean']} median={wind_stats['median']} p90={wind_stats['p90']} frac_above_45deg={wind_stats['frac_above_threshold']}")
    print(f"\nГотово: {TMP_DIR}/result.json")


if __name__ == "__main__":
    main()
