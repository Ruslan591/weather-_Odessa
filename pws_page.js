/* =========================================================
   PWS_PAGE.JS — страница pws.html
   Одна станция на экране, выбор через select
   Коррекция давления сохраняется в localStorage
   Зависит от: utils.js, indicators.js, pws.js (WU_KEYS)
========================================================= */

const PWS_STATIONS = [
    { id:"IODESA137", name:"пос. Котовского"  },
    { id:"IODESA138", name:"Центр"           },
    { id:"IODESA139", name:"Чудо Город"      },
    { id:"IODESS41",  name:"Судостроительная" },
    { id:"IODESS44",  name:"Аркадия"         },
    { id:"IODESS16",  name:"Таирова"         },
    { id:"IODESS31",  name:"Савиньон"        },
    { id:"IODESS37",  name:"Застава"         },
    { id:"IKRASN91",  name:"пос. Степовое"   },
];

const PWS_REFRESH = 15;
const CALIB_KEY   = "pwsCalib2";
const SEL_KEY     = "pwsLastStation";

let _timer     = null;
let _currentId = null;
let _lastData  = null;

/* =========================================================
   ШТОРКА
========================================================= */
function toggleDetails(e){
    e.preventDefault();
    const det = e.currentTarget.closest("details");
    if(det.open){
        det.querySelector(".details-body").style.gridTemplateRows = "0fr";
        setTimeout(() => det.removeAttribute("open"), 350);
    } else {
        det.setAttribute("open","");
        requestAnimationFrame(() => {
            det.querySelector(".details-body").style.gridTemplateRows = "1fr";
        });
    }
}

/* =========================================================
   КОРРЕКЦИЯ ДАВЛЕНИЯ
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
    if(_histParam === "pressure") histLoad();
}
function resetCalib(){
    setOffset(_currentId, 0);
    const inp = document.getElementById("calibInput");
    if(inp) inp.value = "0";
    if(_lastData) renderPWSStation(_lastData);
    if(_histParam === "pressure") histLoad();
}
function calibBySynop(){
    let synopData;
    try { synopData = JSON.parse(localStorage.getItem("synopLastPressure")); }
    catch(e){ synopData = null; }
    const msgEl = document.getElementById("calibMsg");
    if(!synopData || synopData.pressure == null){
        if(msgEl){ msgEl.textContent = "Нет данных SYNOP. Обновите сводку на странице SYNOP."; msgEl.style.color = "#ff8f43"; }
        return;
    }
    const ageMs  = Date.now() - synopData.ts;
    const ageMin = Math.round(ageMs / 60000);
    if(ageMin > 180){
        if(msgEl){ msgEl.textContent = `Данные SYNOP утратили актуальность (${ageMin} мин назад). Обновите сводку.`; msgEl.style.color = "#ff8f43"; }
        return;
    }
    const p = _lastData;
    if(!p || p.error || p.pressure == null){
        if(msgEl){ msgEl.textContent = "Нет данных PWS для коррекции."; msgEl.style.color = "#ff8f43"; }
        return;
    }
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
   ЦВЕТ ТЕМПЕРАТУРЫ
========================================================= */
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
   ПОЛОЖЕНИЕ СОЛНЦА
   Возвращает { elev (рад), elevDeg, az (°, от С по часовой) }
========================================================= */
function solarPosition(lat, lon, date){
    const rad = Math.PI / 180;
    const start     = Date.UTC(date.getUTCFullYear(), 0, 0);
    const dayOfYear = Math.floor((date - start) / 86400000);
    const B    = (360/365) * (dayOfYear - 81) * rad;
    const eot  = 9.87*Math.sin(2*B) - 7.53*Math.cos(B) - 1.5*Math.sin(B);
    const decl = 23.45 * Math.sin(B) * rad;
    const utcH      = date.getUTCHours() + date.getUTCMinutes()/60 + date.getUTCSeconds()/3600;
    const solarH    = utcH + lon/15 + eot/60;
    const hourAngle = (solarH - 12) * 15 * rad;
    const latR      = lat * rad;
    const sinElev   = Math.sin(latR)*Math.sin(decl) + Math.cos(latR)*Math.cos(decl)*Math.cos(hourAngle);
    const elev      = Math.asin(Math.max(-1, Math.min(1, sinElev)));
    const cosElev   = Math.cos(elev);
    let az = 0;
    if(cosElev > 1e-6){
        const cosAz = (Math.sin(decl) - Math.sin(latR)*sinElev) / (Math.cos(latR)*cosElev);
        const azRaw = Math.acos(Math.max(-1, Math.min(1, cosAz))) * 180/Math.PI;
        az = hourAngle > 0 ? 360 - azRaw : azRaw;
    }
    return { elev, elevDeg: Math.round(elev*180/Math.PI*10)/10, az: Math.round(az) };
}

/* =========================================================
   ВОСХОД / ЗАХОД СОЛНЦА
   Возвращает { riseUTC, setUTC } в часах UTC или null
========================================================= */
function solarRiseSet(lat, lon, date){
    const rad = Math.PI / 180;
    const start     = Date.UTC(date.getUTCFullYear(), 0, 0);
    const dayOfYear = Math.floor((date - start) / 86400000);
    const B    = (360/365) * (dayOfYear - 81) * rad;
    const eot  = 9.87*Math.sin(2*B) - 7.53*Math.cos(B) - 1.5*Math.sin(B);
    const decl = 23.45 * Math.sin(B) * rad;
    const latR = lat * rad;
    const cosH = -Math.tan(latR) * Math.tan(decl);
    if(cosH < -1 || cosH > 1) return null;
    const H    = Math.acos(cosH) * 180/Math.PI;
    const noon = 12 - lon/15 - eot/60;
    return { riseUTC: noon - H/15, setUTC: noon + H/15 };
}

/* =========================================================
   ПОЛОЖЕНИЕ ЛУНЫ (алгоритм Meeus, упрощённый)
   Возвращает { elev, elevDeg, az, phase, illumination, phaseName }
========================================================= */
function lunarPosition(lat, lon, date){
    const rad = Math.PI / 180;
    const JD  = date.getTime() / 86400000 + 2440587.5;
    const d   = JD - 2451545.0; // дней от J2000

    const L0 = ((218.316 + 13.176396*d) % 360 + 360) % 360;
    const M  = ((134.963 + 13.064993*d) % 360 + 360) % 360 * rad;
    const F  = ((93.272  + 13.229350*d) % 360 + 360) % 360 * rad;

    const lonM  = (L0 + 6.289*Math.sin(M)) * rad;
    const latM  = 5.128*Math.sin(F)        * rad;
    const eps   = 23.439 * rad;

    const sinDec = Math.sin(latM)*Math.cos(eps) + Math.cos(latM)*Math.sin(eps)*Math.sin(lonM);
    const decl   = Math.asin(Math.max(-1, Math.min(1, sinDec)));
    const ra     = Math.atan2(
        Math.sin(lonM)*Math.cos(eps) - Math.tan(latM)*Math.sin(eps),
        Math.cos(lonM)
    );

    const GMST     = ((280.46061837 + 360.98564736629*d) % 360 + 360) % 360 * rad;
    const LST      = GMST + lon*rad;
    const hourAngle = LST - ra;

    const latR    = lat * rad;
    const sinElev = Math.sin(latR)*Math.sin(decl) + Math.cos(latR)*Math.cos(decl)*Math.cos(hourAngle);
    const elev    = Math.asin(Math.max(-1, Math.min(1, sinElev)));
    const cosElev = Math.cos(elev);
    let az = 0;
    if(cosElev > 1e-6){
        const cosAz = (Math.sin(decl) - Math.sin(latR)*sinElev) / (Math.cos(latR)*cosElev);
        const azRaw = Math.acos(Math.max(-1, Math.min(1, cosAz))) * 180/Math.PI;
        az = Math.sin(hourAngle) > 0 ? 360 - azRaw : azRaw;
    }

    const phase        = ((d % 29.53059) / 29.53059 + 1) % 1;
    const illumination = Math.round((1 - Math.cos(phase * 2*Math.PI)) / 2 * 100);
    const phaseName    =
        phase < 0.03 || phase > 0.97 ? "🌑 Новолуние"          :
        phase < 0.22                  ? "🌒 Молодой месяц"      :
        phase < 0.28                  ? "🌓 Первая четверть"    :
        phase < 0.47                  ? "🌔 Прибывающая луна"   :
        phase < 0.53                  ? "🌕 Полнолуние"         :
        phase < 0.72                  ? "🌖 Убывающая луна"     :
        phase < 0.78                  ? "🌗 Последняя четверть" :
                                        "🌘 Старый месяц";

    return {
        elev, elevDeg: Math.round(elev*180/Math.PI*10)/10,
        az: Math.round(az),
        phase, illumination, phaseName,
    };
}

/* =========================================================
   ТЕОРЕТИЧЕСКАЯ ИНСОЛЯЦИЯ ЯСНОГО НЕБА
   Модель Kasten & Young (1989)
========================================================= */
function clearskyIrradiance(elevDeg){
    if(elevDeg <= 0) return 0;
    const sinElev = Math.sin(elevDeg * Math.PI / 180);
    const AM = 1 / (sinElev + 0.50572 * Math.pow(elevDeg + 6.07995, -1.6364));
    return Math.max(0, 1361 * Math.pow(0.7, Math.pow(AM, 0.678)) * sinElev);
}

/* =========================================================
   ТЕМПЕРАТУРА ШАРОВОГО ТЕРМОМЕТРА
   Liljegren et al. (2008) + kt-коррекция прямой/рассеянной радиации
========================================================= */
function calcGlobeTemp(ta, sr, wind, elev, rh){
    if(ta == null) return null;
    const v       = Math.max(wind ?? 0.5, 0.5);          // минимум 0.5 м/с
    const elevDeg = elev != null ? elev * 180/Math.PI : -1;
    const dryness = rh  != null ? Math.max(0, 1 - rh/100) : 0.3;
    const tgNight = ta - 4.0 * Math.pow(dryness, 0.5);

    // Ночь / солнце под горизонтом
    if(elevDeg <= 0 || sr == null || sr < 1)
        return Math.round(tgNight * 10) / 10;

    // Clearness index: 1.0 = ясно, 0 = сплошная облачность
    const clearsky = clearskyIrradiance(elevDeg);
    const kt = clearsky > 10 ? Math.min(1, sr / clearsky) : 0;

    // Доля рассеянного излучения (Orgill & Hollands, упрощённо)
    // kt=0 → 100% рассеянное, kt≥0.8 → 15% рассеянное
    const diffuseFrac = kt >= 0.8 ? 0.15 : Math.max(0.15, 1.0 - 1.0625 * kt);
    const srDiffuse   = sr * diffuseFrac;
    const srDirect    = sr - srDiffuse;

    // Поглощение сферой:
    // прямое — усиливается при низком солнце (1/sinElev)
    // рассеянное — изотропное, без усиления угла
    const sinElev         = Math.sin(elev);
    const srSphereDirect  = srDirect  * 0.5 / Math.max(sinElev, 0.087);
    const srSphereDiffuse = srDiffuse * 0.5;
    const srSphere        = Math.min(srSphereDirect + srSphereDiffuse, sr * 2.0);

    const hc    = 6.3 * Math.pow(v, 0.6);
    const tgDay = ta + (0.95 * srSphere) / hc;

    // Плавный переход при очень слабой радиации
    if(sr < 20){
        const w = sr / 20;
        return Math.round((tgNight*(1-w) + tgDay*w) * 10) / 10;
    }

    return Math.round(tgDay * 10) / 10;
}

/* =========================================================
   SVG-ЦИФЕРБЛАТ НЕБОСВОДА
   Вид сверху, север вверху. Объекты ближе к краю = ниже над горизонтом.
========================================================= */
function makeSkyDial(sun, moon, riseSet, lat, lon, date){
    const S = 200, cx = 100, cy = 100, R = 80;

    function toXY(az, elevDeg){
        const azR = az * Math.PI/180;
        const r   = R * Math.cos(Math.max(0, elevDeg) * Math.PI/180);
        return { x: cx + r*Math.sin(azR), y: cy - r*Math.cos(azR) };
    }

    // Дуга дневного пути (60 шагов от восхода до заката)
    let arcPath = "";
    if(riseSet){
        const pts = [];
        for(let i = 0; i <= 60; i++){
            const h  = riseSet.riseUTC + (riseSet.setUTC - riseSet.riseUTC)*i/60;
            const d2 = new Date(Date.UTC(
                date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(),
                Math.floor(h), Math.round((h%1)*60)
            ));
            const sp = solarPosition(lat, lon, d2);
            if(sp.elevDeg < 0) continue;
            const {x,y} = toXY(sp.az, sp.elevDeg);
            pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        }
        if(pts.length > 1)
            arcPath = `<polyline points="${pts.join(" ")}" fill="none" stroke="#ffd84d55" stroke-width="2" stroke-linecap="round"/>`;
    }

    // Солнце
    const sunAbove = sun.elevDeg > 0;
    const sXY  = toXY(sun.az, Math.max(sun.elevDeg, 0));
    const sR   = sunAbove ? Math.max(6, Math.min(12, 6 + sun.elevDeg/9)) : 0;
    const sunSvg = sunAbove ? `
        <circle cx="${sXY.x.toFixed(1)}" cy="${sXY.y.toFixed(1)}" r="${(sR+5).toFixed(1)}" fill="#ffd84d20"/>
        <circle cx="${sXY.x.toFixed(1)}" cy="${sXY.y.toFixed(1)}" r="${sR.toFixed(1)}" fill="#ffd84d"/>` : "";

    // Луна
    const moonAbove = moon.elevDeg > 0;
    const mXY = toXY(moon.az, Math.max(moon.elevDeg, 0));
    const moonSvg = moonAbove ? `
        <circle cx="${mXY.x.toFixed(1)}" cy="${mXY.y.toFixed(1)}" r="11" fill="#aaccff18"/>
        <circle cx="${mXY.x.toFixed(1)}" cy="${mXY.y.toFixed(1)}" r="7"  fill="#aaccff" opacity="0.85"/>` : "";

    // Стороны света
    const cardinals = ["С","В","Ю","З"].map((l,i) => {
        const a = i*90*Math.PI/180;
        const x = cx + (R+15)*Math.sin(a), y = cy - (R+15)*Math.cos(a);
        return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="#444" font-family="sans-serif">${l}</text>`;
    }).join("");

    // Метки восхода/заката на горизонте
    let rsMarks = "";
    if(riseSet){
        const fmtLocal = h => {
            const t = ((h+3)%24+24)%24;
            return `${String(Math.floor(t)).padStart(2,"0")}:${String(Math.round((t%1)*60)).padStart(2,"0")}`;
        };
        const rd = new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),date.getUTCDate(),
            Math.floor(riseSet.riseUTC), Math.round((riseSet.riseUTC%1)*60)));
        const sd = new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),date.getUTCDate(),
            Math.floor(riseSet.setUTC),  Math.round((riseSet.setUTC%1)*60)));
        const rp = solarPosition(lat, lon, rd), sp2 = solarPosition(lat, lon, sd);
        const rxy = toXY(rp.az, 0), sxy = toXY(sp2.az, 0);
        rsMarks = `
            <circle cx="${rxy.x.toFixed(1)}" cy="${rxy.y.toFixed(1)}" r="3.5" fill="#ffd84daa"/>
            <circle cx="${sxy.x.toFixed(1)}" cy="${sxy.y.toFixed(1)}" r="3.5" fill="#ff9f43aa"/>
            <text x="${(cx).toFixed(1)}" y="${(cy+R+18).toFixed(1)}" text-anchor="middle" font-size="9" fill="#ffd84d88" font-family="sans-serif">↑восход ${fmtLocal(riseSet.riseUTC)}</text>
            <text x="${(cx).toFixed(1)}" y="${(cy+R+28).toFixed(1)}" text-anchor="middle" font-size="9" fill="#ff9f4388" font-family="sans-serif">↓закат ${fmtLocal(riseSet.setUTC)}</text>`;
    }

    return `<svg width="${S}" height="${S+20}" viewBox="0 0 ${S} ${S+20}" style="display:block;margin:0 auto;">
        <circle cx="${cx}" cy="${cy}" r="${R}" fill="#080808" stroke="#1e1e1e" stroke-width="1.5"/>
        <circle cx="${cx}" cy="${cy}" r="${(R*Math.cos(30*Math.PI/180)).toFixed(1)}" fill="none" stroke="#151515" stroke-width="1"/>
        <circle cx="${cx}" cy="${cy}" r="${(R*Math.cos(60*Math.PI/180)).toFixed(1)}" fill="none" stroke="#151515" stroke-width="1"/>
        <line x1="${cx}" y1="${cy-R}" x2="${cx}" y2="${cy+R}" stroke="#181818" stroke-width="1"/>
        <line x1="${cx-R}" y1="${cy}" x2="${cx+R}" y2="${cy}" stroke="#181818" stroke-width="1"/>
        <circle cx="${cx}" cy="${cy}" r="2.5" fill="#222"/>
        ${arcPath}
        ${rsMarks}
        ${moonSvg}
        ${sunSvg}
        ${cardinals}
    </svg>`;
}

/* =========================================================
   БЛОК: НЕБОСВОД, СОЛНЦЕ, ЛУНА И ТЕПЛОВОЙ СТРЕСС
========================================================= */
function makeSolarWbgtBlock(p){
    if(p.lat == null && p.solarRad == null && p.uv == null) return "";

    const lat     = p.lat;
    const lon     = p.lon;
    const obsDate = p.obsTimeUtc ? new Date(p.obsTimeUtc) : new Date();

    const sun     = lat != null ? solarPosition(lat, lon, obsDate) : null;
    const moon    = lat != null ? lunarPosition(lat, lon, obsDate)  : null;
    const riseSet = lat != null ? solarRiseSet(lat, lon, obsDate)   : null;

    const dialHtml = (sun && moon) ? makeSkyDial(sun, moon, riseSet, lat, lon, obsDate) : "";

    // Clearness index (новая строка после dialHtml)
    const kt = (sun && sun.elevDeg > 0 && p.solarRad != null)
        ? (() => { const cs = clearskyIrradiance(sun.elevDeg); return cs > 10 ? Math.min(1, p.solarRad / cs) : 0; })()
        : null;
    const cloudPct = kt != null ? Math.round((1 - kt) * 100) : null;

    // Солнце
    let sunInfoHtml = "";
    if(sun){
        const status = sun.elevDeg > 0
            ? `${sun.elevDeg}° над горизонтом`
            : `${Math.abs(sun.elevDeg)}° под горизонтом`;
        const fmtLocal = h => {
            const t = ((h+3)%24+24)%24;
            return `${String(Math.floor(t)).padStart(2,"0")}:${String(Math.round((t%1)*60)).padStart(2,"0")}`;
        };
        const rsRow = riseSet
            ? `<div class="districtLine"><span>Восход / Закат</span><span>${fmtLocal(riseSet.riseUTC)} / ${fmtLocal(riseSet.setUTC)}</span></div>`
            : "";
        sunInfoHtml = `
        <div class="districtLine"><span>☀️ Солнце</span><span>${status} · ${degToText(sun.az)} ${sun.az}°</span></div>
        ${rsRow}`;
    }

    // Луна
    let moonInfoHtml = "";
    if(moon){
        const status = moon.elevDeg > 0
            ? `${moon.elevDeg}° над горизонтом`
            : `${Math.abs(moon.elevDeg)}° под горизонтом`;
        moonInfoHtml = `
        <div class="districtLine"><span>${moon.phaseName}</span><span>${moon.illumination}% · ${status}</span></div>
        <div class="districtLine"><span>Азимут Луны</span><span>${degToText(moon.az)} ${moon.az}°</span></div>`;
    }

    // SR и UV
    const srHtml = p.solarRad != null
        ? `<div class="districtLine"><span>Солнечная радиация</span><span>${fmt0(p.solarRad," Вт/м²")}${cloudPct != null ? ` · облачность ~${cloudPct}%` : ""}</span></div>`
        : "";
    const uvLevel = p.uv == null ? null
        : p.uv < 3  ? { label:"Низкий",        color:"#4caf50" }
        : p.uv < 6  ? { label:"Умеренный",     color:"#ffd166" }
        : p.uv < 8  ? { label:"Высокий",       color:"#ff9800" }
        : p.uv < 11 ? { label:"Очень высокий", color:"#f44336" }
        :              { label:"Экстремальный", color:"#9c27b0" };
    const burnMin = (p.uv >= 3) ? Math.round(200 / (p.uv * 3.5)) : null;
    const uvHtml  = uvLevel ? `
        <div class="districtLine">
            <span>УФ-индекс</span>
            <span style="color:${uvLevel.color};font-weight:600;">${p.uv} · ${uvLevel.label}</span>
        </div>
        ${burnMin != null ? `<div class="districtLine"><span>Время до ожога (I тип кожи)</span><span>~${burnMin} мин</span></div>` : ""}` : "";

    // WBGT
    let wbgtHtml = "";
    if(p.temp != null && p.dewpt != null && sun != null){
        const rh   = calcRelativeHumidity(p.temp, p.dewpt);
        const wind = p.windSpeedMs ?? 0.5;
        const tg   = calcGlobeTemp(p.temp, p.solarRad, wind, sun.elev, rh);
        if(tg != null){
            const res = calcWBGT(p.temp, tg, p.dewpt);
            if(res){
                const { wbgt, tw } = res;
                const iso = wbgt < 28 ? { label:"Комфортно",    color:"#4caf50" }
                          : wbgt < 32 ? { label:"Осторожно",    color:"#ff9800" }
                          : wbgt < 35 ? { label:"Опасно",       color:"#f44336" }
                          :             { label:"Очень опасно", color:"#9c27b0" };
                const zones = [[0,0],[28,25],[32,50],[35,75],[40,100]];
const pct = (() => {
    if(wbgt <= 0)  return 0;
    if(wbgt >= 40) return 100;
    for(let i = 1; i < zones.length; i++){
        const [v0,p0] = zones[i-1], [v1,p1] = zones[i];
        if(wbgt <= v1) return p0 + (wbgt-v0)/(v1-v0)*(p1-p0);
    }
    return 100;
})();
                wbgtHtml = `
                <div style="margin-top:8px;border-top:1px solid #1e1e1e;padding-top:8px;">
                    <div class="districtLine"><span>Tw (влажный термометр)</span><span>${fmt1(tw,"°C")}</span></div>
                    <div class="districtLine"><span>Tg (шар, расчётный)</span><span>${fmt1(tg,"°C")}</span></div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin:10px 0 4px;">
                        <span style="font-size:13px;font-weight:600;color:#888;">WBGT</span>
                        <span style="font-size:26px;font-weight:800;color:${iso.color};">${wbgt.toFixed(1)}°C</span>
                    </div>
                    <div style="position:relative;height:8px;border-radius:4px;
                                background:linear-gradient(to right,#4caf50,#ffd166,#ff9800,#f44336,#9c27b0);
                                margin-bottom:4px;">
                        <div style="position:absolute;top:-3px;left:calc(${pct}% - 7px);
                                    width:14px;height:14px;border-radius:50%;
                                    background:${iso.color};border:2px solid #111;"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:10px;color:#444;margin-bottom:8px;">
                        <span>0°</span><span>28°</span><span>32°</span><span>35°</span><span>40°+</span>
                    </div>
                    <div style="text-align:center;padding:6px 10px;border-radius:8px;
                                background:${iso.color}22;border:1px solid ${iso.color}55;">
                        <span style="color:${iso.color};font-weight:700;font-size:14px;">ISO 7243 · ${iso.label}</span>
                    </div>
                </div>`;
            }
        }
    }

    return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        <div style="font-size:11px;color:#555;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;">Небосвод и тепловой стресс</div>
        ${dialHtml}
        <div class="pws-fields" style="margin-top:8px;">
            ${sunInfoHtml}
            ${moonInfoHtml}
            ${srHtml}
            ${uvHtml}
            ${wbgtHtml}
        </div>
    </div>`;
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
   РЕНДЕР СТАНЦИИ
========================================================= */
function timeAgeColor(obsTimeLocal){
    if(!obsTimeLocal) return "#666";
    const d = new Date(obsTimeLocal.replace(" ","T"));
    if(isNaN(d)) return "#666";
    const ageMin = (Date.now() - d.getTime()) / 60000;
    if(ageMin < 20)  return "#5fe08f";
    if(ageMin < 60)  return "#ffd166";
    if(ageMin < 180) return "#ff9f43";
    return "#ff6b6b";
}

function renderPWSStation(p){
    _lastData = p;
    const box = document.getElementById("pwsContent");
    if(!box) return;

    const off = getOffset(_currentId);
    const cfg = PWS_STATIONS.find(s=>s.id===_currentId);

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

    const pCorr    = p.pressure != null ? Math.round((p.pressure + off)*10)/10 : null;
    const feelsLike =
        p.temp!=null&&p.temp>=27&&p.heatIndex!=null ? p.heatIndex :
        p.temp!=null&&p.temp<=10&&p.windChill!=null  ? p.windChill : p.temp;

    const rows = [
        p.dewpt       != null                          ? ["Точка росы",           fmt1(p.dewpt,"°C")]          : null,
        p.windGustMs  != null && p.windGustMs  > 0     ? ["Порывы",               fmt1(p.windGustMs," м/с")]   : null,
        p.precipRate  != null && p.precipRate  > 0     ? ["Интенсивность осадков", fmt1(p.precipRate," мм/ч")]  : null,
        p.precipTotal != null && p.precipTotal > 0     ? ["Осадки",               fmt1(p.precipTotal," мм")]   : null,
        p.solarRad    != null                          ? ["Солнечная радиация",    fmt0(p.solarRad," Вт/м²")]  : null,
        p.uv          != null                          ? ["УФ-индекс",             String(p.uv)]               : null,
    ].filter(Boolean);

    const rowsAbout = [
        p.elev         != null ? ["Высота над уровнем моря", fmt0(p.elev," м")]                               : null,
        p.softwareType != null ? ["ПО станции",              escapeHtml(p.softwareType)]                       : null,
        p.lat          != null ? ["Координаты",              `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`]      : null,
    ].filter(Boolean);

    box.innerHTML = `
    <div class="pws-station-card">
        <div class="pws-station-header">
            <div>
                <div class="cardTitle" style="margin-bottom:2px;">${escapeHtml(cfg?.name||_currentId)}</div>
                <div style="display:inline-block;margin-top:4px;padding:3px 10px;border-radius:20px;
                            font-size:13px;font-weight:600;
                            background:${timeAgeColor(p.obsTimeLocal)}22;
                            border:1px solid ${timeAgeColor(p.obsTimeLocal)}66;
                            color:${timeAgeColor(p.obsTimeLocal)};">
                    ${escapeHtml(timeStr)}
                    ${(()=>{const d=new Date((p.obsTimeLocal||"").replace(" ","T")); const m=Math.round((Date.now()-d)/60000); return isNaN(m)?"":`· ${m} мин назад`;})()}
                </div>
            </div>
            <div style="font-size:28px;font-weight:800;color:${tempColorExact(p.temp)};">${fmt1(p.temp,"°C")}</div>
        </div>

        <div class="ind-grid-2x2">
            ${tempIndicatorSvg(p.temp, feelsLike)}
            ${humidityIndicatorSvg(p.humidity)}
            ${windIndicatorSvg({windSpeed:p.windSpeedMs, windGustMs:p.windGustMs, windDir:p.windDir})}
            ${pressureIndicatorSvg({seaPressure:pCorr, tendencyCode:null, tendencyValue:null})}
            ${p.solarRad != null || p.uv != null ? solarIndicatorSvg(p.solarRad) : ""}
            ${p.uv       != null || p.solarRad != null ? uvIndicatorSvg(p.uv)    : ""}
            ${p.precipRate  != null ? precipRateIndicatorSvg(p.precipRate)        : ""}
            ${p.precipTotal != null ? precipTotalIndicatorSvg(p.precipTotal)      : ""}
        </div>

        ${rows.length ? `<div class="pws-fields">${rows.map(([k,v])=>`<div class="districtLine"><span>${k}</span><span>${v}</span></div>`).join("")}</div>` : ""}

        ${makeSolarWbgtBlock(p)}

        ${rowsAbout.length ? `<details style="margin-top:8px;">
            <summary onclick="toggleDetails(event)">О станции</summary>
            <div class="details-body"><div>
                <div class="pws-fields" style="margin-top:8px;">
                    ${rowsAbout.map(([k,v])=>`<div class="districtLine"><span>${k}</span><span>${v}</span></div>`).join("")}
                </div>
            </div></div>
        </details>` : ""}

        <div class="pws-calib">
            <span class="small" style="color:#666;">Коррекция давления:</span>
            <input id="calibInput" type="number" step="0.1" value="${off}"
                   style="width:65px;background:#232323;border:1px solid #333;border-radius:6px;
                          color:#eee;font-size:12px;padding:4px 8px;text-align:center;">
            <span class="small" style="color:#555;">гПа</span>
            <button onclick="applyCalib()"   style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#ccc;">✓</button>
            <button onclick="calibBySynop()" style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#72c8ff;">По SYNOP</button>
            <button onclick="resetCalib()"   style="width:auto;padding:4px 10px;font-size:11px;background:#252525;color:#888;">Сброс</button>
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
    histLoad();
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
    const box = document.getElementById("pwsContent");
    if(box) box.innerHTML = `<div style="padding:20px;color:#888;text-align:center;">Загрузка...</div>`;
    await loadAndRender();
    startRefresh();
}

initPWSPage();
