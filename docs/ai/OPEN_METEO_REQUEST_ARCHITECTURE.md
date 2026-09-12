# OPEN_METEO_REQUEST_ARCHITECTURE_001

Статус: **awaiting GPT review**
Дата анализа: 2026-09-12 (Claude, чтение фактического кода на GitHub main)

---

## 1. Current architecture — точки входа

Активные потребители Open-Meteo (main → weather-_Odessa):

| # | Скрипт | Кто вызывает | Событийный гейт |
|---|---|---|---|
| 1 | `vps_pipeline.py::fetch_run_time_and_interval()` | сам, в цикле по 6 моделям | due-логика (`model_next_expected.json`, next_expected = last_run + interval×0.7) — **проактивный, хорошо оптимизирован** |
| 2 | `update.py::fetch_ensemble_ready_time()` | `update.py::main()` шаг 3, **безусловно** | только circuit breaker (guard), **НЕТ due-гейта** |
| 3 | `update.py::fetch_forecast_model()` ×8 моделей | `update.py::main()` шаг 3, если `need_synop or need_pws` | триггер = `ensemble_ready_time` вырос (см. §2) |
| 4 | `update.py::fetch_historical_model()` ×8 моделей | `update.py::main()` шаг 2, только при пропуске в SYNOP-истории | редкое событие (backfill), не routine |
| 5 | `open_meteo_frontal_confirm.py::fetch_model_batch()` ×5 моделей | satellite pipeline, `check_open_meteo_frontal_confirm()` | `_has_new_model_run()` — событийный гейт по `model_runs_history.json`, **хорошо оптимизирован** |
| 6 | `open_meteo_field_fetch.py` (8 моделей × N треков) | **ОТКЛЮЧЕНО** 2026-09-05 (закомментировано в `main()`) | throttle 15 мин добавлен, но код не вызывается |
| 7 | `open_meteo_very_far_line.py` (1 модель) | **ОТКЛЮЧЕНО** 2026-09-05 (закомментировано в `main()`) | throttle 15 мин добавлен, но код не вызывается |

**Вывод:** источники #6 и #7 (те, что вы подозревали как "каждые 5 минут") уже отключены с 05.09 и не могут объяснять инциденты 10-11.09. Реальный источник — связка #1+#2+#3.

---

## 2. Цепочка: новый прогон → Forecast API (ГЛАВНАЯ НАХОДКА)

`fetch_ensemble_ready_time()` (update.py:418) считает:
```
ensemble_ready_time = max(last_run_availability_time по ВСЕМ 6 моделям с metaId)
```
Это **единое агрегированное** значение, не per-model. Дальше:
```
need_synop = ensemble_ready_time > last_synop_snapshot.runTime
need_pws   = ensemble_ready_time > last_pws_snapshot.runTime
```
Если True — `fetch_forecast_model()` дергается **для ВСЕХ 8 моделей** (не только для той, что реально обновилась).

**Ответ на прямой вопрос из задачи: да, новый прогон ОДНОЙ модели гарантированно вызывает Forecast API запрос для ВСЕХ 8 моделей**, потому что `ensemble_ready_time` — это max(), а не per-model tracking.

Это не баг per se (снимок ансамбля по определению должен содержать все модели), но it means: 6 событий "новый прогон" в сутки (по одному на каждую из 6 моделей с независимым расписанием) = потенциально 6 отдельных полных 8-моделных Forecast-запросов в сутки, а не 1.

---

## 3. Дублирование meta.json-проверок

`vps_pipeline.py` уже сделал due-гейтированную проверку meta.json для due-моделей в начале цикла. Секунды спустя, если `new_models` непустой → `run_pipeline()` → `update_local.py --no-model` → **безусловно** `update.py::main()` → **безусловно** `fetch_ensemble_ready_time()` → **те же самые 6 meta.json запросов ещё раз**, без учёта due-статуса (просто "не в cooldown — стучим").

Итог: каждое обнаружение нового прогона стоит не 1, а фактически 2 раунда meta.json-проверок (один в `vps_pipeline.py` для due-моделей, второй — полный по всем 6 — в `update.py`).

---

## 4. Amplification через retry() при 429

`fetch_forecast_model()`/`fetch_historical_model()` обёрнуты в `retry(attempts=3, delay=10)` (update.py:80-88), который **ловит `HTTPError` как обычное исключение** и повторяет попытку 3 раза (10с пауза) ПЕРЕД тем, как исключение дойдёт до внешнего `except HTTPError` в `main()`, где стоит проверка `e.code == 429` → `guard.record_429()` → `break`.

Следствие: при уже начавшемся 429-шторме первая модель, наткнувшаяся на 429 в этом вызове, тратит **3 реальных запроса** (не 1) прежде, чем цикл по моделям остановится и guard.record_429() сработает. Guard срабатывает НА ОДИН такт позже, чем мог бы.

---

## 5. Совпадение с открытым satellite pipeline (frontal_confirm)

`open_meteo_frontal_confirm.py` реагирует на ТОТ ЖЕ `model_runs_history.json`, что и `update.py`. Оба процесса читают его независимо (main pipeline и satellite pipeline, разные cron-такты), поэтому при новом прогоне модели, входящей в оба списка (ECMWF/ICON EU/UKMO/Arpège/GFS — 5 из 6), возможен **временной нахлёст**: `update.py` делает свой 8-моделный Forecast-запрос в рамках `run_pipeline()`, а на соседнем такте satellite pipeline подхватывает то же событие и запускает `run_europe_detection()` (5 моделей × 1 запрос, 30с пауза = ~2.5 мин). Единственная защита от совпадения по времени — общий circuit breaker (реактивный), **проактивного разнесения по времени нет**.

---

## 6. Request inventory (сколько запросов в разных сценариях)

| Сценарий | meta.json | Forecast API (тяжёлые) |
|---|---|---|
| Обычный цикл 5 мин, ничего due | 0 | 0 |
| 1 модель due, прогон не сменился | 1 (vps_pipeline) | 0 |
| 1 модель due, **новый прогон** | 1 (vps_pipeline) + 6 (update.py) = 7 | 8 (fetch_forecast_model, все модели) |
| Несколько моделей стали due и новыми в одном цикле | N (vps_pipeline, N≤6) + 6 (update.py, один раз — run_pipeline вызывается 1 раз/цикл) | 8 (один раз — ensemble_ready_time уже max) |
| SYNOP-окно (8 раз/сутки), новых прогонов нет | 6 (update.py всё равно их делает) | 0 (need_synop/need_pws уже False) |
| SYNOP-окно + прогон обновился в этом же окне | 6 | 8 |
| Backfill (пропуск в SYNOP-истории) | доп. вызовы fetch_historical_model — 8 на дату пропуска | — |
| frontal_confirm событие (5 из 6 моделей) | 0 (свои meta.json не делает, читает history) | 5 (30с между) |
| Уже 429 (guard OPEN, cooldown) | 0 (все non-probe skip), кроме 1 probe-попытки после cooldown | 0 |
| 429 ловится ВНУТРИ retry() (см. §4) | — | ×3 реальных запроса на первую упавшую модель, до срабатывания guard |

**Худший бытовой (не аварийный) день:** 6 моделей × 1 новый прогон каждая ≈ 6 событий × (7 meta.json + 8 forecast) = 42 meta.json + 48 forecast API запросов в сутки от одного только update.py/vps_pipeline. Плюс 8 SYNOP-окон × 6 meta.json = 48 meta.json запросов, из которых бо́льшая часть просто подтверждает "без изменений". Плюс до 6 событий × 5 forecast (frontal_confirm) = 30 forecast API запросов. Итого grubo ≈90 meta.json + ~78 forecast запросов/сутки в штатном режиме — это НЕ похоже на переполнение суточной квоты (10000/сутки), значит 429 — это не суточная квота, а **часовой/минутный лимит** (5000/час, 600/мин), пробитый BURST'ом, когда несколько событий (SYNOP-окно + новый прогон + frontal_confirm) совпадают в одну и ту же минуту/пятиминутку.

---

## 7. Причина неравномерности обновления моделей (наблюдения 07-11.09)

Объясняется комбинацией факторов, а не одним:
- **Реальный джиттер публикации** — задокументированная находка 2026-09-08: ICON EU публикуется до -29% раньше паспортного интервала, у остальных 0-17%.
- **SCHEDULE_MARGIN_FRACTION=0.30** намеренно смещает `next_expected` раньше паспортного интервала — это НЕ баг, это защита от пропуска раннего прогона, но создаёт видимость "неравномерности" в логах (модель проверяется чаще, чем раз в паспортный интервал).
- **due-тик дискретен по 5-минутному такту** cron — обнаружение всегда отстаёт от реальной публикации на 0-5 минут.
- **cooldown/429** — если модель стала due во время OPEN-состояния guard, её due-статус НЕ сбрасывается (next_expected не пересчитывается, пока fetch не пройдёт успешно) — следующая успешная проверка происходит на первом такте после закрытия guard, что может выглядеть как "скачок" в логах.
- Нет доказательств, что due-логика реально ПРОПУСКАЕТ прогоны (next_expected пересчитывается только от факта, дрейф структурно исключён по дизайну) — неравномерность это ожидаемый эффект, не дефект.

---

## 8. Proposal

### Proposal A (минимальный, рекомендуемый первый шаг)

1. **Убрать дублирование meta.json**: `fetch_ensemble_ready_time()` в `update.py` не должна ходить в сеть заново — `vps_pipeline.py` уже знает актуальные `last_run_availability_time` по всем 6 моделям (из `model_runs_history.json`, который она же пишет). Передавать это как параметр/файл вместо повторного HTTP. Экономия: 6 запросов на каждый вызов `update.py::main()` (и по `run_pipeline()`, и по SYNOP-окну — итого экономия ~90 запросов/сутки без потери функциональности).
2. **Убрать retry() для 429 конкретно**: в `retry()` не повторять при `HTTPError.code == 429` — сразу пробрасывать наверх, чтобы внешний guard сработал с первой (не третьей) попытки. Retry оставить только для сетевых/5xx ошибок.
3. **Разнести SYNOP-окно от model-run события по времени**, если они совпали в одном цикле: если `run_pipeline()` уже отработал в этом цикле (`ran_update_local_this_cycle=True`), SYNOP-окно и так пропускается (уже реализовано) — но сам факт, что `update.py::main()` внутри `run_pipeline()` тоже делает шаг 3 (ensemble/snapshot) означает, что событие "новый прогон" ГАРАНТИРОВАННО тянет за собой ensemble-логику. Это нормально, но после фикса п.1 стоимость этого падает с 6+8 до 0+8 запросов.

### Proposal B (глубже, если A не решит проблему)

Global 15-минутный throttle на сам `fetch_forecast_model()`-блок (не на discovery): если `need_synop or need_pws` стало True раньше, чем прошло 15 минут с прошлого реального forecast-запроса — отложить (флаг pending, обработать на следующем due-тике). Компромисс: снимок ансамбля будет отставать от реального прогона на 0-15 минут вместо 0-5, но burst сглаживается. Это вариант 1+2 из списка задачи, требует нового persistent-файла-throttle (`_forecast_api_throttle.json`, по аналогии с `_open_meteo_cooldown.json`).

### Что останется работать каждые 5 минут
Due-проверка meta.json в `vps_pipeline.py` (это дёшево и уже оптимально) — без изменений.

### Что будет ограничено/собрано
Только тяжёлые `fetch_forecast_model` (Proposal B) — discovery (meta.json) не трогается.

### Как не потерять новые model runs
Discovery-логика (`vps_pipeline.py`, `model_runs_history.json`, `new_models`) не меняется вообще — Proposal A/B трогают только downstream (что происходит ПОСЛЕ обнаружения), не сам факт обнаружения.

### Минимальный план реализации (после GPT review)
1. `update.py::fetch_ensemble_ready_time()` — принимать `ready_times: dict[label, iso]` явным параметром вместо самостоятельного HTTP; `update_local.py`/`vps_pipeline.py` передают уже известные значения из `model_runs_history.json`.
2. `retry()` — добавить проверку `except HTTPError as e: if e.code == 429: raise` до общего `except Exception`.
3. (Proposal B, опционально) — `open_meteo_guard.py` расширить не нужно, throttle для forecast-блока — отдельный лёгкий файл с той же `fcntl`-схемой.

**Код не пишется до APPROVE от GPT.**

---

## 9. GPT review (2026-09-12) — вердикт и реализация

**Verdict: A1+A2 APPROVED** (после проверки семантики). **B — HOLD** (не внедрять до измерения реального трафика).

### Проверка семантики (обязательное условие A1)

Проверено на факте (`data/model_runs_history.json`, живые данные 2026-09-12):
поле `run_time` в history = `ts_to_iso(last_run_availability_time)`, детект-время
хранится отдельно в поле `detected_at`. Семантика совпадает 1:1 с тем, что
раньше возвращал HTTP-запрос к meta.json → **условие A1 выполнено, миграция безопасна**.

### Реализовано (STATUS: DONE, задеплоено в main)

- **A1** — `update.py::fetch_ensemble_ready_time()` (scripts/update.py) больше не делает HTTP;
  читает `data/model_runs_history.json` через `gh_load_json()` (работает и в GH Actions,
  и на VPS через monkey-patch в `update_local.py`, как и остальной I/O). Сетевое discovery
  meta.json остаётся ТОЛЬКО в `vps_pipeline.py`.
- **A2** — `update.py::retry()` больше не ретраит HTTP 429: пробрасывает немедленно на
  первой попытке, `guard.record_429()` теперь срабатывает после первого, а не третьего запроса.
  Retry остаётся для сетевых сбоев и прочих HTTP-ошибок.
- **Единый лог запросов** (`scripts/open_meteo_request_log.py`, требование GPT review) —
  JSONL, append-only под flock, поля: `ts, script, function, endpoint, model, status, gate, attempt`.
  Не коммитится в git (аналог `_open_meteo_cooldown.json`). Подключён во всех активных
  точках входа: `vps_pipeline.py` (meta.json), `update.py::retry()` (forecast/historical,
  через `log_ctx`, логирует КАЖДУЮ попытку внутри retry — видно реальное усиление),
  `open_meteo_frontal_confirm.py` (forecast, 5 моделей).

### НЕ сделано / открыто

- **Proposal B — HOLD**, не реализовывать, пока нет измеренного трафика.
- Причина 429 10-11.09 **не считается доказанной** (штатный объём запросов, по расчёту
  §6, недостаточен для суточной квоты — вероятно minute/hour burst, но это ГИПОТЕЗА, не
  факт). Следующий шаг — дождаться следующего инцидента (или заданного окна наблюдения)
  и разобрать `data/_open_meteo_requests.jsonl` количественно: реальный overlap/burst
  между `vps_pipeline.py` / `update.py` / `open_meteo_frontal_confirm.py`.
- `open_meteo_frontal_confirm.py::fetch_model_batch()` и `open_meteo_field_fetch.py`
  (отключён) имеют СВОЙ внутренний одиночный retry на 429 (не через `update.py::retry()`,
  не затронут A2-фиксом) — тот же класс риска (лишний запрос на 429 до проброса), но
  вне текущего approve-scope. Кандидат на отдельную задачу, если лог покажет значимый вклад.

STATUS: A1+A2 задеплоены. Единый лог включён. Ожидаем накопления данных для количественного разбора burst (п. "Отдельно проверить" из review) перед решением по Proposal B.
