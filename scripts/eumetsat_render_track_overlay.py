"""eumetsat_render_track_overlay.py — финальная сборка CLM-снимков (near+west)
с покраской РЕАЛЬНОЙ формы фронта по маске пикселей, вместо PCA-эллипса.

Запускается в оркестраторе ПОСЛЕ eumetsat_frontal_track.py (см. порядок в
gh_satellite_pipeline.py) — к этому моменту data/eumetsat_frontal_track.json
уже содержит current_target_id для треков, подтверждённых В ЭТОМ кадре
(см. изменения в eumetsat_frontal_track.py, 2026-08-19). Раньше (до этой
правки) снимок красился ПРЯМО в cloud_forecast.py/west_watch.py, ДО
frontal_track.py — треки были минимум на 1 цикл устаревшими (тот фронт уже
физически сместился), а сама линия — приближение PCA-эллипсом, не реальный
контур блоба. См. docs/topics/eumetsat.md, обсуждение 2026-08-19
(пользователь: "может проще просто подкрашивать пиксели с фронтами разными
цветами?").

Не делает НИКАКИХ сетевых запросов — только читает scratch-файлы,
записанные cloud_forecast.py/eumetsat_west_watch.py в ЭТОМ ЖЕ прогоне job'а
(они не коммитятся в git, живут только в рамках одного запуска пайплайна —
все шаги работают в общей рабочей папке, без git между ними).

Если scratch-файлы отсутствуют для тайла (cloud_forecast.py/west_watch.py
не писали новых данных в этом цикле — свой internal-гейт source_stale или
orchestrator-гейт по времени) — тайл тихо пропускается, прежний
eumetsat_*_snapshot_clm.png остаётся как есть. Это обычный холостой цикл,
не ошибка.
"""
import json
import os

import numpy as np
from PIL import Image

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FRONTAL_TRACK_FILE = os.path.join(BASE_DIR, "data", "eumetsat_frontal_track.json")

NEAR_SCRATCH_BASE = os.path.join(BASE_DIR, "data", "_scratch_clm_base.png")
NEAR_SCRATCH_PIXELMAP = os.path.join(BASE_DIR, "data", "_scratch_clm_pixelmap.npy")
NEAR_OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_clm_snapshot.png")

WEST_SCRATCH_BASE = os.path.join(BASE_DIR, "data", "_scratch_west_clm_base.png")
WEST_SCRATCH_PIXELMAP = os.path.join(BASE_DIR, "data", "_scratch_west_pixelmap.npy")
WEST_OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_snapshot_clm.png")


def _render_tile(scratch_base_path, scratch_pixelmap_path, out_path,
                  tracks_for_tile, origin_dx_km, origin_dy_km):
    """Красит реальные пиксели блоба (по pixel_map == current_target_id+1)
    в цвет трека, поверх сохранённой базы (уже с контуром берега/кругом
    обзора, без треков/маркера — см. cloud_forecast.py/west_watch.py),
    дорисовывает маркер Одессы поверх покраски, сохраняет финальный PNG."""
    if not (os.path.exists(scratch_base_path) and os.path.exists(scratch_pixelmap_path)):
        return "skipped_no_scratch"
    try:
        base_img = Image.open(scratch_base_path).convert("RGB")
        pixel_map = np.load(scratch_pixelmap_path)
        arr = np.array(base_img)
        painted = 0
        for t in tracks_for_tile:
            tid = t.get("current_target_id")
            if tid is None:
                continue  # трек не подтверждён В ЭТОМ кадре — красить нечего
            mask = pixel_map == (tid + 1)
            if not mask.any():
                continue
            color = fc.FRONTAL_TRACK_COLORS[t["track_id"] % len(fc.FRONTAL_TRACK_COLORS)]
            arr[mask] = color
            painted += 1
        out_img = Image.fromarray(arr, mode="RGB")
        out_img = fc.draw_odessa_marker(out_img, origin_dx_km=origin_dx_km, origin_dy_km=origin_dy_km)
        out_img.save(out_path)
        return f"ok_{painted}_tracks"
    except Exception as e:
        print(f"  [WARN] eumetsat_render_track_overlay: {out_path} — {e}")
        return f"error: {e}"


def main():
    ft = None
    if os.path.exists(FRONTAL_TRACK_FILE):
        try:
            with open(FRONTAL_TRACK_FILE, "r", encoding="utf-8") as f:
                ft = json.load(f)
        except Exception as e:
            print(f"  [WARN] eumetsat_render_track_overlay: не удалось прочитать frontal_track.json: {e}")

    tracks = (ft or {}).get("tracks", [])
    near_tracks = [t for t in tracks if t.get("tile") == "near"]
    west_tracks = [t for t in tracks if t.get("tile") == "west"]

    near_status = _render_tile(
        NEAR_SCRATCH_BASE, NEAR_SCRATCH_PIXELMAP, NEAR_OUT_FILE,
        near_tracks, origin_dx_km=0.0, origin_dy_km=0.0,
    )
    west_status = _render_tile(
        WEST_SCRATCH_BASE, WEST_SCRATCH_PIXELMAP, WEST_OUT_FILE,
        west_tracks, origin_dx_km=fc.WEST_TILE_OFFSET_DX_KM, origin_dy_km=fc.WEST_TILE_OFFSET_DY_KM,
    )
    print(f"  [OK] eumetsat_render_track_overlay: near={near_status}, west={west_status}")


if __name__ == "__main__":
    main()
