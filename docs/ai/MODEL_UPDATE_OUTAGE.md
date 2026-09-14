# MODEL_UPDATE_OUTAGE — инцидент остановки обновления моделей

**Дата фиксации:** 10.09.2026, ~19:37 UTC (22:37 Kyiv)
**Приоритет:** выше EUROPE_FRONT_LINE_001 (временно)
**STATUS: awaiting GPT review**

---

## INITIAL DIAGNOSTIC (факты)

### 1. Где остановился pipeline
Нигде — процесс **не завис**. `vps_pipeline.py` (главный, cron `*/5 * * * *`) исправно стартует каждый цикл, доходит до конца, коммитит и пушит в GitHub. Аналогично `vps_satellite_pipeline.py` и `vps_ai_pipeline.py` работают штатно (генерация видео, блоков и т.д. по кэшированным/наблюдательным данным продолжается).

Обрыв — **на этапе получения новых данных моделей от Open-Meteo API**, в блоке `check_model_runs` / фетче сырых переменных внутри `vps_pipeline.py`.

### 2. Последний успешный timestamp
- **Последний новый прогон, успешно задетектирован:** UKMO, `run_time 2026-09-10T13:20`, зафиксирован в `data/model_runs_history.json` (detected ~13:20 UTC).
- **Последняя запись в `data/modeldata/modelData_2026_09.json` (сырые данные моделей):** коммит `13:12:58Z` (`update_local: modelData_2026_09.json...`).
- С этого момента (~13:13–13:20 UTC, **6+ часов назад** от текущего момента) ни один из 8 моделей не получил новых данных.
- Наблюдательные данные (SYNOP/PWS, `ensemble_snapshots_synop.json`, `ensemble_snapshots_pws.json`) продолжают обновляться нормально (последняя запись — 18:12 UTC) — это независимый источник, к Open-Meteo не относится.

### 3. Ошибка — подтверждена
**Да, подтверждён HTTP 429 (Too Many Requests) от Open-Meteo**, причём **по всем 8 моделям одновременно**, на каждом цикле, без единого исключения за проверенное окно (последние ~25+ минут лога, `19:15:37`–`19:37:xx`, полностью 0 успешных фетчей):

```
19:XX:XX  WARNING   Retry 1/3 after: HTTP Error 429: Too Many Requests
19:XX:XX  WARNING   Retry 2/3 after: HTTP Error 429: Too Many Requests
19:XX:XX  INFO        ✗ <model>: HTTP Error 429: Too Many Requests
```
Паттерн повторяется последовательно для: `ecmwf_ifs → icon_eu → icon_global → ukmo_global_deterministic_10km → meteofrance_arpege_europe → gfs_global → gem_global → cma_grapes_global` — то есть retry-логика (3 попытки, интервал ~10–20с) отрабатывает штатно, но упирается в 429 на каждой попытке для каждой модели.

### 4. Завис ли процесс
**Нет.** `ps aux` показывает штатные процессы (`vps_pipeline.py`, `vps_ai_pipeline.py`, `vps_satellite_pipeline.py`, bridge, agent) с ожидаемым временем старта по cron-расписанию. Циклы завершаются за нормальное время (`[main] цикл занял 211.9с`, `[satellite] цикл занял 95.4с`). `git push`/`repo synced` — без ошибок. Диск 21% (35G свободно), load average 3.0–4.0 — в норме, uptime 15 дней без перезагрузок.

### 5. Обрыв цепочки: raw data → snapshots
- Сырые данные моделей (`modelData_2026_09.json`) **не растут** с 13:12:58Z — новых записей 0.
- `calc_model_bias_cloud.py` и `calc_weights.py` в каждом цикле **успешно отрабатывают**, но на **старых, неизменных** данных (n=10737 идентично в 19:20:09, 19:25:09, 19:30:09 — значения bias/MAE побитово одинаковые).
- Соответственно **все производные снимки** (bias, weights, forecast blocks, verification) с 13:xx UTC фактически "замороженные копии", а не новые снимки.
- `verification_snapshots.json` не обновлялся с 03.09 — это отдельная, более старая известная проблема (см. userMemories), не связана с текущим инцидентом напрямую, но усугубляет картину.

---

## Причина (предварительно)

Полный, синхронный, непрерывный 429 **по всем моделям сразу**, длящийся **более 6 часов без единого успеха**, не похож на обычный кратковременный per-minute throttle (600/мин) — такой обычно снимается за секунды-минуты при паузе между вызовами. Характер (тотальный и продолжительный) больше похож на исчерпание **часовой (5000/ч) или суточной (10000/сутки) квоты** Open-Meteo для IP VPS, либо на временную блокировку/деградацию на стороне Open-Meteo для этого IP.

**Не подтверждено количественно** — точный счётчик сделанных сегодня запросов не инструментирован в коде, поэтому нельзя однозначно сказать «исчерпан суточный лимit» vs «блок на стороне провайдера». Это первое, что нужно проверить в следующем шаге.

---

## Proposal (минимальный, без изменений кода на этом этапе)

1. **Ждать и мониторить** — если это суточная квота (10 000/сутки), сброс должен произойти около полуночи UTC. Проверить восстановление после 00:00–01:00 UTC (03:00–04:00 Kyiv).
2. **Инструментировать счётчик вызовов Open-Meteo** (минимальная правка после диагностики): логировать нарастающий дневной счётчик запросов по всем трём пайплайнам (main/satellite/ai) в один файл, чтобы в следующий раз сразу видеть, дошли ли до 10000/сутки или 5000/час.
3. **Не увеличивать частоту retry** — текущие ретраи (3×) только усугубляют исчерпание лимита при 429; на время диагностики лимит стоит не трогать.
4. Если после полуночи UTC 429 не снимется — тогда это не квота, а блокировка IP/провайдера, и потребуется отдельное расследование (смена User-Agent, задержки между провайдерами, обращение в поддержку Open-Meteo).

---

## Технические детали (для последующих сессий)

- Проверочная команда для статуса: bridge-задача с `tail -N /var/log/vps-pipeline.log` + `grep 429`.
- Формат успешного фетча в логе НЕ содержит паттерна `✓ <model_name>:` в том виде, что ожидалось — нужно будет найти точный формат строки успеха при следующей диагностике (быстрый grep не нашёл ни одного совпадения за весь лог, возможно иное форматирование).
- `/var/log/vps-pipeline.log` не ротируется logrotate'ом (`/etc/logrotate.d/` — пусто для vps), растёт с 27.08 (Birth), сейчас 297k+ строк — стоит отдельно рассмотреть ротацию (не в рамках этого инцидента).

**STATUS: awaiting GPT review**


---

## ОБНОВЛЕНИЕ 11.09.2026 05:20 UTC — восстановление + разбор кода по запросу GPT

### Восстановление подтверждено
Первый успешный коммит новых модельных данных после инцидента: **`2026-09-11T00:16:25Z`** (`update_local: modelData_2026_09.json...`). Разрыв длился **~13:13 → ~00:16 UTC, т.е. ~11 часов**. Восстановление произошло практически ровно в полночь UTC — это сильно склоняет гипотезу в сторону **суточной квоты (10 000/сутки)**, а не блокировки IP (блокировка IP не привязана к границе суток так точно).

### Инвентаризация ВСЕХ точек вызова Open-Meteo в проекте

**`vps_pipeline.py` (главный, cron */5 мин):**
| Вызов | Условие запуска | Запросов за срабатывание | Retry |
|---|---|---|---|
| `fetch_run_time_and_interval()` (meta.json) | по модели, только когда "due" (не каждый цикл) | до 8 (редко все разом) | нет |
| → `update_local.py` → `update.py::fetch_ensemble_ready_time()` | **безусловно**, при каждом вызове update_local.py | 6 (модели с metaId), без пауз между ними | нет |
| → `update.py::fetch_forecast_model()` (16 дней, все поля) | только если `need_synop`/`need_pws` (новый прогон) | 8, пауза 0.5с между | до 3× с задержкой 10с на каждый = до 24 |
| → `update.py::fetch_historical_model()` (бэкфилл SYNOP) | только если есть новые SYNOP-дни | 8 × N_дней, пауза 0.5с | до 3× delay=10с на каждый |

`update_local.py` вызывается: при детекте нового прогона ЛЮБОЙ из 8 моделей (`run_pipeline`) **и** в каждом SYNOP-окне (8 раз/сутки), если ещё не вызывался в этом цикле.

**`vps_satellite_pipeline.py` (cron */5 мин, независимо от главного):**
| Вызов | Условие запуска | Запросов | Retry |
|---|---|---|---|
| `open_meteo_frontal_confirm.py` | внутренний событийный гейт: новый прогон у любой из **5** отслеживаемых моделей (читает тот же `model_runs_history.json`, что пишет главный pipeline) | 5 (batch на все точки), пауза `REQUEST_INTERVAL=30с` между | 1 повтор на 429 (Retry-After, макс. 30с) |
| `open_meteo_field_fetch.py` | throttle 15 мин (`_throttle_ok`) | 8 моделей × N_треков, **без пауз** между моделями | 1 повтор на 429 на каждый |
| `open_meteo_very_far_line.py` | throttle 15 мин | 1 (batch) | 1 повтор |

`vps_ai_pipeline.py` — Open-Meteo не использует, к инциденту не относится.

### Расчёт максимального числа запросов

**Худший случай на ОДИН 5-минутный тик крона** (совпадение: новый прогон модели детектирован главным pipeline → тот же тик читает спутниковый pipeline → плюс оба 15-минутных throttle-окна как раз открыты, N_треков=1):

- Главный: 8 (проверка прогонов) + 6 (`fetch_ensemble_ready_time`, без ретраев) + до 24 (`fetch_forecast_model`, 8×3 ретрая) ≈ **до 38**
- Спутниковый: до 10 (`frontal_confirm`, 5×2) + до 16 (`field_fetch`, 8×2) + до 2 (`very_far_line`) ≈ **до 28**
- **Итого за один цикл (5 мин), худший случай: ~66 запросов** (при нескольких одновременных треках фронта — кратно больше, N_треков=3 → ~98).

**Критично:** это не разовый всплеск. Пока модель/фетч не получает успешный ответ, **"due"-состояние не снимается** — ни `next_expected` у главного pipeline, ни `need_synop/need_pws`, ни событийный гейт спутникового. Значит **тот же набор запросов повторяется КАЖДЫЙ следующий тик крона** (каждые 5 минут), пока не будет хотя бы один успех. Это даёт:

- **≈ 66 запросов × 12 тиков/час ≈ 790 запросов/час** (консервативно, N_треков=1) — само по себе меньше часового лимита 5000/ч, НО:
- **за ~11 часов инцидента: 790 × 11 ≈ 8 700 запросов**, поверх обычного дневного трафика ДО начала инцидента (SYNOP-окна, успешные детекты прогонов и т.д.) — это правдоподобно **добивает суточную квоту 10 000/сутки** и держит её исчерпанной до полуночи UTC, вместо того чтобы дать ей "остыть".

**Вывод: даже если исходный триггер был случайным совпадением (несколько скриптов дёрнули API почти одновременно, как уже фиксировалось 08.09 — см. комментарий в `vps_pipeline.py` строка ~1011), именно ОТСУТСТВИЕ общего контура ("все получили 429 → все замолчали") превратило кратковременный всплеск в 11-часовой простой: каждый из 3+ независимых скриптов на каждом cron-тике самостоятельно "не знал", что остальные тоже словили 429, и продолжал попытки.**

---

## Proposal v1 — глобальный Open-Meteo cooldown / circuit breaker (архитектура, БЕЗ кода)

### Общее состояние
Один файл на VPS-диске (не коммитится в git, как существующие `_throttle_*.json` — персистентный между cron-запусками): `data/_open_meteo_cooldown.json`
```json
{"cooldown_until": "2026-09-10T14:00:00Z", "triggered_by": "ecmwf_ifs@vps_pipeline", "consecutive_trips": 1}
```

### Общий модуль
Новый маленький файл `scripts/open_meteo_guard.py` с тремя функциями:
- `is_in_cooldown() -> bool` — читает файл, `True` если `now < cooldown_until`.
- `record_429(retry_after=None)` — пишет/продлевает `cooldown_until` = `now + max(retry_after, BASE_COOLDOWN)`; при повторном триггере **во время уже активного cooldown** — экспоненциально увеличивает (`consecutive_trips += 1`, cooldown ×2, потолок — например 2 часа).
- `clear_cooldown()` — вызывается после первого контролируемого успеха, сбрасывает `consecutive_trips`.

### Изменения в существующих скриптах (5 точек входа)
Каждый из: `vps_pipeline.py` (проверка прогонов), `update.py` (все 3 fetch-функции), `open_meteo_frontal_confirm.py`, `open_meteo_field_fetch.py`, `open_meteo_very_far_line.py` — на **входе** в свой Open-Meteo-блок:
1. `if is_in_cooldown(): лог "пропущено — глобальный cooldown до <ts>"; return/continue без единого запроса.`
2. Внутри циклов по моделям: **при первом же 429 — `record_429(...)`, `break` из цикла** (не идти дальше по остальным моделям, не делать локальный retry×3 — это и есть просьба GPT «не ретраить остальные модели»).
3. После окончания cooldown (`is_in_cooldown()` вернул `False`, но `consecutive_trips > 0`) — **первый запрос после паузы делать ТОЛЬКО ОДИН**, например `fetch_run_time()` для одной модели (самый дешёвый эндпоинт), а не сразу полный залп 8+6+8. Если он успешен — `clear_cooldown()` и на СЛЕДУЮЩЕМ тике уже штатная логика; если снова 429 — `record_429()` продлевает cooldown ещё раз.

### Почему это минимально
- Один новый файл (~30-40 строк), без изменения бизнес-логики детекта прогонов/снимков.
- В каждый из 5 существующих скриптов — по 2-3 строки (импорт + проверка в начале + `break` вместо продолжения цикла на 429).
- Не трогает git-часть, БУФР, спутниковый анализ, AI-пайплайн (он и так не использует Open-Meteo).

### Открытый вопрос к GPT
- Величина `BASE_COOLDOWN`: предлагаю **15 минут** (совпадает с уже существующими throttle-окнами `open_meteo_field`/`open_meteo_very_far_line` — единообразно, не нужно вводить новую константу "с нуля"). Устраивает?
- Контролируемая "one probe" попытка — через `fetch_run_time()` одной конкретной модели (например, ecmwf_ifs, она мониторится всеми тремя механизмами) — согласны, или нужен отдельный самый лёгкий индикатор?

**STATUS: awaiting GPT review of proposal**


---

## Уточнение по фактическому коду: что означает "Retry X/3"

Из `update.py::retry()` (строки 78-86):
```python
def retry(fn, attempts=3, delay=5):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            log.warning("  Retry %d/%d after: %s", i+1, attempts, e)
            time.sleep(delay)
```
Это **не** "3 повторных запроса после первого" — это **всего 3 попытки суммарно** (i=0,1,2). Лог `"Retry 1/3"` печатается ПОСЛЕ первой неудачной попытки, перед второй. Итого на модель: **3 HTTP-запроса, 2 паузы по `delay` (10с у `fetch_forecast_model`/`fetch_historical_model`)** — не больше. Мой предыдущий расчёт (8 моделей × 3 = 24 для `fetch_forecast_model`) — **верен**, уточнение только терминологическое.

Для сравнения, у спутниковых скриптов (`open_meteo_frontal_confirm.py`, `open_meteo_field_fetch.py`) логика другая — НЕ цикл, а один рекурсивный повтор конкретно на HTTP 429 (`_retry=True` → при 429 один доп. вызов с `_retry=False`): **максимум 2 запроса на модель**, не 3. `fetch_ensemble_ready_time()` и `fetch_run_time_and_interval()` — вообще без повторов, **1 запрос**, тихий `except: pass`.

Итоговая таблица (запросов на 1 модель, худший случай):
| Функция | Файл | Запросов/модель | Между попытками |
|---|---|---|---|
| `fetch_run_time_and_interval` | vps_pipeline.py | 1 | — |
| `fetch_ensemble_ready_time` | update.py | 1 | — |
| `fetch_forecast_model` | update.py | 3 | 10с |
| `fetch_historical_model` | update.py | 3 | 10с |
| `fetch_model_batch` | open_meteo_frontal_confirm.py | 2 | Retry-After (≤30с) |
| `fetch_model_current` | open_meteo_field_fetch.py | 2 | Retry-After (≤30с) |

(Числа в предыдущем расчёте "~66 запросов/цикл" не меняются — они уже были посчитаны по этой таблице.)

---

## Proposal v2 — с учётом правок GPT

### 1. BASE_COOLDOWN
Принято: **30 минут**, экспоненциально при повторном триггере ВНУТРИ ещё активного cooldown: `30м → 1ч → 2ч (потолок)`. Если после 2ч всё ещё 429 — остаётся 2ч на каждый следующий цикл проб (не растёт дальше), чтобы не улететь в сутки от одного затяжного инцидента.

### 2. HALF_OPEN / контролируемое восстановление (новое состояние)
Три состояния в общем файле вместо двух (`CLOSED` / `OPEN`):
- **CLOSED** — норма, все скрипты работают как сейчас (+ проверка гейта, см. ниже).
- **OPEN** — активный cooldown, `now < cooldown_until`. Все точки входа пропускают Open-Meteo целиком (0 запросов).
- **HALF_OPEN** — переходное состояние ПОСЛЕ истечения `cooldown_until`, но ДО подтверждения, что API снова отвечает:
  - Только **один** процесс получает право на probe (см. п.3 — race condition).
  - Probe = **один** самый дешёвый запрос (`meta.json` для одной фиксированной модели, например `ecmwf_ifs`) — НЕ часть обычного 6/8-модельного залпа, отдельный лёгкий вызов прямо в `open_meteo_guard.py`.
  - **Успех probe** → состояние переходит в `RECOVERING` на **один cron-тик** (5 мин, один цикл главного pipeline): в этом окне разрешены только дешёвые вызовы без пачек (`fetch_run_time_and_interval`, `fetch_ensemble_ready_time`) — тяжёлые пакетные (`fetch_forecast_model` 8×, `open_meteo_field_fetch` 8×N, `open_meteo_frontal_confirm` 5×) **остаются заблокированы** ещё один тик, чтобы не повторить именно тот сценарий, из-за которого возник инцидент (несколько скриптов разом бьют по API в момент восстановления).
  - Если за это окно ни один вызов не поймал новый 429 → автоматический переход в `CLOSED`, все точки входа работают штатно со следующего тика.
  - Если хоть один вызов (даже дешёвый) поймал 429 в `RECOVERING` → немедленно назад в `OPEN`, cooldown умножается ×2 (см. п.1).
  - **Провал probe** (429 на самом probe) → назад в `OPEN`, cooldown ×2, флаг "право на probe" освобождается для следующей попытки после нового `cooldown_until`.

### 3. Race condition — process-safe механизм
Три независимых cron-процесса (главный/спутниковый/AI — хотя AI Open-Meteo не трогает) читают/пишут один файл `data/_open_meteo_cooldown.json`. Без блокировки два процесса могут одновременно увидеть "cooldown истёк" и оба попытаться сделать probe, либо гонка на запись (`consecutive_trips` потеряется).

Решение — тот же паттерн, что уже используется в проекте для git-операций в bridge (`flock -w 20 /tmp/vps_git.lock`, см. Tools & resources): отдельный lock-файл `data/_open_meteo_cooldown.lock` (persistent VPS-диск, не коммитится).

`open_meteo_guard.py` оборачивает КАЖДУЮ операцию чтения-с-намерением-изменить и запись в критическую секцию:
```python
import fcntl

def _with_lock(fn):
    with open(LOCK_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)   # блокирующий, ждёт своей очереди
        try:
            return fn()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
```
Все три операции — `is_in_cooldown()`, `try_acquire_probe()`, `record_429()` / `report_probe_result()` — читают JSON, при необходимости меняют его и пишут обратно **внутри одной блокировки** (read-modify-write атомарно), а не отдельными read+write вызовами. Так `try_acquire_probe()` гарантированно вернёт `True` только ОДНОМУ из конкурирующих процессов: под локом он проверяет `probe_claimed_at is None`, и если да — сразу же (не выходя из лока) выставляет `probe_claimed_at=now, probe_claimed_by=<script>` и возвращает `True`; конкурент, зашедший в лок вторым, увидит уже занятый `probe_claimed_at` и получит `False`.

Так как критическая секция — это только чтение/запись небольшого JSON (не сетевой запрос!), блокировка держится миллисекунды — конкурентные cron-процессы не будут друг друга ощутимо задерживать.

### Итоговая схема точек входа (без изменений с v1, кроме самой логики гейта)
Те же 5 файлов (`vps_pipeline.py`, `update.py`, `open_meteo_frontal_confirm.py`, `open_meteo_field_fetch.py`, `open_meteo_very_far_line.py`) на входе в Open-Meteo-блок вызывают `open_meteo_guard.gate(caller_id=...)`, которая под локом возвращает одно из: `"proceed"` (CLOSED или RECOVERING+дешёвый вызов), `"probe"` (этому вызову выдано право на пробный запрос), `"skip"` (всё остальное — OPEN, или RECOVERING+тяжёлый вызов, или probe уже занят кем-то другим). При первом же 429 в цикле по моделям — `break` (не идём дальше по остальным моделям, как договорились в v1) + `open_meteo_guard.record_429(retry_after=...)`.

**STATUS: awaiting GPT review of v2**


---

## Proposal v3 — упрощённая state machine (по замечаниям GPT)

### Убрано
- Отдельное состояние `RECOVERING` и деление вызовов на cheap/heavy — убрано целиком.
- Guard больше НЕ делает HTTP-запросов сам — только состояние + lock.

### Состояния — всего два
`CLOSED` (норма) / `OPEN` (cooldown). Файл `data/_open_meteo_cooldown.json`:
```json
{"state": "OPEN", "cooldown_until": "2026-09-10T14:00:00Z", "trips": 1, "probe_claimed_at": null}
```

### Кто выполняет probe
Guard НЕ ходит в сеть. Probe — это **существующий** вызов `fetch_run_time_and_interval("ecmwf_ifs025")` в `vps_pipeline.py` (главный pipeline, проверка прогонов моделей). Он и так самый дешёвый (1 запрос, meta.json, без ретраев) и и так выполняется на каждом цикле как часть штатной проверки прогонов. Фиксированный, единственный probe-owner — **этот конкретный вызов для этой конкретной модели**, никакой отдельной синтетической функции в guard не создаётся.

### Логика для 5 точек входа
Все точки входа (включая саму проверку `ecmwf_ifs` в `vps_pipeline.py`) на входе делают:
```python
if guard.is_in_cooldown():
    # но если это ИМЕННО probe-owner (ecmwf_ifs check) — сначала пробуем застолбить probe
    if caller_is_probe_owner and guard.try_acquire_probe():
        pass  # разрешено выполнить СВОЙ обычный запрос как probe
    else:
        skip()  # 0 запросов
```
Остальные 4 точки входа (`update.py`×3 функции, `open_meteo_frontal_confirm.py`, `open_meteo_field_fetch.py`, `open_meteo_very_far_line.py`) видят `is_in_cooldown() == True` и просто пропускают весь блок, пока `state != CLOSED` — без какого-либо разделения "лёгкий/тяжёлый" вызов.

### Переходы состояний
1. **CLOSED → OPEN** (первый трип): любая из 5 точек входа поймала первый 429 в своём цикле → `guard.record_429()` → если `state == CLOSED`: `state = OPEN`, `cooldown_until = now + 30м`, `trips = 1`.
2. **429 во время уже открытого OPEN, НЕ от probe-owner'а**: это "хвостовой" запрос, начатый ДО того, как ворота закрылись (гонка с моментом трипа) — `record_429()` при `state == OPEN` и вызов НЕ помечен как probe → **no-op**, ничего не меняем (по просьбе GPT: backoff не растёт от параллельных 429, начавшихся до трипа).
3. **OPEN, `now >= cooldown_until`**: только probe-owner (`ecmwf_ifs` check в `vps_pipeline.py`) вызывает `try_acquire_probe()` — под flock атомарно проверяет `probe_claimed_at is None`, если да — ставит `probe_claimed_at = now` и возвращает `True` (право получено), иначе `False`. Только обладатель `True` реально делает HTTP-запрos.
4. **Probe успешен**: `guard.report_probe_result(success=True)` → `state = CLOSED`, `trips = 0`, `probe_claimed_at = None`. Все точки входа с этого момента (следующая их проверка `is_in_cooldown()`) работают штатно.
5. **Probe провалился (429 на самом probe)**: `guard.report_probe_result(success=False)` → `state` остаётся `OPEN`, `trips += 1`, `cooldown_until = now + backoff(trips)`, `probe_claimed_at = None` (разблокировано для следующей попытки после нового `cooldown_until`). `backoff`: `{1: 30м, 2: 1ч, 3+: 2ч}` (потолок 2ч).

### Итог: 3 функции в `open_meteo_guard.py`, ноль сетевых вызовов внутри него
- `is_in_cooldown() -> bool` (под flock, простое чтение `state`)
- `try_acquire_probe() -> bool` (под flock, атомарный claim, только для вызова из `vps_pipeline.py`/`ecmwf_ifs`-проверки)
- `record_429(is_probe: bool)` / `report_probe_result(success: bool)` — по сути один и тот же путь записи, разница только в источнике вызова (обычная точка входа vs probe-owner)

Изменения в существующих файлах — как в v1/v2 (2-3 строки на файл), без HALF_OPEN-специфики. Код по-прежнему не менял.

**STATUS: awaiting GPT review of v3**


---

## РЕАЛИЗАЦИЯ (11.09.2026) — Proposal v3 внедрён

### Коммиты (main)
| Файл | Commit SHA |
|---|---|
| `scripts/open_meteo_guard.py` (новый) | `87f082e1dbd01284ed7f29dd0cc69ab07bc07833` |
| `scripts/vps_pipeline.py` | `14f5392b02da8b9e0ef36436b423d15205de998f` |
| `scripts/update.py` | `f01d7222d0ed73f8339be21549b2d798849ecdf5` |
| `scripts/open_meteo_frontal_confirm.py` | `96411ed939a6107f755bde4b1934bebdcb059d2c` |
| `scripts/open_meteo_field_fetch.py` | `dbd4a78e4995db3c7ac1fd03dfc9ec05dc3b81b8` |
| `scripts/open_meteo_very_far_line.py` | `e2e1d4de18e0d99da79dffc18299cf4df182c06d` |

Все правки — целевые `str_replace` (не heredoc), после каждой — `py_compile` + `ast`-сверка списка функций до/после (0 потерянных, 0 случайно добавленных функций во всех 5 изменённых файлах). Содержимое на GitHub после пуша сверено байт-в-байт с локальной версией — совпадает во всех 6 файлах.

### Что именно внедрено (соответствует Proposal v3)
- `open_meteo_guard.py`: 2 состояния (`CLOSED`/`OPEN`), файл состояния `data/_open_meteo_cooldown.json` + lock `data/_open_meteo_cooldown.lock` (не коммитятся — не входят в whitelist `git add` ни одного из трёх pipeline, как и существующие `_throttle_*.json`). `gate(probe_owner)` — единая атомарная точка (под `fcntl.flock`), возвращает `proceed`/`probe`/`skip`. `record_429()` — no-op, если уже `OPEN` (защита от "хвостовых" параллельных 429). `report_probe_result()` — только `CLOSED` (успех) или backoff 30м→1ч→2ч (провал).
- Probe-owner — **только** проверка `ecmwf_ifs` в `vps_pipeline.py` (уже существующий самый дешёвый вызов `fetch_run_time_and_interval`, без изменений в самой сети/логике детекта прогонов).
- Во всех 5 точках входа: gate-проверка перед сетевым блоком + `break`/`continue` на первом 429 в переборе моделей (не долбим оставшиеся модели в этом цикле).

### Тесты (без сети, только логика state machine)
Прогнаны локально в песочнице (не на VPS):
1. **CLOSED → первый 429 (non-probe) → OPEN, trips=1, cooldown=30м** — OK.
2. **Второй 429 (non-probe) во время уже открытого OPEN → no-op** (state не меняется побитово) — OK, подтверждён явным сравнением словаря состояния до/после.
3. **gate() для не-probe-владельца — `skip` и до, и после истечения cooldown** (пока пробу не подтвердили) — OK.
4. **gate() для probe-владельца до истечения cooldown → `skip`**; **после истечения → `probe`** (claim выставлен) — OK.
5. **Провал probe → `report_probe_result(False)` → `OPEN`, trips=2, cooldown=1ч** — OK.
6. **Повторная проба после истечения нового cooldown → успех → `report_probe_result(True)` → `CLOSED`, trips=0** — OK.
7. **Race condition**: 20 параллельных процессов (`fork` через отдельные `python3`-процессы, не threads — реалистичнее для независимых cron-джобов) одновременно вызывают `gate(probe_owner=True)` при истёкшем cooldown → **ровно один** получил `"probe"`, остальные 19 — `"skip"`. Файл состояния не повреждён.
8. **10 параллельных non-probe вызовов** `gate(probe_owner=False)` во время активного `OPEN` → все 10 корректно получили `"skip"`, состояние (`trips`, `cooldown_until`) не изменилось ни на йоту.

Скрипты тестов не коммитились в репозиторий (временные, в песочнице) — при необходимости могу оформить как `tests/test_open_meteo_guard.py` отдельным коммитом, если нужно для CI/регрессии.

### Как это доедет до VPS
`vps_pipeline.py` в начале **каждого** 5-минутного цикла делает `git fetch origin main --depth 1 && git reset --hard origin/main` (см. докстринг файла) — значит все 6 файлов подтянутся на VPS автоматически на первом же cron-тике после этого коммита, без ручного вмешательства. `git reset --hard` не трогает untracked-файлы (`_throttle_*.json`, теперь и `_open_meteo_cooldown.*`) — персистентность между циклами сохраняется.

### Что осталось проверить УЖЕ на живом VPS (не проверено в этой сессии — сети к Open-Meteo из песочницы нет, состояние на VPS сейчас `CLOSED`, инцидент не воспроизвести искусственно без реального 429)
- Что `import open_meteo_guard` резолвится корректно при запуске `python3 /opt/weather-pipeline/repo/scripts/vps_pipeline.py` из cron (ожидается — Python добавляет директорию скрипта в `sys.path[0]`, как уже используется для `from open_meteo_field_fetch import ...` в `open_meteo_very_far_line.py`).
- Что при следующем реальном 429 (если он случится) в логе появится `"cooldown зафиксирован"` / `"⛔ Open-Meteo cooldown активен"` — визуальное подтверждение, что breaker сработал.

**STATUS: implemented, awaiting first live 429 (or manual VPS smoke-test) for on-server confirmation**

---

## IMPLEMENTATION — 11.09.2026

- Incident diagnosis: Open-Meteo HTTP 429 confirmed; pipeline/VPS themselves continued working normally.
- Recovery: new model data resumed at `2026-09-11T00:16:25Z`, shortly after UTC midnight; daily quota hypothesis strongly supported, exact Open-Meteo limit mechanism not independently confirmed.
- Root architectural issue: independent pipelines continued making Open-Meteo requests after the first 429, with no shared cross-process cooldown.
- Fix implemented: global persistent Open-Meteo circuit breaker in `scripts/open_meteo_guard.py`.
- State machine: `CLOSED → OPEN`; first 429 stops further model requests; cooldown `30m → 1h → 2h`; one atomic probe after cooldown; probe success returns to `CLOSED`.
- Process safety: shared state protected with `fcntl.flock`; concurrent probe claim tested with 20 processes, exactly one probe winner.
- Guard does not perform HTTP itself; probe uses existing `ecmwf_ifs` run-time check.
- All 5 Open-Meteo entry points integrated.
- Implementation commits: `87f082e`, `14f5392`, `f01d722`, `96411ed`, `dbd4a78`, `e2e1d4d`.
- Local state-machine tests: PASS.
- VPS smoke-test / first live 429 confirmation: pending.

STATUS: implemented; awaiting VPS smoke-test and first live 429 confirmation.
