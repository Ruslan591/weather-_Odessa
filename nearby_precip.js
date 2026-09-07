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

// Зеркало Python field_motion_common.FRONTAL_TRACK_COLORS (2026-08-19) —
// тот же track_id должен быть того же цвета и на снимке (реальные пиксели
// блоба, см. eumetsat_render_track_overlay.py), и здесь, в номере трека
// таблицы. Порядок и состав ОБЯЗАНЫ совпадать 1-в-1 с Python-списком —
// при правке одного менять оба. Жёлтый намеренно не включён (см. коммент
// в Python-версии — слишком похож на цвет окружности обзора на снимке).
const FRONTAL_TRACK_COLORS = [
    "rgb(255,59,48)",   // красный
    "rgb(52,199,89)",   // зелёный
    "rgb(10,132,255)",  // синий
    "rgb(255,149,0)",   // оранжевый
    "rgb(191,90,242)",  // фиолетовый
    "rgb(255,45,149)",  // розовый
    "rgb(100,210,255)", // голубой
];

function _trackColor(trackId){
    if(trackId == null) return "#666";
    const idx = ((trackId % FRONTAL_TRACK_COLORS.length) + FRONTAL_TRACK_COLORS.length) % FRONTAL_TRACK_COLORS.length;
    return FRONTAL_TRACK_COLORS[idx];
}

function _trackColorDot(trackId){
    const color = _trackColor(trackId);
    return `<span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:${color}; margin-right:5px; vertical-align:middle;"></span>`;
}

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
let _eumetsatFarWatchData      = null;
let _eumetsatFarWatchFetchedAt = 0;
let _eumetsatVeryFarWatchData      = null;
let _eumetsatVeryFarWatchFetchedAt = 0;
let _openMeteoFrontalConfirmData      = null;
let _openMeteoFrontalConfirmFetchedAt = 0;
let _eumetsatTargetSummaryData      = null;
let _eumetsatTargetSummaryFetchedAt = 0;
let _eumetsatWestWatchData      = null;
let _eumetsatWestWatchFetchedAt = 0;
let _eumetsatPrecipHistoryData      = null;
let _eumetsatPrecipHistoryFetchedAt = 0;
let _eumetsatLightningHistoryData      = null;
let _eumetsatLightningHistoryFetchedAt = 0;

// Хронология переходов (data/eumetsat_precip_history.jsonl, пишет
// eumetsat_precip_forecast.py при каждом запуске). Отдельный формат —
// JSON Lines, не единый JSON, поэтому парсинг построчный. См.
// docs/topics/eumetsat.md, обсуждение 2026-08-09 (кейс шквала на пляже —
// разбор задним числом по git-истории коммитов вместо штатной таблицы
// на сайте).
async function loadEumetsatPrecipHistory(){
    if(Date.now() - _eumetsatPrecipHistoryFetchedAt < 12 * 60000) return; // раз в 12 мин
    _eumetsatPrecipHistoryFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_precip_history.jsonl",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const text = await r.text();
        const rows = text.split("\n")
            .map(l => l.trim())
            .filter(Boolean)
            .map(l => { try { return JSON.parse(l); } catch(e){ return null; } })
            .filter(Boolean);
        if(rows.length) _eumetsatPrecipHistoryData = rows;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatPrecipHistoryFetchedAt = 0;
    }
}

// Та же хронология, но для грозы (data/eumetsat_lightning_history.jsonl,
// пишет eumetsat_lightning_forecast.py) — отдельная таблица, не смешивается
// с осадками (см. обсуждение 2026-08-09: раздельные push для дождя и грозы,
// хронология на сайте следует той же логике).
async function loadEumetsatLightningHistory(){
    if(Date.now() - _eumetsatLightningHistoryFetchedAt < 12 * 60000) return; // раз в 12 мин
    _eumetsatLightningHistoryFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_lightning_history.jsonl",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const text = await r.text();
        const rows = text.split("\n")
            .map(l => l.trim())
            .filter(Boolean)
            .map(l => { try { return JSON.parse(l); } catch(e){ return null; } })
            .filter(Boolean);
        if(rows.length) _eumetsatLightningHistoryData = rows;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatLightningHistoryFetchedAt = 0;
    }
}

async function loadEumetsatTargetSummary(){
    if(Date.now() - _eumetsatTargetSummaryFetchedAt < 12 * 60000) return; // раз в 12 мин
    _eumetsatTargetSummaryFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_target_summary.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatTargetSummaryData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatTargetSummaryFetchedAt = 0;
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

async function loadEumetsatFarWatch(){
    // Сервер обновляет не чаще раза в 30 мин (гейт по mtime в
    // gh_satellite_pipeline.py) — 20 мин клиентского опроса с запасом.
    if(Date.now() - _eumetsatFarWatchFetchedAt < 20 * 60000) return;
    _eumetsatFarWatchFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_far_watch.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatFarWatchData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatFarWatchFetchedAt = 0;
    }
}

async function loadEumetsatVeryFarWatch(){
    // [ИЗМЕНЕНО 2026-09-06] Было "раз в 3ч" (60 мин опроса) — 3ч-гейт на
    // сервере убран 2026-09-04, теперь снимок обновляется каждый цикл
    // VPS (~5мин). Опрос сокращён до 5 мин, чтобы кольцо/таблица
    // подтверждения фронтов (open_meteo_frontal_confirm.py) не казались
    // "зависшими" на час.
    if(Date.now() - _eumetsatVeryFarWatchFetchedAt < 5 * 60000) return;
    _eumetsatVeryFarWatchFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_very_far_watch.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatVeryFarWatchData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatVeryFarWatchFetchedAt = 0;
    }
}

async function loadOpenMeteoFrontalConfirm(){
    // Согласовано с пользователем 2026-09-06 — подтверждение фронтов по
    // Open-Meteo (open_meteo_frontal_confirm.py), событийный источник на
    // бэкенде, но здесь просто опрашиваем как обычно (короткого TTL
    // достаточно, лишней сети это не создаёт — файл читается с GitHub,
    // не дёргает Open-Meteo напрямую).
    if(Date.now() - _openMeteoFrontalConfirmFetchedAt < 5 * 60000) return;
    _openMeteoFrontalConfirmFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/open_meteo_frontal_confirm.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.generated_at) _openMeteoFrontalConfirmData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _openMeteoFrontalConfirmFetchedAt = 0;
    }
}

// Западный тайл (пилот, план "мозаика тайлов", 2026-08-16/17) — гейт по
// времени кадра CLM внутри eumetsat_west_watch.py (не искусственный
// wall-clock интервал, см. докстринг там), но качает данные не каждый
// цикл (жёсткий IR+GC-фильтр + STALE_TRACK_MINUTES означают, что кадры
// могут быть редкими) — 20 мин клиентского опроса как у far_watch,
// с запасом.
async function loadEumetsatWestWatch(){
    if(Date.now() - _eumetsatWestWatchFetchedAt < 20 * 60000) return;
    _eumetsatWestWatchFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_west_watch.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.timestamp) _eumetsatWestWatchData = j;
        renderNearbyPrecipCard();
    } catch(e){
        _eumetsatWestWatchFetchedAt = 0;
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

    // Опережающее предупреждение по реестру ложных срабатываний (см.
    // docs/topics/eumetsat.md, запись 2026-08-08 (2)) — этот блок видит
    // ТОЛЬКО CLM/своё поле, без переклёстной проверки внутри одного цикла;
    // если на предыдущей проверке той же точки другие каналы её не
    // подтвердили, честно показываем это здесь же, а не молчим до
    // автоисключения через "Итог".
    const warnHtml = f.cross_check_warning
        ? `<div class="small muted" style="margin-top:6px; color:#e0a030;">⚠ ${f.cross_check_warning}</div>`
        : "";

    return _hr() + _blockTitle(cfg.emoji, cfg.title, timeTag)
        + _plain(`Над станцией: ${stateStr}.`)
        + _subhead(targetStr[0].toUpperCase() + targetStr.slice(1))
        + _bullets(targetBullets)
        + (assessBullets.length ? _subhead("Оценка") + _bullets(assessBullets) : "")
        + warnHtml
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
    // Вид облаков (фаза) — из eumetsat_cloud_phase_type.json, подобран
    // ПО target_id/class, чтобы описывать ровно тот же объект, что и
    // "ближайшее облако" выше (см. docs/topics/eumetsat.md, запись
    // 2026-08-08 — до синхронизации выбора цели это могли быть разные
    // объекты).
    const pt = _eumetsatCloudPhaseTypeData;
    if(pt && f.target_id != null && f.class){
        let label = null;
        if(f.class === "local" && pt.target_confirmation && pt.target_confirmation.target_id === f.target_id){
            label = pt.target_confirmation.roi_dominant_phase_label;
        } else if(f.class === "system" && pt.system_analysis && pt.system_analysis.available && pt.system_analysis.target_id === f.target_id){
            label = pt.system_analysis.roi_dominant_phase_label;
        }
        if(label) out.push(`вид облаков — ${label}`);
    }
    return out;
}

function _renderCloudForecastLines(f){
    return _fieldBlock(f, {
        emoji: "☁️", title: "Облачность",
        // Расширенная градация (запрос 2026-08-10) — см.
        // eumetsat_cloud_forecast.py, current_state теперь считается по
        // пересечению CLM∩ИК∩GeoColour (учитываются только облака,
        // подтверждённые всеми тремя каналами), 6 уровней вместо прежних 3.
        stateLabels: {
            clear: "ясно",
            mostly_clear: "малооблачно",
            variable: "переменная облачность",
            considerable: "значительная облачность",
            cloud: "облачно",
            overcast: "пасмурно",
        },
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

    const labels = { clear: "ясно", variable: "переменная облачность", cloud: "облачно" };
    const stationText = g.station_state ? (labels[g.station_state] || g.station_state) : null;
    const stationHtml = stationText ? _plain(`Над станцией: ${stationText}.`) : "";

    if(!g.valid){
        return _hr() + title + stationHtml + _plain(g.verdict || "Недоступно.");
    }

    const lowConfidence = g.frame_pairs_used != null && g.frame_pairs_used <= 2;
    const suffix = lowConfidence ? " (мало пар кадров — невысокая уверенность)" : "";

    const massBullets = [];
    let massHtml;
    if(g.cloud_mass_distance_km != null){
        massBullets.push(`расстояние: ≈${Math.round(g.cloud_mass_distance_km)} км (${g.cloud_mass_compass})`);
        massBullets.push(`движение: на ${g.direction_compass}`);
        massBullets.push(`скорость: ≈${Math.round(g.speed_kmh)} км/ч`);
        massHtml = _subhead("Основная облачная масса") + _bullets(massBullets);
    } else {
        massHtml = _plain(g.cloud_mass_verdict || "Значимой облачной массы в поле зрения нет.");
    }

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

    return _hr() + title + stationHtml + massHtml + trendHtml + forecastHtml;
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

    const stateLabels = { clear: "ясно", variable: "переменная облачность", cloud: "облачно" };
    const stationText = g.station_state ? (stateLabels[g.station_state] || g.station_state) : null;
    const stationHtml = stationText ? _plain(`Над станцией: ${stationText}.`) : "";

    if(!g.valid){
        return _hr() + title + stationHtml + _plain(g.verdict || "Недоступно.");
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

    return _hr() + title + stationHtml + massHtml + trendHtml + forecastHtml;
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

// Сводка геометрии анализа — единая шапка перед всеми блоками карточки.
// Источник данных: observed_area из eumetsat_geocolour_motion.json (единственный
// скрипт, который сейчас публикует geometry в JSON). window/center/local_trend_radius_km
// приходят с сервера напрямую из field_motion_common.py (CENTER_LAT/LON, HALF_WINDOW_DEG,
// LOCAL_RADIUS_KM), state_radius_km — из fc.STATE_RADIUS_KM (добавлено 2026-08-02).
// Радиус для осадков/гроз (192км) НЕ отдельная константа на сервере — это ровно
// половина ширины окна (motion_window_km.width / 2), т.к. и *_motion.py, и
// eumetsat_lightning_forecast.py используют один и тот же HALF_WINDOW_DEG/KM_PER_DEG_LON
// из field_motion_common.py. Считаем на лету, а не дублируем магическое число —
// если HALF_WINDOW_DEG когда-нибудь изменится, оба числа обновятся синхронно сами.
//
// ВАЖНО: "радиус" здесь имеет два разных смысла:
//  - 12км и 50км — настоящий круг (маска по honest haversine-расстоянию, см.
//    _radius_mask()/station_area_mask() в scripts).
//  - 192км (осадки/гроза) — НЕ круг, а половина ширины прямоугольного окна
//    по долготе (запад-восток). По широте (север-юг) окно тянется дальше,
//    до ≈278км (половина от height=557км) — окно квадратное в градусах
//    (2.5°×2.5°), но не в км, из-за сужения градуса долготы на широте Одессы.
function _renderAreaSummary(g, farData, veryFarData){
    const area = g && g.observed_area;
    if(!area || area.center_lat == null || area.center_lon == null) return "";

    const bullets = [];
    const w = area.motion_window_km && area.motion_window_km.width;
    const h = area.motion_window_km && area.motion_window_km.height;
    if(w && h) bullets.push(`окно: ≈${w} × ${h} км`);
    bullets.push(`центр: ${Number(area.center_lat).toFixed(2)}°N, ${Number(area.center_lon).toFixed(2)}°E (Одесса)`);

    const stateRadius = area.state_radius_km || 12; // фолбэк на старые data-файлы без поля
    bullets.push(`локальный обзор над станцией, радиус ≈${stateRadius} км`);

    if(area.local_trend_radius_km) bullets.push(`анализ облачности в радиусе ≈${area.local_trend_radius_km} км`);

    const precipRadius = w ? Math.round(w / 2) : 192; // фолбэк, если окна ещё нет в данных
    bullets.push(`анализ осадков и гроз в радиусе ≈${precipRadius} км`);

    // Далёкие тиры (2026-08-03) — радиус берём из самих far/very_far данных
    // (observed_area.radius_label_km), а не хардкодим тут: если появятся —
    // подтянутся сами, если ещё не загрузились — тихо не показываем строку
    // (не ждём их специально, area уже требует geocolour_motion как основу).
    const farRadius = farData && farData.observed_area && farData.observed_area.radius_label_km;
    if(farRadius) bullets.push(`дальний контроль (Балканы/Турция/Центр.Европа) — радиус ≈${farRadius} км`);
    const veryFarRadius = veryFarData && veryFarData.observed_area && veryFarData.observed_area.radius_label_km;
    if(veryFarRadius) bullets.push(`очень дальний контроль (Испания/Италия/Британия) — радиус ≈${veryFarRadius} км`);

    return _subhead("Область анализа") + _bullets(bullets);
}

// Компас-названия секторов — те же 8, что и fc.COMPASS на Python-стороне
// (scripts/field_motion_common.py), порядок важен для читаемого текста.
const _COMPASS_RU = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"];

function _renderOneFarTier(data, label){
    if(!data) return "";
    const ts = data.timestamp ? _obsTimeTag(data.timestamp, 240) : ""; // окно "устарело" пошире — тир редкий (30мин/3ч), не 10-15мин как ближние
    const img = data.observed_area && data.observed_area.geocolour_image;
    const imgHtml = img
        ? `<img src="https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/${img}?v=${encodeURIComponent(data.timestamp || "")}"
                alt="${label}" style="width:100%; border-radius:8px; margin:6px 0; display:block;"
                onerror="this.style.display='none';">`
        : "";

    const sectorBullets = _COMPASS_RU
        .map(name => [name, data.sectors && data.sectors[name]])
        .filter(([, s]) => s && s.cloud_fraction != null && s.cloud_fraction >= 0.1)
        .sort((a, b) => b[1].cloud_fraction - a[1].cloud_fraction)
        .map(([name, s]) => {
            const pct = Math.round(s.cloud_fraction * 100);
            const trend = s.trend ? `, ${s.trend}` : "";
            return `${name}: ${pct}%${trend}`;
        });

    return _blockTitle("🌍", label, ts)
        + imgHtml
        + _plain(data.verdict || "нет данных")
        + (sectorBullets.length ? _bullets(sectorBullets) : "");
}

// Слой конфликтов — сводка target_confirmation всех 5 модулей в одно
// место (data/eumetsat_target_summary.json, пишет eumetsat_target_summary.py,
// см. docs/topics/eumetsat.md, план от 2026-08-04/05). Ставится ПЕРВЫМ
// блоком карточки — это уже готовый вывод ("что происходит"), детали по
// каждому каналу идут ниже как обоснование, а не наоборот.
const _CONSENSUS_BADGE = {
    confirmed:        { color: "#4caf50", label: "подтверждено" },
    not_confirmed:     { color: "#888",    label: "не подтверждено" },
    disputed:          { color: "#e0a030", label: "каналы расходятся" },
    insufficient_data: { color: "#666",    label: "недостаточно данных" },
};
// Отдельный бейдж для case'а "цель — уже известный повторяющийся шумовой
// объект, подавлено по реестру ложных срабатываний" (не то же самое, что
// not_confirmed — здесь мы даже не гоняли повторную ROI-проверку в этом
// цикле, см. docs/topics/eumetsat.md, запись 2026-08-07).
const _SUPPRESSED_BADGE = { color: "#5c6bc0", label: "известный шумовой объект" };
function _moduleIcon(confirmed){
    if(confirmed === true) return "✅";
    if(confirmed === false) return "❌";
    return "➖";
}
const _MODULE_LABELS = {
    ir_motion: "ИК", geocolour_motion: "GeoColour", cloud_phase_type: "Фаза/тип",
    precip_forecast: "Осадки", lightning_forecast: "Гроза",
};
function _renderTargetSummaryLines(s){
    if(!s) return "";
    const timeTag = _obsTimeTag(s.timestamp, 20);

    if(s.status === "no_data") return "";
    if(s.status === "no_target"){
        return `${_blockTitle("🎯", "Итог", timeTag)}`
            + _plain("Значимых облачных масс поблизости сейчас нет.");
    }
    if(s.status === "system_only"){
        return `${_blockTitle("🎯", "Итог", timeTag)}`
            + _plain(s.verdict);
    }
    if(s.status === "suppressed_known_false_positive"){
        return `${_blockTitle("🎯", "Итог", timeTag)}`
            + `<div style="margin-top:4px;">`
            + `<span style="display:inline-block; padding:1px 8px; border-radius:10px; background:${_SUPPRESSED_BADGE.color}; `
            + `color:#fff; font-size:11.5px; font-weight:700;">${_SUPPRESSED_BADGE.label}</span>`
            + `</div>`
            + _plain(s.verdict);
    }
    if(s.status !== "ok") return "";

    const badge = _CONSENSUS_BADGE[s.existence.consensus] || _CONSENSUS_BADGE.insufficient_data;
    const moduleBits = Object.entries(s.existence.modules)
        .map(([k, v]) => `${_moduleIcon(v.confirmed)} ${_MODULE_LABELS[k] || k}`).join("&nbsp;&nbsp;");
    const phenomBits = Object.entries(s.phenomena || {})
        .map(([k, v]) => `${_moduleIcon(v.confirmed)} ${_MODULE_LABELS[k] || k}`).join("&nbsp;&nbsp;");

    return `${_blockTitle("🎯", "Итог", timeTag)}`
        + `<div style="margin-top:4px;">`
        + `<span style="display:inline-block; padding:1px 8px; border-radius:10px; background:${badge.color}; `
        + `color:#111; font-size:11.5px; font-weight:700;">${badge.label}</span>`
        + `</div>`
        + _plain(s.verdict)
        + _subhead("По каналам")
        + `<div class="small muted" style="margin-top:2px; font-size:12px;">${moduleBits}</div>`
        + (phenomBits ? `<div class="small muted" style="margin-top:2px; font-size:12px;">${phenomBits}</div>` : "");
}

// Таблица ВСЕХ локальных очагов (не только первичного, который уже описан
// в "Итог" выше как voting-цель) — снапшот, не хронология. Та же структура
// колонок, что у таблицы систем ниже (по запросу из Horizon 2026-08-09:
// "такая же таблица, как для систем, для локальных очагов"). "Фронт?"
// у локальных очагов всегда "—" (компактные массы <300км² физически не
// могут быть фронтом, см. docs/topics/eumetsat.md) — колонка оставлена
// для единообразия вида с таблицей систем.
function _renderLocalCandidatesTable(rows, suppressedCount){
    const supNote = suppressedCount > 0
        ? `<div style="color:#777; font-size:11.5px; margin-top:4px;">+${suppressedCount} известных шумовых ${suppressedCount === 1 ? "объект" : "объекта"} скрыто (не подтверждены ни ИК, ни GeoColour)</div>`
        : "";
    if(!rows || !rows.length){
        if(suppressedCount > 0){
            return `<div style="margin-top:10px; color:#72c8ff; font-size:13px; font-weight:600;">☁️ Локальные очаги (0)</div>${supNote}`;
        }
        return "";
    }
    const trs = rows.map(r => {
        const dist = r.distance_km != null ? r.distance_km : "—";
        const dir = r.compass || "—";
        const area = r.area_km2 != null ? Math.round(r.area_km2).toLocaleString("ru-RU") : "—";
        const axisDeg = r.elongation_axis_deg != null ? ` (${Math.round(r.elongation_axis_deg)}°)` : "";
        const axis = r.elongation_axis_compass ? `${r.elongation_axis_compass}${axisDeg}` : "—";
        const ratio = r.elongation_aspect_ratio != null ? r.elongation_aspect_ratio.toFixed(2) : "—";
        const front = r.frontlike ? "🌩️" : "—";
        const phase = r.phase_label && r.phase_label !== "безоблачно" ? r.phase_label : "—";
        const typeLbl = r.type_label && r.type_label !== "безоблачно" ? r.type_label : "—";
        const precip = r.has_precip === true ? "🌧️" : (r.has_precip === false ? "—" : "?");
        const lightning = r.has_lightning === true ? "⚡" : (r.has_lightning === false ? "—" : "?");
        const irConf = r.ir_confirmed === true ? "✅" : (r.ir_confirmed === false ? "❌" : "?");
        const gcConf = r.geocolour_confirmed === true ? "✅" : (r.geocolour_confirmed === false ? "❌" : "?");
        return `<tr>
            <td style="padding:3px 10px 3px 0; color:#bbb; text-align:right;">${dist}</td>
            <td style="padding:3px 10px; color:#bbb;">${dir}</td>
            <td style="padding:3px 10px; color:#bbb; text-align:right;">${area}</td>
            <td style="padding:3px 10px; color:#ccc;">${axis}</td>
            <td style="padding:3px 10px; color:#ccc; text-align:right;">${ratio}</td>
            <td style="padding:3px 0; text-align:center;">${front}</td>
            <td style="padding:3px 0 3px 10px; color:#ccc;">${phase}</td>
            <td style="padding:3px 0 3px 10px; color:#ccc;">${typeLbl}</td>
            <td style="padding:3px 0; text-align:center;">${precip}</td>
            <td style="padding:3px 0; text-align:center;">${lightning}</td>
            <td style="padding:3px 0; text-align:center;">${irConf}</td>
            <td style="padding:3px 0; text-align:center;">${gcConf}</td>
        </tr>`;
    }).join("");
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">☁️ Локальные очаги (${rows.length})</summary>
        <div style="overflow-x:auto; margin-top:6px;">
        <table style="width:100%; border-collapse:collapse; font-size:12.5px;">
            <thead><tr style="color:#777; text-align:left;">
                <th style="padding:3px 10px 3px 0; font-weight:600; text-align:right;">Км</th>
                <th style="padding:3px 10px; font-weight:600;">Напр.</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Площадь</th>
                <th style="padding:3px 10px; font-weight:600;">Ось</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Aspect</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">Фронт?</th>
                <th style="padding:3px 0 3px 10px; font-weight:600;">Фаза</th>
                <th style="padding:3px 0 3px 10px; font-weight:600;">Тип</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">🌧️</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">⚡</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;" title="ИК">IR</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;" title="Естественный свет (GeoColour)">GC</th>
            </tr></thead>
            <tbody>${trs}</tbody>
        </table>
        </div>
    </details>${supNote}`;
}

// Таблица ВСЕХ систем синоптического масштаба (не только ближайшей, которая
// уже описана в "Итог" выше) — снапшот, не хронология. По запросу
// 2026-08-09: раньше дальние системы считались (elongation/frontlike есть
// у каждого кандидата в cloud_forecast.json), но нигде не показывались.
function _renderSystemCandidatesTable(rows, suppressedCount){
    const supNote = suppressedCount > 0
        ? `<div style="color:#777; font-size:11.5px; margin-top:4px;">+${suppressedCount} известных шумовых ${suppressedCount === 1 ? "объект" : "объекта"} скрыто (не подтверждены ни ИК, ни GeoColour)</div>`
        : "";
    if(!rows || !rows.length){
        if(suppressedCount > 0){
            return `<div style="margin-top:10px; color:#72c8ff; font-size:13px; font-weight:600;">🌍 Системы синоптического масштаба (0)</div>${supNote}`;
        }
        return "";
    }
    const trs = rows.map(r => {
        const dist = r.distance_km != null ? r.distance_km : "—";
        const dir = r.compass || "—";
        const area = r.area_km2 != null ? Math.round(r.area_km2).toLocaleString("ru-RU") : "—";
        const axisDeg = r.elongation_axis_deg != null ? ` (${Math.round(r.elongation_axis_deg)}°)` : "";
        const axis = r.elongation_axis_compass ? `${r.elongation_axis_compass}${axisDeg}` : "—";
        const ratio = r.elongation_aspect_ratio != null ? r.elongation_aspect_ratio.toFixed(2) : "—";
        const front = r.frontlike ? "🌩️" : "—";
        // Обогащение по каналам (фаза/осадки/гроза) для КАЖДОЙ системы —
        // по запросу 2026-08-09, тот же смысл, что и модули подтверждения
        // у локальных целей, но здесь не voting, а просто "что внутри".
        const phase = r.phase_label && r.phase_label !== "безоблачно" ? r.phase_label : "—";
        const typeLbl = r.type_label && r.type_label !== "безоблачно" ? r.type_label : "—";
        const precip = r.has_precip === true ? "🌧️" : (r.has_precip === false ? "—" : "?");
        const lightning = r.has_lightning === true ? "⚡" : (r.has_lightning === false ? "—" : "?");
        const irConf = r.ir_confirmed === true ? "✅" : (r.ir_confirmed === false ? "❌" : "?");
        const gcConf = r.geocolour_confirmed === true ? "✅" : (r.geocolour_confirmed === false ? "❌" : "?");
        // window_spanning — bbox упирается в оба края окна обзора хотя бы по
        // одной оси, подозрение на склейку разрозненных пятен через шум при
        // 8-связной разметке (см. docs/topics/eumetsat.md, 2026-08-09
        // "продолжение 4"). Площадь/форма этой строки ненадёжны — не скрываем,
        // но помечаем и приглушаем визуально.
        const spanning = !!r.window_spanning;
        const rowStyle = spanning ? ' style="opacity:0.6;"' : "";
        const areaLabel = spanning
            ? `<span title="Площадь/форма ненадёжны — объект упирается в границы окна обзора, возможна склейка через шум">⚠️ ${area}</span>`
            : area;
        return `<tr${rowStyle}>
            <td style="padding:3px 10px 3px 0; color:#bbb; text-align:right;">${dist}</td>
            <td style="padding:3px 10px; color:#bbb;">${dir}</td>
            <td style="padding:3px 10px; color:#bbb; text-align:right;">${areaLabel}</td>
            <td style="padding:3px 10px; color:#ccc;">${axis}</td>
            <td style="padding:3px 10px; color:#ccc; text-align:right;">${ratio}</td>
            <td style="padding:3px 0; text-align:center;">${front}</td>
            <td style="padding:3px 0 3px 10px; color:#ccc;">${phase}</td>
            <td style="padding:3px 0 3px 10px; color:#ccc;">${typeLbl}</td>
            <td style="padding:3px 0; text-align:center;">${precip}</td>
            <td style="padding:3px 0; text-align:center;">${lightning}</td>
            <td style="padding:3px 0; text-align:center;">${irConf}</td>
            <td style="padding:3px 0; text-align:center;">${gcConf}</td>
        </tr>`;
    }).join("");
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">🌍 Системы синоптического масштаба (${rows.length})</summary>
        <div style="overflow-x:auto; margin-top:6px;">
        <table style="width:100%; border-collapse:collapse; font-size:12.5px;">
            <thead><tr style="color:#777; text-align:left;">
                <th style="padding:3px 10px 3px 0; font-weight:600; text-align:right;">Км</th>
                <th style="padding:3px 10px; font-weight:600;">Напр.</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Площадь</th>
                <th style="padding:3px 10px; font-weight:600;">Ось</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Aspect</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">Фронт?</th>
                <th style="padding:3px 0 3px 10px; font-weight:600;">Фаза</th>
                <th style="padding:3px 0 3px 10px; font-weight:600;">Тип</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">🌧️</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">⚡</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;" title="ИК">IR</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;" title="Естественный свет (GeoColour)">GC</th>
            </tr></thead>
            <tbody>${trs}</tbody>
        </table>
        </div>
    </details>${supNote}`;
}

// Снимок ВСЕХ систем синоптического масштаба (не персистентные frontlike-
// треки ниже, а СНАПШОТ текущего кадра — все "system"-класс структуры,
// подтверждённые хотя бы одним из ИК/GeoColour, независимо от вытянутости/
// накопленной истории). Покраска РЕАЛЬНЫХ пикселей блоба, тем же приёмом,
// что "Треки фронтов" на Cloud Mask (см. eumetsat_render_track_overlay.py),
// источник — eumetsat_render_systems_overlay.py + target_summary.
// system_candidates. По запросу пользователя: абстрактная линия PCA-оси
// на GeoColour ("Треки фронтов") оказалась малоинформативной ("это всё
// что угодно, только не фронт") — для систем выбран сразу подход "красим
// реальную форму".
// Цвет закреплён за ПОЗИЦИЕЙ в списке (тот же порядок, что в таблице
// выше), НЕ за физическим объектом — target_id системы не персистентен
// между циклами (см. докстринг eumetsat_render_systems_overlay.py),
// поэтому цвет одной и той же реальной системы может смениться при
// следующем обновлении страницы — это ожидаемо, не баг.
function _renderSystemsSnapshot(targetSummaryData){
    const rows = targetSummaryData && targetSummaryData.system_candidates;
    // ВАЖНО: targetSummaryData.timestamp — это время ЗАПУСКА
    // eumetsat_target_summary.py (он выполняется КАЖДЫЙ цикл, даже когда
    // cloud_forecast.py застрял/скипнут), а не время самого кадра CLM, на
    // основе которого построена картинка. Реальное время кадра —
    // cloud_forecast_timestamp (тот же таймстемп, что показан под
    // "Центральный тайл — снимки" ниже). Раньше здесь ошибочно стоял
    // .timestamp — из-за этого подпись могла показывать "23:23", когда
    // картинка на самом деле построена по кадру 23:00 (несоответствие
    // замечено пользователем на скриншоте 2026-09-02).
    const frameTs = targetSummaryData && targetSummaryData.cloud_forecast_timestamp;
    if(!rows || !rows.length || !frameTs) return "";
    const ts = _obsTimeTag(frameTs, 20);
    const src = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_systems_snapshot.png?v=${encodeURIComponent(frameTs)}`;
    return `<div style="margin-top:10px;">
        <div style="color:#72c8ff; font-size:13px; font-weight:600; margin-bottom:4px;">🎨 Системы синоптического масштаба — на карте ${ts}</div>
        <img src="${src}" alt="Системы синоптического масштаба"
             style="width:100%; border-radius:8px; display:block;"
             onerror="this.parentElement.style.display='none';">
        <div style="color:#777; font-size:11px; margin-top:3px;">Реальная форма каждой системы из таблицы выше; цвет = позиция в таблице (сверху вниз), может смениться при следующем обновлении — это не тот же трекинг, что у "Треков фронтов" ниже.</div>
    </div>`;
}

// Последний снимок GeoColour — чистый натуральный цвет (без оверлея
// классификации, тот отдельно, только для внутренней калибровки, см.
// eumetsat_geocolour_debug_preview.png) — по запросу 2026-08-10,
// уточнённому после скриншота ("я имел в виду ЭТОТ снимок" — натуральный
// цвет как на eumetsat.html). Полупрозрачной жёлтой окружностью (по
// отдельному запросу "сделай не такой яркий" — см.
// fc.draw_view_radius_circle() в field_motion_common.py) размечена зона
// обзора тира "near" (~192км, radius fc.NEAR_RADIUS_KM) — именно оттуда
// берутся все кандидаты для таблиц local_candidates/system_candidates
// выше; всё, что за кругом (например облачность на востоке/северо-востоке),
// таблицы не видят — это ловит только далёкий грубый посекторный far_watch
// ниже. Файл перезаписывается КАЖДЫЙ цикл eumetsat_geocolour_motion.py
// (см. _save_clean_snapshot()) — всегда самый свежий кадр, кэш-бастинг
// через timestamp самих geocolour-данных.
// Треки фронтоподобных систем во времени — шаг 4 плана "Отслеживание
// фронтов" (2026-08-14, см. docs/topics/eumetsat.md). Источник —
// data/eumetsat_frontal_track.json через target_summary.frontal_tracks
// (не отдельная загрузка, чтобы не плодить ещё один fetch — файл маленький
// и уже проходит через target_summary как единая точка сборки). Строка
// таблицы = один активный трек (пойман в ТЕКУЩЕМ кадре, см. докстринг
// eumetsat_frontal_track.py — устаревшие треки target_summary не отдаёт).
// velocity/movement_bearing присутствуют только при points_count>=3
// (см. MIN_POINTS_FOR_VELOCITY в скрипте) — до этого строка показывает
// только текущее положение/ось, без "куда и как быстро едет".
// Наблюдения наземных станций "впереди"/"позади" трека — план шага 5
// "Наземные наблюдения вдоль траектории фронта" (2026-08-14/15), пункт 5.
// По запросу 2026-08-15 ("не хватает осадков/ветра/экстремальных явлений")
// показываем не только давление+тенденцию+температуру+облачность, но и
// осадки (precip_mm/precip_period_hours) и текущую погоду
// (present_weather_label/is_extreme_weather из группы 7wwW1W2, см.
// ground_station_obs_fetch.py). station — запись из ahead_station/
// behind_station (name/along_km/perp_km/wmo_synop_id/...), obs — запись
// из ahead_obs/behind_obs (может быть null — станция выбрана геометрией,
// но SYNOP ещё не подтянут, лаг в 1 цикл, см. eumetsat_frontal_track.py).
function _renderStationObsPanel(sideLabel, station, obs){
    if(!station) return `<div style="color:#666; font-size:12px; margin-top:4px;">${sideLabel}: станция не найдена (нет подходящей в радиусе курса)</div>`;
    const along = station.along_km != null ? Math.round(Math.abs(station.along_km)) : "—";
    const name = station.name || "—";
    const header = `<div style="color:#9fd6ff; font-size:12.5px; font-weight:600;">${sideLabel}: ${name} <span style="color:#777; font-weight:400;">(${along}км)</span></div>`;

    if(!obs || !obs.obs_time){
        return `<div style="margin-top:4px;">${header}<div style="color:#777; font-size:11.5px; margin-top:2px;">наблюдение ещё не получено</div></div>`;
    }

    const timeTag = _obsTimeTag(obs.obs_time, obs.obs_source === "BUFR" ? 90 : 200); // BUFR почасовой — порог строже, чем у SYNOP (~3ч)
    // Метка источника — 2026-08-16, BUFR-фолбэк (Meteomanz) подключён для
    // станций, переставших слать классический SYNOP на ogimet (найдено на
    // FETESTI/MAHMUDIA); показываем явно, чтобы не выглядело как обычный
    // SYNOP — набор полей чуть уже (нет периода осадков и т.п.).
    const sourceTag = obs.obs_source === "BUFR"
        ? `<span style="color:#8899aa; font-size:10.5px; margin-left:4px;" title="Данные получены не из SYNOP (станция его не шлёт), а из часового автоматического BUFR (Meteomanz)">· BUFR</span>`
        : "";
    const temp = obs.temp != null ? `${obs.temp > 0 ? "+" : ""}${obs.temp}°C` : "—";
    let pressure = "—";
    if(obs.sea_pressure != null){
        pressure = `${obs.sea_pressure} гПа`;
        if(obs.pressure_tendency_value != null){
            const tv = obs.pressure_tendency_value;
            const arrow = tv > 0.1 ? "↑" : (tv < -0.1 ? "↓" : "→");
            pressure += ` ${arrow}${Math.abs(tv).toFixed(1)}`;
        }
    }
    const cloud = obs.total_cloud_okta != null ? `${obs.total_cloud_okta}/8` : "—";
    let wind = "—";
    if(obs.wind_speed_ms != null){
        wind = obs.wind_dir_deg != null ? `${obs.wind_dir_deg}° ${obs.wind_speed_ms}м/с` : `${obs.wind_speed_ms}м/с (штиль/неопр.)`;
    }
    let precip = "—";
    if(obs.precip_mm != null){
        const period = obs.precip_period_hours != null ? `/${obs.precip_period_hours}ч` : "";
        precip = `${obs.precip_mm}мм${period}`;
    }

    let weatherLine = "";
    if(obs.present_weather_label){
        const badgeColor = obs.is_extreme_weather ? "#ff5555" : "#e0a030";
        const badgeBg = obs.is_extreme_weather ? "rgba(255,85,85,0.12)" : "rgba(224,160,48,0.10)";
        const icon = obs.is_extreme_weather ? "⚠️ " : "";
        weatherLine = `<div style="margin-top:3px;"><span style="color:${badgeColor}; background:${badgeBg}; border-radius:4px; padding:1px 6px; font-size:11.5px;">${icon}${obs.present_weather_label}</span></div>`;
    }

    return `<div style="margin-top:4px;">
        ${header}${timeTag ? `<span style="font-size:11px;">${timeTag}</span>` : ""}${sourceTag}
        <div style="color:#ccc; font-size:11.5px; margin-top:2px; display:flex; gap:12px; flex-wrap:wrap;">
            <span>🌡️ ${temp}</span>
            <span>📈 ${pressure}</span>
            <span>☁️ ${cloud}</span>
            <span>💨 ${wind}</span>
            <span>🌧️ ${precip}</span>
        </div>
        ${weatherLine}
    </div>`;
}

// opts.tileFilter — "west" | "near" | undefined(все). Треки без поля tile
// (старые записи, до 2026-08-17) считаются "near" — тайл near был основным
// с самого начала, west подключён позже. opts.title переопределяет
// заголовок аккордеона (используется, когда таблица встраивается ВНУТРЬ
// уже существующего аккордея своего тайла — запрос пользователя
// 2026-08-17: "раздельная таблица только для фронтов западного тайла" /
// "только для фронтов центрального тайла", вместо одной общей таблицы).
function _renderFrontalTracksTable(tracks, opts){
    opts = opts || {};
    const tileFilter = opts.tileFilter;
    const filtered = (tracks || []).filter(t => {
        if(!tileFilter) return true;
        const tile = t.tile || "near";
        return tile === tileFilter;
    });
    if(!filtered.length) return "";
    const titleText = opts.title || "Треки фронтов";
    const trs = filtered.map(t => {
        const dist = t.distance_from_odessa_km != null ? t.distance_from_odessa_km : "—";
        const dir = t.direction_compass || "—";
        const area = t.area_km2 != null ? Math.round(t.area_km2).toLocaleString("ru-RU") : "—";
        const axisDeg = t.axis_deg != null ? ` (${Math.round(t.axis_deg)}°)` : "";
        const axis = axisDeg ? axisDeg.trim() : "—";
        const age = t.age_minutes != null ? `${Math.round(t.age_minutes)} мин` : "—";
        const hasVelocity = t.velocity_kmh != null;
        const velocity = hasVelocity ? `${Math.round(t.velocity_kmh)} км/ч` : "—";
        const moveDir = hasVelocity && t.movement_bearing_compass ? t.movement_bearing_compass : "—";
        const rotation = t.axis_rotation_deg != null ? `${Math.round(t.axis_rotation_deg)}°` : "—";
        // Осадки/гроза (2026-08-14) — та же трёхзначная логика, что везде
        // в проекте: true/false/null различаются, "?" ≠ "—" (см. систему
        // подавления и системную таблицу выше). null означает "канал не
        // отработал в этом кадре для этого target_id", НЕ "точно нет".
        const precip = t.has_precip === true ? "🌧️" : (t.has_precip === false ? "—" : "?");
        const lightning = t.has_lightning === true ? "⚡" : (t.has_lightning === false ? "—" : "?");
        // Молодые треки (<3 точек) ещё не публикуют скорость — приглушаем
        // строку, чтобы визуально не путать "пока нет данных" с "стоит на
        // месте" (velocity_kmh=0 выглядело бы так же, как отсутствие поля,
        // если не различать явно).
        const pending = !hasVelocity;
        const rowStyle = pending ? ' style="opacity:0.6;"' : "";
        const velocityLabel = pending
            ? `<span title="Меньше 3 подтверждений подряд — скорость ещё не публикуется">${velocity}</span>`
            : velocity;
        // Станции вдоль курса — план шага 5, пункт 5 (2026-08-15). Под
        // спойлером на строку трека (не отдельной таблицей, не прямо в
        // строке) — по решению Claude при отсутствии предпочтения
        // пользователя, тот же паттерн, что уже принят для "Подробности
        // по каналам". Показываются только когда известно движение трека
        // (иначе ahead_station/behind_station всегда null, см.
        // ground_station_selector.select_ahead_behind).
        const stationsBlock = hasVelocity ? `<tr${rowStyle}>
            <td colspan="11" style="padding:0 0 6px 0;">
                <details style="margin-top:2px;">
                    <summary style="cursor:pointer; color:#666; font-size:11.5px;">Станции вдоль курса</summary>
                    <div style="margin-top:4px; padding-left:6px; border-left:2px solid #333;">
                        ${_renderStationObsPanel("Впереди", t.ahead_station, t.ahead_obs)}
                        ${_renderStationObsPanel("Позади", t.behind_station, t.behind_obs)}
                    </div>
                </details>
            </td>
        </tr>` : "";
        return `<tr${rowStyle}>
            <td style="padding:3px 10px 3px 0; color:#666; font-family:monospace;">${_trackColorDot(t.track_id)}#${t.track_id != null ? t.track_id : "?"}</td>
            <td style="padding:3px 10px 3px 0; color:#bbb; text-align:right;">${dist}</td>
            <td style="padding:3px 10px; color:#bbb;">${dir}</td>
            <td style="padding:3px 10px; color:#bbb; text-align:right;">${area}</td>
            <td style="padding:3px 10px; color:#ccc;">${axis}</td>
            <td style="padding:3px 10px; color:#ccc; text-align:right;">${velocityLabel}</td>
            <td style="padding:3px 10px; color:#ccc;">${moveDir}</td>
            <td style="padding:3px 10px; color:#ccc; text-align:right;">${rotation}</td>
            <td style="padding:3px 0; text-align:center;">${precip}</td>
            <td style="padding:3px 0; text-align:center;">${lightning}</td>
            <td style="padding:3px 0; color:#888; text-align:right;">${age}</td>
        </tr>${stationsBlock}`;
    }).join("");
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">🌩️ ${titleText} (${filtered.length})</summary>
        <div style="overflow-x:auto; margin-top:6px;">
        <table style="width:100%; border-collapse:collapse; font-size:12.5px;">
            <thead><tr style="color:#777; text-align:left;">
                <th style="padding:3px 10px 3px 0; font-weight:600;" title="Условный номер трека — сквозной счётчик, не переиспользуется. Цвет кружка = цвет покраски этого фронта на снимке выше (реальная форма блоба, не эллипс)">#</th>
                <th style="padding:3px 10px 3px 0; font-weight:600; text-align:right;">Км</th>
                <th style="padding:3px 10px; font-weight:600;">Напр.</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Площадь</th>
                <th style="padding:3px 10px; font-weight:600;">Ось</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;" title="Скорость смещения центроида">Скорость</th>
                <th style="padding:3px 10px; font-weight:600;" title="Куда движется (не ось, а направление смещения)">Движение</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;" title="Поворот оси за время трека">Поворот</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">🌧️</th>
                <th style="padding:3px 0; font-weight:600; text-align:center;">⚡</th>
                <th style="padding:3px 0; font-weight:600; text-align:right;">Возраст</th>
            </tr></thead>
            <tbody>${trs}</tbody>
        </table>
        </div>
    </details>`;
}

function _renderGeocolourSnapshot(geocolourData){
    if(!geocolourData || !geocolourData.timestamp) return "";
    const ts = _obsTimeTag(geocolourData.timestamp, 20);
    const src = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_geocolour_snapshot.png?v=${encodeURIComponent(geocolourData.timestamp)}`;
    return `<div style="margin-top:10px;">
        <div style="color:#72c8ff; font-size:13px; font-weight:600; margin-bottom:4px;">🛰️ Последний снимок GeoColour ${ts}</div>
        <img src="${src}" alt="GeoColour"
             style="width:100%; border-radius:8px; display:block;"
             onerror="this.parentElement.style.display='none';">
        <div style="color:#777; font-size:11px; margin-top:3px;">Круг — зона обзора таблиц выше (~192км); дальше видит только грубый посекторный обзор ниже</div>
    </div>`;
}

// Последний снимок ИК (10.5 мкм) — под GeoColour, по прямому запросу
// 2026-08-10 ("под этим снимком добавь ИК, такой же, с кругом"). Тот же
// принцип: eumetsat_ir_motion.py._save_ir_snapshot() перезаписывает файл
// каждый цикл, тот же fc.draw_view_radius_circle() для круга — визуально
// согласовано со снимком GeoColour выше.
function _renderIrSnapshot(irData){
    if(!irData || !irData.timestamp) return "";
    const ts = _obsTimeTag(irData.timestamp, 20);
    const src = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_ir_snapshot.png?v=${encodeURIComponent(irData.timestamp)}`;
    return `<div style="margin-top:10px;">
        <div style="color:#72c8ff; font-size:13px; font-weight:600; margin-bottom:4px;">🌡️ Последний снимок ИК 10.5 мкм ${ts}</div>
        <img src="${src}" alt="ИК 10.5 мкм"
             style="width:100%; border-radius:8px; display:block;"
             onerror="this.parentElement.style.display='none';">
        <div style="color:#777; font-size:11px; margin-top:3px;">Тот же круг — зона обзора таблиц выше (~192км)</div>
    </div>`;
}

// Снимки ЗАПАДНОГО тайла (пилот, план "мозаика тайлов", 2026-08-16) —
// В АККОРДЕОНЕ (свёрнут по умолчанию), по прямому запросу пользователя
// 2026-08-17 ("Снимки выводим в аккордеоне") — в отличие от near-tier
// снимков выше (всегда развёрнуты, это основной тайл), west — вторичный/
// диагностический, не должен быть на виду по умолчанию. GeoColour и CLM
// сохраняются КАЖДЫЙ непустой цикл eumetsat_west_watch.py вместе (тот же
// момент времени = тот же timestamp), в отличие от near-tier, где это два
// разных файла/скрипта — здесь один источник data (geocolourData==clmData
// по факту, оставлено одним параметром для ясности).
function _renderWestSnapshot(westData, tracks){
    if(!westData || !westData.timestamp) return "";
    const ts = _obsTimeTag(westData.timestamp, 20);
    const n = (westData.candidates || []).length;
    const gcSrc = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_west_snapshot_geocolour.png?v=${encodeURIComponent(westData.timestamp)}`;
    const irSrc = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_west_snapshot_ir.png?v=${encodeURIComponent(westData.timestamp)}`;
    const clmSrc = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_west_snapshot_clm.png?v=${encodeURIComponent(westData.timestamp)}`;
    // Отдельная таблица ТОЛЬКО фронтов западного тайла (запрос пользователя
    // 2026-08-17) — раньше "Треки фронтов" была одной общей таблицей (near+
    // west вперемешку, различить можно было только по чтению координат).
    const tracksHtml = _renderFrontalTracksTable(tracks, {tileFilter: "west", title: "Треки фронтов (западный тайл)"});
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">🧩 Западный тайл — снимки ${ts} (кандидатов: ${n})</summary>
        <div style="margin-top:6px;">
            ${tracksHtml}
            <div style="color:#777; font-size:11px; margin-bottom:3px;">GeoColour</div>
            <img src="${gcSrc}" alt="Западный тайл — GeoColour"
                 style="width:100%; border-radius:8px; display:block;"
                 onerror="this.parentElement.style.display='none';">
            <div style="color:#777; font-size:11px; margin:8px 0 3px;">ИК 10.5 мкм</div>
            <img src="${irSrc}" alt="Западный тайл — ИК"
                 style="width:100%; border-radius:8px; display:block;"
                 onerror="this.parentElement.style.display='none';">
            <div style="color:#777; font-size:11px; margin:8px 0 3px;">Cloud Mask (CLM)</div>
            <img src="${clmSrc}" alt="Западный тайл — CLM"
                 style="width:100%; border-radius:8px; display:block;"
                 onerror="this.parentElement.style.display='none';">
            <div style="color:#777; font-size:11px; margin-top:3px;">Пилотный тайл впритык к near-tier, западнее Одессы (~190-570км) — детектит ТОЛЬКО frontlike-системы для блока "Треки фронтов" выше, локальные очаги и синоптические системы здесь не считаются. Жёлтая дуга у правого края — кусочек окружности обзора near-tier (~192км от Одессы, она сама далеко за кадром справа); зелёная линия на CLM — контур берега.</div>
        </div>
    </details>`;
}

// Последний снимок Cloud Mask (CLM) — бинарная маска облако/ясно, ТО, ЧТО
// РЕАЛЬНО является входом детектора кандидатов/frontlike (см.
// eumetsat_cloud_forecast.py::_classify_cloud_mask/_significant_blobs) —
// в отличие от GC/ИК выше, которые лишь ПОДТВЕРЖДАЮЩИЕ каналы
// (area_fraction_now = CLM & (IR|GC)). Добавлено 2026-08-15 по прямому
// запросу пользователя: ночной трек не был виден ни на GC (ночью только
// огни городов), ни на ИК (низкий контраст тонкой облачности), хотя CLM
// его детектировал — этот снимок объясняет почему, без гадания по другим
// каналам. Timestamp берём из _eumetsatForecastData (тот же кадр, на
// котором считался is_cloud_now в питоне) — у CLM своего отдельного JSON
// с timestamp нет, снимок пишется сбоку в eumetsat_cloud_forecast.py.
function _renderClmSnapshot(forecastData){
    if(!forecastData || !forecastData.timestamp) return "";
    const ts = _obsTimeTag(forecastData.timestamp, 20);
    const src = `https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/eumetsat_clm_snapshot.png?v=${encodeURIComponent(forecastData.timestamp)}`;
    return `<div style="margin-top:10px;">
        <div style="color:#72c8ff; font-size:13px; font-weight:600; margin-bottom:4px;">🗺️ Cloud Mask (вход детектора) ${ts}</div>
        <img src="${src}" alt="Cloud Mask"
             style="width:100%; border-radius:8px; display:block;"
             onerror="this.parentElement.style.display='none';">
        <div style="color:#777; font-size:11px; margin-top:3px;">Белое — облако, тёмно-синее — ясно, серое — нет данных. Это ТО, ЧТО реально видит детектор кандидатов/фронтов — не GC/ИК (те лишь подтверждают)</div>
    </div>`;
}

// Все три снимка near-tier (GC/ИК/CLM) — В ОДНОМ АККОРДЕОНЕ, свёрнутом по
// умолчанию (запрос пользователя 2026-08-17: "сделай такой же аккордеон
// для одесского (центрального) пайла" — по образцу west-аккордеона,
// добавленного чуть раньше в этом же диалоге). Сами функции
// _renderGeocolourSnapshot/_renderIrSnapshot/_renderClmSnapshot НЕ
// менялись — просто их объединённый вывод завёрнут в <details> снаружи,
// вместо трёх отдельных всегда-развёрнутых <div> прямо в карточке.
function _renderNearSnapshotsAccordion(geocolourData, irData, forecastData, tracks){
    // Отдельная таблица ТОЛЬКО фронтов центрального (near) тайла — пара к
    // west-таблице в _renderWestSnapshot(), тот же запрос 2026-08-17.
    const tracksHtml = _renderFrontalTracksTable(tracks, {tileFilter: "near", title: "Треки фронтов (центральный тайл)"});
    const inner = tracksHtml
        + _renderGeocolourSnapshot(geocolourData)
        + _renderIrSnapshot(irData)
        + _renderClmSnapshot(forecastData);
    if(!inner) return "";
    const ts = _obsTimeTag((geocolourData && geocolourData.timestamp) || (forecastData && forecastData.timestamp), 20);
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">🛰️ Центральный тайл — снимки ${ts}</summary>
        <div style="margin-top:2px;">${inner}</div>
    </details>`;
}

// Таблица подтверждения фронтов по Open-Meteo (open_meteo_frontal_
// confirm.py) — согласовано с пользователем 2026-09-06. Кольцо+голоса на
// самих снимках (near-tier CLM и very_far GeoColour) рисует бэкенд, тут —
// детальная разбивка по каждой из 5 моделей (перепад temp/pressure,
// сдвиг ветра, голос за/против), чтобы видеть не только вердикт, но и
// на чём он основан.
function _renderFrontalConfirmTable(data){
    if(!data || !data.candidates || !Object.keys(data.candidates).length) return "";
    const cards = Object.entries(data.candidates).map(([tid, c]) => {
        const icon = c.confirmed ? "✅" : "⬜";
        const modelLines = Object.entries(c.per_model || {}).map(([mid, m]) => {
            if(m.reason === "incomplete_data"){
                return `<div style="color:#777;">· ${mid}: нет данных</div>`;
            }
            const mark = m.vote ? "✓" : "·";
            const color = m.vote ? "#6adc6a" : "#888";
            return `<div style="color:${color};">${mark} ${mid}: Δt=${m.temp_grad ?? "?"}°C, Δp=${m.pressure_grad ?? "?"}гПа, ветер=${m.wind_shift_deg ?? "?"}°</div>`;
        }).join("");
        return `<div style="margin:8px 0; padding:8px; border:1px solid #333; border-radius:8px;">
            <div style="font-weight:600;">${icon} Кандидат ${tid} — ${c.votes}/${c.n_models} моделей</div>
            <div style="font-size:12px; margin-top:4px; line-height:1.5;">${modelLines}</div>
        </div>`;
    }).join("");
    const ts = _obsTimeTag(data.generated_at, 60);
    return `<div style="margin-top:10px;">
        <div style="color:#72c8ff; font-size:13px; font-weight:600; margin-bottom:4px;">🗳️ Подтверждение фронтов по Open-Meteo ${ts}</div>
        ${cards}
        <div style="color:#777; font-size:11px; margin-top:3px;">Пороги подтверждения — первая прикидка, не откалибрована на реальных случаях, см. docs/topics/frontal_line_stations.md.</div>
    </div>`;
}

function _renderFarWatchLines(farData, veryFarData, confirmData){
    if(!farData && !veryFarData) return "";
    return _hr()
        + _subhead("Наблюдения по Европе")
        + _renderOneFarTier(farData, "Дальний контроль (~1000км)")
        + _renderOneFarTier(veryFarData, "Очень дальний контроль (~2500км)")
        + _renderFrontalConfirmTable(confirmData);
}

// Таблица "хронология" — последние N записей из .jsonl-лога, свежие сверху.
// Общая функция для осадков и грозы (title/emoji параметризованы) — именно
// эти данные (время/расстояние/ETA/вердикт) достаточны, чтобы восстановить,
// как менялся прогноз, не лезя в git-историю коммитов (см. кейс 2026-08-09).
function _renderHistoryTable(rows, emoji, title){
    if(!rows || !rows.length) return "";
    const last = rows.slice(-16).reverse();
    const trs = last.map(r => {
        const t = _fmtObsTime(r.timestamp) || "—";
        const dist = r.distance_km_now != null ? r.distance_km_now : "—";
        const dir = r.compass || "—";
        const eta = r.eta_min != null ? r.eta_min : "—";
        const verdict = r.verdict || "—";
        return `<tr>
            <td style="padding:3px 10px 3px 0; color:#999; white-space:nowrap;">${t}</td>
            <td style="padding:3px 10px; color:#bbb; text-align:right;">${dist}</td>
            <td style="padding:3px 10px; color:#bbb;">${dir}</td>
            <td style="padding:3px 10px; color:#bbb; text-align:right;">${eta}</td>
            <td style="padding:3px 0; color:#ccc;">${verdict}</td>
        </tr>`;
    }).join("");
    return `<details style="margin-top:10px;">
        <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">${emoji} ${title} (последние ${last.length})</summary>
        <div style="overflow-x:auto; margin-top:6px;">
        <table style="width:100%; border-collapse:collapse; font-size:12.5px;">
            <thead><tr style="color:#777; text-align:left;">
                <th style="padding:3px 10px 3px 0; font-weight:600;">Время</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">Км</th>
                <th style="padding:3px 10px; font-weight:600;">Напр.</th>
                <th style="padding:3px 10px; font-weight:600; text-align:right;">ETA</th>
                <th style="padding:3px 0; font-weight:600;">Вердикт</th>
            </tr></thead>
            <tbody>${trs}</tbody>
        </table>
        </div>
    </details>`;
}

function renderNearbyPrecipCard(){
    const card = document.getElementById("nearbyPrecipCard");
    if(!card) return;

    const anyData = _eumetsatForecastData || _eumetsatPrecipForecastData
        || _eumetsatLightningForecastData || _eumetsatIrMotionData || _eumetsatPrecipMotionData
        || _eumetsatCloudPhaseTypeData || _eumetsatGeocolourMotionData
        || _eumetsatFarWatchData || _eumetsatVeryFarWatchData || _eumetsatTargetSummaryData;
    if(!anyData){ card.innerHTML = ""; return; }

    // Единый блок наверху ("Итог" из target_summary + хронология) — это
    // единственное, что нужно прочитать в спешке. Разбивка по каналам
    // (8 модулей) свёрнута под спойлер: раньше это были отдельные блоки
    // подряд на странице, из-за чего в моменте легко перепутать, какое
    // именно число/вердикт читаешь (см. docs/topics/eumetsat.md,
    // обсуждение 2026-08-09, кейс шквала на пляже).
    const channelDetails = `
        ${_renderAreaSummary(_eumetsatGeocolourMotionData, _eumetsatFarWatchData, _eumetsatVeryFarWatchData)}
        ${_renderCloudForecastLines(_eumetsatForecastData)}
        ${_renderCloudPhaseTypeLines(_eumetsatCloudPhaseTypeData)}
        ${_renderIrMotionLines(_eumetsatIrMotionData)}
        ${_renderGeocolourMotionLines(_eumetsatGeocolourMotionData)}
        ${_renderPrecipForecastLines(_eumetsatPrecipForecastData)}
        ${_renderPrecipMotionLines(_eumetsatPrecipMotionData)}
        ${_renderLightningForecastLines(_eumetsatLightningForecastData)}
        ${_renderFarWatchLines(_eumetsatFarWatchData, _eumetsatVeryFarWatchData, _openMeteoFrontalConfirmData)}
    `;

    card.innerHTML = `
        <div class="cardTitle">Анализ спутниковых снимков (EUMETSAT)</div>
        <div class="small muted">Точка наблюдения: станция "${STATION_LABEL}"</div>
        ${_renderTargetSummaryLines(_eumetsatTargetSummaryData)}
        ${_renderLocalCandidatesTable(_eumetsatTargetSummaryData && _eumetsatTargetSummaryData.local_candidates, _eumetsatTargetSummaryData && _eumetsatTargetSummaryData.local_suppressed_count)}
        ${_renderSystemCandidatesTable(_eumetsatTargetSummaryData && _eumetsatTargetSummaryData.system_candidates, _eumetsatTargetSummaryData && _eumetsatTargetSummaryData.system_suppressed_count)}
        ${_renderSystemsSnapshot(_eumetsatTargetSummaryData)}
        ${_renderWestSnapshot(_eumetsatWestWatchData, _eumetsatTargetSummaryData && _eumetsatTargetSummaryData.frontal_tracks)}
        ${_renderNearSnapshotsAccordion(_eumetsatGeocolourMotionData, _eumetsatIrMotionData, _eumetsatForecastData, _eumetsatTargetSummaryData && _eumetsatTargetSummaryData.frontal_tracks)}
        ${_renderHistoryTable(_eumetsatPrecipHistoryData, "📜", "Хронология осадков")}
        ${_renderHistoryTable(_eumetsatLightningHistoryData, "⛈️", "Хронология грозы")}
        <details style="margin-top:10px;">
            <summary style="cursor:pointer; color:#72c8ff; font-size:13px; font-weight:600;">🔧 Подробности по каналам</summary>
            <div style="margin-top:6px;">${channelDetails}</div>
        </details>
        ${_hr()}
        <div class="small muted">
            Data: <a href="https://www.eumetsat.int/" target="_blank" rel="noopener" style="color:#72c8ff;">EUMETSAT</a>
        </div>`;
}

