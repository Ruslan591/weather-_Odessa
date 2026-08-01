# Тема: Спутниковый пайплайн EUMETSAT

_Последнее обновление: 2026-08-02_

## Что это
Спутниковый модуль проекта верификации погоды Одессы: карты и анализ облачности на базе EUMETSAT WMS.

## Файлы
- `eumetsat.html` — интерактивная карта Leaflet с анимированными WMS-слоями EUMETSAT
- `eumetsat.js` — логика карты
- `nearby.html` / `nearby_precip.js` — карточный анализ облачного движения/прогноза, только EUMETSAT (PWS-сенсоры и RainViewer удалены из этого блока)

## Технические детали (проверено, работает)
- Endpoint: `https://view.eumetsat.int/geoserver/wms`
- CRS: `CRS:84` (НЕ EPSG:3857)
- bbox в порядке `lon,lat`
- Рабочие слои:
  - `msg_fes:clm`
  - `msg_fes:cth`
  - `msg_fes:h60b`
  - `msg_fes:gii_kindex`
  - `msg_fes:ir108`
  - `msg_fes:ir039`
  - `mtg_fd:li_afa`
  - `mtg_fd:rgb_geocolour`
  - `mtg_fd:ir105_hrfi`
- Частота обновления слоёв:
  - `msg_fes:*` — 15 мин
  - `mtg_fd:li_afa` — 5 мин
  - `mtg_fd:rgb_geocolour` — 10 мин
- `time=None` (latest) часто отдаёт дубль последнего явного тайм-стампа из-за publication lag
- `mtg_fd:*` слои НЕ имеют nearestValue-снэппинга (в отличие от `msg_fes`) → при несуществующих тайм-стампах ошибка `"cannot identify image file"`. Решение — `build_time_steps()` выравнивает по границам шага
- GetLegendGraphic для mosaic-слоёв возвращает XML-ошибку вместо картинки → используются статические HTML-легенды

## Открытые задачи
- [ ] Уточнить WMS-имя нового слоя MTG Cloud Top Temperature and Height (CTTH), чтобы заменить устаревший `msg_fes:cth` на `eumetsat.html`

## История решений
- PWS-сенсоры и RainViewer убраны из `nearby.html` — оставлен только EUMETSAT как источник
