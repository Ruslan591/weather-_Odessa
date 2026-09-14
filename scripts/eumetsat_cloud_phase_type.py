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
# Ночная замена — по запросу 2026-08-09 ("на свету Phase/Type, в темноте
# Fog/Dust"; пользователь сам подтвердил точные имена слоёв через Termux
# GetCapabilities). НЕ HSV-анкерная классификация (см. _classify_contrast
# ниже) — пользователь прямо сказал, что результат Phase/Type его "не
# удовлетворяет", у Fog/Dust совсем другая цветовая семантика (пыль/туман,
# не фаза/тип облака), калибровать вторые анкеры с нуля сейчас не стали.
LAYER_NIGHT_A = "mtg_fd:rgb_fog"
LAYER_NIGHT_B = "mtg_fd:rgb_dust"
MODE_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_phase_type_mode.json")

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
    _set(_in_hue_range(h_deg, 215, 245) & (s > 0.25) & (s <= 0.45), 5.0)   # синий: лёд (s_max=0.45 по калибровке 2026-08-12, см. docs/topics/eumetsat.md)
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
    _set(_in_hue_range(h_deg, 215, 245) & (s > 0.25) & (s <= 0.45), 2.0)    # синий: высокая ледяная (s_max=0.45 по калибровке 2026-08-12, см. docs/topics/eumetsat.md)
    _set(_in_hue_range(h_deg, 180, 215) & (s >= 0.15) & (s <= 0.5), 2.0)    # голубовато-белый: перистые
    _set(_in_hue_range(h_deg, 45, 65) & (s > 0.3), 1.0)                     # жёлтый: средняя
    _set(_in_hue_range(h_deg, 80, 160) & (s > 0.2), 1.0)                    # зелёный: низкая
    # красно-коричневый/охра (суша, безоблачно) — реальный коричневый лежит
    # на Hue ~20-30° (между красным 0° и жёлтым 60°), а не около 0°, поэтому
    # окно шире, чем у чистого красного; тусклее по V, чем яркий шторм-топ
    _set(_in_hue_range(h_deg, 345, 45) & (s >= 0.15) & (v >= 0.2) & (v <= 0.65), 0.0)

    valid = alpha_valid & matched
    return group, valid


def _classify_fog_brightness(rgba, gray_max=0.25):
    """Классификатор Fog RGB (LAYER_NIGHT_A), откалиброван по SYNOP
    2026-08-13 (73 ночных срока станции 33837, см. docs/topics/
    eumetsat.md). ЗАМЕНИЛ self-relative контраст (_classify_contrast) —
    тот провалился для Fog: НЕ монотонно по N, ложные 40-70% на любом
    радиусе/пороге sigma. Оказалось, сигнал абсолютный и ОБРАТНЫЙ: ROI
    темнее при большей облачности (r=25км: gray_mean 0.412 при N=0 ->
    0.307 при N=8-9). Порог gray_max=0.25 на r=25км дал: ложное N=0=0.4%,
    N=1-2=2.2%, детект N=8-9=52.7%, почти монотонно по всем бакетам —
    выбран сознательно консервативный порог (низкое ложное), не самый
    высокий детект (у gray_max=0.30 детект выше, 58%, но ложные растут
    до 5-15% и не монотонно).
    ВАЖНО: этот классификатор — ТОЛЬКО для Fog (LAYER_A). Dust (LAYER_B)
    пока НЕ откалиброван — остаётся на _classify_contrast() ниже, до
    отдельной калибровки тем же методом (следующий шаг в очереди)."""
    alpha_valid = rgba[:, :, 3] > 0
    gray = rgba[:, :, :3].astype(np.float32).mean(axis=2) / 255.0
    ordinal = (gray < gray_max).astype(np.float32)
    return ordinal, alpha_valid


def _classify_contrast(rgba, sigma_threshold=1.0):
    """Ночная замена _classify_phase/_classify_type для Dust RGB — по
    запросу 2026-08-09. НЕ анкерная классификация (нет попытки сказать
    "это конкретно туман" или "это конкретно пыль" по цвету) — вместо
    этого self-relative контраст яркости, ТОТ ЖЕ принцип, что уже
    проверен и одобрен в eumetsat_ir_motion.py (roi_contrast_sigma).
    Возвращает (ordinal (H,W) float 0/1, valid (H,W) bool):
      1 — пиксель заметно отличается по яркости от медианы всего тайла
          (потенциальный сигнал — туман ИЛИ пыль, не различаем ЧТО именно)
      0 — фон, ничего примечательного
    valid = alpha>0 везде (в отличие от HSV-анкеров тут нет "неопознанного
    цвета" — единственная причина невалидности пикселя — нет данных).
    ВНИМАНИЕ: для Fog (LAYER_A) этот метод ПРОВАЛИЛСЯ при калибровке
    2026-08-13 (не монотонно по N) — заменён на _classify_fog_brightness()
    выше. Здесь остаётся ТОЛЬКО для Dust (LAYER_B), пока не откалиброван
    отдельно тем же методом (абсолютный порог по gray)."""
    alpha_valid = rgba[:, :, 3] > 0
    gray = rgba[:, :, :3].astype(np.float32).mean(axis=2) / 255.0
    vals = gray[alpha_valid]
    if vals.size < 10:
        return np.zeros(gray.shape, dtype=np.float32), np.zeros(gray.shape, dtype=bool)
    median = float(np.median(vals))
    std = float(np.std(vals)) or 1e-6
    sigma = (gray - median) / std
    ordinal = (np.abs(sigma) >= sigma_threshold).astype(np.float32)
    return ordinal, alpha_valid


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

    # --- Выбор день/ночь набора слоёв — по запросу 2026-08-09. Грубая
    # оценка через fc.is_daytime() (локальный час, без сезонной точности,
    # см. её докстринг) — этого достаточно, чтобы развести ветки; секундная
    # точность восхода/заката тут не нужна.
    is_day = fc.is_daytime(_fmt_time(now))
    mode = "day" if is_day else "night"
    if is_day:
        LAYER_A, LAYER_B = LAYER_PHASE, LAYER_TYPE
        classify_a, classify_b = _classify_phase, _classify_type
        labels_a, labels_b = PHASE_LABELS, TYPE_LABELS
    else:
        LAYER_A, LAYER_B = LAYER_NIGHT_A, LAYER_NIGHT_B
        classify_a, classify_b = _classify_fog_brightness, _classify_contrast
        labels_a = {0: "нет выраженного сигнала (Fog RGB)", 1: "заметное отклонение — возможен туман/дымка"}
        labels_b = {0: "нет выраженного сигнала (Dust RGB)", 1: "заметное отклонение — возможна пыль"}

    # Смена режима день<->ночь между запусками делает буфер (накопленный на
    # ДРУГОЙ паре слоёв) бессмысленным для тренда — сравнивать Phase-ординал
    # часовой давности с сегодняшним Fog-сигналом не имеет смысла. При смене
    # режима принудительно считаем буфер невалидным (как будто stale) —
    # естественно уйдёт в существующую ветку bootstrap ниже, без отдельного
    # dublirующего пути.
    last_mode = None
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            last_mode = json.load(f).get("mode")
    except (OSError, json.JSONDecodeError):
        pass
    mode_changed = last_mode is not None and last_mode != mode
    os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
    with open(MODE_FILE, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "timestamp": _fmt_time(now)}, f)

    times, packed_frames = fc.load_frame_buffer(BUFFER_FILE)
    if mode_changed:
        times, packed_frames = [], []
        debug["mode_changed"] = f"{last_mode} -> {mode}, буфер сброшен"

    stale = True
    if times:
        try:
            last_t = fc.datetime.strptime(str(times[-1]), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=fc.timezone.utc)
            stale = (now - last_t).total_seconds() > STALE_BUFFER_SECONDS
        except Exception:
            stale = True

    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_A)
    debug["server_latest_time"] = server_latest_iso
    debug["mode"] = mode

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
                phase_arr = fc.fetch_tile(LAYER_A, t_iso)
                type_arr = fc.fetch_tile(LAYER_B, t_iso)
            except Exception as e:
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_cloud_phase_type.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            phase_ord, phase_valid = classify_a(phase_arr)
            type_grp, type_valid = classify_b(type_arr)
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
                fc.log_skip_event("eumetsat_cloud_phase_type.py", "source_stale",
                                   layer=LAYER_A, server_latest_time=server_latest_iso,
                                   extra={"last_known_frame": times[-1]})
                fc.record_pipeline_health("eumetsat_cloud_phase_type.py", ok=False)
                print(f"  [SKIP] eumetsat_cloud_phase_type.py: новых кадров пока нет")
                return
            next_t_iso = server_latest_iso
        else:
            next_t = fc.datetime.fromtimestamp((last_t_min + STEP_MINUTES) * 60, tz=fc.timezone.utc)
            next_t_iso = _fmt_time(next_t)

        try:
            phase_arr = fc.fetch_tile(LAYER_A, next_t_iso)
            type_arr = fc.fetch_tile(LAYER_B, next_t_iso)
        except Exception as e:
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            fc.log_skip_event("eumetsat_cloud_phase_type.py", "next_frame_not_ready",
                               layer=LAYER_A, server_latest_time=server_latest_iso,
                               extra={"awaited_time": next_t_iso, "error": str(e)})
            print(f"  [SKIP] eumetsat_cloud_phase_type.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return

        phase_ord_new, phase_valid_new = classify_a(phase_arr)
        type_grp_new, type_valid_new = classify_b(type_arr)
        last_phase, _, _ = _unpack_frame(packed_frames[-1])
        if fc.is_duplicate_pair(last_phase, phase_ord_new):
            debug["skipped_duplicate"] = True
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра)"})
            fc.log_skip_event("eumetsat_cloud_phase_type.py", "duplicate_frame",
                               layer=LAYER_A, server_latest_time=server_latest_iso)
            fc.record_pipeline_health("eumetsat_cloud_phase_type.py", ok=False)
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

    out = {"timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode}

    unclassified_now = 1.0 - (valid_frames[-1] & local_mask).sum() / max(1, local_mask.sum())
    out["unclassified_fraction_now"] = round(float(unclassified_now), 3)

    if valid_first_local.sum() > 5 and valid_last_local.sum() > 5:
        phase_first = float(phase_frames[0][valid_first_local].mean())
        phase_last = float(phase_frames[-1][valid_last_local].mean())
        phase_delta = phase_last - phase_first
        type_first = float(type_frames[0][valid_first_local].mean())
        type_last = float(type_frames[-1][valid_last_local].mean())
        type_delta = type_last - type_first

        if is_day:
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
        else:
            # Ночью ordinal — доля 0/1 аномальных пикселей (Fog/Dust), не
            # фаза/тип, "смещается к льду" не имеет смысла — просто
            # растёт/падает доля сигнала.
            if phase_delta > 0.1:
                phase_verdict = "доля Fog-сигнала растёт"
            elif phase_delta < -0.1:
                phase_verdict = "доля Fog-сигнала падает"
            else:
                phase_verdict = "без существенных изменений"
            if type_delta > 0.1:
                type_verdict = "доля Dust-сигнала растёт"
            elif type_delta < -0.1:
                type_verdict = "доля Dust-сигнала падает"
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
            if is_day:
                # Днём type_group==0 значит "безоблачно" — гейт cloud_px по
                # нему валиден, ordinal Phase внутри облачных пикселей имеет
                # смысл (см. докстринг PHASE_LABELS).
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
                    "roi_dominant_phase_label": labels_a.get(round(dominant_phase_ordinal), "неопределено"),
                    "verdict": (
                        "Phase/Type подтверждает: в ROI CLM-цели преобладает облачность"
                        if confirmed else
                        "Phase/Type НЕ подтверждает: в ROI CLM-цели облачность не преобладает — возможно расхождение слоёв"
                    ),
                }
            else:
                # Ночью НЕ гейтуем по roi_type>0 — тут это доля аномальных
                # Dust-пикселей, а не "облачно/нет", гейт по нему обнулил бы
                # почти всё. Просто средняя доля аномалии Fog/Dust по ВСЕМ
                # валидным пикселям ROI — не "облачность", а "заметный
                # сигнал" (см. _classify_contrast).
                fog_fraction = float(roi_phase.mean())
                dust_fraction = float(roi_type.mean())
                out["target_confirmation"] = {
                    "confirmed": None,
                    "target_id": target["target_id"],
                    "target_area_km2": target["area_km2"],
                    "roi_fog_signal_fraction": round(fog_fraction, 3),
                    "roi_dust_signal_fraction": round(dust_fraction, 3),
                    "verdict": "Ночь: Fog/Dust RGB — грубый сигнал контраста, не полноценное подтверждение (confirmed не считается)",
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
            if is_day:
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
                    "roi_dominant_phase_label": labels_a.get(round(sys_dominant_phase), "неопределено"),
                    "roi_dominant_type_label": labels_b.get(round(sys_dominant_type), "неопределено"),
                }
            else:
                # Ночью — см. target_confirmation выше, без cloud_px гейта.
                out["system_analysis"] = {
                    "available": True,
                    "target_id": sys_target["target_id"],
                    "area_km2": sys_target["area_km2"],
                    "roi_dominant_phase_label": labels_a.get(1 if float(sys_roi_phase.mean()) >= 0.15 else 0, "неопределено"),
                    "roi_dominant_type_label": labels_b.get(1 if float(sys_roi_type.mean()) >= 0.15 else 0, "неопределено"),
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
        if is_day:
            cloud_px = roi_type > 0
            cloud_fraction = float(cloud_px.mean())
            dominant_phase = float(np.median(roi_phase[cloud_px])) if cloud_px.any() else 0.0
            dominant_type = float(np.median(roi_type[cloud_px])) if cloud_px.any() else 0.0
            system_analysis_all.append({
                "target_id": st["target_id"],
                "available": True,
                "roi_cloud_fraction": round(cloud_fraction, 3),
                "roi_dominant_phase_label": labels_a.get(round(dominant_phase), "неопределено"),
                "roi_dominant_type_label": labels_b.get(round(dominant_type), "неопределено"),
            })
        else:
            # Ночью — см. target_confirmation выше, без cloud_px гейта:
            # raw доля аномальных пикселей Fog/Dust по ROI, не "облачность".
            system_analysis_all.append({
                "target_id": st["target_id"],
                "available": True,
                "roi_dominant_phase_label": labels_a.get(1 if float(roi_phase.mean()) >= 0.15 else 0, "неопределено"),
                "roi_dominant_type_label": labels_b.get(1 if float(roi_type.mean()) >= 0.15 else 0, "неопределено"),
            })
    out["system_analysis_all"] = system_analysis_all

    # --- То же самое, но для ВСЕХ локальных очагов (не только первичного
    # target_confirmation выше) — по запросу 2026-08-09 ("такая же таблица,
    # как для систем, для локальных очагов"), см. docs/topics/eumetsat.md,
    # Horizon. Не заменяет target_confirmation (тот учитывает реестр ложных
    # срабатываний через fc.load_primary_target()) — построчный снапшот по
    # всем кандидатам CLM для обзорной таблицы. Та же день/ночь логика.
    local_analysis_all = []
    for lt in fc.load_local_targets_all():
        loc_roi_mask = fc.km_bbox_to_pixel_mask(lt["bbox_km"], pad_km=2.0)
        loc_roi_valid = valid_frames[-1][loc_roi_mask]
        if loc_roi_valid.sum() < 5:
            local_analysis_all.append({
                "target_id": lt["target_id"],
                "available": False,
                "reason": "мало классифицированных пикселей в ROI (облачно, но цвет неуверенный, либо вне окна)",
            })
            continue
        loc_roi_phase = phase_frames[-1][loc_roi_mask][loc_roi_valid]
        loc_roi_type = type_frames[-1][loc_roi_mask][loc_roi_valid]
        if is_day:
            loc_cloud_px = loc_roi_type > 0
            loc_cloud_fraction = float(loc_cloud_px.mean())
            loc_dominant_phase = float(np.median(loc_roi_phase[loc_cloud_px])) if loc_cloud_px.any() else 0.0
            loc_dominant_type = float(np.median(loc_roi_type[loc_cloud_px])) if loc_cloud_px.any() else 0.0
            local_analysis_all.append({
                "target_id": lt["target_id"],
                "available": True,
                "roi_cloud_fraction": round(loc_cloud_fraction, 3),
                "confirmed": loc_cloud_fraction >= 0.5,
                "roi_dominant_phase_label": labels_a.get(round(loc_dominant_phase), "неопределено"),
                "roi_dominant_type_label": labels_b.get(round(loc_dominant_type), "неопределено"),
            })
        else:
            # Ночью — без cloud_px гейта (см. target_confirmation выше),
            # confirmed не считается (грубый сигнал Fog/Dust, не полноценное
            # подтверждение облачности).
            local_analysis_all.append({
                "target_id": lt["target_id"],
                "available": True,
                "confirmed": None,
                "roi_dominant_phase_label": labels_a.get(1 if float(loc_roi_phase.mean()) >= 0.15 else 0, "неопределено"),
                "roi_dominant_type_label": labels_b.get(1 if float(loc_roi_type.mean()) >= 0.15 else 0, "неопределено"),
            })
    out["local_analysis_all"] = local_analysis_all

    out["buffer_status"] = _buffer_status(len(packed_frames))
    if is_day:
        out["method_note"] = (
            f"[День] Персистентный буфер до {MAX_FRAMES} кадров Cloud Phase RGB + Cloud Type RGB "
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
    else:
        out["method_note"] = (
            f"[Ночь] Персистентный буфер до {MAX_FRAMES} кадров Fog RGB + Dust RGB "
            f"(шаг {STEP_MINUTES} мин, до 2 часов), заменяют Cloud Phase/Type RGB "
            "(ненадёжны ночью — дневные composites, см. docs/topics/eumetsat.md). "
            "НЕ цветовая классификация (у Phase/Type она не откалибрована и не "
            "устроила пользователя, здесь решили не повторять) — self-relative "
            "контраст яркости, тот же принцип, что roi_contrast_sigma в "
            "eumetsat_ir_motion.py. ordinal 0/1 = нет/есть заметное отклонение "
            "яркости от медианы тайла — НЕ различает 'это туман' от 'это пыль' "
            "по смыслу, просто two отдельных RGB-источника (Fog vs Dust) с "
            "одинаковым методом детекции аномалии каждый. Первая версия, порог "
            "sigma_threshold=1.0 не откалиброван по живым сценам."
        )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    fc.record_pipeline_health("eumetsat_cloud_phase_type.py", ok=True)
    print(f"  [OK] eumetsat_cloud_phase_type.py: mode={mode}, phase={out.get('phase_ordinal_now')}, "
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

