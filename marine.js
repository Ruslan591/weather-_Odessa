/* =========================================================
   MARINE.JS — общий морской модуль
   Используется на pws.html (встроенный блок) и marine.html
   (отдельная страница с историей и точностью).
   Зависит от: ничего (самодостаточный), опционально echarts
   для renderMarineHistChart().
========================================================= */

const MARINE_PARAMS = {
    sst:          { label:"Температура воды",  unit:"°C",  color:"#ffd166" },
    waveH:        { label:"Высота волны",      unit:"м",   color:"#74b9ff" },
    windWaveH:    { label:"Ветровая волна",    unit:"м",   color:"#81ecec" },
    swellH:       { label:"Зыбь",              unit:"м",   color:"#a29bfe" },
    seaWindSpeed: { label:"Ветер над морем",   unit:"м/с", color:"#55efc4" },
    seaPressure:  { label:"Давление (море)",   unit:"гПа", color:"#fab1a0" },
    seaLevel:     { label:"Уровень моря",      unit:"м",   color:"#00cec9" },
    currentV:     { label:"Течение",           unit:"м/с", color:"#ff7675" },
};

let _marineData  = null;
let _marineFetchedAt = 0;
let _marineHistLast    = null;
let _marineHistFetchedAt = 0;
let _marineHistArr     = null;
let _marineChartPeriod = "24h";
let _marineChartParam  = "sst";
let _hmcbasSeaTemp    = null;
let _hmcbasFetchedAt  = 0;
let _hmcbasTelegram   = null;
let _hmcbasTelegramArr = null;
let _hmcbasTgFetchedAt = 0;
let _tiktokSeaTemp    = [];
let _tiktokFetchedAt  = 0;

/* =========================================================
   МОРСКОЙ API (open-meteo marine + ветер над морем)
========================================================= */
async function loadMarine(){
    if(Date.now() - _marineFetchedAt < 15 * 60000) return;
    _marineFetchedAt = Date.now();
    const marineUrl =
        "https://marine-api.open-meteo.com/v1/marine" +
        "?latitude=46.35&longitude=30.90" +
        "&current=wave_height,wave_direction,wave_period,wave_peak_period" +
",wind_wave_height,wind_wave_direction" +
",swell_wave_height,swell_wave_period,swell_wave_direction" +
",sea_surface_temperature" +
",ocean_current_velocity,ocean_current_direction" +
"&hourly=sea_level_height_msl&timezone=auto&forecast_days=1";
    const windUrl =
        "https://api.open-meteo.com/v1/forecast" +
        "?latitude=46.35&longitude=30.90" +
        "&current=wind_speed_10m,wind_gusts_10m,wind_direction_10m,surface_pressure" +
        "&wind_speed_unit=ms&timezone=auto";
    try {
        const [mr, wr] = await Promise.all([
            fetch(marineUrl, { cache:"no-store" }),
            fetch(windUrl,   { cache:"no-store" }),
        ]);
        const marineJson = mr.ok ? await mr.json() : {};
        const c = marineJson.current || {};
        let seaLevelCm = null;
        try {
            const htimes = marineJson.hourly?.time || [];
            const hvals  = marineJson.hourly?.sea_level_height_msl || [];
            if(htimes.length && hvals.length){
                const now = Date.now();
                let bestI = 0, bestDiff = Infinity;
                for(let i=0; i<htimes.length; i++){
                    const diff = Math.abs(new Date(htimes[i]).getTime() - now);
                    if(diff < bestDiff){ bestDiff = diff; bestI = i; }
                }
                const mean = hvals.reduce((a,b)=>a+b,0) / hvals.length;
                seaLevelCm = Math.round((hvals[bestI] - mean) * 100);
            }
        } catch(e){}
        _marineData = {
            sst:        c.sea_surface_temperature    ?? null,
            seaLevel:   seaLevelCm,
            waveH:      c.wave_height                ?? null,
            waveDir:    c.wave_direction             ?? null,
            wavePer:    c.wave_period                ?? null,
            wavePeakPer:c.wave_peak_period           ?? null,
            windWaveH:  c.wind_wave_height           ?? null,
            windWaveDir:c.wind_wave_direction        ?? null,
            swellH:     c.swell_wave_height          ?? null,
            swellPer:   c.swell_wave_period          ?? null,
            swellDir:   c.swell_wave_direction       ?? null,
            currentV:   c.ocean_current_velocity     ?? null,
            currentDir: c.ocean_current_direction    ?? null,
            time:       c.time                       ?? null,
        };
        if(wr.ok){
            const wc = ((await wr.json()).current || {});
            _marineData.seaWindSpeed = wc.wind_speed_10m     ?? null;
            _marineData.seaWindGust  = wc.wind_gusts_10m     ?? null;
            _marineData.seaWindDir   = wc.wind_direction_10m ?? null;
            _marineData.seaPressure  = wc.surface_pressure   ?? null;
        }
    } catch(e){
        console.warn("Marine API:", e.message);
        _marineFetchedAt = 0;
    }
}

async function loadMarineHistory(){
    if(Date.now() - _marineHistFetchedAt < 30 * 60000) return; // раз в 30 мин
    _marineHistFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/marine_history.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const arr = await r.json();
        if(Array.isArray(arr) && arr.length){
            _marineHistLast = arr[arr.length - 1];
            _marineHistArr  = arr.slice(-20000);
            renderMarineHistChart();
        }
    } catch(e){
        _marineHistFetchedAt = 0;
    }
}

async function loadHmcbasSeaTemp(){
    // Реальная (не прогнозная) температура воды с виджета ГМЦ ЧАМ —
    // независимый референс для сверки с моделью CMEMS.
    if(Date.now() - _hmcbasFetchedAt < 20 * 60000) return; // раз в 20 мин
    _hmcbasFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/hmcbas_sea_temp_realtime.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const j = await r.json();
        if(j && j.sea_temp != null) _hmcbasSeaTemp = j;
    } catch(e){
        _hmcbasFetchedAt = 0;
    }
}

async function loadHmcbasTelegram(){
    // Утренний факт из t.me/HMC_Odesa — самый надёжный референс (раз в сутки),
    // накапливается в hmcbas_telegram_sea_temp.json, берём последнюю запись,
    // а весь массив храним для расчёта точности модели.
    if(Date.now() - _hmcbasTgFetchedAt < 30 * 60000) return; // раз в 30 мин
    _hmcbasTgFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/hmcbas_telegram_sea_temp.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const arr = await r.json();
        if(Array.isArray(arr) && arr.length){
            _hmcbasTelegramArr = arr;
            _hmcbasTelegram    = arr[arr.length - 1];
        }
    } catch(e){
        _hmcbasTgFetchedAt = 0;
    }
}

async function loadTiktokSeaTemp(){
    // Речевой факт из TikTok-роликов (неск. каналов), накапливается в
    // tiktok_sea_temp.json; на странице показываем последнюю запись по
    // каждому каналу, а весь массив храним для расчёта точности модели.
    if(Date.now() - _tiktokFetchedAt < 30 * 60000) return; // раз в 30 мин
    _tiktokFetchedAt = Date.now();
    try {
        const r = await fetch(
            "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/tiktok_sea_temp.json",
            { cache: "no-store" }
        );
        if(!r.ok) return;
        const arr = await r.json();
        if(Array.isArray(arr)) _tiktokSeaTemp = arr;
    } catch(e){
        _tiktokFetchedAt = 0;
    }
}

/* =========================================================
   ГРАФИК ИСТОРИИ
========================================================= */
function getMarineFilteredData(){
    if(!_marineHistArr || !_marineHistArr.length) return [];
    const now = Date.now();
    const period = _marineChartPeriod;
    let fromTs, toTs = now;
    if(period === "today"){
        const d = new Date(); d.setHours(0,0,0,0);
        fromTs = d.getTime();
    } else if(period === "yesterday"){
        const d = new Date(); d.setHours(0,0,0,0);
        toTs   = d.getTime();
        fromTs = toTs - 24*3600*1000;
    } else if(period.startsWith("n")){
        const days = parseInt(period.slice(1)) || 7;
        fromTs = now - days*24*3600*1000;
    } else { // "24h" и запасной вариант
        fromTs = now - 24*3600*1000;
    }
    return _marineHistArr.filter(o => {
        const t = Date.parse(o.time);
        return !isNaN(t) && t >= fromTs && t <= toTs;
    });
}

function setMarinePeriod(period){
    _marineChartPeriod = period;
    renderMarineHistChart();
}

function applyMarineCustomDays(){
    const inp = document.getElementById("marineDaysInput");
    let n = parseInt(inp && inp.value);
    if(isNaN(n) || n < 1) n = 1;
    if(n > 90) n = 90;
    if(inp) inp.value = n;
    _marineChartPeriod = "n" + n;
    renderMarineHistChart();
}

function setMarineParam(key){
    if(!MARINE_PARAMS[key]) return;
    _marineChartParam = key;
    renderMarineHistChart();
}

function renderMarineHistChart(){
    const card = document.getElementById("sstChartCard");
    if(!card) return;
    if(!_marineHistArr || _marineHistArr.length < 2){ card.innerHTML = ""; return; }
    if(typeof echarts === "undefined") return;

    // сохраняем позицию горизонтальной прокрутки строки параметров,
    // иначе клик по кнопке за пределами видимой области сбрасывает её в начало
    const prevParamRow = document.getElementById("marineParamRow");
    const prevScrollLeft = prevParamRow ? prevParamRow.scrollLeft : null;

    const cfg = MARINE_PARAMS[_marineChartParam] || MARINE_PARAMS.sst;

    const periods = [
        { id:"24h",       label:"24 часа" },
        { id:"today",     label:"Сегодня" },
        { id:"yesterday", label:"Вчера"   },
    ];
    const btnStyle = active =>
        `width:auto;padding:4px 10px;font-size:11px;border-radius:6px;cursor:pointer;` +
        `border:1px solid ${active ? "#72c8ff" : "#333"};` +
        `background:${active ? "#1c3a4d" : "#252525"};` +
        `color:${active ? "#72c8ff" : "#ccc"};`;

    const isCustom   = _marineChartPeriod.startsWith("n");
    const customDays = isCustom ? (parseInt(_marineChartPeriod.slice(1)) || 7) : 7;

    const periodButtonsHtml = periods.map(p =>
        `<button onclick="setMarinePeriod('${p.id}')" style="${btnStyle(_marineChartPeriod===p.id)}">${p.label}</button>`
    ).join("") + `
        <span style="font-size:11px;color:#555;margin-left:2px;">·</span>
        <input id="marineDaysInput" type="number" min="1" max="90" value="${customDays}"
               onchange="applyMarineCustomDays()"
               style="width:48px;background:#232323;
                      border:1px solid ${isCustom ? "#72c8ff" : "#333"};border-radius:6px;
                      color:${isCustom ? "#72c8ff" : "#eee"};font-size:11px;padding:4px 6px;text-align:center;">
        <span style="font-size:11px;color:${isCustom ? "#72c8ff" : "#888"};">дней</span>`;

    const paramBtnStyle = active =>
        `width:auto;flex:0 0 auto;padding:5px 12px;font-size:12px;border-radius:16px;cursor:pointer;` +
        `border:1px solid ${active ? "#72c8ff" : "#333"};` +
        `background:${active ? "#1c3a4d" : "#252525"};` +
        `color:${active ? "#72c8ff" : "#ccc"};white-space:nowrap;`;

    const paramSelectHtml = `
        <div id="marineParamRow" style="display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;
                    padding:2px 0 8px;margin:4px 0 4px;scrollbar-width:none;">
            ${Object.keys(MARINE_PARAMS).map(k =>
                `<button onclick="setMarineParam('${k}')" style="${paramBtnStyle(k===_marineChartParam)}">${MARINE_PARAMS[k].label}</button>`
            ).join("")}
        </div>`;

    card.innerHTML = `
        <div class="cardTitle">История моря — график</div>
        ${paramSelectHtml}
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin:0 0 4px;align-items:center;">${periodButtonsHtml}</div>
        <div id="sstHistChart" style="height:180px;margin-top:6px;"></div>`;

    const div = document.getElementById("sstHistChart");
    if(!div) return;

    const paramRow = document.getElementById("marineParamRow");
    if(paramRow && prevScrollLeft != null) paramRow.scrollLeft = prevScrollLeft;

    const filtered = getMarineFilteredData();
    if(filtered.length < 2){
        div.innerHTML = `<div style="color:#666;text-align:center;padding:30px;font-size:12px;">Нет данных за выбранный период</div>`;
        return;
    }

    const chart = echarts.init(div, null, { backgroundColor: "transparent" });

    const seriesData = filtered
        .map(o => {
            const v = o[_marineChartParam];
            const t = Date.parse(o.time);
            return (typeof v === "number" && !isNaN(t)) ? [t, v] : null;
        })
        .filter(Boolean);

    chart.setOption({
        backgroundColor: "transparent",
        animation: false,
        grid: { top: 22, right: 12, bottom: 30, left: 40, containLabel: false },
        tooltip: {
            trigger: "axis",
            backgroundColor: "rgba(20,20,20,0.97)",
            borderColor: "#333",
            borderWidth: 1,
            textStyle: { color: "#eee", fontSize: 12 },
            formatter(params){
                const d = new Date(params[0].value[0]);
                const timeStr = d.toLocaleString("ru-RU", {
                    day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit"
                });
                const lines = params.map(p =>
                    `<div style="font-size:12px;color:${p.color};">${cfg.label}: ${p.value[1].toFixed(1)} ${cfg.unit}</div>`
                ).join("");
                return `<div style="font-size:11px;color:#888;margin-bottom:4px;">${timeStr}</div>${lines}`;
            },
        },
        xAxis: {
            type: "time",
            axisLine:  { lineStyle: { color: "#333" } },
            axisTick:  { lineStyle: { color: "#333" } },
            axisLabel: {
                color: "#555", fontSize: 10,
                formatter: val => new Date(val).toLocaleDateString("ru-RU", {day:"2-digit", month:"2-digit"}),
            },
            splitLine: { lineStyle: { color: "#252525" } },
        },
        yAxis: {
            type: "value",
            scale: true,
            axisLine:  { show: false },
            axisTick:  { show: false },
            axisLabel: { color: "#555", fontSize: 10, formatter: v => v + " " + cfg.unit },
            splitLine: { lineStyle: { color: "#252525" } },
        },
        series: [
            {
                name: cfg.label,
                type: "line",
                data: seriesData,
                smooth: 0.4,
                symbol: "none",
                lineStyle: { color: cfg.color, width: 2 },
                itemStyle: { color: cfg.color },
                connectNulls: true,
                z: 2,
            },
        ],
    });
}

/* =========================================================
   ТЕКУЩИЕ ФАКТЫ (карточка "Море · Чёрное море")
========================================================= */
/* =========================================================
   ОБЩИЕ ФОРМАТТЕРЫ (используются и в тексте, и в индикаторах)
========================================================= */
const MARINE_DIR_NAMES = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ",
                           "Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];
function marineDirText(deg){
    if(deg == null) return "—";
    return MARINE_DIR_NAMES[Math.round(deg/22.5)%16] + " " + Math.round(deg) + "°";
}
function marineHeightParts(v){
    if(v == null) return { value:"—", unit:"" };
    return v < 1
        ? { value: String(Math.round(v * 100)), unit:"см" }
        : { value: v.toFixed(1),                unit:"м" };
}
function marineSeaStateLabel(h){
    if(h == null) return null;
    if(h < 0.10) return { label:"Штиль (0 баллов)",         color:"#55efc4" };
    if(h < 0.50) return { label:"Рябь (1 балл)",            color:"#00cec9" };
    if(h < 1.25) return { label:"Лёгкое волнение (2)",      color:"#74b9ff" };
    if(h < 2.50) return { label:"Умеренное волнение (3–4)", color:"#ffd166" };
    if(h < 4.00) return { label:"Значительное (5)",         color:"#ff9f5c" };
    if(h < 6.00) return { label:"Сильное (6–7)",            color:"#ff6b6b" };
    return              { label:"Очень сильное (8–9)",       color:"#d63031" };
}

/* =========================================================
   ИНДИКАТОР: ТЕМПЕРАТУРА ВОДЫ (дуга, 0..30°C)
========================================================= */
function seaTempIndicatorSvg(sst){
    const tMin = 0, tMax = 30, tMid = 15;
    const tC    = sst != null ? Math.max(tMin, Math.min(tMax, sst)) : null;
    const angle = tC != null ? (tC - tMid) / tMid * 90 : 0;

    const T_STOPS = [
        {offset:0,    color:"#3a8fff"},
        {offset:0.33, color:"#72c8ff"},
        {offset:0.5,  color:"#5fe08f"},
        {offset:0.75, color:"#ffd166"},
        {offset:1,    color:"#ff9f5c"},
    ];
    const tT = tC != null ? (tC - tMin) / (tMax - tMin) : null;
    const vc = tT != null ? gradientColor(T_STOPS, tT) : "#aaa";

    return `
    <div class="ind-card">
        <div class="ind-title">Температура воды</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Температура воды" style="overflow:visible;">
            <defs>
                <linearGradient id="stArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#3a8fff"/>
                    <stop offset="33%"  stop-color="#72c8ff"/>
                    <stop offset="50%"  stop-color="#5fe08f"/>
                    <stop offset="75%"  stop-color="#ffd166"/>
                    <stop offset="100%" stop-color="#ff9f5c"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#stArc)" stroke-width="7" stroke-linecap="round"/>
            <text x="1.0" y="86.5" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">0</text>
            <text x="11.6" y="47.0" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">5</text>
            <text x="40.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">10</text>
            <text x="80.0" y="7.5" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">15</text>
            <text x="119.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">20</text>
            <text x="148.4" y="47.0" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">25</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">30</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="${vc}">
                ${sst != null ? sst.toFixed(1) : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">°C</text>
        </svg>
    </div>`;
}

/* =========================================================
   ИНДИКАТОР: НАГОН/СГОН (дуга, -30..+30 см)
========================================================= */
function seaLevelIndicatorSvg(cm){
    const vMin = -30, vMax = 30;
    const vC    = cm != null ? Math.max(vMin, Math.min(vMax, cm)) : null;
    const angle = vC != null ? vC / vMax * 90 : 0;

    const L_STOPS = [
        {offset:0,    color:"#ff9f5c"},
        {offset:0.5,  color:"#999999"},
        {offset:1,    color:"#74b9ff"},
    ];
    const lT = vC != null ? (vC - vMin) / (vMax - vMin) : null;
    const vc = lT != null ? gradientColor(L_STOPS, lT) : "#aaa";

    return `
    <div class="ind-card">
        <div class="ind-title">Нагон/сгон</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Нагон/сгон" style="overflow:visible;">
            <defs>
                <linearGradient id="slArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#ff9f5c"/>
                    <stop offset="50%"  stop-color="#999999"/>
                    <stop offset="100%" stop-color="#74b9ff"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#slArc)" stroke-width="7" stroke-linecap="round"/>
            <text x="1.0" y="86.5" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">-30</text>
            <text x="11.6" y="47.0" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">-20</text>
            <text x="40.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">-10</text>
            <text x="80.0" y="7.5" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">0</text>
            <text x="119.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">10</text>
            <text x="148.4" y="47.0" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">20</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">30</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="${vc}">
                ${cm != null ? (cm >= 0 ? "+" : "") + cm : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">см</text>
        </svg>
    </div>`;
}

/* =========================================================
   ИНДИКАТОР: РОЗА НАПРАВЛЕНИЯ (волна/зыбь/ветровая волна/течение)
========================================================= */
function seaCompassIndicatorSvg(o){
    const dir  = o.dir;
    const rot  = (dir != null ? dir : 0) + 180;
    const ring = o.color || "rgba(255,255,255,0.35)";
    const clickAttr = o.toggleKey ? ` onclick="toggleMarineVariant('${o.toggleKey}')"` : "";

    return `
    <div class="ind-card"${clickAttr}>
        <div class="ind-title">${o.title}</div>
        <svg viewBox="0 0 160 160" width="${IND_W}" height="${IND_W}" aria-label="${o.title}">
            <line x1="80.0" y1="13.0" x2="80.0" y2="20.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="120.3" y1="29.7" x2="115.4" y2="34.6" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="137.0" y1="70.0" x2="130.0" y2="70.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="120.3" y1="110.3" x2="115.4" y2="105.4" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="80.0" y1="127.0" x2="80.0" y2="120.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="39.7" y1="110.3" x2="44.6" y2="105.4" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="23.0" y1="70.0" x2="30.0" y2="70.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="39.7" y1="29.7" x2="44.6" y2="34.6" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <text x="80"  y="10"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">С</text>
            <text x="143" y="73"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">В</text>
            <text x="80"  y="137" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">Ю</text>
            <text x="16"  y="73"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">З</text>
            <circle cx="80" cy="70" r="43" fill="none" stroke="${ring}" stroke-opacity="0.75" stroke-width="3.5"/>
            ${dir != null ? `
            <g style="transform-origin:80px 70px;transform:rotate(${rot}deg);transition:transform 0.8s cubic-bezier(0.34,1.56,0.64,1);">
                <polygon points="80,95 76,114.5 84,114.5" fill="currentColor" opacity="0.85"/>
            </g>` : ""}
            <text x="80" y="73.5" text-anchor="middle" font-size="22" font-weight="800" fill="currentColor">
                ${o.mainValue ?? "-"}
            </text>
            <text x="80" y="52" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.65">${o.mainUnit || ""}</text>
            ${o.secondaryValue != null ? `
            <text x="80" y="100" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.40">${o.secondaryLabel || ""}</text>
            <text x="80" y="88" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor" fill-opacity="0.85">
                ${o.secondaryValue}
            </text>` : ""}
            <text x="80" y="155" text-anchor="middle" font-size="12" fill="currentColor" fill-opacity="0.65">
                ${dir != null ? marineDirText(dir) : "—"}
            </text>
        </svg>
    </div>`;
}

/* =========================================================
   ИНДИКАТОР: ВЫСОТА ВОЛНЫ КАК ДУГА (альтернативный вариант —
   приоритет высоте, направление/период — подписью снизу)
========================================================= */
let _waveArcIdSeq = 0;
function seaWaveArcSvg(o){
    const vMax  = 3; // м — шкала дуги
    const hRaw  = o.height;
    const hC    = hRaw != null ? Math.max(0, Math.min(vMax, hRaw)) : null;
    const angle = hC != null ? (hC - vMax/2) / (vMax/2) * 90 : 0;

    const W_STOPS = [
        {offset:0,    color:"#55efc4"},
        {offset:0.17, color:"#00cec9"},
        {offset:0.42, color:"#74b9ff"},
        {offset:0.83, color:"#ffd166"},
        {offset:1,    color:"#ff6b6b"},
    ];
    const wT = hC != null ? hC / vMax : null;
    const vc = wT != null ? gradientColor(W_STOPS, wT) : "#aaa";
    const hp = marineHeightParts(hRaw);
    const gid = "waveArc" + (_waveArcIdSeq++);
    const clickAttr = o.toggleKey ? ` onclick="toggleMarineVariant('${o.toggleKey}')"` : "";

    const subParts = [];
    if(o.dir != null) subParts.push(marineDirText(o.dir));
    if(o.period != null) subParts.push(o.period.toFixed(1) + " с");

    return `
    <div class="ind-card"${clickAttr}>
        <div class="ind-title">${o.title}</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="${o.title}" style="overflow:visible;">
            <defs>
                <linearGradient id="${gid}" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#55efc4"/>
                    <stop offset="17%"  stop-color="#00cec9"/>
                    <stop offset="42%"  stop-color="#74b9ff"/>
                    <stop offset="83%"  stop-color="#ffd166"/>
                    <stop offset="100%" stop-color="#ff6b6b"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#${gid})" stroke-width="7" stroke-linecap="round"/>
            <text x="1.0" y="86.5" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">0</text>
            <text x="11.6" y="47.0" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">0.5</text>
            <text x="40.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">1</text>
            <text x="80.0" y="7.5" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">1.5</text>
            <text x="119.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">2</text>
            <text x="148.4" y="47.0" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">2.5</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">3м</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="${vc}">${hp.value}</text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">${hp.unit}</text>
        </svg>
        ${subParts.length ? `<div class="ind-sub">${subParts.join(" · ")}</div>` : ""}
    </div>`;
}

/* =========================================================
   ВЫБОР ВАРИАНТА ОТОБРАЖЕНИЯ (компас / дуга) — по тапу,
   хранится в localStorage, отдельно на волну/зыбь/ветр. волну
========================================================= */
const MARINE_VARIANT_KEY = "marineIndVariants";
const MARINE_VARIANT_DEFAULTS = { wave:"compass", swell:"compass", windWave:"compass" };

function getMarineVariants(){
    try {
        return Object.assign({}, MARINE_VARIANT_DEFAULTS,
            JSON.parse(localStorage.getItem(MARINE_VARIANT_KEY) || "{}"));
    } catch(e){
        return Object.assign({}, MARINE_VARIANT_DEFAULTS);
    }
}

function toggleMarineVariant(key){
    const v = getMarineVariants();
    v[key] = v[key] === "arc" ? "compass" : "arc";
    try { localStorage.setItem(MARINE_VARIANT_KEY, JSON.stringify(v)); } catch(e){}
    refreshMarineIndGrid();
}

function refreshMarineIndGrid(){
    const el = document.getElementById("marineIndGrid");
    if(!el || !_marineData) return;
    el.innerHTML = buildMarineIndicatorCards(_marineData);
}

function buildMarineIndicatorCards(m){
    const cards = [];
    const variants = getMarineVariants();

    if(m.sst != null) cards.push(seaTempIndicatorSvg(m.sst));
    if(m.seaLevel != null) cards.push(seaLevelIndicatorSvg(m.seaLevel));

    if(m.waveH != null){
        const hp = marineHeightParts(m.waveH);
        const per = m.wavePeakPer ?? m.wavePer;
        const state = marineSeaStateLabel(m.waveH);
        cards.push(variants.wave === "arc"
            ? seaWaveArcSvg({ title:"Волна", height:m.waveH, dir:m.waveDir, period:per, toggleKey:"wave" })
            : seaCompassIndicatorSvg({
                title: "Волна", dir: m.waveDir,
                mainValue: hp.value, mainUnit: hp.unit,
                secondaryLabel: "период", secondaryValue: per != null ? per.toFixed(1) + " с" : null,
                color: state ? state.color : null, toggleKey: "wave",
            }));
    }
    if(m.swellH != null){
        const hp = marineHeightParts(m.swellH);
        cards.push(variants.swell === "arc"
            ? seaWaveArcSvg({ title:"Зыбь", height:m.swellH, dir:m.swellDir, period:m.swellPer, toggleKey:"swell" })
            : seaCompassIndicatorSvg({
                title: "Зыбь", dir: m.swellDir,
                mainValue: hp.value, mainUnit: hp.unit,
                secondaryLabel: "период", secondaryValue: m.swellPer != null ? m.swellPer.toFixed(1) + " с" : null,
                color: "#a29bfe", toggleKey: "swell",
            }));
    }
    if(m.windWaveH != null){
        const hp = marineHeightParts(m.windWaveH);
        cards.push(variants.windWave === "arc"
            ? seaWaveArcSvg({ title:"Ветровая волна", height:m.windWaveH, dir:m.windWaveDir, period:null, toggleKey:"windWave" })
            : seaCompassIndicatorSvg({
                title: "Ветровая волна", dir: m.windWaveDir,
                mainValue: hp.value, mainUnit: hp.unit,
                color: "#81ecec", toggleKey: "windWave",
            }));
    }
    if(m.seaWindSpeed != null){
        cards.push(windIndicatorSvg({
            windSpeed: Math.round(m.seaWindSpeed),
            windGustMs: m.seaWindGust != null ? Math.round(m.seaWindGust) : null,
            windDir: m.seaWindDir,
        }));
    }
    if(m.seaPressure != null){
        cards.push(pressureIndicatorSvg({
            seaPressure: Math.round(m.seaPressure * 10) / 10,
            tendencyCode: null, tendencyValue: null,
        }));
    }
    if(m.currentV != null && m.currentV > 0.05){
        cards.push(seaCompassIndicatorSvg({
            title: "Течение", dir: m.currentDir,
            mainValue: m.currentV.toFixed(1), mainUnit: "м/с",
            color: "#ff7675",
        }));
    }

    return cards.join("");
}

function makeMarineIndicatorsGrid(m){
    const cards = buildMarineIndicatorCards(m);
    if(!cards) return "";
    return `<div class="ind-grid-2x2" id="marineIndGrid">${cards}</div>`;
}

/* =========================================================
   БЛОК: МОРЕ (карточка "Море · Чёрное море")
========================================================= */
function makeMarineBlock(opts){
    opts = opts || {};
    const m = _marineData;
    if(!m) return "";

    const state    = marineSeaStateLabel(m.waveH);
    const gridHtml = makeMarineIndicatorsGrid(m);
    if(!gridHtml) return "";

    const warnHtml = state && m.waveH >= 1.25 ? `
        <div style="margin-bottom:8px;padding:7px 10px;border-radius:8px;
             background:${state.color}15;border:1px solid ${state.color}44;
             font-size:13px;font-weight:700;color:${state.color};">
            🌊 ${state.label}
        </div>` : "";

    const sourceTime = m.time ? (() => {
        const d = new Date(m.time);
        return isNaN(d) ? "" :
            d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});
    })() : "";

    const titleText = opts.hideTitlePrefix
        ? `${sourceTime ? sourceTime + " · " : ""}модель CMEMS`
        : `Море · Чёрное море${sourceTime ? " · " + sourceTime : ""} · модель CMEMS`;

    return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        <div style="font-size:11px;color:#666;margin-bottom:8px;
                    text-transform:uppercase;letter-spacing:.5px;">
            ${titleText}
        </div>
        ${warnHtml}
        ${gridHtml}
    </div>`;
}



/* =========================================================
   БЛОК: СВЕРКА С РЕАЛЬНЫМИ ЗАМЕРАМИ (ГМЦ ЧАМ)
========================================================= */
function makeHmcbasVerifyBlock(){
    const hasSite = _hmcbasSeaTemp   && _hmcbasSeaTemp.sea_temp   != null;
    const hasTg   = _hmcbasTelegram  && _hmcbasTelegram.sea_temp  != null;

    const modelSst = _marineData && _marineData.sst != null ? _marineData.sst : null;

    function factRow(label, factT, diffHtml, extraTxt){
        return `<div class="seaFactRow">
            <span class="sfLabel">${label}${extraTxt || ""}</span>
            <span class="sfValue">${factT.toFixed(1)}°C${diffHtml}</span>
        </div>`;
    }

    function diffSpan(factT){
        if(modelSst == null) return "";
        const diff = modelSst - factT;
        const col  = Math.abs(diff) >= 1 ? "#ff9f5c" : "#888";
        return ` <span style="font-size:12px;color:${col};">(CMEMS ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}°)</span>`;
    }

    const siteRow = hasSite ? factRow(
        "📡 ГМЦ ЧАМ, сайт",
        _hmcbasSeaTemp.sea_temp,
        diffSpan(_hmcbasSeaTemp.sea_temp),
        _hmcbasSeaTemp.stale ? " · устар." : ""
    ) : "";

    const tgRow = hasTg ? (() => {
        let dateTxt = "";
        try {
            const dt = new Date(_hmcbasTelegram.timestamp);
            if(!isNaN(dt)){
                const d = dt.toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit",timeZone:"Europe/Kyiv"});
                const t = dt.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",timeZone:"Europe/Kyiv"});
                dateTxt = ` · ${d} ${t}`;
            }
        } catch(e){}
        return factRow("📨 ГМЦ ЧАМ", _hmcbasTelegram.sea_temp, diffSpan(_hmcbasTelegram.sea_temp), dateTxt);
    })() : "";

    // последняя валидная запись по каждому TikTok-каналу
    const tiktokLatest = {};
    for(const e of _tiktokSeaTemp){
        if(e.sea_temp == null) continue;
        const key = e.channel || e.url;
        if(!tiktokLatest[key] || e.timestamp > tiktokLatest[key].timestamp) tiktokLatest[key] = e;
    }
    const tiktokRows = Object.values(tiktokLatest).map(e => {
        let dateTxt = e.date ? " · " + e.date.split("-").slice(1).reverse().join(".") : "";
        if(e.time) dateTxt += " " + e.time;
        let beachTxt = "";
        if(e.beach){
            let b = e.beach.charAt(0).toUpperCase() + e.beach.slice(1);
            b = b.replace(/станция/gi, "ст.");
            beachTxt = " " + b;
        }
        return factRow("🎵" + beachTxt + dateTxt, e.sea_temp, diffSpan(e.sea_temp), "");
    }).join("");

    if(!hasSite && !hasTg && !tiktokRows) return "";

    return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        <div style="font-size:11px;color:#555;margin-bottom:8px;
                    text-transform:uppercase;letter-spacing:.5px;">
            Сверка с реальными замерами
        </div>
        <div class="pws-fields seaVerifyList">
            ${siteRow}
            ${tgRow}
            ${tiktokRows}
        </div>
    </div>`;
}

/* =========================================================
   БЛОК: ТОЧНОСТЬ МОДЕЛИ CMEMS (сравнение с реальными замерами
   во времени — ГМЦ ЧАМ телеграм + TikTok-каналы)
========================================================= */
function nearestMarineSst(targetTs, maxDiffMs){
    if(!_marineHistArr || !_marineHistArr.length) return null;
    let best = null, bestDiff = Infinity;
    for(const o of _marineHistArr){
        if(o.sst == null) continue;
        const t = Date.parse(o.time);
        if(isNaN(t)) continue;
        const diff = Math.abs(t - targetTs);
        if(diff < bestDiff){ bestDiff = diff; best = o.sst; }
    }
    if(bestDiff > maxDiffMs) return null;
    return best;
}

function makeMarineAccuracyBlock(){
    if(!_marineHistArr || !_marineHistArr.length) return "";

    function stats(entries, getTs, getVal){
        const diffs = [];
        for(const e of entries){
            const val = getVal(e);
            if(val == null) continue;
            const ts = getTs(e);
            if(isNaN(ts)) continue;
            const modelSst = nearestMarineSst(ts, 3 * 3600000); // ±3ч
            if(modelSst == null) continue;
            diffs.push(modelSst - val);
        }
        if(diffs.length < 2) return null;
        const n    = diffs.length;
        const mae  = diffs.reduce((a,b)=>a+Math.abs(b),0) / n;
        const bias = diffs.reduce((a,b)=>a+b,0) / n;
        return { n, mae, bias };
    }

    const cards = [];

    if(_hmcbasTelegramArr && _hmcbasTelegramArr.length){
        const st = stats(_hmcbasTelegramArr, e=>Date.parse(e.timestamp), e=>e.sea_temp);
        if(st) cards.push({ label:"📨 ГМЦ ЧАМ", ...st });
    }

    const byChannel = {};
    for(const e of _tiktokSeaTemp){
        const key = e.channel || e.url;
        (byChannel[key] = byChannel[key] || []).push(e);
    }
    for(const key of Object.keys(byChannel)){
        const arr = byChannel[key];
        const st  = stats(arr, e=>Date.parse(e.timestamp), e=>e.sea_temp);
        if(!st) continue;
        let label = "🎵";
        const withBeach = arr.slice().reverse().find(e=>e.beach);
        if(withBeach){
            let b = withBeach.beach.charAt(0).toUpperCase() + withBeach.beach.slice(1);
            b = b.replace(/станция/gi, "ст.");
            label += " " + b;
        }
        cards.push({ label, ...st });
    }

    const header = `
        <div style="font-size:11px;color:#555;margin-bottom:8px;
                    text-transform:uppercase;letter-spacing:.5px;">
            Точность модели CMEMS
        </div>`;

    if(!cards.length){
        return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        ${header}
        <div style="color:#666;font-size:13px;padding:6px 0;">Недостаточно данных для оценки точности</div>
    </div>`;
    }

    return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        ${header}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${cards.map(c => {
                const col = Math.abs(c.bias) < 0.3 ? "#5fe08f" : Math.abs(c.bias) < 0.8 ? "#ffd166" : "#ff6b6b";
                return `<div class="es-card">
                    <div class="es-card-label">${c.label}</div>
                    <div class="es-card-mae" style="color:${col};">${c.mae.toFixed(1)}°</div>
                    <div class="es-card-sub">по ${c.n} замерам<br>смещение ${c.bias >= 0 ? "+" : ""}${c.bias.toFixed(1)}°</div>
                </div>`;
            }).join("")}
        </div>
    </div>`;
}
