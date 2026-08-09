"""
eumetsat_cloud_phase_type.py — качественная (не моторная) оценка фазы облаков
и грубого типа облачности по MTG Cloud Phase RGB / Cloud Type RGB:
  - Cloud Phase RGB (mtg_fd:rgb_cloudphase) -> ординальный индекс 0..8
    (безоблачно -> водяные (низкие/средние/плотные) -> лёд (тонкий/плотный)
    -> смешанная фаза -> очень холодные ледяные верхушки Cb -> гроза)
  - Cloud Type RGB (mtg_fd:rgb_cloudtype) -> грубая группа 0..2
    (безоблачно / низкая-средняя облачность / плотная-высокая облачность)

ПОЧЕМУ HSV-ДИАПАЗОНЫ, А НЕ ТОЧНЫЕ АНКЕРЫ (как в CLM/CTH):
Оба слоя — НАСТОЯЩИЕ RGB-композиты (в GetCapabilities у них нет отдельного
"Style" с фиксированной палитрой, в отличие от msg_clm/msg_cth), то есть
официальной таблицы "цвет -> категория" не существует в принципе — оттенок
плавает с освещением/сезоном/влажностью сцены. GetLegendGraphic для этих
слоёв возвращает не легенду, а бессмысленный градиент (тот же класс проблемы,
что уже известен для mosaic-слоёв, см. field_motion_common.py). Поэтому
анкеры здесь — ПРИБЛИЗИТЕЛЬНАЯ первая версия по человеческому описанию
цветов (см. обсуждение в чате), заданная как диапазоны Hue/Saturation/Value,
а не точки RGB — устойчивее к вариациям тона одного и того же "смысла".
ОЖИДАЕТСЯ калибровка/правки после первых живых прогонов (см. debug-файл:
там сохраняется доля пикселей, не попавших ни в одно правило — если она
велика, анкеры нужно расширять/сдвигать).

ЧТО СЧИТАЕТСЯ:
  - phase_ordinal_now / phase_ordinal_delta — средний ординальный индекс
    Cloud Phase в радиусе LOCAL_RADIUS_KM, сравнение первого и последнего
    кадра буфера (до 2 часов). Рост -> "фаза смещается к льду/мощной
    конвекции", падение -> "к воде/распад".
  - type_group_now / type_group_delta — то же для грубой группы Cloud Type
    (0 безоблачно/1 низкая-средняя/2 плотная-высокая).
  - unclassified_fraction — доля пикселей локальной области, не попавших
    уверенно ни в одно цветовое правило (диагностика качества анкеров).

ВАЖНО — ограничения:
  - Никакого трекинга движения здесь нет (это дублировало бы Cloud Mask/IR
    motion) — только качественный тренд фазы/группы, дополняющий IR 10.5.
  - Ординальный индекс/группа — НЕ физическая шкала, только для
    относительного тренда.
  - Первая версия анкеров не откалибрована по реальным сценам — см.
    unclassified_fraction в выводе, при высокой доле анкеры надо пересмотреть.

Пишет data/eumetsat_cloud_phase_type.json (результат) и
data/eumetsat_cloud_phase_type_buffer.npz (персистентный буфер, 2 канала:
phase_ordinal, type_group + valid-маска).
"""

import os

import numpy as np

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_phase_type.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_phase_type_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_phase_type_buffer.npz")

LAYER_PHASE = "mtg_fd:rgb_cloudphase"
LAYER_TYPE = "mtg_fd:rgb_cloudtype"

TILE_SIZE = fc.TILE_SIZE
LOCAL_RADIUS_KM = fc.LOCAL_RADIUS_KM

MAX_FRAMES = 13                  # 13 кадров * 10 мин шаг = 120 мин (2 часа)
MIN_FRAMES_FOR_INCREMENTAL = 2
STEP_MINUTES = 10
STALE_BUFFER_SECONDS = 25 * 60   # ~2.5x шага, как у остальных 10-минутных слоёв

PHASE_CHANGE_THRESHOLD = 0.6     # изменение среднего ординального индекса фазы
TYPE_CHANGE_THRESHOLD = 0.25     # изменение средней группы типа

# Метки ординального индекса фазы — соответствуют цветовым правилам в
# _classify_phase() выше (см. её докстринг про неоткалиброванные анкеры).
PHASE_LABELS = {
    0: "безоблачно",
    1: "низкая водяная",
    2: "средняя водяная",
    3: "плотная водяная",
    4: "тонкий лёд (перистые)",
    5: "лёд",
    6: "смешанная фаза",
    7: "холодные верхушки (мощная конвекция)",
    8: "гроза",
}

# Cloud Type RGB (mtg_fd:rgb_cloudtype) — ДРУГОЙ слой, отдельная от Phase
# классификация (грубая группа плотности/высоты, не фаза воды/льда). До
# 2026-08-09 type_group использовался только внутренне (roi_type > 0 —
# "это облако"), сама классификация типа никуда не попадала — по прямому
# запросу пользователя ("Фаза и тип вместе будут? Это разные каналы")
# теперь показывается отдельно, рядом с PHASE_LABELS, не вместо него.
TYPE_LABELS = {
    0: "безоблачно",
    1: "низкая/средняя",
    2: "плотная/высокая",
}


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def _rgb_to_hsv_vec(arr):
    """arr: (H,W,3) uint8 RGB -> (h_deg, s, v), все (H,W) float, векторно.
    Стандартная формула RGB->HSV без внешних зависимостей (matplotlib нет
    в requirements пайплайна)."""
    rgb = arr.astype(np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc > 1e-6, delta / np.where(maxc > 1e-6, maxc, 1), 0.0)

    h = np.zeros_like(maxc)
    safe_delta = np.where(delta > 1e-6, delta, 1.0)
    rc = (maxc - r) / safe_delta
    gc = (maxc - g) / safe_delta
    bc = (maxc - b) / safe_delta

    is_r = (maxc == r) & (delta > 1e-6)
    is_g = (maxc == g) & (delta > 1e-6) & (~is_r)
    is_b = (maxc == b) & (delta > 1e-6) & (~is_r) & (~is_g)

    h = np.where(is_r, (bc - gc), h)
    h = np.where(is_g, 2.0 + rc - bc, h)
    h = np.where(is_b, 4.0 + gc - rc, h)
    h = (h / 6.0) % 1.0
    h_deg = h * 360.0
    return h_deg, s, v


def _in_hue_range(h_deg, lo, hi):
    """Диапазон, корректно обрабатывающий переход через 0/360 (например 345-15)."""
    if lo <= hi:
        return (h_deg >= lo) & (h_deg <= hi)
    return (h_deg >= lo) | (h_deg <= hi)


def _classify_phase(rgba):
    """arr: (H,W,4) RGBA -> (phase_ordinal (H,W) float, valid (H,W) bool).
    valid=False там, где alpha=0 (нет данных) ИЛИ пиксель не попал уверенно
    ни в одно цветовое правило (см. докстринг модуля — первая, не
    откалиброванная версия анкеров)."""
    alpha_valid = rgba[:, :, 3] > 0
    h_deg, s, v = _rgb_to_hsv_vec(rgba[:, :, :3])

    ordinal = np.full(h_deg.shape, -1.0, dtype=np.float32)
    matched = np.zeros(h_deg.shape, dtype=bool)

    def _set(mask, value):
        nonlocal ordinal, matched
        new = mask & (~matched)
        ordinal = np.where(new, value, ordinal)
        matched = matched | new

    _set(v < 0.22, 0.0)                                                    # тёмный: безоблачно
    _set((s < 0.18) & (v > 0.80), 3.0)                                     # ярко-белый: плотная водяная
    _set(_in_hue_range(h_deg, 265, 300) & (s > 0.25), 8.0)                 # фиолетовый: гроза
    _set(_in_hue_range(h_deg, 300, 345) & (s > 0.25), 6.0)                 # розовый: смешанная фаза
    # Разделение "яркий красный (холодные верхушки Cb)" и "красно-коричневая
    # суша" — по Value (яркость), а не Saturation: у настоящего коричневого
    # насыщенность часто выше, чем у чистого красного, поэтому порог по S
    # пересекался бы. Гроза — только очень яркий красный; суша — более тусклый.
    _set(_in_hue_range(h_deg, 345, 15) & (s > 0.4) & (v > 0.65), 7.0)      # яркий красный: холодные верхушки Cb
    _set(_in_hue_range(h_deg, 215, 245) & (s > 0.25), 5.0)                 # синий: лёд
    _set(_in_hue_range(h_deg, 180, 215) & (s >= 0.15) & (s <= 0.5), 4.0)   # голубовато-белый: тонкий лёд
    _set(_in_hue_range(h_deg, 45, 65) & (s > 0.3), 2.0)                    # жёлтый: средняя водяная
    _set(_in_hue_range(h_deg, 80, 160) & (s > 0.2), 1.0)                   # зелёный: низкая водяная
    # красно-коричневый/охра (суша, безоблачно) — реальный коричневый лежит
    # на Hue ~20-30° (между красным 0° и жёлтым 60°), а не около 0°, поэтому
    # окно шире, чем у чистого красного; тусклее по V, чем яркий шторм-топ
    _set(_in_hue_range(h_deg, 345, 45) & (s >= 0.15) & (v >= 0.2) & (v <= 0.65), 0.0)

    valid = alpha_valid & matched
    return ordinal, valid


def _classify_type(rgba):
    """Та же логика хода, но итог — грубая группа 0/1/2 (см. докстринг)."""
    alpha_valid = rgba[:, :, 3] > 0
    h_deg, s, v = _rgb_to_hsv_vec(rgba[:, :, :3])

    group = np.full(h_deg.shape, -1.0, dtype=np.float32)
    matched = np.zeros(h_deg.shape, dtype=bool)

    def _set(mask, value):
        nonlocal group, matched
        new = mask & (~matched)
        group = np.where(new, value, group)
        matched = matched | new

    _set(v < 0.22, 0.0)                                                     # безоблачно (тёмное море)
    _set((s < 0.18) & (v > 0.80), 2.0)                                      # ярко-белый: плотная/высокая
    _set(_in_hue_range(h_deg, 265, 300) & (s > 0.25), 2.0)                  # фиолетовый: гроза
    _set(_in_hue_range(h_deg, 300, 345) & (s > 0.25), 2.0)                  # розовый: конвекция (грубо, см. докстринг)
    _set(_in_hue_range(h_deg, 345, 15) & (s > 0.4) & (v > 0.65), 2.0)       # яркий красный: холодные верхушки
    _set(_in_hue_range(h_deg, 215, 245) & (s > 0.25), 2.0)                  # синий: высокая ледяная
    _set(_in_hue_range(h_deg, 180, 215) & (s >= 0.15) & (s <= 0.5), 2.0)    # голубовато-белый: перистые
    _set(_in_hue_range(h_deg, 45, 65) & (s > 0.3), 1.0)                     # жёлтый: средняя
    _set(_in_hue_range(h_deg, 80, 160) & (s > 0.2), 1.0)                    # зелёный: низкая
    # красно-коричневый/охра (суша, безоблачно) — реальный коричневый лежит
    # на Hue ~20-30° (между красным 0° и жёлтым 60°), а не около 0°, поэтому
    # окно шире, чем у чистого красного; тусклее по V, чем яркий шторм-топ
    _set(_in_hue_range(h_deg, 345, 45) & (s >= 0.15) & (v >= 0.2) & (v <= 0.65), 0.0)

    valid = alpha_valid & matched
    return group, valid


def _pack_frame(phase_ordinal, phase_valid, type_group, type_valid):
    valid = (phase_valid & type_valid).astype(np.float32)
    return np.stack([phase_ordinal.astype(np.float32),
                      type_group.astype(np.float32), valid], axis=0)


def _unpack_frame(packed):
    return packed[0], packed[1], packed[2] > 0.5


def _local_area_mask():
    fc_ = fc
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * fc_.KM_PER_PX_X
    dy_km = (rows - center) * fc_.KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def _buffer_status(n_frames):
    eta_min = max(0, (MAX_FRAMES - n_frames) * STEP_MINUTES)
    span_now = max(0, (n_frames - 1) * STEP_MINUTES)
    span_target = (MAX_FRAMES - 1) * STEP_MINUTES
    if n_frames >= MAX_FRAMES:
        note = f"буфер заполнен ({n_frames}/{MAX_FRAMES}), тренд по полному окну ~{span_target} мин"
    else:
        note = (f"в памяти {n_frames}/{MAX_FRAMES} снимков (~{span_now} мин истории), "
                f"полное {span_target}-минутное окно накопится через ~{eta_min} мин")
    return {
        "frames_in_memory": n_frames,
        "frames_target": MAX_FRAMES,
        "span_minutes_now": span_now,
        "span_minutes_target": span_target,
        "eta_full_window_min": eta_min,
        "note": note,
    }


def main():
    import json
    now = fc.datetime.now(fc.timezone.utc)
    debug = {}

    times, packed_frames = fc.load_frame_buffer(BUFFER_FILE)

    stale = True
    if times:
        try:
            last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
            stale = (now - last_t).total_seconds() > STALE_BUFFER_SECONDS
        except Exception:
            stale = True

    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_PHASE)
    debug["server_latest_time"] = server_latest_iso

    bootstrap = (not times) or (len(packed_frames) < MIN_FRAMES_FOR_INCREMENTAL) or stale
    debug["bootstrap"] = bootstrap
    debug["buffer_before"] = len(packed_frames)

    if bootstrap:
        if server_latest_iso:
            latest_min = fc._parse_iso_minutes(server_latest_iso)
            times_iso = [
                fc.datetime.fromtimestamp((latest_min - STEP_MINUTES * i) * 60, tz=fc.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:00.000Z")
                for i in range(MAX_FRAMES - 1, -1, -1)
            ]
        else:
            times_iso = fc.build_time_steps(STEP_MINUTES, MAX_FRAMES, latest_as_none=False)

        new_times, new_packed, failed = [], [], []
        for t_iso in times_iso:
            try:
                phase_arr = fc.fetch_tile(LAYER_PHASE, t_iso)
                type_arr = fc.fetch_tile(LAYER_TYPE, t_iso)
            except Exception as e:
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_cloud_phase_type.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            phase_ord, phase_valid = _classify_phase(phase_arr)
            type_grp, type_valid = _classify_type(type_arr)
            new_times.append(t_iso or _fmt_time(now))
            new_packed.append(_pack_frame(phase_ord, phase_valid, type_grp, type_valid))

        if len(new_packed) < MIN_FRAMES_FOR_INCREMENTAL:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": "bootstrap", "failed": failed,
                                         "note": f"годных кадров {len(new_packed)}/{MAX_FRAMES} — недостаточно"})
            print(f"  [WARN] eumetsat_cloud_phase_type.py: bootstrap провалился, годных {len(new_packed)}/{MAX_FRAMES}")
            return

        if failed:
            debug["bootstrap_failed_frames"] = failed
        times, packed_frames = new_times, new_packed
    else:
        last_t_min = fc._parse_iso_minutes(times[-1])
        if server_latest_iso:
            server_min = fc._parse_iso_minutes(server_latest_iso)
            if server_min <= last_t_min:
                fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                             "note": f"сервер ещё не объявил кадр новее {times[-1]}"})
                print(f"  [SKIP] eumetsat_cloud_phase_type.py: новых кадров пока нет")
                return
            next_t_iso = server_latest_iso
        else:
            next_t = fc.datetime.fromtimestamp((last_t_min + STEP_MINUTES) * 60, tz=fc.timezone.utc)
            next_t_iso = _fmt_time(next_t)

        try:
            phase_arr = fc.fetch_tile(LAYER_PHASE, next_t_iso)
            type_arr = fc.fetch_tile(LAYER_TYPE, next_t_iso)
        except Exception as e:
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            print(f"  [SKIP] eumetsat_cloud_phase_type.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return

        phase_ord_new, phase_valid_new = _classify_phase(phase_arr)
        type_grp_new, type_valid_new = _classify_type(type_arr)
        last_phase, _, _ = _unpack_frame(packed_frames[-1])
        if fc.is_duplicate_pair(last_phase, phase_ord_new):
            debug["skipped_duplicate"] = True
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра)"})
            print("  [SKIP] eumetsat_cloud_phase_type.py: новых данных ещё нет (дубль)")
            return

        new_packed = _pack_frame(phase_ord_new, phase_valid_new, type_grp_new, type_valid_new)
        times = (times + [next_t_iso])[-MAX_FRAMES:]
        packed_frames = (packed_frames + [new_packed])[-MAX_FRAMES:]

    fc.save_frame_buffer(BUFFER_FILE, times, packed_frames, MAX_FRAMES)
    debug["buffer_size"] = len(packed_frames)
    debug["buffer_times"] = list(times)

    unpacked = [_unpack_frame(p) for p in packed_frames]
    phase_frames = [u[0] for u in unpacked]
    type_frames = [u[1] for u in unpacked]
    valid_frames = [u[2] for u in unpacked]

    local_mask = _local_area_mask()
    valid_first_local = valid_frames[0] & local_mask
    valid_last_local = valid_frames[-1] & local_mask

    out = {"timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ")}

    unclassified_now = 1.0 - (valid_frames[-1] & local_mask).sum() / max(1, local_mask.sum())
    out["unclassified_fraction_now"] = round(float(unclassified_now), 3)

    if valid_first_local.sum() > 5 and valid_last_local.sum() > 5:
        phase_first = float(phase_frames[0][valid_first_local].mean())
        phase_last = float(phase_frames[-1][valid_last_local].mean())
        phase_delta = phase_last - phase_first
        type_first = float(type_frames[0][valid_first_local].mean())
        type_last = float(type_frames[-1][valid_last_local].mean())
        type_delta = type_last - type_first

        if phase_delta > PHASE_CHANGE_THRESHOLD:
            phase_verdict = "смещается к льду/мощной конвекции"
        elif phase_delta < -PHASE_CHANGE_THRESHOLD:
            phase_verdict = "смещается к воде (распад/ослабление)"
        else:
            phase_verdict = "без существенных изменений"

        if type_delta > TYPE_CHANGE_THRESHOLD:
            type_verdict = "становится плотнее/выше"
        elif type_delta < -TYPE_CHANGE_THRESHOLD:
            type_verdict = "становится реже/ниже"
        else:
            type_verdict = "без существенных изменений"

        out.update({
            "phase_ordinal_now": round(phase_last, 2),
            "phase_ordinal_delta": round(phase_delta, 2),
            "phase_verdict": phase_verdict,
            "type_group_now": round(type_last, 2),
            "type_group_delta": round(type_delta, 2),
            "type_verdict": type_verdict,
        })
    else:
        out["verdict"] = "недостаточно классифицированных пикселей в локальной области"

    # --- ROI-подтверждение той же цели, что выбрал CLM (candidates[0] в
    # cloud_forecast.json) — классификация фазы/типа ИМЕННО её ROI, а не
    # региональное среднее по LOCAL_RADIUS_KM=50 выше. Отвечает на
    # "что за облака: перистые/слоистые и т.д." из задуманного алгоритма
    # (см. docs/topics/eumetsat.md, план от 2026-08-04). Аддитивно.
    target, target_reason = fc.load_primary_target()
    if target is None:
        out["target_confirmation"] = {"confirmed": None, "reason": target_reason}
    else:
        roi_mask = fc.km_bbox_to_pixel_mask(target["bbox_km"], pad_km=2.0)
        roi_valid = valid_frames[-1][roi_mask]
        if roi_valid.sum() < 5:
            out["target_confirmation"] = {
                "confirmed": None,
                "reason": "мало классифицированных пикселей в ROI цели CLM (облачно, но цвет неуверенный, либо вне окна)",
                "target_id": target["target_id"],
            }
        else:
            roi_phase = phase_frames[-1][roi_mask][roi_valid]
            roi_type = type_frames[-1][roi_mask][roi_valid]
            cloud_px = roi_type > 0
            cloud_fraction = float(cloud_px.mean())
            confirmed = cloud_fraction >= 0.5
            dominant_phase_ordinal = float(np.median(roi_phase[cloud_px])) if cloud_px.any() else 0.0
            out["target_confirmation"] = {
                "confirmed": confirmed,
                "target_id": target["target_id"],
                "target_area_km2": target["area_km2"],
                "roi_cloud_fraction": round(cloud_fraction, 3),
                "roi_dominant_phase_ordinal": round(dominant_phase_ordinal, 1),
                "roi_dominant_phase_label": PHASE_LABELS.get(round(dominant_phase_ordinal), "неопределено"),
                "verdict": (
                    "Phase/Type подтверждает: в ROI CLM-цели преобладает облачность"
                    if confirmed else
                    "Phase/Type НЕ подтверждает: в ROI CLM-цели облачность не преобладает — возможно расхождение слоёв"
                ),
            }

    # --- Обогащающий (не voting) анализ крупной системы синоптического
    # масштаба, если CLM её отметил (class=="system"). В отличие от блока
    # выше это НЕ подтверждение существования (система и так очевидно
    # реальна при такой площади, ROI-голосование под неё не нужно — см.
    # docs/topics/eumetsat.md, обсуждение 2026-08-06), а просто описание
    # содержимого: доминирующая фаза/тип внутри её ROI. Аддитивно, поле
    # "confirmed" здесь намеренно отсутствует.
    sys_target, sys_reason = fc.load_system_target()
    if sys_target is None:
        out["system_analysis"] = {"available": False, "reason": sys_reason}
    else:
        sys_roi_mask = fc.km_bbox_to_pixel_mask(sys_target["bbox_km"], pad_km=2.0)
        sys_roi_valid = valid_frames[-1][sys_roi_mask]
        if sys_roi_valid.sum() < 5:
            out["system_analysis"] = {
                "available": False,
                "reason": "мало классифицированных пикселей в ROI системы (облачно, но цвет неуверенный, либо вне окна)",
                "target_id": sys_target["target_id"],
            }
        else:
            sys_roi_phase = phase_frames[-1][sys_roi_mask][sys_roi_valid]
            sys_roi_type = type_frames[-1][sys_roi_mask][sys_roi_valid]
            sys_cloud_px = sys_roi_type > 0
            sys_cloud_fraction = float(sys_cloud_px.mean())
            sys_dominant_phase = float(np.median(sys_roi_phase[sys_cloud_px])) if sys_cloud_px.any() else 0.0
            sys_dominant_type = float(np.median(sys_roi_type[sys_cloud_px])) if sys_cloud_px.any() else 0.0
            out["system_analysis"] = {
                "available": True,
                "target_id": sys_target["target_id"],
                "area_km2": sys_target["area_km2"],
                "roi_cloud_fraction": round(sys_cloud_fraction, 3),
                "roi_dominant_phase_ordinal": round(sys_dominant_phase, 1),
                "roi_dominant_phase_label": PHASE_LABELS.get(round(sys_dominant_phase), "неопределено"),
                "roi_dominant_type_label": TYPE_LABELS.get(round(sys_dominant_type), "неопределено"),
            }

    # --- То же самое, но для ВСЕХ систем (не только ближайшей выше) — по
    # запросу 2026-08-09: "подтверждение от остальных каналов для каждой
    # системы", не только для ближайшей. Отдельный список, старое поле
    # system_analysis (выше) не трогали — его читает nearby_precip.js для
    # цветовой метки кандидата, ломать не стали.
    system_analysis_all = []
    for st in fc.load_system_targets_all():
        roi_mask = fc.km_bbox_to_pixel_mask(st["bbox_km"], pad_km=2.0)
        roi_valid = valid_frames[-1][roi_mask]
        if roi_valid.sum() < 5:
            system_analysis_all.append({
                "target_id": st["target_id"],
                "available": False,
                "reason": "мало классифицированных пикселей в ROI (облачно, но цвет неуверенный, либо вне окна)",
            })
            continue
        roi_phase = phase_frames[-1][roi_mask][roi_valid]
        roi_type = type_frames[-1][roi_mask][roi_valid]
        cloud_px = roi_type > 0
        cloud_fraction = float(cloud_px.mean())
        dominant_phase = float(np.median(roi_phase[cloud_px])) if cloud_px.any() else 0.0
        system_analysis_all.append({
            "target_id": st["target_id"],
            "available": True,
            "roi_cloud_fraction": round(cloud_fraction, 3),
            "roi_dominant_phase_label": PHASE_LABELS.get(round(dominant_phase), "неопределено"),
        })
    out["system_analysis_all"] = system_analysis_all

    out["buffer_status"] = _buffer_status(len(packed_frames))
    out["method_note"] = (
        f"Персистентный буфер до {MAX_FRAMES} кадров Cloud Phase RGB + Cloud Type RGB "
        f"(шаг {STEP_MINUTES} мин, до 2 часов). Анкеры цвета — HSV-диапазоны, ПЕРВАЯ, "
        "не откалиброванная по реальным сценам версия (у обоих слоёв нет официальной "
        "легенды — это настоящие RGB-композиты, GetLegendGraphic возвращает не легенду). "
        "phase_ordinal (0..8) — безоблачно -> вода (низкая/средняя/плотная) -> лёд "
        "(тонкий/плотный) -> смешанная фаза -> холодные верхушки Cb -> гроза. "
        "type_group (0..2) — безоблачно/низкая-средняя/плотная-высокая. Тренд — сравнение "
        f"первого и последнего кадра буфера в радиусе {round(LOCAL_RADIUS_KM)}км. "
        "unclassified_fraction_now — доля пикселей, не попавших уверенно ни в одно "
        "цветовое правило: при большом значении анкеры нужно пересматривать."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_cloud_phase_type.py: phase={out.get('phase_ordinal_now')}, "
          f"type={out.get('type_group_now')}, unclassified={out['unclassified_fraction_now']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Раньше падение здесь было ПОЛНОСТЬЮ невидимым: subprocess.run() в
        # gh_satellite_pipeline.py вызывается без check=True, необработанное
        # исключение тут не роняет ни job, ни оркестратор, просто основной
        # data/eumetsat_cloud_phase_type.json не обновляется — обнаружилось
        # только по запросу 2026-08-09 ("Фаза пустая, канал работает, а
        # разбора нет"), снапшот был устаревшим на 52 минуты. Основной
        # OUT_FILE НЕ трогаем (пусть отдаёт последний валидный результат,
        # это лучше, чем ничего) — пишем traceback только в DEBUG_FILE,
        # чтобы в следующий раз ошибку можно было увидеть через
        # data/eumetsat_cloud_phase_type_debug.json, не копаясь в логах
        # Actions (которые недоступны Claude — blob storage не в allowlist
        # сети песочницы).
        import traceback
        try:
            fc.write_debug(DEBUG_FILE, {
                "status": "error",
                "timestamp": fc.datetime.now(fc.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
        except Exception:
            pass
        print(f"  [ERROR] eumetsat_cloud_phase_type.py: {e}")
        raise
