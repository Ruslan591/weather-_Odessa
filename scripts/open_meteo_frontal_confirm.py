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
    раньше) ПЛЮС [ДОБАВЛЕНО 2026-09-09, TASK EUROPE_FRONT_LINE_001]
    "segments" — связные линии фронта, извлечённые через diameter-path
    (double Dijkstra) из connected components confirmed-ячеек, с
    рекурсивным junction-разбиением на боковые ветви. "points" не
    убраны — обратная совместимость / fallback фронтенда, если
    segments пуст. См. docs/ai/AI_DISCUSSION.md (Proposal v2/v3,
    APPROVED) — там же обоснование, почему NOT NMS+PCA, а diameter-path.
  data/eumetsat_near_tile_projection.json — интерполированное поле,
    спроецированное на near-tile (для SVG-слоя на Cloud Mask), НЕ
    затронуто изменениями EUROPE_FRONT_LINE_001 (использует сырой
    votes_grid/n_valid_grid до сегментации).
Запуск: python3 scripts/open_meteo_frontal_confirm.py
"""
import heapq
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import numpy as np
from PIL import Image

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

# [ДОБАВЛЕНО 2026-09-09, TASK EUROPE_FRONT_LINE_001] Минимальный размер
# connected component (8-связность по confirmed-ячейкам), чтобы из него
# извлекать diameter-path сегмент. Меньшие компоненты остаются видны
# только через "points" (старый point-by-point рендер) — согласовано с
# GPT (docs/ai/AI_DISCUSSION.md, REVIEW: APPROVED).
MIN_COMPONENT_CELLS = 3

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


def _component_cells(confirmed):
    """[TASK EUROPE_FRONT_LINE_001] BFS 8-связность по confirmed grid
    (bool rows x cols). Возвращает список компонент, каждая — set из
    (row, col). Чистый Python/numpy, без scipy (см. AI_DISCUSSION,
    Proposal v2 п. "не требует scipy")."""
    rows, cols = confirmed.shape
    visited = np.zeros_like(confirmed, dtype=bool)
    components = []
    for r in range(rows):
        for c in range(cols):
            if confirmed[r, c] and not visited[r, c]:
                stack = [(r, c)]
                visited[r, c] = True
                comp = set()
                while stack:
                    cr, cc = stack.pop()
                    comp.add((cr, cc))
                    for dr, dc in _NEIGHBOR_OFFSETS:
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < rows and 0 <= nc < cols and confirmed[nr, nc] and not visited[nr, nc]:
                            visited[nr, nc] = True
                            stack.append((nr, nc))
                components.append(comp)
    return components


def _subgraph_dijkstra(start, cells_set):
    """Dijkstra по подграфу cells_set (8-связность, вес ребра = евклидово
    расстояние в шагах сетки: 1.0 орто-сосед, sqrt(2) диагональный) —
    heapq из стандартной библиотеки, без scipy. cells_set предполагается
    связным (иначе dist просто не покроет недостижимые узлы — вызывающий
    код гарантирует связность, передавая сюда только компоненты/под-
    компоненты одного BFS-обхода)."""
    dist = {start: 0.0}
    parent = {start: None}
    pq = [(0.0, start)]
    while pq:
        d, node = heapq.heappop(pq)
        if d > dist.get(node, float("inf")):
            continue
        r, c = node
        for dr, dc in _NEIGHBOR_OFFSETS:
            nb = (r + dr, c + dc)
            if nb in cells_set:
                w = math.sqrt(2) if (dr != 0 and dc != 0) else 1.0
                nd = d + w
                if nd < dist.get(nb, float("inf")):
                    dist[nb] = nd
                    parent[nb] = node
                    heapq.heappush(pq, (nd, nb))
    return dist, parent


def _diameter_path(cells_set):
    """[TASK EUROPE_FRONT_LINE_001, AI_DISCUSSION Proposal v2/v3,
    APPROVED] Centerline компонента через "диаметр графа" (double
    Dijkstra) вместо NMS+PCA:
      1) из произвольной ячейки cells_set ищем самую удалённую P1;
      2) из P1 ищем самую удалённую P2, восстанавливаем путь P1->P2 по
         parent-указателям.
    Путь P1->P2 — диаметр графа: не рвёт прямую цепочку соседних ячеек
    (диаметр пути-графа = весь путь) и корректно идёт вдоль изгибов
    (следует реальным рёбрам графа, а не проекции на одну ось, как
    делала бы PCA-сортировка). cells_set непустой и связный (проверяется
    вызывающим кодом через MIN_COMPONENT_CELLS и BFS-происхождение)."""
    start = next(iter(cells_set))
    dist1, _ = _subgraph_dijkstra(start, cells_set)
    p1 = max(dist1, key=dist1.get)
    dist2, parent2 = _subgraph_dijkstra(p1, cells_set)
    p2 = max(dist2, key=dist2.get)
    path = []
    node = p2
    while node is not None:
        path.append(node)
        node = parent2[node]
    path.reverse()
    return path


def _connected_subcomponents(cells):
    """BFS 8-связность внутри произвольного множества ячеек `cells`
    (не обязательно всей сетки) — используется для разбиения "остатка"
    после извлечения diameter-path на отдельные под-компоненты."""
    visited = set()
    out = []
    for cell in cells:
        if cell in visited:
            continue
        stack = [cell]
        visited.add(cell)
        sub = set()
        while stack:
            cr, cc = stack.pop()
            sub.add((cr, cc))
            for dr, dc in _NEIGHBOR_OFFSETS:
                nb = (cr + dr, cc + dc)
                if nb in cells and nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        out.append(sub)
    return out


def _extract_segments_recursive(cells_set, min_cells=MIN_COMPONENT_CELLS):
    """[TASK EUROPE_FRONT_LINE_001, AI_DISCUSSION Proposal v3 п.3,
    APPROVED "с условием защиты от дублирования ячеек между сегментами
    и бесконечной рекурсии"] Извлекает из компонента ГЛАВНЫЙ diameter-
    path, а остаток (ячейки компонента, не попавшие на путь) —
    рекурсивно раскладывает на under-компоненты и обрабатывает каждую
    той же процедурой. Так T-образный/ветвящийся фронт даёт несколько
    сегментов (основная линия + боковые ветви) вместо потери веток.

    Гарантии (проверено юнит-тестом на синтетических сетках, см. commit
    message / AI_DISCUSSION):
      - НЕТ дублирования ячеек между сегментами: remaining = cells_set -
        set(path) — строгая разность множеств, path и remaining
        непересекающиеся по построению; под-компоненты remaining также
        взаимно непересекающиеся (это результат одного BFS-разбиения
        одного множества).
      - НЕТ бесконечной рекурсии: каждый рекурсивный вызов получает
        cells_set строго меньшего размера, чем родительский (т.к.
        len(path) >= 1 всегда вычитается), а базовый случай
        len(cells_set) < min_cells останавливает рекурсию — общее число
        уровней рекурсии ограничено размером исходного компонента."""
    if len(cells_set) < min_cells:
        return []
    path = _diameter_path(cells_set)
    segments = [{"cells": path, "n_cells": len(cells_set)}]
    remaining = cells_set - set(path)
    for sub in _connected_subcomponents(remaining):
        segments.extend(_extract_segments_recursive(sub, min_cells))
    return segments


def extract_europe_segments(confirmed, consensus_score_grid, lats, lons, min_cells=MIN_COMPONENT_CELLS):
    """Точка входа: confirmed grid -> список сегментов с lat/lon (без
    px — пиксели добавляются отдельно в _attach_pixel_coords_to_segments,
    т.к. используют ту же _lonlat_to_px, что и обычные points, и не
    должны дублировать эту логику проекции)."""
    components = _component_cells(confirmed)
    all_segments = []
    for comp in components:
        all_segments.extend(_extract_segments_recursive(comp, min_cells))
    out = []
    for seg in all_segments:
        cells = seg["cells"]
        scores = [consensus_score_grid[r, c] for (r, c) in cells if not math.isnan(consensus_score_grid[r, c])]
        avg_score = round(float(np.mean(scores)), 2) if scores else None
        path = [{"lat": round(float(lats[r]), 3), "lon": round(float(lons[c]), 3)} for (r, c) in cells]
        out.append({
            "n_cells": seg["n_cells"],
            "path_length": len(cells),
            "avg_score": avg_score,
            "path": path,
        })
    return out, len(components)


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
    for i, (model_id, _label) in enumerate(MODELS):
        try:
            model_results_by_id[model_id] = fetch_model_batch(model_id, points)
        except Exception as e:
            print(f"  [WARN] open_meteo_frontal_confirm: модель {model_id}: {e}")
        if i < len(MODELS) - 1:
            time.sleep(REQUEST_INTERVAL)

    votes_grid, n_valid_grid, confirmed, consensus_score_grid = detect_europe_fronts(model_results_by_id, rows, cols)
    overlay_points, far_wh, very_far_wh = _build_europe_overlay(points, votes_grid, n_valid_grid, confirmed, geo)

    # [TASK EUROPE_FRONT_LINE_001] segments — связная линия фронта вместо
    # облака точек (см. docs/ai/AI_DISCUSSION.md, Proposal v3, APPROVED).
    # "points" НЕ убирается (обратная совместимость / fallback фронтенда).
    raw_segments, n_components = extract_europe_segments(confirmed, consensus_score_grid, lats, lons)
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
    # Диагностика по запросу GPT review (docs/ai/AI_DISCUSSION.md, Proposal v3/APPROVED):
    # confirmed cells / connected components / итоговые segments / длина каждого.
    seg_lengths = [s["path_length"] for s in segments]
    print(f"  [OK] open_meteo_frontal_confirm: confirmed_cells={n_confirmed} components={n_components} "
          f"segments={len(segments)} lengths={seg_lengths}")

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
