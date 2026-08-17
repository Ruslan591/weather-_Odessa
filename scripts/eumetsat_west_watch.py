"""
eumetsat_west_watch.py — детект фронтоподобных систем в ЗАПАДНОМ тайле
(пилот плана "мозаика тайлов", обсуждение с пользователем 2026-08-16,
docs/topics/eumetsat.md). Тот же метод сегментации/классификации, что
system-проход в eumetsat_cloud_forecast.py (_significant_blobs), и то же
IR/GC ROI-подтверждение, что system_analysis_all в eumetsat_ir_motion.py/
eumetsat_geocolour_motion.py — просто применённые к ДРУГОМУ географическому
тайлу (западнее near-tier, впритык, с нахлёстом WEST_TILE_OFFSET см.
field_motion_common.py) и БЕЗ multi-frame буфера/моушена (не нужен —
см. ниже).

СТРОГО ОГРАНИЧЕНО решением пользователя 2026-08-16 "Западный Пайл будет
работать только для блока Треки фронтов":
  - Локальные очаги (class="local", 4-связность) — НЕ детектируются вообще
    (даже проход не выполняется, экономия compute).
  - Системы синоптического масштаба, НЕ являющиеся frontlike (aspect_ratio
    < FRONTLIKE_ASPECT_THRESHOLD), — НЕ попадают в выходной файл (find, но
    сразу отбрасываются).
  - Осадки/гроза/фаза-тип/CTH — не подключены вообще.
  Итог: единственный потребитель data/eumetsat_west_watch.json —
  eumetsat_frontal_track.py (блок "Треки фронтов" на nearby.html).

ПОЧЕМУ НЕ НУЖЕН БУФЕР (в отличие от eumetsat_cloud_forecast.py): у
near-tier буфер (eumetsat_cloud_buffer.npz) нужен для сравнения
первого/последнего кадра (тренд плотности/высоты/формы облачности) —
этой задачи у западного тайла нет вообще (см. ограничение выше). Сама
сегментация frontlike-систем и их IR/GC-подтверждение — однокадровые
операции (contrast/классификация относительно статистики ТЕКУЩЕГО кадра),
истории не требуют. Поэтому это цельный однопроходный скрипт: CLM+IR+GC
одного момента времени → сегментация → фильтр frontlike → ROI-подтверждение
→ запись результата. До 3 WMS-запросов на непустой цикл (не считая
GetCapabilities для гейта) — CLM всегда, GeoColour всегда (2026-08-16,
для визуального снимка тайла, см. CLM_SNAPSHOT_FILE/GEOCOLOUR_SNAPSHOT_FILE
ниже — запрос пользователя "выведешь снимки нового квадрата"; ДО этого GC
качался только при найденных frontlike-системах, экономя запрос на пустых
циклах — сознательно пожертвовали этой экономией ради снимков), IR — ТОЛЬКО
если нашлись frontlike-системы (единственная оставшаяся экономия). СТРОГО
РЕЖЕ near-tier (3 слоя vs имитация непрерывного моушена по 5+ слоям) по
требованию "максимально зажать нагрузку".

ГЕЙТ: тот же принцип, что у *_motion.py/cloud_forecast.py — НЕ искусственный
wall-clock интервал, а сравнение с последним временем кадра CLM, ОБЪЯВЛЕННЫМ
СЕРВЕРОМ (fc.get_layer_latest_time, дешёвый GetCapabilities-запрос). Если
сервер не опубликовал кадр новее последнего сохранённого — выходим, не
делая тяжёлых GetMap-запросов вообще (0 запросов на холостой цикл — гейт
срабатывает ДО снимков тоже, снимки просто не обновляются лишний раз).

КООРДИНАТЫ: centroid_dx_km/dy_km и bbox_km кандидатов — в ЕДИНОЙ системе
"км от Одессы" (fc.WEST_TILE_OFFSET_DX_KM/DY_KM прибавляется к локальному
km-смещению от центра ЗАПАДНОГО тайла, посчитанному ТОЙ ЖЕ формулой, что и
near-tier) — см. обсуждение с пользователем 2026-08-16: нужна одна система
координат на все тайлы разом, для склейки на границе и для
eumetsat_frontal_track.py (который уже матчит объекты по dx_km/dy_km от
Одессы, ему всё равно, из какого тайла они пришли).

СКЛЕЙКА НА ГРАНИЦЕ (нахлёст WEST_TILE_OFFSET) — реализована ПОЗЖЕ, отдельным
шагом в eumetsat_frontal_track.py (дедупликация near+west кандидатов по
близости centroid) — этот скрипт сам по себе о near-tier ничего не знает.

Пишет ТОЛЬКО data/eumetsat_west_watch.json — буфера/npz нет.
"""

import math
import os
from datetime import datetime, timezone

import numpy as np
from PIL import Image
from scipy import ndimage

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_watch.json")
CLM_SNAPSHOT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_snapshot_clm.png")
GEOCOLOUR_SNAPSHOT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_snapshot_geocolour.png")
IR_SNAPSHOT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_west_snapshot_ir.png")

LAYER_CLM = "msg_fes:clm"
LAYER_IR105 = "mtg_fd:ir105_hrfi"
STYLE_IR105 = "mtg_fd:mtg_fd_ir105_hrfi_grayscale"
LAYER_GEOCOLOUR = "mtg_fd:rgb_geocolour"

TILE_SIZE = fc.TILE_SIZE
KM_PER_PX_X = fc.KM_PER_PX_X
KM_PER_PX_Y = fc.KM_PER_PX_Y
WEST_BBOX = fc.WEST_BBOX
OFFSET_DX_KM = fc.WEST_TILE_OFFSET_DX_KM
OFFSET_DY_KM = fc.WEST_TILE_OFFSET_DY_KM
MIN_CLOUD_CONTRAST_SIGMA = fc.MIN_CLOUD_CONTRAST_SIGMA

# Те же значения, что в eumetsat_cloud_forecast.py (LARGE_SYSTEM_AREA_KM2,
# FRONTLIKE_ASPECT_THRESHOLD, MIN_SIGNIFICANT_BLOB_PX) — НЕ независимая
# калибровка, копия констант для идентичного поведения на другом тайле
# (то же разрешение км/px, тот же смысл площади/вытянутости).
LARGE_SYSTEM_AREA_KM2 = 300.0
FRONTLIKE_ASPECT_THRESHOLD = 2.2
MIN_SIGNIFICANT_BLOB_PX = 40
WINDOW_SPAN_TOLERANCE_PX = 2
ROI_PAD_KM = 2.0        # тот же запас, что pad_km в fc.km_bbox_to_pixel_mask
GC_CLOUD_FRACTION_THRESHOLD = 0.5   # тот же порог, что system_analysis_all в geocolour_motion.py

CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}


def _classify_clm(arr):
    """Копия eumetsat_cloud_forecast.py::_classify_cloud_mask — тот же метод
    (ближайший цвет-якорь), намеренно не импортируется оттуда (см. докстринг
    модуля — этот скрипт самодостаточный, без риска для near-tier при правках
    здесь)."""
    h, w, _ = arr.shape
    rgb = arr[:, :, :3].reshape(-1, 3).astype(np.float32)
    alpha = arr[:, :, 3].reshape(-1)
    valid = alpha > 0
    anchors = np.array(list(CLM_ANCHORS.values()), dtype=np.float32)
    keys = list(CLM_ANCHORS.keys())
    dists = np.sum((rgb[:, None, :] - anchors[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    is_cloud = (np.array(keys)[nearest_idx] == "cloud").reshape(h, w)
    valid = valid.reshape(h, w)
    is_cloud = is_cloud & valid
    return is_cloud, valid


def _classify_geocolour(rgba, is_day):
    """Копия eumetsat_geocolour_motion.py::_classify_cloud — те же
    откалиброванные пороги (2026-08-11 день / 2026-08-12 ночь), см. там
    комментарии про калибровку по SYNOP. Скопировано, а не импортировано —
    см. докстринг модуля."""
    alpha_valid = rgba[:, :, 3] > 0
    h, s, v = fc.rgb_to_hsv_vec(rgba[:, :, :3])
    city_light = ((h >= 15) & (h <= 70)) & (s > 0.2) & (v > 0.25)
    if is_day:
        cloud = (s < 0.35) & (v > 0.40)
    else:
        cloud = ((h >= 180) & (h <= 260)) & (s > 0.06) & (v > 0.20)
    cloud = cloud & ~city_light & alpha_valid
    return cloud, alpha_valid


def _pixel_to_local_km(row, col):
    """То же самое, что fc.pixel_to_km_offset(), но относительно центра
    ЗАПАДНОГО тайла (не near-tile/Одессы) — единственное отличие. Результат
    ещё не в системе координат Одессы, см. _to_odessa_km() ниже."""
    center = (TILE_SIZE - 1) / 2
    dx_km = (col - center) * KM_PER_PX_X
    dy_km = -(row - center) * KM_PER_PX_Y
    return dx_km, dy_km


def _to_odessa_km(dx_km, dy_km):
    return dx_km + OFFSET_DX_KM, dy_km + OFFSET_DY_KM


def _window_edge_km():
    center = (TILE_SIZE - 1) / 2
    return center * KM_PER_PX_X, center * KM_PER_PX_Y


def _blob_elongation(ys, xs):
    """PCA по пикселям блоба — идентично eumetsat_cloud_forecast.py::
    _blob_elongation, но center_row/center_col = 0, т.к. ковариация
    инвариантна к постоянному сдвигу системы координат (см. коммент там)."""
    if len(ys) < 5:
        return None, None
    dx_km = xs.astype(np.float64) * KM_PER_PX_X
    dy_km = -ys.astype(np.float64) * KM_PER_PX_Y
    cov = np.cov(np.stack([dx_km, dy_km], axis=0))
    if cov.shape != (2, 2):
        return None, None
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    if eigvals[1] <= 1e-9:
        return None, None
    aspect = math.sqrt(max(eigvals[0], 0) / max(eigvals[1], 1e-9))
    major = eigvecs[:, 0]
    bearing = (math.degrees(math.atan2(major[0], major[1])) + 360) % 180
    return aspect, bearing


def _axis_compass_label(bearing_deg):
    if bearing_deg is None:
        return None
    a = fc.compass(bearing_deg % 360)
    b = fc.compass((bearing_deg + 180) % 360)
    return f"{a}-{b}"


def _detect_frontlike_systems(is_cloud_mask, valid_mask):
    """Только СИСТЕМНЫЙ проход (8-связность + binary_opening), только
    frontlike — см. докстринг модуля, никаких local/не-frontlike на выход.
    Возвращает список dict с полями, СОВМЕСТИМЫМИ по схеме с
    eumetsat_cloud_forecast.py::_significant_blobs (class="system",
    centroid_dx_km/dy_km, bbox_km, elongation_*, frontlike, window_spanning),
    плюс "tile": "west" и внутренний "_pixel_mask" (для ROI IR/GC-проверки,
    удаляется перед записью в JSON)."""
    raw_target = is_cloud_mask

    system_input = ndimage.binary_opening(
        raw_target, structure=ndimage.generate_binary_structure(2, 1)
    )
    labeled8, n8 = ndimage.label(system_input, structure=np.ones((3, 3), dtype=int))
    if n8 == 0:
        return []
    sizes = ndimage.sum(raw_target, labeled8, range(1, n8 + 1))
    edge_dx_km, edge_dy_km = _window_edge_km()
    tol_dx_km = WINDOW_SPAN_TOLERANCE_PX * KM_PER_PX_X
    tol_dy_km = WINDOW_SPAN_TOLERANCE_PX * KM_PER_PX_Y

    result = []
    for lbl in range(1, n8 + 1):
        blob_px = float(sizes[lbl - 1])
        if blob_px < MIN_SIGNIFICANT_BLOB_PX:
            continue
        blob_area_km2 = blob_px * KM_PER_PX_X * KM_PER_PX_Y
        if blob_area_km2 < LARGE_SYSTEM_AREA_KM2:
            continue
        ys, xs = np.where(labeled8 == lbl)
        aspect_ratio, axis_bearing = _blob_elongation(ys, xs)
        if aspect_ratio is None or aspect_ratio < FRONTLIKE_ASPECT_THRESHOLD:
            continue  # не frontlike — по решению 2026-08-16 не выводим вообще

        center = (TILE_SIZE - 1) / 2
        dist_px = np.sqrt((ys - center) ** 2 + (xs - center) ** 2)
        best_i = np.argmin(dist_px)
        row, col = int(ys[best_i]), int(xs[best_i])
        cdx_local, cdy_local = _pixel_to_local_km(row, col)

        corners_dx, corners_dy = [], []
        for r, c in ((ys.min(), xs.min()), (ys.max(), xs.max())):
            dx, dy = _pixel_to_local_km(int(r), int(c))
            corners_dx.append(dx)
            corners_dy.append(dy)
        spans_x = (min(corners_dx) <= -edge_dx_km + tol_dx_km) and (max(corners_dx) >= edge_dx_km - tol_dx_km)
        spans_y = (min(corners_dy) <= -edge_dy_km + tol_dy_km) and (max(corners_dy) >= edge_dy_km - tol_dy_km)
        if spans_x or spans_y:
            continue  # window_spanning — ненадёжный по площади/форме, как и у near-tier (frontal_track фильтрует их так же)

        cdx_odessa, cdy_odessa = _to_odessa_km(cdx_local, cdy_local)
        bbox_dx = [c + OFFSET_DX_KM for c in corners_dx]
        bbox_dy = [c + OFFSET_DY_KM for c in corners_dy]

        result.append({
            "tile": "west",
            "class": "system",
            "centroid_dx_km": round(cdx_odessa, 2),
            "centroid_dy_km": round(cdy_odessa, 2),
            "area_km2": round(blob_area_km2, 1),
            "bbox_km": {
                "dx_min": round(min(bbox_dx), 2),
                "dx_max": round(max(bbox_dx), 2),
                "dy_min": round(min(bbox_dy), 2),
                "dy_max": round(max(bbox_dy), 2),
            },
            "elongation_aspect_ratio": round(aspect_ratio, 2),
            "elongation_axis_deg": round(axis_bearing, 0) if axis_bearing is not None else None,
            "elongation_axis_compass": _axis_compass_label(axis_bearing),
            "frontlike": True,
            "window_spanning": False,
            "_pixel_mask": (labeled8 == lbl),
        })
    return result


def _build_clm_snapshot_image(is_cloud, valid):
    """Тот же кастомный рекол-стайлинг, что у near-tier
    (eumetsat_cloud_forecast.py::_save_clm_snapshot) — НЕ сырые пиксели
    WMS-сервера (те дают синий=вода/зелёный=суша/белый=облако — у
    западного тайла суши намного больше, чем у near-tier у моря, отсюда
    и был вопрос "почему у west фон зелёный, а не синий" 2026-08-17: это
    была не намеренная разница, а забытая перекраска). Тёмно-синий=ясно,
    белый=облако, серый=нет данных — ОДИНАКОВО на обоих тайрах теперь."""
    rgb = np.zeros((TILE_SIZE, TILE_SIZE, 3), dtype=np.uint8)
    rgb[:, :] = (60, 60, 68)
    rgb[valid & ~is_cloud] = (18, 22, 40)
    rgb[valid & is_cloud] = (232, 232, 238)
    return Image.fromarray(rgb, mode="RGB")


def _confirm_ir(system, ir_gray):
    frame_median = float(np.median(ir_gray))
    frame_std = float(ir_gray.std()) or 1.0
    roi_mask = ndimage.binary_dilation(
        system["_pixel_mask"], iterations=max(1, int(round(ROI_PAD_KM / min(KM_PER_PX_X, KM_PER_PX_Y))))
    )
    roi_vals = ir_gray[roi_mask]
    if roi_vals.size == 0:
        return {"available": False, "reason": "ROI вне окна ИК-кадра"}
    roi_mean = float(roi_vals.mean())
    sigma = (roi_mean - frame_median) / frame_std
    return {
        "available": True,
        "roi_contrast_sigma": round(sigma, 2),
        "confirmed": sigma >= MIN_CLOUD_CONTRAST_SIGMA,
    }


def _confirm_gc(system, gc_is_cloud):
    roi_mask = ndimage.binary_dilation(
        system["_pixel_mask"], iterations=max(1, int(round(ROI_PAD_KM / min(KM_PER_PX_X, KM_PER_PX_Y))))
    )
    roi_vals = gc_is_cloud[roi_mask]
    if roi_vals.size == 0:
        return {"available": False, "reason": "ROI вне окна GeoColour-кадра"}
    frac = float(roi_vals.mean())
    return {
        "available": True,
        "roi_cloud_fraction": round(frac, 3),
        "confirmed": frac >= GC_CLOUD_FRACTION_THRESHOLD,
    }


def main():
    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_CLM)
    if server_latest_iso is None:
        print("  [WARN] eumetsat_west_watch: GetCapabilities недоступен, пропуск цикла")
        return

    prev = None
    try:
        import json
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = None

    if prev is not None and prev.get("timestamp") == server_latest_iso:
        return  # сервер не объявил кадр новее — SKIP, без единого GetMap-запроса

    try:
        clm_arr = fc.fetch_map_custom(LAYER_CLM, WEST_BBOX, TILE_SIZE, TILE_SIZE, time_iso=server_latest_iso)
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch: CLM недоступен ({e}), пропуск цикла")
        return

    is_cloud, valid = _classify_clm(clm_arr)
    systems = _detect_frontlike_systems(is_cloud, valid)

    # --- Снимки для визуальной проверки границ тайла (запрос пользователя
    # 2026-08-16/17) — CLM, GeoColour, ИК сохраняются КАЖДЫЙ непустой цикл,
    # независимо от того, найдены ли frontlike-системы. Все три — теперь
    # ДОРОГЕ по сети, чем раньше (было: CLM всегда + GC только при
    # найденных системах; стало: CLM+GC+ИК ВСЕГДА, до 3 запросов на
    # холостой цикл вместо 1-2) — осознанный компромисс по прямому запросу
    # пользователя ("добавь ИК снимок"), продолжающий компромисс с GC от
    # 2026-08-16. Если снимки станут не нужны — просто убрать блок ниже,
    # на детект/подтверждение это не влияет (ir_gray/gc_is_cloud всё равно
    # нужны для _confirm_ir/_confirm_gc, если есть кандидаты).
    #
    # Оверлеи (запрос 2026-08-17: "хоть какие-то ориентиры в GeoColour
    # есть, а в ИК и CLM никаких" + "дорисуй окружность обзора" + "границы
    # (контуры) нарисуй"; та же origin_dx_km/dy_km-генерализация в
    # field_motion_common.py, что у трёх draw_*-функций) — политика
    # СКОПИРОВАНА 1-в-1 с near-tier (см. eumetsat_geocolour_motion.py/
    # eumetsat_ir_motion.py/eumetsat_cloud_forecast.py): GeoColour/ИК —
    # только окружность+маркер Одессы (натуральная картинка/яркостный
    # контраст уже дают ориентиры, контур береговой линии избыточен и на
    # west-тайле всё равно почти ничего не покажет — там нет моря в кадре);
    # CLM — окружность+маркер+КОНТУР БЕРЕГОВОЙ ЛИНИИ (своей географии нет
    # вообще). Маркер Одессы и бо́льшая часть окружности физически ВНЕ
    # кадра западного тайла (Одесса ~360км восточнее его центра) — виден
    # только небольшой кусок дуги окружности у восточного края (там же,
    # где near-tier и west-tier перекрываются) — это ожидаемо, не ошибка.
    try:
        clm_img = _build_clm_snapshot_image(is_cloud, valid)
        clm_img = fc.draw_coastline_overlay(clm_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        clm_img = fc.draw_view_radius_circle(clm_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        clm_img = fc.draw_odessa_marker(clm_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        clm_img.save(CLM_SNAPSHOT_FILE)
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch: не удалось сохранить CLM snapshot ({e})")

    is_day = fc.is_daytime(server_latest_iso)

    gc_arr = None
    try:
        gc_arr = fc.fetch_map_custom(LAYER_GEOCOLOUR, WEST_BBOX, TILE_SIZE, TILE_SIZE, time_iso=server_latest_iso)
        gc_img = Image.fromarray(gc_arr).convert("RGB")
        gc_img = fc.draw_view_radius_circle(gc_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        gc_img = fc.draw_odessa_marker(gc_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        gc_img.save(GEOCOLOUR_SNAPSHOT_FILE)
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch: GeoColour/snapshot недоступен ({e})")

    ir_arr = None
    ir_gray = None
    try:
        ir_arr = fc.fetch_map_custom(LAYER_IR105, WEST_BBOX, TILE_SIZE, TILE_SIZE,
                                      time_iso=server_latest_iso, style=STYLE_IR105, crs="EPSG:4326")
        ir_gray = fc.to_grayscale_luminance(ir_arr)
        ir_img = Image.fromarray(ir_arr).convert("RGB")
        ir_img = fc.draw_view_radius_circle(ir_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        ir_img = fc.draw_odessa_marker(ir_img, origin_dx_km=OFFSET_DX_KM, origin_dy_km=OFFSET_DY_KM)
        ir_img.save(IR_SNAPSHOT_FILE)
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch: ИК/snapshot недоступен ({e}), ir_confirmation=None для всех")
        ir_gray = None

    if not systems:
        out = {
            "timestamp": server_latest_iso,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "candidates": [],
        }
        import json
        tmp = OUT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, OUT_FILE)
        print("  [OK] eumetsat_west_watch: 0 frontlike-систем")
        return

    gc_is_cloud = None
    if gc_arr is not None:
        try:
            gc_is_cloud, _ = _classify_geocolour(gc_arr, is_day)
        except Exception as e:
            print(f"  [WARN] eumetsat_west_watch: классификация GeoColour не удалась ({e}), gc_confirmation=None для всех")

    for s in systems:
        s["ir_confirmation"] = _confirm_ir(s, ir_gray) if ir_gray is not None else {"available": False, "reason": "слой недоступен в этом цикле"}
        s["gc_confirmation"] = _confirm_gc(s, gc_is_cloud) if gc_is_cloud is not None else {"available": False, "reason": "слой недоступен в этом цикле"}
        del s["_pixel_mask"]

    systems.sort(key=lambda s: math.hypot(s["centroid_dx_km"], s["centroid_dy_km"]))
    for i, s in enumerate(systems):
        s["target_id"] = i

    out = {
        "timestamp": server_latest_iso,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates": systems,
    }
    import json
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_FILE)
    print(f"  [OK] eumetsat_west_watch: {len(systems)} frontlike-систем(а)")


if __name__ == "__main__":
    main()
