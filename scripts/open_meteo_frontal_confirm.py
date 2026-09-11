"""
open_meteo_frontal_confirm.py — консенсус-детекция атмосферных фронтов по
полю (температура/давление) Open-Meteo, регулярная сетка по Европе/
Атлантике.

[ПЕРЕРАБОТАНО 2026-09-09] Раньше было ДВА детектора: near/west
(подтверждение уже найденных спутником кандидатов на локальной сетке
35км вокруг блоба) и europe (независимая консенсус-детекция по
регулярной сетке 220км). По прямому запросу пользователя near/west-
детектор УБРАН ПОЛНОСТЬЮ — остаётся ОДИН детектор (европейская сетка), а
на near-tile (центральный тайл, ~192км) результат ПРОЕЦИРУЕТСЯ
(билинейная интерполяция уже посчитанного поля голосов) — БЕЗ единого
дополнительного запроса к Open-Meteo. Причины: (1) один детектор проще
поддерживать, не дублирует логику голосования; (2) near/west-сетка
(вокруг конкретного спутникового блоба) физически не то же самое явление,
что синоптический фронт/фронтогенез — если европейская сетка видит
реальный крупномасштабный фронт, его "эхо" будет заметно и на
интерполяции до near-tile, просто грубее (это ЧЕСТНЫЙ побочный эффект
отказа от отдельного запроса под near-tile, не баг — near-tile ~192км
МЕЛЬЧЕ шага европейской сетки 220км, поэтому проекция всегда будет
сглаженной, не точным контуром конкретного облака).

Классификация тёплый/холодный в этой версии ОТСУТСТВУЕТ — для регулярной
статичной сетки без данных о движении системы это отдельная, более
сложная синоптическая задача, отложено.

Логика:
  1. Регулярная (НЕ повёрнутая) lat/lon сетка по объединённому bbox
     far ∪ very_far (см. _europe_grid_bbox) с шагом EUROPE_GRID_STEP_KM.
     266 точек при 220км — с запасом ниже безопасных вживую 300 (см.
     докстринг REQUEST_INTERVAL ниже и docs/topics/open_meteo_rate_limits.md).
  2. Один batch-запрос на модель (5 моделей), только current=.
  3. 5 последовательных запросов с паузой REQUEST_INTERVAL между ними —
     ОДИН процесс, БЕЗ отдельного скрипта/гейта (см. разбор реального 429
     07.09.2026 в docs/topics/open_meteo_rate_limits.md — причина была не
     в объёме запросов, а в двух независимых скриптах/ветках, сработавших
     на одно и то же событие одновременно; коллизия структурно невозможна,
     если это один процесс).
  4. Консенсус: точка сетки "фронт-подобна" для модели, если модуль
     градиента temp ИЛИ pressure (между соседними ИНДЕКСАМИ сетки, шаг
     220км, np.gradient) превышает порог. Точка "подтверждена", если ЗА
     проголосовало большинство моделей (>=MIN_MODEL_VOTES из 5).
  5. Проекция на near-tile: билинейная интерполяция consensus_score
     (votes/n_models, непрерывная величина 0..1) с точек европейской
     сетки на NEAR_PROJECTION_GRID_SIDE x NEAR_PROJECTION_GRID_SIDE
     сэмплов внутри near-tile bbox — чистая математика, без сети.
  6. Запуск СОБЫТИЙНЫЙ: только если появился новый прогон хотя бы одной
     из 5 отслеживаемых моделей — сверяется с data/model_runs_history.json.

ВАЖНО про модели: "arpege_europe" — НЕ валидный &models= идентификатор
Open-Meteo. Правильный (подтверждён по реальному рабочему вызову в
update.py и check_model_runs.py) — "meteofrance_arpege_europe".

Пороги подтверждения (EUROPE_TEMP_GRAD_THRESHOLD/EUROPE_PRESSURE_GRAD_
THRESHOLD) — первая прикидка, НЕ откалиброваны по реальным случаям
прохождения фронта. См. docs/topics/frontal_line_stations.md.

Нагрузка на Open-Meteo проверена вживую пользователем через Termux
2026-09-06: 300 точек x 7 параметров x 5 моделей с паузой 30с — все 5
запросов 200 OK. Отдельно подтверждён burst-порог (500-600 точек в одном
запросе без пауз уже ловит 429) — 266 точек далеко от этого порога.

Пишет:
  data/europe_frontal_overlay.json — точки консенсус-детекции с
    пиксельными координатами под снимки far/very_far ("points", как и
    раньше) ПЛЮС [TASK EUROPE_FRONT_LINE_001] "segments" — связные линии
    фронта. [ПЕРЕРАБОТАНО 2026-09-10] Алгоритм извлечения линии — Hessian-
    based ridge extraction (directional NMS вдоль eigenvector(lambda_min)
    Гессиана consensus_score_grid, НЕ вдоль градиента и НЕ через
    diameter-path/recursive remainder — предыдущая версия на diameter-path
    была отклонена GPT review по живым данным, давала "сетку ломаных"
    вместо линий). "points" не убраны — обратная совместимость / fallback
    фронтенда, если segments пуст. См. docs/ai/AI_DISCUSSION.md
    (Proposal v6-v10, APPROVED) — там же полное обоснование математики
    (curvature+anisotropy тест, corner-cut-free связность, junction-
    разбиение без Dijkstra).
  data/eumetsat_near_tile_projection.json — интерполированное поле,
    спроецированное на near-tile (для SVG-слоя на Cloud Mask), НЕ
    затронуто изменениями EUROPE_FRONT_LINE_001 (использует сырой
    votes_grid/n_valid_grid до сегментации).
Запуск: python3 scripts/open_meteo_frontal_confirm.py
"""
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import numpy as np
from PIL import Image

import open_meteo_guard as _om_guard

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
GEO_CONFIG_FILE = os.path.join(DATA_DIR, "geo_config.json")
MODEL_RUNS_HISTORY_FILE = os.path.join(DATA_DIR, "model_runs_history.json")
STATE_FILE = os.path.join(DATA_DIR, "_state_open_meteo_frontal_confirm.json")
VERY_FAR_IMG_FILE = os.path.join(DATA_DIR, "anim", "very_far_geocolour.png")
FAR_IMG_FILE = os.path.join(DATA_DIR, "anim", "far_geocolour.png")
EUROPE_OVERLAY_FILE = os.path.join(DATA_DIR, "europe_frontal_overlay.json")
NEAR_TILE_PROJECTION_FILE = os.path.join(DATA_DIR, "eumetsat_near_tile_projection.json")

EUROPE_GRID_STEP_KM = 220.0
EUROPE_TEMP_GRAD_THRESHOLD = 3.0      # °C НА ШАГ СЕТКИ (220км) — первая
                                       # прикидка, НЕ калибровано.
EUROPE_PRESSURE_GRAD_THRESHOLD = 1.5  # гПа на шаг сетки — тоже не калибровано

# id для &models= -> label в model_runs_history.json (для событийного гейта)
MODELS = [
    ("ecmwf_ifs", "ECMWF IFS"),
    ("icon_eu", "ICON EU"),
    ("meteofrance_arpege_europe", "Arpège"),  # НЕ "arpege_europe" — см. докстринг
    ("ukmo_global_deterministic_10km", "UKMO"),
    ("gfs_global", "GFS"),
]

CURRENT_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "pressure_msl",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation",
]

REQUEST_INTERVAL = 30  # секунд между запросами моделей — проверено вживую 2026-09-06
MIN_MODEL_VOTES = 3    # из 5 — подтверждено

# MIN_SEGMENT_CELLS, RIDGE_ANISOTROPY_RATIO, CURVATURE_EPSILON,
# VECTOR_EPSILON, MIN_ELONGATION_RATIO — см. блок Hessian-based
# ridge extraction ниже (TASK EUROPE_FRONT_LINE_001, Proposal v6-v10).

# Порог consensus_score (votes/n_models) для near-tile проекции —
# соответствует MIN_MODEL_VOTES/5 у "сырых" точек европейской сетки, тот
# же порог применяем к ИНТЕРПОЛИРОВАННОМУ значению.
NEAR_PROJECTION_THRESHOLD = MIN_MODEL_VOTES / 5.0
NEAR_PROJECTION_GRID_SIDE = 20  # 20x20 сэмплов по near-tile (400x400px) —
                                 # сглаженная проекция, НЕ точный контур
                                 # конкретного облака (того больше нет,
                                 # см. докстринг файла).


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _latest_run_times():
    """{label: run_time} — последняя запись по каждой из 5 отслеживаемых
    моделей из model_runs_history.json (список записей на label, берём
    последнюю)."""
    history = _load_json(MODEL_RUNS_HISTORY_FILE, {})
    out = {}
    for _model_id, label in MODELS:
        entries = history.get(label)
        if entries:
            out[label] = entries[-1].get("run_time")
    return out


def _has_new_model_run(state):
    """Событийный гейт: True, если хотя бы у одной из 5 моделей run_time
    новее того, что сохранён в state с прошлого прогона."""
    latest = _latest_run_times()
    prev = state.get("last_run_times", {})
    for label, run_time in latest.items():
        if run_time and run_time != prev.get(label):
            return True, latest
    return False, latest


def fetch_model_batch(model_id, flat_points, timeout=30, _retry=True):
    """Один batch-запрос current= для ВСЕХ точек пула. Ретрай 1 раз на
    HTTP 429 (см. Retry-After) — та же логика, что open_meteo_field_fetch.py."""
    lats = ",".join(str(p["lat"]) for p in flat_points)
    lons = ",".join(str(p["lon"]) for p in flat_points)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        f"&current={','.join(CURRENT_VARIABLES)}"
        f"&models={model_id}&wind_speed_unit=ms&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-odessa-frontal-confirm/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and _retry:
            wait_s = 5
            try:
                wait_s = int(e.headers.get("Retry-After", "5"))
            except (TypeError, ValueError):
                pass
            time.sleep(min(wait_s, 30))
            return fetch_model_batch(model_id, flat_points, timeout=timeout, _retry=False)
        raise
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        cur = (d or {}).get("current") or {}
        out.append({v: cur.get(v) for v in CURRENT_VARIABLES})
    return out


def _europe_grid_bbox(geo):
    """Объединённый bbox far ∪ very_far (Атлантика-Кавказ, см. разбор в
    чате 2026-09-08: -10..44°E, 33..60°N). far_window задан через
    half_window_deg вокруг Одессы (симметрично), very_far_window — явный
    несимметричный bbox (запад/юго-запад Европы) — берём объединение
    обеих рамок, а не одну."""
    center_lat, center_lon = geo.get("center_lat"), geo.get("center_lon")
    far_half = (geo.get("far_window") or {}).get("half_window_deg")
    vf_bbox = (geo.get("very_far_window") or {}).get("bbox")
    if center_lat is None or center_lon is None or far_half is None or not vf_bbox:
        return None
    far_min_lon, far_min_lat = center_lon - far_half, center_lat - far_half
    far_max_lon, far_max_lat = center_lon + far_half, center_lat + far_half
    vf_min_lon, vf_min_lat, vf_max_lon, vf_max_lat = vf_bbox
    return (
        min(far_min_lon, vf_min_lon), min(far_min_lat, vf_min_lat),
        max(far_max_lon, vf_max_lon), max(far_max_lat, vf_max_lat),
    )


def build_europe_grid(bbox, step_km=EUROPE_GRID_STEP_KM):
    """Регулярная (НЕ повёрнутая, в отличие от убранной near/west
    candidate-сетки) lat/lon сетка по bbox с шагом step_km. Строки — с
    севера на юг (как у растровых снимков), чтобы reshape(rows,cols)
    сразу давал массив в привычной для np.gradient/картинок ориентации.
    Возвращает lats/lons ОТДЕЛЬНО (не только внутри points) — нужны
    project_to_near_tile() для билинейной интерполяции."""
    min_lon, min_lat, max_lon, max_lat = bbox
    center_lat = (min_lat + max_lat) / 2.0
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))
    km_per_deg_lat = 111.32
    width_km = (max_lon - min_lon) * km_per_deg_lon
    height_km = (max_lat - min_lat) * km_per_deg_lat
    cols = max(int(width_km / step_km) + 1, 2)
    rows = max(int(height_km / step_km) + 1, 2)
    lons = [min_lon + i * (max_lon - min_lon) / (cols - 1) for i in range(cols)]
    lats = [max_lat - i * (max_lat - min_lat) / (rows - 1) for i in range(rows)]
    # [ИСПРАВЛЕНО 2026-09-09] Реальная причина сбоя 08.09 (изначально
    # принятого за 429) — БЕЗ round() каждое значение lat/lon отдаёт
    # полную точность float (до 17 значащих цифр, напр. "46.44060000000001"),
    # а fetch_model_batch склеивает ВСЕ 266 точек в одну строку через
    # запятую для &latitude=/&longitude= — без округления это ~8900
    # символов только на координаты, сервер Open-Meteo отвечает HTTP 414
    # "Request-URI Too Large" (см. живой лог: 4 из 5 моделей упали именно
    # с 414, не 429 — это НЕ связано с частотой запросов, чистая длина URL).
    # round(...,3) — точность ~111м, с огромным запасом для сетки с шагом
    # 220км — даёт ~3600 символов, далеко от типичных лимитов на длину URL.
    points = [{"lat": round(lat, 3), "lon": round(lon, 3)} for lat in lats for lon in lons]
    return points, rows, cols, lats, lons


def detect_europe_fronts(model_results_by_id, rows, cols):
    """Консенсус-детекция по регулярной сетке — кандидатов заранее нет
    вообще, ищем сами по полю градиента. Сознательно упрощённо: только
    temp+pressure, БЕЗ классификации тёплый/холодный (см. докстринг
    файла).

    [ПЕРЕРАБОТАНО 2026-09-09, TASK EUROPE_FRONT_LINE_001] Раньше был
    только votes_grid (bool front_like на модель, OR по порогам). Теперь
    дополнительно считается consensus_score_grid — непрерывное поле,
    median() нормированного score ПО ВСЕМ ВАЛИДНЫМ МОДЕЛЯМ в ячейке (не
    только по тем, что проголосовали "front_like") — так решил GPT
    review (docs/ai/AI_DISCUSSION.md, Proposal v3 п.1, APPROVED): не
    терять информацию, ограничиваясь только моделями, прошедшими порог.
    votes_grid/confirmed — гейт подтверждения, семантика НЕ изменилась
    (score > 1.0 эквивалентно старому grad_t > T OR grad_p > P, т.к.
    score = max(grad_t/T, grad_p/P))."""
    votes_grid = np.zeros((rows, cols), dtype=int)
    n_valid_grid = np.zeros((rows, cols), dtype=int)
    score_stack = []  # список (rows,cols) массивов, по одному на модель, NaN где невалидно
    for model_id, results in model_results_by_id.items():
        if len(results) != rows * cols:
            continue
        temp_vals = [r.get("temperature_2m") for r in results]
        pres_vals = [r.get("pressure_msl") for r in results]
        temp_arr = np.array(temp_vals, dtype=float).reshape(rows, cols)
        pres_arr = np.array(pres_vals, dtype=float).reshape(rows, cols)
        valid = ~np.isnan(temp_arr) & ~np.isnan(pres_arr)
        n_valid_grid += valid.astype(int)
        gy_t, gx_t = np.gradient(temp_arr)
        grad_t = np.sqrt(gx_t ** 2 + gy_t ** 2)
        gy_p, gx_p = np.gradient(pres_arr)
        grad_p = np.sqrt(gx_p ** 2 + gy_p ** 2)
        score = np.maximum(grad_t / EUROPE_TEMP_GRAD_THRESHOLD, grad_p / EUROPE_PRESSURE_GRAD_THRESHOLD)
        score = np.where(valid, score, np.nan)
        front_like = (score > 1.0) & valid  # эквивалент старого OR-условия по порогам
        votes_grid += front_like.astype(int)
        score_stack.append(score)
    confirmed = (votes_grid >= MIN_MODEL_VOTES) & (n_valid_grid >= MIN_MODEL_VOTES)
    if score_stack:
        stacked = np.stack(score_stack, axis=0)
        with np.errstate(invalid="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)  # nanmedian на all-NaN срезе — ожидаемо в ячейках без валидных моделей
                consensus_score_grid = np.nanmedian(stacked, axis=0)
    else:
        consensus_score_grid = np.full((rows, cols), np.nan)
    return votes_grid, n_valid_grid, confirmed, consensus_score_grid


_NEIGHBOR_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

# [TASK EUROPE_FRONT_LINE_001, ПЕРЕРАБОТАНО 2026-09-10] Полная замена
# сегментации: recursive diameter-path decomposition (Proposal v2/v3)
# была ОТКЛОНЕНА GPT по итогам живого прогона (docs/ai/AI_DISCUSSION.md,
# implementation review REQUEST CHANGES) — на реальных данных давала
# "сетку ломаных" вместо осмысленных линий, т.к. диаметр графа честно
# находится, но на СЫРОМ широком confirmed-blob'е, а рекурсивная обработка
# остатка снова и снова резала широкую область на диаметры.
#
# Новый pipeline (Proposal v6-v10, APPROVED):
#   consensus_score_grid
#       -> Фаза 1: Hessian-based ridge extraction (директ. NMS вдоль
#          eigenvector(lambda_min), НЕ вдоль градиента — см. п.1)
#       -> Фаза 2: связность по ridge-маске через ЕДИНЫЙ
#          corner-cut-free neighbor helper (_valid_ridge_neighbors)
#       -> Фаза 3: классификация компонента (простая линия / цикл /
#          junction-разбиение на макс. простые пути) — БЕЗ recursive
#          remainder decomposition
#       -> Фаза 4: прямой детерминированный обход (endpoint->endpoint
#          или вокруг цикла) — БЕЗ Dijkstra/diameter, т.к. граф после
#          Фазы 1 уже тонкий по построению
#
# Все константы ниже — эмпирические, калибруются под ЭТУ сетку
# (~220 км, bbox ~30-60°N), не выводятся из физических единиц (см.
# Proposal v10 п.1 — index-space Hessian это осознанная grid-space
# эвристика, а не физически метрический Гессиан).
CURVATURE_EPSILON = 1e-3        # порог "есть ли вообще кривизна" (ridge/peak vs flat plateau)
RIDGE_ANISOTROPY_RATIO = 0.5    # |lambda_max|/|lambda_min| <= это -> "вытянуто" (ridge), не "круг" (peak)
VECTOR_EPSILON = 1e-9           # numerical guard нормировки eigenvector (Proposal v7/v9)
MIN_SEGMENT_CELLS = 3           # финальный сегмент короче — не публикуется, остаётся в points
MIN_ELONGATION_RATIO = 1.5      # [Proposal v9 п.4] пост-хок geometry guard ПОСЛЕ topology,
                                 # эмпирическая страховка, а не мат. доказательство отсутствия
                                 # ложно прошедшего изотропного пика


def _bilinear_sample(grid, row, col, rows, cols):
    """Билинейная интерполяция значения grid в дробной позиции (row, col).
    None, если позиция вне сетки ИЛИ хотя бы один из 4 опорных углов NaN
    — тогда directional NMS в этом направлении корректно не вычислим
    (граница данных), см. Proposal v9 п.3 (явный NaN-гард)."""
    if row < 0 or row > rows - 1 or col < 0 or col > cols - 1:
        return None
    r0 = int(math.floor(row))
    c0 = int(math.floor(col))
    r1 = min(r0 + 1, rows - 1)
    c1 = min(c0 + 1, cols - 1)
    fr = row - r0
    fc = col - c0
    corners = (grid[r0, c0], grid[r0, c1], grid[r1, c0], grid[r1, c1])
    if any(math.isnan(v) for v in corners):
        return None
    top = grid[r0, c0] * (1 - fc) + grid[r0, c1] * fc
    bot = grid[r1, c0] * (1 - fc) + grid[r1, c1] * fc
    return top * (1 - fr) + bot * fr


def _ridge_mask(score, confirmed, rows, cols):
    """[Фаза 1, Proposal v6-v10, APPROVED] Hessian-based ridge detection.

    Направление NMS берётся из eigenvector(lambda_min) Гессиана поля
    score, а НЕ из градиента — градиент вырождается ровно на вершине
    ridge (пример из review: "1 2 3 4 5 4 3 2 1", в точке 5 первая
    производная = 0, но вторая производная сильно отрицательна), поэтому
    градиент-based направление ошибочно отправляло настоящие вершины
    ridge в plateau-fallback.

    Ridge-условие СТРОГО ПОСЛЕДОВАТЕЛЬНОЕ (Proposal v10 п.2 — знак
    lambda_min принципиален, проверяется первым):
      1) lambda_min < -CURVATURE_EPSILON  (есть выраженная вогнутость;
         lambda_min > 0 дисквалифицирует НЕМЕДЛЕННО, ratio не считается)
      2) |lambda_max| / |lambda_min| <= RIDGE_ANISOTROPY_RATIO
         (вытянутость, а не изотропный peak/blob — Proposal v7,
         разрешает review-пример "1 2 1 / 2 5 2 / 1 2 1" отклонить, т.к.
         там lambda_min≈lambda_max, ratio≈1)
      3) score — локальный максимум вдоль eigenvector(lambda_min)
         (билинейная интерполяция на +-1 шаг, асимметричный tie-break
         `>` назад / `>=` вперёд — детерминированное утончение даже при
         точных совпадениях на плато вдоль самой линии)

    Гессиан считается в INDEX SPACE — детерминированная grid-space
    эвристика для этой конкретной сетки, СОЗНАТЕЛЬНОЕ ограничение v1
    (Proposal v10 п.1), не физически метрический Гессиан; все три
    константы выше калибруются эмпирически под эту сетку.

    NaN в любом из H_rr/H_cc/H_rc (край сетки, невалидные соседи из-за
    отсутствия моделей) -> явный isnan-гард -> ячейка NOT ridge
    (Proposal v9 п.3), не полагаемся на случайное поведение сравнений
    с NaN."""
    d_row, d_col = np.gradient(score)
    H_rr, H_rc_a = np.gradient(d_row)
    H_cr_b, H_cc = np.gradient(d_col)
    H_rc = (H_rc_a + H_cr_b) / 2.0

    ridge = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            if not confirmed[r, c]:
                continue
            hrr, hrc, hcc = float(H_rr[r, c]), float(H_rc[r, c]), float(H_cc[r, c])
            if math.isnan(hrr) or math.isnan(hrc) or math.isnan(hcc):
                continue
            trace = hrr + hcc
            disc = math.sqrt(max(0.0, ((hrr - hcc) / 2.0) ** 2 + hrc ** 2))
            lambda_min = trace / 2.0 - disc
            lambda_max = trace / 2.0 + disc
            # условие 1 — знак и порог lambda_min ОБЯЗАТЕЛЬНЫ первыми
            if not (lambda_min < -CURVATURE_EPSILON):
                continue
            # условие 2 — anisotropy ratio, ТОЛЬКО после условия 1
            if abs(lambda_max) > RIDGE_ANISOTROPY_RATIO * abs(lambda_min):
                continue
            # eigenvector(lambda_min) = (v_row, v_col), с fallback по норме
            v_row, v_col = hrc, lambda_min - hrr
            norm = math.sqrt(v_row * v_row + v_col * v_col)
            if norm < VECTOR_EPSILON:
                if hrr <= hcc:
                    v_row, v_col = 1.0, 0.0
                else:
                    v_row, v_col = 0.0, 1.0
            else:
                v_row, v_col = v_row / norm, v_col / norm
            # условие 3 — directional NMS вдоль (v_row, v_col)
            s_here = float(score[r, c])
            s_back = _bilinear_sample(score, r - v_row, c - v_col, rows, cols)
            s_fwd = _bilinear_sample(score, r + v_row, c + v_col, rows, cols)
            if s_back is None or s_fwd is None:
                continue
            if not (s_here > s_back and s_here >= s_fwd):
                continue
            ridge[r, c] = True
    return ridge


def _valid_ridge_neighbors(cell, ridge_mask, confirmed):
    """[Фаза 2, Proposal v5/v7 п.6, APPROVED — уточнено при реализации,
    см. IMPLEMENTED-отчёт] ЕДИНЫЙ источник топологии для ВСЕХ
    последующих шагов (components, degree, traversal, junction split).

    Corner-cut-free: диагональный сосед допустим, только если хотя бы
    одна из двух ортогональных "опорных" ячеек ПОДТВЕРЖДЕНА консенсусом
    (`confirmed`), а не обязательно сама является ridge-точкой.

    [НАЙДЕНО ПРИ ТЕСТИРОВАНИИ, отклонение от буквальной формулировки
    Proposal v5] Изначально опора проверялась по `ridge_mask` (как было
    сформулировано в Proposal). Юнит-тест на чистой диагональной линии
    (`i,i` для всех i) показал: после Фазы 1 ridge-маска УЖЕ тонкая по
    построению — у настоящей однопиксельной диагональной линии по
    определению НЕТ соседей-опор, которые сами были бы ridge-точками
    (иначе линия не была бы тонкой). Проверка опоры по `ridge_mask`
    ошибочно рвала любую диагональную линию на N изолированных
    компонент по 1 ячейке. Проверка по `confirmed` (широкий гейт ДО
    утончения) сохраняет исходный смысл правила — не позволять двум
    объектам, действительно не связанным физически (например, через
    вогнутый угол L-образной области, где опорные ячейки лежат вне
    confirmed-области вообще), соединяться по диагонали — но больше не
    мешает честной тонкой диагональной линии, у которой опорные ячейки
    физически рядом confirmed, просто сами не стали ridge-максимumом
    после утончения."""
    r, c = cell
    rows, cols = ridge_mask.shape
    neighbors = []
    for dr, dc in _NEIGHBOR_OFFSETS:
        nr, nc = r + dr, c + dc
        if not (0 <= nr < rows and 0 <= nc < cols):
            continue
        if not ridge_mask[nr, nc]:
            continue
        if dr != 0 and dc != 0 and not (confirmed[r, nc] or confirmed[nr, c]):
            continue  # diagonal corner-cut без confirmed-опоры — запрещено
        neighbors.append((nr, nc))
    return neighbors


def _ridge_components(ridge_mask, confirmed):
    """[Фаза 2] BFS по ridge-маске через _valid_ridge_neighbors."""
    rows, cols = ridge_mask.shape
    visited = np.zeros_like(ridge_mask, dtype=bool)
    components = []
    for r in range(rows):
        for c in range(cols):
            if ridge_mask[r, c] and not visited[r, c]:
                stack = [(r, c)]
                visited[r, c] = True
                comp = set()
                while stack:
                    cell = stack.pop()
                    comp.add(cell)
                    for nb in _valid_ridge_neighbors(cell, ridge_mask, confirmed):
                        if not visited[nb]:
                            visited[nb] = True
                            stack.append(nb)
                components.append(comp)
    return components


def _classify_and_order_component(comp, ridge_mask, confirmed):
    """[Фаза 3+4, Proposal v5/v10, APPROVED] БЕЗ Dijkstra/diameter —
    прямой детерминированный обход, т.к. после Фазы 1 граф уже тонкий
    по построению (degree<=2 везде, кроме настоящих junction).

    - Простая линия (ровно endpoints, degree==2 в остальном): обход
      endpoint -> endpoint напрямую.
    - Цикл (degree==2 везде, endpoint нет): обход по кольцу от
      детерминированного старта, останов перед повторным заходом в start.
    - Junction (есть degree>=3): раскладывается на максимальные простые
      пути между вершинами degree!=2. Junction-ячейка МОЖЕТ и будет
      повторяться как общий endpoint нескольких путей — это корректное
      топологическое представление ветвления, НЕ ошибочное дублирование
      (Proposal v5 п.5, APPROVED дословно)."""
    degree = {cell: len(_valid_ridge_neighbors(cell, ridge_mask, confirmed)) for cell in comp}
    junctions = {cell for cell, d in degree.items() if d >= 3}
    endpoints = {cell for cell, d in degree.items() if d <= 1}

    if junctions:
        special = junctions | endpoints
        visited_edges = set()
        paths = []
        for s in sorted(special):
            for nb in sorted(_valid_ridge_neighbors(s, ridge_mask, confirmed)):
                edge = frozenset((s, nb))
                if edge in visited_edges:
                    continue
                visited_edges.add(edge)
                path = [s, nb]
                prev, cur = s, nb
                while cur not in special:
                    nbs = [n for n in _valid_ridge_neighbors(cur, ridge_mask, confirmed) if n != prev]
                    if not nbs:
                        break
                    prev, cur = cur, nbs[0]
                    path.append(cur)
                    visited_edges.add(frozenset((path[-2], path[-1])))
                paths.append(path)
        return paths

    if not endpoints:
        # чистый цикл: degree==2 у всех вершин
        start = min(comp)
        nbs_start = sorted(_valid_ridge_neighbors(start, ridge_mask, confirmed))
        if not nbs_start:
            return [[start]]  # вырожденный случай (не должен происходить у настоящего цикла)
        path = [start]
        prev, cur = start, nbs_start[0]
        while cur != start:
            path.append(cur)
            nbs = [n for n in _valid_ridge_neighbors(cur, ridge_mask, confirmed) if n != prev]
            if not nbs:
                break  # защита от неожиданной разомкнутости
            prev, cur = cur, nbs[0]
        return [path]

    # простая линия: endpoints (degree<=1), остальные degree==2
    start = min(endpoints)
    path = [start]
    prev, cur = None, start
    while True:
        nbs = [n for n in _valid_ridge_neighbors(cur, ridge_mask, confirmed) if n != prev]
        if not nbs:
            break
        prev, cur = cur, nbs[0]
        path.append(cur)
    return [path]


SPREAD_EPSILON = 1e-9  # guard деления на ~0 в _elongation_ratio (идеально прямая линия)


def _elongation_ratio(path):
    """[Proposal v9 п.4, УТОЧНЕНО ПРИ РЕАЛИЗАЦИИ — см. IMPLEMENTED-отчёт]
    Изначально guard был сформулирован как `bbox_h/bbox_w`. Юнит-тест на
    чистой 45°-диагональной линии показал: у диагонали `bbox_h == bbox_w`
    (квадратный bbox) НЕЗАВИСИМО от длины линии — naive bbox-ratio
    ошибочно отклонял любую диагональную/повёрнутую линию как "неvytянутую".

    Заменено на ориентационно-независимую меру: собственные значения
    ковариационной матрицы координат точек пути (тот же приём 2×2
    eigen-decomposition, что и в Фазе 1, применённый здесь не к Гессиану
    поля, а к разбросу самих точек). `spread_max`/`spread_min` — дисперсия
    вдоль главной оси облака точек и поперёк неё, не зависят от того, как
    именно линия расположена относительно сетки (диагональ, горизонталь,
    любой другой угол — считается корректно одинаково).

    Возвращает "линейное" отношение `sqrt(spread_max/spread_min)`
    (приведено к линейному масштабу, а не к масштабу дисперсии, чтобы
    порог `MIN_ELONGATION_RATIO=1.5` сохранял тот же смысл, что и в
    исходной bbox-формулировке — "во сколько раз линия длиннее, чем
    широкая"). `inf`, если `spread_min ~ 0` (идеально прямая линия без
    поперечного разброса вообще — максимально вытянуто по определению)."""
    if len(path) < 2:
        return 0.0
    rs = [p[0] for p in path]
    cs = [p[1] for p in path]
    mean_r = sum(rs) / len(rs)
    mean_c = sum(cs) / len(cs)
    s_rr = sum((r - mean_r) ** 2 for r in rs) / len(rs)
    s_cc = sum((c - mean_c) ** 2 for c in cs) / len(cs)
    s_rc = sum((r - mean_r) * (c - mean_c) for r, c in zip(rs, cs)) / len(rs)
    trace = s_rr + s_cc
    disc = math.sqrt(max(0.0, ((s_rr - s_cc) / 2.0) ** 2 + s_rc ** 2))
    spread_max = trace / 2.0 + disc
    spread_min = trace / 2.0 - disc
    if spread_min < SPREAD_EPSILON:
        return float("inf")
    return math.sqrt(spread_max / spread_min)


def extract_europe_segments(consensus_score_grid, confirmed, lats, lons,
                             min_cells=MIN_SEGMENT_CELLS, min_elongation=MIN_ELONGATION_RATIO):
    """Точка входа Фаз 1-4. Возвращает (segments, n_components, n_ridge_cells)
    — последние два для диагностики (запрошено GPT review)."""
    rows, cols = confirmed.shape
    ridge_mask = _ridge_mask(consensus_score_grid, confirmed, rows, cols)
    n_ridge_cells = int(ridge_mask.sum())
    components = _ridge_components(ridge_mask, confirmed)

    raw_paths = []
    for comp in components:
        raw_paths.extend(_classify_and_order_component(comp, ridge_mask, confirmed))

    segments = []
    for path in raw_paths:
        if len(path) < min_cells:
            continue
        if _elongation_ratio(path) < min_elongation:
            continue  # [Proposal v9 п.4] эмпирический guard, не мат. доказательство
        scores = [consensus_score_grid[r, c] for (r, c) in path if not math.isnan(consensus_score_grid[r, c])]
        avg_score = round(float(np.mean(scores)), 2) if scores else None
        seg_path = [{"lat": round(float(lats[r]), 3), "lon": round(float(lons[c]), 3)} for (r, c) in path]
        segments.append({
            "n_cells": len(path),
            "path_length": len(path),
            "avg_score": avg_score,
            "path": seg_path,
        })
    return segments, len(components), n_ridge_cells


def _far_bboxes(geo):
    """Общий helper для far/very_far bbox+wh — используется и
    _build_europe_overlay (points), и _attach_pixel_coords_to_segments
    (segments), чтобы не дублировать/не рассинхронизировать логику
    проекции lon/lat -> px между ними (см. AI_DISCUSSION Proposal v3 п.4,
    APPROVED)."""
    far_bbox = far_wh = very_far_bbox = very_far_wh = None
    try:
        far_half = geo["far_window"]["half_window_deg"]
        far_bbox = (geo["center_lon"] - far_half, geo["center_lat"] - far_half,
                    geo["center_lon"] + far_half, geo["center_lat"] + far_half)
        if os.path.exists(FAR_IMG_FILE):
            far_wh = Image.open(FAR_IMG_FILE).size
    except Exception:
        pass
    try:
        very_far_bbox = tuple(geo["very_far_window"]["bbox"])
        if os.path.exists(VERY_FAR_IMG_FILE):
            very_far_wh = Image.open(VERY_FAR_IMG_FILE).size
    except Exception:
        pass
    return far_bbox, far_wh, very_far_bbox, very_far_wh


def _attach_pixel_coords_to_segments(segments, geo):
    """Добавляет px_far/px_very_far к каждой точке path сегмента — той
    же _lonlat_to_px, что и у points (см. _far_bboxes)."""
    far_bbox, far_wh, very_far_bbox, very_far_wh = _far_bboxes(geo)
    out = []
    for seg in segments:
        new_path = []
        for pt in seg["path"]:
            lat, lon = pt["lat"], pt["lon"]
            px_far = _lonlat_to_px(lon, lat, far_bbox, far_wh)
            px_very_far = _lonlat_to_px(lon, lat, very_far_bbox, very_far_wh)
            new_path.append({"lat": lat, "lon": lon, "px_far": px_far, "px_very_far": px_very_far})
        out.append({k: v for k, v in seg.items() if k != "path"} | {"path": new_path})
    return out, far_wh, very_far_wh


def _lonlat_to_px(lon, lat, bbox, wh):
    """Проекция lon/lat в пиксели снимка по его собственному bbox+размеру."""
    if not bbox or not wh:
        return None
    min_lon, min_lat, max_lon, max_lat = bbox
    w, h = wh
    col = (lon - min_lon) / (max_lon - min_lon) * w - 0.5
    row = (max_lat - lat) / (max_lat - min_lat) * h - 0.5
    if 0 <= row < h and 0 <= col < w:
        return [round(col, 1), round(row, 1)]
    return None


def _build_europe_overlay(points_meta, votes_grid, n_valid_grid, confirmed, geo):
    """Векторные данные для SVG-слоя с тумблером на снимках far/very_far.
    Каждая точка — с пиксельными координатами СРАЗУ на ОБОИХ снимках, т.к.
    объединённый bbox шире каждого из них по отдельности — точка может
    попасть в один, другой, оба или ни один (за кадром)."""
    far_bbox, far_wh, very_far_bbox, very_far_wh = _far_bboxes(geo)

    rows, cols = votes_grid.shape
    out_points = []
    for i in range(rows):
        for j in range(cols):
            if n_valid_grid[i, j] < MIN_MODEL_VOTES:
                continue  # недостаточно моделей ответили в этой точке — не публикуем вообще
            meta = points_meta[i * cols + j]
            lat, lon = meta["lat"], meta["lon"]
            px_far = _lonlat_to_px(lon, lat, far_bbox, far_wh)
            px_very_far = _lonlat_to_px(lon, lat, very_far_bbox, very_far_wh)
            if px_far is None and px_very_far is None:
                continue
            out_points.append({
                "lat": round(lat, 3), "lon": round(lon, 3),
                "votes": int(votes_grid[i, j]), "n_models": int(n_valid_grid[i, j]),
                "confirmed": bool(confirmed[i, j]),
                "px_far": px_far, "px_very_far": px_very_far,
            })
    return out_points, far_wh, very_far_wh


def _bilinear_interp(lats, lons, field, lat, lon):
    """Билинейная интерполяция непрерывного поля field[row][col] (та же
    ориентация, что у lats — убывает, север->юг — и lons — возрастает) в
    произвольной точке (lat,lon). None, если точка вне покрытия сетки ИЛИ
    среди 4 соседей есть NaN (недостаточно моделей ответило в этой ячейке
    европейской сетки)."""
    if lat > lats[0] or lat < lats[-1] or lon < lons[0] or lon > lons[-1]:
        return None
    i = 0
    while i < len(lats) - 2 and lats[i + 1] > lat:
        i += 1
    j = 0
    while j < len(lons) - 2 and lons[j + 1] < lon:
        j += 1
    lat0, lat1 = lats[i], lats[i + 1]
    lon0, lon1 = lons[j], lons[j + 1]
    tx = (lon - lon0) / (lon1 - lon0) if lon1 != lon0 else 0.0
    ty = (lat0 - lat) / (lat0 - lat1) if lat0 != lat1 else 0.0
    v00, v01, v10, v11 = field[i][j], field[i][j + 1], field[i + 1][j], field[i + 1][j + 1]
    if any(v is None or math.isnan(v) for v in (v00, v01, v10, v11)):
        return None
    top = v00 + tx * (v01 - v00)
    bot = v10 + tx * (v11 - v10)
    return top + ty * (bot - top)


def project_to_near_tile(lats, lons, votes_grid, n_valid_grid, geo):
    """[ДОБАВЛЕНО 2026-09-09] Проекция европейской сетки на near-tile —
    ЗАМЕНА убранного near/west-детектора (см. докстринг файла целиком).
    НИКАКИХ новых запросов к Open-Meteo — чистая интерполяция уже
    посчитанного consensus_score = votes/n_models с точек европейской
    сетки на NEAR_PROJECTION_GRID_SIDE x NEAR_PROJECTION_GRID_SIDE
    сэмплов внутри near-tile bbox."""
    mw = geo.get("motion_window") or {}
    half = mw.get("half_window_deg")
    center_lat, center_lon = geo.get("center_lat"), geo.get("center_lon")
    if half is None or center_lat is None or center_lon is None:
        return None
    near_bbox = (center_lon - half, center_lat - half, center_lon + half, center_lat + half)
    tile_size = mw.get("tile_size", 400)

    score_field = []
    for i in range(len(lats)):
        row = []
        for j in range(len(lons)):
            n = n_valid_grid[i, j]
            row.append((votes_grid[i, j] / n) if n >= MIN_MODEL_VOTES else float("nan"))
        score_field.append(row)

    side = NEAR_PROJECTION_GRID_SIDE
    min_lon, min_lat, max_lon, max_lat = near_bbox
    cells = []
    for gi in range(side):
        for gj in range(side):
            lat = max_lat - (gi + 0.5) * (max_lat - min_lat) / side
            lon = min_lon + (gj + 0.5) * (max_lon - min_lon) / side
            score = _bilinear_interp(lats, lons, score_field, lat, lon)
            if score is None:
                continue
            px_x = (gj + 0.5) * tile_size / side
            px_y = (gi + 0.5) * tile_size / side
            cell_size = tile_size / side
            cells.append({
                "px": [round(px_x, 1), round(px_y, 1)],
                "size": round(cell_size, 1),
                "score": round(float(score), 2),
                "confirmed": bool(score >= NEAR_PROJECTION_THRESHOLD),
            })
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tile_size": tile_size,
        "grid_side": side,
        "cells": cells,
    }


def run_europe_detection(geo):
    """Единственный детектор (см. докстринг файла) — 5 запросов, пауза
    30с, событийный гейт проверяется в main()."""
    bbox = _europe_grid_bbox(geo)
    if not bbox:
        print("  [WARN] open_meteo_frontal_confirm: bbox не построен (far_window/very_far_window)")
        return
    points, rows, cols, lats, lons = build_europe_grid(bbox)
    print(f"  open_meteo_frontal_confirm: сетка {rows}x{cols}={rows*cols} точек, шаг {EUROPE_GRID_STEP_KM}км")

    model_results_by_id = {}
    if _om_guard.gate(probe_owner=False) == "skip":
        print("  [INFO] open_meteo_frontal_confirm: Open-Meteo cooldown активен — пропуск")
    else:
        for i, (model_id, _label) in enumerate(MODELS):
            try:
                model_results_by_id[model_id] = fetch_model_batch(model_id, points)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    _om_guard.record_429()
                    print(f"  [WARN] open_meteo_frontal_confirm: {model_id}: HTTP 429 — cooldown зафиксирован, останавливаю перебор моделей")
                    break
                print(f"  [WARN] open_meteo_frontal_confirm: модель {model_id}: {e}")
            except Exception as e:
                print(f"  [WARN] open_meteo_frontal_confirm: модель {model_id}: {e}")
            if i < len(MODELS) - 1:
                time.sleep(REQUEST_INTERVAL)

    votes_grid, n_valid_grid, confirmed, consensus_score_grid = detect_europe_fronts(model_results_by_id, rows, cols)
    overlay_points, far_wh, very_far_wh = _build_europe_overlay(points, votes_grid, n_valid_grid, confirmed, geo)

    # [TASK EUROPE_FRONT_LINE_001, ПЕРЕРАБОТАНО 2026-09-10] Hessian-based
    # ridge extraction (см. docs/ai/AI_DISCUSSION.md, Proposal v6-v10,
    # APPROVED) — заменяет отклонённый на живых данных recursive
    # diameter-path (Proposal v2/v3, дал "сетку ломаных" вместо линий).
    # "points" НЕ убирается (обратная совместимость / fallback фронтенда).
    raw_segments, n_components, n_ridge_cells = extract_europe_segments(consensus_score_grid, confirmed, lats, lons)
    segments, _far_wh2, _very_far_wh2 = _attach_pixel_coords_to_segments(raw_segments, geo)

    _save_json(EUROPE_OVERLAY_FILE, {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bbox": list(bbox),
        "step_km": EUROPE_GRID_STEP_KM,
        "far_wh": list(far_wh) if far_wh else None,
        "very_far_wh": list(very_far_wh) if very_far_wh else None,
        "points": overlay_points,
        "segments": segments,
    })
    n_confirmed = sum(1 for p in overlay_points if p["confirmed"])
    print(f"  [OK] open_meteo_frontal_confirm: {n_confirmed}/{len(overlay_points)} точек подтверждено консенсусом")
    # Диагностика по запросу GPT review (docs/ai/AI_DISCUSSION.md,
    # Proposal v10/APPROVED + implementation review requirement):
    # confirmed cells / ridge cells / connected components / итоговые
    # segments / длина каждого.
    seg_lengths = [s["path_length"] for s in segments]
    print(f"  [OK] open_meteo_frontal_confirm: confirmed_cells={n_confirmed} ridge_cells={n_ridge_cells} "
          f"components={n_components} segments={len(segments)} lengths={seg_lengths}")

    projection = project_to_near_tile(lats, lons, votes_grid, n_valid_grid, geo)
    if projection is not None:
        _save_json(NEAR_TILE_PROJECTION_FILE, projection)
        n_proj_confirmed = sum(1 for c in projection["cells"] if c["confirmed"])
        print(f"  [OK] open_meteo_frontal_confirm: near-tile проекция — {n_proj_confirmed}/{len(projection['cells'])} ячеек подтверждено")


def main():
    state = _load_json(STATE_FILE, {})
    has_new_run, latest_run_times = _has_new_model_run(state)
    if not has_new_run:
        print("  [SKIP] open_meteo_frontal_confirm: нет нового прогона моделей с прошлой проверки")
        return

    geo = _load_json(GEO_CONFIG_FILE, {})
    if geo.get("center_lat") is None or geo.get("center_lon") is None:
        print("  [WARN] open_meteo_frontal_confirm: geo_config.json без center_lat/center_lon")
        return

    run_europe_detection(geo)

    state["last_run_times"] = latest_run_times
    _save_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
