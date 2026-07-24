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

/* =========================================================
   PWS GROUND TRUTH — реальные показания дождемеров всех PWS-станций
   в городе. Добавлено из-за подтверждённого провала покрытия RainViewer
   прямо над Одессой и морем к югу (~20км+ от города радар не видит вообще,
   независимо от того, идёт дождь или нет — это дыра в исходных данных
   RainViewer, а не наша логика). Для "идёт ли дождь СЕЙЧАС В ГОРОДЕ" эти
   датчики надёжнее радара: они физически стоят в городе, провала
   покрытия по определению быть не может.
   Те же станции и тот же метод, что и PWS_AVG на pws.html (pws_page.js),
   но отдельно и легковесно — только precipRate, без давления/WBGT и т.п.
========================================================= */

const PWS_GT_STATIONS = [
    "IODESA137", "IODESA138", "IODESA139", "IODESS41", "IODESS44",
    "IODESS35", "IODESS16", "IODESS31", "IODESS37", "IKRASN91",
];
const WU_KEYS_GT = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525",
];

let _pwsGroundTruthData      = null;
let _pwsGroundTruthFetchedAt = 0;

async function _fetchStationPrecip(id){
    const url = `https://api.weather.com/v2/pws/observations/current` +
        `?stationId=${encodeURIComponent(id)}&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${WU_KEYS_GT[0]}`;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
        const r = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
        if(!r.ok) return null;
        const data = await r.json();
        if(!data?.observations?.length) return null;
        const m = data.observations[0].metric || {};
        return { id, precipRate: m.precipRate ?? null };
    } catch(e){
        return null;
    } finally {
        clearTimeout(timer);
    }
}

async function loadPwsGroundTruth(){
    if(Date.now() - _pwsGroundTruthFetchedAt < 3 * 60000) return; // раз в 3 мин
    _pwsGroundTruthFetchedAt = Date.now();
    try {
        const results = await Promise.all(PWS_GT_STATIONS.map(_fetchStationPrecip));
        const ok = results.filter(r => r && r.precipRate != null);
        if(!ok.length){
            _pwsGroundTruthData = null;
        } else {
            const raining = ok.filter(r => r.precipRate > 0);
            const maxRate = Math.max(...ok.map(r => r.precipRate));
            const avgRate = ok.reduce((s, r) => s + r.precipRate, 0) / ok.length;
            _pwsGroundTruthData = {
                stationsReporting: ok.length,
                stationsRaining: raining.length,
                maxRateMmH: Math.round(maxRate * 10) / 10,
                avgRateMmH: Math.round(avgRate * 10) / 10,
                isRaining: raining.length > 0,
            };
        }
        renderNearbyPrecipCard();
    } catch(e){
        _pwsGroundTruthFetchedAt = 0;
    }
}

function _renderPwsGroundTruth(g){
    if(!g){
        return `<div class="small muted">PWS-датчики города сейчас недоступны.</div>`;
    }
    const title = g.isRaining
        ? `идёт дождь`
        : `сухо`;
    const detail = g.isRaining
        ? `${g.stationsRaining} из ${g.stationsReporting} станций фиксируют осадки, макс. ${g.maxRateMmH} мм/ч (сред. ${g.avgRateMmH} мм/ч)`
        : `0 из ${g.stationsReporting} станций фиксируют осадки`;
    return `
        <div class="row">
            <div class="label">В городе сейчас (PWS-датчики)</div>
            <div class="value">${title}</div>
        </div>
        <div class="small muted" style="margin-top:2px;">${detail}</div>
        <div class="small muted" style="margin-top:4px; border-bottom:1px solid #333; padding-bottom:10px;">
            Это реальные дождемеры физически в городе — надёжнее радара для вопроса
            "идёт ли дождь прямо сейчас": у RainViewer подтверждён провал покрытия
            над Одессой и морем к югу (~20км+ от города радар просто не видит,
            независимо от погоды).
        </div>`;
}

let _nearbyPrecipData      = null;
let _nearbyPrecipFetchedAt = 0;
let _eumetsatPointData      = null;
let _eumetsatPointFetchedAt = 0;
let _eumetsatForecastData      = null;
let _eumetsatForecastFetchedAt = 0;
let _eumetsatPrecipForecastData      = null;
let _eumetsatPrecipForecastFetchedAt = 0;
let _eumetsatLightningForecastData      = null;
let _eumetsatLightningForecastFetchedAt = 0;
let _eumetsatGeocolourMotionData      = null;
let _eumetsatGeocolourMotionFetchedAt = 0;

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

const NO_SIGNAL_HUE = "серый/чёрный (низ шкалы или нет сигнала)";

function _eumetsatRow(label, layerData, hideIfNoSignal){
    if(hideIfNoSignal && layerData && layerData.hue_bucket === NO_SIGNAL_HUE) return "";
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

function _renderTrend(t){
    if(!t) return "";
    const parts = [];
    if(t.density_verdict) parts.push(`плотность: ${t.density_verdict}`);
    if(t.height_verdict) parts.push(`высота: ${t.height_verdict}`);
    if(t.shape_verdict) parts.push(`форма: ${t.shape_verdict}`);
    if(!parts.length) return "";
    return `<div class="small muted" style="margin-top:2px;">${parts.join(" · ")}</div>`;
}

function _renderFieldForecast(f, cfg){
    if(!f) return "";
    const stateStr = f.current_state === cfg.stateOnValue ? cfg.stateOnLabel : cfg.stateOffLabel;
    const targetStr = f.target_type === cfg.massTargetValue ? cfg.targetMassLabel : cfg.targetClearingLabel;

    if(f.distance_km_now == null){
        return `<div class="small muted" style="margin-top:8px;">${cfg.title}: ${stateStr}, ${f.verdict || "недостаточно данных для оценки"}.</div>
        ${_renderTrend(f.trend)}`;
    }

    const distStr = `${Number(f.distance_km_now).toLocaleString("ru-RU")} км (${f.compass})`;
    const stationary = f.verdict === "почти стоит на месте";
    let verdictLine;
    if(f.verdict === "приближается" || f.verdict === "уже у города"){
        const etaStr = f.eta_min != null ? `~${Math.round(f.eta_min)} мин` : "скоро";
        verdictLine = `${targetStr} приближается, ${etaStr} до города`;
    } else if(f.verdict === "пройдёт мимо, город, скорее всего, не заденет"){
        verdictLine = `${targetStr} пройдёт мимо на расстоянии ~${Math.round(f.cpa_km)} км, город, скорее всего, не заденет`;
    } else if(f.verdict === "удаляется"){
        verdictLine = `${targetStr} удаляется`;
    } else if(stationary){
        verdictLine = `${targetStr} почти не движется`;
    } else {
        verdictLine = f.verdict || "";
    }
    // при скорости ~0 направление движения бессмысленно ("скорость 0, но
    // направление на С") — показываем его только когда реально что-то едет
    const dirStr = (f.direction_compass && !stationary) ? `, направление на ${f.direction_compass}` : "";
    const probStr = (f.target_type === cfg.massTargetValue && f.probability_percent != null)
        ? ` Вероятность, что ${cfg.probVerb}: ~${f.probability_percent}%.`
        : "";

    return `
        <div class="row">
            <div class="label">${cfg.title}</div>
            <div class="value">${stateStr}</div>
        </div>
        <div class="small muted" style="margin-top:4px;">
            ${targetStr}: ${distStr}${f.speed_kmh != null ? `, скорость ~${Math.round(f.speed_kmh)} км/ч${dirStr}` : ""}. ${verdictLine}.${probStr}
        </div>
        ${_renderTrend(f.trend)}`;
}

function _renderCloudForecast(f){
    return _renderFieldForecast(f, {
        title: "Прогноз облачности",
        stateOnValue: "cloud", stateOnLabel: "сейчас облачно", stateOffLabel: "сейчас ясно",
        massTargetValue: "cloud_mass", targetMassLabel: "ближайшее облако", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт изменение погоды",
    });
}

function _renderPrecipForecast(f){
    return _renderFieldForecast(f, {
        title: "Прогноз осадков (спутник)",
        stateOnValue: "precip", stateOnLabel: "сейчас есть осадки", stateOffLabel: "сейчас без осадков",
        massTargetValue: "precip_mass", targetMassLabel: "ближайшие осадки", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт осадки",
    });
}

function _renderLightningForecast(f){
    return _renderFieldForecast(f, {
        title: "Прогноз грозовой активности",
        stateOnValue: "storm", stateOnLabel: "сейчас гроза", stateOffLabel: "сейчас без грозы",
        massTargetValue: "storm_mass", targetMassLabel: "ближайшая грозовая ячейка", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт грозу",
    });
}

function _renderRadarMotion(label, m){
    if(!m) return "";
    const stationary = m.verdict === "почти стоит на месте";
    let verdictLine;
    if(m.verdict === "приближается" || m.verdict === "уже у города"){
        const etaStr = m.eta_min != null ? `~${Math.round(m.eta_min)} мин до города` : "скоро у города";
        verdictLine = etaStr;
    } else if(m.verdict === "пройдёт мимо, город, скорее всего, не заденет"){
        verdictLine = `пройдёт мимо на ~${Math.round(m.cpa_km)} км, город, скорее всего, не заденет`;
    } else if(m.verdict === "удаляется"){
        verdictLine = "удаляется";
    } else if(stationary){
        verdictLine = "почти не движется";
    } else {
        verdictLine = m.verdict || "";
    }
    const dirPart = stationary ? "" : ` на ${m.direction_compass}`;
    return `<div class="small muted" style="margin-top:2px;">
        ${label}: ~${Math.round(m.speed_kmh)} км/ч${dirPart}. ${verdictLine}.
    </div>`;
}

function _renderGeocolourMotion(g){
    if(!g) return "";
    if(!g.valid){
        return `<div class="small muted" style="margin-top:2px;">По HD-снимку (естественный цвет): ${g.verdict || "недоступно"}.</div>`;
    }
    return `<div class="small muted" style="margin-top:2px;">
        По HD-снимку (естественный цвет, независимая оценка по текстуре): ~${Math.round(g.speed_kmh)} км/ч на ${g.direction_compass}.
    </div>`;
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
        ${_eumetsatRow("Молнии (Flash Area/5мин)", e.layers.li_afa, true)}
        ${_renderCloudForecast(_eumetsatForecastData)}
        ${_renderGeocolourMotion(_eumetsatGeocolourMotionData)}
        ${_renderPrecipForecast(_eumetsatPrecipForecastData)}
        ${_renderLightningForecast(_eumetsatLightningForecastData)}
        <div class="small muted" style="margin-top:4px;">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
    }

    card.innerHTML = `
        <div class="cardTitle">Осадки и гроза поблизости</div>
        ${_renderPwsGroundTruth(_pwsGroundTruthData)}
        <div class="row">
            <div class="label">Ближайшие осадки</div>
            <div class="value">${precipStr}</div>
        </div>
        <div class="row">
            <div class="label">Гроза (прокси по радару)</div>
            <div class="value">${thunderStr}</div>
        </div>
        ${_renderRadarMotion("Движение области осадков", d.precip_motion)}
        ${_renderRadarMotion("Движение грозового ядра", d.thunderstorm_motion)}
        <div class="small muted" style="margin-top:8px;">
            Радар обновлён: ${ageStr}. Признак грозы — отражаемость ≥45 dBZ на радаре,
            это НЕ детекция реальной молнии, а эвристика по силе осадков. Скорость —
            усреднённая кросс-корреляция нескольких кадров, не трекинг одной точки.
        </div>
        <div class="small muted" style="margin-top:4px;">
            Weather data by
            <a href="https://www.rainviewer.com/" target="_blank" rel="noopener" style="color:#72c8ff;">RainViewer</a>
        </div>
        ${eumetsatBlock}`;
}
