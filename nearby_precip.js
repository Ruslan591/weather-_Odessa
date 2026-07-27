/* =========================================================
   NEARBY_PRECIP.JS — карточка "Анализ спутниковых снимков (EUMETSAT)"
   на nearby.html. Только спутниковый анализ (EUMETSAT), без PWS-датчиков
   и без радара RainViewer — по просьбе убрано всё остальное со страницы.

   Источники (пишут соответствующие scripts/eumetsat_*.py раз в 5-15 мин):
     data/eumetsat_cloud_forecast.json      — движение облачности (Cloud Mask)
     data/eumetsat_precip_forecast.json     — движение осадков (h60b)
     data/eumetsat_lightning_forecast.json  — движение грозовой активности (li_afa)
     data/eumetsat_ir_motion.json           — независимая оценка по текстуре
                                               ИК-канала (msg_fes:ir108, 10.8мкм) —
                                               заменил GeoColour после того как
                                               выяснилось, что ночью там огни
                                               городов ломают phase correlation
                                               (см. историю коммитов field_motion_common.py)
========================================================= */

const STATION_LABEL = "Одесса (СИНОП 33837)";

let _eumetsatForecastData      = null;
let _eumetsatForecastFetchedAt = 0;
let _eumetsatPrecipForecastData      = null;
let _eumetsatPrecipForecastFetchedAt = 0;
let _eumetsatLightningForecastData      = null;
let _eumetsatLightningForecastFetchedAt = 0;
let _eumetsatIrMotionData      = null;
let _eumetsatIrMotionFetchedAt = 0;

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

async function loadEumetsatIrMotion(){
    if(Date.now() - _eumetsatIrMotionFetchedAt < 10 * 60000) return; // раз в 10 мин
    _eumetsatIrMotionFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_ir_motion.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatIrMotionData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatIrMotionFetchedAt = 0;
    }
}

function _fmtObsTime(iso){
    if(!iso) return null;
    const d = new Date(iso);
    if(isNaN(d)) return null;
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function _ageMinutes(iso){
    if(!iso) return null;
    const d = new Date(iso);
    if(isNaN(d)) return null;
    return (Date.now() - d.getTime()) / 60000;
}

// staleMin — после скольки минут показывать предупреждение "устарело":
// у каждого источника свой цикл обновления (облачность/осадки — 15 мин,
// молния — 5 мин, HD-снимок — 10 мин), поэтому порог передаётся отдельно.
function _obsTimeTag(iso, staleMin){
    const timeStr = _fmtObsTime(iso);
    if(!timeStr) return "";
    const age = _ageMinutes(iso);
    if(age != null && age > staleMin){
        const ageStr = age < 60 ? `${Math.round(age)} мин` : `${(age/60).toFixed(1)} ч`;
        return ` <span style="color:#e0a030;">(${timeStr} · ⚠ устарело, ${ageStr} назад)</span>`;
    }
    return ` <span style="color:#777;">(${timeStr})</span>`;
}

function _renderFieldForecastLines(f, cfg){
    if(!f) return "";
    const targetStr = f.target_type === cfg.massTargetValue ? cfg.targetMassLabel : cfg.targetClearingLabel;
    const stateStr = f.current_state === cfg.stateOnValue ? cfg.stateOnLabel : cfg.stateOffLabel;
    const timeTag = _obsTimeTag(f.timestamp, cfg.staleMin);
    const titleLine = `<div style="font-weight:600; color:#eee;">${cfg.title}${timeTag}</div>`;
    const stateLine = `<div class="small muted" style="margin-top:2px;">${stateStr}</div>`;

    if(f.distance_km_now == null){
        return `<div style="margin-top:14px;">
            ${titleLine}
            ${stateLine}
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
        ${titleLine}
        ${stateLine}
        <div class="small muted" style="margin-top:2px;">${targetStr} к точке наблюдения: ${distStr}${speedStr}.</div>
        <div class="small muted" style="margin-top:2px;">${verdictLine}.</div>
        ${probLine}
    </div>`;
}

function _renderCloudForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Облачность",
        stateOnValue: "cloud", stateOnLabel: "сейчас облачно", stateOffLabel: "сейчас ясно",
        massTargetValue: "cloud_mass", targetMassLabel: "ближайшее облако", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт изменение погоды",
        staleMin: 25,
    });
}

function _renderPrecipForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Осадки",
        stateOnValue: "precip", stateOnLabel: "сейчас есть осадки", stateOffLabel: "сейчас без осадков",
        massTargetValue: "precip_mass", targetMassLabel: "ближайшие осадки", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт осадки",
        staleMin: 25,
    });
}

function _renderLightningForecastLines(f){
    return _renderFieldForecastLines(f, {
        title: "Молния",
        stateOnValue: "storm", stateOnLabel: "сейчас гроза", stateOffLabel: "сейчас без грозы",
        massTargetValue: "storm_mass", targetMassLabel: "ближайшая грозовая ячейка", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт грозу",
        staleMin: 15,
    });
}

function _renderIrMotionLines(g){
    if(!g) return "";
    const timeTag = _obsTimeTag(g.timestamp, 20);
    const areaLine = _renderIrAreaLine(g.observed_area);

    if(!g.valid){
        return `<div style="margin-top:14px;">
            <div style="font-weight:600; color:#eee;">По ИК-снимку (10.5мкм, MTG, день/ночь)${timeTag}</div>
            ${areaLine}
            <div class="small muted" style="margin-top:2px;">${g.verdict || "недоступно"}.</div>
        </div>`;
    }

    const lowConfidence = g.frame_pairs_used != null && g.frame_pairs_used <= 2;
    const lines = [];

    // Положение цели (где она СЕЙЧАС относительно станции) — перед строкой
    // о направлении её движения, тот же порядок, что в блоке Облачность выше.
    if(g.cloud_mass_distance_km != null){
        lines.push(`значимая облачная масса: ~${Math.round(g.cloud_mass_distance_km)} км (${g.cloud_mass_compass}) от станции.`);
    }
    lines.push(`скорость ~${Math.round(g.speed_kmh)} км/ч, направление на ${g.direction_compass}.`);

    if(g.acceleration_verdict){
        lines.push(`${g.acceleration_verdict}${lowConfidence ? " (мало пар кадров — невысокая уверенность)" : ""}.`);
    }
    if(g.turning_verdict){
        lines.push(`${g.turning_verdict}${lowConfidence ? " (мало пар кадров — невысокая уверенность)" : ""}.`);
    }
    if(g.area_trend_verdict){
        lines.push(`${g.area_trend_verdict}.`);
    }
    if(g.temperature_trend_verdict){
        lines.push(`${g.temperature_trend_verdict}.`);
    }
    if(g.forecast_displacement && g.forecast_displacement["30min"] && g.forecast_displacement["60min"] && g.forecast_displacement["120min"]){
        const f30 = g.forecast_displacement["30min"];
        const f60 = g.forecast_displacement["60min"];
        const f120 = g.forecast_displacement["120min"];
        lines.push(
            `Прогноз смещения: ~${f30.distance_km}км за 30мин, ~${f60.distance_km}км за 60мин, `
            + `~${f120.distance_km}км за 120мин (направление ~${f60.compass}).`
        );
    }

    const linesHtml = lines.map(l => `<div class="small muted" style="margin-top:2px;">${l}</div>`).join("");

    return `<div style="margin-top:14px;">
        <div style="font-weight:600; color:#eee;">По ИК-снимку (10.5мкм, MTG, день/ночь)${timeTag}</div>
        ${areaLine}
        ${linesHtml}
    </div>`;
}

// Строку "область анализа" рендерим отдельно от остальных verdict-строк:
// это не тренд/прогноз, а статичная привязка к местности — где именно на
// снимке измеряется движение (окно ~WxH км) и где считается площадь/тренд
// температуры (радиус в км), в отличие от остальных карточек этого блока,
// которые отслеживают ближайший ОБЪЕКТ (облако/осадки) от станции.
function _renderIrAreaLine(area){
    if(!area || area.center_lat == null || area.center_lon == null) return "";
    const lat = Number(area.center_lat).toFixed(2);
    const lon = Number(area.center_lon).toFixed(2);
    const w = area.motion_window_km && area.motion_window_km.width;
    const h = area.motion_window_km && area.motion_window_km.height;
    const windowStr = (w && h) ? `окно ~${w}×${h} км` : "";
    const radiusStr = area.local_trend_radius_km ? `, площадь/температура — в радиусе ~${area.local_trend_radius_km} км` : "";
    return `<div class="small muted" style="margin-top:2px;">Наблюдаемая область: ${windowStr} с центром у Одессы (${lat}°N, ${lon}°E)${radiusStr}.</div>`;
}

function renderNearbyPrecipCard(){
    const card = document.getElementById("nearbyPrecipCard");
    if(!card) return;

    const anyData = _eumetsatForecastData || _eumetsatPrecipForecastData
        || _eumetsatLightningForecastData || _eumetsatIrMotionData;
    if(!anyData){ card.innerHTML = ""; return; }

    card.innerHTML = `
        <div class="cardTitle">Анализ спутниковых снимков (EUMETSAT)</div>
        <div class="small muted">Точка наблюдения: станция "${STATION_LABEL}"</div>
        ${_renderCloudForecastLines(_eumetsatForecastData)}
        ${_renderIrMotionLines(_eumetsatIrMotionData)}
        ${_renderPrecipForecastLines(_eumetsatPrecipForecastData)}
        ${_renderLightningForecastLines(_eumetsatLightningForecastData)}
        <div class="small muted" style="margin-top:14px;">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
}
