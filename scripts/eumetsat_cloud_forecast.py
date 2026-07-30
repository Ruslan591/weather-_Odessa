"""
eumetsat_cloud_forecast.py — мини-прогноз облачности для Одессы:
  1) движение области облачности/просвета (приближается/пройдёт мимо/ETA)
  2) тренд ПЛОТНОСТИ (уплотняется/рассеивается) — доля облачных пикселей
     в локальной области вокруг города за последние кадры
  3) тренд ВЫСОТЫ (растут/опускаются вершины) — по Cloud Top Height,
     усреднённой ТОЛЬКО по облачным пикселям локальной области
  4) тренд ФОРМЫ (вытягивается/остаётся компактной) — аспект-рейшо
     bounding box крупнейшего облачного пятна в локальной области

ЗАЧЕМ ПЕРСИСТЕНТНЫЙ БУФЕР (data/eumetsat_cloud_buffer.npz):
Раньше каждый прогон качал N_FRAMES=4 кадра msg_fes:clm + 4 кадра msg_fes:cth
заново (8 GetMap-запросов), хотя 3 из 4 уже качались в прошлый прогон 15 минут
назад. Теперь буфер хранится между прогонами (как в eumetsat_ir_motion.py и
eumetsat_precip_motion.py): обычный прогон докачивает ТОЛЬКО один новый кадр
(clm+cth = 2 запроса вместо 8), добавляет его в конец, самый старый выпадает
(FIFO, максимум MAX_FRAMES). Полная перезакачка происходит только при
"бутстрапе" — буфера ещё нет, повреждён, или пропущено слишком много прогонов.

ЗАЧЕМ MAX_FRAMES=9 (не 4): msg_fes обновляется раз в 15 минут (см.
eumetsat_ir_motion.py/precip_motion.py про частоты слоёв), поэтому 9 кадров
с шагом 15 мин = 120 минут (ровно 2 часа) истории — по концепции
многоуровневого анализа атмосферы. Тренды плотности/высоты/формы теперь
сравнивают САМЫЙ старый и САМЫЙ новый кадр буфера, то есть по мере наполнения
буфера окно сравнения растёт с ~15 мин (сразу после бутстрапа с нуля) до
полных 2 часов — это ожидаемо и отражено в buffer_status ниже, а не баг.

УПАКОВКА ДВУХ ПОЛЕЙ В ОДИН БУФЕР: field_motion_common.save_frame_buffer()
хранит список 2D-массивов как есть, без привязки к смыслу пикселя — поэтому
на кадр пакуется ОДИН (3,H,W) float32-массив: канал 0 = is_cloud (0/1),
канал 1 = valid (0/1, нет данных = 0), канал 2 = cth_ordinal_index. Это
позволяет переиспользовать общие load_frame_buffer/save_frame_buffer без
изменений в field_motion_common.py.

МЕТОД ДВИЖЕНИЯ: классификация по 3 цветам легенды Cloud Mask, сдвиг поля
между каждой парой кадров буфера через FFT phase correlation (окно Ханнинга),
скорости усреднены по всем парам с РЕАЛЬНЫМ dt между кадрами (буфер может
содержать пропуски — одиночный недоступный слот не обрывает весь прогон, см.
bootstrap ниже, — тогда шаг между соседними кадрами не всегда ровно
STEP_MINUTES). Позиция ближайшей "противоположной" точки (просвет, если
сейчас облачно; облако, если ясно) берётся с самого свежего кадра буфера.

МЕТОД ПЛОТНОСТИ/ВЫСОТЫ/ФОРМЫ: сравниваем ПЕРВЫЙ и ПОСЛЕДНИЙ кадр буфера в
локальной области (круг радиуса LOCAL_RADIUS_KM вокруг Одессы):
  - плотность = доля облачных пикселей в круге
  - высота = средний "ординальный индекс" по цветовой шкале CTH (НЕ метры —
    официальной таблицы цвет→высота у нас, в отличие от RainViewer, нет;
    анкеры цветов подобраны по виду легенды по возрастанию, только для
    ОТНОСИТЕЛЬНОГО тренда роста/понижения, не для абсолютных чисел),
    усреднённый ТОЛЬКО по пикселям, которые Cloud Mask в тот же момент
    считает облачными (иначе "нет данных/прозрачно" перепутается с "низкие
    облака", у обоих чёрный/тёмный цвет)
  - форма = aspect ratio (макс.сторона/мин.сторона bounding box) крупнейшей
    связной облачной области в круге (scipy.ndimage.label)

ВАЖНО — ограничения:
  - Линейная экстраполяция скорости, разрешение Cloud Mask/CTH ~8-10км/px.
  - Тренды плотности/высоты/формы — сравнение первого и последнего кадра
    буфера (до 2 часов при заполненном буфере), не полноценная регрессия.
    Пороги для "существенно изменилось" подобраны эмпирически, не
    откалиброваны по историческим данным.
  - Высота — ординальный индекс по приближённым анкерам цвета, не метры.
  - Прозрачные/необработанные (no-data) пиксели явно исключаются из
    классификации (не прибиваются к ближайшему цвету), а поиск края
    облако/просвет игнорирует связные пятна меньше MIN_SIGNIFICANT_BLOB_PX
    (шум/антиалиасинг границы).
  - Обратный случай (сейчас ясно/переменная облачность): если в радиусе
    найдено значимое (после фильтра шума) поле облачности, дополнительно
    считается probability_percent — эвристическая (не физическая) оценка
    вероятности, что оно принесёт изменение погоды, по близости точки
    сближения, площади поля и уверенности в оценке скорости.

Пишет data/eumetsat_cloud_forecast.json (результат) и
data/eumetsat_cloud_buffer.npz (персистентный буфер кадров).
"""

import math
import os

import numpy as np
from scipy import ndimage

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_buffer.npz")

LAYER_CLM = "msg_fes:clm"
LAYER_CTH = "msg_fes:cth"

CENTER_LABEL = "Одесса (СИНОП 33837)"

TILE_SIZE = fc.TILE_SIZE
KM_PER_DEG_LAT = fc.KM_PER_DEG_LAT
KM_PER_DEG_LON = fc.KM_PER_DEG_LON
KM_PER_PX_X = fc.KM_PER_PX_X
KM_PER_PX_Y = fc.KM_PER_PX_Y
HALF_WINDOW_DEG = fc.HALF_WINDOW_DEG

MAX_FRAMES = 9                   # 9 кадров * 15 мин шаг = 120 мин (2 часа)
MIN_FRAMES_FOR_INCREMENTAL = 2   # меньше — недостаточно даже для одной пары
STEP_MINUTES = 15
STALE_BUFFER_SECONDS = 35 * 60   # ~2.3x шага — если последний кадр буфера старше, бутстрап заново
AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02

LOCAL_RADIUS_KM = 50.0           # область вокруг города для плотности/высоты/формы
DENSITY_CHANGE_THRESHOLD = 0.10  # 10 п.п. — считаем существенным изменением
HEIGHT_CHANGE_THRESHOLD = 0.6    # изменение среднего ординального индекса
ASPECT_CHANGE_THRESHOLD = 0.5    # изменение aspect ratio bounding box

# Порог связной области (px), меньше которого пятно считается шумом/
# антиалиасингом границы, а не реальным краем облачного поля. Одновременно
# служит критерием "поле достаточно значимое, чтобы нести изменение погоды"
# для обратного случая (сейчас ясно/переменная облачность).
MIN_SIGNIFICANT_BLOB_PX = 40     # ~50-55 км² при текущем разрешении тайла
# "Опорная" площадь синоптически значимого пятна для нормировки вероятности
# (больше — вероятность влияния ближе к максимуму; меньше — доля от неё).
SIGNIFICANT_AREA_REF_KM2 = 1200.0

CLM_ANCHORS = {
    "clear_water": (0, 0, 255),
    "clear_land": (0, 170, 0),
    "cloud": (255, 255, 255),
}

# Ординальные анкеры для CTH-рампы (приближённо, по виду легенды: чёрный
# внизу шкалы -> ... -> белый вверху). НЕ официальная таблица, только для
# относительного тренда роста/понижения индекса.
CTH_ORDINAL_ANCHORS = [
    (0, (0, 0, 0)),
    (1, (75, 0, 130)),
    (2, (0, 0, 255)),
    (3, (0, 255, 255)),
    (4, (0, 200, 0)),
    (5, (255, 255, 0)),
    (6, (255, 0, 0)),
    (7, (255, 255, 255)),
]
_CTH_IDX = np.array([a[0] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)
_CTH_RGB = np.array([a[1] for a in CTH_ORDINAL_ANCHORS], dtype=np.float32)

COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def _fmt_time(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00.000Z")


def _bearing_compass(dx_km, dy_km):
    bearing = (math.degrees(math.atan2(dx_km, dy_km)) + 360) % 360
    idx = int(((bearing + 22.5) % 360) // 45)
    return bearing, COMPASS[idx]


def _compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def _classify_cloud_mask(arr):
    """arr: (H,W,4) RGBA. Возвращает (is_cloud, valid) — valid=False там, где
    пиксель прозрачный (нет данных/сцена не обработана), такие пиксели не
    участвуют ни в облаке, ни в просвете, а не силой прибиваются к ближайшему
    цвету."""
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


def _cth_ordinal_index(arr):
    """arr: (H,W,4) RGBA -> (H,W) float, ординальный индекс 0..7 (не метры)."""
    h, w = arr.shape[:2]
    pixels = arr[:, :, :3].reshape(-1, 3).astype(np.float32)
    dists = np.sum((pixels[:, None, :] - _CTH_RGB[None, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    return _CTH_IDX[nearest_idx].reshape(h, w)


def _pack_frame(is_cloud, valid, cth_idx):
    """Упаковывает 3 поля кадра в один (3,H,W) float32 массив для буфера
    (см. докстринг модуля — зачем: переиспользовать общий save/load без
    изменений field_motion_common.py)."""
    return np.stack([is_cloud.astype(np.float32), valid.astype(np.float32),
                      cth_idx.astype(np.float32)], axis=0)


def _unpack_frame(packed):
    return packed[0] > 0.5, packed[1] > 0.5, packed[2]


def _pixel_to_km_offset(row, col):
    frac_x = col / (TILE_SIZE - 1)
    frac_y = row / (TILE_SIZE - 1)
    lon = fc.CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = fc.CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - fc.CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - fc.CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


def _local_area_mask():
    """Булев (H,W) — True внутри LOCAL_RADIUS_KM от центра тайла."""
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def _nearest_of_type(is_cloud_mask, valid_mask, want_cloud, min_blob_px=MIN_SIGNIFICANT_BLOB_PX):
    """Ищет ближайшую к центру точку нужного типа (облако/просвет), но только
    внутри связных областей площадью >= min_blob_px — единичные шумовые/
    переходные (антиалиасинг границы) пиксели и no-data не считаются краем.
    Возвращает (dx_km, dy_km, blob_area_km2) для найденного пятна, или None
    если значимых областей нужного типа в кадре не найдено."""
    raw_target = is_cloud_mask if want_cloud else (~is_cloud_mask & valid_mask)
    labeled, n = ndimage.label(raw_target)
    if n == 0:
        return None
    sizes = ndimage.sum(raw_target, labeled, range(1, n + 1))
    keep_labels = np.where(sizes >= min_blob_px)[0] + 1
    if len(keep_labels) == 0:
        return None
    filtered = np.isin(labeled, keep_labels)
    ys, xs = np.where(filtered)
    center_row = center_col = (TILE_SIZE - 1) / 2
    dist_px = np.sqrt((ys - center_row) ** 2 + (xs - center_col) ** 2)
    best_i = np.argmin(dist_px)
    row, col = int(ys[best_i]), int(xs[best_i])
    blob_label = labeled[row, col]
    blob_px = float(sizes[blob_label - 1])
    blob_area_km2 = blob_px * KM_PER_PX_X * KM_PER_PX_Y
    dx_km, dy_km = _pixel_to_km_offset(row, col)
    return dx_km, dy_km, blob_area_km2


def _parabolic_subpixel(c_minus, c_zero, c_plus):
    """Субпиксельная поправка к целочисленному пику по трём соседним точкам
    корреляции (параболическая интерполяция) — без неё любой сдвиг меньше
    1 px (слабый ветер / малый интервал между кадрами) округляется ровно
    до 0. См. ту же функцию в field_motion_common.py."""
    denom = c_minus - 2 * c_zero + c_plus
    if abs(denom) < 1e-9:
        return 0.0
    offset = 0.5 * (c_minus - c_plus) / denom
    return float(np.clip(offset, -0.5, 0.5))


def _phase_shift_px(mask_prev, mask_curr):
    win = np.outer(np.hanning(mask_prev.shape[0]), np.hanning(mask_prev.shape[1]))
    a = (mask_prev.astype(np.float64) - mask_prev.mean()) * win
    b = (mask_curr.astype(np.float64) - mask_curr.mean()) * win
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    r = fb * np.conj(fa)
    denom = np.abs(r)
    denom[denom < 1e-10] = 1e-10
    r = r / denom
    corr = np.fft.ifft2(r).real
    corr = np.fft.fftshift(corr)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    center = np.array(corr.shape) // 2
    dy_px, dx_px = (np.array(peak) - center).tolist()

    row, col = peak
    if 0 < row < corr.shape[0] - 1:
        dy_px += _parabolic_subpixel(corr[row - 1, col], corr[row, col], corr[row + 1, col])
    if 0 < col < corr.shape[1] - 1:
        dx_px += _parabolic_subpixel(corr[row, col - 1], corr[row, col], corr[row, col + 1])

    return dy_px, dx_px


def _is_uniform(mask):
    frac_cloud = mask.mean()
    return min(frac_cloud, 1 - frac_cloud) < MIN_FRACTION_FOR_CORR


def _estimate_motion(masks, times_iso):
    """Как раньше, но dt между КАЖДОЙ парой кадров — РЕАЛЬНЫЙ (из
    таймстемпов буфера), а не фиксированный STEP_MINUTES: персистентный
    буфер может содержать пропуски (одиночный недоступный слот в bootstrap
    пропускается, см. main()), и тогда интервал между соседними кадрами
    может быть кратен шагу — при фиксированном шаге скорость для такой пары
    была бы посчитана неверно."""
    vx_list, vy_list = [], []
    times_min = [fc._parse_iso_minutes(t) for t in times_iso]
    for i in range(len(masks) - 1):
        dt_h = (times_min[i + 1] - times_min[i]) / 60.0
        if dt_h <= 0:
            continue
        m_prev, m_curr = masks[i], masks[i + 1]
        if _is_uniform(m_prev) or _is_uniform(m_curr):
            continue
        dy_px, dx_px = _phase_shift_px(m_prev, m_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def _largest_component_aspect(mask):
    """Aspect ratio (>=1) bounding box крупнейшей связной области True в mask, или None."""
    labeled, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    biggest_label = int(np.argmax(sizes)) + 1
    ys, xs = np.where(labeled == biggest_label)
    h = ys.max() - ys.min() + 1
    w = xs.max() - xs.min() + 1
    return max(h, w) / max(1, min(h, w))


def _density_height_shape_trend(is_cloud_frames, cth_index_frames, valid_frames, local_mask):
    first_cloud, last_cloud = is_cloud_frames[0], is_cloud_frames[-1]
    valid_first_local = valid_frames[0] & local_mask
    valid_last_local = valid_frames[-1] & local_mask
    local_first = first_cloud & local_mask
    local_last = last_cloud & local_mask

    frac_first = local_first.sum() / max(1, valid_first_local.sum())
    frac_last = local_last.sum() / max(1, valid_last_local.sum())
    density_delta = frac_last - frac_first

    if density_delta > DENSITY_CHANGE_THRESHOLD:
        density_verdict = "уплотняется"
    elif density_delta < -DENSITY_CHANGE_THRESHOLD:
        density_verdict = "рассеивается"
    else:
        density_verdict = "без существенных изменений"

    # высота: средний ординальный индекс ТОЛЬКО по облачным пикселям локальной области
    height_verdict = None
    height_delta = None
    if local_first.sum() > 5 and local_last.sum() > 5:
        h_first = float(cth_index_frames[0][local_first].mean())
        h_last = float(cth_index_frames[-1][local_last].mean())
        height_delta = h_last - h_first
        if height_delta > HEIGHT_CHANGE_THRESHOLD:
            height_verdict = "вершины растут (возможно усиление)"
        elif height_delta < -HEIGHT_CHANGE_THRESHOLD:
            height_verdict = "вершины опускаются (возможно ослабление)"
        else:
            height_verdict = "без существенных изменений"

    # форма: aspect ratio крупнейшего пятна в локальной области
    shape_verdict = None
    aspect_delta = None
    aspect_first = _largest_component_aspect(local_first)
    aspect_last = _largest_component_aspect(local_last)
    if aspect_first is not None and aspect_last is not None:
        aspect_delta = aspect_last - aspect_first
        if aspect_delta > ASPECT_CHANGE_THRESHOLD:
            shape_verdict = "вытягивается (возможно формирование линии/фронта)"
        elif aspect_delta < -ASPECT_CHANGE_THRESHOLD:
            shape_verdict = "становится компактнее"
        else:
            shape_verdict = "без существенных изменений"

    return {
        "density_fraction_now": round(float(frac_last), 2),
        "density_delta": round(float(density_delta), 2),
        "density_verdict": density_verdict,
        "height_ordinal_delta": round(height_delta, 2) if height_delta is not None else None,
        "height_verdict": height_verdict,
        "shape_aspect_ratio_now": round(aspect_last, 2) if aspect_last is not None else None,
        "shape_aspect_delta": round(aspect_delta, 2) if aspect_delta is not None else None,
        "shape_verdict": shape_verdict,
    }


def _change_probability(effective_distance_km, blob_area_km2, confidence):
    """Эвристическая (НЕ физическая модель осадков) оценка вероятности, что
    значимое облачное поле принесёт изменение погоды в точку наблюдения."""
    proximity = max(0.0, 1 - effective_distance_km / (AFFECT_THRESHOLD_KM * 4))
    size = min(1.0, blob_area_km2 / SIGNIFICANT_AREA_REF_KM2)
    score = 0.5 * proximity + 0.3 * size + 0.2 * confidence
    return int(round(max(5, min(95, 5 + 90 * score))))


def _buffer_status(n_frames):
    eta_min = max(0, (MAX_FRAMES - n_frames) * STEP_MINUTES)
    span_now = max(0, (n_frames - 1) * STEP_MINUTES)
    span_target = (MAX_FRAMES - 1) * STEP_MINUTES
    if n_frames >= MAX_FRAMES:
        note = f"буфер заполнен ({n_frames}/{MAX_FRAMES}), тренды считаются по полному окну ~{span_target} мин"
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

    # Авторитетное "самое свежее доступное время" слоя — из GetCapabilities
    # (см. подробное обоснование в eumetsat_ir_motion.py), а не floor(now).
    server_latest_iso, _ = fc.get_layer_latest_time(LAYER_CLM)
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
                clm_arr = fc.fetch_tile(LAYER_CLM, t_iso)
                cth_arr = fc.fetch_tile(LAYER_CTH, t_iso)
            except Exception as e:
                # Одиночный пропуск на конкретном историческом слоте — не
                # повод обрывать весь прогон (см. подробности в
                # eumetsat_ir_motion.py): пропускаем кадр, собираем остальные.
                failed.append({"time": t_iso, "error": str(e)})
                print(f"  [SKIP] eumetsat_cloud_forecast.py: bootstrap кадр {t_iso} недоступен, пропуск: {e}")
                continue
            is_cloud, valid = _classify_cloud_mask(clm_arr)
            cth_idx = _cth_ordinal_index(cth_arr)
            new_times.append(t_iso or _fmt_time(now))
            new_packed.append(_pack_frame(is_cloud, valid, cth_idx))

        if len(new_packed) < MIN_FRAMES_FOR_INCREMENTAL:
            fc.write_debug(DEBUG_FILE, {"status": "error", "stage": "bootstrap", "failed": failed,
                                         "note": f"годных кадров {len(new_packed)}/{MAX_FRAMES} — недостаточно для анализа"})
            print(f"  [WARN] eumetsat_cloud_forecast.py: bootstrap провалился, годных кадров {len(new_packed)}/{MAX_FRAMES}")
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
                                             "note": f"сервер ещё не объявил кадр новее {times[-1]} (default={server_latest_iso})"})
                print(f"  [SKIP] eumetsat_cloud_forecast.py: новых кадров пока нет (server default={server_latest_iso})")
                return
            next_t_iso = server_latest_iso
        else:
            next_t = fc.datetime.fromtimestamp((last_t_min + STEP_MINUTES) * 60, tz=fc.timezone.utc)
            next_t_iso = _fmt_time(next_t)

        try:
            clm_arr = fc.fetch_tile(LAYER_CLM, next_t_iso)
            cth_arr = fc.fetch_tile(LAYER_CTH, next_t_iso)
        except Exception as e:
            debug["awaited_time"] = next_t_iso
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": f"следующий кадр ({next_t_iso}) ещё не опубликован"})
            print(f"  [SKIP] eumetsat_cloud_forecast.py: следующий кадр ({next_t_iso}) ещё не опубликован: {e}")
            return

        is_cloud_new, valid_new = _classify_cloud_mask(clm_arr)
        cth_idx_new = _cth_ordinal_index(cth_arr)
        last_is_cloud, _, _ = _unpack_frame(packed_frames[-1])
        if fc.is_duplicate_pair(last_is_cloud.astype(float), is_cloud_new.astype(float)):
            debug["skipped_duplicate"] = True
            fc.write_debug(DEBUG_FILE, {"status": "skipped", **debug,
                                         "note": "новых данных ещё нет (дубль последнего кадра — задержка публикации)"})
            print("  [SKIP] eumetsat_cloud_forecast.py: новых данных ещё нет (дубль)")
            return

        new_packed = _pack_frame(is_cloud_new, valid_new, cth_idx_new)
        times = (times + [next_t_iso])[-MAX_FRAMES:]
        packed_frames = (packed_frames + [new_packed])[-MAX_FRAMES:]

    fc.save_frame_buffer(BUFFER_FILE, times, packed_frames, MAX_FRAMES)
    debug["buffer_size"] = len(packed_frames)
    debug["buffer_times"] = list(times)

    unpacked = [_unpack_frame(p) for p in packed_frames]
    is_cloud_frames = [u[0] for u in unpacked]
    valid_frames = [u[1] for u in unpacked]
    cth_index_frames = [u[2] for u in unpacked]

    is_cloud_now = is_cloud_frames[-1]
    valid_now = valid_frames[-1]

    center_idx = int((TILE_SIZE - 1) / 2)
    currently_cloudy = bool(is_cloud_now[center_idx, center_idx])
    want_cloud_target = not currently_cloudy
    target_type = "cloud_mass" if want_cloud_target else "clearing"

    nearest = _nearest_of_type(is_cloud_now, valid_now, want_cloud_target)
    p_now = nearest[:2] if nearest is not None else None
    blob_area_km2 = nearest[2] if nearest is not None else None
    vx, vy, n_pairs = _estimate_motion(is_cloud_frames, times)

    local_mask = _local_area_mask()
    trend = _density_height_shape_trend(is_cloud_frames, cth_index_frames, valid_frames, local_mask)
    buffer_status = _buffer_status(len(packed_frames))

    if p_now is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": "cloud" if currently_cloudy else "clear",
            "target_type": target_type,
            "verdict": "однородно в радиусе ~{}км, {} не найдено".format(
                round(HALF_WINDOW_DEG * KM_PER_DEG_LON),
                "просветов" if want_cloud_target else "облаков",
            ),
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = _bearing_compass(*p_now)

        if vx is None:
            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "blob_area_km2": round(blob_area_km2, 0),
                "verdict": "скорость посчитать не удалось (поле слишком однородно во всех кадрах)",
            }
            if target_type == "cloud_mass":
                out["probability_percent"] = _change_probability(dist_now, blob_area_km2, confidence=0.25)
                out["probability_note"] = (
                    "эвристика (близость + размер поля), скорость не посчиталась — доверие снижено"
                )
        else:
            speed_kmh = math.hypot(vx, vy)
            dot_pv = p_now[0] * vx + p_now[1] * vy
            dot_vv = vx * vx + vy * vy
            t_cpa = max(0.0, -dot_pv / dot_vv) if dot_vv > 1e-6 else 0.0
            cpa_x = p_now[0] + vx * t_cpa
            cpa_y = p_now[1] + vy * t_cpa
            cpa_km = math.hypot(cpa_x, cpa_y)
            eta_min = round(t_cpa * 60, 0)

            if speed_kmh < STATIONARY_SPEED_KMH:
                verdict = "почти стоит на месте"
            elif cpa_km <= AFFECT_THRESHOLD_KM:
                verdict = "приближается" if eta_min > 5 else "уже у города"
            elif t_cpa <= 1e-6:
                verdict = "удаляется"
            else:
                verdict = "пройдёт мимо, город, скорее всего, не заденет"

            bearing_v = (math.degrees(math.atan2(vx, vy)) + 360) % 360

            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": "cloud" if currently_cloudy else "clear",
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "direction_compass": _compass(bearing_v),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "blob_area_km2": round(blob_area_km2, 0),
                "verdict": verdict,
                "frame_pairs_used": n_pairs,
            }
            if target_type == "cloud_mass":
                confidence = min(1.0, n_pairs / max(1, len(packed_frames) - 1))
                out["probability_percent"] = _change_probability(cpa_km, blob_area_km2, confidence)
                out["probability_note"] = (
                    "эвристика (близость точки максимального сближения + размер поля + "
                    "уверенность в оценке скорости), не физическая модель осадков"
                )

    out["trend"] = trend
    out["buffer_status"] = buffer_status
    out["method_note"] = (
        f"Персистентный буфер до {MAX_FRAMES} кадров Cloud Mask + CTH (шаг {STEP_MINUTES} мин, "
        "до 2 часов истории), хранится между прогонами (FIFO) — обычный прогон докачивает только "
        "1 новый кадр вместо всех заново. Скорость усреднена по всем парам кадров буфера с реальным "
        "dt (phase correlation всего поля). Край облака/просвета ищется только среди связных "
        f"областей >= {MIN_SIGNIFICANT_BLOB_PX}px (~{round(MIN_SIGNIFICANT_BLOB_PX*KM_PER_PX_X*KM_PER_PX_Y)}км²) "
        "с учётом прозрачных no-data пикселей. Тренды плотности/высоты/формы — сравнение первого и "
        f"последнего кадра БУФЕРА в радиусе {round(LOCAL_RADIUS_KM)}км (окно растёт по мере наполнения "
        "буфера, см. buffer_status). Высота — ординальный индекс по цвету (не метры, официальной "
        "таблицы нет). Вероятность (только когда сейчас ясно/переменная облачность и есть значимое "
        "приближающееся поле) — эвристическая оценка по близости/размеру/уверенности в скорости, "
        "не физическая модель осадков. Линейная экстраполяция, годится на ~1 час."
    )

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        import json
        json.dump(out, f, ensure_ascii=False, indent=2)

    fc.write_debug(DEBUG_FILE, {"status": "ok", **debug, "result": out})
    print(f"  [OK] eumetsat_cloud_forecast.py: {out.get('verdict')}, buffer={len(packed_frames)}/{MAX_FRAMES}")


if __name__ == "__main__":
    main()
