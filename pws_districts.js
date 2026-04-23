/* =========================================================
   PWS_DISTRICTS.JS — несколько PWS станций по районам
   Зависит от: utils.js, indicators.js
   
   Коррекция давления:
   - Ручная: pressureOffset на каждую станцию (±гПа)
   - Авто: сравнение с SYNOP в часы наблюдений (00,06,12,18 UTC)
            сохраняется в localStorage, можно отключить на каждой станции
========================================================= */

/* =========================================================
   1. КОНФИГУРАЦИЯ СТАНЦИЙ
   Замени Station ID на реальные.
   neighbourhood — твоё название района
   pressureOffset — ручная поправка давления в гПа (0 = без поправки)
   autoCalib — true/false: участвует ли в автокалибровке по SYNOP
========================================================= */
const PWS_STATIONS = [
    {
        id:            "IODESA138",
        neighbourhood: "Центр",
        pressureOffset: 0,
        autoCalib:     true
    },
    {
        id:            "IODESS16",
        neighbourhood: "Таирова",
        pressureOffset: 0,
        autoCalib:     true
    },
    {
        id:            "IODESS44",
        neighbourhood: "Аркадия",
        pressureOffset: 0,
        autoCalib:     true
    },
    {
        id:            "IODESS37",
        neighbourhood: "Застава",
        pressureOffset: 0,
        autoCalib:     true
    },
    {
        id:            "IODESA137",
        neighbourhood: "пос. Котовского",
        pressureOffset: 0,
        autoCalib:     true
    },
];

// Интервал автообновления (секунды)
const PWS_D_REFRESH_SEC = 15;

// Часы SYNOP наблюдений в UTC
const SYNOP_HOURS_UTC = [0, 6, 12, 18];

// Допустимое окно сравнения с SYNOP (±минут от часа наблюдения)
const SYNOP_CALIB_WINDOW_MIN = 20;

/* =========================================================
   2. КАЛИБРОВКА ДАВЛЕНИЯ
========================================================= */
const CALIB_STORE_KEY = "pwsCalibOffsets"; // localStorage ключ

function loadCalibOffsets(){
    try { return JSON.parse(localStorage.getItem(CALIB_STORE_KEY) || "{}"); }
    catch(e){ return {}; }
}

function saveCalibOffset(stationId, offset){
    const offsets = loadCalibOffsets();
    offsets[stationId] = { offset: +offset.toFixed(2), ts: Date.now() };
    localStorage.setItem(CALIB_STORE_KEY, JSON.stringify(offsets));
}

function getCalibOffset(stationId){
    const offsets = loadCalibOffsets();
    return offsets[stationId]?.offset ?? 0;
}

// Проверяем — сейчас время SYNOP наблюдения?
function isNearSynopHour(){
    const now     = new Date();
    const utcH    = now.getUTCHours();
    const utcM    = now.getUTCMinutes();
    const totalM  = utcH * 60 + utcM;
    return SYNOP_HOURS_UTC.some(h => {
        const diff = Math.abs(totalM - h * 60);
        return diff <= SYNOP_CALIB_WINDOW_MIN;
    });
}

// Вызывается из synop.js после загрузки SYNOP
// synopPressure — давление QNH из телеграммы (гПа)
function calibratePWSBySynop(synopPressure){
    if(synopPressure == null) return;
    if(!isNearSynopHour()){
        console.log("PWS calib: не время SYNOP наблюдения, пропускаем");
        return;
    }

    const results = loadCalibOffsets();

    PWS_STATIONS.forEach(st => {
        if(!st.autoCalib) return;

        // Берём последнее загруженное давление этой станции
        const raw = _pwsLastRaw[st.id];
        if(raw == null) return;

        const station = PWS_STATIONS.find(s => s.id === st.id);
        const manualOffset = station?.pressureOffset ?? 0;
        const rawPressure  = raw + manualOffset;
        const diff         = synopPressure - rawPressure;

        // Ограничиваем поправку разумными пределами (±15 гПа)
        if(Math.abs(diff) > 15){
            console.warn(`PWS calib ${st.id}: разница ${diff.toFixed(1)} гПа слишком большая, пропускаем`);
            return;
        }

        saveCalibOffset(st.id, diff);
        console.log(`PWS calib ${st.id}: поправка = ${diff > 0 ? "+" : ""}${diff.toFixed(2)} гПа`);
    });

    // Перерисовываем карточки с новыми поправками
    if(Object.keys(_pwsLastData).length > 0){
        renderPWSDistricts(_pwsLastData);
    }
}

/* =========================================================
   3. СОСТОЯНИЕ
========================================================= */
let _pwsDTimer   = null;
let _pwsLastRaw  = {};  // { stationId: rawPressure }
let _pwsLastData = {};  // { stationId: parsedData }
let _pwsDKeyIdx  = 0;

/* =========================================================
   4. ЗАГРУЗКА ОДНОЙ СТАНЦИИ
========================================================= */
async function loadOnePWS(stationId){
    const key = WU_KEYS[_pwsDKeyIdx % WU_KEYS.length];
    const url  =
        `https://api.weather.com/v2/pws/observations/current` +
        `?stationId=${encodeURIComponent(stationId)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${key}`;

    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
        const r = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
        if(!r.ok){
            if(r.status === 401 || r.status === 403) _pwsDKeyIdx++;
            throw new Error("HTTP " + r.status);
        }
        const data = await r.json();
        if(data?.errors?.length)
            throw new Error(data.errors[0]?.error?.message || "API error");
        if(!data?.observations?.length)
            throw new Error("Нет данных");
        return parsePWSOne(data, stationId);
    } finally {
        clearTimeout(timer);
    }
}

/* =========================================================
   5. ЗАГРУЗКА ВСЕХ СТАНЦИЙ
========================================================= */
async function loadAllPWSDistricts(){
    const results = await Promise.allSettled(
        PWS_STATIONS.map(st =>
            loadOnePWS(st.id).then(data => ({ ...data, _configId: st.id }))
        )
    );

    const out = {};
    results.forEach((r, i) => {
        const id = PWS_STATIONS[i].id;
        if(r.status === "fulfilled"){
            out[id] = r.value;
            // Сохраняем сырое давление для автокалибровки
            if(r.value.pressure != null) _pwsLastRaw[id] = r.value.pressure;
        } else {
            out[id] = { error: r.reason?.message || "Ошибка" };
        }
    });

    _pwsLastData = out;
    return out;
}

/* =========================================================
   6. ПАРСИНГ
========================================================= */
function parsePWSOne(data, stationId){
    const obs = data.observations[0];
    const m   = obs.metric || {};
    const kmhToMs = v => v != null ? Math.round(v / 3.6 * 10) / 10 : null;

    return {
        stationID:    stationId,
        obsTimeLocal: obs.obsTimeLocal || null,
        epoch:        obs.epoch        ?? null,
        temp:         m.temp           ?? null,
        dewpt:        m.dewpt          ?? null,
        heatIndex:    m.heatIndex      ?? null,
        windChill:    m.windChill      ?? null,
        pressure:     m.pressure       ?? null,  // сырое, без поправки
        precipRate:   m.precipRate     ?? null,
        precipTotal:  m.precipTotal    ?? null,
        elev:         m.elev           ?? null,
        windDir:      obs.winddir      ?? null,
        humidity:     obs.humidity     ?? null,
        uv:           obs.uv           ?? null,
        solarRad:     obs.solarRadiation ?? null,
        windSpeedMs:  kmhToMs(m.windSpeed),
        windGustMs:   kmhToMs(m.windGust),
    };
}

/* =========================================================
   7. ПОЛУЧИТЬ СКОРРЕКТИРОВАННОЕ ДАВЛЕНИЕ
========================================================= */
function correctedPressure(stationId, rawPressure){
    if(rawPressure == null) return null;
    const cfg          = PWS_STATIONS.find(s => s.id === stationId);
    const manualOffset = cfg?.pressureOffset ?? 0;
    const autoOffset   = cfg?.autoCalib ? getCalibOffset(stationId) : 0;
    const result       = rawPressure + manualOffset + autoOffset;
    return Math.round(result * 10) / 10;
}

/* =========================================================
   8. РЕНДЕР КАРТОЧЕК
========================================================= */
function renderPWSDistricts(allData){
    const box = document.getElementById("pwsDistricts");
    if(!box) return;

    let html = `<div class="cardTitle">PWS — погода по районам</div>`;

    // Время последнего обновления
    const now = new Date().toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
    html += `<div class="subTitle" style="margin-bottom:10px;">Обновлено: ${now}</div>`;

    html += `<div class="districtGrid">`;

    PWS_STATIONS.forEach(cfg => {
        const p = allData[cfg.id];

        // Карточка с ошибкой
        if(!p || p.error){
            html += `
            <div class="districtCard">
                <div class="districtTop">
                    <div class="districtName">${escapeHtml(cfg.neighbourhood)}</div>
                    <div class="small" style="color:#888;">${escapeHtml(cfg.id)}</div>
                </div>
                <div class="small" style="color:#ff8f43;margin-top:6px;">
                    ${escapeHtml(p?.error || "Нет данных")}
                </div>
            </div>`;
            return;
        }

        const tc        = tempClass(p.temp);
        const pCorrected = correctedPressure(cfg.id, p.pressure);
        const autoOff   = cfg.autoCalib ? getCalibOffset(cfg.id) : 0;
        const manOff    = cfg.pressureOffset;
        const hasCorr   = (Math.abs(autoOff) > 0.01 || Math.abs(manOff) > 0.01);

        const feelsLike =
            p.temp != null && p.temp >= 27 && p.heatIndex != null ? p.heatIndex :
            p.temp != null && p.temp <= 10 && p.windChill != null ? p.windChill :
            p.temp;

        const timeStr = p.obsTimeLocal
            ? (() => {
                const d = new Date(p.obsTimeLocal.replace(" ","T"));
                return isNaN(d) ? p.obsTimeLocal
                    : d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});
            })()
            : "-";

        html += `
        <div class="districtCard">
            <div class="districtTop">
                <div>
                    <div class="districtName">${escapeHtml(cfg.neighbourhood)}</div>
                    <div class="small">${escapeHtml(cfg.id)} · ${escapeHtml(timeStr)}</div>
                </div>
                <div class="districtTemp ${tc}">${fmt1(p.temp,"°C")}</div>
            </div>

            ${feelsLike != null && Math.abs(feelsLike - p.temp) >= 0.5 ? `
            <div class="districtLine">
                <span>Ощущается как</span>
                <span>${fmt1(feelsLike,"°C")}</span>
            </div>` : ""}

            <div class="districtLine">
                <span>Влажность</span>
                <span>${fmt0(p.humidity," %")}</span>
            </div>

            <div class="districtLine">
                <span>Точка росы</span>
                <span>${fmt1(p.dewpt,"°C")}</span>
            </div>

            <div class="districtLine">
                <span>Ветер</span>
                <span>${fmt1(p.windSpeedMs," м/с")} ${escapeHtml(degToText(p.windDir))} ${windArrow(p.windDir)}</span>
            </div>

            ${p.windGustMs != null && p.windGustMs > 0 ? `
            <div class="districtLine">
                <span>Порывы</span>
                <span>${fmt1(p.windGustMs," м/с")}</span>
            </div>` : ""}

            <div class="districtLine">
                <span>Давление${hasCorr ? " *" : ""}</span>
                <span>${fmt1(pCorrected," гПа")}</span>
            </div>

            ${p.precipRate != null && p.precipRate > 0 ? `
            <div class="districtLine">
                <span>Интенсивность</span>
                <span>${fmt1(p.precipRate," мм/ч")}</span>
            </div>` : ""}

            ${p.precipTotal != null && p.precipTotal > 0 ? `
            <div class="districtLine">
                <span>Осадки</span>
                <span>${fmt1(p.precipTotal," мм")}</span>
            </div>` : ""}

            ${p.solarRad != null ? `
            <div class="districtLine">
                <span>Радиация</span>
                <span>${fmt0(p.solarRad," Вт/м²")}</span>
            </div>` : ""}

            ${hasCorr ? `
            <div class="small" style="margin-top:4px;color:#888;">
                * поправка: ${manOff !== 0 ? `ручная ${manOff > 0 ? "+" : ""}${manOff}` : ""}
                ${autoOff !== 0 ? `авто ${autoOff > 0 ? "+" : ""}${autoOff.toFixed(2)}` : ""}
            </div>` : ""}
        </div>`;
    });

    html += `</div>`;

    // Кнопка сброса автокалибровки
    html += `
    <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <button onclick="resetPWSCalib()" style="width:auto;padding:6px 14px;font-size:12px;background:#2a2a2a;">
            Сбросить автокалибровку
        </button>
        <div class="small" style="color:#888;">
            Следующая калибровка: ${nextSynopHourStr()}
        </div>
    </div>`;

    box.innerHTML = html;
}

/* =========================================================
   9. ВСПОМОГАТЕЛЬНЫЕ
========================================================= */
function nextSynopHourStr(){
    const now   = new Date();
    const utcH  = now.getUTCHours();
    const utcM  = now.getUTCMinutes();
    const next  = SYNOP_HOURS_UTC.find(h => h * 60 > utcH * 60 + utcM)
                  ?? (SYNOP_HOURS_UTC[0] + 24);
    const diffM = next * 60 - (utcH * 60 + utcM);
    const hh    = Math.floor(diffM / 60);
    const mm    = diffM % 60;
    return hh > 0 ? `через ${hh} ч ${mm} мин` : `через ${mm} мин`;
}

function resetPWSCalib(){
    localStorage.removeItem(CALIB_STORE_KEY);
    if(Object.keys(_pwsLastData).length > 0) renderPWSDistricts(_pwsLastData);
    console.log("PWS: автокалибровка сброшена");
}

function windArrow(deg){
    if(deg == null || Number.isNaN(deg)) return "";
    return `<span style="display:inline-block;transform:rotate(${deg}deg)">↑</span>`;
}

/* =========================================================
   10. UI-ОБЁРТКА
========================================================= */
async function loadPWSDistrictsUI(){
    const btn = document.getElementById("btnPWSDistricts");
    if(btn) btn.disabled = true;

    clearLog("pwsDistrictsLog");
    showLogBox("pwsDistrictsLogBox");

    try {
        logTo("pwsDistrictsLog", `🚀 Загрузка ${PWS_STATIONS.length} PWS станций`);
        const data = await loadAllPWSDistricts();
        const ok   = Object.values(data).filter(d => !d.error).length;
        logTo("pwsDistrictsLog", `📥 Получено: ${ok}/${PWS_STATIONS.length}`);
        renderPWSDistricts(data);
        logTo("pwsDistrictsLog", "✅ Готово");
        hideLogBoxLater("pwsDistrictsLogBox", 2500);

        startPWSDistrictsAutoRefresh();
    } catch(e){
        logTo("pwsDistrictsLog", "❌ " + (e?.message || e));
    } finally {
        if(btn) btn.disabled = false;
    }
}

/* =========================================================
   11. АВТООБНОВЛЕНИЕ
========================================================= */
function startPWSDistrictsAutoRefresh(){
    if(_pwsDTimer) clearInterval(_pwsDTimer);
    _pwsDTimer = setInterval(async () => {
        try {
            const data = await loadAllPWSDistricts();
            renderPWSDistricts(data);
        } catch(e){
            console.warn("PWS districts auto-refresh:", e?.message);
        }
    }, PWS_D_REFRESH_SEC * 1000);
}

function stopPWSDistrictsAutoRefresh(){
    if(_pwsDTimer){ clearInterval(_pwsDTimer); _pwsDTimer = null; }
}
