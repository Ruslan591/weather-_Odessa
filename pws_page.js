/* =========================================================
   PWS_PAGE.JS — страница pws.html
   Одна станция на экране, выбор через select
   Коррекция давления сохраняется в localStorage
   Зависит от: utils.js, indicators.js, pws.js (WU_KEYS)
========================================================= */

const PWS_STATIONS = [
    { id:"IODESA137", name:"пос. Котовского"  },
    { id:"IODESA138", name:"Центр"           },
    { id:"IODESA139", name:"Чудо Город"          },
    { id:"IODESS41", name:"Судостроительная"          },
    { id:"IODESS44", name:"Аркадия"          },
    { id:"IODESS16", name:"Таирова"          },
    { id:"IODESS31", name:"Савиньон"        },
    { id:"IODESS37", name:"Застава"          },
    { id:"IKRASN91", name:"пос.Степовое"  },
];

const PWS_REFRESH  = 15;           // сек
const CALIB_KEY    = "pwsCalib2";  // localStorage: { stationId: offset }
const SEL_KEY      = "pwsLastStation"; // запомнить последнюю выбранную

let _timer       = null;
let _currentId   = null;
let _lastData    = null;

/* ≠≠============================================≠≠=========
    функция для плавности шторки
===========================≠=======≠===================== */  
   function toggleDetails(e){
    e.preventDefault();
    const det = e.currentTarget.closest("details");
    if(det.open){
        // Закрываем: сначала анимация, потом убираем open
        det.querySelector(".details-body").style.gridTemplateRows = "0fr";
        setTimeout(() => det.removeAttribute("open"), 350);
    } else {
        // Открываем: сначала open, потом анимация
        det.setAttribute("open", "");
        requestAnimationFrame(() => {
            det.querySelector(".details-body").style.gridTemplateRows = "1fr";
        });
    }
} 
    
/* =========================================================
   КОРРЕКЦИЯ (сохраняется в localStorage)
========================================================= */
function getOffset(id){
    try{ return parseFloat(JSON.parse(localStorage.getItem(CALIB_KEY)||"{}")[id] ?? 0) || 0; }
    catch(e){ return 0; }
}

function setOffset(id, val){
    const c = JSON.parse(localStorage.getItem(CALIB_KEY)||"{}");
    c[id] = val;
    localStorage.setItem(CALIB_KEY, JSON.stringify(c));
}

function applyCalib(){
    const inp = document.getElementById("calibInput");
    if(!inp) return;
    const val = parseFloat(inp.value);
    if(isNaN(val)){ inp.style.outline="1px solid #ff6b6b"; return; }
    inp.style.outline = "";
    setOffset(_currentId, val);
    if(_lastData) renderPWSStation(_lastData);
    if(_histParam === "pressure") histLoad(); // ← добавить
}

function resetCalib(){
    setOffset(_currentId, 0);
    const inp = document.getElementById("calibInput");
    if(inp) inp.value = "0";
    if(_lastData) renderPWSStation(_lastData);
    if(_histParam === "pressure") histLoad(); // ← добавить
}

function calibBySynop(){
    // Читаем сохранённые данные SYNOP
    let synopData;
    try { synopData = JSON.parse(localStorage.getItem("synopLastPressure")); }
    catch(e){ synopData = null; }

    const msgEl = document.getElementById("calibMsg");

    if(!synopData || synopData.pressure == null){
        if(msgEl) { msgEl.textContent = "Нет данных SYNOP. Обновите сводку на странице SYNOP."; msgEl.style.color = "#ff8f43"; }
        return;
    }

    // Проверяем актуальность: SYNOP выходит каждые 6 часов
    // Если с момента сохранения прошло > 3 часов — данные могут быть устаревшими
    const ageMs  = Date.now() - synopData.ts;
    const ageMin = Math.round(ageMs / 60000);
    if(ageMin > 180){
        if(msgEl){
            msgEl.textContent = `Данные SYNOP утратили актуальность (${ageMin} мин назад). Обновите сводку.`;
            msgEl.style.color = "#ff8f43";
        }
        return;
    }

    // Получаем текущее сырое давление PWS
    const p = _lastData;
    if(!p || p.error || p.pressure == null){
        if(msgEl){ msgEl.textContent = "Нет данных PWS для коррекции."; msgEl.style.color = "#ff8f43"; }
        return;
    }

    // Вычисляем разницу: сколько нужно добавить к PWS чтобы совпало с SYNOP
    const diff = Math.round((synopData.pressure - p.pressure) * 10) / 10;
    setOffset(_currentId, diff);

    const inp = document.getElementById("calibInput");
    if(inp) inp.value = diff;

    if(msgEl){
        msgEl.textContent = `Коррекция применена: ${diff > 0 ? "+" : ""}${diff} гПа (SYNOP ${synopData.pressure} гПа, ${ageMin} мин назад)`;
        msgEl.style.color = "#5fe08f";
    }

    if(_lastData) renderPWSStation(_lastData);
}

/* =========================================================
    передаем цвет температуры
===================≠===================================== */
function tempColorExact(temp){
    if(temp == null) return "#aaa";
    const stops = [
        {offset:0,    color:"#3a8fff"},
        {offset:0.25, color:"#9dd6ff"},
        {offset:0.5,  color:"#5fe08f"},
        {offset:0.75, color:"#ffd84d"},
        {offset:1,    color:"#ff6b3a"},
    ];
    const t = (Math.max(-20, Math.min(40, temp)) + 20) / 60;
    return gradientColor(stops, t);
}

/* =========================================================
   ЗАГРУЗКА
========================================================= */
async function fetchStation(id){
    const url =
        `https://api.weather.com/v2/pws/observations/current` +
        `?stationId=${encodeURIComponent(id)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${WU_KEYS[0]}`;
    const ctrl  = new AbortController();
    const timer = setTimeout(()=>ctrl.abort(), 10000);
    try {
        const r = await fetch(url, {signal:ctrl.signal, cache:"no-store"});
        if(!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        if(data?.errors?.length) throw new Error(data.errors[0]?.error?.message || "Ошибка API");
        if(!data?.observations?.length) throw new Error("Нет данных");
        return parsePWSOne(data.observations[0]);
    } finally { clearTimeout(timer); }
}

/* =========================================================
   РЕНДЕР
========================================================= */
function timeAgeColor(obsTimeLocal){
    if(!obsTimeLocal) return "#666";
    const d = new Date(obsTimeLocal.replace(" ", "T"));
    if(isNaN(d)) return "#666";
    const ageMin = (Date.now() - d.getTime()) / 60000;
    if(ageMin < 20)  return "#5fe08f";  // свежие — зелёный
    if(ageMin < 60)  return "#ffd166";  // до часа — жёлтый
    if(ageMin < 180) return "#ff9f43";  // до 3 часов — оранжевый
    return "#ff6b6b";                   // старше 3 часов — красный
}

function renderPWSStation(p){
    _lastData = p;
    const box = document.getElementById("pwsContent");
    if(!box) return;

    const off = getOffset(_currentId);
    const cfg = PWS_STATIONS.find(s=>s.id===_currentId);

    // Если ошибка или нет данных
    if(!p || p.error){
        box.innerHTML = `<div class="pws-station-card">
            <div style="color:#888;padding:20px 0;text-align:center;">
                ${p?.error === "offline" ? "📡 Станция недоступна" : "⚠️ " + escapeHtml(p?.error||"Нет данных")}
            </div>
        </div>`;
        return;
    }

    const timeStr = p.obsTimeLocal
        ? (()=>{const d=new Date(p.obsTimeLocal.replace(" ","T")); return isNaN(d)?p.obsTimeLocal:d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"});})()
        : "-";

    const pCorr = p.pressure != null ? Math.round((p.pressure + off)*10)/10 : null;
    const feelsLike =
        p.temp!=null&&p.temp>=27&&p.heatIndex!=null ? p.heatIndex :
        p.temp!=null&&p.temp<=10&&p.windChill!=null  ? p.windChill : p.temp;

    // Данные — только те что есть
    const rows = [
        p.dewpt       != null ? ["Точка росы",         fmt1(p.dewpt,"°C")]            : null,
        p.windGustMs  != null && p.windGustMs>0
                              ? ["Порывы",              fmt1(p.windGustMs," м/с")]     : null,
        p.precipRate  != null && p.precipRate>0
                              ? ["Интенсивность осадков", fmt1(p.precipRate," мм/ч")] : null,
        p.precipTotal != null && p.precipTotal>0
                              ? ["Осадки",              fmt1(p.precipTotal," мм")]     : null,
        p.solarRad    != null ? ["Солнечная радиация",  fmt0(p.solarRad," Вт/м²")]    : null,
        p.uv          != null ? ["УФ-индекс",           String(p.uv)]                 : null,
    ].filter(Boolean);

    // Под шторку: техническая информация о станции
    const rowsAbout = [
        p.elev        != null ? ["Высота над уровнем моря", fmt0(p.elev," м")]        : null,
        p.softwareType!= null ? ["ПО станции",          escapeHtml(p.softwareType)]   : null,
        p.lat         != null ? ["Координаты",          `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`] : null,
    ].filter(Boolean);

    box.innerHTML = `
    <div class="pws-station-card">
        <div class="pws-station-header">
            <div>
                <div class="cardTitle" style="margin-bottom:2px;">${escapeHtml(cfg?.name||_currentId)}</div>
                <div style="
    display:inline-block;
    margin-top:4px;
    padding:3px 10px;
    border-radius:20px;
    font-size:13px;
    font-weight:600;
    background:${timeAgeColor(p.obsTimeLocal)}22;
    border:1px solid ${timeAgeColor(p.obsTimeLocal)}66;
    color:${timeAgeColor(p.obsTimeLocal)};
">
    ${escapeHtml(timeStr)}
    ${(()=>{const d=new Date((p.obsTimeLocal||"").replace(" ","T")); const m=Math.round((Date.now()-d)/60000); return isNaN(m)?"":`· ${m} мин назад`;})()}
</div>
            </div>
            <div style="font-size:28px;font-weight:800;color:${tempColorExact(p.temp)};">${fmt1(p.temp,"°C")}</div>
        </div>

        <!-- Индикаторы 2×2 -->
        <div class="ind-grid-2x2">
            ${tempIndicatorSvg(p.temp, feelsLike)}
            ${humidityIndicatorSvg(p.humidity)}
            ${windIndicatorSvg({windSpeed: p.windSpeedMs, windGustMs: p.windGustMs, windDir: p.windDir})}
            ${pressureIndicatorSvg({seaPressure: pCorr, tendencyCode:null, tendencyValue:null})}
            ${p.solarRad != null || p.uv != null ? solarIndicatorSvg(p.solarRad) : ""}
            ${p.uv != null || p.solarRad != null ? uvIndicatorSvg(p.uv) : ""}
            ${p.precipRate  != null ? precipRateIndicatorSvg(p.precipRate)   : ""}
            ${p.precipTotal != null ? precipTotalIndicatorSvg(p.precipTotal) : ""}
        </div>

        <!-- Дополнительные данные -->
        ${rows.length ? `<div class="pws-fields">${rows.map(([k,v])=>`<div class="districtLine"><span>${k}</span><span>${v}</span></div>`).join("")}</div>` : ""}

        <!-- О станции (шторка) -->
        ${rowsAbout.length ? `<details style="margin-top:8px;">
            <summary onclick="toggleDetails(event)">О станции</summary>
            <div class="details-body"><div>
                <div class="pws-fields" style="margin-top:8px;">${rowsAbout.map(([k,v])=>`<div class="districtLine"><span>${k}</span><span>${v}</span></div>`).join("")}</div>
            </div></div>
        </details>` : ""}

        <!-- Коррекция давления -->
        <div class="pws-calib">
            <span class="small" style="color:#666;">Коррекция давления:</span>
            <input id="calibInput" type="number" step="0.1" value="${off}"
                   style="width:65px;background:#232323;border:1px solid #333;border-radius:6px;
                          color:#eee;font-size:12px;padding:4px 8px;text-align:center;">
            <span class="small" style="color:#555;">гПа</span>
            <button onclick="applyCalib()"
                    style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#ccc;">✓</button>
            <button onclick="calibBySynop()"
                    style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#72c8ff;">По SYNOP</button>
            <button onclick="resetCalib()"
                    style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#888;">Сброс</button>
        </div>
        <div id="calibMsg" style="font-size:11px;margin-top:4px;min-height:14px;padding:0 2px;">
            ${off !== 0 ? `<span style="color:#72c8ff;">поправка: ${off>0?"+":""}${off} гПа</span>` : ""}
        </div>
    </div>`;
}

/* =========================================================
   ВЫБОР СТАНЦИИ
========================================================= */
function buildSelect(){
    const wrap = document.getElementById("stationSelectWrap");
    if(!wrap) return;

    // Восстановить последний выбор
    const saved = localStorage.getItem(SEL_KEY);
    const def   = PWS_STATIONS.find(s=>s.id===saved) ? saved : PWS_STATIONS[0].id;
    _currentId  = def;

    wrap.innerHTML = `
    <div class="station-select-wrap">
        <select id="stationSelect" onchange="onStationChange(this.value)">
            ${PWS_STATIONS.map(s=>`<option value="${s.id}"${s.id===def?" selected":""}>${escapeHtml(s.name)} — ${s.id}</option>`).join("")}
        </select>
    </div>`;
}

function onStationChange(id){
    _currentId = id;
    localStorage.setItem(SEL_KEY, id);
    _lastData  = null;
    document.getElementById("pwsContent").innerHTML = `<div style="padding:20px;color:#888;text-align:center;">Загрузка...</div>`;
    loadAndRender();
    histLoad(); // ← добавить эту строку
}

/* =========================================================
   ЗАГРУЗКА И РЕНДЕР
========================================================= */
async function loadAndRender(){
    try {
        const p = await fetchStation(_currentId);
        renderPWSStation(p);
    } catch(e){
        renderPWSStation({ error: e.message });
    }
    // Обновляем время в шапке
    const ts = document.getElementById("pwsUpdateTime");
    if(ts) ts.textContent = new Date().toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
}

function startRefresh(){
    if(_timer) clearInterval(_timer);
    _timer = setInterval(loadAndRender, PWS_REFRESH * 1000);
}

/* =========================================================
   ИНИЦИАЛИЗАЦИЯ
========================================================= */
async function initPWSPage(){
    buildSelect();

    // Шапка с временем обновления
    const box = document.getElementById("pwsContent");
    if(box) box.innerHTML = `<div style="padding:20px;color:#888;text-align:center;">Загрузка...</div>`;

    await loadAndRender();
    startRefresh();
}

initPWSPage();
