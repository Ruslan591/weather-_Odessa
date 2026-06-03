function weatherCode(code, hour, cloud, rain, snow){
    const isDay = hour >= 6 && hour < 21;
    if(snow > 0)   return { icon:"🌨️", text:"Снег" };
    if(code >= 95) return { icon:"⛈️",  text:"Гроза" };
    if(rain > 0.5) return { icon:"🌧️", text:"Дождь" };
    if(code >= 80) return { icon:"🌦️", text:"Ливень" };
    if(code >= 71) return { icon:"🌨️", text:"Снегопад" };
    if(code >= 61) return { icon:"🌧️", text:"Дождь" };
    if(code >= 51) return { icon:"🌦️", text:"Морось" };
    if(code >= 45) return { icon:"🌫️", text:"Туман" };
    if(cloud > 80) return { icon:"☁️",  text:"Пасмурно" };
    if(cloud > 40) return { icon: isDay ? "⛅" : "🌙☁️", text:"Облачно" };
    return { icon: isDay ? "☀️" : "🌙", text:"Ясно" };
}

function comfortLevel(h){
    const t    = h.temperature_2m;
    const feel = h.apparent_temperature;
    const w    = h.wind_speed_10m;
    const gust = h.wind_gusts_10m ?? w;
    const r    = (h.rain ?? 0) + (h.showers ?? 0);
    const snow = h.snowfall ?? 0;
    const rh   = h.relative_humidity_2m ?? 50;
    const vis  = h.visibility ?? 10000;
    const code = h.weather_code ?? 0;

    if(code >= 95)               return { comfort:"Гроза ⚡",       color:"#f9ca24" };
    if(snow > 1)                 return { comfort:"Снегопад",        color:"#a8d8ea" };
    if(vis < 200)                return { comfort:"Густой туман",    color:"#b2bec3" };
    if(r > 5)                    return { comfort:"Сильный дождь",   color:"#2980b9" };
    if(feel < -15)               return { comfort:"Сильный мороз",   color:"#74b9ff" };
    if(feel < -5)                return { comfort:"Морозно",          color:"#a8d8ea" };
    if(feel > 37)                return { comfort:"Опасная жара",     color:"#d63031" };
    if(feel > 32)                return { comfort:"Очень жарко",      color:"#ff6b6b" };
    if(r > 0.5)                  return { comfort:"Дождливо",         color:"#4a90d9" };
    if(gust > 15)                return { comfort:"Шквалы",        color:"#fd9644" };
    if(w > 10)                   return { comfort:"Ветренно",          color:"#ffd166" };
    if(t > 26 && rh > 75)       return { comfort:"Душно",            color:"#e17055" };
    if(t < 0)                    return { comfort:"Морозно",          color:"#a8d8ea" };
    if(t < 8)                    return { comfort:"Холодно",          color:"#74b9ff" };
    if(t < 14)                   return { comfort:"Прохладно",        color:"#55efc4" };
    if(t <= 25)                  return { comfort:"Комфортно",        color:"#5fe08f" };
    if(t <= 30)                  return { comfort:"Тепло",            color:"#fdcb6e" };
    return                              { comfort:"Жарко",            color:"#ff6b6b" };
}

// =============================================
// МОРСКОЙ API
// =============================================
async function loadMarine(){
    // Точка в Чёрном море у Одессы (~8 км от берега)
    const url = "https://marine-api.open-meteo.com/v1/marine" +
        "?latitude=46.35&longitude=30.90" +
        "&hourly=wave_height,wave_direction,wave_period,wind_wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature" +
        "&timezone=auto&forecast_days=7";
    try {
        const r = await fetch(url);
        if(!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        if(!data.hourly || !data.hourly.time){ window._marineByTime = null; return; }
        const mh = data.hourly;
        window._marineByTime = {};
        mh.time.forEach((t, i) => {
            window._marineByTime[t] = {
                wave_height:             mh.wave_height?.[i]             ?? null,
                wave_direction:          mh.wave_direction?.[i]          ?? null,
                wave_period:             mh.wave_period?.[i]             ?? null,
                wind_wave_height:        mh.wind_wave_height?.[i]        ?? null,
                swell_wave_height:       mh.swell_wave_height?.[i]       ?? null,
                swell_wave_period:       mh.swell_wave_period?.[i]       ?? null,
                sea_surface_temperature: mh.sea_surface_temperature?.[i] ?? null,
            };
        });
    } catch(e) {
        console.warn("Marine API error:", e.message);
        window._marineByTime = null;
    }
}

// =============================================
// LOAD
// =============================================
async function load(){
    if (weatherModel === "ensemble") { loadEnsemble(); return; }
    loadMarine(); // параллельно, не await
    const apiForecastDays = Math.max(5, Math.ceil(forecastHours / 24) + 1);
    const API = `https://api.open-meteo.com/v1/forecast?latitude=46.43&longitude=30.74&hourly=temperature_2m,apparent_temperature,pressure_msl,relative_humidity_2m,weather_code,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation,precipitation_probability,showers,snowfall,snow_depth,shortwave_radiation,direct_radiation,diffuse_radiation,dew_point_2m,runoff,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,cape,uv_index,lifted_index,convective_inhibition,temperature_925hPa,temperature_850hPa,temperature_700hPa,temperature_500hPa,temperature_300hPa,temperature_250hPa,temperature_200hPa,temperature_150hPa,temperature_100hPa,temperature_50hPa,temperature_30hPa,temperature_10hPa,dewpoint_850hPa,dewpoint_700hPa,windspeed_925hPa,windspeed_850hPa,windspeed_700hPa,windspeed_500hPa,windspeed_300hPa,windspeed_250hPa,windspeed_200hPa,winddirection_925hPa,winddirection_850hPa,winddirection_700hPa,winddirection_500hPa,winddirection_300hPa,winddirection_250hPa,winddirection_200hPa,geopotential_height_925hPa,geopotential_height_850hPa,geopotential_height_700hPa,geopotential_height_500hPa,geopotential_height_300hPa,geopotential_height_250hPa,geopotential_height_200hPa,geopotential_height_150hPa,geopotential_height_100hPa,geopotential_height_50hPa,geopotential_height_30hPa,geopotential_height_10hPa,vertical_velocity_500hPa,vertical_velocity_700hPa,vertical_velocity_850hPa,relative_humidity_925hPa,relative_humidity_850hPa,relative_humidity_700hPa,relative_humidity_500hPa,relative_humidity_300hPa,cloud_cover_925hPa,cloud_cover_850hPa,cloud_cover_700hPa,cloud_cover_500hPa,cloud_cover_300hPa&models=${weatherModel}&timezone=auto&forecast_days=${apiForecastDays}&wind_speed_unit=ms`;
    let data;
    try {
        const r = await fetch(API);
        if(!r.ok) throw new Error(`HTTP ${r.status}`);
        data = await r.json();
    } catch(e) {
        document.getElementById("forecast").innerHTML =
            `<div style="padding:20px;text-align:center;color:#ff8f43;">
                ⚠️ Ошибка загрузки прогноза: ${e.message}<br>
                <span style="font-size:12px;color:#666;margin-top:6px;display:block;">
                    Модель: ${weatherModel} · Попробуйте обновить страницу
                </span>
             </div>`;
        return;
    }
    const h = data.hourly;
    if(!h){
        document.getElementById("forecast").innerHTML =
            `<div style="padding:20px;text-align:center;color:#ff8f43;">⚠️ Нет данных от API</div>`;
        return;
    }

    const hours = h.time.map((t, i) => ({
        time:                  t,
        temperature_2m:        h.temperature_2m[i],
        apparent_temperature:  h.apparent_temperature[i],
        pressure_msl:          h.pressure_msl[i],
        relative_humidity_2m:  h.relative_humidity_2m[i],
        weather_code:          h.weather_code[i],
        visibility:            h.visibility[i],
        wind_speed_10m:        h.wind_speed_10m[i],
        wind_gusts_10m:        h.wind_gusts_10m[i],
        wind_direction_10m:    h.wind_direction_10m[i],
        rain:                  h.precipitation[i] || 0,
        showers:               h.showers[i]       || 0,
        precip_prob:           h.precipitation_probability?.[i] ?? null,
        snowfall:              h.snowfall[i],
        snow_depth:            h.snow_depth[i],
        shortwave_radiation:   h.shortwave_radiation[i],
        direct_radiation:      h.direct_radiation[i],
        diffuse_radiation:     h.diffuse_radiation[i],
        dew_point_2m:          h.dew_point_2m[i],
        runoff:                h.runoff[i],
        cloud_cover:           h.cloud_cover[i],
        cloud_cover_low:       h.cloud_cover_low[i],
        cloud_cover_mid:       h.cloud_cover_mid[i],
        cloud_cover_high:      h.cloud_cover_high[i],
        cape:                  h.cape?.[i] ?? null,
        uv_index:              h.uv_index?.[i] ?? null,
        lifted_index:          h.lifted_index?.[i] ?? null,
        convective_inhibition: h.convective_inhibition?.[i] ?? null,
        temperature_925hPa:          h.temperature_925hPa?.[i]          ?? null,
        temperature_850hPa:          h.temperature_850hPa?.[i]          ?? null,
        temperature_700hPa:          h.temperature_700hPa?.[i]          ?? null,
        temperature_500hPa:          h.temperature_500hPa?.[i]          ?? null,
        temperature_300hPa:          h.temperature_300hPa?.[i]          ?? null,
        temperature_250hPa:          h.temperature_250hPa?.[i]          ?? null,
        temperature_200hPa:          h.temperature_200hPa?.[i]          ?? null,
        temperature_150hPa:          h.temperature_150hPa?.[i]          ?? null,
        temperature_100hPa:          h.temperature_100hPa?.[i]          ?? null,
        temperature_50hPa:           h.temperature_50hPa?.[i]           ?? null,
        temperature_30hPa:           h.temperature_30hPa?.[i]           ?? null,
        temperature_10hPa:           h.temperature_10hPa?.[i]           ?? null,
        dewpoint_850hPa:             h.dewpoint_850hPa?.[i]             ?? null,
        dewpoint_700hPa:             h.dewpoint_700hPa?.[i]             ?? null,
        windspeed_925hPa:            h.windspeed_925hPa?.[i]            ?? null,
        windspeed_850hPa:            h.windspeed_850hPa?.[i]            ?? null,
        windspeed_700hPa:            h.windspeed_700hPa?.[i]            ?? null,
        windspeed_500hPa:            h.windspeed_500hPa?.[i]            ?? null,
        windspeed_300hPa:            h.windspeed_300hPa?.[i]            ?? null,
        windspeed_250hPa:            h.windspeed_250hPa?.[i]            ?? null,
        windspeed_200hPa:            h.windspeed_200hPa?.[i]            ?? null,
        winddirection_925hPa:        h.winddirection_925hPa?.[i]        ?? null,
        winddirection_850hPa:        h.winddirection_850hPa?.[i]        ?? null,
        winddirection_700hPa:        h.winddirection_700hPa?.[i]        ?? null,
        winddirection_500hPa:        h.winddirection_500hPa?.[i]        ?? null,
        winddirection_300hPa:        h.winddirection_300hPa?.[i]        ?? null,
        winddirection_250hPa:        h.winddirection_250hPa?.[i]        ?? null,
        winddirection_200hPa:        h.winddirection_200hPa?.[i]        ?? null,
        geopotential_height_925hPa:  h.geopotential_height_925hPa?.[i]  ?? null,
        geopotential_height_850hPa:  h.geopotential_height_850hPa?.[i]  ?? null,
        geopotential_height_700hPa:  h.geopotential_height_700hPa?.[i]  ?? null,
        geopotential_height_500hPa:  h.geopotential_height_500hPa?.[i]  ?? null,
        geopotential_height_300hPa:  h.geopotential_height_300hPa?.[i]  ?? null,
        geopotential_height_250hPa:  h.geopotential_height_250hPa?.[i]  ?? null,
        geopotential_height_200hPa:  h.geopotential_height_200hPa?.[i]  ?? null,
        geopotential_height_150hPa:  h.geopotential_height_150hPa?.[i]  ?? null,
        geopotential_height_100hPa:  h.geopotential_height_100hPa?.[i]  ?? null,
        geopotential_height_50hPa:   h.geopotential_height_50hPa?.[i]   ?? null,
        geopotential_height_30hPa:   h.geopotential_height_30hPa?.[i]   ?? null,
        geopotential_height_10hPa:   h.geopotential_height_10hPa?.[i]   ?? null,
        vertical_velocity_500hPa:    h.vertical_velocity_500hPa?.[i]    ?? null,
        vertical_velocity_700hPa:    h.vertical_velocity_700hPa?.[i]    ?? null,
        vertical_velocity_850hPa:    h.vertical_velocity_850hPa?.[i]    ?? null,
        relative_humidity_925hPa:    h.relative_humidity_925hPa?.[i]    ?? null,
        relative_humidity_850hPa:    h.relative_humidity_850hPa?.[i]    ?? null,
        relative_humidity_700hPa:    h.relative_humidity_700hPa?.[i]    ?? null,
        relative_humidity_500hPa:    h.relative_humidity_500hPa?.[i]    ?? null,
        relative_humidity_300hPa:    h.relative_humidity_300hPa?.[i]    ?? null,
        cloud_cover_925hPa:          h.cloud_cover_925hPa?.[i]          ?? null,
        cloud_cover_850hPa:          h.cloud_cover_850hPa?.[i]          ?? null,
        cloud_cover_700hPa:          h.cloud_cover_700hPa?.[i]          ?? null,
        cloud_cover_500hPa:          h.cloud_cover_500hPa?.[i]          ?? null,
        cloud_cover_300hPa:          h.cloud_cover_300hPa?.[i]          ?? null,
    }));

    window._fcAllHours = hours;

    const nowTime    = Date.now();
    const timesDates = h.time.map(t => new Date(t));
    const hoursToShow = forecastHours;

    let startIndex = timesDates.findIndex(t => t.getTime() >= nowTime);
    if(startIndex === -1) startIndex = 0;
    startIndex = Math.max(0, startIndex - 1);
    const endIndex = Math.min(startIndex + hoursToShow, hours.length);

    let lastValidIndex = hours.length - 1;
    for(let i = hours.length - 1; i >= 0; i--){
        if(hours[i].temperature_2m != null){ lastValidIndex = i; break; }
    }
    const endIndex2 = Math.min(endIndex, lastValidIndex + 1);

    _fcHours = hours.slice(startIndex, endIndex2);
    _fcTimes = h.time.slice(startIndex, endIndex2);
    window._fcAllHours = hours;
    window._fcAllTimes = h.time;

    buildFcParamRow();
    buildFcDayRow();
    renderForecastChart(_fcHours, _fcTimes);
    renderAlertsBlock(_fcHours);
    var _dbg = document.getElementById("ensembleDebug");
    if (_dbg) { _dbg.style.display = "none"; _dbg.innerHTML = ""; }

    const lastDayKey = h.time[endIndex2 - 1].slice(0, 10);
const fullDayEnd = h.time.findLastIndex(t => t.slice(0, 10) === lastDayKey) + 1;
renderForecastDays(hours.slice(0, fullDayEnd), h.time.slice(0, fullDayEnd));
}

function renderForecastDays(hours, times) {
    const nowDate  = new Date();
    const nowHr    = nowDate.getHours();
    const todayKey = `${nowDate.getFullYear()}-${String(nowDate.getMonth()+1).padStart(2,'0')}-${String(nowDate.getDate()).padStart(2,'0')}`;

    const byDay = {};
    hours.forEach(h => {
        const key = h.time.slice(0, 10);
        if(!byDay[key]) byDay[key] = [];
        byDay[key].push(h);
    });

    let html = "";
    Object.keys(byDay).sort().forEach((dayKey, di) => {
        if(dayKey < todayKey) return;
        const dayHoursCheck = byDay[dayKey];
        const hasData = dayHoursCheck.some(h => h.temperature_2m != null);
        if(!hasData) return;
        const dayHours  = byDay[dayKey];
        const dayDate   = new Date(dayKey + "T12:00:00");
        const isToday   = dayKey === todayKey;
        const hasPeriodsWithData = PERIODS.filter(p =>
            dayHoursCheck.some(h => p.hours.includes(new Date(h.time).getHours()) && h.temperature_2m != null)
        );
        if(!isToday && hasPeriodsWithData.length < 3) return;
        const dayLabel  = isToday
            ? `Сегодня, ${dayDate.getDate()} ${MON_NAMES[dayDate.getMonth()]}`
            : `${DAY_NAMES[dayDate.getDay()]}, ${dayDate.getDate()} ${MON_NAMES[dayDate.getMonth()]}`;

        const nowPeriodId = currentPeriodId(nowHr);
        const periodOrder = ["night","morn","day","eve"];
        const futureHours = isToday
            ? dayHours.filter(h => {
                const hr = new Date(h.time).getHours();
                const pId = currentPeriodId(hr);
                return periodOrder.indexOf(pId) >= periodOrder.indexOf(nowPeriodId);
            })
            : dayHours;
        const dayAgg = aggregateDay(futureHours.length ? futureHours : dayHours);
        const { tMin, tMax, avgDir, avgSpd, precip, snow, wx, comfort, comfortColor } = dayAgg;

        const defaultPeriod = isToday ? currentPeriodId(nowHr) : "day";

        const visiblePeriods = PERIODS.filter(p => {
            if(!isToday) return true;
            return periodOrder.indexOf(p.id) >= periodOrder.indexOf(nowPeriodId);
        });

        const periodsHtml = visiblePeriods.map(p => {
            const periodHrs = dayHours.filter(h => p.hours.includes(new Date(h.time).getHours()));
            if (!periodHrs.length) return "";
            const hasData = periodHrs.some(h => h.temperature_2m != null);
            if (!hasData) return "";
            const agg = aggregatePeriod(periodHrs);
            return renderPeriodCard(p.id, agg, dayKey, p.id === defaultPeriod);
        }).join("");

        const precipSummary = precip > 0.5
            ? `<span style="font-size:15px;color:#74b9ff;">💧${precip.toFixed(1)} мм</span>`
            : snow > 0.1
            ? `<span style="font-size:15px;color:#a8d8ea;">❄ ${snow.toFixed(1)}</span>`
            : "";

        html += `
        <div class="day-block" id="db_${dayKey}" style="margin-bottom:10px;">
            <div style="
                display:flex;align-items:baseline;justify-content:center;gap:12px;
                padding:14px 12px 12px;
                background:linear-gradient(180deg, ${comfortColor}22 0%, ${comfortColor}08 60%, transparent 100%);
                border-bottom:1px solid ${comfortColor}33;
            ">
                <span style="font-size:42px;font-weight:800;color:#fff;line-height:1;">${dayDate.getDate()}</span>
                <span style="font-size:22px;color:#bbb;text-transform:uppercase;letter-spacing:0.1em;align-self:center;">${MON_NAMES[dayDate.getMonth()]}</span>
                <span style="font-size:18px;color:${isToday ? '#FFD700' : '#666'};font-weight:${isToday ? '700' : '400'};align-self:center;">${isToday ? '· сегодня' : '· ' + DAY_NAMES[dayDate.getDay()]}</span>
            </div>
            <div class="day-summary" onclick="toggleDay('${dayKey}')">
                <div class="indicator-line" style="background:${comfortColor};flex-shrink:0;"></div>
                <div style="flex:1;min-width:0;">
                    ${precipSummary ? `<div style="font-size:22px;margin-bottom:6px;">${precipSummary}</div>` : ""}
                    <div style="display:flex;align-items:center;gap:16px;">
                        <span style="font-size:44px;line-height:1;">${wx.icon}</span>
                        <span style="font-size:22px;color:#aaa;">${wx.text}</span>
                    </div>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:6px;flex-shrink:0;">
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;">
                        <span style="font-size:30px;font-weight:800;color:#ff8f00;line-height:1;">${tMax!=null?tMax.toFixed(0)+'°':'-'}</span>
                        <span style="font-size:22px;color:#74b9ff;line-height:1;">${tMin!=null?tMin.toFixed(0)+'°':'-'}</span>
                    </div>
                    <div style="font-size:18px;color:#aaa;text-align:right;">
                        <i style="display:inline-block;transform:rotate(${avgDir+180}deg);font-style:normal;">↑</i>
                        ${Math.round(avgSpd)} м/с
                    </div>
                    <div style="font-size:16px;color:${comfortColor};font-weight:600;">${comfort}</div>
                </div>
            </div>
            <div class="day-body" id="dayBody_${dayKey}">
                <div class="day-body-inner">
                    <div class="day-body-inner-pad">
                        <div class="periods-grid" id="pg_${dayKey}">${periodsHtml}</div>
                        <div id="periodBodies_${dayKey}"></div>
                    </div>
                </div>
            </div>
        </div>`;
    });

    document.getElementById("forecast").innerHTML = html;
}  // конец renderForecastDays
// =============================================
// КОНСТАНТЫ
// =============================================
const DAY_NAMES  = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
const MON_NAMES  = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
const PERIODS    = [
    { id:"night", label:"Ночь",  hours:[0,1,2,3,4,5]           },
    { id:"morn",  label:"Утро",  hours:[6,7,8,9,10,11]          },
    { id:"day",   label:"День",  hours:[12,13,14,15,16,17]       },
    { id:"eve",   label:"Вечер", hours:[18,19,20,21,22,23]       },
];

const tColors = [
    [62,200,255],[157,214,255],[95,224,143],[255,216,77],[255,107,107]
];
function lerpRgb(norm){
    const seg = (tColors.length - 1) * norm;
    const i0  = Math.min(Math.floor(seg), tColors.length - 2);
    const f   = seg - i0;
    const a   = tColors[i0], b = tColors[i0+1];
    return [
        Math.round(a[0]+(b[0]-a[0])*f),
        Math.round(a[1]+(b[1]-a[1])*f),
        Math.round(a[2]+(b[2]-a[2])*f)
    ];
}

function currentPeriodId(hr){
    if(hr < 6)  return "night";
    if(hr < 12) return "morn";
    if(hr < 18) return "day";
    return "eve";
}

function aggregatePeriod(hrs){
    if(!hrs.length) return null;
    const temps  = hrs.map(h => h.temperature_2m).filter(v => v != null);
    const feels  = hrs.map(h => h.apparent_temperature).filter(v => v != null);
    const winds  = hrs.map(h => h.wind_speed_10m).filter(v => v != null);
    const gusts  = hrs.map(h => h.wind_gusts_10m).filter(v => v != null);
    const precip = hrs.reduce((s,h) => s + (h.rain||0) + (h.showers||0), 0);
    const snow   = hrs.reduce((s,h) => s + (h.snowfall||0), 0);
    const prob   = Math.max(...hrs.map(h => h.precip_prob ?? 0));
    const cloud  = Math.round(hrs.reduce((s,h) => s + (h.cloud_cover||0), 0) / hrs.length);
    const code   = Math.max(...hrs.map(h => h.weather_code ?? 0));
    let sx = 0, sy = 0;
    hrs.forEach(h => {
        const rad = (h.wind_direction_10m ?? 0) * Math.PI / 180;
        sx += Math.sin(rad); sy += Math.cos(rad);
    });
    const avgDir = ((Math.atan2(sx/hrs.length, sy/hrs.length) * 180/Math.PI) + 360) % 360;
    const avgSpd = winds.length ? winds.reduce((a,b)=>a+b,0)/winds.length : 0;
    const maxGust= gusts.length ? Math.max(...gusts) : 0;
    const tMin   = temps.length ? Math.min(...temps) : null;
    const tMax   = temps.length ? Math.max(...temps) : null;
    const tAvg   = temps.length ? temps.reduce((a,b)=>a+b,0)/temps.length : null;
    const fAvg   = feels.length ? feels.reduce((a,b)=>a+b,0)/feels.length : null;
    const rh     = Math.round(hrs.reduce((s,h)=>s+(h.relative_humidity_2m||0),0)/hrs.length);
    const psl    = hrs.reduce((s,h)=>s+(h.pressure_msl||0),0)/hrs.length;
    const vis    = Math.round(hrs.reduce((s,h)=>s+(h.visibility||10000),0)/hrs.length / 1000);
    const midH   = hrs[Math.floor(hrs.length/2)];
    const { comfort, color: comfortColor } = comfortLevel(midH);
    const hrMid  = new Date(midH.time).getHours();
    const wx     = weatherCode(code, hrMid, cloud, precip, snow);
    return {
        hrs, temps, tMin, tMax, tAvg, fAvg,
        avgDir, avgSpd, maxGust,
        precip, snow, prob, cloud, rh, psl, vis,
        code, wx, comfort, comfortColor
    };
}

function aggregateDay(dayHours){
    const temps  = dayHours.map(h => h.temperature_2m).filter(v => v != null);
    const precip = dayHours.reduce((s,h)=>s+(h.rain||0)+(h.showers||0), 0);
    const snow   = dayHours.reduce((s,h)=>s+(h.snowfall||0), 0);
    const cloud  = Math.round(dayHours.reduce((s,h)=>s+(h.cloud_cover||0),0)/dayHours.length);
    const code   = Math.max(...dayHours.map(h => h.weather_code ?? 0));
    let sx = 0, sy = 0;
    dayHours.forEach(h => {
        const rad = (h.wind_direction_10m ?? 0) * Math.PI / 180;
        sx += Math.sin(rad); sy += Math.cos(rad);
    });
    const avgDir = ((Math.atan2(sx/dayHours.length, sy/dayHours.length) * 180/Math.PI) + 360) % 360;
    const winds  = dayHours.map(h => h.wind_speed_10m).filter(v=>v!=null);
    const avgSpd = winds.length ? winds.reduce((a,b)=>a+b,0)/winds.length : 0;
    const tMin   = temps.length ? Math.min(...temps) : null;
    const tMax   = temps.length ? Math.max(...temps) : null;
    const dayH   = dayHours.find(h => new Date(h.time).getHours() === 14) || dayHours[Math.floor(dayHours.length/2)];
    const { comfort, color: comfortColor } = comfortLevel(dayH);
    const wx     = weatherCode(code, 14, cloud, precip, snow);
    return { tMin, tMax, avgDir, avgSpd, precip, snow, wx, comfort, comfortColor };
}

function renderHourCard(h){
    const d       = new Date(h.time);
    const hr      = d.getHours();
    const t       = h.temperature_2m;
    const tNorm   = Math.max(0, Math.min(1, (t + 20) / 60));
    const [r,g,b2]= lerpRgb(tNorm);
    const rowBg   = `rgba(${r},${g},${b2},${(hr<6||hr>=23)?0.03:0.08})`;
    const wx      = weatherCode(h.weather_code, hr, h.cloud_cover, h.rain, h.snowfall);
    const { comfort, color: c } = comfortLevel(h);
    const windDeg = h.wind_direction_10m ?? 0;
    const precip  = (h.rain||0) + (h.showers||0);
    const precipPct = Math.min(100, precip / 10 * 100);
    const probPct = h.precip_prob ?? 0;
    const cloudPct= h.cloud_cover ?? 0;

    function bar(pct, color, bg="#222"){
        return `<div style="flex:1;height:5px;background:${bg};border-radius:3px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:${color};border-radius:3px;"></div>
        </div>`;
    }
    function barRow(label, pct, color, valStr, bg="#222"){
        return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span style="width:74px;flex-shrink:0;font-size:13px;color:#aaa;">${label}</span>
            ${bar(pct, color, bg)}
            <span style="font-size:13px;color:#777;width:44px;text-align:right;flex-shrink:0;">${valStr}</span>
        </div>`;
    }

    const uid = h.time.replace(/[^0-9]/g, "");

    return `
    <div class="hour-row" style="background:${rowBg};" id="hr_${uid}">
        <div class="hour-summary" onclick="toggleHourCard('${uid}')">
            <div class="indicator-line" style="background:${c};"></div>
            <div style="width:16%;font-size:15px;color:#aaa;">${hr}:00</div>
            <div style="width:18%;font-size:1.7em;text-align:center;">${wx.icon}</div>
            <div style="width:32%;text-align:center;font-weight:800;font-size:17px;color:${t>0?'#ff8f00':'#00e5ff'}">${t.toFixed(1)}°</div>
            <div style="width:34%;text-align:center;">
                <i style="display:inline-block;transform:rotate(${windDeg+180}deg);font-style:normal;font-size:15px;">↑</i>
                <span style="font-size:14px;font-weight:600;margin-left:2px;">${Math.round(h.wind_speed_10m)}<span style="font-size:11px;color:#777;"> м/с</span></span>
            </div>
        </div>
        <div class="hour-details" id="hd_${uid}">
            <div class="hour-details-inner">
                <div class="status-line" style="color:${c};font-size:14px;padding:8px 0;">${wx.text} · ${comfort}</div>
                <div style="padding:8px 0;border-top:1px solid #222;display:flex;flex-direction:column;">
                    ${barRow("Осадки", precipPct, "#4a90d9", precip>0?precip.toFixed(1)+" мм":"0 мм", "#1e2a3a")}
                    ${barRow("Вер-ть", probPct, "#5b8fc9", Math.round(probPct)+"%")}
                    ${barRow("Облака", cloudPct, "#666", Math.round(cloudPct)+"%")}
                </div>
                <div style="padding:8px 0;border-top:1px solid #222;">
                    ${(()=>{ const m = window._marineByTime?.[h.time];
                        if(!m || m.wave_height == null) return "";
                        const wDir = m.wave_direction != null ? windDir(m.wave_direction) : "";
                        const swStr= m.swell_wave_height != null ? ` · зыбь ${m.swell_wave_height.toFixed(1)} м` : "";
                        const sstStr = m.sea_surface_temperature != null ? ` · вода ${m.sea_surface_temperature.toFixed(1)}°` : "";
                        return `<div style="padding:6px 0 4px;border-bottom:1px solid #222;margin-bottom:6px;font-size:12px;color:#00cec9;">
                            🌊 волна ${m.wave_height.toFixed(1)} м${swStr}
                            ${wDir ? ` · ${wDir}` : ""}
                            ${m.wave_period != null ? ` · T=${m.wave_period.toFixed(0)} с` : ""}${sstStr}
                        </div>`;
                    })()}
                    <div class="grid-container" style="gap:10px;">
                        <div><span class="label" style="font-size:12px;">Ощущается</span><div class="val" style="font-size:15px;">${h.apparent_temperature.toFixed(1)}°</div></div>
                        <div><span class="label" style="font-size:12px;">Влажность</span><div class="val" style="font-size:15px;">${Math.round(h.relative_humidity_2m)}%</div></div>
                        <div><span class="label" style="font-size:12px;">Ветер</span><div class="val" style="font-size:15px;">${windDir(windDeg)} ${Math.round(h.wind_speed_10m)} м/с</div></div>
                        <div><span class="label" style="font-size:12px;">Порывы</span><div class="val" style="font-size:15px;">${Math.round(h.wind_gusts_10m)} м/с</div></div>
                        <div><span class="label" style="font-size:12px;">Давление</span><div class="val" style="font-size:15px;">${h.pressure_msl.toFixed(1)} гПа</div></div>
                        <div><span class="label" style="font-size:12px;">Видимость</span><div class="val" style="font-size:15px;">${(h.visibility/1000).toFixed(0)} км</div></div>
                        ${h.snowfall > 0 ? `<div><span class="label" style="font-size:12px;">Снег</span><div class="val" style="font-size:15px;">${h.snowfall} мм</div></div>` : ""}
                    </div>
                </div>
            </div>
        </div>
    </div>`;
}

// =============================================
// ВЕРОЯТНОСТЬ ОСАДКОВ
// =============================================
function renderForecastProb(hours, times){
    const wrap     = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;
    const zeroLine = "";

    const W = 320, H = 160;
    const pad = { t:24, r:10, b:28, l:34 };
    const iW  = W - pad.l - pad.r;
    const iH  = H - pad.t - pad.b;

    const data = hours.map(h => h.precip_prob ?? 0);
    const tMin = new Date(times[0]).getTime();
    const tMax = new Date(times[times.length - 1]).getTime();
    const px = t => pad.l + (new Date(t).getTime() - tMin) / (tMax - tMin || 1) * iW;
    const py = v => pad.t + (1 - Math.max(0, Math.min(100, v)) / 100) * iH;

    let yGrid = "", yLabels = "";
    [0, 25, 50, 75, 100].forEach(v => {
        const y = py(v);
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="${v===50?'#2a3a4a':'#252525'}" stroke-width="${v===50?1.5:1}"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v}</text>`;
    });

    const PR_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid = "", xLabels = "";
    times.forEach((t, i) => {
        const d  = new Date(t);
        const hr = d.getHours();
        const x  = px(t);
        if(hr === 0){
            xGrid += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nextMidnight = times.slice(i+1).find(t2 => new Date(t2).getHours() === 0);
            const xEnd = nextMidnight ? px(nextMidnight) : pad.l + iW;
            const xMid = (x + xEnd) / 2;
            xLabels += `<text x="${xMid}" y="${pad.t - 6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${PR_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`;
        }
        if(hr % 6 === 0)
            xLabels += `<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`;
    });

    let nowLine = "";
    const nowTs = Date.now();
    if(nowTs >= tMin && nowTs <= tMax){
        const xNow = pad.l + (nowTs - tMin) / (tMax - tMin) * iW;
        nowLine = `<line x1="${xNow}" y1="${pad.t}" x2="${xNow}" y2="${pad.t+iH}"
                         stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`;
    }

    // Зоны риска: 30–60% желтая, >60% оранжевая
    const bottom = pad.t + iH;
    let zones = "";
    const y30 = py(30), y60 = py(60);
    zones += `<rect x="${pad.l}" y="${y60}" width="${iW}" height="${y30-y60}" fill="#ff9f5c" fill-opacity="0.06"/>`;
    zones += `<rect x="${pad.l}" y="${pad.t}" width="${iW}" height="${y60-pad.t}" fill="#ff6b6b" fill-opacity="0.06"/>`;

    const pts = times.map((t, i) => ({ x: px(t), y: py(data[i]) }));
    const linePath = smooth(pts);
    const x0 = pts[0].x, xN = pts[pts.length-1].x;
    const areaPath = linePath + ` L${xN},${bottom} L${x0},${bottom} Z`;

    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs>
            <linearGradient id="probGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stop-color="#5b8fc9" stop-opacity="0.45"/>
                <stop offset="100%" stop-color="#5b8fc9" stop-opacity="0.04"/>
            </linearGradient>
        </defs>
        ${yGrid}${xGrid}${nowLine}${zeroLine}
        ${zones}
        <path d="${areaPath}" fill="url(#probGrad)" stroke="none"/>
        <path d="${linePath}" fill="none" stroke="#5b8fc9" stroke-width="2.5"/>
        ${yLabels}${xLabels}
    </svg>`;

    const svgEl = wrap.querySelector("svg");
    const cfg = FC_PARAMS.find(p => p.key === "prob");
    if(svgEl) addCrosshair(svgEl, pts, pad, iW, iH, W, cfg.color, data, times, cfg, true);

    // Статистика
    if(statsBox){
        statsBox.style.display = "grid";
        const high = data.filter(v => v >= 60).length;
        const med  = data.filter(v => v >= 30 && v < 60).length;
        const maxP = Math.round(Math.max(...data));
        const avgP = Math.round(data.reduce((a,b)=>a+b,0) / data.length);
        statsBox.innerHTML = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Макс. вер-ть</div>
            <div class="fc-stat-value" style="color:#5b8fc9;">${maxP}%</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Средняя</div>
            <div class="fc-stat-value" style="color:#ccc;">${avgP}%</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Высокий риск</div>
            <div class="fc-stat-value" style="color:#ff6b6b;">${high} ч</div>
            <div class="fc-stat-time">≥60%</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Умеренный</div>
            <div class="fc-stat-value" style="color:#ff9f5c;">${med} ч</div>
            <div class="fc-stat-time">30–60%</div>
        </div>`;
    }
}

function renderPeriodCard(pId, agg, dayKey, isActive){
    if(!agg) return "";
    const p = PERIODS.find(x => x.id === pId);
    const tNorm = Math.max(0, Math.min(1, ((agg.tAvg??0) + 20) / 60));
    const [r,g,b2] = lerpRgb(tNorm);
    const bg = `rgba(${r},${g},${b2},0.06)`;
    const precipStr = agg.precip > 0.1 ? `${agg.precip.toFixed(1)} мм` : (agg.snow > 0.1 ? `❄ ${agg.snow.toFixed(1)}` : "");
    return `
    <div class="period-card${isActive?' period-active':''}"
         id="pc_${dayKey}_${pId}"
         onclick="togglePeriod('${dayKey}','${pId}')"
         style="background:${bg};">
        <div style="font-size:12px;color:#666;margin-bottom:4px;">${p.label}</div>
        <div style="font-size:1.6em;">${agg.wx.icon}</div>
        <div style="font-weight:800;font-size:17px;color:${(agg.tAvg??0)>0?'#ff8f00':'#00e5ff'};margin:3px 0;">${agg.tAvg!=null?agg.tAvg.toFixed(0)+'°':'-'}</div>
        <div style="font-size:12px;color:#777;margin-top:3px;">
            <i style="display:inline-block;transform:rotate(${agg.avgDir+180}deg);font-style:normal;">↑</i>
            ${Math.round(agg.avgSpd)}
        </div>
        ${precipStr ? `<div style="font-size:12px;color:#74b9ff;margin-top:3px;">${precipStr}</div>` : ""}
    </div>`;
}

function renderPeriodBody(pId, agg, dayKey){
    if(!agg) return "";
    const hoursHtml = agg.hrs.map(h => renderHourCard(h)).join("");
    return `
    <div class="period-body" id="pb_${dayKey}_${pId}">
        <div class="period-body-inner">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;padding:10px 0 8px;border-bottom:1px solid #222;">
                <div style="text-align:center;">
                    <div style="font-size:12px;color:#666;">Мин/Макс</div>
                    <div style="font-weight:800;font-size:17px;">${agg.tMin!=null?agg.tMin.toFixed(0)+'°':'-'} / ${agg.tMax!=null?agg.tMax.toFixed(0)+'°':'-'}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:12px;color:#666;">Осадки</div>
                    <div style="font-weight:800;font-size:17px;">${agg.precip>0.1?agg.precip.toFixed(1)+' мм':(agg.snow>0.1?'❄ '+agg.snow.toFixed(1):'нет')}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:12px;color:#666;">Влажность</div>
                    <div style="font-weight:800;font-size:17px;">${agg.rh}%</div>
                </div>
            </div>
            <div style="padding:10px 0 6px;font-size:12px;color:#555;font-weight:600;letter-spacing:0.04em;">ПО ЧАСАМ</div>
            ${hoursHtml}
        </div>
    </div>`;
}

let _openHourUid = null;

function toggleHourCard(uid){
    const det = document.getElementById("hd_" + uid);
    if(!det) return;
    const isOpen = det.classList.contains("open");
    if(_openHourUid && _openHourUid !== uid){
        const prev = document.getElementById("hd_" + _openHourUid);
        if(prev) prev.classList.remove("open");
    }
    if(isOpen){
        det.classList.remove("open");
        _openHourUid = null;
    } else {
        det.classList.add("open");
        _openHourUid = uid;
    }
}

function toggleDay(dayKey){
    const body = document.getElementById("dayBody_" + dayKey);
    if(!body) return;
    const isOpen = body.classList.contains("open");
    document.querySelectorAll(".day-body").forEach(el => el.classList.remove("open"));
    if(!isOpen){
        body.classList.add("open");
        const pbCont = document.getElementById("periodBodies_" + dayKey);
        if(pbCont && !pbCont.innerHTML.trim()){
            const firstActive = document.querySelector(`#pg_${dayKey} .period-card.period-active`);
            if(firstActive){
                const pId = firstActive.id.split("_").slice(-1)[0];
                openPeriod(dayKey, pId);
            }
        }
    }
}

function togglePeriod(dayKey, pId){
    const pbCont  = document.getElementById("periodBodies_" + dayKey);
    if(!pbCont) return;
    const existing = document.getElementById("pb_" + dayKey + "_" + pId);
    if(existing){
        existing.classList.remove("open");
        setTimeout(() => {
            pbCont.innerHTML = "";
            document.querySelectorAll(`#pg_${dayKey} .period-card`).forEach(el => el.classList.remove("period-active"));
        }, 500);
        return;
    }
    openPeriod(dayKey, pId);
}

function openPeriod(dayKey, pId){
    if(!window._fcAllHours) return;
    const p = PERIODS.find(x => x.id === pId);
    if(!p) return;
    const periodHrs = window._fcAllHours.filter(h =>
        h.time.slice(0,10) === dayKey &&
        p.hours.includes(new Date(h.time).getHours())
    );
    if(!periodHrs.length) return;
    const agg = aggregatePeriod(periodHrs);
    if(!agg) return;
    const pbCont = document.getElementById("periodBodies_" + dayKey);
    if(!pbCont) return;
    const prevBody = pbCont.querySelector(".period-body");
    if(prevBody){
        prevBody.classList.remove("open");
        setTimeout(() => {
            pbCont.innerHTML = "";
            _renderAndOpenPeriod(dayKey, pId, agg, pbCont);
        }, 480);
    } else {
        _renderAndOpenPeriod(dayKey, pId, agg, pbCont);
    }
}

function _renderAndOpenPeriod(dayKey, pId, agg, pbCont){
    document.querySelectorAll(`#pg_${dayKey} .period-card`).forEach(el => el.classList.remove("period-active"));
    const btn = document.getElementById("pc_" + dayKey + "_" + pId);
    if(btn) btn.classList.add("period-active");
    pbCont.innerHTML = renderPeriodBody(pId, agg, dayKey);
    _openHourUid = null;
    const pb = document.getElementById("pb_" + dayKey + "_" + pId);
    if(pb) requestAnimationFrame(() => requestAnimationFrame(() => pb.classList.add("open")));
}

function openSheet(id){
    const s = document.getElementById(id);
    if(s){ s.classList.add("open"); }
}
function closeSheet(id){
    const s = document.getElementById(id);
    if(s){ s.classList.remove("open"); }
}

// Генерация списка моделей из реестра
(function(){
    var cont = document.getElementById("modelSheetItems");
    if(cont){
        cont.innerHTML =
            '<div class="sheet-item" onclick="setModel(\'ensemble\')" ' +
            'style="color:#ffd166;font-weight:700;">⚡ Ансамбль (взвешенный)</div>' +
            MODEL_REGISTRY.map(function(m){
                return '<div class="sheet-item" onclick="setModel(\'' + m.id + '\')">' + m.long + '</div>';
            }).join("");
    }
})();

load();
