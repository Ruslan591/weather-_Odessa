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
function makeMarineBlock(opts){
    opts = opts || {};
    const m = _marineData;
    if(!m) return "";

    function seaStateLabel(h){
        if(h == null) return null;
        if(h < 0.10) return { label:"Штиль (0 баллов)",         color:"#55efc4" };
        if(h < 0.50) return { label:"Рябь (1 балл)",            color:"#00cec9" };
        if(h < 1.25) return { label:"Лёгкое волнение (2)",      color:"#74b9ff" };
        if(h < 2.50) return { label:"Умеренное волнение (3–4)", color:"#ffd166" };
        if(h < 4.00) return { label:"Значительное (5)",         color:"#ff9f5c" };
        if(h < 6.00) return { label:"Сильное (6–7)",            color:"#ff6b6b" };
        return              { label:"Очень сильное (8–9)",       color:"#d63031" };
    }

    const state    = seaStateLabel(m.waveH);
    const sstColor = m.sst == null ? "#aaa"
        : m.sst < 12 ? "#74b9ff"
        : m.sst < 20 ? "#00cec9"
        : m.sst < 26 ? "#55efc4"
        :               "#ffd166";

    const fV   = v   => v != null ? v.toFixed(1) : "—";
    const fWind = v  => v != null ? Math.round(v) : "—";
    const fHeight = v => {
        if(v == null) return "—";
        return v < 1 ? `${Math.round(v * 100)} см` : `${v.toFixed(1)} м`;
    };
    const fDir = deg => {
        if(deg == null) return "—";
        const dirs = ["С","ССВ","СВ","ВСВ","В","ВЮВ","ЮВ","ЮЮВ",
                      "Ю","ЮЮЗ","ЮЗ","ЗЮЗ","З","ЗСЗ","СЗ","ССЗ"];
        return dirs[Math.round(deg/22.5)%16] + " " + Math.round(deg) + "°";
    };

    const warnHtml = state && m.waveH >= 1.25 ? `
        <div style="margin-bottom:8px;padding:7px 10px;border-radius:8px;
             background:${state.color}15;border:1px solid ${state.color}44;
             font-size:13px;font-weight:700;color:${state.color};">
            🌊 ${state.label}
        </div>` : "";

    const sstHtml = m.sst != null ? `
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:8px 0 10px;border-bottom:1px solid #1e1e1e;margin-bottom:6px;">
            <span style="font-size:14px;color:#888;">🌡️ Температура воды</span>
            <span style="font-size:26px;font-weight:800;color:${sstColor};">${m.sst.toFixed(1)}°C</span>
        </div>` : "";

    const seaLevelHtml = m.seaLevel != null ? (() => {
        const cm  = m.seaLevel;
        const arr = cm > 5 ? " ↑" : cm < -5 ? " ↓" : " →";
        const col = cm > 5 ? "#74b9ff" : cm < -5 ? "#ff9f5c" : "#888";
        return `<div class="seaFactRow">
            <span class="sfLabel">📏 Нагон/сгон</span>
            <span class="sfValue" style="color:${col};">${cm >= 0 ? "+" : ""}${cm} см${arr}</span>
        </div>`;
    })() : "";

    const rows = [
        m.waveH      != null ? ["🌊 Волна",
            `${fHeight(m.waveH)} · ${fDir(m.waveDir)}`
            + (m.wavePeakPer != null ? ` · Tп=${m.wavePeakPer.toFixed(0)} с`
               : m.wavePer   != null ? ` · T=${m.wavePer.toFixed(0)} с` : "")
        ] : null,
        m.swellH     != null ? ["〰️ Зыбь",
            `${fHeight(m.swellH)} · ${fDir(m.swellDir)}`
            + (m.swellPer != null ? ` · T=${m.swellPer.toFixed(0)} с` : "")
        ] : null,
        m.windWaveH  != null ? ["💨 Ветровая волна",
            `${fHeight(m.windWaveH)} · ${fDir(m.windWaveDir)}`
        ] : null,
        m.seaWindSpeed != null ? ["🌬️ Ветер над морем",
            `${fWind(m.seaWindSpeed)} м/с · порывы ${fWind(m.seaWindGust)} · ${fDir(m.seaWindDir)}`
        ] : null,
        m.seaPressure != null ? ["🔵 Давление (море)", `${m.seaPressure.toFixed(1)} гПа`] : null,
        m.currentV   != null && m.currentV > 0.05 ? ["🔄 Течение",
            `${fV(m.currentV)} м/с · ${fDir(m.currentDir)}`
        ] : null,
    ].filter(Boolean);

    if(!sstHtml && !rows.length) return "";

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
        ${sstHtml}
        <div class="pws-fields">
            ${seaLevelHtml}
            ${rows.map(([k,v]) =>
                `<div class="seaFactRow"><span class="sfLabel">${k}</span><span class="sfValue">${v}</span></div>`
            ).join("")}
        </div>
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
