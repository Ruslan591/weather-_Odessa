// ensembleVerify.js
// Сохранение и верификация прогнозов ансамбля
// Ключ в localStorage: "ensembleSnapshots"
// Структура: массив { savedAt, forecastHorizonH, hours: [{time, temp, pressure, wind, windDir, humidity}] }

var EV = (function() {

    var STORAGE_KEY = "ensembleSnapshots";
    var MAX_SNAPSHOTS = 200; // чтобы не переполнять localStorage

    function load() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch(e) { return []; }
    }

    function save(arr) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(arr)); } catch(e) {}
    }

    // Вызывать сразу после mergeEnsemble в loadEnsemble
    // hours — результат mergeEnsemble (уже слайс _fcHours не нужен, берём полный ensembleHours)
    function saveSnapshot(hours) {
        if (!hours || !hours.length) return;
        var snaps = load();

        // Не сохранять дублирующий снимок (тот же первый час прогноза)
        // СТАЛО — дедупликация по текущему часу сохранения (не чаще 1 раза в час):
var nowHour = new Date();
nowHour.setMinutes(0, 0, 0);
var nowHourStr = nowHour.toISOString().slice(0, 13); // "2025-04-21T14"
for (var i = 0; i < snaps.length; i++) {
    if (snaps[i].savedAt && snaps[i].savedAt.slice(0, 13) === nowHourStr) return;
}

        var snapshot = {
            savedAt: new Date().toISOString(),
            hours: hours.map(function(h) {
                return {
                    time:     h.time,
                    temp:     h.temperature_2m,
                    pressure: h.pressure_msl,
                    wind:     h.wind_speed_10m,
                    windDir:  h.wind_direction_10m,
                    humidity: h.relative_humidity_2m,
                    rain:        h.rain,
                    cloudcover:  h.cloud_cover,
                    weatherCode: h.weather_code
                };
            })
        };

        snaps.push(snapshot);

        // Обрезаем старые
        if (snaps.length > MAX_SNAPSHOTS) snaps = snaps.slice(snaps.length - MAX_SNAPSHOTS);
        save(snaps);
    }

    // Считает метрики ансамбля относительно наблюдений из modelHistoryProgress
    // obs — массив {time, temp, pressure, wind, windDir, humidity} (SYNOP-наблюдения)
    function calcMetrics(obs) {
        if (!obs || !obs.length) return null;
        var snaps = load();
        if (!snaps.length) return null;

        // Строим индекс наблюдений по времени (округляем до часа)
        var obsIndex = {};
        obs.forEach(function(o) {
            var key = roundToHour(o.time);
            if (key) obsIndex[key] = o;
        });

        var errors = { temp: [], pressure: [], wind: [], windDir: [], humidity: [], rain: [], cloudcover: [] };
        var wxHits = 0, wxTotal = 0; // явления — % совпадений по группам

        snaps.forEach(function(snap) {
            snap.hours.forEach(function(fh) {
                var key = roundToHour(fh.time);
                var ob = obsIndex[key];
                if (!ob) return;

                if (fh.temp    != null && ob.temp    != null) errors.temp.push(fh.temp - ob.temp);
                if (fh.pressure != null && ob.pressure != null) errors.pressure.push(fh.pressure - ob.pressure);
                if (fh.wind    != null && ob.wind    != null) errors.wind.push(fh.wind - ob.wind);
                if (fh.humidity != null && ob.humidity != null) errors.humidity.push(fh.humidity - ob.humidity);
                // Осадки: только факт (>0.1 мм) — почасовой прогноз vs 6-часовое SYNOP несравнимы количественно
                var obRain = ob.rain != null ? ob.rain : (ob.precip != null ? ob.precip : null);
                if (fh.rain != null && obRain != null) {
                    var fHad = fh.rain > 0.1 ? 1 : 0;
                    var oHad = obRain  > 0.1 ? 1 : 0;
                    errors.rain.push(fHad - oHad); // 0=совпало, ±1=ошибка
                }
                if (fh.cloudcover != null && ob.cloudcover != null) errors.cloudcover.push(fh.cloudcover - ob.cloudcover);
                if (fh.weatherCode != null && ob.ww != null) {
                    var fGroup = wmoGroupSimple(fh.weatherCode);
                    var oGroup = synopGroupSimple(ob.ww);
                    if (fGroup != null && oGroup != null) {
                        wxTotal++;
                        if (fGroup === oGroup) wxHits++;
                    }
                }
                if (fh.windDir != null && ob.windDir != null) {
                    var d = Math.abs(fh.windDir - ob.windDir);
                    if (d > 180) d = 360 - d;
                    errors.windDir.push(d);
                }
            });
        });

        var result = {};
        Object.keys(errors).forEach(function(k) {
            var arr = errors[k];
            if (!arr.length) { result[k] = null; return; }
            var mae  = arr.reduce(function(s,v){ return s + Math.abs(v); }, 0) / arr.length;
            var rmse = Math.sqrt(arr.reduce(function(s,v){ return s + v*v; }, 0) / arr.length);
            var bias = arr.reduce(function(s,v){ return s + v; }, 0) / arr.length;
            result[k] = { mae: mae, rmse: rmse, bias: bias, n: arr.length };
        });
        result._wx = wxTotal > 0 ? { hits: wxHits, total: wxTotal, pct: Math.round(wxHits / wxTotal * 100) } : null;
        return result;
    }

    function roundToHour(timeStr) {
        if (!timeStr) return null;
        var d = new Date(timeStr);
        if (isNaN(d)) return null;
        d.setMinutes(0, 0, 0);
        return d.toISOString().slice(0, 16); // "2025-04-21T14:00"
    }

    function getSnapshotCount() { return load().length; }

    function clearSnapshots() { localStorage.removeItem(STORAGE_KEY); }

    // Возвращает горизонт прогноза (часы) для каждого снимка
function getHorizonStats() {
    var snaps = load();
    return snaps.map(function(s) {
        var h0 = s.hours.length ? new Date(s.hours[0].time) : new Date(s.savedAt);
        var hN = s.hours.length ? new Date(s.hours[s.hours.length - 1].time) : h0;
        return { savedAt: s.savedAt, horizonH: Math.round((hN - h0) / 3600000), count: s.hours.length };
    });
}

function wmoGroupSimple(code) {
        if (code == null) return null;
        if (code <= 1)                  return "clear";
        if (code <= 3)                  return "cloudy";
        if (code === 45 || code === 48) return "fog";
        if (code >= 51 && code <= 67)   return "rain";
        if (code >= 71 && code <= 77)   return "snow";
        if (code >= 80 && code <= 84)   return "shower";
        if (code >= 85 && code <= 94)   return "shower";  // снеговые ливни, grad
        if (code >= 95)                 return "thunder";
        return "cloudy";   // 4–44 не охвачены WMO → облачно
    }

    function synopGroupSimple(ww) {
        if (ww == null) return null;
        if (ww <= 1)                return "clear";
        if (ww <= 9)                return "cloudy";   // дымка, пыль и пр.
        if (ww <= 19)               return "cloudy";   // коды 10-19: туманы/морось прошлые
        if (ww <= 29)               return "cloudy";   // коды 20-29: явления в прошлом
        if (ww <= 39)               return "cloudy";   // коды 30-39: пыльные бури
        if (ww >= 40 && ww <= 49)   return "fog";
        if (ww >= 50 && ww <= 69)   return "rain";
        if (ww >= 70 && ww <= 79)   return "snow";
        if (ww >= 80 && ww <= 90)   return "shower";
        if (ww >= 91 && ww <= 99)   return "thunder";
        return null;
    }

    return { saveSnapshot, calcMetrics, getSnapshotCount, clearSnapshots, getHorizonStats };
})();