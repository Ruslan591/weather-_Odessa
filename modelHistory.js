/* =========================================================
   modelHistory.js — загрузка исторических данных моделей
   Зависит от: verify.html (db, models, modelLabel, setStatus, saveData, windDirError)

   Структура записи obs:
     { temp, pressure, wind, windDir, cloudcover, precip, ww, synop }

   Структура записи models[m]:
     { temp, pressure, wind, windDir, cloudcover, precip, weatherCode }

   Поле forecastHour — заблаговременность в часах:
     для исторических данных считается как разница synopTime - время записи (нет реальной),
     поэтому для истории ставим null, для свежих данных — реальный hourIndex от момента запроса.
========================================================= */

const HISTORY_SYNOP_HOURS = [0, 3, 6, 9, 12, 15, 18, 21];
const HISTORY_START_YEAR = new Date().getFullYear() - 3;
const HISTORY_STORAGE_KEY = "modelHistoryProgress";

let historyStopped = false;

function stopHistory() {
    historyStopped = true;
    document.getElementById("stopBtn").style.display = "none";
    setStatus("⛔ Загрузка истории остановлена");
}

/* ---------------------------------------------------------
   Вспомогательные
--------------------------------------------------------- */
function historyMonths() {
    const months = [];
    const now = new Date();
    let year = HISTORY_START_YEAR;
    let month = 1;

    while (year < now.getFullYear() || (year === now.getFullYear() && month <= now.getMonth() + 1)) {
        months.push({ year, month });
        month++;
        if (month > 12) { month = 1; year++; }
    }
    return months;
}

function pad2(n) { return String(n).padStart(2, "0"); }

function monthStartEnd(year, month) {
    const start = `${year}-${pad2(month)}-01`;
    const lastDay = new Date(year, month, 0).getDate();
    const end = `${year}-${pad2(month)}-${pad2(lastDay)}`;
    return { start, end };
}

function sleep(ms) {
    return new Promise(res => setTimeout(res, ms));
}

/* ---------------------------------------------------------
   Загрузка SYNOP за месяц из локального txt файла
--------------------------------------------------------- */
async function loadOgimetMonth(year, month) {
    const fileName = `synop_${year}.txt`;
    const mm = pad2(month);

    let text;
    try {
        const r = await fetch(fileName);
        if (!r.ok) throw new Error("HTTP " + r.status);
        text = await r.text();
    } catch(e) {
        throw new Error(`Не удалось загрузить ${fileName}: ${e}`);
    }

    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    const result = [];

    for (const line of lines) {
        const m = line.match(/^33837,(\d{4}),(\d{2}),(\d{2}),(\d{2}),(\d{2}),(AAXX\s.+)$/);
if (!m) continue;
const [, y, mo, dd, hh, mm, synopLine] = m;
// ...
const telegramKey = `${y}${mo}${dd}${hh}${mm}`;

        try {
            const parsed = parseSynop(synopLine, telegramKey);
            if (parsed && parsed.temp !== null) {
                result.push({ telegramKey, synopLine, parsed });
            }
        } catch(e) {
            console.log("Ошибка парсинга:", line, e);
        }
    }

    return result;
}

/* ---------------------------------------------------------
   Загрузка historical-forecast за месяц
   Теперь включает: cloud_cover, precipitation, weather_code
--------------------------------------------------------- */
async function loadForecastMonth(year, month) {
    const se = monthStartEnd(year, month);
    const label = pad2(month) + "." + year;
    const hourly = {};

    const params = [
        "temperature_2m",
        "pressure_msl",
        "wind_speed_10m",
        "wind_direction_10m",
        "cloud_cover",
        "precipitation",
        "weather_code"
    ].join(",");

    for (const model of models) {
        let attempt = 0;
        while (attempt < 3) {
            try {
                setStatus("⏳ " + label + " — " + modelLabel(model) + "...", true);
                const url = "https://historical-forecast-api.open-meteo.com/v1/forecast" +
                    "?latitude=46.4406&longitude=30.7703" +
                    "&hourly=" + params +
                    "&models=" + model +
                    "&start_date=" + se.start + "&end_date=" + se.end +
                    "&timezone=UTC&wind_speed_unit=ms";

                const r = await fetchWithTimeout(url, 45000);
                if (r.status === 429) {
                    setStatus("⏳ Rate limit, пауза 60с...", true);
                    await sleep(60000);
                    attempt++;
                    continue;
                }
                const d = await r.json();
                if (!d.hourly) { console.log("Нет данных для", model); break; }

                for (const key of Object.keys(d.hourly)) {
                    hourly[key] = d.hourly[key];
                }
                break;
            } catch(e) {
                attempt++;
                console.log("Ошибка модели", model, "попытка", attempt, e);
                if (attempt < 3) {
                    setStatus("⏳ " + label + " " + modelLabel(model) + " — retry " + attempt + "/3...", true);
                    await sleep(5000 * attempt);
                } else {
                    console.log("Пропускаем модель", model);
                }
            }
        }
        await sleep(1000);
    }

    if (!hourly.time) throw new Error("Нет данных ни от одной модели");
    return hourly;
}

/* ---------------------------------------------------------
   Извлечение данных модели из hourly (суффиксы моделей)
   Возвращает все параметры включая новые
--------------------------------------------------------- */
function extractModelData(hourly, modelName, hourIndex, synopHour) {
    function get(field) {
        const arr = hourly[field + "_" + modelName];
        if (!arr) return null;
        const v = arr[hourIndex];
        return v != null ? v : null;
    }

    function getPrecipSum(field) {
        const arr = hourly[field + "_" + modelName];
        if (!arr) return null;
        // 00,06,12,18 UTC — 6-часовые сводки → сумма 6 часов
        // 03,09,15,21 UTC — 3-часовые сводки → сумма 3 часов
        const hours = (synopHour % 6 === 0) ? 6 : 3;
        let sum = 0;
        for (let i = hourIndex - hours + 1; i <= hourIndex; i++) {
            if (i < 0 || arr[i] == null) return null;
            sum += arr[i];
        }
        return Math.round(sum * 10) / 10;
    }

    const windDir = get("wind_direction_10m");

// временная диагностика — удалить после проверки
const rawArr = hourly["precipitation_" + modelName];
if (rawArr) console.log(modelName + " precip[hourIndex-6..hourIndex]:", 
    rawArr.slice(Math.max(0, hourIndex-6), hourIndex+1));

    return {
        temp:        get("temperature_2m"),
        pressure:    get("pressure_msl"),
        wind:        get("wind_speed_10m"),
        windDir:     windDir != null ? Math.round(windDir / 10) * 10 : null,
        cloudcover:  get("cloud_cover"),
        precip:      getPrecipSum("precipitation"),
        weatherCode: get("weather_code")
    };
}

/* ---------------------------------------------------------
   Обработка одного месяца
   rebuild=true — перезаписывает записи которые уже есть
--------------------------------------------------------- */
async function processMonth(year, month, rebuild = false) {
    const label = `${pad2(month)}.${year}`;
    setStatus(`⏳ ${label} — загрузка SYNOP...`, true);

    let synops;
    try {
        synops = await loadOgimetMonth(year, month);
    } catch(e) {
        setStatus("⚠️ " + label + " — ошибка SYNOP: " + e);
        await sleep(3000);
        return -1;
    }

    const missing = [];
    for (const s of synops) {
        const hour = parseInt(s.telegramKey.slice(8, 10));
        if (!HISTORY_SYNOP_HOURS.includes(hour)) continue;

        if (!rebuild) {
            const exists = await synopExists(s.telegramKey);
            if (exists) continue;
        }
        missing.push(s);
    }

    console.log(`${label}: synops=${synops.length} missing=${missing.length}`);

    if (!missing.length) {
        setStatus(`✅ ${label} — уже в базе`);
        await sleep(300);
        return 0;
    }

    setStatus(`⏳ ${label} — загрузка моделей (${missing.length} сводок)...`, true);

    let hourly;
    try {
        hourly = await loadForecastMonth(year, month);
    } catch(e) {
        setStatus(`⚠️ ${label} — ошибка моделей: ${e}`);
        await sleep(3000);
        return 0;
    }

    const batch = [];
    for (const s of missing) {
        const tk = s.telegramKey;
        const targetTime = `${tk.slice(0,4)}-${tk.slice(4,6)}-${tk.slice(6,8)}T${tk.slice(8,10)}:00`;
        const hourIndex = hourly.time.findIndex(t => t.startsWith(targetTime));

        if (hourIndex === -1) {
            console.log("Не найден час:", targetTime);
            continue;
        }

        const modelsData = {};
        for (const m of models) {
            const synopHour = parseInt(tk.slice(8, 10));
            modelsData[m] = extractModelData(hourly, m, hourIndex, synopHour);
        }

        batch.push({
            time:        new Date().toISOString(),
            synopTime:   tk,
            obs:         s.parsed,
            models:      modelsData,
            hourIndex,
            forecastHour: null
        });
    }

    await saveDataBatch(batch);
    var saved = batch.length;

    setStatus(`✅ ${label} — сохранено: ${saved}`);
    console.log(`${label}: сохранено ${saved} из ${missing.length}`);
    await sleep(300);
    return saved;
}

/* ---------------------------------------------------------
   Главная функция — загрузка всей истории
   rebuild=true — игнорирует localStorage, перезаписывает всё
--------------------------------------------------------- */
async function loadModelHistory(rebuild = false) {
    if (!db) await initDB();

    historyStopped = false;
    document.getElementById("stopBtn").style.display = "inline-block";

    if (rebuild) {
        localStorage.removeItem(HISTORY_STORAGE_KEY);
        setStatus("🔄 Перестройка базы — сброс прогресса...");
        await sleep(500);
    }

    const months = historyMonths();
    const progress = JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "{}");

    let totalSaved = 0;
    let processed = 0;

    for (const { year, month } of months) {
        if (historyStopped) break;

        const key = `${year}-${pad2(month)}`;
        if (!rebuild && progress[key]) continue;

        const result = await processMonth(year, month, rebuild);

        if (result !== -1) {
            progress[key] = true;
            localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(progress));
        }

        if (result > 0) totalSaved += result;
        processed++;
        await sleep(2000);
    }

    document.getElementById("stopBtn").style.display = "none";

    if (processed === 0) {
        setStatus("✅ История актуальна");
    } else {
        setStatus(`✅ История загружена: ${processed} мес., записей: ${totalSaved}`);
        await render();
        await drawChart();
    }
}

/* ---------------------------------------------------------
   Перестройка базы — полная перезапись всех записей
   Вызывается кнопкой "Перестроить базу"
--------------------------------------------------------- */
async function rebuildHistory() {
    const ok = confirm(
        "Перестроить базу?\n\n" +
        "Все записи будут перезаписаны с новыми параметрами (облачность, осадки, явления).\n" +
        "Это займёт длительное время. Не закрывайте страницу."
    );
    if (!ok) return;

    await loadModelHistory(true);
}

/* ---------------------------------------------------------
   Запуск при старте если база пустая / JSON файлы недоступны
--------------------------------------------------------- */
async function maybeLoadHistory() {
    if (!db) await initDB();

    try {
        const r = await fetch("modelData_2023.json", { method: "HEAD" });
        if (r.ok) return; // JSON файлы есть — история не нужна
    } catch(e) {}

    const tx    = db.transaction("stats", "readonly");
    const store = tx.objectStore("stats");
    const req   = store.getAll();

    req.onsuccess = async function() {
        const data = req.result;
        const now  = Date.now();
        const hasOld = data.some(function(d) {
            return (now - new Date(d.time).getTime()) > 30 * 24 * 3600 * 1000;
        });
        if (!hasOld) {
            setStatus("📦 Загрузка истории...");
            await loadModelHistory(false);
        }
    };
}
