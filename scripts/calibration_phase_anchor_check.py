"""
calibration_phase_anchor_check.py — визуальная + числовая проверка
цветовых якорей каскада _classify_phase(). Контекст: первый прогон
калибровки Phase RGB (2026-08-13) дал почти нулевую точность (кроме
"безоблачно") даже после фикса карты CL/CM/CH и исключения сумерек по
реальной элевации Солнца — подозрение, что сами HSV-якоря каскада
(白/фиолетовый/розовый/красный/синий/голубой/жёлтый/зелёный/коричневый),
взятые как первое приближение без калибровки (см. докстринг
_classify_phase: "первая, не откалиброванная версия анкеров"), не
соответствуют реальному рендерингу mtg_fd:rgb_cloudphase на
view.eumetsat.int.

Метод: для 8 вручную отобранных "чистых" сроков (один явно
доминирующий ярус CL/CM/CH, высокое солнце elev>15°, по одному
представителю на каждую непустую категорию 0-5,7,8 — 6 отсутствует,
данных не было изначально) — тянет тайл, сохраняет:
1. PNG-снимок ROI (обрезка 25км вокруг станции) — для визуальной
   проверки глазами человека, что реально нарисовано;
2. JSON со статистикой: топ-10 наиболее частых (H,S,V)-кластеров в ROI
   (округление H до 5°, S/V до 0.05 перед подсчётом) — числовая проверка,
   действительно ли доминирующий цвет близок к ожидаемому якорю.

Результат — data/calibration_phase_anchor_check/*.png +
data/calibration_phase_anchor_check_stats.json.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import field_motion_common as fc  # noqa: E402
from eumetsat_cloud_phase_type import _rgb_to_hsv_vec, LAYER_PHASE  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "data", "calibration_phase_anchor_check")
OUT_STATS = os.path.join(BASE_DIR, "data", "calibration_phase_anchor_check_stats.json")
RADIUS_KM = 25

# Вручную отобранные "чистые" срока (см. докстринг выше) — по одному
# представителю на категорию (0 и 1-5,7,8; 6 нет данных в архиве).
CANDIDATES = [
    {"synop_timestamp": "2025-02-21T15:00:00.000Z", "expected_ordinal": 0, "label": "безоблачно (N=0)"},
    {"synop_timestamp": "2026-06-22T09:00:00.000Z", "expected_ordinal": 1, "label": "низкая (CL=1)"},
    {"synop_timestamp": "2026-04-10T06:00:00.000Z", "expected_ordinal": 2, "label": "средняя (CM=3)"},
    {"synop_timestamp": "2025-09-08T06:00:00.000Z", "expected_ordinal": 3, "label": "плотная (CM=3, повтор яруса)"},
    {"synop_timestamp": "2025-06-07T06:00:00.000Z", "expected_ordinal": 4, "label": "тонкий лёд (CH=1)"},
    {"synop_timestamp": "2026-06-17T09:00:00.000Z", "expected_ordinal": 5, "label": "лёд (CH=2)"},
    {"synop_timestamp": "2026-06-09T09:00:00.000Z", "expected_ordinal": 7, "label": "холодные верхушки (CL=3)"},
    {"synop_timestamp": "2025-05-07T09:00:00.000Z", "expected_ordinal": 8, "label": "конвекция (CL=3,CM=7,CH=4 — ближайшее к CL=9 из архива)"},
]


def _radius_mask(radius_km):
    rows, cols = np.meshgrid(np.arange(fc.TILE_SIZE), np.arange(fc.TILE_SIZE), indexing="ij")
    center = (fc.TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc.KM_PER_PX_X
    dy_km = (rows - center) * fc.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    mask = _radius_mask(RADIUS_KM)
    results = []

    for c in CANDIDATES:
        ts = c["synop_timestamp"]
        safe_name = ts.replace(":", "").replace("-", "")
        try:
            arr = fc.fetch_tile(LAYER_PHASE, ts, retries=2, delay=3)
        except Exception as e:
            print(f"  [FAIL] {ts}: {e}")
            results.append({**c, "error": str(e)})
            continue

        alpha_valid = arr[:, :, 3] > 0
        roi = alpha_valid & mask

        # PNG всего тайла 400x400 (для контекста) — крупный, но один раз
        img = Image.fromarray(arr[:, :, :3].astype(np.uint8), mode="RGB")
        img.save(os.path.join(OUT_DIR, f"{safe_name}_ord{c['expected_ordinal']}_full.png"))

        # Обрезка непосредственно ROI (25км) для крупного плана
        rows_idx, cols_idx = np.where(mask)
        r0, r1 = rows_idx.min(), rows_idx.max()
        c0, c1 = cols_idx.min(), cols_idx.max()
        crop = Image.fromarray(arr[r0:r1+1, c0:c1+1, :3].astype(np.uint8), mode="RGB")
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST)
        crop.save(os.path.join(OUT_DIR, f"{safe_name}_ord{c['expected_ordinal']}_roi_zoom.png"))

        h_deg, s, v = _rgb_to_hsv_vec(arr[:, :, :3])
        h_roi, s_roi, v_roi = h_deg[roi], s[roi], v[roi]

        h_bin = (np.round(h_roi / 5) * 5).astype(int) % 360
        s_bin = np.round(s_roi / 0.05) * 0.05
        v_bin = np.round(v_roi / 0.05) * 0.05

        from collections import Counter
        clusters = Counter(zip(h_bin.tolist(), s_bin.round(2).tolist(), v_bin.round(2).tolist()))
        top10 = clusters.most_common(10)
        total = int(roi.sum())

        results.append({
            **c,
            "roi_valid_px": total,
            "top_hsv_clusters": [
                {"h": h, "s": s_, "v": v_, "fraction": round(cnt / total, 4)}
                for (h, s_, v_), cnt in top10
            ],
        })
        print(f"  [OK] {ts} ({c['label']}) top-3: {top10[:3]}")

    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("Готово.")


if __name__ == "__main__":
    main()
