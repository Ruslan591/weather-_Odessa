"""
scripts/experiments/eumetsat_front_products_experiment.py

ИЗОЛИРОВАННЫЙ эксперимент (docs/ai/EUMETSAT_FRONT_DETECTION_PRODUCTS_EXPERIMENT.md).
НЕ трогает production detector/nearby.html/config. Запускается ТОЛЬКО через
.github/workflows/experiment_front_products.yml (workflow_dispatch), пишет
результаты в data/experiments/eumetsat_front_products/ и docs/ai/.

Цель: проверить, дают ли готовые EUMETSAT/NWC SAF продукты (CT/CTTH/OCA)
что-то полезное для детекции фронтов сверх уже используемых
GeoColour+IR105+CLM (+ уже интегрированный в production Cloud Type RGB).

Метод: тот же bbox/геометрия, что у центрального (near-tier) production
pipeline (data/geo_config.json: CENTER_LAT/LON ± HALF_WINDOW_DEG), тот же
WMS-сервер (view.eumetsat.int/geoserver/wms), те же приёмы (fetch_map_custom,
GetCapabilities) — переиспользованы из field_motion_common.py напрямую,
не задублированы.
"""
import io
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import field_motion_common as fc

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "data", "experiments", "eumetsat_front_products")
os.makedirs(OUT_DIR, exist_ok=True)

# Тот же bbox, что near-tier production pipeline (field_motion_common.py:
# CENTER_LON/LAT ± HALF_WINDOW_DEG). Явный литерал здесь — для полной
# прозрачности отчёта (не полагаемся молча на TILE_SIZE=400 constant).
BBOX = (fc.CENTER_LON - fc.HALF_WINDOW_DEG, fc.CENTER_LAT - fc.HALF_WINDOW_DEG,
        fc.CENTER_LON + fc.HALF_WINDOW_DEG, fc.CENTER_LAT + fc.HALF_WINDOW_DEG)
WIDTH = HEIGHT = 700  # крупнее production TILE_SIZE=400 — для лучшей визуальной проверки

DATES = ["2026-08-18", "2026-09-21"]
TIMES_UTC = ["12:00", "14:00", "15:00", "16:00", "17:00", "18:00", "20:00"]

KNOWN_LAYERS = {
    "geocolour": ("mtg_fd:rgb_geocolour", ""),
    "ir105": ("mtg_fd:ir105_hrfi", "mtg_fd:mtg_fd_ir105_hrfi_grayscale"),
    "clm": ("msg_fes:clm", ""),
    "cloudtype_rgb": ("mtg_fd:rgb_cloudtype", ""),  # уже в production, ближайший доступный прокси "CT"
}

# Кандидаты на квантативные CT/CTTH/OCA — проверяем реальным GetCapabilities,
# не полагаемся только на память о прошлой разведке (2026-08-02).
CANDIDATE_QUANT_LAYERS = [
    "msg_fes:ct", "msg_fes:ctth", "msg_fes:cth", "msg_fes:oca",
    "mtg_fd:ct", "mtg_fd:ctth", "mtg_fd:oca",
    "msg_fes:cloud_type", "msg_fes:cloud_top", "mtg_fd:cloud_type", "mtg_fd:cloud_top",
]


def get_all_layer_names():
    r = requests.get(fc.GETCAPABILITIES_URL, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    names = []
    for layer in root.iter(f"{fc._WMS_NS}Layer"):
        name_el = layer.find(f"{fc._WMS_NS}Name")
        if name_el is not None and name_el.text:
            names.append(name_el.text)
    return names


def nearest_dt(date_str, time_str):
    return f"{date_str}T{time_str}:00Z"


def main():
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "bbox_lonlat_crs84": list(BBOX),
        "width": WIDTH, "height": HEIGHT,
        "note": "bbox идентичен near-tier production pipeline (field_motion_common.py)",
        "layer_capability_check": {},
        "frames": [],
    }

    # 1) Проверка реального списка слоёв на предмет квантативных CT/CTTH/OCA
    try:
        all_names = get_all_layer_names()
        manifest["all_layer_count"] = len(all_names)
        found_candidates = {}
        for cand in CANDIDATE_QUANT_LAYERS:
            found_candidates[cand] = cand in all_names
        # Плюс полнотекстовый поиск по подстрокам "ct", "ctth", "oca", "cloud_top", "cloudtop"
        substr_hits = sorted(set(
            n for n in all_names
            if any(s in n.lower() for s in ["ctth", "cloud_top", "cloudtop", ":oca", "_oca", "oca_"])
        ))
        manifest["layer_capability_check"] = {
            "exact_candidates_found": {k: v for k, v in found_candidates.items() if v},
            "exact_candidates_checked": list(CANDIDATE_QUANT_LAYERS),
            "substring_hits_ctth_oca": substr_hits,
        }
    except Exception as e:
        manifest["layer_capability_check"] = {"error": str(e)}

    # 2) Фетч кадров
    for date_str in DATES:
        for time_str in TIMES_UTC:
            t_iso = nearest_dt(date_str, time_str)
            for key, (layer, style) in KNOWN_LAYERS.items():
                fname = f"{date_str}_{time_str.replace(':','')}_{key}.png"
                fpath = os.path.join(OUT_DIR, fname)
                entry = {
                    "date": date_str, "requested_time_utc": t_iso,
                    "product": key, "layer": layer, "file": f"data/experiments/eumetsat_front_products/{fname}",
                }
                try:
                    crs = "EPSG:4326" if key == "ir105" else "CRS:84"
                    bbox_arg = BBOX
                    arr = fc.fetch_map_custom(layer, bbox_arg, WIDTH, HEIGHT, time_iso=t_iso,
                                               retries=2, delay=3, style=style, crs=crs)
                    from PIL import Image
                    Image.fromarray(arr).save(fpath)
                    entry["status"] = "ok"
                    entry["nonzero_alpha_fraction"] = float((arr[..., 3] > 0).mean())
                except Exception as e:
                    entry["status"] = "error"
                    entry["error"] = str(e)[:300]
                manifest["frames"].append(entry)
                time.sleep(1)

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("DONE", manifest_path)


if __name__ == "__main__":
    main()
