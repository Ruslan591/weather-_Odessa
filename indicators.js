/* =========================================================
   INDICATORS.JS — SVG индикаторы (ветер, давление, влажность, температура)
   Единый viewBox: 0 0 160 110
   Зависит от: utils.js
========================================================= */

/* =========================================================
   ИНТЕРПОЛЯЦИЯ ЦВЕТА ПО ПОЗИЦИИ НА ГРАДИЕНТЕ
   stops: [{offset: 0..1, color: "#rrggbb"}, ...]
   t: 0..1 — позиция на шкале
========================================================= */
function gradientColor(stops, t){
    t = Math.max(0, Math.min(1, t));
    for(let i = 1; i < stops.length; i++){
        const a = stops[i-1], b = stops[i];
        if(t <= b.offset){
            const u = (t - a.offset) / (b.offset - a.offset);
            return lerpHex(a.color, b.color, u);
        }
    }
    return stops[stops.length-1].color;
}

function lerpHex(c1, c2, t){
    const h = s => [
        parseInt(s.slice(1,3),16),
        parseInt(s.slice(3,5),16),
        parseInt(s.slice(5,7),16)
    ];
    const [r1,g1,b1] = h(c1), [r2,g2,b2] = h(c2);
    const r = Math.round(r1 + (r2-r1)*t);
    const g = Math.round(g1 + (g2-g1)*t);
    const b = Math.round(b1 + (b2-b1)*t);
    return "#" + [r,g,b].map(v=>v.toString(16).padStart(2,"0")).join("");
}

const IND_VB  = "0 0 160 110";  // единый viewBox
const IND_W   = 200;             // ширина в px (масштабируется CSS)
const IND_H   = 138;             // высота в px

/* ------ Полноэкранный просмотр при тапе ------ */
function indExpand(cardEl){
    if(document.getElementById("indOverlay")) return;

    // Определяем тип индикатора по заголовку
    const titleText = cardEl.querySelector(".ind-title")?.textContent?.trim() || "";
    const svgOrig   = cardEl.querySelector("svg");
    if(!svgOrig) return;

    const ov = document.createElement("div");
    ov.id = "indOverlay";
    ov.style.cssText = "position:fixed;inset:0;z-index:9999;background:rgba(10,10,10,0.96);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;box-sizing:border-box;cursor:pointer;";

    const titleEl = document.createElement("div");
    titleEl.style.cssText = "font-size:14px;color:#aaa;margin-bottom:16px;";
    titleEl.textContent = titleText;

    const svgWrap = document.createElement("div");

    const hint = document.createElement("div");
    hint.style.cssText = "margin-top:32px;font-size:12px;color:#444;";
    hint.textContent = "нажми чтобы закрыть";

    ov.appendChild(titleEl);
    ov.appendChild(svgWrap);
    ov.appendChild(hint);

    function buildSvg(){
        // Получаем свежие данные через глобальную переменную _lastData
        const d = (typeof _lastData !== "undefined") ? _lastData : null;
        if(!d) return null;

        let html = "";
        if(titleText.includes("Ветер")){
            const tmp = document.createElement("div");
            tmp.innerHTML = windIndicatorSvg({
        windSpeed: d.windSpeedMs ?? d.windSpeed ?? null,
        windGust:  d.windGustMs  ?? d.windGust  ?? null,
        windDir:   d.windDir ?? null
    });
            html = tmp.querySelector("svg")?.outerHTML || "";
        } else if(titleText.includes("Давление")){
            const off = (typeof getOffset === "function" && typeof _currentId !== "undefined")
                ? getOffset(_currentId) : 0;
            const pCorr = d.pressure != null ? Math.round((d.pressure + off)*10)/10 : null;
            const tmp = document.createElement("div");
            tmp.innerHTML = pressureIndicatorSvg({seaPressure: pCorr, tendencyCode: d.tendencyCode ?? null, tendencyValue: d.tendencyValue ?? null});
            html = tmp.querySelector("svg")?.outerHTML || "";
        } else if(titleText.includes("Влажность")){
            const tmp = document.createElement("div");
            tmp.innerHTML = humidityIndicatorSvg(d.humidity);
            html = tmp.querySelector("svg")?.outerHTML || "";
        } else if(titleText.includes("Температура")){
            const feelsLike =
                d.temp!=null&&d.temp>=27&&d.heatIndex!=null ? d.heatIndex :
                d.temp!=null&&d.temp<=10&&d.windChill!=null  ? d.windChill : d.temp;
            const tmp = document.createElement("div");
            tmp.innerHTML = tempIndicatorSvg(d.temp, feelsLike);
            html = tmp.querySelector("svg")?.outerHTML || "";
        } else {
            // Для SYNOP — просто клонируем текущий SVG из оригинальной карточки
            return svgOrig.cloneNode(true);
        }

        if(!html) return svgOrig.cloneNode(true);
        const wrap = document.createElement("div");
        wrap.innerHTML = html;
        return wrap.querySelector("svg");
    }

    function syncSvg(){
        const svg = buildSvg();
        if(!svg) return;
        svg.style.width  = "min(85vw, 380px)";
        svg.style.height = "auto";
        svgWrap.innerHTML = "";
        svgWrap.appendChild(svg);
    }

    syncSvg();
    const timer = setInterval(syncSvg, 2000);

    ov.onclick = () => { clearInterval(timer); ov.remove(); };
    document.body.appendChild(ov);
}

/* =========================================================
   ВЕТЕР
========================================================= */
function windIndicatorSvg(d){
    const W_STOPS = [
        {offset:0,    color:"#7ec8ff"},
        {offset:0.13, color:"#67d7a7"},
        {offset:0.36, color:"#ffd166"},
        {offset:0.57, color:"#ff9f5c"},
        {offset:1,    color:"#ff6b6b"},
    ];
    const vMax = 25;
    const gust = d.windGust ?? d.windGustMs ?? null;

    const color     = d.windSpeed != null ? gradientColor(W_STOPS, Math.min(d.windSpeed, vMax) / vMax) : "rgba(255,255,255,0.14)";
    const colorGust = gust        != null ? gradientColor(W_STOPS, Math.min(Math.max(gust, (d.windSpeed ?? 0) + 3), vMax) / vMax) : null;
    const dir = d.windDir ?? 0;

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Ветер</div>
        <svg viewBox="0 0 160 160" width="${IND_W}" height="${IND_W}" aria-label="Ветер">
            <!-- Основные 8 румбов (С,СВ,В,ЮВ,Ю,ЮЗ,З,СЗ) -->
            <line x1="80.0" y1="13.0" x2="80.0" y2="20.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="120.3" y1="29.7" x2="115.4" y2="34.6" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="137.0" y1="70.0" x2="130.0" y2="70.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="120.3" y1="110.3" x2="115.4" y2="105.4" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="80.0" y1="127.0" x2="80.0" y2="120.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="39.7" y1="110.3" x2="44.6" y2="105.4" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="23.0" y1="70.0" x2="30.0" y2="70.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <line x1="39.7" y1="29.7" x2="44.6" y2="34.6" stroke="currentColor" stroke-opacity="0.55" stroke-width="2.2" stroke-linecap="round"/>
            <!-- Промежуточные 8 румбов -->
            <line x1="101.8" y1="17.3" x2="100.3" y2="21.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="132.7" y1="48.2" x2="129.0" y2="49.7" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="132.7" y1="91.8" x2="129.0" y2="90.3" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="101.8" y1="122.7" x2="100.3" y2="119.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="58.2" y1="122.7" x2="59.7" y2="119.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="27.3" y1="91.8" x2="31.0" y2="90.3" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="27.3" y1="48.2" x2="31.0" y2="49.7" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <line x1="58.2" y1="17.3" x2="59.7" y2="21.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.4" stroke-linecap="round"/>
            <!-- Стороны света -->
            <text x="80"  y="10"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">С</text>
            <text x="143" y="73"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">В</text>
            <text x="80"  y="137" text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">Ю</text>
            <text x="16"  y="73"  text-anchor="middle" font-size="10" fill="currentColor" fill-opacity="0.8">З</text>
            <!-- Кольцо -->
            <circle cx="80" cy="70" r="43" fill="none" stroke="${color}" stroke-opacity="0.75" stroke-width="3.5"/>
            <!-- Стрелка -->
            <g style="transform-origin:80px 70px;transform:rotate(${dir + 180}deg);transition:transform 0.8s cubic-bezier(0.34,1.56,0.64,1);">
                <polygon points="80,95 76,114.5 84,114.5" fill="currentColor" opacity="0.85"/>
            </g>
            <defs>
                <linearGradient id="wValGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${color}"/>
                    <stop offset="100%" stop-color="${color}" stop-opacity="0.5"/>
                </linearGradient>
                ${colorGust ? `
                <linearGradient id="wGustGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${colorGust}"/>
                    <stop offset="100%" stop-color="${colorGust}" stop-opacity="0.5"/>
                </linearGradient>` : ""}
            </defs>
            <!-- Значение -->
            <text x="80" y="73.5" text-anchor="middle" font-size="22" font-weight="800" fill="url(#wValGrad)">
                ${d.windSpeed ?? "-"}
            </text>
            <text x="80" y="52" text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.65">м/с</text>
            ${gust != null ? `
            <text x="80" y="100" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.40">порывы</text>
            <text x="80" y="88" text-anchor="middle" font-size="13" font-weight="700" fill="url(#wGustGrad)">
                ${fmt1(gust,"")}
            </text>` : ""}
            <text x="80" y="155" text-anchor="middle" font-size="12" fill="currentColor" fill-opacity="0.65">
            ${escapeHtml(degToText(d.windDir))}${d.windDir != null ? ` · ${d.windDir}°` : ""}</text>
        </svg>
    </div>`;
}

/* =========================================================
   ДАВЛЕНИЕ
========================================================= */
function pressureIndicatorSvg(d){
    const pVal = d.seaPressure;
    const pMin = 980, pMax = 1040;
    const pC   = pVal != null ? Math.max(pMin, Math.min(pMax, pVal)) : null;
    const angle = pC != null ? (pC - 1010) / 30 * 90 : 0;

    // Градиент дуги давления: 980=синий, 1000=голубой, 1015=зелёный, 1030=жёлтый, 1040=оранжевый
const P_STOPS = [
    {offset:0,    color:"#3a8fff"},
    {offset:0.33, color:"#72c8ff"},
    {offset:0.55, color:"#5fe08f"},
    {offset:0.75, color:"#c8e05f"},
    {offset:0.92, color:"#ffb347"},
    {offset:1,    color:"#ff6b3a"},
];
const pT  = pVal != null ? (Math.max(980, Math.min(1040, pVal)) - 980) / 60 : null;
const vc  = pT != null ? gradientColor(P_STOPS, pT) : "#aaa";

    const trendPaths = {
        "0":"M0,10 L12,8 L24,6 L36,4 L48,2",
        "1":"M0,11 L12,9 L24,7 L36,4 L48,1",
        "2":"M0,10 L12,7 L24,4 L36,3 L48,3",
        "3":"M0,2 L12,4 L24,7 L36,9 L48,11",
        "4":"M0,6 L12,6 L24,6 L36,6 L48,6",
        "5":"M0,9 L12,8 L24,7 L36,6 L48,6",
        "6":"M0,2 L12,5 L24,8 L36,10 L48,11",
        "7":"M0,2 L12,4 L24,7 L36,9 L48,11",
        "8":"M0,5 L12,5 L24,6 L36,9 L48,11"
    };
    const tp = d.tendencyCode != null ? (trendPaths[String(d.tendencyCode)] || null) : null;
    const ts = d.tendencyValue != null
        ? (d.tendencyValue > 0 ? "+" : "") + d.tendencyValue.toFixed(1) + " гПа" : "";

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Давление</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Давление" style="overflow:visible;">
            <defs>
                <linearGradient id="pArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#3a8fff"/>
                    <stop offset="33%"  stop-color="#72c8ff"/>
                    <stop offset="55%"  stop-color="#5fe08f"/>
                    <stop offset="75%"  stop-color="#c8e05f"/>
                    <stop offset="92%"  stop-color="#ffb347"/>
                    <stop offset="100%" stop-color="#ff6b3a"/>
                </linearGradient>
                <linearGradient id="pVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#pArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="17.2" y1="68.2" x2="22.0" y2="69.5" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="34.0" y1="39.0" x2="37.6" y2="42.6" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="63.2" y1="22.2" x2="64.5" y2="27.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="96.8" y1="22.2" x2="95.5" y2="27.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="126.0" y1="39.0" x2="122.4" y2="42.6" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="142.8" y1="68.2" x2="138.0" y2="69.5" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <text x="1.0" y="86.5" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">980</text>
            <text x="11.6" y="47.0" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">990</text>
            <text x="40.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">1000</text>
            <text x="80.0" y="7.5" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">1010</text>
            <text x="119.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">1020</text>
            <text x="148.4" y="47.0" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">1030</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">1040</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#pVal)">
                ${pVal ?? "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">гПа</text>
        </svg>
        <div class="ind-trend">
            <svg viewBox="0 0 52 14" width="70" height="19">
                ${tp
                    ? `<path d="${tp}" fill="none" stroke="currentColor" stroke-opacity="0.80" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`
                    : `<line x1="0" y1="7" x2="52" y2="7" stroke="currentColor" stroke-opacity="0.20" stroke-width="1.5" stroke-dasharray="3,3"/>`
                }
            </svg>
            <div class="small">${ts}</div>
        </div>
    </div>`;
}

/* =========================================================
   ВЛАЖНОСТЬ
========================================================= */
function humidityIndicatorSvg(humidity){
    const val   = humidity != null ? Math.round(humidity) : null;
    const angle = val != null ? (val - 50) / 50 * 90 : 0;

    // Градиент дуги влажности: 0%=жёлтый, 50%=зелёный, 100%=синий
const H_STOPS = [
    {offset:0,   color:"#ffd166"},
    {offset:0.5, color:"#5fe08f"},
    {offset:1,   color:"#58aeff"},
];
const hT  = val != null ? val / 100 : null;
const vc  = hT != null ? gradientColor(H_STOPS, hT) : "#aaa";


    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Влажность</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Влажность" style="overflow:visible;">
            <defs>
                <linearGradient id="hArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#ffd166"/>
                    <stop offset="50%"  stop-color="#5fe08f"/>
                    <stop offset="100%" stop-color="#58aeff"/>
                </linearGradient>
                <linearGradient id="hVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#hArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="23.0" y2="85.0" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="34.0" y1="39.0" x2="39.7" y2="44.7" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="28.0" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="126.0" y1="39.0" x2="120.3" y2="44.7" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="137.0" y2="85.0" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.8" stroke-linecap="round"/>
            <text x="1.0"  y="86.5" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">0</text>
            <text x="24.1" y="30.6" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">25</text>
            <text x="80.0" y="7.5"  text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.55">50</text>
            <text x="135.9" y="30.6" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.55">75</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.55">100</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#hVal)">
                ${val != null ? val + "" : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">%</text>
        </svg>
    </div>`;
}

/* =========================================================
   ТЕМПЕРАТУРА (циферблат -20..+40°C)
========================================================= */
function tempIndicatorSvg(temp, feelsLike){
    const tMin = -20, tMax = 40;
    const tC   = temp != null ? Math.max(tMin, Math.min(tMax, temp)) : null;
    const angle = tC != null ? (tC - 10) / 30 * 90 : 0;
    // 10°C = середина шкалы (вверх), -20 = -90°, +40 = +90°

    // Градиент дуги температуры: -20=синий, -10=голубой, 0=зелёный, 10=жёлтый, 40=оранжевый
const T_STOPS = [
    {offset:0,    color:"#3a8fff"},
    {offset:0.25, color:"#9dd6ff"},
    {offset:0.5,  color:"#5fe08f"},
    {offset:0.75, color:"#ffd84d"},
    {offset:1,    color:"#ff6b3a"},
];
const tT  = tC != null ? (tC - (-20)) / 60 : null;
const vc  = tT != null ? gradientColor(T_STOPS, tT) : "#aaa";


    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Температура</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Температура" style="overflow:visible;">
            <defs>
                <linearGradient id="tArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#3a8fff"/>
                    <stop offset="25%"  stop-color="#9dd6ff"/>
                    <stop offset="50%"  stop-color="#5fe08f"/>
                    <stop offset="75%"  stop-color="#ffd84d"/>
                    <stop offset="100%" stop-color="#ff6b3a"/>
                </linearGradient>
                <linearGradient id="tVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#tArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="17.2" y1="68.2" x2="22.0" y2="69.5" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="34.0" y1="39.0" x2="37.6" y2="42.6" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="63.2" y1="22.2" x2="64.5" y2="27.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="96.8" y1="22.2" x2="95.5" y2="27.0" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="126.0" y1="39.0" x2="122.4" y2="42.6" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <line x1="142.8" y1="68.2" x2="138.0" y2="69.5" stroke="currentColor" stroke-opacity="0.22" stroke-width="1.2" stroke-linecap="round"/>
            <text x="1.0" y="86.5" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">-20</text>
            <text x="11.6" y="47.0" text-anchor="end" font-size="8" fill="currentColor" fill-opacity="0.60">-10</text>
            <text x="40.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">0</text>
            <text x="80.0" y="7.5" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">10</text>
            <text x="119.5" y="18.1" text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.60">20</text>
            <text x="148.4" y="47.0" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">30</text>
            <text x="159.0" y="86.5" text-anchor="start" font-size="8" fill="currentColor" fill-opacity="0.60">40</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#tVal)">
                ${temp != null ? fmt1(temp,"") : "-"}
            </text>
            ${feelsLike != null && Math.abs(feelsLike - temp) >= 0.5 ? `
            <text x="80" y="95" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">
                ощущ. ${fmt1(feelsLike,"°")}
            </text>` : `
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">°C</text>`
            }
        </svg>
    </div>`;
}

/* =========================================================
   СОЛНЕЧНАЯ РАДИАЦИЯ (0..1200 Вт/м²)
========================================================= */
function solarIndicatorSvg(solarRad){
    const val  = solarRad != null ? Math.round(solarRad) : null;
    const vMax = 1200;
    const t    = val != null ? Math.min(val, vMax) / vMax : null;
    const angle = t != null ? (t - 0.5) * 180 : 0;

    const S_STOPS = [
        {offset:0,    color:"#3a8fff"},
        {offset:0.25, color:"#c8e05f"},
        {offset:0.6,  color:"#ffd84d"},
        {offset:1,    color:"#ff8c00"},
    ];
    const vc = t != null ? gradientColor(S_STOPS, t) : "#aaa";

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Радиация</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Радиация" style="overflow:visible;">
            <defs>
                <linearGradient id="sArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#3a8fff"/>
                    <stop offset="25%"  stop-color="#c8e05f"/>
                    <stop offset="60%"  stop-color="#ffd84d"/>
                    <stop offset="100%" stop-color="#ff8c00"/>
                </linearGradient>
                <linearGradient id="sVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#sArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <text x="1.0"   y="86.5" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">0</text>
            <text x="11.6"  y="47.0" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">300</text>
            <text x="80.0"  y="7.5"  text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.55">600</text>
            <text x="148.4" y="47.0" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">900</text>
            <text x="159.0" y="86.5" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">1200</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#sVal)">
                ${val != null ? val : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">Вт/м²</text>
        </svg>
    </div>`;
}

/* =========================================================
   УФ-ИНДЕКС (0..11+)
========================================================= */
function uvIndicatorSvg(uv){
    const val  = uv != null ? Math.round(uv * 10) / 10 : null;
    const vMax = 11;
    const t    = val != null ? Math.min(val, vMax) / vMax : null;
    const angle = t != null ? (t - 0.5) * 180 : 0;

    const UV_STOPS = [
        {offset:0,    color:"#5fe08f"},
        {offset:0.27, color:"#ffd84d"},
        {offset:0.55, color:"#ff8c00"},
        {offset:0.73, color:"#ff4444"},
        {offset:1,    color:"#a855f7"},
    ];
    const vc = t != null ? gradientColor(UV_STOPS, t) : "#aaa";

    const uvLabel = val == null ? "" :
        val <= 2  ? "Низкий" :
        val <= 5  ? "Умеренный" :
        val <= 7  ? "Высокий" :
        val <= 10 ? "Очень высокий" : "Экстремальный";

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">УФ-индекс</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="УФ-индекс" style="overflow:visible;">
            <defs>
                <linearGradient id="uvArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#5fe08f"/>
                    <stop offset="27%"  stop-color="#ffd84d"/>
                    <stop offset="55%"  stop-color="#ff8c00"/>
                    <stop offset="73%"  stop-color="#ff4444"/>
                    <stop offset="100%" stop-color="#a855f7"/>
                </linearGradient>
                <linearGradient id="uvVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#uvArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <text x="1.0"   y="86.5" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">0</text>
            <text x="11.6"  y="47.0" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">3</text>
            <text x="80.0"  y="7.5"  text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.55">6</text>
            <text x="148.4" y="47.0" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">9</text>
            <text x="159.0" y="86.5" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">11+</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#uvVal)">
                ${val != null ? val : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">УФ</text>
            <text x="80" y="96" text-anchor="middle" font-size="9" fill="${vc}" fill-opacity="0.85">${uvLabel}</text>
        </svg>
    </div>`;
}

/* =========================================================
   ИНТЕНСИВНОСТЬ ОСАДКОВ (0..50 мм/ч)
========================================================= */
function precipRateIndicatorSvg(precipRate){
    const val  = precipRate != null ? Math.round(precipRate * 10) / 10 : null;
    const vMax = 50;
    const t    = val != null ? Math.min(val, vMax) / vMax : null;
    const angle = t != null ? (t - 0.5) * 180 : 0;

    const R_STOPS = [
        {offset:0,    color:"#c8e05f"},
        {offset:0.1,  color:"#5fe08f"},
        {offset:0.3,  color:"#58aeff"},
        {offset:0.6,  color:"#3a8fff"},
        {offset:1,    color:"#a855f7"},
    ];
    const vc = t != null ? gradientColor(R_STOPS, t) : "#aaa";

    const rLabel = val == null ? "" :
        val === 0    ? "Нет" :
        val < 0.5    ? "Следы" :
        val < 2      ? "Слабый" :
        val < 10     ? "Умеренный" :
        val < 25     ? "Сильный" : "Ливень";

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Интенсивность</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Интенсивность осадков" style="overflow:visible;">
            <defs>
                <linearGradient id="rrArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#c8e05f"/>
                    <stop offset="10%"  stop-color="#5fe08f"/>
                    <stop offset="30%"  stop-color="#58aeff"/>
                    <stop offset="60%"  stop-color="#3a8fff"/>
                    <stop offset="100%" stop-color="#a855f7"/>
                </linearGradient>
                <linearGradient id="rrVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#rrArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <text x="1.0"   y="86.5" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">0</text>
            <text x="11.6"  y="47.0" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">2</text>
            <text x="80.0"  y="7.5"  text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.55">10</text>
            <text x="148.4" y="47.0" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">25</text>
            <text x="159.0" y="86.5" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">50</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#rrVal)">
                ${val != null ? fmt1(val,"") : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">мм/ч</text>
            <text x="80" y="96" text-anchor="middle" font-size="9" fill="${vc}" fill-opacity="0.85">${rLabel}</text>
        </svg>
    </div>`;
}

/* =========================================================
   СУММА ОСАДКОВ (0..100 мм)
========================================================= */
function precipTotalIndicatorSvg(precipTotal){
    const val  = precipTotal != null ? Math.round(precipTotal * 10) / 10 : null;
    const vMax = 100;
    const t    = val != null ? Math.min(val, vMax) / vMax : null;
    const angle = t != null ? (t - 0.5) * 180 : 0;

    const T_STOPS = [
        {offset:0,    color:"#c8e05f"},
        {offset:0.05, color:"#5fe08f"},
        {offset:0.2,  color:"#58aeff"},
        {offset:0.5,  color:"#3a8fff"},
        {offset:1,    color:"#a855f7"},
    ];
    const vc = t != null ? gradientColor(T_STOPS, t) : "#aaa";

    return `
    <div class="ind-card" onclick="indExpand(this)">
        <div class="ind-title">Осадки</div>
        <svg viewBox="${IND_VB}" width="${IND_W}" height="${IND_H}" aria-label="Сумма осадков" style="overflow:visible;">
            <defs>
                <linearGradient id="rtArc" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%"   stop-color="#c8e05f"/>
                    <stop offset="5%"   stop-color="#5fe08f"/>
                    <stop offset="20%"  stop-color="#58aeff"/>
                    <stop offset="50%"  stop-color="#3a8fff"/>
                    <stop offset="100%" stop-color="#a855f7"/>
                </linearGradient>
                <linearGradient id="rtVal" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%"   stop-color="${vc}"/>
                    <stop offset="100%" stop-color="${vc}" stop-opacity="0.5"/>
                </linearGradient>
            </defs>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="currentColor" stroke-opacity="0.10" stroke-width="8" stroke-linecap="round"/>
            <path d="M 15 85 A 65 65 0 0 1 145 85"
                  fill="none" stroke="url(#rtArc)" stroke-width="7" stroke-linecap="round"/>
            <line x1="15.0" y1="85.0" x2="24.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="23.7" y1="52.5" x2="31.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="47.5" y1="28.7" x2="52.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="80.0" y1="20.0" x2="80.0" y2="29.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="112.5" y1="28.7" x2="108.0" y2="36.5" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="136.3" y1="52.5" x2="128.5" y2="57.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <line x1="145.0" y1="85.0" x2="136.0" y2="85.0" stroke="currentColor" stroke-opacity="0.55" stroke-width="2" stroke-linecap="round"/>
            <text x="1.0"   y="86.5" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">0</text>
            <text x="11.6"  y="47.0" text-anchor="end"    font-size="8" fill="currentColor" fill-opacity="0.55">5</text>
            <text x="80.0"  y="7.5"  text-anchor="middle" font-size="8" fill="currentColor" fill-opacity="0.55">20</text>
            <text x="148.4" y="47.0" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">50</text>
            <text x="159.0" y="86.5" text-anchor="start"  font-size="8" fill="currentColor" fill-opacity="0.55">100</text>
            <g style="transform-origin:80px 85px;transform:rotate(${angle}deg);transition:transform 0.8s ease;">
                <polygon points="80,28 73,42 87,42" fill="currentColor" opacity="0.92"/>
            </g>
            <text x="80" y="85" text-anchor="middle" font-size="21" font-weight="800" fill="url(#rtVal)">
                ${val != null ? fmt1(val,"") : "-"}
            </text>
            <text x="80" y="65" text-anchor="middle" font-size="9" fill="currentColor" fill-opacity="0.50">мм</text>
        </svg>
    </div>`;
}
