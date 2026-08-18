# Тема: Полный облачный пайплайн (verification + AI + PWS)

_Последнее обновление: 2026-08-18 (создание файла, план выноса AI-блока)_

Основной (не спутниковый) пайплайн проекта — сравнение 8 ансамблевых
моделей против SYNOP/PWS, AI-анализ прогноза (Claude + Gemini), синк PWS,
морская история. Спутниковый модуль — отдельная тема, см.
`docs/topics/eumetsat.md`.

## Что это

- **Workflow:** `.github/workflows/full_pipeline.yml`, название в GitHub Actions — "Полный облачный пайплайн (verification + AI + PWS)"
- **Дирижёр:** `scripts/gh_pipeline.py` (облачный аналог телефонного `check_model_runs.py` — телефонную версию НЕ трогать, отдельное решение)
- **Триггер:** только `workflow_dispatch`, собственного `schedule` нет специально — время держит телефон (`termux-job-scheduler`, тот же job, что и для спутникового пайплайна) через `scripts/trigger_gh_pipeline.sh`
- **Concurrency:** группа `full-pipeline`, `cancel-in-progress: false`
- **Timeout:** 45 минут

## Порядок выполнения (`gh_pipeline.py main()`)

1. Проверка прогонов 8 моделей (`MODELS` — ECMWF IFS, ICON EU, UKMO, Arpège, GFS, GRAPES + ещё 2, см. список в файле) через Open-Meteo meta API — сравнение с `data/model_history.json`
2. Если есть новые прогоны (`new_models`):
   - `calc_model_bias_cloud.py` — расчёт смещения моделей
   - `calc_weights.py` — веса моделей (без `LOCAL=1`, пишет через GitHub API сам)
   - `update_local.py --no-model` — обновление локальных данных
   - **AI-блок** (см. ниже — то, что планируется вынести)
   - `git commit + push`
3. Если новых прогонов нет: короткий путь (`update_local.py --no-model --no-fill`) + проверка "pending Gemini" (retry, если предыдущий вызов упёрся в rate-limit)
4. Каждый цикл, независимо от новых прогонов: `check_pws_sync()`, `check_pws_calibration()`, `check_marine_history()`, `check_nearby_precip()`, `check_hmcbas_telegram()` (`check_hmcbas_sea_temp()` отключён — виджет сайта стабильно отдаёт брак)
5. Финальный `git_push_history()` — т.к. `calibrate_pws_pressure.py`/`marine_history.py` пишут только в локальный checkout раннера, без явного push их изменения терялись бы при завершении job'а
6. `if: always()` шаг — явный `workflow_dispatch` API-вызов `satellite_pipeline.yml` (не полагается на встроенный `workflow_run` — задокументированно ненадёжен, ни разу не сработал на практике после выноса спутникового модуля 2026-07-26)

## AI-блок (текущее место — внутри `main()`, инлайн, НЕ отдельная функция)

Условие запуска: `new_models` непустой И `run_pipeline(new_models)` вернул `ok=True`.

1. `generate_ai_analysis.py --models <новые>` (+ `--force` если передан `--force-ai` в сам gh_pipeline.py) — Claude (`claude-sonnet-4-5`, триггер ECMWF IFS) + Gemini (`gemini-2.5-flash`, триггер ICON EU), расписание — `data/ai_schedule.json`, читается ВНУТРИ `generate_ai_analysis.py` (не в gh_pipeline.py — это важно для выноса, см. план ниже)
2. Если `data/forecast_analysis_claude.json.changed == true` → `make_blocks_cloud.py`
3. Если `data/forecast_analysis_gemini.json.changed == true` → `make_blocks_gemini_cloud.py` → (если ок) `make_video.py gemini`
4. Отдельная ветка (когда новых моделей НЕТ, но `forecast_analysis_gemini.json.pending == true` — предыдущий вызов Gemini упёрся в rate-limit): `generate_ai_analysis.py --force-gemini` → тот же каскад `make_blocks_gemini_cloud.py` → `make_video.py gemini`

Секреты, используемые AI-блоком: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (передаются в `full_pipeline.yml` как env всего шага "Запуск облачного пайплайна", не только AI-части).

## Известные детали/подводные камни

- `deploy.yml` — проверено 2026-08-18: `paths-ignore` ОТСУТСТВУЕТ, триггерится на любой push в `main`. Упомянутая ранее проблема "автопайплайн не триггерит передеплой" на сегодня неактуальна (либо патч применён, либо описание было устаревшим — в любом случае текущее состояние проверено вживую, не по памяти).
- `workflow_run` для запуска `satellite_pipeline.yml` в самом `satellite_pipeline.yml` оставлен как резервный путь (не мешает), но реально спутниковый пайплайн запускается ТОЛЬКО через явный `curl -X POST .../dispatches` из `full_pipeline.yml`.
- AI-каскад (`make_blocks_*` → `make_video.py`) завязан на `changed`/`pending` флаги в JSON-файлах результата, а не на код возврата напрямую — это state-машина через файлы, тот же паттерн, что у `eumetsat_alert_state.json.just_triggered` в спутниковом пайплайне.
- `verification.py` — общий модуль, импортируется `generate_ai_analysis.py` напрямую (`import verification`), должен быть доступен в PYTHONPATH/cwd = BASE_DIR.

## План: вынести AI-блок в отдельный workflow (не начато, обсуждалось 2026-08-18)

**Мотивация (озвучена пользователем):** та же, что была у спутникового
модуля при выносе 2026-07-26 (см. докстринг `gh_pipeline.py`) — AI-блок
утяжеляет и удлиняет этот пайплайн, хочется отдельный workflow по
образцу `satellite_pipeline.yml`.

**Прямой аналог уже есть в этом же репо** — 2026-07-26 спутниковый модуль
был вынесен из этого же `gh_pipeline.py` в `gh_satellite_pipeline.py` +
`satellite_pipeline.yml` по такой схеме:
- Отдельный workflow, `workflow_dispatch` + опциональный `workflow_run` (ненадёжный, держится как резерв)
- `full_pipeline.yml` явно триггерит его через `curl -X POST .../dispatches` шагом `if: always()`, с `git commit` debug-ответа диспетча
- Своя `concurrency` группа, свой timeout, свой `git config` для коммитов бота
- Внутри — набор `check_eumetsat_*()` функций, каждая сама решает, нужна ли ей работа (сравнение с сохранённым состоянием) — то есть workflow дёргается КАЖДЫЙ цикл безусловно, а не только когда что-то точно изменилось

**Ключевое отличие AI-блока от спутникового модуля, которое надо решить
перед вынесением:** спутниковые `check_eumetsat_*()` полностью
самодостаточны — сами решают, свежие ли данные, no external input needed.
AI-блок же управляется переменной `new_models` — списком моделей с новым
прогоном, вычисленным ВЫШЕ по `main()` этого же файла (шаги 1-2), и
запускается ТОЛЬКО если `run_pipeline(new_models)` (calc_bias/weights/
update_local) отработал успешно. Это реальная зависимость по данным, не
просто по времени.

**Два варианта решения, оба рабочие — на выбор в момент реализации:**

1. **Передать `new_models` явно через `workflow_dispatch` input** (как
   `chain_depth` у `eumetsat_alert_redispatch.yml`) — `full_pipeline.yml`
   после успешного `run_pipeline()` дёргает
   `ai_pipeline.yml/dispatches` с `{"inputs":{"models":"ECMWF IFS,ICON EU"}}`,
   пустая строка если новых моделей не было (или шаг просто не вызывается
   в этом случае — тогда пропадает only-Gemini-retry путь, см. вариант 2).
2. **Сделать `gh_ai_pipeline.py` самодостаточным, как спутниковый** — дёргать
   его КАЖДЫЙ цикл безусловно (`if: always()`, без input), а внутри читать
   `data/model_history.json` + маркер "какие модели уже AI-проанализированы"
   (понадобится новый файл-флаг, например `data/_ai_last_analyzed.json`,
   т.к. сейчас `new_models` — временная переменная, нигде не персистится
   отдельно от истории) — тогда автоматически подхватывается и
   "pending Gemini retry" путь (просто ещё одно условие внутри), без
   входных параметров вообще. Ближе по духу к спутниковому прецеденту.

**Склоняюсь к варианту 2** (при реализации) — меньше связности между
workflow'ами, весь AI-пайплайн решает сам, нужна ли ему работа, точно как
`check_eumetsat_*()`. Понадобится доработать `gh_pipeline.py`, чтобы он
персистил список только что обнаруженных новых моделей (сейчас видно
из diff `model_history.json` до/после, но явного файла с "необработанным
AI списком" нет).

**Что переезжает в новый `gh_ai_pipeline.py`/`ai_pipeline.yml`:**
- Весь AI-блок целиком (см. секцию выше) — `generate_ai_analysis.py` вызовы,
  `make_blocks_cloud.py`/`make_blocks_gemini_cloud.py`, `make_video.py gemini`
- Расписание (`data/ai_schedule.json`) переезжает бесплатно — читается
  внутри `generate_ai_analysis.py`, не в `gh_pipeline.py`
- Секреты `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` — нужно прописать в новом workflow отдельно
- `verification.py` — нужен в PYTHONPATH нового job'а (тот же checkout, тот же `scripts/`, проблем быть не должно)

**Что остаётся в `gh_pipeline.py`/`full_pipeline.yml`:**
- Проверка прогонов моделей (шаг 1)
- `calc_model_bias_cloud.py` / `calc_weights.py` / `update_local.py` (шаг 2, verification-часть)
- PWS/морская история/nearby_precip/hmcbas-проверки (шаг 4)
- Явный dispatch `satellite_pipeline.yml` (без изменений)
- Новый явный dispatch `ai_pipeline.yml` (по аналогии)

**Не начато. Ничего из плана выше не реализовано** — это только зафиксированный
план для следующей сессии по этой теме.
