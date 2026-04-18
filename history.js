/* =========================================================
   HISTORY.JS — график истории PWS
   Зависит от: utils.js, pws.js (WU_KEYS), pws_page.js (PWS_STATIONS, _currentId)
   Библиотека: uPlot (CDN)
========================================================= */

/* =========================================================
   КОНФИГ ПАРАМЕТРОВ
========================================================= */
const HIST_PARAMS = {
    temp:     { label:"Температура",  unit:"°C",    color:"#ff6b6b", field:"temp",        stroke:"#ff6b6b", fill:"rgba(255,107,107,0.10)" },
    pressure: { label:"Давление",     unit:" гПа",  color:"#58aeff", field:"pressure",    stroke:"#58aeff", fill:"rgba(88,174,255,0.10)"  },
    humidity: { label:"Влажность",    unit:"%",     color:"#5fe08f", field:"humidity",    stroke:"#5fe08f", fill:"rgba(95,224,143,0.10)"  },
    wind:     { label:"Ветер",        unit:" м/с",  color:"#ffd166", field:"windSpeedMs", stroke:"#ffd166", fill:"rgba(255,209,102,0.10)"  },
    winddir:  { label:"Направление",  unit:"°",     color:"#74b9ff", field:"windDir",     stroke:"#74b9ff", fill:"rgba(116,185,255,0.10)", scatter:true },
    precip:   { label:"Осадки",       unit:" мм",   color:"#448aff", field:"precip",      stroke:"#448aff", fill:"rgba(68,138,255,0.15)",  bar:true },
    solar:    { label:"Радиация",     unit:" Вт/м²",color:"#ff9f43", field:"solarRad",    stroke:"#ff9f43", fill:"rgba(255,159,67,0.10)"   },
    uv:       { label:"УФ-индекс",    unit:"",      color:"#a29bfe", field:"uv",          stroke:"#a29bfe", fill:"rgba(162,155,254,0.10)"  },
};

const HIST_PERIODS = [
    { id:"today",  label:"Сегодня" },
    { id:"7day",   label:"7 дней"  },
    { id:"month",  label:"Месяц"   },
    { id:"custom", label:"Период"  },
];

/* ==============≠==========================================

========================================================= */
function histParseObs(o){
    const m   = o.metric || {};
    const km  = v => v != null ? Math.round(v / 3.6 * 10) / 10 : null;
    const off = (typeof getOffset === "function" && typeof _currentId !== "undefined")
        ? getOffset(_currentId) : 0;
    const rawP = m.pressureMax ?? m.pressureAvg ?? m.pressure ?? null;
    return {
        obsTimeLocal: o.obsTimeLocal || o.obsTimeUtc || null,
        temp:         m.tempAvg     ?? m.temp     ?? null,
        tempHigh:     m.tempHigh    ?? null,
        tempLow:      m.tempLow     ?? null,
        pressure:     rawP != null ? Math.round((rawP + off) * 10) / 10 : null,
        humidity:     o.humidityAvg ?? o.humidity ?? null,
        windSpeedMs:  km(m.windspeedAvg ?? m.windSpeed ?? null),
        windGustMs:   km(m.windgustHigh ?? m.windGust  ?? null),
        windDir:      o.winddirAvg  ?? o.winddir  ?? null,
        precip:       m.precipTotal ?? m.precipRate ?? null,
        precipRate:   m.precipRate ?? null,
        solarRad:     o.solarRadiationHigh ?? o.solarRadiation ?? null,
        uv:           o.uvHigh      ?? o.uv       ?? null,
    };
}

/* =========================================================
   СОСТОЯНИЕ
========================================================= */
let _histChart   = null;
let _histParam   = "temp";
let _histPeriod  = "today";
let _histData    = null;   // { times:[], values:[], obs:[] }
let _histLoading = false;

/* =========================================================
   ЗАГРУЗКА ДАННЫХ
========================================================= */
async function histFetch(stationId, period){
    const key = WU_KEYS[0];

    if(period === "today"){
    const url = `https://api.weather.com/v2/pws/observations/all/1day`
        + `?stationId=${encodeURIComponent(stationId)}&format=json&units=m&numericPrecision=decimal&apiKey=${key}`;
    const r = await fetch(url, {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    const text = await r.text();
    if(!text || !text.trim()) throw new Error("Нет данных за сегодня");
    let d;
    try { d = JSON.parse(text); } catch(e) { throw new Error("Нет данных за сегодня"); }
    if(!d?.observations?.length) throw new Error("Нет данных");
    return d.observations.map(histParseObs);
}

if(period === "7day"){
    const url = `https://api.weather.com/v2/pws/observations/hourly/7day`
        + `?stationId=${encodeURIComponent(stationId)}&format=json&units=m&numericPrecision=decimal&apiKey=${key}`;
    const r = await fetch(url, {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if(!d?.observations?.length) throw new Error("Нет данных");
    return d.observations.map(histParseObs);
}

    if(period === "month"){
        // Собираем последние 30 дней через history/all по дням (оптимально: hourly не даёт месяц)
        // Используем history/daily для агрегатов
        const end   = new Date();
        const start = new Date(); start.setDate(start.getDate() - 29);
        const fmt   = d => d.toISOString().slice(0,10).replace(/-/g,"");
        const url = `https://api.weather.com/v2/pws/history/daily`
            + `?stationId=${encodeURIComponent(stationId)}&format=json&units=m&numericPrecision=decimal`
            + `&startDate=${fmt(start)}&endDate=${fmt(end)}&apiKey=${key}`;
        const r = await fetch(url, {cache:"no-store"});
        if(!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        if(!d?.observations?.length) throw new Error("Нет данных");
        // Дневные агрегаты — адаптируем под общий формат
        return d.observations.map(o => ({
            obsTimeLocal: o.obsTimeLocal || (o.obsTimeUtc||""),
            temp:         o.metric?.tempAvg    ?? null,
            tempHigh:     o.metric?.tempHigh   ?? null,
            tempLow:      o.metric?.tempLow    ?? null,
            pressure:     o.metric?.pressureMax?? null,
            humidity:     o.humidityAvg        ?? null,
            windSpeedMs:  o.metric?.windspeedAvg != null ? Math.round(o.metric.windspeedAvg/3.6*10)/10 : null,
            windGustMs:   o.metric?.windgustHigh != null ? Math.round(o.metric.windgustHigh/3.6*10)/10 : null,
            solarRad:     o.solarRadiationHigh ?? null,
            uv:           o.uvHigh             ?? null,
            _daily:       true,
        }));
    }

    if(period === "custom"){
    const s = document.getElementById("histDateStart")?.value;
    const e = document.getElementById("histDateEnd")?.value;
    if(!s || !e) throw new Error("Выберите даты");

    // Собираем все дни в диапазоне
    const start = new Date(s);
    const end   = new Date(e);
    const allObs = [];

    for(let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)){
        const ymd = d.toISOString().slice(0,10).replace(/-/g,"");
        const url = `https://api.weather.com/v2/pws/history/all`
            + `?stationId=${encodeURIComponent(stationId)}&format=json&units=m&numericPrecision=decimal`
            + `&date=${ymd}&apiKey=${key}`;
        try {
            const r = await fetch(url, {cache:"no-store"});
            if(!r.ok) continue;
            const d2 = await r.json();
            if(d2?.observations?.length) allObs.push(...d2.observations.map(histParseObs));
        } catch(e){ continue; }
    }

    if(!allObs.length) throw new Error("Нет данных за выбранный период");
    return allObs;
}
}

/* =========================================================
   ПАРСИНГ В ЧИСЛОВЫЕ МАССИВЫ ДЛЯ uPlot
========================================================= */
function histPrepare(obs, paramKey){
    const cfg    = HIST_PARAMS[paramKey];
    const times  = [];
    const values = [];

    for(const o of obs){
        // Пробуем все варианты поля времени
        const raw = o.obsTimeLocal || o.obsTimeUtc || "";
        if(!raw) continue;
        // Нормализуем: заменяем пробел на T, убираем лишнее
        const normalized = raw.trim().replace(" ", "T");
        const d = new Date(normalized);
        if(isNaN(d.getTime())) continue;
        const val = o[cfg.field];
        times.push(d.getTime() / 1000);
        values.push(val != null ? +val : null);
    }
    return { times, values, obs };
}

/* =========================================================
   РЕНДЕР uPlot
========================================================= */
function histRenderChart(data, paramKey){
    if(paramKey === "winddir") return histRenderChart_WindDir(data);
    const engine = (typeof HIST_ENGINE !== "undefined") ? HIST_ENGINE : "uplot";
    if(engine === "svg")    return histRenderChart_SVG(data, paramKey);
    if(engine === "chartjs") return histRenderChart_ChartJS(data, paramKey);
    return histRenderChart_uPlot(data, paramKey);
}

/* ── движок uPlot (текущий) ── */
function histRenderChart_uPlot(data, paramKey){
    const cfg  = HIST_PARAMS[paramKey];
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;

    if(_histChart){ _histChart.destroy(); _histChart = null; }
    wrap.innerHTML = "";

    const { times, values } = data;
    if(!times.length){
        wrap.innerHTML = `<div style="color:#666;text-align:center;padding:30px;">Нет данных для отображения</div>`;
        return;
    }

    const W = wrap.clientWidth || 340;

    const opts = {
        width:  W,
        height: 220,
        class:  "hist-uplot",
        cursor: {
            sync: { key: "hist" },
            points: { show: true, size: 8, fill: cfg.color, stroke: "#1e1e1e" },
            drag: { x: true, y: false },
        },
        legend: { show: false },
        scales: {
            x: { time: true },
            y: { auto: true },
        },
        axes: [
            {
                stroke:    "#555",
                grid:      { stroke:"#252525", width:1 },
                ticks:     { stroke:"#333",    width:1 },
                font:      "11px sans-serif",
                labelFont: "11px sans-serif",
            },
            {
                stroke:    "#555",
                grid:      { stroke:"#252525", width:1 },
                ticks:     { stroke:"#333",    width:1 },
                font:      "11px sans-serif",
                size:      46,
                values:    (u, vals) => vals.map(v => v != null ? v + cfg.unit : ""),
            },
        ],
        series: [
            {},
            {
                label:        cfg.label,
                stroke:       cfg.stroke,
                fill:         cfg.fill,
                width:        2,
                spanGaps:     false,
                points: { show: false },
            },
        ],
        hooks: {
            setCursor: [
                u => {
                    const idx = u.cursor.idx;
                    if(idx == null){ histHideTooltip(); return; }
                    histShowTooltip(u, idx, data, paramKey);
                }
            ],
        },
    };

    _histChart = new uPlot(opts, [new Float64Array(times), values.map(v => v ?? NaN)], wrap);
}

/* ── движок SVG (встроенный, без зависимостей) ── */
function histRenderChart_SVG(data, paramKey){
    const cfg  = HIST_PARAMS[paramKey];
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;

    if(_histChart){ _histChart.destroy && _histChart.destroy(); _histChart = null; }

    const { times, values } = data;
    if(!times.length){
        wrap.innerHTML = `<div style="color:#666;text-align:center;padding:30px;">Нет данных для отображения</div>`;
        return;
    }

    const W = wrap.clientWidth || 340, H = 220;
    const pad = { t:10, r:10, b:36, l:50 };
    const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;

    const vals = values.map(v => v ?? NaN);
    const tMin = Math.min(...times), tMax = Math.max(...times);
    const vAll = vals.filter(v => !isNaN(v));
    if(!vAll.length){ wrap.innerHTML = `<div style="color:#666;text-align:center;padding:30px;">Нет данных</div>`; return; }

    let vMin = Math.min(...vAll), vMax = Math.max(...vAll);
    if(vMin === vMax){ vMin -= 1; vMax += 1; }

    const px = t => pad.l + (t - tMin) / (tMax - tMin) * iW;
    const py = v => pad.t + (1 - (v - vMin) / (vMax - vMin)) * iH;

    // Строим path
    // Собираем точки
    const pts = [];
    times.forEach((t, i) => {
        if(isNaN(vals[i])) return;
        pts.push({ x: px(t), y: py(vals[i]) });
    });

    // Сглаживание через квадратичные кривые Безье (как в forecast.html)
    function smoothPath(points){
        if(!points.length) return "";
        let d = `M ${points[0].x} ${points[0].y}`;
        for(let i = 1; i < points.length - 1; i++){
            const xc = (points[i].x + points[i+1].x) / 2;
            const yc = (points[i].y + points[i+1].y) / 2;
            d += ` Q ${points[i].x} ${points[i].y} ${xc} ${yc}`;
        }
        const last = points[points.length - 1];
        d += ` T ${last.x} ${last.y}`;
        return d;
    }

    const pathD = pts.length > 1 ? smoothPath(pts) : "";
    const areaD = pts.length > 1
        ? pathD + ` L${pts[pts.length-1].x},${pad.t+iH} L${pts[0].x},${pad.t+iH} Z`
        : "";

    // Метки Y
    const yTicks = 5;
    let yLabels = "";
    for(let i = 0; i <= yTicks; i++){
        const v = vMin + (vMax - vMin) * (1 - i / yTicks);
        const y = pad.t + iH * i / yTicks;
        yLabels += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="10" fill="#555">${v.toFixed(1)}</text>`;
    }

    // Метки X (до 6 меток)
    let xLabels = "";
    const xStep = Math.ceil(times.length / 6);
    times.forEach((t, i) => {
        if(i % xStep !== 0) return;
        const x = px(t);
        const d = new Date(t * 1000);
        const lbl = d.getDate() === new Date(times[0]*1000).getDate()
    ? d.toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit"})
    : d.toLocaleDateString("ru-RU", {day:"2-digit", month:"2-digit", year:"numeric"});
        xLabels += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#252525" stroke-width="1"/>`;
        xLabels += `<text x="${x}" y="${H-8}" text-anchor="middle" font-size="10" fill="#555">${lbl}</text>`;
    });

    const gradId = "svgHistGrad_" + paramKey;
    wrap.innerHTML = `
    <svg width="${W}" height="${H}" style="display:block;">
        <defs>
            <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${cfg.color}" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="${cfg.color}" stop-opacity="0"/>
            </linearGradient>
        </defs>
        ${yLabels}${xLabels}
        ${areaD ? `<path d="${areaD}" fill="url(#${gradId})" stroke="none"/>` : ""}
        <path d="${pathD}" fill="none" stroke="${cfg.stroke}" stroke-width="2" stroke-linejoin="round"/>
    </svg>`;

    // Тултип по наведению
    const svg = wrap.querySelector("svg");
    svg.addEventListener("mousemove", e => {
        const rect = svg.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        // Ищем ближайшую точку
        let best = 0, bestDist = Infinity;
        times.forEach((t, i) => {
            if(isNaN(vals[i])) return;
            const dist = Math.abs(px(t) - mx);
            if(dist < bestDist){ bestDist = dist; best = i; }
        });
        histShowTooltip({ cursor:{ left: mx } }, best, data, paramKey);
    });
    svg.addEventListener("mouseleave", histHideTooltip);

    // Возвращаем псевдо-объект с destroy для совместимости
    _histChart = {
        destroy(){ wrap.innerHTML = ""; },
        setSize({ width }){ histRenderChart_SVG(data, paramKey); }
    };
}

/* ── движок WindDir — scatter со стрелками ── */
/* ── движок WindDir — scatter со стрелками ── */
function histRenderChart_WindDir(data){
    const cfg  = HIST_PARAMS["winddir"];
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;

    if(_histChart){ _histChart.destroy && _histChart.destroy(); _histChart = null; }

    const { times, values, obs } = data;
    if(!times.length){
        wrap.innerHTML = `<div style="color:#666;text-align:center;padding:30px;">Нет данных</div>`;
        return;
    }

    const W = wrap.clientWidth || 340, H = 220;
    const pad = { t:20, r:10, b:28, l:34 };
    const iW = W - pad.l - pad.r, iH = H - pad.t - pad.b;

    // times здесь в секундах (Unix), конвертируем в мс для Date
    const tMin = Math.min(...times), tMax = Math.max(...times);
    const px = t => pad.l + (t - tMin) / (tMax - tMin || 1) * iW;
    const py = v => pad.t + (1 - v / 360) * iH;

    // Сетка Y — румбы
    const yRumbs = [
        [0,"С"],[45,"СВ"],[90,"В"],[135,"ЮВ"],
        [180,"Ю"],[225,"ЮЗ"],[270,"З"],[315,"СЗ"],[360,"С"]
    ];
    let yGrid = "", yLabels = "";
    for(const [deg, lbl] of yRumbs){
        const y = py(deg);
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${lbl}</text>`;
    }

    // Сетка X + метки с разделителями дней
    const DAY_NAMES_WD = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid = "", xLabels = "";
    const firstDay = new Date(tMin * 1000).getDate();
    const isMultiDay = new Date(tMax * 1000).getDate() !== firstDay || (tMax - tMin) > 86400;

    if(isMultiDay){
        // Найти все полночи
        const midnights = [];
        for(let i = 0; i < times.length; i++){
            const d = new Date(times[i] * 1000);
            if(d.getHours() === 0 && d.getMinutes() < 30){
                // Проверяем что это новая дата
                if(!midnights.length || new Date(midnights[midnights.length-1] * 1000).getDate() !== d.getDate()){
                    midnights.push(times[i]);
                }
            }
        }
        // Метки дней между полночами
        [...midnights].forEach((mt, mi) => {
            const x = px(mt);
            xGrid += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nextMt = midnights[mi + 1] ?? tMax;
            const xMid = (px(mt) + px(nextMt)) / 2;
            const d = new Date(mt * 1000);
            xLabels += `<text x="${xMid}" y="${pad.t - 4}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${DAY_NAMES_WD[d.getDay()]} ${d.getDate()}</text>`;
        });
        // Числовые метки времени по шагу
        const xStep = Math.max(1, Math.ceil(times.length / 6));
        times.forEach((t, i) => {
            if(i % xStep !== 0) return;
            const d = new Date(t * 1000);
            const hr = d.getHours();
            if(hr % 6 !== 0) return;
            xLabels += `<text x="${px(t)}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`;
        });
    } else {
        // Один день — просто часовые метки
        const xStep = Math.max(1, Math.ceil(times.length / 6));
        times.forEach((t, i) => {
            if(i % xStep !== 0) return;
            const d = new Date(t * 1000);
            xLabels += `<text x="${px(t)}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"})}</text>`;
        });
    }

    // Линия текущего времени
    let nowLine = "";
    const nowTs = Date.now() / 1000;
    if(nowTs >= tMin && nowTs <= tMax){
        const xNow = px(nowTs);
        nowLine = `<line x1="${xNow}" y1="${pad.t}" x2="${xNow}" y2="${pad.t+iH}"
                         stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`;
    }

    // Градиент цвета по скорости ветра
    const W_STOPS = [
        {offset:0,    color:"#7ec8ff"},
        {offset:0.13, color:"#67d7a7"},
        {offset:0.36, color:"#ffd166"},
        {offset:0.57, color:"#ff9f5c"},
        {offset:1,    color:"#ff6b6b"},
    ];
    const vMax = 25;
    function gradCol(spd){
        const t = Math.min(spd ?? 0, vMax) / vMax;
        const stops = W_STOPS;
        const cl = Math.max(0, Math.min(1, t));
        for(let i = 1; i < stops.length; i++){
            const a = stops[i-1], b = stops[i];
            if(cl <= b.offset){
                const u2 = (cl - a.offset) / (b.offset - a.offset);
                const hex = s => [parseInt(s.slice(1,3),16), parseInt(s.slice(3,5),16), parseInt(s.slice(5,7),16)];
                const [r1,g1,b1] = hex(a.color), [r2,g2,b2] = hex(b.color);
                return "#"+[r1+(r2-r1)*u2, g1+(g2-g1)*u2, b1+(b2-b1)*u2]
                    .map(v => Math.round(v).toString(16).padStart(2,"0")).join("");
            }
        }
        return stops[stops.length-1].color;
    }

    // Соединительная пунктирная линия
    const connPts = [];
    times.forEach((t, i) => {
        if(values[i] == null || isNaN(values[i])) return;
        connPts.push(`${px(t)},${py(values[i])}`);
    });
    const connectLine = connPts.length > 1
        ? `<polyline points="${connPts.join(" ")}" fill="none" stroke="${cfg.color}" stroke-width="1" stroke-opacity="0.2" stroke-dasharray="3 3"/>`
        : "";

    // Стрелки
    const step = Math.max(1, Math.floor(times.length / 80));
    let arrows = "";
    times.forEach((t, i) => {
        if(i % step !== 0) return;
        const dir = values[i];
        if(dir == null || isNaN(dir)) return;
        const spd = obs[i]?.windSpeedMs ?? null;
        const col = gradCol(spd);
        const x = px(t), y = py(dir);
        const rot = dir + 180;
        arrows += `<g transform="translate(${x},${y}) rotate(${rot})">
            <line x1="0" y1="-5" x2="0" y2="5" stroke="${col}" stroke-width="1.8" stroke-linecap="round"/>
            <polyline points="-2.5,-1 0,-5 2.5,-1" fill="none" stroke="${col}" stroke-width="1.8" stroke-linejoin="round"/>
        </g>`;
    });

    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        ${yGrid}${xGrid}${nowLine}${connectLine}${arrows}
        ${yLabels}${xLabels}
    </svg>`;

    // Тултип — мышь
    const svgEl = wrap.querySelector("svg");
    const allPts = times.map(t => ({ x: px(t) }));
    const onMove = (clientX) => {
        const rect = svgEl.getBoundingClientRect();
        const scaleX = W / rect.width;
        const mx = (clientX - rect.left) * scaleX;
        let best = 0, bestDist = Infinity;
        allPts.forEach((p, i) => {
            if(values[i] == null) return;
            const dist = Math.abs(p.x - mx);
            if(dist < bestDist){ bestDist = dist; best = i; }
        });
        histShowTooltip({ cursor:{ left: (clientX - rect.left) } }, best, data, "winddir");
    };
    svgEl.addEventListener("mousemove", e => onMove(e.clientX));
    svgEl.addEventListener("mouseleave", histHideTooltip);
    svgEl.addEventListener("touchmove", e => {
        onMove(e.touches[0].clientX);
        e.preventDefault();
    }, { passive: false });
    svgEl.addEventListener("touchend", histHideTooltip);

    _histChart = {
        destroy(){ wrap.innerHTML = ""; },
        setSize(){ if(_histData) histRenderChart_WindDir(_histData); }
    };
}

/* ── движок Chart.js (нужен CDN в pws.html) ── */
function histRenderChart_ChartJS(data, paramKey){
    const cfg  = HIST_PARAMS[paramKey];
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;

    if(_histChart){ _histChart.destroy && _histChart.destroy(); _histChart = null; }
    wrap.innerHTML = `<canvas style="width:100%;height:220px;"></canvas>`;

    const canvas = wrap.querySelector("canvas");
    const { times, values } = data;

    const labels = times.map(t => {
        const d = new Date(t * 1000);
        return d.toLocaleString("ru-RU", {day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit"});
    });

    if(typeof Chart === "undefined"){
        const errBox = document.getElementById("histError");
        if(errBox) errBox.textContent = "Загрузка Chart.js…";
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js";
        script.onload = () => {
            if(errBox) errBox.textContent = "";
            histRenderChart_ChartJS(data, paramKey);
        };
        script.onerror = () => {
            if(errBox) errBox.textContent = "Ошибка загрузки Chart.js";
            wrap.innerHTML = `<div style="color:#ff8f43;padding:20px;text-align:center;">
                Chart.js недоступен. Попробуйте вручную:<br>
                <a href="https://cdn.jsdelivr.net/npm/chart.js" target="_blank"
                   style="color:#72c8ff;font-size:11px;">cdn.jsdelivr.net/npm/chart.js</a>
            </div>`;
        };
        document.head.appendChild(script);
        return;
    }

    _histChart = new Chart(canvas, {
        type: "line",
        data: {
            labels,
            datasets: [{
                data: values.map(v => v ?? null),
                borderColor: cfg.stroke,
                backgroundColor: cfg.fill,
                borderWidth: 2,
                pointRadius: times.length < 60 ? 3 : 0,
                spanGaps: false,
                tension: 0.3,
            }]
        },
        options: {
            responsive: false,
            plugins: { legend:{ display:false }, tooltip:{
                callbacks: { label: ctx => (ctx.parsed.y ?? "-") + cfg.unit }
            }},
            scales: {
                x: { ticks:{ color:"#555", maxTicksLimit:6, maxRotation:0 }, grid:{ color:"#252525" } },
                y: { ticks:{ color:"#555", callback: v => v + cfg.unit }, grid:{ color:"#252525" } }
            }
        }
    });
}

/* ── движок ECharts ── */
function histRenderChart_ECharts(data, paramKey){
    const cfg  = HIST_PARAMS[paramKey];
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;

    if(_histChart){ _histChart.destroy && _histChart.destroy(); _histChart = null; }
    wrap.innerHTML = "";

    const { times, values } = data;
    if(!times.length){
        wrap.innerHTML = `<div style="color:#666;text-align:center;padding:30px;">Нет данных для отображения</div>`;
        return;
    }

    if(typeof echarts === "undefined"){
        const errBox = document.getElementById("histError");
        if(errBox) errBox.textContent = "Загрузка ECharts…";
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js";
        script.onload = () => {
            if(errBox) errBox.textContent = "";
            histRenderChart_ECharts(data, paramKey);
        };
        script.onerror = () => {
            if(errBox) errBox.textContent = "Ошибка загрузки ECharts";
            wrap.innerHTML = `<div style="color:#ff8f43;padding:20px;text-align:center;">
                ECharts недоступен.<br>
                <a href="https://cdn.jsdelivr.net/npm/echarts" target="_blank"
                   style="color:#72c8ff;font-size:11px;">cdn.jsdelivr.net/npm/echarts</a>
            </div>`;
        };
        document.head.appendChild(script);
        return;
    }

    const div = document.createElement("div");
    div.style.cssText = "width:100%;height:220px;";
    wrap.appendChild(div);

    const chart = echarts.init(div, null, { backgroundColor: "transparent" });

    // Извлекаем RGB из hex для rgba()
    function hexToRgb(hex){
        const r = parseInt(hex.slice(1,3),16);
        const g = parseInt(hex.slice(3,5),16);
        const b = parseInt(hex.slice(5,7),16);
        return `${r},${g},${b}`;
    }
    const rgb = hexToRgb(cfg.color);

    const seriesData = times.map((t, i) =>
        values[i] != null ? [t * 1000, values[i]] : null
    ).filter(Boolean);

    chart.setOption({
        backgroundColor: "transparent",
        animation: false,
        grid: { top: 12, right: 12, bottom: 36, left: 50, containLabel: false },
        // Встроенный тултип полностью отключён — используем histShowTooltip
        tooltip: {
            trigger: "axis",
            backgroundColor: "rgba(20,20,20,0.97)",
            borderColor: "#333",
            borderWidth: 1,
            textStyle: { color: "#eee", fontSize: 12 },
            axisPointer: {
                lineStyle: { color: "rgba(255,255,255,0.18)", width: 1 }
            },
            formatter(params){
                const p = params[0];
                if(!p) return "";
                const d = new Date(p.value[0]);
                const timeStr = d.toLocaleString("ru-RU", {
                    day:"2-digit", month:"2-digit",
                    hour:"2-digit", minute:"2-digit"
                });
                return `<div style="font-size:11px;color:#888;margin-bottom:4px;">${timeStr}</div>
                        <div style="font-size:15px;font-weight:800;color:${cfg.color};">${p.value[1]}${cfg.unit}</div>
                        <div style="font-size:11px;color:#aaa;">${cfg.label}</div>`;
            },
        },
        xAxis: {
            type: "time",
            axisLine:  { lineStyle: { color: "#333" } },
            axisTick:  { lineStyle: { color: "#333" } },
            axisLabel: {
                color: "#555", fontSize: 10,
                formatter(val){
    const d = new Date(val);
    const sameDay = new Date(times[0]*1000).getDate() === d.getDate();
    return sameDay
        ? d.toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit"})
        : d.toLocaleDateString("ru-RU", {day:"2-digit", month:"2-digit", year:"numeric"});
}
            },
            splitLine: { lineStyle: { color: "#252525" } },
        },
        yAxis: {
    type: "value",
    scale: true,
    min: v => {
        const spread = v.max - v.min;
        const pad = Math.max(spread * 0.3, 1);  // 30% от размаха, но не меньше 1
        return Math.floor(v.min - pad);
    },
    max: v => {
        const spread = v.max - v.min;
        const pad = Math.max(spread * 0.3, 1);
        return Math.ceil(v.max + pad);
    },
    axisLine:  { show: false },
    axisTick:  { show: false },
            axisLabel: {
                color: "#555", fontSize: 10,
                formatter: v => v + cfg.unit,
            },
            splitLine: { lineStyle: { color: "#252525" } },
        },
        series: [{
            type: "line",
            data: seriesData,
            smooth: 0.6,
            smoothMonotone: "x",
            symbol: "none",
            symbolSize: 4,
            lineStyle: { color: cfg.stroke, width: 2 },
            itemStyle: { color: cfg.stroke },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0,   color: `rgba(${rgb}, 0.25)` },
                    { offset: 0.7, color: `rgba(${rgb}, 0.05)` },
                    { offset: 1,   color: `rgba(${rgb}, 0)`    },
                ]),
            },
            connectNulls: false,
        }],
    });

    // Тултип через наш histShowTooltip — без дублирования


    _histChart = {
        destroy(){ chart.dispose(); wrap.innerHTML = ""; },
        setSize({ width }){ chart.resize({ width, height: 220 }); },
    };
}

/* =========================================================
   ТУЛТИП
========================================================= */
function histShowTooltip(u, idx, data, paramKey){
    const cfg = HIST_PARAMS[paramKey];
    const obs = data.obs[idx];
    if(!obs) return;

    let tip = document.getElementById("histTooltip");
    if(!tip){
        tip = document.createElement("div");
        tip.id = "histTooltip";
        tip.style.cssText = `
            position:fixed;z-index:999;pointer-events:none;
            background:rgba(20,20,20,0.97);border:1px solid #333;border-radius:10px;
            padding:10px 14px;font-size:12px;color:#eee;min-width:160px;
            box-shadow:0 4px 24px rgba(0,0,0,0.5);transition:opacity 0.1s;
        `;
        document.body.appendChild(tip);
    }

    const raw   = obs.obsTimeLocal || obs.obsTimeUtc || "";
    const d     = new Date(raw.replace(" ","T"));
    const timeStr = isNaN(d) ? raw : d.toLocaleString("ru-RU",{
        day:"2-digit", month:"2-digit",
        hour:"2-digit", minute:"2-digit"
    });

    const val = obs[cfg.field];
    const valStr = val != null ? (+val).toFixed(paramKey==="uv"?1:1) + cfg.unit : "—";

    // Дополнительные строки в зависимости от параметра
    let extra = "";
    if(paramKey === "temp"){
        if(obs.tempHigh != null && obs.tempLow != null)
            extra = `<div style="color:#888;margin-top:4px;">макс ${fmt1(obs.tempHigh,"°")} · мин ${fmt1(obs.tempLow,"°")}</div>`;
        if(obs.humidity != null)
            extra += `<div style="color:#5fe08f;">💧 ${Math.round(obs.humidity)}%</div>`;
    }
    if(paramKey === "wind" && obs.windGustMs != null)
        extra = `<div style="color:#888;margin-top:4px;">порыв ${fmt1(obs.windGustMs," м/с")}</div>`;
    if(paramKey === "pressure" && obs.temp != null)
        extra = `<div style="color:#888;margin-top:4px;">🌡 ${fmt1(obs.temp,"°C")}</div>`;

    tip.innerHTML = `
        <div style="color:#888;margin-bottom:6px;font-size:11px;">${escapeHtml(timeStr)}</div>
        <div style="font-size:16px;font-weight:800;color:${cfg.color};">${escapeHtml(valStr)}</div>
        <div style="color:#aaa;font-size:11px;">${cfg.label}</div>
        ${extra}
    `;
    tip.style.opacity = "1";

    // Позиция — следим за мышью/касанием
    const bbox  = document.getElementById("histChartWrap").getBoundingClientRect();
    const cx    = u.cursor.left + bbox.left;
    const tipW  = 180;
    const left  = cx + tipW + 20 > window.innerWidth ? cx - tipW - 12 : cx + 12;
    tip.style.left = left + "px";
    tip.style.top  = (bbox.top + 60) + "px";
}

function histHideTooltip(){
    const tip = document.getElementById("histTooltip");
    if(tip) tip.style.opacity = "0";
}

/* =========================================================
   СТАТИСТИКА
========================================================= */
function histRenderStats(data, paramKey){
    const cfg    = HIST_PARAMS[paramKey];
    const box    = document.getElementById("histStats");
    if(!box) return;

    const vals = data.values.filter(v => v != null && !isNaN(v));
    if(!vals.length){ box.innerHTML = ""; return; }

    // Специальная статистика для направления ветра
    if(paramKey === "winddir"){
        const dirs8 = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"];

        const rumbCounts = {};
        vals.forEach(v => {
            const r = dirs8[Math.round(((v % 360) + 360) % 360 / 45) % 8];
            rumbCounts[r] = (rumbCounts[r] || 0) + 1;
        });
        const dominant = Object.entries(rumbCounts).sort((a,b) => b[1]-a[1])[0] || ["-", 0];

        let sinSum = 0, cosSum = 0;
        vals.forEach(v => { sinSum += Math.sin(v * Math.PI/180); cosSum += Math.cos(v * Math.PI/180); });
        const meanDeg = ((Math.atan2(sinSum/vals.length, cosSum/vals.length) * 180/Math.PI) + 360) % 360;
        const meanRumb = dirs8[Math.round(meanDeg / 45) % 8];

        const spdVals = data.obs.map(o => o.windSpeedMs).filter(v => v != null);
        const avgSpd  = spdVals.length ? spdVals.reduce((a,b)=>a+b,0)/spdVals.length : null;
        const maxSpd  = spdVals.length ? Math.max(...spdVals) : null;

        // Те же 4 карточки что и в forecast.html
        box.innerHTML = `
        <div class="hist-stats-grid">
            <div class="hist-stat-card">
                <div class="hist-stat-label">Доминирующий</div>
                <div class="hist-stat-value" style="color:${cfg.color};">${dominant[0]}</div>
                <div class="hist-stat-time">${dominant[1]} набл.</div>
            </div>
            <div class="hist-stat-card">
                <div class="hist-stat-label">Среднее</div>
                <div class="hist-stat-value" style="color:#ccc;">${meanRumb}</div>
                <div class="hist-stat-time">${Math.round(meanDeg)}°</div>
            </div>
            <div class="hist-stat-card">
                <div class="hist-stat-label">Сред. скорость</div>
                <div class="hist-stat-value" style="color:#8bc34a;">${avgSpd != null ? avgSpd.toFixed(1) : "—"} м/с</div>
                <div class="hist-stat-time">&nbsp;</div>
            </div>
            <div class="hist-stat-card">
                <div class="hist-stat-label">Макс. скорость</div>
                <div class="hist-stat-value" style="color:#ff9f5c;">${maxSpd != null ? maxSpd.toFixed(1) : "—"} м/с</div>
                <div class="hist-stat-time">&nbsp;</div>
            </div>
        </div>`;
        return;
    }

    // Специальная статистика для осадков
    if(paramKey === "precip"){
        // Норма осадков Одесса, ст. 33837 (pogodaiklimat.ru), мм по месяцам
        const ODESSA_PRECIP_NORM = [43, 35, 34, 28, 39, 48, 45, 40, 42, 37, 39, 36];

        const isDaily = data.obs.some(o => o._daily);

        // Сумма за период
        let totalSum = null;
        if(isDaily){
            totalSum = data.obs.map(o => o.precip ?? 0).reduce((a,b) => a+b, 0);
        } else {
            const lastTotal = [...data.obs.map(o => o.precip ?? null)].reverse().find(v => v != null);
            totalSum = lastTotal ?? 0;
        }

        // Шаг между замерами в минутах
        const stepMin = data.obs.length > 1 ? (() => {
            const t1 = new Date((data.obs[0].obsTimeLocal||"").replace(" ","T"));
            const t2 = new Date((data.obs[1].obsTimeLocal||"").replace(" ","T"));
            return Math.round(Math.abs(t2 - t1) / 60000) || 5;
        })() : 5;
        const stepHours = stepMin / 60;

        // Вычисляем precipRate из разницы соседних precip
        const computedRates = [];
        for(let i = 1; i < data.obs.length; i++){
            const diff = (data.obs[i].precip ?? 0) - (data.obs[i-1].precip ?? 0);
            computedRates.push(diff > 0 ? Math.round(diff / stepHours * 10) / 10 : 0);
        }

        // Пик интенсивности + время
        let peakRate = null, peakTimeStr = "";
        computedRates.forEach((r, i) => {
            if(r > (peakRate ?? 0)){
                peakRate = r;
                const o = data.obs[i + 1];
                if(o){
                    const d = new Date((o.obsTimeLocal||"").replace(" ","T"));
                    peakTimeStr = isNaN(d) ? "" : d.toLocaleString("ru-RU",{
                        day:"2-digit", month:"2-digit",
                        hour:"2-digit", minute:"2-digit"
                    });
                }
            }
        });

        // Продолжительность
        const wetCount = computedRates.filter(v => v > 0).length;
        const durMin = wetCount * stepMin;
        let durStr = "—";
        if(isDaily){
            const wetDays = data.obs.filter(o => (o.precip ?? 0) > 0).length;
            durStr = wetDays + " д.";
        } else if(durMin > 0){
            durStr = durMin >= 60
                ? Math.floor(durMin/60) + " ч " + (durMin % 60 ? (durMin % 60) + " мин" : "")
                : durMin + " мин";
        }

        // % от нормы — только если период в пределах одного месяца
        let normCard = "";
        const months = [...new Set(data.obs.map(o => {
            const d = new Date((o.obsTimeLocal||"").replace(" ","T"));
            return isNaN(d) ? null : d.getMonth();
        }).filter(m => m !== null))];

        if(months.length === 1){
            const norm = ODESSA_PRECIP_NORM[months[0]];
            const pct  = totalSum != null ? Math.round(totalSum / norm * 100) : null;
            normCard = `
            <div class="hist-stat-card">
                <div class="hist-stat-label">% от нормы</div>
                <div class="hist-stat-value" style="color:${pct != null && pct >= 100 ? '#5fe08f' : cfg.color};">
                    ${pct != null ? pct + "%" : "—"}
                </div>
                <div class="hist-stat-time">норма ${norm} мм</div>
            </div>`;
        }

        box.innerHTML = `
        <div class="hist-stats-grid${normCard ? "" : " hist-stats-grid-3"}">
            <div class="hist-stat-card">
                <div class="hist-stat-label">Сумма за период</div>
                <div class="hist-stat-value" style="color:${cfg.color};">${totalSum != null ? totalSum.toFixed(1) : "—"} мм</div>
                <div class="hist-stat-time">${data.obs.length} замеров</div>
            </div>
            <div class="hist-stat-card">
                <div class="hist-stat-label">Пик интенсивности</div>
                <div class="hist-stat-value" style="color:${cfg.color};">${peakRate != null ? peakRate.toFixed(1) : "—"} мм/ч</div>
                <div class="hist-stat-time">${peakTimeStr || "&nbsp;"}</div>
            </div>
            <div class="hist-stat-card">
                <div class="hist-stat-label">Продолжительность</div>
                <div class="hist-stat-value" style="color:#ccc;">${durStr}</div>
                <div class="hist-stat-time">&nbsp;</div>
            </div>
            ${normCard}
        </div>`;
        return;
    }

    const vMin  = Math.min(...vals);
    const vMax  = Math.max(...vals);
    const vAvg  = vals.reduce((a,b)=>a+b,0) / vals.length;
    const vLast = vals[vals.length-1];

    // Мин/макс время
    const iMin = data.values.indexOf(vMin);
    const iMax = data.values.indexOf(vMax);
    const tFmt = i => {
        const o = data.obs[i];
        if(!o) return "";
        const raw = o.obsTimeLocal || o.obsTimeUtc || "";
        const d = new Date(raw.replace(" ","T"));
        if(isNaN(d)) return "";
        return d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    };

    const u1 = cfg.unit;

    const engine = (typeof HIST_ENGINE !== "undefined") ? HIST_ENGINE : "uplot";
    const engineLabel = { uplot: "uPlot", svg: "SVG", chartjs: "Chart.js", echarts: "ECharts" }[engine] || engine;

    box.innerHTML = `
    <div class="hist-stats-grid">
        <div class="hist-stat-card">
            <div class="hist-stat-label">Минимум</div>
            <div class="hist-stat-value" style="color:${cfg.color};">${fmt1(vMin,u1)}</div>
            <div class="hist-stat-time">${tFmt(iMin)}</div>
        </div>
        <div class="hist-stat-card">
            <div class="hist-stat-label">Максимум</div>
            <div class="hist-stat-value" style="color:${cfg.color};">${fmt1(vMax,u1)}</div>
            <div class="hist-stat-time">${tFmt(iMax)}</div>
        </div>
        <div class="hist-stat-card">
            <div class="hist-stat-label">Среднее</div>
            <div class="hist-stat-value" style="color:#ccc;">${fmt1(vAvg,u1)}</div>
            <div class="hist-stat-time">${vals.length} значений</div>
        </div>
        <div class="hist-stat-card">
            <div class="hist-stat-label">Последнее</div>
            <div class="hist-stat-value" style="color:#ccc;">${fmt1(vLast,u1)}</div>
            <div class="hist-stat-time">${tFmt(data.values.lastIndexOf(vLast))}</div>
        </div>
    </div>
    <div style="margin-top:6px;text-align:right;font-size:10px;color:#333;">
        движок: ${engineLabel}
    </div>`;
}

/* =========================================================
   ЗАГРУЗКА + РЕНДЕР
========================================================= */
async function histLoad(){
    if(_histLoading) return;
    _histLoading = true;

    const stationId = _currentId || (typeof PWS_STATIONS !== "undefined" ? PWS_STATIONS[0].id : "IODESS44");
    const errBox    = document.getElementById("histError");
    const loader    = document.getElementById("histLoader");

    if(loader) loader.style.display = "block";
    if(errBox) errBox.textContent   = "";
    histHideTooltip();

    try {
        const obs  = await histFetch(stationId, _histPeriod);
        console.log("obs[0]:", JSON.stringify(obs[0]));
console.log("obs sample precip fields:", obs.slice(0,5).map(o => ({ precip: o.precip, precipRate: o.precipRate })));
        _histData  = histPrepare(obs, _histParam);
        histRenderChart(_histData, _histParam);
        histRenderStats(_histData, _histParam);
    } catch(e){
        if(errBox) errBox.textContent = "Ошибка: " + (e?.message || e);
        const wrap = document.getElementById("histChartWrap");
        if(wrap) wrap.innerHTML = "";
    } finally {
        if(loader) loader.style.display = "none";
        _histLoading = false;
    }
}

/* =========================================================
   ПЕРЕКЛЮЧЕНИЕ ПАРАМЕТРА (без перезагрузки данных)
========================================================= */
function histSwitchParam(paramKey){
    _histParam = paramKey;
    document.querySelectorAll(".hist-param-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.param === paramKey);
    });
    if(_histData){
        // Перепарсиваем из тех же obs с новым полем
        _histData = histPrepare(_histData.obs, _histParam);
        histRenderChart(_histData, _histParam);
        histRenderStats(_histData, _histParam);
    }
}

/* =========================================================
   ПЕРЕКЛЮЧЕНИЕ ПЕРИОДА
========================================================= */
function histSwitchPeriod(periodId){
    _histPeriod = periodId;
    document.querySelectorAll(".hist-period-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.period === periodId);
    });
    const customRow = document.getElementById("histCustomRow");
    if(customRow) customRow.style.display = periodId === "custom" ? "flex" : "none";
    histLoad();
}

/* =========================================================
   RESIZE
========================================================= */
function histResize(){
    if(!_histChart) return;
    const wrap = document.getElementById("histChartWrap");
    if(!wrap) return;
    _histChart.setSize({ width: wrap.clientWidth, height: 220 });
}

/* =========================================================
   ИНИЦИАЛИЗАЦИЯ СЕКЦИИ
========================================================= */
function initHistorySection(){
    const section = document.getElementById("histSection");
    if(!section) return;

    // Инициализируем даты для custom периода
    const today  = new Date();
    const week   = new Date(); week.setDate(week.getDate() - 6);
    const toISO  = d => d.toISOString().slice(0,10);

    section.innerHTML = `
    <!-- Заголовок -->
    <div class="cardTitle" style="margin-bottom:12px;">
        📈 История наблюдений
    </div>

    <!-- Переключатели параметра -->
    <div class="hist-param-row">
        ${Object.entries(HIST_PARAMS).map(([k,v]) => `
            <button class="hist-param-btn${k===_histParam?' active':''}"
                    data-param="${k}"
                    style="--c:${v.color}"
                    onclick="histSwitchParam('${k}')">
                ${v.label}
            </button>
        `).join("")}
    </div>

    <!-- Переключатели периода -->
    <div class="hist-period-row">
        ${HIST_PERIODS.map(p => `
            <button class="hist-period-btn${p.id===_histPeriod?' active':''}"
                    data-period="${p.id}"
                    onclick="histSwitchPeriod('${p.id}')">
                ${p.label}
            </button>
        `).join("")}
    </div>

    <!-- Выбор дат для custom -->
    <div id="histCustomRow" style="display:none;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
        <input id="histDateStart" type="date" value="${toISO(week)}"
               style="background:#232323;border:1px solid #333;border-radius:8px;color:#eee;padding:6px 10px;font-size:13px;">
        <span style="color:#555;">—</span>
        <input id="histDateEnd" type="date" value="${toISO(today)}"
               style="background:#232323;border:1px solid #333;border-radius:8px;color:#eee;padding:6px 10px;font-size:13px;">
        <button onclick="histLoad()"
                style="width:auto;padding:6px 14px;font-size:12px;background:#252525;color:#aaa;">
            Загрузить
        </button>
    </div>

    <!-- Лоадер и ошибка -->
    <div id="histLoader" style="display:none;text-align:center;padding:10px;color:#666;font-size:12px;">
        Загрузка данных…
    </div>
    <div id="histError" style="color:#ff8f43;font-size:12px;min-height:16px;margin-bottom:4px;"></div>

    <!-- График -->
    <div id="histChartWrap" style="width:100%;overflow:hidden;border-radius:10px;background:#161616;min-height:60px;"></div>

    <!-- Статистика -->
    <div id="histStats" style="margin-top:12px;"></div>
    `;

    window.addEventListener("resize", histResize);

    // Первичная загрузка
    histLoad();
}
