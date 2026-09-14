"""
eumetsat_render_systems_overlay.py — подсветка ВСЕХ систем синоптического
масштаба (не только персистентных frontlike-треков) на снимке CLM реальными
пикселями блоба, тем же приёмом, что eumetsat_render_track_overlay.py
(запрос пользователя: "давай попробуем отобразить Системы синоптического
масштаба и подкрасить их. Для этого наверное ещё одну карту добавить
нужно" — после того, как абстрактная линия PCA-оси на GeoColour для
персистентных треков ("Треки фронтов") оказалась визуально малополезной:
"это всё что угодно, только не фронт").

В отличие от eumetsat_render_track_overlay.py:
  - Источник строк — НЕ eumetsat_frontal_track.json (персистентные
    многокадровые треки, только frontlike+подтверждённые за 3+ кадра), а
    eumetsat_target_summary.json -> system_candidates: СНАПШОТ текущего
    цикла — ВСЕ достаточно крупные (class=="system") облачные структуры,
    подтверждённые хотя бы одним из ИК/GeoColour, независимо от того,
    вытянуты ли они (frontlike) и успели ли накопить историю трека.
  - target_id системы НЕ персистентен между циклами (это позиция в
    отсортированном по расстоянию списке candidates ТЕКУЩЕГО кадра, см.
    eumetsat_cloud_forecast.py::_significant_blobs) — поэтому цвет здесь
    закреплён за ПОЗИЦИЕЙ в списке system_candidates (тот же порядок, в
    котором фронтенд рисует таблицу "Системы синоптического масштаба"),
    а не за физическим объектом. Между обновлениями страницы цвет одной
    и той же реальной системы может смениться — это осознанный
    компромисс: непрерывность цвета трека во времени решает ДРУГОЙ,
    уже существующий механизм (frontlike-треки, красятся в
    eumetsat_render_track_overlay.py); здесь задача другая — показать
    сейчас реальную форму/протяжённость КАЖДОЙ системы, а не проследить
    её во времени.

Запускается в оркестраторе ПОСЛЕ eumetsat_target_summary.py (см. порядок
в gh_satellite_pipeline.py) — только там system_candidates уже прошли
фильтр видимости по ИК/GeoColour (реестр
eumetsat_system_channel_suppression_log.json) — красить неподтверждённый
шум незачем, та же таблица на фронтенде его тоже не показывает (см.
nearby_precip.js::_renderSystemCandidatesTable).

Не делает НИКАКИХ сетевых запросов — только читает near-tier scratch-файлы,
записанные eumetsat_cloud_forecast.py В ЭТОМ ЖЕ прогоне job'а
(_scratch_clm_base.png/_scratch_clm_pixelmap.npy — те же файлы, что читает
eumetsat_render_track_overlay.py, используются здесь ПОВТОРНО и независимо,
сама покраска не мутирует исходные scratch-файлы). Системы считаются
только на near-tier (west-tier детектит ТОЛЬКО frontlike, без разбиения
на class local/system — см. eumetsat_west_watch.py), поэтому отдельного
west-варианта этого скрипта нет.

Если scratch-файлы отсутствуют (тайл в этом цикле не обновлялся — обычный
холостой цикл, не ошибка) — тихо ничего не делает, прежний
eumetsat_systems_snapshot.png остаётся как есть.

Пишет data/eumetsat_systems_snapshot.png.
"""
import json
import os

import numpy as np
from PIL import Image

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGET_SUMMARY_FILE = os.path.join(BASE_DIR, "data", "eumetsat_target_summary.json")

SCRATCH_BASE = os.path.join(BASE_DIR, "data", "_scratch_clm_base.png")
SCRATCH_PIXELMAP = os.path.join(BASE_DIR, "data", "_scratch_clm_pixelmap.npy")
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_systems_snapshot.png")


def main():
    if not (os.path.exists(SCRATCH_BASE) and os.path.exists(SCRATCH_PIXELMAP)):
        print("  [SKIP] eumetsat_render_systems_overlay: нет near-tier scratch (тайл не обновлялся в этом цикле)")
        return

    system_candidates = []
    if os.path.exists(TARGET_SUMMARY_FILE):
        try:
            with open(TARGET_SUMMARY_FILE, "r", encoding="utf-8") as f:
                ts_data = json.load(f)
            # Ключ "system_candidates" присутствует во всех "содержательных"
            # веток main() eumetsat_target_summary.py (ok/suppressed) и
            # отсутствует в пустых (no_data/no_target) — .get() безопасно
            # вернёт [] в последнем случае, отдельная ветка не нужна.
            system_candidates = ts_data.get("system_candidates") or []
        except Exception as e:
            print(f"  [WARN] eumetsat_render_systems_overlay: не удалось прочитать target_summary.json: {e}")

    try:
        base_img = Image.open(SCRATCH_BASE).convert("RGB")
        pixel_map = np.load(SCRATCH_PIXELMAP)
        arr = np.array(base_img)
        painted = 0
        for i, c in enumerate(system_candidates):
            tid = c.get("target_id")
            if tid is None:
                continue
            mask = pixel_map == (tid + 1)
            if not mask.any():
                continue
            # Цвет по ПОЗИЦИИ в списке (i), не по track_id, как в
            # render_track_overlay.py — см. докстринг про непостоянство
            # target_id у систем между циклами.
            color = fc.FRONTAL_TRACK_COLORS[i % len(fc.FRONTAL_TRACK_COLORS)]
            arr[mask] = color
            painted += 1
        out_img = Image.fromarray(arr, mode="RGB")
        out_img = fc.draw_odessa_marker(out_img)
        out_img.save(OUT_FILE)
        print(f"  [OK] eumetsat_render_systems_overlay: {painted}/{len(system_candidates)} систем закрашено")
    except Exception as e:
        print(f"  [WARN] eumetsat_render_systems_overlay: {OUT_FILE} — {e}")


if __name__ == "__main__":
    main()
