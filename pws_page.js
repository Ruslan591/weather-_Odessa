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
    { id:"IODESS35",  name:"Аркадия2"         },
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
let _ensembleCloudPct = null;  // % из последнего снимка
let _ensembleCloudFetchedAt = 0;
let _ktOcData    = null;
let _marineData  = null;
let _marineFetchedAt = 0;

async function fetchEnsembleCloud(){
    if(Date.now() - _ensembleCloudFetchedAt < 1200000) return; // обновляем раз в час
    try {
        const r = await fetch(
            "data/ensemble_snapshots_synop.json",
            {cache:"no-store"}
        );
        if(!r.ok) return;
        const snaps = await r.json();
        if(!snaps.length) return;
        const last = snaps[snaps.length - 1];
        const now  = Date.now();
        let best = null, bestDiff = Infinity;
        for(const h of last.hours){
            const t = Date.UTC(
                +h.time.slice(0,4), +h.time.slice(5,7)-1, +h.time.slice(8,10),
                +h.time.slice(11,13), 0
            );
            const diff = Math.abs(now - t);
            if(diff < bestDiff){ bestDiff = diff; best = h; }
        }
        if(best && bestDiff < 6*3600*1000){
            _ensembleCloudPct = best.cloudcover;
            _ensembleCloudFetchedAt = Date.now();
        }
    } catch(e){}
}

let _synopFetchedAt = 0;

async function fetchSynopCloud(){
    if(Date.now() - _synopFetchedAt < 2.5 * 3600000) return;
    _synopFetchedAt = Date.now();
    try {
        const year = new Date().getFullYear();
        const r = await fetch(`data/synop_${year}.txt`, {
            headers: { Range: "bytes=-500" },
            cache: "no-store"
        });
        if(!r.ok && r.status !== 206){ _synopFetchedAt = 0; return; }
        const text = await r.text();
        const lines = text.split("\n").map(s => s.trim()).filter(Boolean);
        const last  = lines[lines.length - 1];
        const m = last.match(/33837,\d+,\d+,(\d+),(\d+),\d+,AAXX\s+\d{5}\s+33837\s+[\d\/]{5}\s+([\d\/])/);
        if(!m){ _synopFetchedAt = 0; return; }
        const cloudN = parseInt(m[3]);
        if(isNaN(cloudN) || cloudN === 9){ _synopFetchedAt = 0; return; }
        const yyggi  = m[1].padStart(2,"0") + m[2].padStart(2,"0") + "1";
        const existing = JSON.parse(localStorage.getItem("synopLastPressure") || "{}");
        localStorage.setItem("synopLastPressure", JSON.stringify({
            ...existing, cloudN, yyggi, ts: Date.now()
        }));
    } catch(e){ _synopFetchedAt = 0; }
}

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
"&timezone=auto&forecast_days=1";
    const windUrl =
        "https://api.open-meteo.com/v1/forecast" +
        "?latitude=46.35&longitude=30.90" +
        "&current=wind_speed_10m,wind_gusts_10m,wind_direction_10m" +
        "&wind_speed_unit=ms&timezone=auto";
    try {
        const [mr, wr] = await Promise.all([
            fetch(marineUrl, { cache:"no-store" }),
            fetch(windUrl,   { cache:"no-store" }),
        ]);
        const c = mr.ok ? ((await mr.json()).current || {}) : {};
        _marineData = {
            sst:        c.sea_surface_temperature    ?? null,
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
        }
    } catch(e){
        console.warn("Marine API:", e.message);
        _marineFetchedAt = 0;
    }
}

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
    const v = Math.max(wind ?? 0.5, 1.0);
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
    // При kt<0.4 (сплошная облачность) прямого луча физически нет — усиление угла не применяем
    const directBoost     = kt > 0.4 ? 0.5 / Math.max(sinElev, 0.087) : 0.5;
    const srSphereDirect  = srDirect  * directBoost;
    const srSphereDiffuse = srDiffuse * 0.5;
    const srSphere        = Math.min(srSphereDirect + srSphereDiffuse, sr * 2.0);

    const v_eff = Math.sqrt(v * v + 0.25);   // естественная конвекция ≈ 0.5 м/с в квадратуре
const hc    = 17.0 * Math.pow(v_eff, 0.6) + 5.5;
    const tgDay = ta + (0.95 * srSphere) / hc;

    // Плавный переход при очень слабой радиации
    if(sr < 20){
        const w = sr / 20;
        return Math.round((tgNight*(1-w) + tgDay*w) * 10) / 10;
    }

    return Math.round(tgDay * 10) / 10;
}

/* =========================================================
   ЦВЕТ НЕБА ПО ВЫСОТЕ СОЛНЦА
   Интерполяция по реальным тонам от ночи до полудня
========================================================= */
function skyColorByElev(elevDeg){
    const stops = [
        [-90, [  0,  3,  8]],
        [-18, [  1,  8, 22]],
        [-12, [  3, 14, 45]],
        [ -6, [  8, 20, 72]],
        [ -2, [ 22, 38,105]],
        [  0, [ 38, 72,155]],
        [  5, [ 28, 95,185]],
        [ 15, [ 20,112,205]],
        [ 30, [ 16,118,215]],
        [ 60, [ 14,122,220]],
        [ 90, [ 13,118,212]],
    ];
    const e = Math.max(-90, Math.min(90, elevDeg ?? -90));
    if(e <= stops[0][0]) return `rgb(${stops[0][1]})`;
    const last = stops[stops.length-1];
    if(e >= last[0]) return `rgb(${last[1]})`;
    for(let i = 1; i < stops.length; i++){
        if(e <= stops[i][0]){
            const t = (e - stops[i-1][0]) / (stops[i][0] - stops[i-1][0]);
            const c = stops[i-1][1].map((v,j) => Math.round(v + t*(stops[i][1][j]-v)));
            return `rgb(${c[0]},${c[1]},${c[2]})`;
        }
    }
    return `rgb(${last[1]})`;
}

/* =========================================================
   SVG-ЦИФЕРБЛАТ НЕБОСВОДА
   Вид сверху, север вверху. Объекты ближе к краю = ниже над горизонтом.
========================================================= */
function makeSkyDial(sun, moon, riseSet, lat, lon, date, kt){
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
    const ktVal       = kt ?? 1;
    const haloOpacity = Math.round(ktVal * 0x30).toString(16).padStart(2,"0");
    const diskColor   = ktVal > 0.5 ? "#ffd84d" : `rgba(255,216,77,${(0.3 + ktVal*0.7).toFixed(2)})`;
    const sunSvg = sunAbove ? `
        <circle cx="${sXY.x.toFixed(1)}" cy="${sXY.y.toFixed(1)}" r="${(sR+5).toFixed(1)}" fill="#ffd84d${haloOpacity}"/>
        <circle cx="${sXY.x.toFixed(1)}" cy="${sXY.y.toFixed(1)}" r="${sR.toFixed(1)}" fill="${diskColor}"/>` : "";

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

// --- Цвет неба по высоте солнца ---
    const skyColor = skyColorByElev(sun.elevDeg);
    const gridColor = sun.elevDeg > -6 ? "#ffffff18" : "#ffffff0a";
    const axisColor = sun.elevDeg > -6 ? "#ffffff12" : "#ffffff08";

    // Кольца высот (30° и 60°) и оси
    const r30 = (R * Math.cos(30 * Math.PI/180)).toFixed(1);
    const r60 = (R * Math.cos(60 * Math.PI/180)).toFixed(1);
    const grid = `
        <line x1="${cx}" y1="${cy-R}" x2="${cx}" y2="${cy+R}" stroke="${axisColor}" stroke-width="1"/>
        <line x1="${cx-R}" y1="${cy}" x2="${cx+R}" y2="${cy}" stroke="${axisColor}" stroke-width="1"/>
        <circle cx="${cx}" cy="${cy}" r="${r30}" fill="none" stroke="${gridColor}" stroke-width="1"/>
        <circle cx="${cx}" cy="${cy}" r="${r60}" fill="none" stroke="${gridColor}" stroke-width="1"/>
        <circle cx="${cx}" cy="${cy}" r="3" fill="#ffffff22"/>
        <circle cx="${cx}" cy="${cy}" r="1.5" fill="#ffffff55"/>`;

    return `<svg width="${S}" height="${S+20}" viewBox="0 0 ${S} ${S+20}" style="display:block;margin:0 auto;">
        <circle cx="${cx}" cy="${cy}" r="${R}" fill="${skyColor}" stroke="#1e1e1e" stroke-width="1.5"/>
        ${grid}
        ${arcPath}
        ${rsMarks}
        ${moonSvg}
        ${sunSvg}
        ${cardinals}
    </svg>`;
}

async function loadKtOcTable(){
    const month = String(new Date().getMonth() + 1).padStart(2, "0");
    const urls = [
        `data/pws/combined/monthly/kt_oc_table_${month}.json`,
        `data/pws/combined/kt_oc_table.json`,
    ];
    for(const url of urls){
        try {
            const r = await fetch(url, {cache:"no-store"});
            if(r.ok){ _ktOcData = await r.json(); return; }
        } catch(e){}
    }
}

function _getKtRow(elevDeg){
    if(!_ktOcData) return null;
    const bins = Object.keys(_ktOcData).map(Number).sort((a,b)=>a-b);
    if(!bins.length) return null;
    if(elevDeg <= bins[0]) return _ktOcData[bins[0]];
    if(elevDeg >= bins[bins.length-1]) return _ktOcData[bins[bins.length-1]];
    for(let i=0; i<bins.length-1; i++){
        if(elevDeg >= bins[i] && elevDeg < bins[i+1]){
            const f   = (elevDeg - bins[i]) / (bins[i+1] - bins[i]);
            const r0  = _ktOcData[bins[i]];
            const r1  = _ktOcData[bins[i+1]];
            const allN = [...new Set([...Object.keys(r0),...Object.keys(r1)])].map(Number).sort((a,b)=>a-b);
            const merged = {};
            for(const n of allN){
                const v0 = r0[n] ?? null, v1 = r1[n] ?? null;
                merged[n] = (v0!=null && v1!=null) ? v0*(1-f)+v1*f : (v0??v1);
            }
            return merged;
        }
    }
    return null;
}

function getKtOc(elevDeg){
    const row = _getKtRow(elevDeg);
    return row?.[8] ?? 0.35;
}

function ktToCloudPct(kt, elevDeg){
    if(kt == null || elevDeg == null || elevDeg < 8) return null;
    const row = _getKtRow(elevDeg);
    if(!row) return kt < 0.35 ? 100 : kt > 0.85 ? 0 : Math.round((0.85-kt)/0.50*100);
    // пары [N, kt] отсортированы по убыванию kt (ясно→пасмурно)
    const pairs = Object.entries(row).map(([n,v])=>[+n,v]).sort((a,b)=>b[1]-a[1]);
    if(kt >= pairs[0][1])              return 0;
    if(kt <= pairs[pairs.length-1][1]) return 100;
    for(let i=0; i<pairs.length-1; i++){
        const [n0,kt0] = pairs[i], [n1,kt1] = pairs[i+1];
        if(kt <= kt0 && kt >= kt1){
            const f = (kt0-kt) / (kt0-kt1);
            return Math.round((n0 + f*(n1-n0)) / 8 * 100);
        }
    }
    return null;
}

/* =========================================================
   ОПРЕДЕЛЕНИЕ ТИПА ОБЛАЧНОСТИ по kt и динамике SR
========================================================= */
function detectCloudType(kt, elevDeg, precipRate, uv){
    if(kt == null || elevDeg == null) return null;

    const kt_oc  = getKtOc(elevDeg);
    const ktNorm = kt >= 0.85 ? 1 : kt <= kt_oc ? 0 : (kt - kt_oc) / (0.85 - kt_oc);

    let srStd = null, srTrend = null;
    if(typeof _histData !== "undefined" && _histData?.obs?.length >= 3){
        const vals = _histData.obs.slice(-12).map(o => o.solarRad).filter(v => v != null);
        if(vals.length >= 3){
            const mean = vals.reduce((a,b)=>a+b,0) / vals.length;
            srStd = Math.sqrt(vals.reduce((a,b)=>a+(b-mean)**2,0) / vals.length);
        }
        if(vals.length >= 6){
            const first = vals.slice(0,3).reduce((a,b)=>a+b,0)/3;
            const last3 = vals.slice(-3).reduce((a,b)=>a+b,0)/3;
            srTrend = last3 - first;
        }
    }

    const stable     = srStd != null && srStd < 12;
    const variable   = srStd != null && srStd >= 12 && srStd < 45;
    const convective = srStd != null && srStd >= 45;
    const highSun    = elevDeg >= 30;
    const midSun     = elevDeg >= 15;

    const trend = (srTrend != null && !convective && midSun)
        ? srTrend >  80 ? "↑ быстро рассеивается"
        : srTrend >  30 ? "↑ рассеивается"
        : srTrend < -80 ? "↓ быстро нарастает"
        : srTrend < -30 ? "↓ нарастает"
        : null
        : null;

    const uv_cs   = elevDeg / 9;
    const uvRatio = (uv != null && uv_cs > 0.5) ? uv / uv_cs : null;
    const uvHigh  = uvRatio != null && uvRatio >= 0.70;
    const uvMid   = uvRatio != null && uvRatio >= 0.35 && uvRatio < 0.70;
    const uvLow   = uvRatio != null && uvRatio < 0.35;

    const T = "Верхний ярус (6–13 км)";
    const M = "Средний ярус (2–6 км)";
    const L = "Нижний ярус (0–2 км)";
    const V = "Вертикального развития";

    if(precipRate > 0){
        if(convective) return { label:"Кучево-дождевые (Cb)", icon:"⛈️", tier:V, trend };
        return                { label:"Слоисто-дождевые (Ns)", icon:"🌧️", tier:L, trend };
    }

    if(ktNorm >= 0.92) return { label:"Ясно", icon:"☀️", tier:null, trend };

    if(ktNorm >= 0.72){
        if(midSun && (stable || uvHigh)) return { label:"Перистые (Ci/Cs)",             icon:"🌤️", tier:T, trend };
        if(midSun && uvMid)              return { label:"Высокослоистые тонкие (As)",    icon:"🌤️", tier:M, trend };
        if(convective)                   return { label:"Малооблачно (Cu)",              icon:"🌤️", tier:V, trend };
        return                                  { label:"Малооблачно",                   icon:"🌤️", tier:null, trend };
    }

    if(ktNorm >= 0.40){
        if(convective)          return { label:"Кучевые (Cu)",                icon:"⛅",  tier:V, trend };
        if(highSun && stable && uvHigh)
                                return { label:"Перисто-слоистые (Cs)",       icon:"🌥️", tier:T, trend };
        if(highSun && stable)   return { label:"Высокослоистые (As)",         icon:"🌥️", tier:M, trend };
        if(highSun && variable) return { label:"Высококучевые (Ac)",          icon:"🌥️", tier:M, trend };
        return                         { label:"Переменная облачность",        icon:"🌥️", tier:null, trend };
    }

    if(ktNorm >= 0.12){
        if(convective)          return { label:"Кучевые мощные (Cu)",         icon:"☁️",  tier:V, trend };
        if(highSun && uvMid)    return { label:"Высокослоистые плотные (As)", icon:"☁️",  tier:M, trend };
        if(highSun && stable)   return { label:"Высокослоистые плотные (As)", icon:"☁️",  tier:M, trend };
        if(highSun && variable) return { label:"Высококучевые плотные (Ac)",  icon:"☁️",  tier:M, trend };
        return                         { label:"Сплошная облачность",          icon:"☁️",  tier:null, trend };
    }

    if(highSun && uvLow && stable)  return { label:"Слоистые (St)",           icon:"🌫️", tier:L, trend };
    if(highSun && uvLow && variable)return { label:"Слоисто-кучевые (Sc)",    icon:"☁️",  tier:L, trend };
    if(highSun && stable)           return { label:"Слоистые (St)",           icon:"🌫️", tier:L, trend };
    if(highSun && variable)         return { label:"Слоисто-кучевые (Sc)",    icon:"☁️",  tier:L, trend };
    if(midSun  && stable)           return { label:"Слоистые (St)",           icon:"🌫️", tier:L, trend };
    if(convective)                  return { label:"Кучево-дождевые (Cb)",    icon:"⛈️",  tier:V, trend };
    return                                 { label:"Нижний ярус (St/Sc)",     icon:"🌫️", tier:L, trend };
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

    // Сглаженный SR: медиана последних 4 точек истории (~20 мин)
    let srSmooth = p.solarRad;
    if(typeof _histData !== "undefined" && _histData?.obs?.length >= 2){
        const recent = [
            ..._histData.obs.slice(-3).map(o => o.solarRad),
            p.solarRad
        ].filter(v => v != null);
        if(recent.length >= 2){
            const sorted = [...recent].sort((a,b) => a-b);
            srSmooth = sorted[Math.floor(sorted.length / 2)];
        }
    }
    const kt = (sun && sun.elevDeg > 0 && srSmooth != null)
        ? (() => { const cs = clearskyIrradiance(sun.elevDeg); return cs > 10 ? Math.min(1, srSmooth / cs) : 0; })()
        : null;
    const cloudPct = p.precipRate > 0 ? 100 : ktToCloudPct(kt, sun?.elevDeg);

    const dialHtml = (sun && moon) ? makeSkyDial(sun, moon, riseSet, lat, lon, obsDate, kt) : "";

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
    const cloudType = detectCloudType(kt, sun?.elevDeg, p.precipRate, p.uv);
    // ---- справочные данные облачности ----


const srHtml = p.solarRad != null ? `
    <div class="districtLine"><span>Солнечная радиация</span><span>${fmt0(p.solarRad," Вт/м²")}</span></div>
    ${cloudPct != null ? `<div class="districtLine"><span>Покрытие неба (оценочно)</span><span>~${cloudPct}%</span></div>` : ""}
    ${cloudType ? `
        <div class="districtLine"><span>Облачность (оценочно)</span><span>${cloudType.icon} ${cloudType.label}</span></div>
        ${cloudType.tier  ? `<div class="districtLine"><span style="color:#888;">↳ Ярус</span><span>${cloudType.tier}</span></div>` : ""}
        ${cloudType.trend ? `<div class="districtLine"><span style="color:#888;">↳ Динамика</span><span>${cloudType.trend}</span></div>` : ""}
    ` : ""}` : "";
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
   БЛОК: МОРЕ
========================================================= */
function makeMarineBlock(){
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
        

    const rows = [
        m.waveH      != null ? ["🌊 Волна",
            `${fV(m.waveH)} м · ${fDir(m.waveDir)}`
            + (m.wavePeakPer != null ? ` · Tп=${m.wavePeakPer.toFixed(0)} с`
               : m.wavePer   != null ? ` · T=${m.wavePer.toFixed(0)} с` : "")
        ] : null,
        m.swellH     != null ? ["〰️ Зыбь",
            `${fV(m.swellH)} м · ${fDir(m.swellDir)}`
            + (m.swellPer != null ? ` · T=${m.swellPer.toFixed(0)} с` : "")
        ] : null,
        m.windWaveH  != null ? ["💨 Ветровая волна",
            `${fV(m.windWaveH)} м · ${fDir(m.windWaveDir)}`
        ] : null,
        m.seaWindSpeed != null ? ["🌬️ Ветер над морем",
            `${fV(m.seaWindSpeed)} м/с · порывы ${fV(m.seaWindGust)} · ${fDir(m.seaWindDir)}`
        ] : null,
        m.currentV   != null && m.currentV > 0.05 ? ["🔄 Течение",
            `${fV(m.currentV)} м/с · ${fDir(m.currentDir)}`
        ] : null,
    ].filter(Boolean);

    if(!sstHtml && !rows.length) return "";

    const sourceTime = m.time ? (() => {
        const d = new Date(m.time);
        return isNaN(d) ? "" :
            " · " + d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});
    })() : "";

    return `
    <div style="margin-top:12px;border-top:1px solid #2a2a2a;padding-top:10px;">
        <div style="font-size:11px;color:#555;margin-bottom:8px;
                    text-transform:uppercase;letter-spacing:.5px;">
            Море · Чёрное море<span style="font-weight:400;letter-spacing:0;
            color:#333;">${sourceTime} · модель CMEMS</span>
        </div>
        ${warnHtml}
        ${sstHtml}
        <div class="pws-fields">
            
            ${rows.map(([k,v]) =>
                `<div class="districtLine"><span>${k}</span><span>${v}</span></div>`
            ).join("")}
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

    const rows = [];

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
            ${p.precipRate  != null ? precipRateIndicatorSvg(p.precipRate)        : ""}
            ${p.precipTotal != null ? precipTotalIndicatorSvg(p.precipTotal)      : ""}
        </div>

        ${rows.length ? `<div class="pws-fields">${rows.map(([k,v])=>`<div class="districtLine"><span>${k}</span><span>${v}</span></div>`).join("")}</div>` : ""}

        ${makeSolarWbgtBlock(p)}
        ${makeMarineBlock()}

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
    _histData  = null;    // ← добавить
    document.getElementById("pwsContent").innerHTML = `<div style="padding:20px;color:#888;text-align:center;">Загрузка...</div>`;
    loadAndRender();
    histLoad();
}

/* =========================================================
   ЗАГРУЗКА И РЕНДЕР
========================================================= */
async function loadAndRender(){
    const [stationResult] = await Promise.allSettled([
    fetchStation(_currentId),
    fetchEnsembleCloud(),
    fetchSynopCloud(),
    loadMarine()
]);
    const p = stationResult.status === "fulfilled"
        ? stationResult.value
        : { error: stationResult.reason?.message || "Ошибка" };
    renderPWSStation(p);
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
    await loadKtOcTable();
    await loadAndRender();
    startRefresh();
    if(typeof histLoad === "function") histLoad();
}

initPWSPage();
