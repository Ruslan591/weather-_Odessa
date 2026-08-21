# Тема: Полный облачный пайплайн (verification + AI + PWS)

_Последнее обновление: 2026-08-21 (вынос AI-блока в отдельный workflow + перестройка порядка цепочки: телефон→спутниковый→этот→AI; проверено вживую 8.5ч работы в проде)_

Основной (не спутниковый, не AI) пайплайн проекта — сравнение 8 ансамблевых
моделей против SYNOP/PWS, синк PWS, морская история. AI-анализ прогноза
(Claude + Gemini) с 2026-08-20 живёт отдельно, см. секцию ниже. Спутниковый
модуль — отдельная тема, см. `docs/topics/eumetsat.md`.

## Архитектура цепочки (с 2026-08-20)

```
Телефон (job 1001, каждые 15 мин, scripts/trigger_gh_pipeline.sh)
   │  workflow_dispatch          [ВРЕМЕННО, пока не git pull на телефоне:
   │                               satellite_pipeline.yml ТАКЖЕ на cron
   │                               */15 * * * * — см. ретроспективу ниже]
   ▼
satellite_pipeline.yml  (EUMETSAT — своя тема, docs/topics/eumetsat.md)
   │  явный dispatch последним шагом ("Явный запуск полного пайплайна")
   ▼
full_pipeline.yml  ← ЭТОТ ФАЙЛ
   │  явный dispatch последним шагом ("Явный запуск AI-пайплайна")
   ▼
ai_pipeline.yml  (AI-анализ — секция ниже)
```

**До 2026-08-20 порядок был другой:** телефон триггерил `full_pipeline.yml`
напрямую, а тот последним шагом диспетчил `satellite_pipeline.yml`. AI-блок
жил инлайн внутри `gh_pipeline.py`. Порядок перевёрнут и AI вынесен по
явному решению пользователя — не из-за зависимости по данным (её между
тремя модулями как не было, так и нет, кроме одного нюанса с AI, см. ниже).

Каждый переход в цепочке — явный `curl -X POST .../dispatches` (НЕ
`workflow_run`: он документированно ненадёжен, ни разу не сработал на
практике за всё время, что где-либо стоял в этом проекте), с guard'ом
"пропустить, если целевой workflow уже `in_progress`/`queued`" и
debug-коммитом HTTP-ответа (`data/_debug_full_dispatch.json`,
`data/_debug_ai_dispatch.json`) для диагностики. Все три диспетч-шага —
`if: always()`: они просто "передают эстафету" следующей стадии, которая
сама самодостаточно решает, есть ли ей работа — это НЕ то же самое, что
push-уведомления/redispatch-шаги внутри `satellite_pipeline.yml`, которые
читают "just_triggered"-флаги и обязаны быть гейтованы `success()` (см.
инцидент 2026-08-18, `docs/topics/eumetsat.md`) — разные категории шагов,
разные правила безопасности.

## Что это (`full_pipeline.yml`)

- **Workflow:** `.github/workflows/full_pipeline.yml`, название в GitHub Actions — "Полный облачный пайплайн (verification + AI + PWS)" (название не переименовывали, хотя AI из него уехал — цена переименования выше пользы)
- **Дирижёр:** `scripts/gh_pipeline.py` (облачный аналог телефонного `check_model_runs.py` — телефонную версию НЕ трогать, отдельное решение)
- **Триггер:** только `workflow_dispatch` — запускается явным диспетчем из последнего шага `satellite_pipeline.yml` (до 2026-08-20 — напрямую телефоном)
- **Concurrency:** группа `full-pipeline`, `cancel-in-progress: false`
- **Timeout:** 45 минут
- **Python-зависимости:** `requests numpy Pillow` (с 2026-08-20; `edge-tts`/`scipy` убраны — были нужны только AI-блоку, который уехал; `numpy`/`Pillow`/`requests` остались — их использует `nearby_precip.py`/`marine_history.py`, НЕ AI-скрипты, см. «Технические детали»)
- ffmpeg и шрифт Carlito с 2026-08-20 здесь больше не ставятся — были нужны только `make_video.py`/`make_blocks_*`, переехали в `ai_pipeline.yml`

## Порядок выполнения (`gh_pipeline.py main()`)

1. Проверка прогонов 8 моделей (`MODELS` — ECMWF IFS, ICON EU, UKMO, Arpège, GFS, GRAPES + ещё 2) через Open-Meteo meta API — сравнение с `data/model_runs_history.json`
2. Если есть новые прогоны (`new_models`):
   - `calc_model_bias_cloud.py` — расчёт смещения моделей
   - `calc_weights.py` — веса моделей (без `LOCAL=1`, пишет через GitHub API сам, читает `GITHUB_TOKEN`)
   - `update_local.py --no-model` (импортирует `update.py`, тоже читает `GITHUB_TOKEN`)
   - если все три отработали успешно (`ok=True`) → `queue_ai_models(new_models)`: пишет/сливает `data/_ai_pending_models.json` — **это единственное место, где что-либо решает, нужен ли AI-анализ**; сам AI-пайплайн этот список не формирует, только читает и опустошает (см. секцию AI ниже)
   - `git commit + push`
3. Если новых прогонов нет: короткий путь — `update_local.py --no-model --no-fill` + `git commit + push` (retry pending-Gemini уехал в AI-пайплайн, см. ниже — здесь этой логики больше нет)
4. Каждый цикл, независимо от новых прогонов: `check_pws_sync()`, `check_pws_calibration()`, `check_marine_history()`, `check_nearby_precip()`, `check_hmcbas_telegram()` (`check_hmcbas_sea_temp()` отключён — виджет сайта стабильно отдаёт брак)
5. Финальный `git_push_history()` — т.к. `calibrate_pws_pressure.py`/`marine_history.py` пишут только в локальный checkout раннера
6. `if: always()` шаг в YAML (не в `gh_pipeline.py`) — явный `workflow_dispatch` API-вызов `ai_pipeline.yml`

## AI-пайплайн (`ai_pipeline.yml` / `gh_ai_pipeline.py`, вынесен 2026-08-20)

Отдельный workflow, `workflow_dispatch`-only (+ опциональный input `force`
для ручного теста из GitHub UI), concurrency-группа `ai-pipeline`, timeout
30 мин. Диспетчится последним шагом `full_pipeline.yml` — см. архитектуру
цепочки выше.

**Два независимых, самодостаточных механизма внутри `main()`:**

1. **`check_ai_new_models()`** — читает `data/_ai_pending_models.json`
   (наполняет ТОЛЬКО `gh_pipeline.py`, только при успешном `run_pipeline()`
   — это сохраняет исходную зависимость AI-анализа от реальных данных,
   посчитанных `calc_model_bias_cloud`/`calc_weights`/`update_local`, а не
   просто от факта нового прогона модели). Если очередь непуста:
   `generate_ai_analysis.py --models <очередь>` → если
   `forecast_analysis_claude.json.changed` → `make_blocks_cloud.py` (видео
   для Claude НЕ вызывается здесь — `make_video.yml`, отдельный workflow,
   триггерится push'ом по `data/blocks/blocks_meta.json`/`*.mp3`, без
   изменений в этом рефакторинге) → если
   `forecast_analysis_gemini.json.changed` → `make_blocks_gemini_cloud.py`
   → `make_video.py gemini` (для Gemini отдельного push-workflow нет,
   вызывается инлайн, как и раньше). Очередь очищается ТОЛЬКО при успехе
   верхнеуровневого `generate_ai_analysis.py` — при ошибке остаётся для
   повтора в следующем цикле (небольшое усиление устойчивости относительно
   исходного кода, где повтора не было вообще).
2. **`check_ai_gemini_pending()`** — независимая проверка
   `forecast_analysis_gemini.json.pending` (rate-limit retry), та же логика,
   что раньше жила в ветке "новых прогонов нет" в `gh_pipeline.py`.

`git_push_ai()` коммитит только AI-файлы: `forecast_analysis_claude.*`,
`data/blocks`, `forecast_analysis_gemini.*`, `data/blocks_gemini`,
`ai_schedule*.json`, `forecast_video*.mp4`, `data/_ai_pending_models.json`.

**Секреты:** `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — переехали сюда из
`full_pipeline.yml` (там больше не нужны, `gh_pipeline.py` их не читает).
`CLAUDE_ANALYSIS_ENABLED`/`GEMINI_ANALYSIS_ENABLED` тоже здесь.
`GITHUB_TOKEN` сюда НЕ переехал — не нужен ни одному AI-скрипту (нужен
`calc_weights.py`/`update.py`/`pws_sync.py`, все они остались в
`gh_pipeline.py`).

## Известные детали/подводные камни

- `deploy.yml` — проверено 2026-08-18: `paths-ignore` ОТСУТСТВУЕТ, триггерится на любой push в `main`.
- `workflow_run` как резервный триггер убран из `satellite_pipeline.yml` 2026-08-20 (при новом порядке цепочки указывал бы "назад" на `full_pipeline.yml` — риск цикла). Явный `curl -X POST .../dispatches` — единственный механизм везде в цепочке.
- AI-каскад (`make_blocks_*` → `make_video.py`) по-прежнему завязан на `changed`/`pending` флаги в JSON-файлах результата — тот же паттерн, что у `eumetsat_alert_state.json.just_triggered` в спутниковом пайплайне, теперь используется и для передачи `data/_ai_pending_models.json` между `gh_pipeline.py` и `gh_ai_pipeline.py`.
- `verification.py` — общий модуль, импортируется `generate_ai_analysis.py` напрямую (`import verification`), доступен через `sys.path[0]` (директория самого скрипта), не через `cwd` — переезд в отдельный job/workflow ничего не сломал.
- `data/model_runs_history.json` — фактическое имя файла истории прогонов (не `model_history.json`, как было по ошибке написано в плане от 2026-08-18).

## История: вынос AI-блока (реализовано 2026-08-20)

**Мотивация (пользователь):** та же, что у выноса спутникового модуля
2026-07-26 — AI-блок утяжелял/удлинял этот пайплайн, плюс отдельное
решение перевернуть порядок цепочки (телефон→спутниковый→этот, было
наоборот).

**План от 2026-08-18 предлагал два варианта** (см. предыдущую версию
этого файла в git-истории, если нужны подробности): (1) передать
`new_models` через `workflow_dispatch` input, или (2) сделать
`gh_ai_pipeline.py` полностью самодостаточным по образцу спутникового —
самому сравнивать `data/model_runs_history.json` с отдельным маркером
"что уже AI-проанализировано".

**Реализован уточнённый вариант 2**, не буквально по плану: вместо того
чтобы `gh_ai_pipeline.py` сам сравнивал историю моделей с маркером,
`gh_pipeline.py` сам пишет очередь `data/_ai_pending_models.json` — и
ТОЛЬКО когда `run_pipeline()` (calc_bias/calc_weights/update_local)
отработал успешно. Причина отклонения от буквального плана: чтение
истории моделей напрямую потеряло бы ту самую зависимость по данным,
которую план 2026-08-18 явно отметил как ключевую сложность ("реальная
зависимость по данным, не по времени") — самодостаточная проверка по
времени/истории не отличила бы "модель обновилась, но `calc_weights`
упал" от "модель обновилась, и всё честно посчиталось". Очередь-файл,
которую наполняет только источник данных и только при успехе, закрывает
это ровно и просто, не жертвуя самодостаточностью AI-пайплайна (он всё
ещё ни от чего не зависит, кроме своего входного файла).

**Живой тест и 8.5-часовая ретроспектива (2026-08-20 18:25 UTC → 2026-08-21
03:20 UTC):** ручной `workflow_dispatch` на `satellite_pipeline.yml` в
18:25 подтвердил цепочку целиком за первые же минуты (satellite → dispatch
full → full → dispatch ai → ai, все шаги success). При возврате к сессии
после разрыва по лимиту токенов (~8.5ч спустя) выяснилось:

- **`full_pipeline.yml` и `ai_pipeline.yml` отработали безупречно** — 36/36
  прогонов `success` у каждого за это окно, ни одного сбоя. `ai_pipeline.yml`
  реально обрабатывал очередь не вхолостую: `forecast_analysis_gemini.json`
  обновлялся трижды (18:33, 22:05, 00:06 UTC) с правильным commit message
  `"ai: forecast analysis + blocks + video update"` — подтверждение, что
  весь путь `gh_pipeline.py → data/_ai_pending_models.json → gh_ai_pipeline.py
  → generate_ai_analysis.py → git push` работает от начала до конца в проде,
  не только в теории.
- **Найдена и устранена дыра:** `satellite_pipeline.yml` не запускался ни
  разу с 18:25 до момента обнаружения (03:17) — **8.5 часов без спутникового
  мониторинга**. Причина: телефон всё это время продолжал дёргать
  `full_pipeline.yml` напрямую (старый `trigger_gh_pipeline.sh` на
  устройстве — `git pull` ещё не сделан), а `full_pipeline.yml` (по новому
  коду) больше не диспетчит спутниковый сам, и его собственный `workflow_run`
  тоже убран этим же рефакторингом — в моменте не осталось вообще ни одного
  источника триггера для спутникового модуля, кроме телефона. Устранено
  двумя шагами: (1) немедленный ручной `workflow_dispatch`, (2) временный
  `schedule: cron: "*/15 * * * *"` добавлен в `satellite_pipeline.yml` как
  мост — см. «На горизонте», убрать после подтверждения `git pull` на
  телефоне.
- **Побочная находка, НЕ связанная с этим рефакторингом** (по git-истории
  файла — не менялся с 28 июня, за два месяца до сегодняшних правок):
  `forecast_analysis_claude.json` не обновлялся с 2026-06-28 — Claude-анализ
  не запускался почти два месяца, хотя Gemini исправно работает. Возможная
  зацепка: `data/ai_schedule.json` (общий, БЕЗ суффикса) содержит
  `model_triggers: [{"model": "ICON EU", "provider": "gemini"}]` — то есть
  триггер Gemini, а `data/ai_schedule_gemini.json` (С суффиксом `_gemini`)
  содержит `model_triggers: ["ECMWF IFS"]` + дневной `time_points` (10:05
  UTC) — то есть похоже на триггер Claude. Имена файлов, похоже, не
  соответствуют их реальному содержимому — не расследовано глубже (нужно
  читать `generate_ai_analysis.py` целиком, ~73KB, отдельная задача). См.
  «На горизонте».

## Технические детали (проверено, работает)

- **Реальные внешние зависимости по грепу импортов** (проверено построчно,
  не по памяти) — "остающиеся" в `full_pipeline.yml` скрипты:
  `calc_model_bias_cloud.py`/`calc_weights.py`/`pws_sync.py`/
  `calibrate_pws_pressure.py`/`fetch_hmcbas_telegram.py`/`update.py` —
  только stdlib; `marine_history.py` — `requests`; `nearby_precip.py` —
  `requests`+`numpy`+`PIL`. "Уехавшие" в `ai_pipeline.yml`:
  `generate_ai_analysis.py`/`verification.py` — только stdlib+`edge_tts`;
  `make_blocks_cloud.py`/`make_blocks_gemini_cloud.py` — `edge_tts`+`PIL`;
  `make_video.py` — `PIL` (+ ffmpeg как внешний бинарник, + шрифт Carlito
  для рендера текста, подтверждено содержимым отдельного `make_video.yml`).
  Ни один из "остающихся" скриптов `scipy`/`edge_tts` не использует — оба
  убраны из `full_pipeline.yml` целиком, не просто "на всякий случай"
  оставлены.
- **`if: always()` vs `if: success()`-гейт на диспетч-шагах** — не одно и
  то же решение, разные категории шагов. `always()` корректен для шагов
  "передай эстафету следующей стадии цепочки" (следующая стадия сама
  самодостаточна и не доверяет "что-то только что случилось", а проверяет
  СВОЁ состояние — так у всех трёх переходов в цепочке). `success()`-гейт
  обязателен для шагов, которые ЧИТАЮТ "just_triggered"/"pending"-флаги из
  файлов состояния — иначе stale-чтение при отменённом/skipped прогоне
  повторяет старые данные (см. инцидент 2026-08-18, `eumetsat.md`). Спутать
  категории — воспроизвести тот же класс бага.
- **`make_video.yml` (отдельный существующий workflow, без изменений в
  этом рефакторинге)** — триггерится `push: paths: ['data/blocks/blocks_meta.json', 'data/blocks/*.mp3']`, рендерит `data/forecast_video.mp4` для Claude. Триггер сработает независимо от того, ИЗ какого job'а пришёл push (раньше — `gh_pipeline.py`, теперь — `gh_ai_pipeline.py`) — GitHub не различает источник push для этого типа триггера, менять `make_video.yml` не понадобилось.
- **`scripts/trigger_gh_pipeline.sh` выполняется ЛОКАЛЬНО на телефоне**
  (Termux, checkout в `/storage/emulated/0/Documents/weather`), не
  скачивается заново при каждом запуске job 1001 — правка через GitHub
  API обновляет только репозиторий, эффект на телефоне только после
  `git pull` в этой папке. Единственный файл в проекте с таким свойством
  (все остальные скрипты выполняются в облаке, на checkout GitHub Actions).

## На горизонте

- **[ТРЕБУЕТСЯ ДЕЙСТВИЕ РУСЛАНА, но не горит]** `git pull` в `/storage/emulated/0/Documents/weather` на телефоне — без этого job 1001 продолжит диспетчить `full_pipeline.yml` напрямую (старое поведение). Пока НЕ сделан — временный `schedule: cron: "*/15 * * * *"` в `satellite_pipeline.yml` держит спутниковый модуль живым все эти циклы (добавлено 2026-08-21 после обнаружения 8.5-часовой дыры, см. ретроспективу выше). **После `git pull` этот cron надо убрать** — иначе спутниковый будет получать двойной триггер (и от телефона, и от cron) — безвредно, но лишняя нагрузка/лишние прогоны. Раньше телефон дёргал `full_pipeline.yml`, теперь должен дёргать `satellite_pipeline.yml` — это единственное, что меняется на устройстве, сам скрипт `trigger_gh_pipeline.sh` уже обновлён в репозитории.
- Найти реальную причину, почему Claude-анализ не запускался с 28 июня (см. находку про `ai_schedule.json`/`ai_schedule_gemini.json` выше) — не связано с сегодняшним рефакторингом, но раз обнаружено — стоит закрыть отдельной сессией. Начать с чтения `generate_ai_analysis.py` целиком (не читался в этой сессии — не требовался для выноса AI-блока как такового, только его вызов извне).
- Выключатель верификации для Claude (отложено, из прошлых сессий)
- Серверная коррекция bias (`apply_bias()` вызывается без bias в `build_snapshot()` — клиентский `applyBiasClient` −0.362°C недостаточен для gap 2–4°C)
