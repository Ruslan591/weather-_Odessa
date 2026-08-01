# Тема: Спутниковый пайплайн EUMETSAT

_Последнее обновление: 2026-08-02_

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
