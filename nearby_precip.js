/* =========================================================
   NEARBY_PRECIP.JS — карточка "Анализ спутниковых снимков (EUMETSAT)"
   на nearby.html. Только спутниковый анализ (EUMETSAT), без PWS-датчиков
   и без радара RainViewer — по просьбе убрано всё остальное со страницы.

   Источники (пишут соответствующие scripts/eumetsat_*.py раз в 5-15 мин):
     data/eumetsat_cloud_forecast.json      — движение облачности (Cloud Mask)
     data/eumetsat_precip_forecast.json     — движение осадков (h60b)
     data/eumetsat_lightning_forecast.json  — движение грозовой активности (li_afa)
     data/eumetsat_geocolour_motion.json    — независимая оценка по текстуре
                                               HD true-color снимка (GeoColour RGB)
========================================================= */

const STATION_LABEL = "Одесса (СИНОП 33837)";

let _eumetsatForecastData      = null;
let _eumetsatForecastFetchedAt = 0;
let _eumetsatPrecipForecastData      = null;
let _eumetsatPrecipForecastFetchedAt = 0;
let _eumetsatLightningForecastData      = null;
let _eumetsatLightningForecastFetchedAt = 0;
let _eumetsatGeocolourMotionData      = null;
let _eumetsatGeocolourMotionFetchedAt = 0;

async function loadEumetsatCloudForecast(){
    if(Date.now() - _eumetsatForecastFetchedAt < 12 * 60000) return; // раз в 12 мин
    _eumetsatForecastFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_cloud_forecast.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatForecastData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatForecastFetchedAt = 0;
    }
}

async function loadEumetsatPrecipForecast(){
    if(Date.now() - _eumetsatPrecipForecastFetchedAt < 12 * 60000) return; // раз в 12 мин
    _eumetsatPrecipForecastFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_precip_forecast.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatPrecipForecastData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatPrecipForecastFetchedAt = 0;
    }
}

async function loadEumetsatLightningForecast(){
    if(Date.now() - _eumetsatLightningForecastFetchedAt < 5 * 60000) return; // раз в 5 мин
    _eumetsatLightningForecastFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_lightning_forecast.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatLightningForecastData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatLightningForecastFetchedAt = 0;
    }
}

async function loadEumetsatGeocolourMotion(){
    if(Date.now() - _eumetsatGeocolourMotionFetchedAt < 10 * 60000) return; // раз в 10 мин
    _eumetsatGeocolourMotionFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_geocolour_motion.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatGeocolourMotionData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatGeocolourMotionFetchedAt = 0;
    }
}

function _fmtObsTime(iso){
    if(!iso) return null;
    const d = new Date(iso);
    if(isNaN(d)) return null;
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function _renderFieldForecastLines(f, cfg){
    if(!f) return "";
    const targetStr = f.target_type === cfg.massTargetValue ? cfg.targetMassLabel : cfg.targetClearingLabel;

    if(f.distance_km_now == null){
        return `<div style="margin-top:14px;">
            <div style="font-weight:600; color:#eee;">${cfg.title}</div>
            <div class="small muted" style="margin-top:2px;">${f.verdict || "недостаточно данных для оценки"}.</div>
        </div>`;
    }

    const distStr = `${Number(f.distance_km_now).toLocaleString("ru-RU")} км (${f.compass})`;
    const stationary = f.verdict === "почти стоит на месте";
    let verdictLine;
    if(f.verdict === "приближается" || f.verdict === "уже у города"){
        const etaStr = f.eta_min != null ? `~${Math.round(f.eta_min)} мин` : "скоро";
        verdictLine = `приближается, ${etaStr} до станции`;
    } else if(f.verdict === "пройдёт мимо, город, скорее всего, не заденет"){
        verdictLine = `пройдёт мимо на расстоянии ~${Math.round(f.cpa_km)} км, станцию, скорее всего, не заденет`;
    } else if(f.verdict === "удаляется"){
        verdictLine = `удаляется`;
    } else if(stationary){
        verdictLine = `почти не движется`;
    } else {
        verdictLine = f.verdict || "";
    }
    // при скорости ~0 направление движения бессмысленно ("скорость 0, но
    // направление на С") — показываем его только когда реально что-то едет
    const dirStr = (f.direction_compass && !stationary) ? `, направление на ${f.direction_compass}` : "";
    const speedStr = f.speed_kmh != null ? `, скорость ~${Math.round(f.speed_kmh)} км/ч${dirStr}` : "";
    const probLine = (f.target_type === cfg.massTargetValue && f.probability_percent != null)
        ? `<div class="small muted" style="margin-top:2px;">Вероятность, что ${cfg.probVerb}: ~${f.probability_percent}%.</div>`
        : "";

    return `<div style="margin-top:14px;">
        <div style="font-weight:600; color:#eee;">${cfg.title}</div>
        <div class="small muted" style="margin-top:2px;">${targetStr} к точке наблюдения: ${distStr}${speedStr}.</div>
        <div class="small muted" style="margin-top:2px;">${verdictLine}.</div>
        ${probLine}
    </div>`;
}

function _renderCloudForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Облачность",
        massTargetValue: "cloud_mass", targetMassLabel: "ближайшее облако", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт изменение погоды",
    });
}

function _renderPrecipForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Осадки",
        massTargetValue: "precip_mass", targetMassLabel: "ближайшие осадки", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт осадки",
    });
}

function _renderLightningForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Молния",
        massTargetValue: "storm_mass", targetMassLabel: "ближайшая грозовая ячейка", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт грозу",
    });
}

function _renderGeocolourMotionLines(g){
    if(!g) return "";
    const body = g.valid
        ? `скорость ~${Math.round(g.speed_kmh)} км/ч, направление на ${g.direction_compass}.`
        : `${g.verdict || "недоступно"}.`;
    return `<div style="margin-top:14px;">
        <div style="font-weight:600; color:#eee;">По HD-снимку (естественный цвет)</div>
        <div class="small muted" style="margin-top:2px;">${body}</div>
    </div>`;
}

function renderNearbyPrecipCard(){
    const card = document.getElementById("nearbyPrecipCard");
    if(!card) return;

    const anyData = _eumetsatForecastData || _eumetsatPrecipForecastData
        || _eumetsatLightningForecastData || _eumetsatGeocolourMotionData;
    if(!anyData){ card.innerHTML = ""; return; }

    const obsTimeIso = (_eumetsatForecastData && _eumetsatForecastData.timestamp)
        || (_eumetsatPrecipForecastData && _eumetsatPrecipForecastData.timestamp)
        || (_eumetsatLightningForecastData && _eumetsatLightningForecastData.timestamp)
        || (_eumetsatGeocolourMotionData && _eumetsatGeocolourMotionData.timestamp);
    const timeStr = _fmtObsTime(obsTimeIso) || "—";

    card.innerHTML = `
        <div class="cardTitle">Анализ спутниковых снимков (EUMETSAT)</div>
        <div class="small muted">Точка наблюдения: станция "${STATION_LABEL}"</div>
        <div class="small muted" style="margin-top:2px;">Время наблюдения: ${timeStr}</div>
        ${_renderCloudForecastLines(_eumetsatForecastData)}
        ${_renderGeocolourMotionLines(_eumetsatGeocolourMotionData)}
        ${_renderPrecipForecastLines(_eumetsatPrecipForecastData)}
        ${_renderLightningForecastLines(_eumetsatLightningForecastData)}
        <div class="small muted" style="margin-top:14px;">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
}
