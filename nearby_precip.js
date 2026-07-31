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
let _eumetsatGeocolourMotionData      = null;
let _eumetsatGeocolourMotionFetchedAt = 0;
let _eumetsatPrecipMotionData      = null;
let _eumetsatPrecipMotionFetchedAt = 0;
let _eumetsatCloudPhaseTypeData      = null;
let _eumetsatCloudPhaseTypeFetchedAt = 0;

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

async function loadEumetsatPrecipMotion(){
    if(Date.now() - _eumetsatPrecipMotionFetchedAt < 10 * 60000) return; // раз в 10 мин
    _eumetsatPrecipMotionFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_precip_motion.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatPrecipMotionData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatPrecipMotionFetchedAt = 0;
    }
}

async function loadEumetsatCloudPhaseType(){
    if(Date.now() - _eumetsatCloudPhaseTypeFetchedAt < 10 * 60000) return; // раз в 10 мин
    _eumetsatCloudPhaseTypeFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_cloud_phase_type.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatCloudPhaseTypeData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatCloudPhaseTypeFetchedAt = 0;
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

function _hr(){
    return `<hr style="border:none; border-top:1px solid #333; margin:14px 0 10px;">`;
}
function _blockTitle(emoji, title, timeTag){
    return `<div style="font-weight:700; color:#eee; font-size:14px;">${emoji} ${title}${timeTag}</div>`;
}
function _plain(text){
    return `<div class="small muted" style="margin-top:4px;">${text}</div>`;
}
function _subhead(label){
    return `<div style="font-weight:600; color:#ccc; margin-top:8px; font-size:12.5px;">${label}</div>`;
}
function _bullets(items){
    if(!items || !items.length) return "";
    return `<ul style="margin:3px 0 0 0; padding-left:18px; color:#bbb; font-size:12.5px; line-height:1.55;">`
        + items.map(i => `<li>${i}</li>`).join("") + `</ul>`;
}
// техническая выноска про буфер — просьба "в памяти N снимков, запуск
// анализа через N минут"; формулировка зависит от того, заполнен ли буфер
// целиком (span_minutes_now == span_minutes_target) или ещё нет.
function _bufferLine(status){
    if(!status) return "";
    const full = status.frames_in_memory >= status.frames_target;
    const text = full
        ? `Буфер заполнен: ${status.frames_in_memory}/${status.frames_target} кадров (≈${status.span_minutes_now} минут наблюдений).`
        : `Буфер: ${status.frames_in_memory}/${status.frames_target} кадров, полное окно — через ≈${status.eta_full_window_min} мин.`;
    return `<div class="small muted" style="margin-top:6px; opacity:0.6; font-size:11px;">${text}</div>`;
}

// Общий рендер для карточек "движение объекта относительно станции"
// (Облачность / Осадки / Осадки MTG / Молния) — verdict-логика (текст про
// приближение/удаление/ETA) не меняется, меняется только markup.
function _fieldBlock(f, cfg){
    if(!f) return "";
    const timeTag = _obsTimeTag(f.timestamp, cfg.staleMin);
    // cfg.stateLabels — карта {значение_current_state: текст}; поддерживает
    // и бинарные случаи (Осадки/Молния — только 2 значения), и тройные
    // (Облачность — clear/variable/cloud, area-fraction по радиусу, см.
    // eumetsat_cloud_forecast.py). Раньше был бинарный stateOnValue/
    // stateOnLabel/stateOffLabel — молча показывал бы "variable" как "ясно".
    const stateStr = cfg.stateLabels[f.current_state] || f.current_state;
    const extraHtml = cfg.extraHtml ? cfg.extraHtml(f) : "";

    if(f.distance_km_now == null){
        return _hr() + _blockTitle(cfg.emoji, cfg.title, timeTag)
            + _plain(`Над станцией: ${stateStr}.`)
            + _plain(f.verdict ? `${f.verdict[0].toUpperCase()}${f.verdict.slice(1)}.` : "Недостаточно данных для оценки.")
            + extraHtml;
    }

    const targetStr = f.target_type === cfg.massTargetValue ? cfg.targetMassLabel : cfg.targetClearingLabel;
    const distStr = `${Number(f.distance_km_now).toLocaleString("ru-RU")} км (${f.compass})`;
    const stationary = f.verdict === "почти стоит на месте";

    let verdictText;
    if(f.verdict === "приближается" || f.verdict === "уже у города"){
        const etaStr = f.eta_min != null ? `~${Math.round(f.eta_min)} мин` : "скоро";
        verdictText = `приближается, ${etaStr} до станции`;
    } else if(f.verdict === "пройдёт мимо, город, скорее всего, не заденет"){
        verdictText = `пройдёт мимо на расстоянии ≈${Math.round(f.cpa_km)} км, станцию, скорее всего, не заденет`;
    } else if(f.verdict === "удаляется"){
        verdictText = `удаляется`;
    } else if(stationary){
        verdictText = `практически отсутствует`;
    } else {
        verdictText = f.verdict || "";
    }

    const targetBullets = [`расстояние: ${distStr}`];
    if(f.speed_kmh != null){
        const dirStr = (f.direction_compass && !stationary) ? `, направление на ${f.direction_compass}` : "";
        targetBullets.push(`скорость: ≈${Math.round(f.speed_kmh)} км/ч${dirStr}`);
    }
    targetBullets.push(`движение: ${verdictText}`);

    const assessBullets = [];
    if(f.target_type === cfg.massTargetValue && f.probability_percent != null){
        assessBullets.push(`вероятность, что ${cfg.probVerb}: ≈${f.probability_percent}%`);
    }
    if(cfg.extraBullets) assessBullets.push(...cfg.extraBullets(f));

    return _hr() + _blockTitle(cfg.emoji, cfg.title, timeTag)
        + _plain(`Над станцией: ${stateStr}.`)
        + _subhead(targetStr[0].toUpperCase() + targetStr.slice(1))
        + _bullets(targetBullets)
        + (assessBullets.length ? _subhead("Оценка") + _bullets(assessBullets) : "")
        + _bufferLine(f.buffer_status);
}

function _cloudExtraBullets(f){
    const out = [];
    if(f.trend){
        const t = f.trend;
        if(t.density_verdict) out.push(`облачность в радиусе 50 км — ${t.density_verdict}`);
        if(t.height_verdict) out.push(`высота верхушек — ${t.height_verdict}`);
        if(t.shape_verdict) out.push(`форма поля — ${t.shape_verdict}`);
    }
    return out;
}

function _renderCloudForecastLines(f){
    return _fieldBlock(f, {
        emoji: "☁️", title: "Облачность",
        stateLabels: { clear: "ясно", variable: "переменная облачность", cloud: "облачно" },
        massTargetValue: "cloud_mass", targetMassLabel: "ближайшее облако", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт изменение погоды",
        staleMin: 25,
        extraBullets: _cloudExtraBullets,
    });
}

function _renderPrecipForecastLines(f){
    return _fieldBlock(f, {
        emoji: "🌧", title: "Осадки",
        stateLabels: { precip: "есть осадки", no_precip: "осадков нет" },
        massTargetValue: "precip_mass", targetMassLabel: "ближайшая зона осадков", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт осадки",
        staleMin: 25,
    });
}

function _renderPrecipMotionLines(f){
    return _fieldBlock(f, {
        emoji: "🌧", title: "Осадки (MTG H40B)",
        stateLabels: { precip: "есть осадки", no_precip: "осадков нет" },
        massTargetValue: "precip_mass", targetMassLabel: "ближайшая зона осадков", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт осадки",
        staleMin: 20,
    });
}

function _renderLightningForecastLines(f){
    return _fieldBlock(f, {
        emoji: "⚡", title: "Молниевая активность",
        stateLabels: { storm: "гроза", no_storm: "грозы нет" },
        massTargetValue: "storm_mass", targetMassLabel: "ближайшая грозовая ячейка", targetClearingLabel: "ближайший просвет",
        probVerb: "принесёт грозу",
        staleMin: 15,
    });
}

function _renderIrMotionLines(g){
    if(!g) return "";
    const timeTag = _obsTimeTag(g.timestamp, 20);
    const title = _blockTitle("🌡️", "Инфракрасный канал 10.5 мкм", timeTag);

    const areaBullets = [];
    const area = g.observed_area;
    if(area && area.center_lat != null && area.center_lon != null){
        const w = area.motion_window_km && area.motion_window_km.width;
        const h = area.motion_window_km && area.motion_window_km.height;
        if(w && h) areaBullets.push(`окно: ≈${w} × ${h} км`);
        areaBullets.push(`центр: ${Number(area.center_lat).toFixed(2)}°N, ${Number(area.center_lon).toFixed(2)}°E (Одесса)`);
        if(area.local_trend_radius_km) areaBullets.push(`анализ температуры верхней границы облаков в радиусе ≈${area.local_trend_radius_km} км`);
    }
    const areaHtml = areaBullets.length ? _subhead("Область анализа") + _bullets(areaBullets) : "";

    const labels = { clear: "ясно", variable: "переменная облачность", cloud: "облачно" };
    const stationText = g.station_state ? (labels[g.station_state] || g.station_state) : null;
    const stationHtml = stationText ? _plain(`Над станцией: ${stationText}.`) : "";

    if(!g.valid){
        return _hr() + title + areaHtml + stationHtml + _plain(g.verdict || "Недоступно.");
    }

    const lowConfidence = g.frame_pairs_used != null && g.frame_pairs_used <= 2;
    const suffix = lowConfidence ? " (мало пар кадров — невысокая уверенность)" : "";

    const massBullets = [];
    if(g.cloud_mass_distance_km != null){
        massBullets.push(`расстояние: ≈${Math.round(g.cloud_mass_distance_km)} км (${g.cloud_mass_compass})`);
    }
    massBullets.push(`движение: на ${g.direction_compass}`);
    massBullets.push(`скорость: ≈${Math.round(g.speed_kmh)} км/ч`);
    const massHtml = _subhead("Основная облачная масса") + _bullets(massBullets);

    const trendBullets = [];
    if(g.acceleration_verdict) trendBullets.push(`${g.acceleration_verdict}${suffix}`);
    if(g.turning_verdict) trendBullets.push(`${g.turning_verdict}${suffix}`);
    if(g.area_trend_verdict) trendBullets.push(`площадь облачной массы — ${g.area_trend_verdict}`);
    if(g.temperature_trend_verdict) trendBullets.push(`яркостная температура — ${g.temperature_trend_verdict}`);
    const trendHtml = trendBullets.length ? _subhead("Тренд") + _bullets(trendBullets) : "";

    let forecastHtml = "";
    if(g.forecast_displacement && g.forecast_displacement["30min"] && g.forecast_displacement["60min"] && g.forecast_displacement["120min"]){
        const f30 = g.forecast_displacement["30min"];
        const f60 = g.forecast_displacement["60min"];
        const f120 = g.forecast_displacement["120min"];
        forecastHtml = _subhead("Прогноз смещения") + _bullets([
            `через 30 мин — ≈${Number(f30.distance_km).toLocaleString("ru-RU")} км`,
            `через 60 мин — ≈${Number(f60.distance_km).toLocaleString("ru-RU")} км`,
            `через 120 мин — ≈${Number(f120.distance_km).toLocaleString("ru-RU")} км (на ${f120.compass})`,
        ]);
    }

    return _hr() + title + areaHtml + stationHtml + massHtml + trendHtml + forecastHtml;
}

// GeoColour RGB (mtg_fd:rgb_geocolour) — круглосуточно (day/night-композит,
// ночью облака голубые от ИК-подсветки, огни городов жёлтые — исключены из
// классификации на сервере). Гибрид: motion — phase correlation по сырой
// яркости (как ИК), area-fraction/позиция — абсолютная HSV-классификация
// (как Cloud Mask), не перцентиль. См. eumetsat_geocolour_motion.py.
function _renderGeocolourMotionLines(g){
    if(!g) return "";
    const timeTag = _obsTimeTag(g.timestamp, 20);
    const title = _blockTitle("🌍", "Естественный цвет (GeoColour, круглосуточно)", timeTag);

    const areaBullets = [];
    const area = g.observed_area;
    if(area && area.center_lat != null && area.center_lon != null){
        const w = area.motion_window_km && area.motion_window_km.width;
        const h = area.motion_window_km && area.motion_window_km.height;
        if(w && h) areaBullets.push(`окно: ≈${w} × ${h} км`);
        areaBullets.push(`центр: ${Number(area.center_lat).toFixed(2)}°N, ${Number(area.center_lon).toFixed(2)}°E (Одесса)`);
        if(area.local_trend_radius_km) areaBullets.push(`анализ облачности в радиусе ≈${area.local_trend_radius_km} км`);
    }
    const areaHtml = areaBullets.length ? _subhead("Область анализа") + _bullets(areaBullets) : "";

    const stateLabels = { clear: "ясно", variable: "переменная облачность", cloud: "облачно" };
    const stationText = g.station_state ? (stateLabels[g.station_state] || g.station_state) : null;
    const stationHtml = stationText ? _plain(`Над станцией: ${stationText}.`) : "";

    if(!g.valid){
        return _hr() + title + areaHtml + stationHtml + _plain(g.verdict || "Недоступно.");
    }

    const lowConfidence = g.frame_pairs_used != null && g.frame_pairs_used <= 2;
    const suffix = lowConfidence ? " (мало пар кадров — невысокая уверенность)" : "";

    let massHtml = "";
    if(g.cloud_mass_distance_km != null){
        const massBullets = [
            `расстояние: ≈${Math.round(g.cloud_mass_distance_km)} км (${g.cloud_mass_compass})`,
            `движение: на ${g.direction_compass}`,
            `скорость: ≈${Math.round(g.speed_kmh)} км/ч`,
        ];
        massHtml = _subhead("Основная облачная масса") + _bullets(massBullets);
    }

    const trendBullets = [];
    if(g.acceleration_verdict) trendBullets.push(`${g.acceleration_verdict}${suffix}`);
    if(g.turning_verdict) trendBullets.push(`${g.turning_verdict}${suffix}`);
    if(g.area_trend_verdict) trendBullets.push(`площадь облачности (радиус 50км) — ${g.area_trend_verdict}`);
    const trendHtml = trendBullets.length ? _subhead("Тренд") + _bullets(trendBullets) : "";

    let forecastHtml = "";
    if(g.forecast_displacement && g.forecast_displacement["30min"] && g.forecast_displacement["60min"] && g.forecast_displacement["120min"]){
        const f30 = g.forecast_displacement["30min"];
        const f60 = g.forecast_displacement["60min"];
        const f120 = g.forecast_displacement["120min"];
        forecastHtml = _subhead("Прогноз смещения") + _bullets([
            `через 30 мин — ≈${Number(f30.distance_km).toLocaleString("ru-RU")} км`,
            `через 60 мин — ≈${Number(f60.distance_km).toLocaleString("ru-RU")} км`,
            `через 120 мин — ≈${Number(f120.distance_km).toLocaleString("ru-RU")} км (на ${f120.compass})`,
        ]);
    }

    return _hr() + title + areaHtml + stationHtml + massHtml + trendHtml + forecastHtml;
}

// Cloud Phase/Type RGB — не трекинг движения (это уже делают Cloud
// Mask/IR/GeoColour выше), а качественный тренд фазы (вода->лёд->гроза) и
// грубой группы облачности. Анкеры цвета — первая, не откалиброванная по
// реальным сценам версия (см. method_note в самом JSON) — поэтому здесь же
// показываем unclassified_fraction, чтобы было видно, когда анкеры
// разъезжаются с реальной картинкой.
function _renderCloudPhaseTypeLines(g){
    if(!g) return "";
    const timeTag = _obsTimeTag(g.timestamp, 15);
    const title = _blockTitle("🌈", "Фаза и тип облаков (MTG RGB)", timeTag);

    if(!g.phase_verdict){
        return _hr() + title + _plain(g.verdict || "недостаточно данных");
    }

    let warnHtml = "";
    if(g.unclassified_fraction_now != null && g.unclassified_fraction_now > 0.3){
        const pct = Math.round(g.unclassified_fraction_now * 100);
        warnHtml = `<div class="small muted" style="margin-top:6px; color:#e0a030;">⚠ ${pct}% пикселей области не распознано цветовыми анкерами (первая версия, требует калибровки).</div>`;
    }

    return _hr() + title
        + _bullets([`фаза облаков — ${g.phase_verdict}`, `тип облаков — ${g.type_verdict}`])
        + warnHtml
        + _bufferLine(g.buffer_status);
}

function renderNearbyPrecipCard(){
    const card = document.getElementById("nearbyPrecipCard");
    if(!card) return;

    const anyData = _eumetsatForecastData || _eumetsatPrecipForecastData
        || _eumetsatLightningForecastData || _eumetsatIrMotionData || _eumetsatPrecipMotionData
        || _eumetsatCloudPhaseTypeData || _eumetsatGeocolourMotionData;
    if(!anyData){ card.innerHTML = ""; return; }

    card.innerHTML = `
        <div class="cardTitle">Анализ спутниковых снимков (EUMETSAT)</div>
        <div class="small muted">Точка наблюдения: станция "${STATION_LABEL}"</div>
        ${_renderCloudForecastLines(_eumetsatForecastData)}
        ${_renderCloudPhaseTypeLines(_eumetsatCloudPhaseTypeData)}
        ${_renderIrMotionLines(_eumetsatIrMotionData)}
        ${_renderGeocolourMotionLines(_eumetsatGeocolourMotionData)}
        ${_renderPrecipForecastLines(_eumetsatPrecipForecastData)}
        ${_renderPrecipMotionLines(_eumetsatPrecipMotionData)}
        ${_renderLightningForecastLines(_eumetsatLightningForecastData)}
        ${_hr()}
        <div class="small muted">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
}
