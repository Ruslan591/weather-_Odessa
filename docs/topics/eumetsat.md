# Тема: Спутниковый пайплайн EUMETSAT

_Последнее обновление: 2026-08-19 (поздний вечер)_

Подробная история решений, багов и калибровок — `docs/topics/eumetsat_archive.md`
(датированный лог с 2026-08-02, вынесен туда 2026-08-18, когда этот файл
разросся до ~4500 строк). В обычной сессии архив читать не нужно — только
если требуется восстановить происхождение конкретного решения/константы.

## Что это

Спутниковый модуль проекта верификации погоды Одессы — карты и анализ
облачности на базе EUMETSAT WMS. Два независимых направления:
1. **`eumetsat.html`** — интерактивная Leaflet-карта с анимированными WMS-слоями (обзорная визуализация).
2. **`nearby.html` / `nearby_precip.js`** — карточный анализ: облачность, осадки, гроза, **отслеживание фронтов** — построен на данных near-tier (~192-278км вокруг Одессы) и west-tile (~500км к СЗ, зона раннего предупреждения).

## Архитектура (кратко)

- **Near-tier** (центр — Одесса, окно ±2.5°/HALF_WINDOW_DEG, 400×400px): `eumetsat_cloud_forecast.py` (CLM), `eumetsat_geocolour_motion.py` (GC-моушен), `eumetsat_ir_motion.py` (ИК-моушен), `eumetsat_precip_forecast.py`/`precip_motion.py` (осадки, слой `msg_fes:h60b`), `eumetsat_lightning_forecast.py` (гроза).
- **West-tile** (bbox 23.6°-28.6°E, зона раннего предупреждения, ~500км): `eumetsat_west_watch.py` — CLM+IR+GeoColour, только frontlike-кандидаты. **Precip-канала для west НЕТ** (см. «На горизонте»).
- **Треки фронтов**: `eumetsat_frontal_track.py` объединяет near+west кандидатов (`_merge_near_west()`, дедуп 80км), поле `tile` на каждой точке трека. Публикует `data/eumetsat_frontal_track.json` → `eumetsat_target_summary.py` пробрасывает как есть → фронтенд.
- **Наземная верификация**: `ground_station_selector.py` (станция впереди/позади трека) + `ground_station_obs_fetch.py` (SYNOP/BUFR) → поля `ahead_station`/`behind_station` на каждом треке.
- **Снимки для nearby.html**: с 2026-08-18 все 3 снимка near-tier (CLM/GC/ИК) синхронизированы на ОДНОМ таймстемпе — пишет их `eumetsat_cloud_forecast.py` (гейт 15 мин, частота CLM). `geocolour_motion.py`/`ir_motion.py` снимки больше НЕ пишут (только свой моушен-анализ на гейте 10 мин). West-снимки аналогично синхронизированы внутри `eumetsat_west_watch.py`.
- **Оркестратор**: `scripts/gh_satellite_pipeline.py` — вызывается GitHub Actions (`full_pipeline.yml`) по `workflow_dispatch`, триггерит телефон (`termux-job-scheduler`, job 1001, каждые 15 мин). Порядок важен: cloud_forecast → frontal_track → ... → geocolour_motion/ir_motion.

## Технические детали (проверено, работает)

- Endpoint: `https://view.eumetsat.int/geoserver/wms`, CRS `CRS:84` (НЕ EPSG:3857), bbox `lon,lat`
- Near-tier центр: Одесса (46.4406, 30.7703), окно ±2.5°, 400×400px, ~0.96км/px X, ~1.39км/px Y
- Слои и живой шаг (подтверждено через `GetCapabilities` 2026-08-18): `msg_fes:clm` — `PT15M`, `mtg_fd:ir105_hrfi` — `PT10M`, `mtg_fd:rgb_geocolour` — ~10 мин. Оба проверенных слоя — `nearestValue="1"` (сервер сам снаппит к ближайшему кадру при неточном времени).
- `time=None` (latest) часто отдаёт дубль последнего явного тайм-стампа (publication lag)
- `mtg_fd:*` слои без nearestValue при явном запросе времени вне сетки — `build_time_steps()` выравнивает по границам шага (для near-tier моушен-анализа, не для одиночных снимков)
- CLM классификация: nearest-color к 3 анкерам — `clear_water`(0,0,255), `clear_land`(0,170,0), `cloud`(255,255,255)
- Порог "system" vs "local" объекта: `LARGE_SYSTEM_AREA_KM2 = 300`. Порог frontlike по вытянутости: `FRONTLIKE_ASPECT_THRESHOLD = 2.2` (near-tier) / отдельная логика в west_watch.py.
- IR/GC подтверждение кандидата (`_west_confirmed()`, `eumetsat_frontal_track.py`): GC первичен, ИК — вето только при сильном противоречии (`IR_VETO_SIGMA = -1.0`). См. «На горизонте» — порог не откалиброван по истории, только по одному живому случаю 2026-08-18.

## Открытые задачи / На горизонте (обновлено 2026-08-19)

- **[РЕШЕНО 2026-08-19] 5 дублирующихся push-уведомлений об осадках вечером 2026-08-18 — та же причина, что и пропущенный фронт.** Тревога (`alert=true`, "уже у города", ETA 0.0, 8.0км, 89%) сработала ОДИН раз — коммит `a9212013`, 16:20 UTC. Дальше, ровно в окно EUMETSAT-разрыва (16:26-17:45 UTC), два независимых источника диспетча — explicit-dispatch из `full_pipeline.yml` (каждый цикл, ~15 мин) и self-redispatch цепочка тревоги (`eumetsat_alert_redispatch.yml`, каждые 5 мин, пока `alert=true`) — били в один `concurrency: group: satellite-pipeline`. `cancel-in-progress: false` не отменяет ИДУЩИЙ прогон, но отменяет ОЖИДАЮЩИЙ в очереди при новом диспетче — при частых диспетчах это дало каскад: 8 отменённых прогонов подряд за час (16:26-17:33 UTC). У каждого отменённого прогона реальный шаг `Запуск спутникового пайплайна` был `skipped` (не успевал выполниться), но 4 шага ниже стояли на `if: always()` и всё равно выполнялись — читали СТАРЫЙ `eumetsat_alert_state.json` (с 16:20, `just_triggered: true`) и: (1) слали push повторно, (2) сами же диспетчили следующее звено redispatch-цепочки, поддерживая шторм. Итог: 5 дублей одного и того же протухшего алерта, и ни одного уведомления "отпустило" — по данным пользователя дождь всё ещё "уже у городе", хотя по факту к 17:45 UTC уже "почти стоит на месте" (81%, alert=false).
  Сделано:
  1. `satellite_pipeline.yml`: шагу `Запуск спутникового пайплайна` добавлен `id: run_pipeline`; у всех 4 шагов ниже (push осадки/гроза/health, решение о redispatch) `if: always()` → `if: steps.run_pipeline.outcome == 'success'` — не читают/не действуют на основе данных, которые в этом прогоне не пересчитывались.
  2. `full_pipeline.yml` и `eumetsat_alert_redispatch.yml`: перед диспетчем `satellite_pipeline.yml` — GET `.../runs?status=in_progress` и `?status=queued`; если что-то уже есть, диспетч пропускается (защита от шторма в первую очередь, а не только симптоматика на стороне push-шагов).

- **[РЕШЕНО 2026-08-18/19] Слепое окно источника пропустило реальный фронт — исправлено.** Исходная находка: с 16:26 до 17:45 UTC EUMETSAT ~75 мин не публиковал новые кадры `msg_fes:clm`, `eumetsat_cloud_forecast.py` корректно детектил это и не коммитил (защита от дублей сработала штатно), но именно в это окно фронт (трек 135) прошёл над станцией незамеченным — история `[SKIP]` терялась (только в перезаписываемом `*_debug.json`).
  Сделано:
  1. `fc.log_skip_event()` (`field_motion_common.py`) — постоянный append-only лог `data/eumetsat_skip_log.jsonl` (кап 1000 строк). Подключён во всех 6 скриптах с инкрементальным буфером: `eumetsat_cloud_forecast.py`, `eumetsat_cloud_phase_type.py`, `eumetsat_geocolour_motion.py`, `eumetsat_ir_motion.py`, `eumetsat_precip_motion.py`, `eumetsat_west_watch.py` (у последнего skip раньше был вообще тихим — ни print, ни файл).
  2. `fc.record_pipeline_health()` — счётчик подряд идущих `source_stale`/`duplicate_frame` НА СКРИПТ в `data/eumetsat_pipeline_health.json` (сбрасывается на успехе). `next_frame_not_ready`/`capabilities_unavailable` в счётчик не входят — единичные сетевые сбои, шумят и сами разрешаются.
  3. `check_pipeline_health_alert()` в `gh_satellite_pipeline.py` (вызывается в конце `main()`, до `git_push_satellite()`) — порог 3 подряд (~45 мин простоя источника) на любом скрипте → `data/eumetsat_pipeline_alert_state.json` (`just_triggered`/`just_recovered`, паттерн как у `eumetsat_alert_state.json`).
  4. `.github/workflows/satellite_pipeline.yml` — новый ntfy-шаг на **отдельном топике** `odessa-pipeline-health-k7m2q9wx4h` (НЕ `odessa-storm-x7k2m9qp4h` — это про здоровье пайплайна, не про погоду): пуш на `just_triggered` (какие скрипты встали, с какого времени) и на `just_recovered` (отпустило).
  Оба новых JSON-файла зарегистрированы в whitelist `git_push_satellite()`.
- **[РЕШЕНО 2026-08-19] Разброс длительности прогона пайплайна 1.6–20.6 мин.** Уточнение: 600с-таймаут, который упоминался раньше — это `eumetsat_anim_render.py`, но он выключен из цикла ещё 16.08 (вызов закомментирован в `main()`), к разбросу отношения не имел. Реальная причина — `fc.fetch_tile()`/`fc.fetch_map_custom()` (`field_motion_common.py`): `TIMEOUT=25`с × `retries=2` = до 54с на один неотвечающий тайл, а по всем скриптам пайплайна суммарно ~25 таких вызовов за прогон — несколько медленных тайлов подряд легко давали 15-20 мин. Изменено: `TIMEOUT=25→10`, `retries=2→1` (везде, без явных переопределений по коду — было только дефолтное значение). Худший случай на один тайл: 54с → 10с. Компромисс: единичный транзиторный сетевой сбой (не "сцена не готова", а именно короткий глюк соединения) чаще не переживёт отсутствие ретрая — но при 15-минутном каденсе следующий прогон почти наверняка заберёт кадр нормально, а зависающие на 20 мин прогоны мешали больше (в т.ч. частично разгоняли шторм диспетчей, см. пункт про дубли push выше).
- Проследить за первыми прогонами: появился ли west-трек с новой логикой `_west_confirmed()`; не переусердствовал ли смягчённый фильтр (`IR_VETO_SIGMA=-1.0` выбран на глаз).
- Precip-детекция для west-тайла отсутствует в принципе — нужен отдельный канал (bbox/layer/гейт), аналогично `eumetsat_west_watch.py` для CLM/GC/ИК, если нужно знать про осадки ДО захода объекта в near-tier окно.
- Задача "полноценное отслеживание движения фронтов, включая погодные условия": скорость/направление есть, осадки/молнии — near-tier only, наземная верификация (ahead/behind SYNOP) есть. Не хватает: явной дельты температуры/ветра между ahead/behind станциями (сейчас только сырые наблюдения по обе стороны, не выведенная разница).
- BUFR-данные — интегрированы в `update_local.py`, отображение в `index.html` не сделано.
- Сумеречная контаминация (`is_daytime()` без расчёта угла Солнца) — затрагивает все RGB-композиты на рассвете/закате, влияет на надёжность GC-классификации в эти часы. Отложено, держать в виду (могло сыграть роль в разборе 2026-08-18, см. архив).

## Известные подводные камни при отладке

- Верификация после каждого коммита обязательна: повторный GET по API через `api.github.com` (НЕ `raw.githubusercontent.com` — там CDN-задержка несколько минут), не доверять только ответу PUT.
- Перед PUT — всегда GET текущего sha (иначе 422 конфликт).
- Скриншоты интерфейса (Leaflet, зум) не дают надёжной привязки пиксель→км — для количественной проверки тянуть сырой буфер/JSON из `data/` и считать в sandbox.
- `py_compile` не ловит «потерянные» функции при синтаксически корректном результате → дополнительно `ast.parse` + перечисление `FunctionDef` перед каждым пушем Python. JS — `node --check`.
- Временны́е метки в `data/eumetsat_*.json` — UTC (`Z`). Конвертировать в Europe/Kiev (UTC+3 летом) перед сравнением с PWS/локальным временем — повторяющаяся ошибка.
- Кэш `scripts/__pycache__` на FUSE-Android может не инвалидироваться → `rm -rf scripts/__pycache__` при подозрении на старый код.
- Не делать многофайловые изменения через API, пока телефон одновременно может пушить через git — сначала остановить job 1001.

## Файлы (ключевые)

- `nearby.html` / `nearby_precip.js` — фронтенд карточек (облачность/осадки/гроза/фронты)
- `eumetsat.html` / `eumetsat.js` — обзорная Leaflet-карта
- `scripts/field_motion_common.py` — общие константы/функции проекции, WMS-фетч, оверлеи (используется почти всеми eumetsat_*.py)
- `scripts/eumetsat_cloud_forecast.py` — near-tier CLM + синхронизированные снимки CLM/GC/ИК
- `scripts/eumetsat_geocolour_motion.py`, `eumetsat_ir_motion.py` — near-tier моушен-анализ (буфер, скорость, area_fraction)
- `scripts/eumetsat_west_watch.py` — west-tile кандидаты (CLM+IR+GC, синхронизированные снимки)
- `scripts/eumetsat_frontal_track.py` — объединение near+west, треки во времени, IR/GC-фильтр, has_precip/has_lightning/ahead_station/behind_station
- `scripts/eumetsat_target_summary.py` — агрегатор для фронтенда
- `scripts/ground_station_selector.py`, `ground_station_obs_fetch.py` — наземная SYNOP/BUFR верификация
- `scripts/eumetsat_precip_forecast.py`, `precip_motion.py`, `eumetsat_lightning_forecast.py` — осадки/гроза (near-tier only)
- `scripts/gh_satellite_pipeline.py` — оркестратор всего вышеперечисленного
