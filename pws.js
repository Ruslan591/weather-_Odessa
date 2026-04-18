/* =========================================================
   PWS.JS — данные Personal Weather Station
   Weather Underground API (публичные ключи сайта)
   Зависит от: utils.js
========================================================= */

/* =========================================================
   1. НАСТРОЙКИ
========================================================= */
// Station ID — найди на wunderground.com/wundermap,
// кликни на ближайшую станцию (цветные точки)
const PWS_STATION_ID = "IODESS44"; // например: IODESSA12

// Публичные API ключи, встроенные в сайт WU (не секрет)
const WU_KEYS = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525"
];

// Интервал обновления в секундах
const PWS_REFRESH_SEC = 60;

/* =========================================================
   2. СОСТОЯНИЕ
========================================================= */
let _pwsTimer     = null;
let _pwsKeyIndex  = 0;
let _pwsLastEpoch = null; // отслеживаем новизну данных

/* =========================================================
   3. ЗАГРУЗКА
========================================================= */
async function loadPWS(){
    const key = WU_KEYS[_pwsKeyIndex % WU_KEYS.length];
    const url =
        `https://api.weather.com/v2/pws/observations/current` +
        `?stationId=${encodeURIComponent(PWS_STATION_ID)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${key}`;

    // api.weather.com разрешает CORS — прокси не нужен
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
        const r = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
        if(!r.ok){
            if(r.status === 401 || r.status === 403) _pwsKeyIndex++;
            throw new Error("HTTP " + r.status);
        }
        const data = await r.json();
        if(data?.errors?.length)
            throw new Error(data.errors[0]?.error?.message || "API error");
        if(!data?.observations?.length)
            throw new Error("Нет данных observations");
        return parsePWS(data);
    } finally {
        clearTimeout(timer);
    }
}


/* =========================================================
   4. ПАРСИНГ
========================================================= */
function parsePWS(data){
    const obs = data.observations[0];
    const m   = obs.metric || {};

    // WU с units=m: скорость ветра в км/ч — конвертируем в м/с
    const kmhToMs = v => v != null ? Math.round(v / 3.6 * 10) / 10 : null;

    return {
        stationID:    obs.stationID     || null,
        neighborhood: obs.neighborhood  || null,
        softwareType: obs.softwareType  || null,
        country:      obs.country       || null,
        lat:          obs.lat           ?? null,
        lon:          obs.lon           ?? null,
        obsTimeUtc:   obs.obsTimeUtc    || null,
        obsTimeLocal: obs.obsTimeLocal  || null,
        epoch:        obs.epoch         ?? null,
        qcStatus:     obs.qcStatus      ?? null,

        temp:         m.temp            ?? null,  // °C
        dewpt:        m.dewpt           ?? null,  // °C
        heatIndex:    m.heatIndex       ?? null,  // °C
        windChill:    m.windChill       ?? null,  // °C
        pressure:     m.pressure        ?? null,  // гПа
        precipRate:   m.precipRate      ?? null,  // мм/ч
        precipTotal:  m.precipTotal     ?? null,  // мм
        elev:         m.elev            ?? null,  // м

        windDir:      obs.winddir       ?? null,  // °
        humidity:     obs.humidity      ?? null,  // %
        uv:           obs.uv            ?? null,
        solarRad:     obs.solarRadiation ?? null, // Вт/м²

        // Ветер в м/с
        windSpeedMs:  kmhToMs(m.windSpeed),
        windGustMs:   kmhToMs(m.windGust),
    };
}

/* =========================================================
   5. РЕНДЕР
========================================================= */
function renderPWS(p, isUpdate = false){
    const box = document.getElementById("pws");
    if(!box) return;

    // Форматируем время
    const timeStr = p.obsTimeLocal
        ? (() => {
            const d = new Date(p.obsTimeLocal.replace(" ","T"));
            if(isNaN(d)) return p.obsTimeLocal;
            return d.toLocaleString("ru-RU",{
                day:"2-digit", month:"2-digit",
                hour:"2-digit", minute:"2-digit", second:"2-digit"
            });
        })()
        : "-";

    // Ощущаемая температура
    const feelsLike =
        p.temp != null && p.temp >= 27 && p.heatIndex != null ? p.heatIndex :
        p.temp != null && p.temp <= 10 && p.windChill != null ? p.windChill :
        p.temp;

    const tc = tempClass(p.temp);

    // Индикатор новизны данных
    const isNew     = _pwsLastEpoch !== p.epoch;
    const freshDot  = isNew
        ? `<span style="color:#5fe08f;font-size:10px;margin-left:6px;">● свежие</span>`
        : `<span style="color:#888;font-size:10px;margin-left:6px;">○ без изм.</span>`;

    _pwsLastEpoch = p.epoch;

    box.innerHTML = `
        <div class="cardTitle" style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;">
            PWS · <span style="color:#aaa;">${escapeHtml(p.stationID || "-")}</span>
            ${p.neighborhood ? `<span class="muted" style="font-size:12px;margin-left:4px;">${escapeHtml(p.neighborhood)}</span>` : ""}
            ${freshDot}
        </div>
        <div class="subTitle">${escapeHtml(timeStr)}</div>

        <!-- Температура -->
        <div style="margin:8px 0 6px;">
            <div class="small">Температура</div>
            <div class="heroTemp ${tc}" style="font-size:32px;">${fmt1(p.temp,"°C")}</div>
            ${feelsLike != null && feelsLike !== p.temp
                ? `<div class="heroFeels">Ощущается как: <b>${fmt1(feelsLike,"°C")}</b></div>`
                : ""}
        </div>

        <div class="grid2" style="margin-top:8px;">
            <div class="card" style="margin:0;">
                <div class="cardTitle">Атмосфера</div>
                ${pwsRow("Точка росы",  fmt1(p.dewpt,"°C"))}
                ${pwsRow("Влажность",   fmt0(p.humidity," %"))}
                ${pwsRow("Давление",    fmt1(p.pressure," гПа"))}
            </div>
            <div class="card" style="margin:0;">
                <div class="cardTitle">Ветер</div>
                ${pwsRow("Скорость",
                    fmt1(p.windSpeedMs," м/с") +
                    (p.windDir != null ? " " + escapeHtml(degToText(p.windDir)) + ` · ${p.windDir}°` : "")
                )}
                ${pwsRow("Порывы",      fmt1(p.windGustMs," м/с"))}
            </div>
        </div>

        <div class="card" style="margin-top:8px;">
            <div class="cardTitle">Осадки и радиация</div>
            ${pwsRow("Интенсивность", fmt1(p.precipRate," мм/ч"))}
            ${pwsRow("Сумма",         fmt1(p.precipTotal," мм"))}
            ${p.solarRad != null ? pwsRow("Радиация",   fmt0(p.solarRad," Вт/м²")) : ""}
            ${p.uv != null       ? pwsRow("УФ-индекс",  String(p.uv)) : ""}
        </div>

        <details style="margin-top:8px;">
            <summary>О станции</summary>
            ${pwsRow("Station ID",  escapeHtml(p.stationID  || "-"))}
            ${pwsRow("Район",       escapeHtml(p.neighborhood || "-"))}
            ${pwsRow("ПО станции",  escapeHtml(p.softwareType || "-"))}
            ${pwsRow("Страна",      escapeHtml(p.country || "-"))}
            ${pwsRow("Координаты",
                p.lat != null ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : "-")}
            ${pwsRow("Высота",      p.elev != null ? fmt0(p.elev," м") : "-")}
        </details>
    `;
}

function pwsRow(label, value){
    return `<div class="row">
        <div class="label">${label}</div>
        <div class="value">${value ?? "-"}</div>
    </div>`;
}

/* =========================================================
   6. СТАТУСНАЯ СТРОКА (обновляется без перерисовки карточки)
========================================================= */
function pwsUpdateStatus(msg, color="#aaa"){
    const el = document.getElementById("pwsStatus");
    if(el){ el.textContent = msg; el.style.color = color; }
}

/* =========================================================
   7. UI-ОБЁРТКА (первичная загрузка)
========================================================= */
async function loadPWSUI(){
    const btn = document.getElementById("btnPWS");
    if(btn) btn.disabled = true;
    clearLog("pwsLog");
    showLogBox("pwsLogBox");

    try {
        logTo("pwsLog", `🚀 Станция: ${PWS_STATION_ID}`);
        logTo("pwsLog", "🌐 Запрос к Weather Underground");
        const pws = await loadPWS();
        logTo("pwsLog", "📥 Данные получены");
        renderPWS(pws);
        logTo("pwsLog", "✅ PWS загружен");
        hideLogBoxLater("pwsLogBox", 2500);

        // Запускаем быстрое автообновление
        startPWSAutoRefresh();
    } catch(e){
        logTo("pwsLog", "❌ " + (e?.message || e));
        const box = document.getElementById("pws");
        if(box) box.innerHTML = `
            <div class="cardTitle">PWS</div>
            <div class="small" style="color:#ff8f43;">
                Ошибка: ${escapeHtml(e?.message || e)}
            </div>
            <div class="small" style="margin-top:6px;color:#888;">
                Укажи Station ID в pws.js — найди на
                <a href="https://www.wunderground.com/wundermap"
                   target="_blank" style="color:#72c8ff;">wunderground.com/wundermap</a>
            </div>`;
    } finally {
        if(btn) btn.disabled = false;
    }
}

/* =========================================================
   8. БЫСТРОЕ АВТООБНОВЛЕНИЕ (без перезагрузки страницы)
========================================================= */
function startPWSAutoRefresh(){
    if(_pwsTimer) clearInterval(_pwsTimer);

    _pwsTimer = setInterval(async () => {
        try {
            const pws = await loadPWS();
            renderPWS(pws, true);
        } catch(e){
            // Тихая ошибка — просто ждём следующего цикла
            console.warn("PWS auto-refresh:", e?.message || e);
        }
    }, PWS_REFRESH_SEC * 1000);
}

function stopPWSAutoRefresh(){
    if(_pwsTimer){ clearInterval(_pwsTimer); _pwsTimer = null; }
}

/* =========================================================
   ИСТОРИЯ PWS
========================================================= */

// Все наблюдения за сегодня (каждые ~5 мин)
async function loadPWSToday(stationId) {
    const url =
        `https://api.weather.com/v2/pws/observations/all/1day` +
        `?stationId=${encodeURIComponent(stationId)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${WU_KEYS[0]}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (!data?.observations?.length) throw new Error("Нет данных");
    return data.observations.map(parsePWSOne);
}

// Почасовые данные за последние 7 дней
async function loadPWSHourly7Day(stationId) {
    const url =
        `https://api.weather.com/v2/pws/observations/hourly/7day` +
        `?stationId=${encodeURIComponent(stationId)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&apiKey=${WU_KEYS[0]}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (!data?.observations?.length) throw new Error("Нет данных");
    return data.observations.map(parsePWSOne);
}

// История за конкретный день (все наблюдения)
async function loadPWSHistoryDay(stationId, dateYMD) {
    // dateYMD — строка вида "20250331"
    const url =
        `https://api.weather.com/v2/pws/history/all` +
        `?stationId=${encodeURIComponent(stationId)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&date=${dateYMD}` +
        `&apiKey=${WU_KEYS[0]}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (!data?.observations?.length) throw new Error("Нет данных");
    return data.observations.map(parsePWSOne);
}

// Дневные агрегаты (min/max/avg) за диапазон дат
async function loadPWSDailyStats(stationId, startYMD, endYMD) {
    // startYMD, endYMD — "20250301", "20250331"
    const url =
        `https://api.weather.com/v2/pws/history/daily` +
        `?stationId=${encodeURIComponent(stationId)}` +
        `&format=json&units=m&numericPrecision=decimal` +
        `&startDate=${startYMD}&endDate=${endYMD}` +
        `&apiKey=${WU_KEYS[0]}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    if (!data?.observations?.length) throw new Error("Нет данных");
    // Агрегаты: metric.tempHigh, tempLow, tempAvg, windspeedHigh, windgustHigh, precipTotal и т.д.
    return data.observations;
}