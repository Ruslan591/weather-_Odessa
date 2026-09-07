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
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FRONTAL_TRACK_FILE = os.path.join(BASE_DIR, "data", "eumetsat_frontal_track.json")

NEAR_SCRATCH_BASE = os.path.join(BASE_DIR, "data", "_scratch_clm_base.png")
NEAR_SCRATCH_PIXELMAP = os.path.join(BASE_DIR, "data", "_scratch_clm_pixelmap.npy")
NEAR_OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_clm_snapshot.png")

WEST_SCRATCH_BASE = os.path.join(BASE_DIR, "data", "_scratch_west_clm_base.png")
WEST_SCRATCH_PIXELMAP = os.path.join(BASE_DIR, "data", "_scratch_west_pixelmap.npy")
WEST_OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_snapshot_clm.png")


FRONTAL_LINE_SCORE_FILE = os.path.join(BASE_DIR, "data", "frontal_line_score.json")
FRONTAL_CONFIRM_FILE = os.path.join(BASE_DIR, "data", "open_meteo_frontal_confirm.json")


def _draw_score_checkpoints(base_img, tracks_for_tile, score_data):
    """Шаг 5 плана (frontal_line_stations.md): точки ahead/behind поверх
    уже отрисованного near-tier снимка — зелёная, если предсказание
    best_model близко к реальности (|ошибка|<=1.5°C), иначе красная.
    along_km/perp_km -> dx/dy та же формула, что generate_axis_samples()."""
    if not score_data:
        return base_img
    overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for t in tracks_for_tile:
        tid = str(t["track_id"])
        track_score = score_data.get("tracks", {}).get(tid)
        axis_deg = t.get("axis_deg")
        if not track_score or axis_deg is None:
            continue
        best_model = track_score.get("best_model")
        rad = math.radians(axis_deg)
        ax_x, ax_y = math.sin(rad), math.cos(rad)
        pp_x, pp_y = math.cos(rad), -math.sin(rad)
        for cp in track_score.get("checkpoints", []):
            if best_model not in cp.get("model_predicted", {}):
                continue
            err = abs(cp["model_predicted"][best_model] - cp["real_diff"])
            color = (60, 220, 60, 255) if err <= 1.5 else (230, 60, 60, 255)
            for perp_sign in (1, -1):  # ahead/behind по разные стороны оси
                along_km, perp_km = cp["offset_km"], perp_sign * 40.0
                dx = t.get("dx_km", 0.0) + along_km * ax_x + perp_km * pp_x
                dy = t.get("dy_km", 0.0) + along_km * ax_y + perp_km * pp_y
                cx = (base_img.width - 1) / 2.0 - dx / fc.KM_PER_PX_X
                cy = (base_img.height - 1) / 2.0 + dy / fc.KM_PER_PX_Y
                draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=color, outline=(0, 0, 0, 255))
    return Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")


def _dilate(mask):
    """4-связная дилатация булевой маски без scipy (numpy-сдвиги массива —
    достаточно для 1-2px кольца, отдельная зависимость не нужна)."""
    d = mask.copy()
    d[1:, :] |= mask[:-1, :]
    d[:-1, :] |= mask[1:, :]
    d[:, 1:] |= mask[:, :-1]
    d[:, :-1] |= mask[:, 1:]
    return d


def _draw_frontal_confirm_outline(base_img, tracks_for_tile, mask_by_track_id, confirm_data):
    """Обводит РЕАЛЬНЫЙ контур блоба (не абстрактный круг) цветом
    подтверждения open_meteo_frontal_confirm.py — по запросу пользователя
    2026-09-07 ("фронт это дуга/линия по форме облачности, а не круг").
    Раньше здесь рисовался фиксированный ellipse в центре трека
    (_draw_frontal_confirm_status, удалена) — не отражала ни форму, ни
    размер реального блоба. Кольцо строится дилатацией (_dilate) маски
    блоба на 2px наружу — контур виден поверх любого фона, не сливается
    с уже закрашенным телом блоба (см. _render_tile). Подпись у центроида —
    голоса/модели + тип фронта (х=холодный/т=тёплый), приоритет —
    станционный front_type трека (eumetsat_frontal_track.py), фолбэк —
    модельный front_type_model (open_meteo_frontal_confirm.py, нужен над
    морем, где станций нет). Только near-tile (та же причина, что была у
    предыдущей версии — координаты без origin-сдвига, для west не подходят,
    см. main())."""
    if not confirm_data:
        return base_img
    candidates = confirm_data.get("candidates", {})
    if not candidates:
        return base_img
    h, w = base_img.height, base_img.width
    overlay_arr = np.zeros((h, w, 4), dtype=np.uint8)
    labels = []
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for t in tracks_for_tile:
        tid = t["track_id"]
        verdict = candidates.get(str(tid))
        mask = mask_by_track_id.get(tid)
        if not verdict or mask is None or not mask.any():
            continue
        ring = _dilate(_dilate(mask)) & ~mask
        color = (60, 220, 60, 255) if verdict.get("confirmed") else (160, 160, 160, 255)
        overlay_arr[ring] = color
        ys, xs = np.nonzero(mask)
        cy, cx = float(ys.mean()), float(xs.mean())
        front_type = t.get("front_type") or verdict.get("front_type_model")
        type_tag = " х" if front_type == "cold" else (" т" if front_type == "warm" else "")
        labels.append((cx, cy, f"{verdict.get('votes', 0)}/{verdict.get('n_models', 5)}{type_tag}", color))
    overlay = Image.fromarray(overlay_arr, mode="RGBA")
    out = Image.alpha_composite(base_img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(out)
    for cx, cy, label, color in labels:
        draw.text((cx + 6, cy - 8), label, fill=color, font=font)
    return out.convert("RGB")


def _render_tile(scratch_base_path, scratch_pixelmap_path, out_path,
                  tracks_for_tile, origin_dx_km, origin_dy_km, score_data=None, confirm_data=None):
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
        mask_by_track_id = {}
        for t in tracks_for_tile:
            tid = t.get("current_target_id")
            if tid is None:
                continue  # трек не подтверждён В ЭТОМ кадре — красить нечего
            mask = pixel_map == (tid + 1)
            if not mask.any():
                continue
            color = fc.FRONTAL_TRACK_COLORS[t["track_id"] % len(fc.FRONTAL_TRACK_COLORS)]
            arr[mask] = color
            mask_by_track_id[t["track_id"]] = mask  # для _draw_frontal_confirm_outline ниже
            painted += 1
        out_img = Image.fromarray(arr, mode="RGB")
        out_img = fc.draw_odessa_marker(out_img, origin_dx_km=origin_dx_km, origin_dy_km=origin_dy_km)
        out_img = _draw_score_checkpoints(out_img, tracks_for_tile, score_data)
        out_img = _draw_frontal_confirm_outline(out_img, tracks_for_tile, mask_by_track_id, confirm_data)
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

    score_data = None
    if os.path.exists(FRONTAL_LINE_SCORE_FILE):
        try:
            with open(FRONTAL_LINE_SCORE_FILE, "r", encoding="utf-8") as f:
                score_data = json.load(f)
        except Exception:
            pass

    confirm_data = None
    if os.path.exists(FRONTAL_CONFIRM_FILE):
        try:
            with open(FRONTAL_CONFIRM_FILE, "r", encoding="utf-8") as f:
                confirm_data = json.load(f)
        except Exception:
            pass

    near_status = _render_tile(
        NEAR_SCRATCH_BASE, NEAR_SCRATCH_PIXELMAP, NEAR_OUT_FILE,
        near_tracks, origin_dx_km=0.0, origin_dy_km=0.0, score_data=score_data, confirm_data=confirm_data,
    )
    west_status = _render_tile(
        WEST_SCRATCH_BASE, WEST_SCRATCH_PIXELMAP, WEST_OUT_FILE,
        west_tracks, origin_dx_km=fc.WEST_TILE_OFFSET_DX_KM, origin_dy_km=fc.WEST_TILE_OFFSET_DY_KM,
    )
    print(f"  [OK] eumetsat_render_track_overlay: near={near_status}, west={west_status}")


if __name__ == "__main__":
    main()

