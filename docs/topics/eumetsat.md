# Тема: Спутниковый пайплайн EUMETSAT

_Последнее обновление: 2026-08-02 (фикс радиуса station_state в GeoColour)_

## Что это
Спутниковый модуль проекта верификации погоды Одессы: карты и анализ облачности на базе EUMETSAT WMS.

## Файлы
- `eumetsat.html` — интерактивная карта Leaflet с анимированными WMS-слоями EUMETSAT
- `eumetsat.js` — логика карты
- `nearby.html` / `nearby_precip.js` — карточный анализ облачного движения/прогноза, только EUMETSAT (PWS-сенсоры и RainViewer удалены из этого блока)
- `scripts/eumetsat_cloud_forecast.py` — бэкенд-расчёт блока "Облачность": classification (clear/variable/cloud), движение, тренды density/height/shape
- `scripts/field_motion_common.py` — общие константы проекции тайла (CENTER_LAT/LON, KM_PER_PX и т.д.), используется несколькими eumetsat_*_motion.py скриптами

## Технические детали (проверено, работает)
- Endpoint: `https://view.eumetsat.int/geoserver/wms`
- CRS: `CRS:84` (НЕ EPSG:3857), bbox в порядке `lon,lat`
- Центр тайла: Одесса (46.4406, 30.7703), окно ±2.5° (HALF_WINDOW_DEG), 400×400px
- Масштаб: ~0.96 км/px по X, ~1.39 км/px по Y
- Рабочие слои: `msg_fes:clm`, `msg_fes:cth`, `msg_fes:h60b`, `msg_fes:gii_kindex`, `msg_fes:ir108`, `msg_fes:ir039`, `mtg_fd:li_afa`, `mtg_fd:rgb_geocolour`, `mtg_fd:ir105_hrfi`
- Частота слоёв: `msg_fes:*` — 15 мин; `mtg_fd:li_afa` — 5 мин; `mtg_fd:rgb_geocolour` — 10 мин
- `time=None` (latest) часто отдаёт дубль последнего явного тайм-стампа (publication lag)
- `mtg_fd:*` слои без nearestValue-снэппинга → `build_time_steps()` выравнивает по границам шага
- GetLegendGraphic для mosaic-слоёв → XML-ошибка → используются статические HTML-легенды
- CLM классификация: nearest-color к 3 анкерам — `clear_water`(0,0,255), `clear_land`(0,170,0), `cloud`(255,255,255)

## Открытые задачи
- [ ] Уточнить WMS-имя нового слоя MTG Cloud Top Temperature and Height (CTTH), чтобы заменить устаревший `msg_fes:cth` на `eumetsat.html`

## История решений / фиксов
- PWS-сенсоры и RainViewer убраны из `nearby.html` — оставлен только EUMETSAT как источник
- **2026-08-02: пофикшен радиус для `current_state`.** Баг: `current_state` (clear/variable/cloud "над станцией") считался по доле облачных пикселей в LOCAL_RADIUS_KM=50км — том же радиусе, что используется для регионального ТРЕНДА (density/height/shape). Живой кейс подтверждён числами по буферу: 0% облачности в радиусе 0-10км от станции, но 25.3% в радиусе 50км (стоящее почти на месте облако 15-50км утаскивало долю за порог 0.15 → "переменная облачность", хотя прямо над станцией было чисто). Решение: добавлен отдельный `STATE_RADIUS_KM=12` только для `current_state`; `LOCAL_RADIUS_KM=50` остался для трендов. Проверено на реальных данных буфера (`data/eumetsat_cloud_buffer.npz`): после фикса fraction на 12км = 0.021 → clear (было 0.253 → variable на 50км). Закоммичено в `scripts/eumetsat_cloud_forecast.py`.
- Способ диагностики бага: скачали `data/eumetsat_cloud_buffer.npz` (бинарный буфер 9 кадров CLM+CTH) через Contents API, распаковали в numpy локально, посчитали area_fraction на разных радиусах от центра тайла — это надёжнее, чем визуально читать цвета на скриншотах (первая гипотеза "облако над морем в 50км" была неверной по геометрии, ошибку поймали только числами).

## Известные подводные камни при отладке
- Скриншоты интерфейса (Leaflet, зум) НЕ дают надёжной привязки пиксель→км — для количественной проверки лучше тянуть сырой буфер/JSON из `data/` и считать в sandbox, а не читать цвета на глаз
- `data/eumetsat_cloud_forecast.json` — снапшот последнего результата, полезен для быстрой сверки чисел без похода в буфер


## 2026-08-02: закрыт вопрос MTG CLM/CTTH
Проверили `GetCapabilities` (список слоёв `mtg_fd:*`) — прямого аналога `msg_fes:clm`/`msg_fes:cth` для MTG на публичном WMS `view.eumetsat.int` НЕТ. Есть только RGB-композиты: `rgb_cloudphase`, `rgb_cloudtype`, `rgb_geocolour`, `rgb_truecolour`, `rgb_dust`, `rgb_fog`, `rgb_snow`, `rgb_firetemperature`. Настоящие численные MTG CLM/CTTH существуют только как L2 NetCDF-продукты через EUMETSAT Data Store (`data.eumetsat.int`, другой протокол — eumdac/API, не GetMap) — отдельная задача уровня "новая интеграция", не правка URL.
Дополнительно: EUMETSAT продолжает параллельно генерировать MSG Cloud Mask/CTH "until further notice, or until end of MSG 0° services" — миграция не горит.
Решение: задачу закрыть. `msg_fes:clm`/`msg_fes:cth` остаются источником для `eumetsat_cloud_forecast.py`. RGB-слои MTG уже используются отдельно и по назначению:
  - `rgb_cloudphase` + `rgb_cloudtype` → `scripts/eumetsat_cloud_phase_type.py` (фаза/грубый тип облаков, HSV-анкеры "на глаз", не откалибровано — см. `unclassified_fraction` в debug-файле)
  - `rgb_geocolour` → `scripts/eumetsat_geocolour_motion.py` (движение + area-fraction круглосуточно, день/ночь разные ветки классификации, с фильтром городских огней)


## 2026-08-02: тот же баг радиуса — в ИК-блоке (mtg_fd:ir105_hrfi), плюс баг без-порогового "облака"
`eumetsat_ir_motion.py` содержал ДВЕ проблемы, найденные по живому скриншоту (полностью однородный тёмный кадр, "ясно" по факту):
1. `station_state` считался в LOCAL_RADIUS_KM=50 (той же маске, что и региональный тренд area/brightness) — тот же класс бага, что чинили в `eumetsat_cloud_forecast.py`. Фикс: добавлен общий `STATE_RADIUS_KM=12` и `fc.station_area_mask()` в `field_motion_common.py` (переиспользуемый), `station_state` теперь считается по нему.
2. `cloud_mass_distance_km` ("Основная облачная масса") находился ВСЕГДА — порог был 90-й перцентиль ВНУТРИ кадра, у которого нет абсолютного пола: даже в полностью однородной сцене без единого настоящего облака "10% самых тёплых пикселей" всё равно где-то есть (рельеф/берег/обычный прогрев) и `nearest_of_type()` находил связный blob ≥40px и репортил его как "облачную массу" с движением/скоростью. Фикс: добавлена проверка контраста — 90-й перцентиль должен отличаться от медианы кадра минимум на `MIN_CLOUD_CONTRAST_SIGMA=1.2` std кадра, иначе `cloud_mass_distance_km=None` + `cloud_mass_verdict="значимой облачной массы в поле зрения нет"`.
Также по просьбе убран блок "Область анализа" (окно/центр/радиус) из рендера ИК-блока в `nearby_precip.js` — избыточная техническая информация.

**Открытый вопрос на будущее**: ~~у `eumetsat_geocolour_motion.py` (RGB, day/night) station_state тоже может считаться по общему `fc.local_area_mask()` (50км) — не проверено, надо будет свериться по аналогии, если появится похожая жалоба на этот блок.~~ Подтвердилось (см. ниже).

## 2026-08-02: тот же баг радиуса — в блоке GeoColour (mtg_fd:rgb_geocolour)
Подтверждена ровно та же проблема, что чинили в CLM и IR: `station_state` в `eumetsat_geocolour_motion.py` считался по `fc.local_area_mask()` (LOCAL_RADIUS_KM=50, та же маска, что и региональный тренд area_fraction). Фикс: добавлена отдельная `state_fracs` по `fc.station_area_mask()` (STATE_RADIUS_KM=12), `station_state`/`station_area_fraction` теперь считаются по ней; `area_fracs` (50км) остался только для регионального тренда/гейта motion (`MIN_CLOUD_FRACTION_FOR_MOTION`).
Второй IR-баг (без-порогового "облака" из-за перцентиль-порога) сюда НЕ относится: `_classify_cloud()` в GeoColour и так строит `is_cloud` через абсолютную HSV-классификацию (день: низкая S/высокая V; ночь: голубой hue-диапазон), а не через относительный перцентиль внутри кадра — `nearest_of_type()` уже получает физически осмысленную бинарную маску, "пустого" ложного blob'а там в принципе не возникает.
Закоммичено в `scripts/eumetsat_geocolour_motion.py`.

