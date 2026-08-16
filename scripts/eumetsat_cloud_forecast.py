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
    вероятности, что оно принесёт изменение погоды. С 2026-08-08 база
    берётся ИЗ КАТЕГОРИИ verdict (approaching/receding/passing по CPA), а
    не только из сырой близости — раньше у "удаляется"/"пройдёт мимо" могла
    получиться существенная % оценка вопреки тексту рядом (см.
    docs/topics/eumetsat.md). Площадь поля и уверенность в оценке скорости
    только модулируют базу, не переопределяют её.
  - Выбор "ближайшего облака/просвета" для этого блока СИНХРОНИЗИРОВАН с
    реестром повторяющихся ложных срабатываний CLM
    (data/eumetsat_target_false_positive_log.json, fc.pick_nearest_candidate) —
    известные шумовые объекты сюда не попадают, как и в "Итог" на странице.

Пишет data/eumetsat_cloud_forecast.json (результат) и
data/eumetsat_cloud_buffer.npz (персистентный буфер кадров).
"""

import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
DEBUG_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast_debug.json")
BUFFER_FILE = os.path.join(BASE_DIR, "data", "eumetsat_cloud_buffer.npz")
CLM_SNAPSHOT_FILE = os.path.join(BASE_DIR, "data", "eumetsat_clm_snapshot.png")

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

LOCAL_RADIUS_KM = fc.LOCAL_RADIUS_KM   # область вокруг города для плотности/высоты/формы (тренд)
STATE_RADIUS_KM = fc.STATE_RADIUS_KM   # область для current_state ("сейчас над станцией") —
                                  # меньше LOCAL_RADIUS_KM: живой кейс 2026-08-01 22:00Z
                                  # показал 0% облачности в 0-10км, но 25% в круге 50км
                                  # (стоящий на месте блоб 15-50км утаскивал за порог "variable",
                                  # хотя прямо над станцией было чисто)
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

# Порог площади для классификации кандидата: "local" (компактная масса,
# для неё имеет смысл object-centric ROI-подтверждение через 5 модулей) vs
# "system" (крупный фронт/облачный массив синоптического масштаба — сам
# факт существования очевиден без ROI-сверки, интересна скорее динамика/
# приближение, не подтверждение "существует ли"). НЕ путать с
# SIGNIFICANT_AREA_REF_KM2 выше — та константа для нормировки вероятности
# влияния, эта — чисто для разделения семантики между локальной массой и
# синоптической системой (см. docs/topics/eumetsat.md, вариант "б" от
# 2026-08-05). Подобран по разрыву в реальных данных: локальные массы в
# наблюдаемых прогонах — 60-121км², следующий кластер — уже 215-8632км².
LARGE_SYSTEM_AREA_KM2 = 300.0

# Порог вытянутости (PCA aspect ratio главных осей блоба), выше которого
# крупная система (class=="system") дополнительно помечается как
# потенциально линейная структура ("frontlike") — черновая эвристика для
# идеи "отслеживание фронтов" (см. docs/topics/eumetsat.md, раздел "Идея
# на будущее"). НЕ физическое обнаружение фронта (нет анализа градиента
# давления/температуры, только форма облачного поля по Cloud Mask) —
# просто сигнал "эта система вытянута в линию, а не компактная клякса".
# Подобран на глаз (типичный aspect ratio компактного кучевого поля ~1-1.8,
# вытянутая полоса вдоль фронта — заметно больше), калибровки по реальным
# синоптическим картам ещё не делали.
FRONTLIKE_ASPECT_THRESHOLD = 2.2

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
    # ЕДИНСТВЕННАЯ реализация — в field_motion_common.py (fc.pixel_to_km_offset).
    # Раньше здесь была своя копия со старой edge-to-edge конвенцией сетки —
    # когда её пофиксили в field_motion_common.py (2026-08-02, см. docs/topics/
    # eumetsat.md), фикс сюда не попал именно из-за дублирования. Теперь один
    # источник правды на все *_motion.py и cloud_forecast.py разом.
    return fc.pixel_to_km_offset(row, col)


def _radius_mask(radius_km):
    """Булев (H,W) — True внутри radius_km от центра тайла (Одесса)."""
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= radius_km


def _local_area_mask():
    """Булев (H,W) — True внутри LOCAL_RADIUS_KM (для тренда density/height/shape)."""
    return _radius_mask(LOCAL_RADIUS_KM)


def _station_area_mask():
    """Булев (H,W) — True внутри STATE_RADIUS_KM (для current_state, "сейчас над станцией")."""
    return _radius_mask(STATE_RADIUS_KM)


def _blob_elongation(ys, xs, center_row, center_col):
    """PCA по пикселям блоба (переведённым в км, с учётом разных
    KM_PER_PX_X/Y) — возвращает (aspect_ratio, axis_bearing_deg) главной оси
    вытянутости, или (None, None) при недостатке пикселей для устойчивой
    оценки. aspect_ratio = sqrt(большее собств.значение ковариации / меньшее)
    — во сколько раз объект длиннее, чем шире, вдоль главных осей; устойчивее
    к диагональной ориентации, чем bounding-box aspect ratio (тот уже
    отдельно считается для тренда "вытягивается" в
    _density_height_shape_trend, но только для крупнейшего пятна в
    LOCAL_RADIUS_KM, не по каждому кандидату). axis_bearing_deg — направление
    ГЛАВНОЙ ОСИ как ЛИНИИ (не вектора, поэтому 0..180, не 0..360), та же
    конвенция atan2(dx,dy), что и bearing до объекта."""
    if len(ys) < 5:
        return None, None
    dx_km = (xs - center_col) * KM_PER_PX_X
    dy_km = -(ys - center_row) * KM_PER_PX_Y
    cov = np.cov(np.stack([dx_km, dy_km], axis=0))
    if cov.shape != (2, 2):
        return None, None
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    minor = max(float(eigvals[1]), 1e-6)
    major = max(float(eigvals[0]), 1e-6)
    aspect = math.sqrt(major / minor)
    major_vec = eigvecs[:, 0]
    bearing = (math.degrees(math.atan2(major_vec[0], major_vec[1])) + 360) % 180
    return aspect, bearing


def _axis_compass_label(bearing_deg):
    """Компасная метка ОСИ (не направления, у линии два конца), например
    'СЗ-ЮВ'. bearing_deg ожидается в 0..180 (см. _blob_elongation)."""
    if bearing_deg is None:
        return None
    end_a = _compass(bearing_deg % 360)
    end_b = _compass((bearing_deg + 180) % 360)
    return f"{end_a}-{end_b}"


WINDOW_SPAN_TOLERANCE_PX = 2  # допуск в пикселях при проверке "bbox упирается в край окна"


def _window_edge_km():
    """Km-координаты краёв окна анализа (motion_window) по X и Y — для
    проверки window_spanning (см. _significant_blobs). Симметрично вокруг
    центра тайла, тот же расчёт, что _pixel_to_km_offset даёт для угловых
    пикселей 0 и TILE_SIZE-1."""
    center = (TILE_SIZE - 1) / 2
    return center * KM_PER_PX_X, center * KM_PER_PX_Y


def _significant_blobs(is_cloud_mask, valid_mask, want_cloud, min_blob_px=MIN_SIGNIFICANT_BLOB_PX):
    """Как _nearest_of_type, но возвращает ВСЕ значимые связные области нужного
    типа, а не только ближайшую к центру — основа для object-centric пайплайна
    (см. docs/topics/eumetsat.md, план ROI-передачи между модулями от 2026-08-04).
    Каждый элемент: centroid_dx_km/dy_km, area_km2, class ("local"/"system" —
    см. LARGE_SYSTEM_AREA_KM2, вариант "б" от 2026-08-05), bbox_km (min/max
    dx/dy — прямоугольник в км от центра тайла, для передачи как ROI другим
    скриптам), elongation_aspect_ratio/elongation_axis_compass/frontlike —
    черновая эвристика вытянутости для идеи "отслеживание фронтов" (см.
    FRONTLIKE_ASPECT_THRESHOLD выше, докстринг docs/topics/eumetsat.md).
    Список отсортирован по расстоянию centroid до центра (ближайший
    первым) — target_id = позиция в ЭТОМ общем списке (local+system вперемешку),
    а не отдельная нумерация внутри класса; кто из них "primary" для
    ROI-подтверждения решает fc.load_primary_target() (берёт ближайший именно
    class=="local", пропуская system, если тот оказался ближе).
    """
    raw_target = is_cloud_mask if want_cloud else (~is_cloud_mask & valid_mask)
    center_row = center_col = (TILE_SIZE - 1) / 2

    def _blobs_from_labeling(labeled, n, keep_area_pred, class_label):
        """Общая часть извлечения блобов из уже посчитанной разметки
        ndimage.label — вынесено, чтобы local- и system-проходы (см. ниже)
        считали координаты/bbox/elongation ОДИНАКОВО, различаясь только
        связностью разметки и порогом площади."""
        if n == 0:
            return []
        sizes = ndimage.sum(raw_target, labeled, range(1, n + 1))
        result = []
        for lbl in range(1, n + 1):
            blob_px = float(sizes[lbl - 1])
            if blob_px < min_blob_px:
                continue
            blob_area_km2 = blob_px * KM_PER_PX_X * KM_PER_PX_Y
            if not keep_area_pred(blob_area_km2):
                continue
            ys, xs = np.where(labeled == lbl)
            # centroid — ближайший к центру пиксель блоба (не геометрический
            # центр масс), чтобы distance/bearing были согласованы с тем, как
            # их всегда считал _nearest_of_type (ближайшая точка блоба, не center of mass)
            dist_px = np.sqrt((ys - center_row) ** 2 + (xs - center_col) ** 2)
            best_i = np.argmin(dist_px)
            row, col = int(ys[best_i]), int(xs[best_i])
            cdx_km, cdy_km = _pixel_to_km_offset(row, col)
            # bbox в км — по всем пикселям блоба, для ROI-запроса в других слоях
            corners_dx, corners_dy = [], []
            for r, c in ((ys.min(), xs.min()), (ys.max(), xs.max())):
                dx, dy = _pixel_to_km_offset(int(r), int(c))
                corners_dx.append(dx)
                corners_dy.append(dy)
            aspect_ratio, axis_bearing = _blob_elongation(ys, xs, center_row, center_col)
            # window_spanning — дёшевый диагностический флаг (см. docs/topics/
            # eumetsat.md, находка 2026-08-09 "продолжение 4"): если bbox блоба
            # упирается в ОБА края окна хотя бы по одной оси (X или Y, с
            # допуском WINDOW_SPAN_TOLERANCE_PX), это подозрение, что 8-связный
            # проход склеил разрозненные пятна через диагональную ниточку шума
            # в один "спан" через весь тайл, а не реальная связная структура
            # такого размера. НЕ меняет сегментацию/список кандидатов — только
            # предупреждающая метка для потребителей (target_summary/фронтенд).
            edge_dx_km, edge_dy_km = _window_edge_km()
            tol_dx_km = WINDOW_SPAN_TOLERANCE_PX * KM_PER_PX_X
            tol_dy_km = WINDOW_SPAN_TOLERANCE_PX * KM_PER_PX_Y
            spans_x = (min(corners_dx) <= -edge_dx_km + tol_dx_km) and (max(corners_dx) >= edge_dx_km - tol_dx_km)
            spans_y = (min(corners_dy) <= -edge_dy_km + tol_dy_km) and (max(corners_dy) >= edge_dy_km - tol_dy_km)
            result.append({
                "centroid_dx_km": round(cdx_km, 2),
                "centroid_dy_km": round(cdy_km, 2),
                "area_km2": round(blob_area_km2, 1),
                "class": class_label,
                "bbox_km": {
                    "dx_min": round(min(corners_dx), 2),
                    "dx_max": round(max(corners_dx), 2),
                    "dy_min": round(min(corners_dy), 2),
                    "dy_max": round(max(corners_dy), 2),
                },
                "elongation_aspect_ratio": round(aspect_ratio, 2) if aspect_ratio is not None else None,
                "elongation_axis_deg": round(axis_bearing, 0) if axis_bearing is not None else None,
                "elongation_axis_compass": _axis_compass_label(axis_bearing),
                "frontlike": bool(
                    class_label == "system"
                    and aspect_ratio is not None
                    and aspect_ratio >= FRONTLIKE_ASPECT_THRESHOLD
                    and not (spans_x or spans_y)
                ),
                "window_spanning": bool(spans_x or spans_y),
            })
        return result

    # Проход 1 — ЛОКАЛЬНЫЕ цели: 4-связность (ndimage.label БЕЗ structure,
    # поведение идентично коду до 2026-08-09). НЕ ТРОГАТЬ — явный запрос
    # 2026-08-09 "механизм определения локальных облаков не должен пострадать".
    labeled4, n4 = ndimage.label(raw_target)
    local_blobs = _blobs_from_labeling(labeled4, n4, lambda a: a < LARGE_SYSTEM_AREA_KM2, "local")

    # Проход 2 — СИСТЕМЫ: 8-связность (с диагоналями, structure=3x3 из единиц).
    # Причина отдельного прохода: протяжённая диагональная фронтальная полоса
    # рвётся 4-связностью на множество несвязанных "систем" в местах, где
    # касается себя только по углу пикселя — живой прогон 2026-08-09 показал
    # 14 "систем" с ОДНОЙ И ТОЙ ЖЕ осью СВ-ЮЗ независимо от положения —
    # явные фрагменты одной структуры (см. docs/topics/eumetsat.md). Из
    # 8-связной разметки берутся только компоненты >= LARGE_SYSTEM_AREA_KM2 —
    # то, что мельче, уже точнее учтено локальным (4-связным) проходом выше;
    # пересечение по площади с local_blobs возможно (два мелких локальных
    # блоба могут диагонально слиться в один system-блоб) — это осознанно:
    # local_blobs при этом не меняются ни на пиксель, просто система сверху
    # показывает более крупную структуру, в которую они входят.
    #
    # Антишумовой фильтр (2026-08-14, шаг 2 плана "Отслеживание фронтов",
    # см. docs/topics/eumetsat.md): именно 8-связность склеивает РАЗНЫЕ
    # облачные пятна через одиночную диагональную "ниточку" шумовых
    # пикселей (пиксель P касается соседа A только по углу, соседа B тоже
    # только по углу — 4-связного соседа внутри маски у P нет). Такую
    # ниточку убираем binary_opening с КРЕСТООБРАЗНОЙ (4-связной, НЕ 8-связной!)
    # структурой: точка выживает эрозию только если у неё есть N/S/E/W-сосед
    # в маске — у диагональной ниточки такого соседа по определению нет,
    # она гарантированно стирается. Настоящие полосы (в т.ч. фронтальные,
    # обычно толще 1px = толще ~1-1.4км при текущем разрешении тайла)
    # сохраняют внутренние пиксели с 4-связными соседями и после dilation
    # восстанавливаются почти без потери площади. Применяется ТОЛЬКО к
    # системному проходу — локальный (4-связный) проход выше не трогаем ни
    # на пиксель (явный запрет 2026-08-09, локальные цели мельче и любая
    # эрозия для них разрушительна).
    system_input = ndimage.binary_opening(
        raw_target, structure=ndimage.generate_binary_structure(2, 1)
    )
    labeled8, n8 = ndimage.label(system_input, structure=np.ones((3, 3), dtype=int))
    system_blobs = _blobs_from_labeling(labeled8, n8, lambda a: a >= LARGE_SYSTEM_AREA_KM2, "system")

    blobs = local_blobs + system_blobs
    blobs.sort(key=lambda b: math.hypot(b["centroid_dx_km"], b["centroid_dy_km"]))
    for i, b in enumerate(blobs):
        b["target_id"] = i  # 0 = primary (ближайшая, как раньше выбирал _nearest_of_type)
    return blobs


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
    # МЕДИАНА, а не среднее: на разреженной/шумной маске отдельные пары дают
    # очень разные оценки (замечено живьём — от 0.15 до 111 км/ч на одном и
    # том же облаке за один цикл), и среднее может как случайно занулиться
    # от взаимной компенсации разнонаправленных выбросов, так и утянуться
    # одним выбросом в нереалистичную сторону. Медиана по каждой компоненте
    # устойчива к одиночным выбросам, в отличие от среднего.
    return float(np.median(vx_list)), float(np.median(vy_list)), len(vx_list)


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


def _change_probability(verdict, dist_now_km, cpa_km, eta_min, blob_area_km2, confidence):
    """Эвристическая (НЕ физическая модель осадков) оценка вероятности, что
    значимое облачное поле принесёт изменение погоды в точку наблюдения.

    ПЕРЕДЕЛАНО 2026-08-08 (см. docs/topics/eumetsat.md): раньше база
    считалась ТОЛЬКО из близости точки максимального сближения (cpa_km) и
    площади поля, БЕЗ оглядки на сам verdict — из-за этого у объекта с
    verdict='удаляется' или 'пройдёт мимо, город, скорее всего, не заденет'
    могла получиться существенная % оценка, хотя текст рядом прямо говорил
    обратное (реальная жалоба: "пройдёт мимо, идут в другую сторону, но
    вероятность изменений 50%"). Теперь БАЗА берётся из категории verdict
    (что уже честно отражает физику — approaching/receding/passing по CPA),
    и лишь модулируется площадью поля и уверенностью в оценке скорости —
    поэтому число теперь согласовано с текстом, а не противоречит ему."""
    size = min(1.0, blob_area_km2 / SIGNIFICANT_AREA_REF_KM2)
    if verdict == "уже у города":
        base = 0.90
    elif verdict == "приближается":
        # чем меньше ETA, тем увереннее, что зона дойдёт до порога
        eta_factor = 1.0 if eta_min is None else max(0.3, 1 - eta_min / 180.0)
        base = 0.40 + 0.35 * eta_factor
    elif verdict == "почти стоит на месте":
        base = max(0.10, 1 - dist_now_km / (AFFECT_THRESHOLD_KM * 3))
    elif verdict == "пройдёт мимо, город, скорее всего, не заденет":
        # запас расстояния между CPA и порогом — чем больше, тем ближе к нулю
        margin_km = max(0.0, (cpa_km or 0.0) - AFFECT_THRESHOLD_KM)
        base = max(0.05, 0.35 - margin_km / 200.0)
    elif verdict == "удаляется":
        base = 0.05
    else:
        # скорость не посчиталась — старый fallback, только по близости,
        # честно помечен сниженной уверенностью через confidence-множитель
        base = max(0.05, min(0.6, 1 - dist_now_km / (AFFECT_THRESHOLD_KM * 4)))
    score = 0.70 * base + 0.20 * size + 0.10 * confidence
    return int(round(max(3, min(97, 100 * score))))


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


def _save_clm_snapshot(is_cloud, valid):
    """Чистый снимок бинарной Cloud Mask (CLM) — ЧТО РЕАЛЬНО является
    входом детектора кандидатов/frontlike (см. _classify_cloud_mask() и
    _significant_blobs() выше), а не GeoColour/ИК (те лишь ПОДТВЕРЖДАЮЩИЕ
    каналы для area_fraction_now — CLM & (IR|GC), см. докстринг main()).
    Добавлено 2026-08-15 по прямому запросу пользователя после того, как
    ночной трек оказался не виден ни на GC (ночью — только огни городов,
    без облачного сигнала), ни на ИК (низкий контраст у тонкой/рассеянной
    облачности), хотя CLM его детектировал как frontlike — эта картинка
    показывает ПОЧЕМУ, без гадания по другим каналам.

    Кодировка: светло-серый/белый = облако (is_cloud), тёмно-синий =
    ясно (валидный пиксель, не облако), средне-серый = нет данных
    (valid=False). Тот же geometry-контракт, что у GC/ИК снимков (общий
    fc.draw_view_radius_circle(), TILE_SIZE одинаковый на всех трёх слоях
    WMS).

    БЕЗ оверлея треков (2026-08-16, было и убрано в тот же день). Пробовал
    рисовать линии треков как на GC — оказалось СТРУКТУРНО не может быть
    синхронно с таблицей/GC: cloud_forecast.py в пайплайне идёт ПЕРЕД
    frontal_track.py (тот использует candidates ИЗ ЭТОГО скрипта как
    вход — раньше физически не может), поэтому CLM всегда рисовал бы
    треки с ПРЕДЫДУЩЕГО цикла. Пойманный на живых данных случай (история
    коммитов data/eumetsat_frontal_track.json): цикл A — 3 трека, цикл B
    — пересчитал в 0 (трек на 1 кадр не прошёл frontlike-фильтр), цикл C
    — снова 3. CLM цикла B нарисовал бы треки цикла A (3, хотя таблица
    уже показывала 0), CLM цикла C нарисовал бы 0 треков цикла B (хотя
    таблица уже снова показывала 3) — выглядит как "то фронт есть, то
    нет", хотя это просто рассинхрон на 1 цикл, не баг детекции. Решили:
    честнее показывать только сырую маску без интерпретации сверху,
    сверять положение с треком визуально по форме облака."""
    try:
        rgb = np.zeros((TILE_SIZE, TILE_SIZE, 3), dtype=np.uint8)
        rgb[:, :] = (60, 60, 68)                  # нет данных
        rgb[valid & ~is_cloud] = (18, 22, 40)     # ясно
        rgb[valid & is_cloud] = (232, 232, 238)   # облако
        base = Image.fromarray(rgb, mode="RGB")
        base = fc.draw_view_radius_circle(base)
        base.save(CLM_SNAPSHOT_FILE)
    except Exception as e:
        print(f"  [WARN] eumetsat_cloud_forecast.py: не удалось сохранить CLM snapshot: {e}")


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
    _save_clm_snapshot(is_cloud_now, valid_now)
    local_mask = _local_area_mask()
    station_mask = _station_area_mask()

    # РАНЬШЕ брали ОДИН центральный пиксель (~1.4×1.4км) — та же проблема,
    # что уже находили и чинили в eumetsat_ir_motion.py: человек оценивает
    # облачность над собой в целом, а не 1 пиксель точно над головой, и
    # единичный пиксель может случайно попасть в разрыв между облаками даже
    # при заметной облачности рядом (замечено живьём: ближайшее облако в
    # 13км, а current_state всё равно "ясно"). Тогда взяли долю облачных
    # пикселей в LOCAL_RADIUS_KM=50 — но это радиус для РЕГИОНАЛЬНОГО
    # тренда, не для "сейчас над станцией": живой кейс 2026-08-01 22:00Z
    # показал 0% облачности в 0-10км от станции, но 25% в круге 50км, потому
    # что стоящий на месте блоб в 15-50км утаскивал долю за порог "variable"
    # (0.15), хотя прямо над станцией было чисто. current_state теперь
    # считается по STATE_RADIUS_KM=12 (что реально "над станцией" — по сути
    # площадь города, запрос 2026-08-10 "радиус берём такой чтобы нормально
    # работал по городу" уже удовлетворён этим historические выбором, менять
    # не стали), а LOCAL_RADIUS_KM=50 остаётся только для трендов
    # density/height/shape ниже (там радиус нужен большой — это прогноз по
    # региону, а не факт).
    #
    # 2026-08-10: раньше area_fraction_now считалась ТОЛЬКО по CLM (Cloud
    # Mask) — по прямой жалобе пользователя (скриншот таблицы локальных
    # очагов с десятками объектов, которые CLM видит, а ИК и GeoColour оба
    # в упор нет) заменено на подтверждение независимыми каналами. Раздельные
    # источники — те же сырые буферы, что уже используются в
    # ir_motion.py/geocolour_motion.py (см.
    # fc.load_ir_confirmed_mask()/load_geocolour_confirmed_mask()).
    #
    # 2026-08-11: ПЕРВАЯ версия требовала СТРОГОГО согласия ВСЕХ ТРЁХ
    # каналов (CLM & IR & GC) — на живом снимке (09:56, видны рассеянные
    # кучевые облака) это дало current_state="ясно" (пользователь: "не
    # сказал бы что над станцией ясно... их видно"). Диагностика на сырых
    # буферах подтвердила причину: GeoColour-классификатор
    # (_classify_cloud в eumetsat_geocolour_motion.py, тот же класс
    # проблемы, что уже находили у Phase RGB — неоткалиброванные HSV-
    # анкеры) дал РОВНО 0% в круге станции при явно облачном небе на
    # снимке — единственный "нет" от одного нездорового канала обнулял всё
    # трио. Заменено на CLM & (IR | GC) — облако засчитывается, если CLM
    # его видит И ХОТЯ БЫ ОДИН из двух независимых каналов подтверждает
    # (не обязательно оба сразу). Та же логика симметрии, что уже принята
    # в реестрах подавления шумовых объектов (там наоборот — объект
    # прячем, только если ОБА канала отвергли; здесь — облако засчитываем,
    # если хотя бы один подтвердил), устойчива к временной поломке одного
    # канала. GeoColour-калибровка остаётся отдельной открытой проблемой
    # (см. Horizon в docs/topics/eumetsat.md) — само по себе under-
    # detection GeoColour не устранено, просто current_state больше от
    # него единолично не зависит.
    ir_mask, ir_ok = fc.load_ir_confirmed_mask()
    gc_mask, gc_ok = fc.load_geocolour_confirmed_mask()
    if ir_ok and gc_ok:
        confirmed_cloud_now = is_cloud_now & (ir_mask | gc_mask)
        state_source = "clm_and_ir_or_gc_confirmed"
    elif ir_ok:
        confirmed_cloud_now = is_cloud_now & ir_mask
        state_source = "clm_ir_confirmed_gc_unavailable"
    elif gc_ok:
        confirmed_cloud_now = is_cloud_now & gc_mask
        state_source = "clm_gc_confirmed_ir_unavailable"
    else:
        confirmed_cloud_now = is_cloud_now
        state_source = "clm_only_fallback_ir_and_gc_unavailable"
    area_fraction_now = float(confirmed_cloud_now[station_mask].mean())
    debug["state_source"] = state_source
    debug["state_area_fraction"] = round(area_fraction_now, 3)

    # Расширенная градация (запрос 2026-08-10: "все существующие варианты
    # описания состояния неба") — стандартный русскоязычный метеослог
    # (Гидрометцентр/массовые погодные сервисы), 6 уровней вместо прежних
    # 3. ПЕРВЫЙ ПРОХОД порогов (обновлён 2026-08-11 вместе со сменой AND->OR
    # выше, см. комментарий там) — CLM & (IR|GC) физически даёт МЕНЬШИЕ доли,
    # чем раньше CLM-only (это всё ещё пересечение двух условий, не одного),
    # но БОЛЬШИЕ, чем строгий CLM&IR&GC — границы по-прежнему ниже прежних
    # 0.15/0.70 (не прямое масштабирование), но выше, чем были бы под
    # строгим AND трёх каналов — предстоит откалибровать точнее по мере
    # накопления сравнений с SYNOP (см. Horizon в docs/topics/eumetsat.md).
    if area_fraction_now < 0.05:
        current_state_str = "clear"
    elif area_fraction_now < 0.20:
        current_state_str = "mostly_clear"
    elif area_fraction_now < 0.45:
        current_state_str = "variable"
    elif area_fraction_now < 0.65:
        current_state_str = "considerable"
    elif area_fraction_now < 0.85:
        current_state_str = "cloud"
    else:
        current_state_str = "overcast"

    # Бинарное решение "что искать поблизости" (ближайшее облако vs
    # ближайший просвет) — по большинству (>50% радиуса), отдельно от
    # трёхуровневого current_state выше: для "переменной" облачности
    # искать и то и другое одновременно эта функция не умеет, majority-vote
    # — разумный выбор цели по умолчанию.
    want_cloud_target = area_fraction_now < 0.5
    target_type = "cloud_mass" if want_cloud_target else "clearing"

    # ROI-контракт для остальных модулей пайплайна (ИК/GeoColour/Phase-Type/
    # осадки/гроза читают candidates вместо собственного независимого поиска
    # "ближайшего пятна" — см. docs/topics/eumetsat.md, план от 2026-08-04)
    candidates = _significant_blobs(is_cloud_now, valid_now, want_cloud_target)
    # Выбор "ближайшего облака" СИНХРОНИЗИРОВАН с реестром повторяющихся
    # ложных срабатываний CLM (data/eumetsat_target_false_positive_log.json,
    # см. docs/topics/eumetsat.md, запись 2026-08-08) — раньше этот блок
    # искал ближайшее пятно сам по себе (_nearest_of_type), в обход
    # подавления, из-за чего карточка "Облачность" могла показывать ровно
    # тот объект, который "Итог" уже считает шумовым и подавляет. Для
    # облаков (want_cloud_target) фильтр смотрит на кандидатов ЛЮБОГО
    # класса (не только "local" — крупная система тоже должна попадать
    # сюда, как и раньше попадала через _nearest_of_type); для просветов
    # подавление не имеет смысла (реестр — только про ложные срабатывания
    # облачности), берём просто ближайший.
    suppressed_cand = None
    fp_log = fc.load_false_positive_log()
    if want_cloud_target:
        picked, suppressed_cand = fc.pick_nearest_candidate(candidates, fp_log, require_class=None)
    else:
        picked = candidates[0] if candidates else None
    p_now = (picked["centroid_dx_km"], picked["centroid_dy_km"]) if picked is not None else None
    blob_area_km2 = picked["area_km2"] if picked is not None else None
    picked_target_id = picked["target_id"] if picked is not None else None
    picked_class = picked.get("class") if picked is not None else None
    # Перекрёстная проверка ДО отображения (не только после исключения) —
    # см. docs/topics/eumetsat.md, запись 2026-08-08 (2): этот блок сам по
    # себе видит ТОЛЬКО CLM, без оглядки на ИК/GeoColour/Phase-Type — те
    # голосуют уже ПОСЛЕ этого прогона в этом же цикле (target_summary
    # пишется последним), так что live-consensus текущего цикла тут в
    # принципе недоступен. Но реестр ложных срабатываний уже содержит
    # результат ПРЕДЫДУЩЕЙ проверки той же сигнатуры (not_confirmed_streak) —
    # используем его как опережающий сигнал, а не ждём порога исключения
    # (3 подряд), после которого объект и так пропадёт из candidates.
    cross_check_streak = 0
    if want_cloud_target and picked is not None:
        _sig = fc.false_positive_signature(picked["centroid_dx_km"], picked["centroid_dy_km"])
        _entry = fp_log.get(_sig)
        if _entry:
            cross_check_streak = _entry.get("not_confirmed_streak", 0)
    vx, vy, n_pairs = _estimate_motion(is_cloud_frames, times)

    trend = _density_height_shape_trend(is_cloud_frames, cth_index_frames, valid_frames, local_mask)
    buffer_status = _buffer_status(len(packed_frames))

    if p_now is None:
        verdict_text = "однородно в радиусе ~{}км, {} не найдено".format(
            round(HALF_WINDOW_DEG * KM_PER_DEG_LON),
            "облаков" if want_cloud_target else "просветов",
        )
        if want_cloud_target and suppressed_cand is not None:
            # Кандидат физически есть, но это уже известный шумовой объект
            # (все local/system-кандидаты рядом подавлены) — не то же самое,
            # что "реально пусто", поэтому отдельная формулировка.
            verdict_text = (
                f"рядом виден только известный шумовой объект "
                f"(сигнатура {suppressed_cand['false_positive_signature']}), подавлено — "
                f"настоящих облаков в радиусе не найдено"
            )
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "current_state": current_state_str,
            "station_area_fraction": round(area_fraction_now, 3),
            "target_type": target_type,
            "verdict": verdict_text,
        }
    else:
        dist_now = math.hypot(*p_now)
        bearing_now, compass_now = _bearing_compass(*p_now)

        if vx is None:
            out = {
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "current_state": current_state_str,
                "station_area_fraction": round(area_fraction_now, 3),
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "blob_area_km2": round(blob_area_km2, 0),
                "target_id": picked_target_id,
                "class": picked_class,
                "verdict": "скорость посчитать не удалось (поле слишком однородно во всех кадрах)",
            }
            if target_type == "cloud_mass":
                out["probability_percent"] = _change_probability(
                    out["verdict"], dist_now, cpa_km=None, eta_min=None,
                    blob_area_km2=blob_area_km2, confidence=0.25,
                )
                out["probability_note"] = (
                    "база — близость (скорость не посчиталась, доверие снижено), "
                    "не физическая модель осадков"
                )
                if cross_check_streak > 0:
                    out["cross_check_warning"] = (
                        f"на последней проверке остальные каналы (ИК/GeoColour/"
                        f"Phase-Type) эту цель НЕ подтвердили "
                        f"({cross_check_streak}/{fc.FALSE_POSITIVE_STREAK_THRESHOLD} "
                        f"до автоисключения) — возможно, ложное срабатывание CLM"
                    )
                    out["probability_percent"] = max(3, round(out["probability_percent"] * 0.5))
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
                "current_state": current_state_str,
                "station_area_fraction": round(area_fraction_now, 3),
                "target_type": target_type,
                "distance_km_now": round(dist_now, 1),
                "bearing_deg": round(bearing_now, 0),
                "compass": compass_now,
                "speed_kmh": round(speed_kmh, 1),
                "direction_compass": _compass(bearing_v),
                "cpa_km": round(cpa_km, 1),
                "eta_min": eta_min if verdict in ("приближается", "уже у города") else None,
                "blob_area_km2": round(blob_area_km2, 0),
                "target_id": picked_target_id,
                "class": picked_class,
                "verdict": verdict,
                "frame_pairs_used": n_pairs,
            }
            if target_type == "cloud_mass":
                confidence = min(1.0, n_pairs / max(1, len(packed_frames) - 1))
                out["probability_percent"] = _change_probability(
                    verdict, dist_now, cpa_km, eta_min, blob_area_km2, confidence,
                )
                out["probability_note"] = (
                    f"база берётся из категории движения ('{verdict}'), затем немного "
                    "корректируется площадью поля и уверенностью в оценке скорости — "
                    "у 'удаляется'/'пройдёт мимо' база низкая, у 'приближается'/'уже у "
                    "города' высокая; не физическая модель осадков"
                )
                if cross_check_streak > 0:
                    out["cross_check_warning"] = (
                        f"на последней проверке остальные каналы (ИК/GeoColour/"
                        f"Phase-Type) эту цель НЕ подтвердили "
                        f"({cross_check_streak}/{fc.FALSE_POSITIVE_STREAK_THRESHOLD} "
                        f"до автоисключения) — возможно, ложное срабатывание CLM"
                    )
                    out["probability_percent"] = max(3, round(out["probability_percent"] * 0.5))

    out["trend"] = trend
    out["buffer_status"] = buffer_status
    out["candidates"] = candidates
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


