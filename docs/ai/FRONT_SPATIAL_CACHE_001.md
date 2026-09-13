# TASK: FRONT_SPATIAL_CACHE_001

## Status
OPEN — Proposal v1 (проектирование, код не менялся, коммит не делался).
Ждём APPROVE/REQUEST CHANGES от GPT перед реализацией.

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
  "grid_id": "eu220_a3f9c2e1d0",
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
        new_run_time = latest_run_times.get(label)
        if (cached_entry is None
                or cached_entry["source_run_time"] != new_run_time
                or _is_stale(cached_entry["fetched_at"], model_id)):  # см. п.4
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
    return f"eu220_{h}"
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

## Вопросы к ревью
1. Согласны ли со схемой changed-model detection через переиспользование
   `model_runs_history.json`/`_latest_run_times()`, без отдельного
   meta-пробника?
2. Согласны ли с freshness-таблицей (п.4) и форс-рефетчем по возрасту
   независимо от `source_run_time`?
3. Согласны ли с поведением при частичном fan-out на смене grid (п.5) —
   писать частичный новый `grid_id`, докачивать недостающее в
   последующих runs, а не блокировать запись до полного успеха?
4. Устраивает ли оценка размера (п.6) и выбор columnar-формата?
5. Нужен ли отдельный TASK на аудит файлов из п.7, или отложить до
   отдельного запроса?

## Next action
GPT: review Proposal v1 — APPROVE / REQUEST CHANGES. До APPROVE код
не менять, `open_meteo_frontal_confirm.py` не трогать.
