/* =========================================================
   NEARBY_PRECIP.JS — блок "осадки/гроза поблизости" на pws.html
   Источник: data/nearby_precip.json (пишет scripts/nearby_precip.py раз
   в ~15 мин из RainViewer радара, см. докстринг скрипта).

   ВАЖНО: RainViewer ToS требует видимую атрибуцию "Weather data by
   RainViewer" там, где эти данные показываются пользователю — она есть
   в футере карточки ниже, не убирать при рефакторинге.

   Ниже, для сравнения, добавлен блок EUMETSAT (data/eumetsat_point.json,
   пишет scripts/eumetsat_point.py). ЭТО СЫРЫЕ ЗНАЧЕНИЯ — расшифровка
   (категория облачности/метры/число вспышек) ещё не откалибрована по
   живому ответу сервера, см. докстринг eumetsat_point.py. Показываем как
   диагностику "для сравнения", а не как готовую метрику.
========================================================= */

let _nearbyPrecipData      = null;
let _nearbyPrecipFetchedAt = 0;
let _eumetsatPointData      = null;
let _eumetsatPointFetchedAt = 0;

async function loadNearbyPrecip(){
    if(Date.now() - _nearbyPrecipFetchedAt < 10 * 60000) return; // раз в 10 мин
    _nearbyPrecipFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/nearby_precip.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _nearbyPrecipData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _nearbyPrecipFetchedAt = 0;
    }
}

async function loadEumetsatPoint(){
    if(Date.now() - _eumetsatPointFetchedAt < 10 * 60000) return; // раз в 10 мин
    _eumetsatPointFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_point.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatPointData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatPointFetchedAt = 0;
    }
}

function _nearbyFmt(o){
    if(!o) return null;
    const km = Number(o.distance_km).toLocaleString("ru-RU");
    return `${km} км (${o.compass})`;
}

const CLM_LABELS = {
    clear_water: "ясно (над водой)",
    clear_land: "ясно (над сушей)",
    cloud: "облачно",
};

function _eumetsatRow(label, layerData){
    if(!layerData) return `<div class="row"><div class="label">${label}</div><div class="value">—</div></div>`;
    if(layerData.error || !layerData.rgb){
        return `<div class="row"><div class="label">${label}</div><div class="value">нет данных</div></div>`;
    }
    let shown;
    if(layerData.category){
        shown = CLM_LABELS[layerData.category] || layerData.category;
    } else if(layerData.hue_bucket){
        shown = layerData.hue_bucket;
    } else {
        shown = `RGB(${layerData.rgb.join(",")})`;
    }
    return `<div class="row"><div class="label">${label}</div><div class="value">${shown}</div></div>`;
}

function renderNearbyPrecipCard(){
    const card = document.getElementById("nearbyPrecipCard");
    if(!card) return;
    const d = _nearbyPrecipData;
    if(!d){ card.innerHTML = ""; return; }

    const radiusKm = d.coverage_radius_km ? Math.round(d.coverage_radius_km) : null;
    const notFoundStr = radiusKm ? `не обнаружено в радиусе ~${radiusKm} км` : "нет данных";

    const precipStr  = _nearbyFmt(d.nearest_precip)      || notFoundStr;
    const thunderStr = _nearbyFmt(d.nearest_thunderstorm) || notFoundStr;

    let ageStr = "—";
    if(d.radar_age_min != null){
        ageStr = d.radar_age_min < 1 ? "меньше минуты назад" : `${Math.round(d.radar_age_min)} мин назад`;
    }

    let eumetsatBlock = "";
    const e = _eumetsatPointData;
    if(e && e.layers){
        eumetsatBlock = `
        <div class="small muted" style="margin-top:12px; border-top:1px solid #333; padding-top:8px;">
            Спутник EUMETSAT в точке Одессы — для сравнения (облачность откалибрована; высота облаков и молнии — приблизительно, по позиции на цветовой шкале):
        </div>
        ${_eumetsatRow("Облачность (Cloud Mask)", e.layers.clm)}
        ${_eumetsatRow("Высота облаков (CTH)", e.layers.cth)}
        ${_eumetsatRow("Молнии (Flash Area/5мин)", e.layers.li_afa)}
        <div class="small muted" style="margin-top:4px;">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
    }

    card.innerHTML = `
        <div class="cardTitle">Осадки и гроза поблизости</div>
        <div class="row">
            <div class="label">Ближайшие осадки</div>
            <div class="value">${precipStr}</div>
        </div>
        <div class="row">
            <div class="label">Гроза (прокси по радару)</div>
            <div class="value">${thunderStr}</div>
        </div>
        <div class="small muted" style="margin-top:8px;">
            Радар обновлён: ${ageStr}. Признак грозы — отражаемость ≥45 dBZ на радаре,
            это НЕ детекция реальной молнии, а эвристика по силе осадков.
        </div>
        <div class="small muted" style="margin-top:4px;">
            Weather data by
            <a href="https://www.rainviewer.com/" target="_blank" rel="noopener" style="color:#72c8ff;">RainViewer</a>
        </div>
        ${eumetsatBlock}`;
}
