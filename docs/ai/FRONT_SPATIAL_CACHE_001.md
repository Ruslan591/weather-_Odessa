# TASK: FRONT_SPATIAL_CACHE_001

## Status
APPROVED (Proposal v2) — GPT APPROVE на реализацию получен, при
условии 3 правок из REQUEST CHANGES по v1 (внесены ниже). Код пока НЕ
менялся, коммита в `open_meteo_frontal_confirm.py` не было — это всё
ещё только проектный документ.

## История ревью
- v1: GPT REQUEST CHANGES, 3 пункта:
  1. `new_run_time is None` не должно триггерить fetch само по себе
     (защита от лишних запросов/429, если `model_runs_history.json`
     временно не содержит модель).
  2. Partial cache после смены grid не должен автоматически считаться
     valid для consensus — нужна отдельная freshness/grid-валидация
     на входе в голосование, `MIN_MODEL_VOTES` остаётся единственным
     vote gate.
  3. `grid_id` не должен содержать зашитое `eu220` — сетка может
     измениться в будущем, префикс должен быть общим (`grid_<hash>`).
- v2 (этот документ): все 3 правки внесены — см. п.2, п.5, п.3 ниже.

## Цель
Убрать повторный полный fan-out (5 моделей × ~266 точек) из
`open_meteo_frontal_confirm.py` при каждом run. Сейчас любой запуск
`run_europe_detection()` заново запрашивает spatial grid для ВСЕХ 5
моделей, даже если у большинства run не изменился с прошлого раза.

## Модели (не меняются)
`ecmwf_ifs`, `icon_eu`, `meteofrance_arpege_world`,
`ukmo_global_deterministic_10km`, `gfs_global`.

## Ограничения задачи (входные, не подлежат обсуждению на этом этапе)
- Consensus/`MIN_MODEL_VOTES` — не менять.
- Методику формирования региона (bbox/шаг сетки) — пока не менять,
  архитектура кэша должна быть лишь устойчива к будущему изменению.
- НЕ объединять с `model_forecast_cache.json` (point forecast vs
  spatial fields — разные данные).
- Кэш не должен расти бесконечно: только последний успешный snapshot
  на модель, без истории, одна активная версия `grid_id`, atomic
  replace, без бэкапов/архивов.

---

## 1. Структура `data/front_spatial_cache.json`

Отдельный файл, columnar-формат полей (не list-of-dict per point —
экономит ~40% места на повторяющихся ключах):

```json
{
  "version": 1,
  "grid_id": "grid_a3f9c2e1d0",
  "grid_meta": {
    "schema_version": 1,
    "step_km": 220.0,
    "bbox": [-10.0, 33.0, 44.0, 60.0],
    "rows": 14,
    "cols": 19,
    "n_points": 266
  },
  "models": {
    "ecmwf_ifs": {
      "source_run_time": "2026-09-13T06:00:00Z",
      "fetched_at": "2026-09-13T06:12:03Z",
      "fields": {
        "temperature_2m": [19.6, 19.1, ...],
        "relative_humidity_2m": [87, 88, ...],
        "pressure_msl": [1015.5, 1015.3, ...],
        "wind_speed_10m": [...],
        "wind_direction_10m": [...],
        "wind_gusts_10m": [...],
        "precipitation": [...]
      }
    },
    "icon_eu": { "...": "..." },
    "meteofrance_arpege_world": { "...": "..." },
    "ukmo_global_deterministic_10km": { "...": "..." },
    "gfs_global": { "...": "..." }
  }
}
```

Каждый массив в `fields` длиной `n_points`, порядок = порядок
`build_europe_grid()` (тот же, что уже используется в
`fetch_model_batch()` через `flat_points`). Ключ модели = последний
успешный результат, история не хранится.

## 2. Алгоритм определения changed models

Не завожу отдельный "meta"-пробник — переиспользую существующую
инфраструктуру `model_runs_history.json` + `_latest_run_times()`,
которая уже используется в `_has_new_model_run()` для событийного
гейта:

```
cache = _load_json(FRONT_SPATIAL_CACHE_FILE, default=None)
current_grid_id = compute_grid_id(bbox, step, points, SCHEMA_VERSION)

if cache is None or cache.get("grid_id") != current_grid_id:
    # холодный старт ИЛИ смена сетки — см. п.5
    models_to_fetch = ALL 5 моделей (полный fan-out)
    cache_for_models = {}
else:
    cache_for_models = cache["models"]
    latest_run_times = _latest_run_times()
    models_to_fetch = []
    for model_id, label in MODELS:
        cached_entry = cache_for_models.get(model_id)
        new_run_time = latest_run_times.get(label)  # может быть None —
                                                      # модель временно
                                                      # отсутствует в
                                                      # model_runs_history.json

        if cached_entry is None:
            needs_fetch = True
        elif _is_stale(cached_entry["fetched_at"], model_id):  # см. п.4
            needs_fetch = True
        elif new_run_time is not None and new_run_time != cached_entry["source_run_time"]:
            needs_fetch = True
        else:
            # new_run_time is None (неизвестен) ИЛИ равен source_run_time —
            # НЕ считаем changed. [FIX GPT REQUEST CHANGES v1, п.1]
            # Раньше здесь стояло cached_entry["source_run_time"] != new_run_time,
            # что триггерило fetch каждый раз, когда new_run_time временно
            # None — лишние запросы/риск 429 без реальной причины.
            needs_fetch = False

        if needs_fetch:
            models_to_fetch.append(model_id)
```

Точечные (не fan-out) запросы — только по `models_to_fetch`; остальные
модели берутся из `cache_for_models[model_id]["fields"]` как есть.
Пауза `REQUEST_INTERVAL=30с` — только между реально выполняемыми
запросами.

## 3. `grid_id`

Зависит от всего, что физически меняет состав/порядок точек ИЛИ
формат данных:

```python
SCHEMA_VERSION = 1  # бампится вручную при изменении набора/формата полей

def compute_grid_id(bbox, step_km, points, schema_version):
    payload = json.dumps({
        "schema": schema_version,
        "step_km": round(step_km, 3),
        "bbox": [round(x, 4) for x in bbox],
        "points": [(round(p["lat"], 4), round(p["lon"], 4)) for p in points],
        # порядок points ВАЖЕН — не сортировать, брать as-is из build_europe_grid()
    }, ensure_ascii=False, sort_keys=False)
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]
    return f"grid_{h}"  # [FIX GPT REQUEST CHANGES v1, п.3] было "eu220_{h}" —
                         # зашитое имя региона/шага некорректно, если сетка
                         # в будущем изменится (другой регион/шаг/схема).
                         # Сам hash уже полностью зависит от step_km/bbox/
                         # points/schema_version — префикс чисто декоративный.
```

Округление до 4 знаков (~11м) — чтобы плавающая арифметика при
пересчёте bbox не давала ложных "новых" `grid_id` на идентичной по
сути сетке. `schema_version` ловит изменения, невидимые через
bbox/точки (например, добавили переменную в `CURRENT_VARIABLES` —
набор точек тот же, а формат `fields` — нет).

## 4. Freshness / maximum-age policy

Основной сигнал свежести — сравнение `source_run_time` (п.2). Но
нужен независимый потолок на случай, если `model_runs_history.json`
перестал детектировать новые runs (баг, модель "залипла" на старом
run_time) — иначе кэш обслуживает данные бесконечно.

Потолок по возрасту `fetched_at`, запас ×2-3 от документированной
частоты обновления модели (Open-Meteo model updates docs):

| model_id | частота обновления | MAX_AGE_HOURS |
|---|---|---|
| ecmwf_ifs | каждые 6ч | 18 |
| icon_eu | каждые 3ч | 9 |
| meteofrance_arpege_world | каждый час | 6 |
| ukmo_global_deterministic_10km | каждый час | 6 |
| gfs_global | каждый час | 6 |

Плюс единый hard ceiling = 24ч независимо от модели — страховка от
сюрпризов в таблице.

Поведение при просрочке: `_is_stale()` → True → модель попадает в
`models_to_fetch` НЕЗАВИСИМО от того, изменился ли `source_run_time`
(форс-рефетч). Если форс-рефетч тоже падает — модель на этот run
исключается из consensus (как и сегодня в `except`-ветках
`run_europe_detection`), кэш для неё не обновляется и не удаляется.
`MIN_MODEL_VOTES`/`n_valid_grid` не меняются.

## 5. Поведение при смене grid

Смена = `compute_grid_id()` не совпал с сохранённым в файле. Старый
кэш не участвует ни в чём — точки не совпадают, частично переиспользовать
нечего.

- Старый файл не удаляется заранее. Новый набор `models` строится в
  памяти (полный fan-out, до 5 запросов с паузой).
- Атомарная запись (`tmp` + `os.replace`) — только когда есть что
  писать. Если фан-аут упал частично (3 из 5) — пишем файл с новым
  `grid_id` и теми моделями, что получилось. Следующий run увидит тот
  же `grid_id`, увидит отсутствие 2 моделей → допробует именно их
  (обычный путь из п.2, без спецкейса "докачка после неполной смены").
- Если фан-аут упал полностью (0 из 5) — `os.replace` не вызывается,
  старый файл (с уже нерелевантным `grid_id`) остаётся нетронутым до
  следующей попытки. Разовая ситуация только в момент смены grid.
- `os.replace()` на новый `grid_id` и есть "замена" старого кэша —
  отдельного шага удаления не нужно.

**[FIX GPT REQUEST CHANGES v1, п.2]** Факт присутствия модели в
partial cache (файл на диске) и факт её допуска к consensus этого
run — ДВЕ РАЗНЫЕ вещи, их нельзя смешивать:

```
model_results_by_id = {}
for model_id, label in MODELS:
    entry = cache_after_this_run["models"].get(model_id)
    if entry is None:
        continue  # модели нет в кэше вообще — не участвует, как и сегодня
    if _is_stale(entry["fetched_at"], model_id):
        continue  # есть в файле, но просрочена/не прошла freshness —
                   # НЕ участвует в consensus, даже если физически
                   # лежит в front_spatial_cache.json
    model_results_by_id[model_id] = entry["fields"]

# дальше — БЕЗ ИЗМЕНЕНИЙ:
votes_grid, n_valid_grid, confirmed, consensus_score_grid = \
    detect_europe_fronts(model_results_by_id, rows, cols)
```

То есть на вход в `detect_europe_fronts()` (и, соответственно, в
`MIN_MODEL_VOTES`/`n_valid_grid`) попадают только модели, прошедшие ту
же freshness-проверку, что определяет `models_to_fetch` в п.2 —
раздельно от того, есть ли у них физическая запись в partial cache
после неполного fan-out. `MIN_MODEL_VOTES` остаётся единственным vote
gate, сама логика `detect_europe_fronts()` не меняется.

## 6. Оценка максимального размера

CURRENT_VARIABLES = 7 переменных, n_points = 266 (сейчас), 5 моделей.

- На модель: 7 массивов × 266 значений, ~7 байт/значение (columnar)
  ≈ 1862 байта/переменную × 7 ≈ **~13 КБ/модель**.
- 5 моделей × 13 КБ ≈ **~65 КБ**.
- `grid_meta` + служебное ≈ 1 КБ.
- Итого: **~65-70 КБ**, стабильно (не растёт со временем — только
  последний снимок). List-of-dict-per-point формат дал бы ~150-180 КБ
  из-за повторяющихся ключей — отсюда рекомендация columnar.
- Рост при увеличении сетки/переменных — линейный, предсказуемый.

## 7. Аудит существующих файлов на риск неограниченного роста

| Файл | Статус | Комментарий |
|---|---|---|
| `data/_open_meteo_requests.jsonl` | уже самоограничен | `MAX_LINES=20000`/`KEEP_LINES=15000` в `open_meteo_request_log.py`. Риск: `status=f"error:{e}"` не обрезан по длине — длинный текст исключения может раздуть реальный средний размер строки сверх заложенных ~120 байт. Не файл этой задачи, отдельное наблюдение. |
| `data/model_runs_history.json` (36 КБ) | уже самоограничен | `MAX_ENTRIES=60` на label в `check_model_runs.py` (строки 307-318). Действий не требует. |
| `data/model_forecast_cache.json` (1.5 МБ) | не растёт | Снимок перезаписывается, не история. |
| `data/eumetsat_local_channel_suppression_log.json` (1.09 МБ), `data/eumetsat_system_channel_suppression_log.json` (855 КБ) | не проверялось | Вне контура этой задачи, но по имени/размеру — кандидаты на отдельный аудит "лог или снимок". |
| `data/ensemble_snapshots_pws.json` (4.27 МБ), `data/ensemble_snapshots_synop.json` (1.7 МБ) | не проверялось | Тоже вне контура, тоже кандидаты — название намекает на накопление. |

---

## Итог ревью
GPT APPROVE на Proposal v2 (все 3 правки внесены). Аудит файлов из
п.7 — вынесен в отдельную задачу, не блокирует эту реализацию.

## Next action
Ждём подтверждения от Руслана на старт кодирования. После
подтверждения: реализация в `open_meteo_frontal_confirm.py`
(`FRONT_SPATIAL_CACHE_001`) + `data/front_spatial_cache.json` как
новый файл, с `py_compile`/`ast.parse`/enumeration FunctionDef перед
пушем (проектный стандарт) и верификацией через повторный GET после
коммита.
