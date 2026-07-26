"""
field_motion_common.py — общая геометрия/детекция края/движения для полей
EUMETSAT (Cloud Mask, осадки h60b, молнии li_afa). Вынесено из
eumetsat_cloud_forecast.py, чтобы не дублировать один и тот же алгоритм
в трёх местах (облачность/осадки/молния).

ВАЖНО про "presence"-поля (осадки, молния) в отличие от Cloud Mask:
для msg_fes:h60b и mtg_fd:li_afa прозрачный пиксель (alpha=0) в стиле
EUMETView ОЗНАЧАЕТ "значение 0/нет сигнала", а не "нет данных" — это не
то же самое, что no-data в Cloud Mask (там нужно было явно отличать
"нет данных" от "ясно"). Поэтому здесь valid=True почти everywhere, а
presence = alpha>0 и есть сама классификация.
"""

import io
import math
import os
import json
import time as _time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
CENTER_LAT = 46.4406
CENTER_LON = 30.7703

HALF_WINDOW_DEG = 2.5
TILE_SIZE = 400
KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(CENTER_LAT))
KM_PER_PX_X = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LON) / TILE_SIZE
KM_PER_PX_Y = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LAT) / TILE_SIZE

AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02
MIN_SIGNIFICANT_BLOB_PX = 40
SIGNIFICANT_AREA_REF_KM2 = 1200.0

LOCAL_RADIUS_KM = 50.0

TIMEOUT = 25
COMPASS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def write_debug(path, payload):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fetch_tile(layer_name, time_iso=None, retries=2, delay=4, style="", crs="CRS:84"):
    """crs="CRS:84" (по умолчанию, как раньше) — порядок осей lon,lat.
    crs="EPSG:4326" — используется для mtg_fd:ir105_hrfi (подтверждённый
    рабочий вариант, см. eumetsat_ir_motion.py); ВАЖНО: по спеке WMS 1.3.0
    у EPSG:4326 порядок осей в bbox lat,lon (обратный CRS:84), иначе запрос
    уйдёт с перепутанными широтой/долготой."""
    min_lon = CENTER_LON - HALF_WINDOW_DEG
    max_lon = CENTER_LON + HALF_WINDOW_DEG
    min_lat = CENTER_LAT - HALF_WINDOW_DEG
    max_lat = CENTER_LAT + HALF_WINDOW_DEG
    if crs == "EPSG:4326":
        bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"  # EPSG:4326 = lat,lon
    else:
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"  # CRS:84 = lon,lat

    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer_name,
        "styles": style,
        "crs": crs,
        "bbox": bbox,
        "width": TILE_SIZE,
        "height": TILE_SIZE,
        "format": "image/png",
        "transparent": "true",
    }
    if time_iso:
        params["time"] = time_iso

    attempt_errors = []
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(WMS_BASE, params=params, timeout=TIMEOUT)
            ctype = r.headers.get("content-type", "")
            if r.status_code != 200 or "image" not in ctype:
                # Не-PNG ответ (WMS ServiceException XML, 404, и т.п.) — без этого
                # и "сцена ещё не опубликована", и "неверный CRS/bbox" выглядят
                # одинаково как "cannot identify image file", их не отличить.
                snippet = r.content[:300].decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {r.status_code}, content-type={ctype!r}, len={len(r.content)}: {snippet}")
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return np.array(img)
        except Exception as e:
            attempt_errors.append(f"попытка {attempt}: {e}")
            if attempt < retries:
                _time.sleep(delay)
    # Все попытки провалились — прокидываем ПЕРВУЮ ошибку с полным контекстом
    # (обычно самая информативная), а не только последнюю (retry на 404 обычно
    # даёт тот же 404, но если первая попытка упала иначе — не терять её).
    raise RuntimeError("; ".join(attempt_errors))


def classify_presence_by_alpha(arr):
    """presence = непрозрачный пиксель (значение > 0 по легенде продукта).
    valid = True почти везде — для этих продуктов alpha сам кодирует
    "0/нет сигнала", это не индикатор отсутствия данных."""
    presence = arr[:, :, 3] > 0
    valid = np.ones_like(presence, dtype=bool)
    return presence, valid


def pixel_to_km_offset(row, col):
    frac_x = col / (TILE_SIZE - 1)
    frac_y = row / (TILE_SIZE - 1)
    lon = CENTER_LON - HALF_WINDOW_DEG + frac_x * (2 * HALF_WINDOW_DEG)
    lat = CENTER_LAT + HALF_WINDOW_DEG - frac_y * (2 * HALF_WINDOW_DEG)
    dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
    dy_km = (lat - CENTER_LAT) * KM_PER_DEG_LAT
    return dx_km, dy_km


def local_area_mask():
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def bearing_compass(dx_km, dy_km):
    bearing = (math.degrees(math.atan2(dx_km, dy_km)) + 360) % 360
    idx = int(((bearing + 22.5) % 360) // 45)
    return bearing, COMPASS[idx]


def compass(bearing_deg):
    idx = int(((bearing_deg + 22.5) % 360) // 45)
    return COMPASS[idx]


def nearest_of_type(mask, valid, want_true, min_blob_px=MIN_SIGNIFICANT_BLOB_PX):
    """Ближайшая к центру точка связной области >= min_blob_px, где
    mask==want_true (и valid==True). Возвращает (dx_km, dy_km, area_km2)
    или None, если значимых областей нет."""
    raw_target = mask if want_true else (~mask & valid)
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
    dx_km, dy_km = pixel_to_km_offset(row, col)
    return dx_km, dy_km, blob_area_km2


def _parabolic_subpixel(c_minus, c_zero, c_plus):
    """Субпиксельная поправка к целочисленному пику по трём соседним точкам
    корреляции (параболическая интерполяция) — стандартный приём. Без неё
    любой сдвиг меньше 1 px (например, при слабом ветре и малом шаге между
    кадрами) округляется ровно до 0, и метод не отличает "реально стоит на
    месте" от "движется медленнее одного пикселя за интервал"."""
    denom = c_minus - 2 * c_zero + c_plus
    if abs(denom) < 1e-9:
        return 0.0
    offset = 0.5 * (c_minus - c_plus) / denom
    return float(np.clip(offset, -0.5, 0.5))


def phase_shift_px(mask_prev, mask_curr):
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


def is_uniform(mask):
    frac = mask.mean()
    return min(frac, 1 - frac) < MIN_FRACTION_FOR_CORR


def estimate_motion(masks, dt_minutes):
    vx_list, vy_list = [], []
    dt_h = dt_minutes / 60.0
    for i in range(len(masks) - 1):
        m_prev, m_curr = masks[i], masks[i + 1]
        if is_uniform(m_prev) or is_uniform(m_curr):
            continue
        dy_px, dx_px = phase_shift_px(m_prev, m_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def to_grayscale_luminance(arr):
    """RGBA/RGB (H,W,3|4) uint8 -> (H,W) float яркость (стандартные веса luma)."""
    r = arr[:, :, 0].astype(np.float64)
    g = arr[:, :, 1].astype(np.float64)
    b = arr[:, :, 2].astype(np.float64)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _despeckle(gray, size=5):
    """Убирает точечные источники (городские огни ночью) МЕДИАННЫМ фильтром
    перед phase correlation.

    ВАЖНО почему именно медианный фильтр, а не gaussian blur/клиппинг:
    phase correlation в phase_shift_px() — это нормированная кросс-корреляция
    ПО ФАЗЕ (r = fb*conj(fa); r /= abs(r)), она инвариантна к амплитуде по
    построению. Значит blur/клиппинг яркости точек НЕ меняют их вклад в
    результат корреляции — проверено на синтетике: даже клиппинг по 95-му
    перцентилю не убирал ложный "0 км/ч", возникающий из-за неподвижных
    городских огней на ночном GeoColour-снимке (огни неподвижны -> их вклад
    в корреляцию всегда "сдвиг = 0", и он забивает реальный сдвиг облачной
    текстуры). Медианный фильтр меняет саму пространственную СТРУКТУРУ
    (буквально стирает единичный выброс, заменяя соседями), а не только
    его амплитуду — это и требуется для инвариантного к амплитуде метода.
    """
    return ndimage.median_filter(gray, size=size)


def is_low_contrast(gray, min_std=6.0):
    """Кадр слишком однороден для phase correlation (ночь/сумерки/туман —
    в отличие от бинарной is_uniform() для масок, здесь непрерывная яркость,
    поэтому критерий — стандартное отклонение, а не доля пикселей одного типа."""
    return float(np.std(gray)) < min_std


def is_duplicate_pair(gray_a, gray_b, threshold=0.98):
    """True, если gray_b — это фактически тот же снимок, что и gray_a (сервер
    отдал уже виденную сцену вместо новой — типичная причина: "самый свежий
    доступный" (time=None) запрошен раньше, чем реальный новый скан успел
    опубликоваться, и совпал с предыдущим явным таймстемпом). Такую пару
    нужно ИСКЛЮЧИТЬ из усреднения, а не считать "честным нулевым сдвигом" —
    иначе гарантированный (0,0) от дубля просто размывает среднее к нулю
    вместе с реальными парами (найдено на живых данных: 1 из 3 пар была
    100%-дублем и утащила итоговую скорость к 0 км/ч)."""
    diff = np.abs(gray_a.astype(np.float64) - gray_b.astype(np.float64))
    return float((diff < 0.5).mean()) > threshold


def _parse_iso_minutes(t_iso):
    """ISO-таймстемп буфера ("YYYY-MM-DDTHH:MM:00.000Z") -> минуты с начала эпохи
    (float), для вычисления РЕАЛЬНОГО dt между кадрами."""
    dt = datetime.strptime(str(t_iso), "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=timezone.utc)
    return dt.timestamp() / 60.0


def estimate_motion_continuous(gray_frames, times_iso, min_std=6.0, despeckle_size=5):
    """То же, что estimate_motion(), но для непрерывных (не бинарных) полей
    яркости — используется для оценки движения по текстуре true-color
    снимка (GeoColour RGB), а не по бинарной Cloud Mask. Даёт независимую
    оценку скорости/направления, устойчивую даже при сплошной облачности
    (там, где бинарная маска однородна и phase correlation на ней не
    работает вообще — у текстуры яркости всегда есть локальный рельеф).

    times_iso: список ISO-таймстемпов кадров (та же длина, что gray_frames).
    dt между парой кадров считается из РЕАЛЬНОЙ разницы их таймстемпов, а
    не как фиксированный шаг — буфер может содержать пропуски (одиночный
    недоступный слот в bootstrap пропускается, а не обрывает весь прогон,
    см. eumetsat_ir_motion.py), и тогда реальный интервал между соседними
    кадрами может быть кратен шагу (например, 20 мин вместо 10) — при
    фиксированном шаге скорость для такой пары была бы завышена вдвое.

    Каждый кадр сначала проходит _despeckle() (см. докстринг там) — иначе
    ночью неподвижные городские огни ложно "перетягивают" корреляцию к
    нулевому сдвигу, и метод выдаёт неверный "почти не движется" вместо
    честного "недостаточно контраста", даже когда реальная облачная
    текстура под огнями продолжает двигаться.

    Пары кадров-дублей (см. is_duplicate_pair) тоже пропускаются — иначе
    гарантированный нулевой сдвиг от дубля искажает среднее."""
    vx_list, vy_list = [], []
    times_min = [_parse_iso_minutes(t) for t in times_iso]
    processed = [_despeckle(g, despeckle_size) for g in gray_frames]
    for i in range(len(processed) - 1):
        dt_h = (times_min[i + 1] - times_min[i]) / 60.0
        if dt_h <= 0:
            continue
        g_prev, g_curr = processed[i], processed[i + 1]
        if is_low_contrast(g_prev, min_std) or is_low_contrast(g_curr, min_std):
            continue
        if is_duplicate_pair(g_prev, g_curr):
            continue
        dy_px, dx_px = phase_shift_px(g_prev, g_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


def build_time_steps(step_minutes, n_frames, latest_as_none=True):
    """Строит список ISO-таймстемпов для запроса кадров: N_FRAMES-1 кадров
    в прошлом (шаг step_minutes) + последний кадр либо None (latest_as_none=
    True, по умолчанию — сервер сам отдаёт самый свежий, поведение как
    раньше, используется precip/lightning), либо тоже явный выровненный
    таймстемп (latest_as_none=False — используется ir_motion: явный TIME
    везде надёжнее "latest" при задержке публикации сцены, см. is_duplicate_pair
    и историю бага с почти-дублем кадра). "Сейчас" перед вычитанием шагов
    округляется ВНИЗ до границы step_minutes — иначе получившаяся точная
    отметка времени может не совпасть ни с одной реально существующей сценой
    конкретно у этого слоя (WMS Dimension "time" без nearestValue у части
    mtg_fd-слоёв — строгое совпадение, а не "ближайшее"), и запрос кадра
    падает с ошибкой вида "cannot identify image file"/404 вместо честного
    ответа (для 404 на самом свежем — это нормально, значит сцена ещё не
    опубликована, вызывающий код должен трактовать это как "подождать
    следующего прогона", а не как ошибку). Это было найдено как причина
    3-часовой протухшей eumetsat_geocolour_motion.json: один упавший кадр
    прерывал весь прогон, а старый файл оставался лежать без пометки о
    своей неактуальности."""
    now = datetime.now(timezone.utc)
    aligned = now.replace(second=0, microsecond=0)
    aligned -= timedelta(minutes=aligned.minute % step_minutes)
    times_iso = []
    for i in range(n_frames - 1, -1, -1):
        if i == 0 and latest_as_none:
            times_iso.append(None)
        else:
            t = aligned - timedelta(minutes=step_minutes * i)
            times_iso.append(t.strftime("%Y-%m-%dT%H:%M:00.000Z"))
    return times_iso


def load_frame_buffer(path):
    """Загружает ранее сохранённый буфер кадров (ISO-таймстемпы + grayscale
    массивы). Возвращает ([], []) если файла нет или он повреждён —
    вызывающий код должен в этом случае бутстрапить буфер заново."""
    if not os.path.exists(path):
        return [], []
    try:
        data = np.load(path)
        times = list(data["times"])
        frames = [data["frames"][i] for i in range(data["frames"].shape[0])]
        return times, frames
    except Exception:
        return [], []


def save_frame_buffer(path, times, frames, max_frames=6):
    """Сохраняет буфер (обрезая до последних max_frames — FIFO: новый кадр
    приходит, самый старый вываливается). Один файл, перезаписывается
    каждый прогон — не бесконечно растущая история, а скользящее окно."""
    times = times[-max_frames:]
    frames = frames[-max_frames:]
    arr = np.stack(frames).astype(np.float32)
    times_arr = np.array(times, dtype="<U32")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, times=times_arr, frames=arr)


def circular_angle_diff(bearing_from_deg, bearing_to_deg):
    """Кратчайшая разница углов в градусах (учитывает переход через 360°),
    со знаком: положительное — поворот по часовой стрелке."""
    diff = (bearing_to_deg - bearing_from_deg + 180) % 360 - 180
    return diff


def change_probability(effective_distance_km, blob_area_km2, confidence):
    """Эвристическая (не физическая) оценка вероятности, что значимое поле
    достигнет точки наблюдения. См. подробности в eumetsat_cloud_forecast.py."""
    proximity = max(0.0, 1 - effective_distance_km / (AFFECT_THRESHOLD_KM * 4))
    size = min(1.0, blob_area_km2 / SIGNIFICANT_AREA_REF_KM2)
    score = 0.5 * proximity + 0.3 * size + 0.2 * confidence
    return int(round(max(5, min(95, 5 + 90 * score))))
