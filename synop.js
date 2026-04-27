/* =========================================================
   SYNOP.JS — парсинг, загрузка и рендер SYNOP
   Зависит от: utils.js, indicators.js
========================================================= */

/* =========================================================
   1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПАРСИНГА
========================================================= */
function pressureFromGroup(group){
    if(!group) return null;
    const p = parseInt(group.slice(1), 10) / 10;
    if(Number.isNaN(p)) return null;
    // < 500 → добавляем 1000 (диапазон 1000–1049.9 гПа)
    // >= 500 → реальное значение (850–999.9 гПа)
    return p < 500 ? p + 1000 : p;
}

function signedTenths(group){
    if(!group || group.length !== 5) return null;
    const sign = group[1] === "1" ? -1 : 1;
    const val  = parseInt(group.slice(2), 10);
    if(Number.isNaN(val)) return null;
    return sign * val / 10;
}

/* =========================================================
   2. ПАРСИНГ SYNOP
========================================================= */
function parseSynop(line){
    const parts     = line.trim().split(/\s+/);
    const aaxxIndex = parts.indexOf("AAXX");
    if(aaxxIndex === -1) throw new Error("AAXX не найден");

    const yyggi    = parts[aaxxIndex + 1] || null;
    const station  = parts[aaxxIndex + 2] || null;
    const irixhvv  = parts[aaxxIndex + 3] || null; // iRIXhVV
    const windGroup= parts[aaxxIndex + 4] || null; // Nddff

    const bodyGroups = [], section333 = [], section444 = [], section555 = [];
    let currentSection = "main";

    for(let i = aaxxIndex + 5; i < parts.length; i++){
        const g = parts[i].replace(/=+$/, "");
        if(g === "333"){ currentSection = "333"; continue; }
        if(g === "444"){ currentSection = "444"; continue; }
        if(g === "555"){ currentSection = "555"; continue; }
        if(!g) continue;
        if(currentSection === "main")     bodyGroups.push(g);
        else if(currentSection === "333") section333.push(g);
        else if(currentSection === "444") section444.push(g);
        else if(currentSection === "555") section555.push(g);
    }

    /* ---- переменные ---- */
    let totalCloud = null, windDir = null, windSpeed = null;
    let lowCloudBase = null, visibility = null;
    let temp = null, dew = null;
    let stationPressure = null, seaPressure = null;
    let tendencyCode = null, tendencyValue = null;
    let precipGroup = null;
    let weatherNow = null, weatherPast1 = null, weatherPast2 = null;
    let cloudGroup = null, cloudTotalOkta = null;
    let cloudLowCode = null, cloudMidCode = null, cloudHighCode = null;

    // 333
    let tempMax = null, tempMin = null;
    let groundStateCode = null, groundTemp = null;
    let snowDepthCode = null, snowDepth = null;
    let evapCode = null, evapValue = null;
    let sunHours = null, maxGust333 = null;
    let weatherChange = [];
    // облака из секции 333 (отдельно от основного тела)
    let cloud333Group = null, cloud333N = null;
    let cloud333Low = null, cloud333Mid = null, cloud333High = null;

    // 444
    const specialClouds = [];

    // 555
    let tempMinSurface = null, dailyPrecip = null;
    let maxGust555 = null, sunHours555 = null;
    let phenomCodes = [];
    let sec555TempMax = null, sec555TempMin = null, sec555Temp2m = null;
    let surfStateCode555 = null;

    /* ---- Группа Nddff ---- */
    if(windGroup && /^\d{5}$/.test(windGroup)){
        totalCloud = safeNum(windGroup[0]);
        const rawDir = safeNum(windGroup.slice(1,3));
        windDir    = (rawDir === 0) ? null : rawDir * 10;
        windSpeed  = safeNum(windGroup.slice(3,5));
    }

    /* ---- Группа iRIXhVV ---- */
    if(irixhvv && irixhvv.length === 5){
        lowCloudBase = irixhvv[2] === "/" ? null : irixhvv[2];
        const vv     = irixhvv.slice(3,5);
        visibility   = vv.includes("/") ? null : vv;
    }

    /* ---- Основное тело ---- */
    for(const g of bodyGroups){
        if(/^1[01/]\d{3}$/.test(g))       temp            = signedTenths(g);
        else if(/^2[01/]\d{3}$/.test(g))  dew             = signedTenths(g);
        else if(/^3\d{4}$/.test(g))        stationPressure = pressureFromGroup(g);
        else if(/^4\d{4}$/.test(g))        seaPressure     = pressureFromGroup(g);
        else if(/^5\d{4}$/.test(g)){
            tendencyCode  = g[1];
            const tRaw    = parseInt(g.slice(2), 10) / 10;
            // Коды 5-8: итоговое падение → отрицательное значение
            const falling = ["5","6","7","8"].includes(g[1]);
            tendencyValue = falling ? -tRaw : tRaw;
        }
        else if(/^6\d{4}$/.test(g))        precipGroup = g;
        else if(/^7\d{4}$/.test(g)){
            weatherNow   = g.slice(1,3);
            weatherPast1 = g[3];   // W1: погода за период от 2 до 1 часа до срока
            weatherPast2 = g[4];   // W2: погода за последний час до срока
}
        else if(/^8[\d/]{4}$/.test(g)){
            cloudGroup     = g;
            cloudTotalOkta = g[1] === "/" ? null : safeNum(g[1]);
            cloudLowCode   = g[2] === "/" ? null : g[2];
            cloudMidCode   = g[3] === "/" ? null : g[3];
            cloudHighCode  = g[4] === "/" ? null : g[4];
        }
    }

    /* ---- Секция 333 ---- */
    for(const g of section333){
        const c = g.replace(/=+$/, "");
        if(!c || c.length < 4) continue;

        // 1sTTT — Tmax
        if(/^1[01]\d{3}$/.test(c))
            tempMax = signedTenths(c);

        // 2sTTT — Tmin
        else if(/^2[01]\d{3}$/.test(c))
            tempMin = signedTenths(c);

        // 3EsTT — состояние поверхности + температура почвы
        else if(/^3\d{4}$/.test(c)){
            groundStateCode = safeNum(c[1]);
            const sn  = c[2] === "1" ? -1 : 1;
            const val = parseInt(c.slice(3,5), 10);
            groundTemp = Number.isFinite(val) ? sn * val : null;
        }

        // 4Esss — высота снежного покрова
        else if(/^4\d{4}$/.test(c)){
            snowDepthCode = safeNum(c[1]);
            const d = parseInt(c.slice(2), 10);
            snowDepth = (d === 997) ? 0 : (d === 998 || d === 999) ? null : d;
        }

        // 55SSS — инсоляция (часы × 10)
        else if(/^55\d{3}$/.test(c))
            sunHours = parseInt(c.slice(2), 10) / 10;

        // 6EEEe — испарение (в секции 333 группа 6 — это испарение)
        else if(/^6\d{4}$/.test(c)){
            evapCode  = safeNum(c[4]);
            evapValue = parseInt(c.slice(1,4), 10) / 10;
        }

        // 7wwW1W2 — изменение погоды
        else if(/^7\d{4}$/.test(c))
            weatherChange.push(c.slice(1,3));

        // 8NhCLCMCH — облака из секции 333 сохраняем отдельно
        else if(/^8[\d/]{4}$/.test(c)){
            cloud333Group = c;
            cloud333N     = c[1] === "/" ? null : safeNum(c[1]);
            cloud333Low   = c[2] === "/" ? null : c[2];
            cloud333Mid   = c[3] === "/" ? null : c[3];
            cloud333High  = c[4] === "/" ? null : c[4];
            // Также обновляем основные если они ещё не заполнены
            if(!cloudLowCode)  cloudLowCode  = cloud333Low;
            if(!cloudMidCode)  cloudMidCode  = cloud333Mid;
            if(!cloudHighCode) cloudHighCode = cloud333High;
        }

        // 907ff — максимальный порыв ветра
        else if(/^907\d{2}$/.test(c))
            maxGust333 = parseInt(c.slice(3), 10);
    }

    /* ---- Секция 444 ---- */
    for(const g of section444){
        const c = g.replace(/=+$/, "");
        if(/^\d[\d/]\d{3}$/.test(c)){
            specialClouds.push({
                amount: safeNum(c[0]),
                form:   c[1] === "/" ? null : c[1],
                base:   parseInt(c.slice(2), 10)
            });
        }
    }

    /* ---- Секция 555 (КН-01) ---- */
    for(const g of section555){
        const c = g.replace(/=+$/, "");
        if(!c || c.length < 4) continue;

        // 1EsnTgTg — состояние поверхности + температура почвы (целые °C)
if(/^1[0-9][01]\d{2}$/.test(c)){
    surfStateCode555 = safeNum(c[1]);
    const sn  = c[2] === "1" ? -1 : 1;
    const val = parseInt(c.slice(3, 5), 10);
    if(Number.isFinite(val)) tempMinSurface = sn * val;
}
// 1/TgTgTg — только температура почвы, состояние не наблюдалось
else if(/^1\/\d{3}$/.test(c)){
    const val = parseInt(c.slice(2), 10);
    if(Number.isFinite(val)) tempMinSurface = val;
}

        // 2snTnTnTn — минимальная температура воздуха за ночь (десятые °C)
        else if(/^2[01]\d{3}$/.test(c)){
            const sn  = c[1] === "1" ? -1 : 1;
            const val = parseInt(c.slice(2), 10);
            sec555TempMin = Number.isFinite(val) ? sn * val / 10 : null;
        }

        // 3EsnTgTg — температура поверхности почвы
        // E (c[1]) — состояние, sn (c[2]) — знак, TgTg — целые °C
        else if(/^3[0-9][01]\d{2}$/.test(c)){
            groundStateCode = safeNum(c[1]);
            const sn  = c[2] === "1" ? -1 : 1;
            const val = parseInt(c.slice(3, 5), 10);
            groundTemp = Number.isFinite(val) ? sn * val : null;
        }
        // 4Esss — высота снежного покрова
        else if(/^4\d{4}$/.test(c) && snowDepth === null){
            snowDepthCode = safeNum(c[1]);
            const d = parseInt(c.slice(2), 10);
            snowDepth = (d === 997) ? 0 : (d === 998 || d === 999) ? null : d;
        }

        // 55SSS — инсоляция
        else if(/^55\d{3}$/.test(c))
            sunHours555 = parseInt(c.slice(2), 10) / 10;

        // 6RRRt — суточные осадки
        else if(/^6\d{4}$/.test(c)){
            const amt = parseInt(c.slice(1,4), 10);
            dailyPrecip = amt <= 988 ? amt : null;
        }

        // 7wwW — явления погоды
        else if(/^7\d{3,4}$/.test(c))
            phenomCodes.push(c.slice(1,3));

        // 907ff — порыв
        else if(/^907\d{2}$/.test(c))
            maxGust555 = parseInt(c.slice(3), 10);
    }

    const obsHour    = yyggi ? parseInt(yyggi.slice(2,4), 10) : null;
    const synopIsDay = Number.isFinite(obsHour) ? (obsHour >= 6 && obsHour < 18) : null;

    return {
        synopIsDay, raw: line, parts,
        yyggi, station, irixhvv, windGroup,
        bodyGroups, section333, section444, section555,

        temp, dew,
        stationPressure, seaPressure,
        tendencyCode, tendencyValue,
        precipGroup,
        weatherNow, weatherPast1, weatherPast2, weatherChange,
        cloudGroup, cloudTotalOkta,
        cloudLowCode, cloudMidCode, cloudHighCode,
        totalCloud, lowCloudBase, visibility,
        windDir, windSpeed,

        // 333
        tempMax, tempMin,
        groundStateCode, groundTemp,
        cloud333Group, cloud333N,
        cloud333Low, cloud333Mid, cloud333High,
        snowDepthCode, snowDepth,
        evapCode, evapValue,
        sunHours: sunHours ?? sunHours555 ?? null,
        maxGust333,
        maxGust555,
        weatherChange,

        // 444
        specialClouds,

        // 555
        tempMinSurface,
        surfStateCode555,
        sec555TempMax,
        sec555TempMin,
        sec555Temp2m,
        dailyPrecip,
        phenomCodes,
    };
}

/* =========================================================
   3. ЗАГРУЗКА SYNOP
========================================================= */
let db;

function initDB(){
    return new Promise((resolve, reject) => {
        const req = indexedDB.open("modelStats", 2);
        req.onupgradeneeded = e => {
            db = e.target.result;
            if(!db.objectStoreNames.contains("stats"))
                db.createObjectStore("stats", { keyPath: "time" });
        };
        req.onsuccess = e => { db = e.target.result; resolve(); };
        req.onerror = e => reject(new Error("IndexedDB: " + (e.target.error?.message || e.target.error)));
    });
}

async function recordExists(timeKey){
    if(!db) await initDB();
    const req = db.transaction("stats","readonly").objectStore("stats").getAll();
    return new Promise(res => {
        req.onsuccess = () => res(req.result.some(r => r.synopTime === timeKey));
        req.onerror = () => { res(false); };
    });
}

function saveProxyTime(proxyTimes, proxy, ms, limit=10){
    if(!proxyTimes[proxy]) proxyTimes[proxy] = [];
    proxyTimes[proxy].push(ms);
    if(proxyTimes[proxy].length > limit)
        proxyTimes[proxy] = proxyTimes[proxy].slice(-limit);
}

async function loadSynop(){
    const cacheBust = Date.now();
    const ogimet = `https://www.ogimet.com/display_synops2.php?lang=en&lugar=33837&tipo=ALL&ord=REV&nil=SI&fmt=txt&_=${cacheBust}`;

    const proxies = [
        "https://api.allorigins.win/raw?url=",
        "https://corsproxy.io/?",
        "https://proxy.cors.sh/",
        "https://cors.x2u.in/"
    ];

    const storageKey = "synopProxyTimes";
    let proxyTimes = JSON.parse(localStorage.getItem(storageKey) || "{}");
    proxies.forEach(p => { if(!proxyTimes[p]) proxyTimes[p] = []; });

    function extractKey(text){
        for(const l of text.split("\n").map(s => s.trim()).filter(Boolean)){
            const m = l.match(/^(\d{12})\s+AAXX\b/);
            if(m) return m[1];
        }
        return null;
    }

    function extractLine(text){
        const lines = text.split("\n").map(s => s.trim()).filter(Boolean);
        const start = lines.findIndex(l => /(AAXX|BBXX|OOXX)\b/.test(l));
        if(start === -1) return null;
        const out = [];
        for(let i = start; i < lines.length; i++){
            if(i !== start && /(AAXX|BBXX|OOXX)\b/.test(lines[i])) break;
            out.push(lines[i]);
        }
        return out.join(" ");
    }

    const requests = proxies.map(proxy => new Promise(async (resolve, reject) => {
        const ctrl  = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 8000);
        const t0    = performance.now();
        try {
            const r    = await fetch(proxy + encodeURIComponent(ogimet), { signal: ctrl.signal, cache: "no-store" });
            if(!r.ok) throw new Error("HTTP " + r.status);
            const text = await r.text();
            if(!text?.trim()) throw new Error("Пустой ответ");
            const telegramKey = extractKey(text);
            const line        = extractLine(text);
            if(!telegramKey) throw new Error("Ключ телеграммы не найден");
            if(!line)        throw new Error("SYNOP не найден");
            const ms = Math.round(performance.now() - t0);
            saveProxyTime(proxyTimes, proxy, ms);
            resolve({ proxy, line, telegramKey, ms });
        } catch(e){
            saveProxyTime(proxyTimes, proxy, Math.round(performance.now() - t0));
            reject(e);
        } finally {
            clearTimeout(timer);
        }
    }));

    const settled = await Promise.allSettled(requests);
    localStorage.setItem(storageKey, JSON.stringify(proxyTimes));

    const ok = settled.filter(r => r.status === "fulfilled").map(r => r.value);
    if(!ok.length) throw new Error("Все прокси SYNOP не ответили");

    ok.sort((a,b) => a.telegramKey !== b.telegramKey
        ? b.telegramKey.localeCompare(a.telegramKey)
        : a.ms - b.ms);

    const best = ok[0];
    if(!db) await initDB();
    await recordExists(best.telegramKey);
    return parseSynop(best.line);
}

/* =========================================================
   4. РЕНДЕР SYNOP
========================================================= */
function renderSynop(d){
    const main      = document.getElementById("main");
    const localTime = localTimeFromSynopYYGGi(d.yyggi);
    const wx        = synopWeatherText(d.weatherNow);
    const wxIco     = synopWeatherIcon(d.weatherNow, d.synopIsDay);
    const feelsLike = calcFeelsLike(d.temp, d.windSpeed, d.dew);
    const humidity  = calcRelativeHumidity(d.temp, d.dew);

    /* ---------- осадки основного тела ---------- */
    const precipLine = d.precipGroup
        ? row("Осадки", precipitationText(d.yyggi?.[4], d.precipGroup))
        : "";

    /* ---------- СЕКЦИЯ 333 ---------- */
    const rows333 = [
        d.tempMax    != null ? row("Максимальная температура", fmt1(d.tempMax,"°C")) : "",
        d.cloud333Group != null ? row("Облачность (уточнение)",
            (d.cloud333N != null ? cloudAmountText(d.cloud333N) + " · " : "") +
            [cloudGenusLow(d.cloud333Low), cloudGenusMid(d.cloud333Mid), cloudGenusHigh(d.cloud333High)]
            .filter(v => v && v !== "-").join(" / ") || "-"
        ) : "",
        d.tempMin    != null ? row("Минимальная температура",  fmt1(d.tempMin,"°C")) : "",
        d.groundTemp != null ? row("Температура почвы",
            fmt1(d.groundTemp,"°C") + groundStateLabel(d.groundStateCode)) : "",
        d.snowDepth  != null ? row("Снежный покров",
            snowDepthLabel(d.snowDepthCode, d.snowDepth)) : "",
        d.snowDepth === 0    ? row("Снежный покров", "снега нет") : "",
        d.evapValue  != null ? row("Испарение",
            fmt1(d.evapValue," мм") + evapTypeLabel(d.evapCode)) : "",
        d.sunHours   != null ? row("Солнечное сияние",          fmt1(d.sunHours," ч")) : "",
        d.maxGust333 != null ? row("Максимальный порыв ветра",  fmt0(d.maxGust333," м/с")) : "",
        ...(d.weatherChange || []).filter(Boolean).map((wc, i) =>
            row(`Погода (изменение ${i+1})`, escapeHtml(synopWeatherText(wc)))),
    ].filter(Boolean).join("");

    const sec333Html = rows333
        ? `<div class="card" style="margin-top:12px;">
               <div class="cardTitle">Дополнительные данные (сек. 333)</div>
               ${rows333}
           </div>`
        : "";

    /* ---------- СЕКЦИЯ 444 ---------- */
    let sec444Html = "";
    if(d.specialClouds?.length){
        const rows444 = d.specialClouds.map((sc, i) =>
            row(
                `Особое облако ${i+1} · N=${sc.amount ?? "/"}`,
                `${cloudFormText444(sc.form)} · основание ~${sc.base * 30} м`
            )
        ).join("");
        sec444Html = `<div class="card" style="margin-top:12px;">
            <div class="cardTitle">Особые формы облаков (сек. 444)</div>
            ${rows444}
        </div>`;
    }

    /* ---------- СЕКЦИЯ 555 ---------- */
    const rows555 = [
        // 1EsnT'gT'g — мин. т° поверхности почвы/травы (целые °C)
        d.tempMinSurface != null ? row(
    "Т° поверхности почвы (травы)",
    fmt0(d.tempMinSurface,"°C") + groundStateLabel(d.surfStateCode555)
) : "",
d.sec555TempMin  != null ? row("Мин. т° воздуха за ночь",  fmt1(d.sec555TempMin,"°C")) : "",
d.sec555Temp2m   != null ? row("Т° воздуха на 2 м (доп.)", fmt1(d.sec555Temp2m,"°C")) : "",
// 907ff — порыв ветра
d.maxGust555     != null ? row("Максимальный порыв ветра",  fmt0(d.maxGust555," м/с"))  : "",
        // 6RRRtR — суточные осадки
        d.dailyPrecip    != null ? row("Суточные осадки",           fmt0(d.dailyPrecip," мм"))   : "",
        ...(d.phenomCodes || []).filter(Boolean).map((pc, i) =>
            row(`Явление за период ${i+1}`, escapeHtml(synopWeatherText(pc)))),
    ].filter(Boolean).join("");

    const sec555Html = rows555
        ? `<div class="card" style="margin-top:12px;">
               <div class="cardTitle">Региональные данные (сек. 555)</div>
               ${rows555}
           </div>`
        : "";

    /* ---------- итоговый HTML ---------- */
    main.innerHTML = `
        <div class="cardTitle">SYNOP · станция ${escapeHtml(d.station || "-")}</div>
        <div class="subTitle">Наблюдение: ${escapeHtml(localTime)}</div>

        <div class="heroTempRow" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">
            <div class="heroTempLeft">
                <div class="small">Температура воздуха</div>
                <div class="heroTemp ${tempClass(d.temp)}">${fmt1(d.temp,"°C")}</div>
                <div class="heroFeels">Ощущается как: <b>${fmt1(feelsLike,"°C")}</b></div>
            </div>
            <div class="heroWeather" style="display:flex;align-items:center;gap:10px;">
                <span class="wxIcon" style="font-size:56px;line-height:1;">${wxIco}</span>
                <span style="font-size:16px;">${escapeHtml(wx)}</span>
            </div>
        </div>

        <!-- Индикаторы 2×2: температура | давление / ветер | влажность -->
        <div class="ind-grid-2x2" style="margin-top:16px;">
            ${tempIndicatorSvg(d.temp, feelsLike)}
            ${humidityIndicatorSvg(humidity)}
            ${windIndicatorSvg(d)}
            ${pressureIndicatorSvg(d)}
            
            
        </div>

        <div class="card" style="margin-top:16px;">
            <div class="cardTitle">Кратко</div>
            ${row("Температура",       fmt1(d.temp,"°C"))}
            ${row("Точка росы",        fmt1(d.dew,"°C"))}
            ${row("Отн. влажность",    fmt0(humidity," %"))}
            ${row("Ветер",
                fmt0(d.windSpeed," м/с") + " " +
                escapeHtml(degToText(d.windDir)) + " " +
                windArrow(d.windDir))}
            ${(d.maxGust333 ?? d.maxGust555) != null
                ? row("Порыв ветра", fmt0(d.maxGust333 ?? d.maxGust555," м/с")) : ""}
            ${row("Давление (станц.)", fmt1(d.stationPressure," гПа"))}
            ${row("Давление QNH",      fmt1(d.seaPressure," гПа"))}
            ${row("Барич. тенденция",
                escapeHtml(tendencyText(d.tendencyCode)) +
                (d.tendencyValue != null
                    ? ` ${d.tendencyValue > 0 ? "+" : ""}${d.tendencyValue.toFixed(1)} гПа`
                    : ""))}
            ${precipLine}
            ${row("Явления",           escapeHtml(wx) || "-")}
            ${(d.weatherPast1 && d.weatherPast1 !== "0") ? row("Погода W1", escapeHtml(synopPastWeatherText(d.weatherPast1))) : ""}
            ${(d.weatherPast2 && d.weatherPast2 !== "0") ? row("Погода W2", escapeHtml(synopPastWeatherText(d.weatherPast2))) : ""}
            ${d.tempMax  != null ? row("Макс. температура", fmt1(d.tempMax,"°C"))  : ""}
            ${d.tempMin  != null ? row("Мин. температура",  fmt1(d.tempMin,"°C"))  : ""}
            ${d.sunHours != null ? row("Солнечное сияние",  fmt1(d.sunHours," ч")) : ""}
            ${row("Видимость",         visibilityText(d.visibility))}
        </div>

        <div class="card" style="margin-top:12px;">
            <div class="cardTitle">Облака</div>
            ${row("Общая облачность",  escapeHtml(cloudAmountText(d.totalCloud)))}
            ${row("Кол-во по Nh",
                d.cloudTotalOkta != null
                    ? escapeHtml(cloudAmountText(d.cloudTotalOkta))
                    : "-")}
            ${cloudRow("Нижний ярус",  "low",  d.cloudLowCode,  cloudGenusLow(d.cloudLowCode))}
            ${cloudRow("Средний ярус", "mid",  d.cloudMidCode,  cloudGenusMid(d.cloudMidCode))}
            ${cloudRow("Верхний ярус", "high", d.cloudHighCode, cloudGenusHigh(d.cloudHighCode))}
            ${row("Основание нижних",  lowCloudBaseText(d.lowCloudBase))}
        </div>

        ${sec333Html}
        ${sec444Html}
        ${sec555Html}

        <details style="margin-top:12px;">
            <summary>Полная расшифровка</summary>
            <div class="details-body"><div>
            ${row("YYGGi",               escapeHtml(d.yyggi || "-"))}
            ${row("Станция",             escapeHtml(d.station || "-"))}
            ${row("iRIXhVV",             escapeHtml(d.irixhvv || "-"))}
            ${row("Nddff",               escapeHtml(d.windGroup || "-"))}
            ${row("Давление на станции", fmt1(d.stationPressure," гПа"))}
            ${row("Давление QNH",        fmt1(d.seaPressure," гПа"))}
            ${row("Группа 8NhCLCMCH",   escapeHtml(d.cloudGroup || "-"))}
            ${row("Группа осадков",      escapeHtml(d.precipGroup || "-"))}
            </div></div>
        </details>

        <details style="margin-top:8px;">
            <summary>Сырые данные телеграммы</summary>
            <div class="details-body"><div>
            <div class="codeBlock">${escapeHtml(d.raw)}</div>
            ${row("Основные группы", escapeHtml(d.bodyGroups.join(" ")) || "-")}
            ${row("Секция 333",      escapeHtml(d.section333.join(" ")) || "-")}
            ${row("Секция 444",      escapeHtml(d.section444.join(" ")) || "-")}
            ${row("Секция 555",      escapeHtml(d.section555.join(" ")) || "-")}
            </div></div>
        </details>
    `;
}

/* =========================================================
   5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ РЕНДЕРА
========================================================= */
function row(label, value){
    return `<div class="row">
        <div class="label">${label}</div>
        <div class="value">${value ?? "-"}</div>
    </div>`;
}

function groundStateLabel(code){
    const map = {
        0:"сухая", 1:"влажная", 2:"мокрая", 3:"залита водой",
        4:"замёрзшая", 5:"гололёд", 6:"сухой рыхлый снег",
        7:"сжатый снег", 8:"мокрый снег", 9:"лёд"
    };
    return (code != null && code in map) ? ` · поверхность ${map[code]}` : "";
}

function snowDepthLabel(code, depth){
    if(depth == null) return "не измерялось";
    if(depth === 0)   return "снега нет";
    return `${depth} см`;
}

function evapTypeLabel(code){
    if(code === 0) return " (открытый испаритель)";
    if(code === 1) return " (с поверхности почвы/травы)";
    return "";
}

function lowCloudBaseText(code){
    if(code == null) return "-";
    const map = {
        "0":"< 50 м", "1":"50–100 м", "2":"100–200 м",
        "3":"200–300 м", "4":"300–600 м", "5":"600–1000 м",
        "6":"1000–1500 м", "7":"1500–2000 м", "8":"2000–2500 м",
        "9":"≥ 2500 м или облаков нет"
    };
    return map[String(code)] || `код ${code}`;
}

function cloudFormText444(code){
    if(code == null) return "форма не определена";
    const map = {
        "0":"Перисто-кучевые (Cc)", "1":"Перистые (Ci)",
        "2":"Перисто-слоистые (Cs)", "3":"Высококучевые (Ac)",
        "4":"Высокослоистые (As)", "5":"Слоисто-дождевые (Ns)",
        "6":"Слоисто-кучевые (Sc)", "7":"Слоистые (St)",
        "8":"Кучевые (Cu)", "9":"Кучево-дождевые (Cb)"
    };
    return map[String(code)] || `код ${code}`;
}

/* =========================================================
   6. UI-ОБЁРТКИ
========================================================= */
async function loadSynopUI(){
    const btn = document.getElementById("btnSynop");
    btn.disabled = true;
    setMainStatus("⏳ Загрузка SYNOP...", true);

    try {
        const synop = await loadSynop();
        renderSynop(synop);
        try { localStorage.setItem("synopCachedHTML", document.getElementById("main").innerHTML); } catch(e){}
        var now = new Date().toLocaleString("ru");
        localStorage.setItem("lastSynopUpdate", now);
        setMainStatus("✅ Обновлено: " + now);
        if(synop.seaPressure != null){
            localStorage.setItem("synopLastPressure", JSON.stringify({
                pressure: synop.seaPressure,
                ts:       Date.now(),
                yyggi:    synop.yyggi || null
            }));
        }
        if(typeof calibratePWSBySynop === "function"){
            calibratePWSBySynop(synop.seaPressure);
        }
    } catch(e){
        setMainStatus("❌ Ошибка: " + (e instanceof Error ? e.message : String(e)));
        document.getElementById("main").innerHTML =
            '<div class="cardTitle">SYNOP</div>' +
            '<div class="small">Ошибка загрузки: ' + escapeHtml(e && e.message ? e.message : String(e)) + '</div>';
    } finally {
        btn.disabled = false;
    }
}

function setMainStatus(msg, spinning) {
    var el = document.getElementById("lastUpdate");
    if (!el) return;
    el.innerHTML = '<span>' + (spinning ? '<span class="spin">⏳</span> ' : '') + msg + '</span>';
    el.classList.remove("running");
    requestAnimationFrame(function(){ requestAnimationFrame(function(){
        var s = el.querySelector("span");
        if (s && s.scrollWidth > el.clientWidth) el.classList.add("running");
    }); });
}