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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image, ImageDraw
from scipy import ndimage

WMS_BASE = "https://view.eumetsat.int/geoserver/wms"
GETCAPABILITIES_URL = WMS_BASE + "?service=WMS&version=1.3.0&request=GetCapabilities"
_WMS_NS = "{http://www.opengis.net/wms}"

# ЕДИНЫЙ источник правды по геометрии — data/geo_config.json (центр,
# радиусы, оба окна/bbox). Меняешь его — подхватывается всеми скриптами,
# которые импортируют константы отсюда (fc.CENTER_LAT и т.п.), а не
# держат свою копию числа. См. комментарий в самом geo_config.json.
_GEO_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "data", "geo_config.json")
with open(_GEO_CONFIG_PATH, "r", encoding="utf-8") as _f:
    _GEO = json.load(_f)

CENTER_LAT = _GEO["center_lat"]
CENTER_LON = _GEO["center_lon"]
STATION_LABEL = _GEO["station_label"]

# Контур побережья near-окна — data/coastline_near.json, статичные точки,
# см. комментарий в самом файле (посчитан один раз 2026-08-16, не
# runtime-зависимость). Не критично, если файла нет (старый checkout,
# ручной запуск) — тогда просто пустой список, draw_coastline_overlay()
# рисовать нечего, но не падает.
_COASTLINE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "coastline_near.json")
try:
    with open(_COASTLINE_PATH, "r", encoding="utf-8") as _f:
        COASTLINE_NEAR = json.load(_f).get("polylines", [])
except FileNotFoundError:
    COASTLINE_NEAR = []


def get_layer_latest_time(layer_name, timeout=25):
    """Спрашивает GetCapabilities и возвращает (default_iso, period_iso) для
    указанного слоя — default это АВТОРИТЕТНОЕ "самое свежее доступное
    время" по объявлению самого сервера (Dimension name="time" default=...),
    а не наша локальная догадка "текущее время округлённое вниз до шага".
    Раньше запрос "последнего" кадра строился как now floored to STEP_MINUTES,
    и мог целиться во время, которого сервер ещё не опубликовал (см. историю
    404/ServiceException на конкретный TIME) — эта функция устраняет саму
    причину, беря время напрямую из объявления сервера, а не угадывая его.
    Возвращает (None, None) при сетевой ошибке/отсутствии слоя — вызывающий
    код должен в этом случае откатиться на старую логику (floor(now))."""
    try:
        r = requests.get(GETCAPABILITIES_URL, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for layer in root.iter(_WMS_NS + "Layer"):
            name_el = layer.find(_WMS_NS + "Name")
            if name_el is not None and name_el.text == layer_name:
                dim_el = layer.find(f'{_WMS_NS}Dimension[@name="time"]')
                if dim_el is not None:
                    default_raw = dim_el.get("default")
                    default_iso = None
                    if default_raw:
                        # Сервер отдаёt "...T17:50:00Z" (без миллисекунд) —
                        # приводим к внутреннему формату буфера "...000Z",
                        # иначе не совпадёт с _parse_iso_minutes/is_duplicate_pair.
                        dt = datetime.strptime(default_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        default_iso = dt.strftime("%Y-%m-%dT%H:%M:00.000Z")
                    period_iso = None
                    if dim_el.text and "/" in dim_el.text:
                        period_iso = dim_el.text.strip().split("/")[-1]
                    return default_iso, period_iso
        return None, None
    except Exception:
        return None, None

HALF_WINDOW_DEG = _GEO["motion_window"]["half_window_deg"]
TILE_SIZE = _GEO["motion_window"]["tile_size"]
KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(CENTER_LAT))
KM_PER_PX_X = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LON) / TILE_SIZE
KM_PER_PX_Y = (2 * HALF_WINDOW_DEG * KM_PER_DEG_LAT) / TILE_SIZE

# Широкий обзорный bbox для eumetsat_anim_render.py (mp4-петли на
# eumetsat.html) — раньше был хардкожен прямо там, теперь тоже из
# geo_config.json. WIDTH/HEIGHT в пикселях остаются производными
# (считаются из bbox+target_km_per_px в самом eumetsat_anim_render.py),
# это не независимая настройка.
ANIM_BBOX = tuple(_GEO["anim_window"]["bbox"])
ANIM_TARGET_KM_PER_PX = _GEO["anim_window"]["target_km_per_px"]

# Тир "far" (≈1000км) — симметричный вокруг Одессы, как motion_window, но шире.
# bbox строится из half_window_deg точно так же, как HALF_WINDOW_DEG для
# motion_window (min_lon,min_lat,max_lon,max_lat — порядок CRS:84).
_far_half = _GEO["far_window"]["half_window_deg"]
FAR_BBOX = (CENTER_LON - _far_half, CENTER_LAT - _far_half,
            CENTER_LON + _far_half, CENTER_LAT + _far_half)
FAR_TARGET_KM_PER_PX = _GEO["far_window"]["target_km_per_px"]

# Тир "very_far" (≈2500км, Испания/Италия/Британия) — НЕ симметричен вокруг
# Одессы (нужен запад/юго-запад Европы), поэтому bbox — явный литерал в JSON,
# не производная от CENTER_LAT/LON.
VERY_FAR_BBOX = tuple(_GEO["very_far_window"]["bbox"])
VERY_FAR_TARGET_KM_PER_PX = _GEO["very_far_window"]["target_km_per_px"]

# Радиус тира "near" (≈192км) — та же зона, откуда CLM берёт кандидатов
# для таблиц local_candidates/system_candidates (motion_window). Нужен как
# явная python-константа (не только в geo_config.json) для отрисовки круга
# зоны обзора на снимке GeoColour, см. eumetsat_geocolour_motion.py,
# _save_clean_snapshot() — запрос 2026-08-10 ("дорисуй окружность обзора").
NEAR_RADIUS_KM = _GEO["control_tiers"]["near"]["radius_km"]

# Западный тайл (пилот, план "мозаика тайлов" для дальнего детекта фронтов,
# обсуждение с пользователем 2026-08-16) — тот же half_window_deg/TILE_SIZE,
# что и motion_window (то же разрешение км/px), bbox сдвинут на запад
# впритык к near-tier с нахлёстом overlap_km (для склейки объектов на
# границе в eumetsat_frontal_track.py). ВАЖНО: WEST_TILE_OFFSET_DX_KM/DY_KM —
# смещение ЦЕНТРА западного тайла относительно Одессы. Кандидаты детектора
# считаются локально относительно центра западного тайла ТОЙ ЖЕ формулой,
# что pixel_to_km_offset() для near-tier, а затем к ним прибавляется это
# смещение — так координаты западного тайла оказываются в ТОЙ ЖЕ системе
# "км от Одессы", что и near-tier, без отдельного converter'а через
# абсолютные lat/lon (проще и меньше риска ошибки, т.к. широта тайлов
# одинакова — WEST_CENTER_LAT == CENTER_LAT, поэтому DY-смещение равно 0).
_west_overlap_km = _GEO["west_window"]["overlap_km"]
_west_tile_width_km = 2 * HALF_WINDOW_DEG * KM_PER_DEG_LON
_west_offset_km = _west_tile_width_km - _west_overlap_km
_west_offset_deg_lon = _west_offset_km / KM_PER_DEG_LON
WEST_CENTER_LON = CENTER_LON - _west_offset_deg_lon
WEST_CENTER_LAT = CENTER_LAT
WEST_BBOX = (WEST_CENTER_LON - HALF_WINDOW_DEG, WEST_CENTER_LAT - HALF_WINDOW_DEG,
             WEST_CENTER_LON + HALF_WINDOW_DEG, WEST_CENTER_LAT + HALF_WINDOW_DEG)
WEST_TILE_OFFSET_DX_KM = (WEST_CENTER_LON - CENTER_LON) * KM_PER_DEG_LON
WEST_TILE_OFFSET_DY_KM = (WEST_CENTER_LAT - CENTER_LAT) * KM_PER_DEG_LAT

AFFECT_THRESHOLD_KM = 15.0
STATIONARY_SPEED_KMH = 3.0
MIN_FRACTION_FOR_CORR = 0.02
MIN_SIGNIFICANT_BLOB_PX = 40
SIGNIFICANT_AREA_REF_KM2 = 1200.0

LOCAL_RADIUS_KM = _GEO["local_radius_km"]
# Радиус "прямо над станцией" — МЕНЬШЕ LOCAL_RADIUS_KM (тот — для трендов
# density/height/shape/area по региону). Смешивать их в одном радиусе —
# частая ошибка: живой кейс (eumetsat_cloud_forecast.py, 2026-08-01 22:00Z)
# показал 0% облачности в 0-10км от станции, но 25% в круге 50км, потому что
# стоящее почти на месте облако в 15-50км утаскивало долю за порог "variable".
# STATE_RADIUS_KM — общий для всех *_motion.py скриптов, считающих
# station_state тем же способом (area_fraction в локальном круге).
STATE_RADIUS_KM = _GEO["state_radius_km"]

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


def fetch_map_custom(layer_name, bbox_lonlat, width, height, time_iso=None,
                      retries=2, delay=4, style="", crs="CRS:84"):
    """Как fetch_tile(), но с произвольным bbox/размером картинки — для
    рендера широкого обзорного кадра (eumetsat_anim_render.py), а не
    маленького квадрата анализа вокруг Одессы. bbox_lonlat — кортеж
    (min_lon, min_lat, max_lon, max_lat)."""
    min_lon, min_lat, max_lon, max_lat = bbox_lonlat
    if crs == "EPSG:4326":
        bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    else:
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer_name,
        "styles": style,
        "crs": crs,
        "bbox": bbox,
        "width": width,
        "height": height,
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
                snippet = r.content[:300].decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {r.status_code}, content-type={ctype!r}, len={len(r.content)}: {snippet}")
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return np.array(img)
        except Exception as e:
            attempt_errors.append(f"попытка {attempt}: {e}")
            if attempt < retries:
                _time.sleep(delay)
    raise RuntimeError("; ".join(attempt_errors))


def rgb_to_hsv_vec(arr):
    """arr: (H,W,3) uint8 RGB -> (h_deg, s, v), все (H,W) float, векторно.
    Стандартная формула RGB->HSV без внешних зависимостей (matplotlib нет
    в requirements пайплайна). Общая версия для скриптов, работающих с
    RGB-композитами (Cloud Phase/Type RGB, GeoColour RGB) — в отличие от
    большинства функций этого модуля, рассчитанных на одноканальные
    (grayscale/бинарные) поля."""
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


def classify_presence_by_alpha(arr):
    """presence = непрозрачный пиксель (значение > 0 по легенде продукта).
    valid = True почти везде — для этих продуктов alpha сам кодирует
    "0/нет сигнала", это не индикатор отсутствия данных."""
    presence = arr[:, :, 3] > 0
    valid = np.ones_like(presence, dtype=bool)
    return presence, valid


def pixel_to_km_offset(row, col):
    """ВАЖНО: центр и шаг должны совпадать с local_area_mask()/
    station_area_mask() (center=(TILE_SIZE-1)/2, шаг=KM_PER_PX_*), иначе
    здесь и там — разные конвенции пиксельной сетки. Раньше здесь была
    edge-to-edge конвенция (frac=col/(TILE_SIZE-1), пиксель 0 ровно на
    границе bbox) вместо pixel-as-area (пиксель 0 занимает область шириной
    в 1/TILE_SIZE окна, а не точку на границе) — как и должно быть для
    WMS GetMap, где bbox описывает границы растра, а не координаты точек.
    Расхождение росло от 0 в центре окна до ~0.5км на краю 5°-окна и
    искажало cloud_mass_distance_km/bearing из nearest_of_type() —
    небольшая, но систематическая ошибка именно в «расстоянии до облака
    от станции» (см. обсуждение в чате, 2026-08-02)."""
    center = (TILE_SIZE - 1) / 2
    dx_km = (col - center) * KM_PER_PX_X
    dy_km = -(row - center) * KM_PER_PX_Y  # row растёт вниз (юг) -> dy_km отрицательный
    return dx_km, dy_km


def local_area_mask():
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= LOCAL_RADIUS_KM


def station_area_mask():
    """Как local_area_mask(), но радиус STATE_RADIUS_KM (12км) — для
    station_state ("сейчас над станцией"), а не для региональных трендов."""
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = (rows - center) * KM_PER_PX_Y
    dist_km = np.sqrt(dx_km ** 2 + dy_km ** 2)
    return dist_km <= STATE_RADIUS_KM


# --- Реестр повторяющихся ложных срабатываний CLM (шумовые объекты) ---
# См. docs/topics/eumetsat.md, запись от 2026-08-07: некоторые CLM-кандидаты
# регулярно (по наблюдению — почти круглосуточно) НЕ подтверждаются
# остальными каналами в одной и той же точке — похоже на артефакт
# классификации CLM, а не реальную облачность. Вместо подавления области
# целиком отслеживаем историю ПО СИГНАТУРЕ (квантованная координата),
# исключаем конкретный повторяющийся объект, если он N раз подряд не
# подтверждён, и периодически (TTL) даём ему шанс на повторную проверку.
# Единственный писатель этого файла — eumetsat_target_summary.py (там же
# считается consensus), остальные модули только читают.
FALSE_POSITIVE_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "data", "eumetsat_target_false_positive_log.json")
FALSE_POSITIVE_GRID_KM = 5.0          # квантование координаты в сигнатуру
FALSE_POSITIVE_STREAK_THRESHOLD = 3   # not_confirmed подряд -> исключить
FALSE_POSITIVE_REACTIVATE_STREAK = 2  # confirmed/disputed подряд -> вернуть
FALSE_POSITIVE_TTL_HOURS = 6          # раз в сколько давать повторный шанс

# ОТДЕЛЬНЫЙ (более быстрый) порог для реестров подавления ТАБЛИЦ (local/
# system_channel_suppression) — по прямому запросу 2026-08-10:
# "не ждать несколько прогонов... такие объекты сразу надо вычёркивать".
# В отличие от FALSE_POSITIVE_STREAK_THRESHOLD=3 (используется ТОЛЬКО для
# основной voting-цели — там цена ошибки высокая, объект пропадает из
# "Итог" совсем), здесь цена ошибки низкая (объект просто на 1 цикл
# исчезает из описательной таблицы, легко возвращается при первом же
# подтверждении) — значит нет смысла ждать: если ИК и GeoColour ОБА не
# подтвердили уже в этом цикле, значит нет причин показывать "облако",
# которое ни один реальный канал не видит. Порог возврата НЕ трогаем
# (FALSE_POSITIVE_REACTIVATE_STREAK=2) — небольшой гистерезис на возврат
# защищает от мигания объекта туда-сюда на грани порога.
CHANNEL_SUPPRESSION_STREAK_THRESHOLD = 1  # not_confirmed -> исключить сразу же


def false_positive_signature(dx_km, dy_km, grid_km=FALSE_POSITIVE_GRID_KM):
    """Квантует координату кандидата в ячейку сетки grid_km×grid_km —
    сигнатура одного и того же физического места, устойчивая к мелкому
    дрожанию centroid между прогонами."""
    gx = round(dx_km / grid_km) * grid_km
    gy = round(dy_km / grid_km) * grid_km
    return f"{gx:.0f}_{gy:.0f}"


def load_false_positive_log():
    """Читает data/eumetsat_target_false_positive_log.json. Отсутствие
    файла/битый JSON — не ошибка, просто ещё нет истории (пустой реестр)."""
    try:
        with open(FALSE_POSITIVE_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_false_positive_log(fp_log):
    os.makedirs(os.path.dirname(FALSE_POSITIVE_LOG_PATH), exist_ok=True)
    with open(FALSE_POSITIVE_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(fp_log, f, ensure_ascii=False, indent=2)


# Отдельный реестр подавления ДЛЯ ТАБЛИЦЫ ВСЕХ локальных очагов на
# nearby.html — по запросу 2026-08-10 ("скопления, которые не видит ни
# ir_motion, ни geocolour_motion — банить по принципу как в Итог"). НЕ тот
# же файл, что FALSE_POSITIVE_LOG_PATH выше (тот — трио-голосование
# ир/geocolour/phase_type ТОЛЬКО для основной voting-цели, единственный
# писатель — main() до этой правки). Здесь критерий УЖЕ (только ИК+
# GeoColour оба явно False) и применяется КО ВСЕМ кандидатам таблицы, не
# только к первичному — смешивать в одном файле/одних полях было бы
# путаницей двух разных правил голосования по одной сигнатуре. Та же
# сигнатура координат (false_positive_signature) и та же TTL-логика
# (_fp_currently_excluded, см. fp_currently_excluded ниже) — просто другой
# файл и другие поля счётчиков (см. eumetsat_target_summary.py).
LOCAL_CHANNEL_SUPPRESSION_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "eumetsat_local_channel_suppression_log.json")


def load_local_channel_suppression_log():
    try:
        with open(LOCAL_CHANNEL_SUPPRESSION_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_local_channel_suppression_log(log):
    os.makedirs(os.path.dirname(LOCAL_CHANNEL_SUPPRESSION_LOG_PATH), exist_ok=True)
    with open(LOCAL_CHANNEL_SUPPRESSION_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# Та же логика, но для таблицы систем — по запросу 2026-08-10 ("делай такую
# же фильтрацию невидимых для систем"). ОТДЕЛЬНЫЙ файл от
# LOCAL_CHANNEL_SUPPRESSION_LOG_PATH — системы и локальные очаги физически
# разные объекты, сигнатура координат (одна и та же сетка) могла бы иначе
# случайно столкнуться между классами.
SYSTEM_CHANNEL_SUPPRESSION_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "eumetsat_system_channel_suppression_log.json")


def load_system_channel_suppression_log():
    try:
        with open(SYSTEM_CHANNEL_SUPPRESSION_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_system_channel_suppression_log(log):
    os.makedirs(os.path.dirname(SYSTEM_CHANNEL_SUPPRESSION_LOG_PATH), exist_ok=True)
    with open(SYSTEM_CHANNEL_SUPPRESSION_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _fp_currently_excluded(entry):
    """True, если сигнатура сейчас реально исключена — статус excluded И
    TTL повторного шанса ещё не истёк. По истечении TTL сигнатура на один
    цикл снова становится доступной для выбора: если объект и правда
    шумовой, он почти сразу наберёт новый streak not_confirmed и будет
    переисключён (excluded_since обновится); если условия изменились —
    пройдёт ROI-подтверждение и статус снимется."""
    if not entry or entry.get("status") != "excluded":
        return False
    since = entry.get("excluded_since")
    if not since:
        return True
    try:
        dt = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return age_hours < FALSE_POSITIVE_TTL_HOURS


def fp_currently_excluded(entry):
    """Публичная обёртка над _fp_currently_excluded() — переиспользуется
    другими реестрами с той же TTL-логикой (не только
    FALSE_POSITIVE_LOG_PATH), см. LOCAL_CHANNEL_SUPPRESSION_LOG_PATH выше и
    docs/topics/eumetsat.md, запись 2026-08-10."""
    return _fp_currently_excluded(entry)


def pick_nearest_candidate(candidates, fp_log=None, require_class="local"):
    """Обобщённая версия: выбирает ближайшего кандидата нужного класса,
    ПРОПУСКАЯ те, чья сигнатура сейчас в статусе excluded (см. блок выше).
    require_class: "local" — как раньше (для 5 confirming-модулей и
    target_summary), "system" — только системные, None — любой класс
    (используется картой "Облачность" на nearby.html, чтобы её выбор цели
    совпадал с "Итогом" — см. docs/topics/eumetsat.md, запись 2026-08-08).
    candidates — уже отсортированный по расстоянию список (как отдаёт
    cloud_forecast.json). Возвращает (target_or_None, suppressed_or_None)."""
    if fp_log is None:
        fp_log = load_false_positive_log()
    suppressed = None
    for c in candidates:
        if require_class is not None and c.get("class", "local") != require_class:
            continue
        sig = false_positive_signature(c["centroid_dx_km"], c["centroid_dy_km"])
        if _fp_currently_excluded(fp_log.get(sig)):
            if suppressed is None:
                suppressed = dict(c, false_positive_signature=sig)
            continue
        return c, suppressed
    return None, suppressed


def pick_local_target(candidates, fp_log=None):
    """Выбирает ближайшего local-кандидата, ПРОПУСКАЯ те, чья сигнатура
    сейчас в статусе excluded (см. блок выше). candidates — уже
    отсортированный по расстоянию список (как отдаёт cloud_forecast.json).
    Возвращает (target_or_None, suppressed_or_None) — suppressed — это
    САМЫЙ БЛИЖНИЙ подавленный кандидат (для отображения на странице
    пометки "известный шумовой объект"), даже если дальше нашлась обычная
    цель. Тонкая обёртка над pick_nearest_candidate(require_class="local")."""
    return pick_nearest_candidate(candidates, fp_log, require_class="local")


def load_primary_target(max_age_minutes=30):
    """Читает data/eumetsat_cloud_forecast.json и отдаёт ПЕРВИЧНУЮ ЛОКАЛЬНУЮ
    цель (ближайший кандидат с class=="local" — не просто candidates[0],
    который может оказаться крупной системой, см. вариант "б" от 2026-08-05
    в docs/topics/eumetsat.md) для остальных модулей пайплайна (ИК/
    GeoColour/Phase-Type/осадки/гроза), чтобы они проверяли ТУ ЖЕ ROI, а не
    искали свою независимо (план object-centric пайплайна от 2026-08-04).
    Крупные системы (class=="system") этой функцией не возвращаются
    намеренно — им отдельный, более лёгкий путь без ROI-подтверждения
    (см. eumetsat_target_summary.py).
    Возвращает (target_dict, reason) — target_dict is None если файла нет,
    JSON битый, candidates отсутствует/пусто, локальных масс среди
    кандидатов нет (все system), или снапшот устарел (> max_age_minutes) —
    вызывающий код должен в этом случае откатываться на собственную
    независимую детекцию, а не падать.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "eumetsat_cloud_forecast.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"cloud_forecast.json недоступен: {e}"

    ts_raw = snap.get("timestamp")
    if ts_raw:
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age_min > max_age_minutes:
                return None, f"снапшот устарел ({round(age_min)} мин > {max_age_minutes})"
        except ValueError:
            pass  # не смогли распарсить timestamp — не блокируем, просто не проверяем возраст

    candidates = snap.get("candidates") or []
    if not candidates:
        return None, "candidates пуст или отсутствует (снапшот от старой версии cloud_forecast.py?)"
    # class отсутствует у снапшотов ДО коммита 6f12528 (2026-08-05) —
    # трактуем как "local" для обратной совместимости, старое поведение
    # (просто ближайший) сохраняется, пока не накопятся новые снапшоты.
    target, suppressed = pick_local_target(candidates)
    if target is not None:
        return target, "ok"
    if suppressed is not None:
        return None, (f"известный шумовой объект в этой точке подавлен "
                       f"(сигнатура {suppressed['false_positive_signature']}), "
                       f"других локальных целей нет")
    return None, "среди кандидатов нет локальных масс (только системы синоптического масштаба)"


def load_system_target(max_age_minutes=30):
    """Как load_primary_target(), но отдаёт ближайшую крупную систему
    (class=="system") вместо локальной цели — для обогащающего (не
    voting) анализа "что несёт система" (фаза/тип, осадки, гроза),
    добавлено 2026-08-06 по итогам обсуждения "нужна ли верификация
    системы" (см. docs/topics/eumetsat.md). В отличие от
    load_primary_target() это НЕ про существование (крупная система и
    так очевидно реальна — не шумовое пятно на грани порога
    MIN_SIGNIFICANT_BLOB_PX), а просто ROI для описательного анализа
    содержимого. Снапшоты без поля "class" (до коммита 6f12528)
    трактуются как "local" и ничего не возвращают здесь — те же правила
    обратной совместимости, что в load_primary_target().
    Возвращает (target_dict, reason), target_dict is None при отсутствии
    системы среди кандидатов (обычный случай — большинство прогонов без
    крупных систем поблизости) или прочих сбоях чтения снапшота.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "eumetsat_cloud_forecast.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"cloud_forecast.json недоступен: {e}"

    ts_raw = snap.get("timestamp")
    if ts_raw:
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age_min > max_age_minutes:
                return None, f"снапшот устарел ({round(age_min)} мин > {max_age_minutes})"
        except ValueError:
            pass

    candidates = snap.get("candidates") or []
    if not candidates:
        return None, "candidates пуст или отсутствует"
    for c in candidates:
        if c.get("class", "local") == "system":
            return c, "ok"
    return None, "среди кандидатов нет систем синоптического масштаба (только локальные массы)"


def load_system_targets_all(max_age_minutes=30):
    """Как load_system_target(), но возвращает СПИСОК ВСЕХ систем
    (class=="system"), а не только ближайшую — по запросу 2026-08-09:
    "нужно подтверждение от остальных каналов, как для локальных очагов,
    для КАЖДОЙ системы", не только для ближайшей (её одну уже покрывает
    load_system_target() + _load_system_enrichment() в
    eumetsat_target_summary.py). Используется тремя модулями
    (cloud_phase_type/precip/lightning forecast), которые пишут
    system_analysis_all — список обогащения (фаза/осадки/гроза) по
    КАЖДОМУ target_id, не только по одному. Дублирует часть логики
    load_system_target() ради простоты (не рефакторил в общую приватную
    функцию, чтобы не трогать поведение уже проверенной load_system_target()).
    Возвращает [] (не None) при отсутствии систем или сбоях чтения —
    "нет систем для обогащения" не отличается по последствиям от "снапшот
    недоступен", вызывающему коду достаточно one for-loop без веток.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "eumetsat_cloud_forecast.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    ts_raw = snap.get("timestamp")
    if ts_raw:
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age_min > max_age_minutes:
                return []
        except ValueError:
            pass

    candidates = snap.get("candidates") or []
    return [c for c in candidates if c.get("class", "local") == "system"]


def load_local_targets_all(max_age_minutes=30):
    """Как load_system_targets_all(), но возвращает СПИСОК ВСЕХ локальных
    очагов (class=="local"), а не только первичный (его одного уже покрывает
    load_primary_target()/pick_local_target() с учётом реестра ложных
    срабатываний). Нужно, чтобы построить для локальных очагов ту же
    построчную таблицу (Км/Напр./Площадь/Ось/Aspect/Фронт?/Фаза/Тип/🌧️/⚡/
    IR/GC), что уже есть для систем (см. docs/topics/eumetsat.md, задача из
    Horizon 2026-08-09 "такая же таблица, как для систем, для локальных
    очагов"). В отличие от load_primary_target() НЕ фильтрует по реестру
    ложных срабатываний — таблица описательная (снапшот всех кандидатов
    CLM), подавление актуально только для выбора ОДНОЙ voting-цели, не для
    обзорного списка.
    Возвращает [] (не None) при отсутствии кандидатов или сбоях чтения.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "eumetsat_cloud_forecast.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    ts_raw = snap.get("timestamp")
    if ts_raw:
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            if age_min > max_age_minutes:
                return []
        except ValueError:
            pass

    candidates = snap.get("candidates") or []
    return [c for c in candidates if c.get("class", "local") == "local"]


def km_bbox_to_pixel_mask(bbox_km, pad_km=0.0):
    """Обратное к pixel_to_km_offset() — булева (TILE_SIZE,TILE_SIZE) маска,
    True внутри bbox_km (словарь dx_min/dx_max/dy_min/dy_max, как отдаёт
    _significant_blobs()), с необязательным расширением на pad_km по краям
    (запас на неточность привязки между разными слоями/проекциями WMS)."""
    rows, cols = np.meshgrid(np.arange(TILE_SIZE), np.arange(TILE_SIZE), indexing="ij")
    center = (TILE_SIZE - 1) / 2
    dx_km = (cols - center) * KM_PER_PX_X
    dy_km = -(rows - center) * KM_PER_PX_Y  # тот же знак, что в pixel_to_km_offset
    in_x = (dx_km >= bbox_km["dx_min"] - pad_km) & (dx_km <= bbox_km["dx_max"] + pad_km)
    in_y = (dy_km >= bbox_km["dy_min"] - pad_km) & (dy_km <= bbox_km["dy_max"] + pad_km)
    return in_x & in_y


def is_daytime(t_iso):
    """Грубая оценка дня/ночи по локальному часу — НЕ настоящий расчёт
    восхода/заката (без сезонной/DST-точности, UTC+3 — летнее время
    Одессы), но структурно достаточно, чтобы развести ветки классификации.
    ЕДИНСТВЕННАЯ реализация — раньше была локальная копия в
    eumetsat_geocolour_motion.py, вынесена сюда 2026-08-04 по тому же
    принципу, что и pixel_to_km_offset (см. коммент там про инцидент
    с расхождением копий при фиксе в одном месте, но не в другом)."""
    dt = datetime.strptime(t_iso, "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=timezone.utc)
    local_hour = (dt.hour + 3) % 24
    return 5 <= local_hour < 20


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


def estimate_motion_dt(masks, times_iso):
    """То же, что estimate_motion(masks, dt_minutes), но dt между парой
    считается из РЕАЛЬНЫХ таймстемпов (см. estimate_motion_continuous —
    та же причина: персистентный буфер может содержать пропуски, и
    фиксированный шаг тогда завысит/занизит скорость для затронутой пары).
    Плюс явная защита от кадров-дублей (is_duplicate_pair) — у estimate_motion()
    её нет, там дубль просто давал бы честный (0,0) и не отличался от
    "объект не двигался", здесь же с плавающим dt дубль (diff=0 при dt>0)
    исказил бы среднее так же, как в estimate_motion_continuous."""
    vx_list, vy_list = [], []
    times_min = [_parse_iso_minutes(t) for t in times_iso]
    for i in range(len(masks) - 1):
        dt_h = (times_min[i + 1] - times_min[i]) / 60.0
        if dt_h <= 0:
            continue
        m_prev, m_curr = masks[i], masks[i + 1]
        if is_uniform(m_prev) or is_uniform(m_curr):
            continue
        if np.array_equal(m_prev, m_curr):
            continue
        dy_px, dx_px = phase_shift_px(m_prev, m_curr)
        vx_list.append((dx_px * KM_PER_PX_X) / dt_h)
        vy_list.append((-dy_px * KM_PER_PX_Y) / dt_h)
    if not vx_list:
        return None, None, 0
    return float(np.mean(vx_list)), float(np.mean(vy_list)), len(vx_list)


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


# Единый источник порога ИК-контраста — РАНЬШЕ была локальная константа
# внутри eumetsat_ir_motion.py (тот же смысл, то же значение 1.2), теперь
# здесь, чтобы не было риска рассинхронизации между модулем-источником
# (ir_motion.py per-ROI confirmed) и новым пиксельным использованием ниже
# (eumetsat_cloud_forecast.py, "ясно/переменная облачность/..." — запрос
# 2026-08-10, "учитывать только те облака, которые подтверждены IR и GC").
# eumetsat_ir_motion.py теперь ссылается на fc.MIN_CLOUD_CONTRAST_SIGMA
# вместо своей копии.
#
# 2026-08-11: калибровка по 197 историческим SYNOP-срокам (station 33837)
# показала, что self-relative контраст СТРУКТУРНО слабо коррелирует с
# synop_n (Spearman rho макс. 0.31 на r=100км, немонотонно по бакетам N —
# метод ищет, что выделяется на фоне ВСЕГО окна в сотни км, а не долю
# облачности именно над станцией; см. docs/topics/eumetsat.md). Перебор
# порога это не лечит принципиально, но даёт заметный практический выигрыш
# при том же методе: на sigma=0.8 детект при N=8-9 почти удваивается
# (0.140->0.250 на r=100км), а ложное срабатывание на N=0 остаётся
# умеренным (медиана 0.024). Решение (согласовано с пользователем): лёгкий
# тюнинг 1.2->0.8, полная переработка метода отложена (отдельная задача,
# не 20-минутная калибровка). ИК — подтверждающий канал в голосовании
# (CLM детектирует -> IR подтверждает -> GeoColour подтверждает), чуть
# более чувствительный порог (меньше шанс ложно НЕ подтвердить реальное
# облако) уместнее для такой роли, чем для самостоятельного решения.
MIN_CLOUD_CONTRAST_SIGMA = 0.8

IR_BUFFER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "eumetsat_ir_buffer.npz")
GEOCOLOUR_BUFFER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "data", "eumetsat_geocolour_buffer.npz")


def load_ir_confirmed_mask(smooth_px=3):
    """Пиксельная маска 'ИК видит здесь облако' на последнем доступном
    ИК-кадре (data/eumetsat_ir_buffer.npz — те же сырые grayscale-кадры,
    что читает eumetsat_ir_motion.py). Та же формула self-relative
    контраста, что уже используется там для ROI-подтверждения
    (roi_contrast_sigma >= MIN_CLOUD_CONTRAST_SIGMA), но применённая К
    КАЖДОМУ пикселю кадра, а не к среднему по ROI — по запросу 2026-08-10
    ("учитывать только те облака, которые подтверждены IR и GC" для
    "ясно/малооблачно/..." в eumetsat_cloud_forecast.py).

    smooth_px — сторона box-фильтра (scipy.ndimage.uniform_filter) ПЕРЕД
    расчётом контраста: ROI-агрегация в ir_motion.py усредняет шум по
    площади ROI, а голый попиксельный порог на сыром кадре был бы куда
    шумнее (единичный пиксель может случайно провалиться под порог даже
    в центре настоящего облака) — лёгкое сглаживание 3×3 компенсирует эту
    разницу, не размывая структуру существенно.

    Возвращает (mask (H,W) bool | None, ok bool). ok=False, если буфера ещё
    нет (например ИК-модуль ещё ни разу не отработал) — вызывающий код
    должен в этом случае откатиться на исходную (не-AND) логику, а не
    падать."""
    times, frames = load_frame_buffer(IR_BUFFER_FILE)
    if not frames:
        return None, False
    frame = frames[-1]
    if smooth_px and smooth_px > 1:
        frame = ndimage.uniform_filter(frame, size=smooth_px)
    median = float(np.median(frame))
    std = float(frame.std()) or 1e-6
    sigma = (frame - median) / std
    return sigma >= MIN_CLOUD_CONTRAST_SIGMA, True


def load_geocolour_confirmed_mask():
    """Пиксельная маска 'GeoColour видит здесь облако' — последний
    is_cloud-канал из data/eumetsat_geocolour_buffer.npz (уже бинарный
    per-pixel результат HSV-классификации eumetsat_geocolour_motion.py,
    доп. порог не нужен). Формат упаковки — [gray, is_cloud] на канал 0/1,
    см. _pack_frame()/_unpack_frame() в eumetsat_geocolour_motion.py.
    Возвращает (mask (H,W) bool | None, ok bool), см. докстринг
    load_ir_confirmed_mask() выше про ok=False."""
    times, frames = load_frame_buffer(GEOCOLOUR_BUFFER_FILE)
    if not frames:
        return None, False
    packed = frames[-1]
    return packed[1] > 0.5, True


def draw_coastline_overlay(base_image, color=(140, 165, 130), alpha=130, width=1,
                            origin_dx_km=0.0, origin_dy_km=0.0):
    """Дорисовывает контур береговой линии (суша/море) поверх снимка — по
    запросу 2026-08-16 ("не считаешь нужным добавить контур? для
    ориентира") — ночью/на CLM/ИК географию иначе не разобрать (нет
    натурального цвета, только маска облака/яркость). Источник —
    COASTLINE_NEAR (data/coastline_near.json, статичные точки [lon,lat],
    посчитаны один раз через global-land-mask, см. комментарий в файле).
    Та же RGBA-оверлей-техника, что у draw_view_radius_circle() —
    полупрозрачная линия, не навязчивая поверх снимка. Возвращает НОВОЕ
    Image (режим RGB), не мутирует переданное.

    origin_dx_km/origin_dy_km (добавлено 2026-08-17, план "мозаика тайлов",
    western tile) — смещение ЦЕНТРА снимка относительно Одессы, в системе
    координат "восток/север положительные" (та же, что candidate/track
    dx_km/dy_km, см. fc.WEST_TILE_OFFSET_DX_KM/DY_KM) — ВНУТРИ функции для
    точек береговой линии используется своя south-positive dy-конвенция
    (dy_km = (CENTER_LAT-lat)*KM_PER_DEG_LAT), пересчёт знака сделан здесь.
    Default 0.0 — НЕ МЕНЯЕТ поведение near-tier (его снимок и так
    центрирован на Одессе, тот же результат, что и раньше)."""
    if not COASTLINE_NEAR:
        return base_image
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = (base_image.width - 1) / 2.0
    cy = (base_image.height - 1) / 2.0
    for polyline in COASTLINE_NEAR:
        pts = []
        for lon, lat in polyline:
            dx_km = (lon - CENTER_LON) * KM_PER_DEG_LON
            dy_km = (CENTER_LAT - lat) * KM_PER_DEG_LAT  # y растёт вниз на изображении
            pts.append((cx + (dx_km - origin_dx_km) / KM_PER_PX_X,
                        cy + (dy_km + origin_dy_km) / KM_PER_PX_Y))
        if len(pts) >= 2:
            draw.line(pts, fill=color + (alpha,), width=width)
    return Image.alpha_composite(base_image.convert("RGBA"), overlay).convert("RGB")


def draw_odessa_marker(base_image, color=(225, 225, 230), radius_px=3, outline_color=(0, 0, 0), outline_width=2,
                        origin_dx_km=0.0, origin_dy_km=0.0):
    """Точка-маркер Одессы (станция СИНОП 33837) — по тому же запросу
    2026-08-16, что и draw_coastline_overlay(). Центр снимка ВСЕГДА и есть
    Одесса (CENTER_LAT/CENTER_LON из geo_config.json — та же точка, от
    которой считаются dx_km/dy_km для всех кандидатов/треков/станций) —
    ДЛЯ NEAR-TIER, маркер рисуется прямо в центре кадра, без пересчёта
    координат (origin_dx_km/dy_km=0.0 по умолчанию, см. ниже).

    Правка 2026-08-16 (было и в тот же день): пользователь заметил — точка
    "не того цвета, особенно на CLM" и "слишком яркая". Причина —
    outline_color=(20,20,30) отличался от тёмно-синего фона CLM/ночного
    ИК (18,22,40) всего на 14 единиц суммарной разницы каналов (см. тест
    контраста) — аутлайн был практически невидим, оставалось только
    сплошное яркое БЕЛОЕ (255,255,255) заполнение, которое на CLM сливается
    с белым облаком (232,232,238). Теперь аутлайн — настоящий чёрный
    (0,0,0), шире (width=2, был 1) — читается кольцом даже на белом облаке
    (контраст к (232,232,238) — 702 против 14 у старого к navy). Заливка
    чуть притушена (225,225,230 вместо чистого 255,255,255) и радиус
    уменьшен (3px вместо 4) — менее "кричащая" точка.

    origin_dx_km/origin_dy_km (добавлено 2026-08-17, план "мозаика тайлов")
    — тот же контракт, что у draw_coastline_overlay()/draw_view_radius_circle():
    смещение ЦЕНТРА снимка относительно Одессы (восток/север положительные).
    Для near-tier центр снимка = Одесса, поэтому default 0.0 не меняет
    поведение. Для смещённого тайла (запад) маркер уедет за край кадра
    (Одесса далеко за пределами западного тайла) — PIL просто не нарисует
    видимых пикселей, без ошибки, вызывать безопасно."""
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = (base_image.width - 1) / 2.0 - origin_dx_km / KM_PER_PX_X
    cy = (base_image.height - 1) / 2.0 + origin_dy_km / KM_PER_PX_Y
    r = radius_px
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (255,),
                 outline=outline_color + (255,), width=outline_width)
    return Image.alpha_composite(base_image.convert("RGBA"), overlay).convert("RGB")


def draw_view_radius_circle(base_image, radius_km=None, color=(255, 210, 90), alpha=110, width=2,
                             origin_dx_km=0.0, origin_dy_km=0.0):
    """Дорисовывает ПОЛУПРОЗРАЧНУЮ окружность зоны обзора тира 'near' поверх
    RGB-снимка (PIL Image, режим RGB) — общая для GeoColour и ИК снимков на
    nearby.html (см. eumetsat_geocolour_motion.py, eumetsat_ir_motion.py).
    По запросу 2026-08-10 ('круг сделай не такой яркий') — раньше был
    непрозрачный ImageDraw.ellipse(width=3) прямо по базовому изображению
    (сплошная яркая линия, визуально навязчиво поверх натурального снимка).
    Теперь окружность рисуется на отдельном RGBA-слое с alpha и
    смешивается (Image.alpha_composite) с базой — мягкая полупрозрачная
    линия вместо сплошной.

    radius_km по умолчанию NEAR_RADIUS_KM (тир 'near' ≈192км — та же зона,
    откуда таблицы local_candidates/system_candidates берут кандидатов).
    Возвращает НОВОЕ Image (режим RGB), не мутирует переданное.

    origin_dx_km/origin_dy_km (добавлено 2026-08-17, план "мозаика тайлов")
    — тот же контракт, что у draw_odessa_marker(): сдвигает ЦЕНТР
    окружности (реальный центр окружности всегда Одесса, а не центр
    снимка), радиус не меняется. Для западного тайла центр Одессы лежит
    далеко за правым краем кадра — на снимке появится только небольшая ДУГА
    окружности у восточного края (там, где near-tier и west-tier
    перекрываются, см. WEST_TILE_OFFSET_DX_KM/overlap_km в geo_config.json)
    — это ожидаемо, не ошибка отрисовки."""
    if radius_km is None:
        radius_km = NEAR_RADIUS_KM
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = (base_image.width - 1) / 2.0 - origin_dx_km / KM_PER_PX_X
    cy = (base_image.height - 1) / 2.0 + origin_dy_km / KM_PER_PX_Y
    rx = radius_km / KM_PER_PX_X
    ry = radius_km / KM_PER_PX_Y
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=color + (alpha,), width=width)
    return Image.alpha_composite(base_image.convert("RGBA"), overlay).convert("RGB")


FRONTAL_TRACK_COLORS = [
    (255, 59, 48),    # красный
    (52, 199, 89),    # зелёный
    (10, 132, 255),   # синий
    (255, 149, 0),    # оранжевый
    (191, 90, 242),   # фиолетовый
    (255, 45, 149),   # розовый
    (100, 210, 255),  # голубой
]  # жёлтый намеренно не включён — слишком близок к цвету окружности обзора
   # (255,210,90), легко спутать на глаз


def draw_frontal_tracks_overlay(base_image, tracks, alpha=220, width=5):
    """Подсвечивает найденные frontlike-треки цветными отрезками поверх
    снимка (запрос 2026-08-14: "подсветить найденные фронты, разными
    цветами"). Источник — data/eumetsat_frontal_track.json ("tracks",
    поля dx_km/dy_km/axis_deg/aspect_ratio/area_km2 — см.
    eumetsat_frontal_track.py). Каждый трек — отрезок вдоль его оси
    (axis_deg, конвенция atan2(dx,dy) — 0=С/90=В, ЛИНИЯ 0..180, не вектор,
    поэтому отрезок рисуется симметрично в обе стороны от центроида).
    Длина отрезка — большая ось эллипса, восстановленная из area_km2 и
    aspect_ratio (area=π·a·b, aspect_ratio=a/b ⇒ a=sqrt(area·aspect_ratio/π),
    длина отрезка = 2a) — приближение реальной формы одним числом, не точный
    контур блоба (тот в frontal_track.json не хранится, только сводные
    PCA-параметры).

    Цвет закреплён за track_id (не за позицией в списке `tracks`) через
    FRONTAL_TRACK_COLORS[track_id % len(...)] — один и тот же физический
    трек между кадрами (разными снимками во времени) сохраняет свой цвет,
    что позволяет визуально следить за одним и тем же фронтом по мере его
    движения на последовательных снимках.

    Треки без axis_deg/aspect_ratio (вырожденный PCA, < 5 пикселей —
    см. _blob_elongation) рисуются маленьким кружком-маркером на месте
    центроида вместо отрезка — не пропускаются молча.

    Возвращает НОВОЕ Image (режим RGB), не мутирует переданное — тот же
    контракт, что draw_view_radius_circle."""
    overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = (base_image.width - 1) / 2.0
    cy = (base_image.height - 1) / 2.0
    for t in (tracks or []):
        dx_km = t.get("dx_km")
        dy_km = t.get("dy_km")
        if dx_km is None or dy_km is None:
            continue
        track_id = t.get("track_id", 0)
        color = FRONTAL_TRACK_COLORS[track_id % len(FRONTAL_TRACK_COLORS)]
        px = cx + dx_km / KM_PER_PX_X
        py = cy - dy_km / KM_PER_PX_Y
        axis_deg = t.get("axis_deg")
        aspect_ratio = t.get("aspect_ratio")
        area_km2 = t.get("area_km2")
        if axis_deg is None or aspect_ratio is None or not area_km2:
            # Вырожденный случай — маркер вместо отрезка, не пропускаем.
            r = 6
            draw.ellipse([px - r, py - r, px + r, py + r], outline=color + (alpha,), width=3)
            continue
        semi_major_km = math.sqrt(area_km2 * aspect_ratio / math.pi)
        theta = math.radians(axis_deg)
        step_dx_km = semi_major_km * math.sin(theta)
        step_dy_km = semi_major_km * math.cos(theta)
        step_px = step_dx_km / KM_PER_PX_X
        step_py = -step_dy_km / KM_PER_PX_Y
        draw.line(
            [(px - step_px, py - step_py), (px + step_px, py + step_py)],
            fill=color + (alpha,), width=width,
        )
        r = max(4, width)
        draw.ellipse([px - r, py - r, px + r, py + r], fill=color + (alpha,))
    return Image.alpha_composite(base_image.convert("RGBA"), overlay).convert("RGB")



