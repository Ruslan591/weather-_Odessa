// ensembleVerify.js
// Снимки хранятся в памяти (_snaps), загружаются из GitHub (ensemble_snapshots_synop.json)

var EV = (function() {

    var MAX_SNAPSHOTS = 200;
    var _snaps = [];

    function setSnaps(arr) { _snaps = Array.isArray(arr) ? arr : []; }
    function getSnaps()    { return _snaps; }

    function saveSnapshot(hours) {
        if (!hours || !hours.length) return false;
        var nowHourStr = new Date().toISOString().slice(0, 13);
        for (var i = 0; i < _snaps.length; i++) {
            if (_snaps[i].savedAt && _snaps[i].savedAt.slice(0, 13) === nowHourStr) return false;
        }
        _snaps.push({ savedAt: new Date().toISOString(), hours: hours });
        _snaps.sort(function(a, b) { return (a.savedAt || "") > (b.savedAt || "") ? 1 : -1; });
        if (_snaps.length > MAX_SNAPSHOTS) _snaps = _snaps.slice(_snaps.length - MAX_SNAPSHOTS);
        return true; // новый снимок добавлен — нужно сохранить на GitHub
    }

    function calcMetrics(obs) {
        if (!obs || !obs.length || !_snaps.length) return null;
        var obsIndex = {};
        obs.forEach(function(o) {
            var key = roundToHour(o.time);
            if (key) obsIndex[key] = o;
        });
        var errors = { temp:[], pressure:[], wind:[], windDir:[], humidity:[], rain:[], cloudcover:[] };
        var wxHits = 0, wxTotal = 0;
        _snaps.forEach(function(snap) {
            snap.hours.forEach(function(fh) {
                var key = roundToHour(fh.time);
                var ob = obsIndex[key];
                if (!ob) return;
                if (fh.temp     != null && ob.temp     != null) errors.temp.push(fh.temp - ob.temp);
                if (fh.pressure != null && ob.pressure != null) errors.pressure.push(fh.pressure - ob.pressure);
                if (fh.wind     != null && ob.wind     != null) errors.wind.push(fh.wind - ob.wind);
                if (fh.humidity != null && ob.humidity != null) errors.humidity.push(fh.humidity - ob.humidity);
                var obRain = ob.rain != null ? ob.rain : (ob.precip != null ? ob.precip : null);
                if (fh.rain != null && obRain != null)
                    errors.rain.push((fh.rain > 0.1 ? 1 : 0) - (obRain > 0.1 ? 1 : 0));
                if (fh.cloudcover != null && ob.cloudcover != null) errors.cloudcover.push(fh.cloudcover - ob.cloudcover);
                if (fh.weatherCode != null && ob.ww != null) {
                    var fGroup = wmoGroupSimple(fh.weatherCode);
                    var oGroup = synopGroupSimple(ob.ww);
                    if (fGroup != null && oGroup != null) { wxTotal++; if (fGroup === oGroup) wxHits++; }
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
        return d.toISOString().slice(0, 16);
    }

    function getSnapshotCount() { return _snaps.length; }
    function clearSnapshots()   { _snaps = []; }

    function getHorizonStats() {
        return _snaps.map(function(s) {
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
        if (code >= 80 && code <= 94)   return "shower";
        if (code >= 95)                 return "thunder";
        return "cloudy";
    }

    function synopGroupSimple(ww) {
        if (ww == null) return null;
        if (ww <= 1)              return "clear";
        if (ww <= 39)             return "cloudy";
        if (ww >= 40 && ww <= 49) return "fog";
        if (ww >= 50 && ww <= 69) return "rain";
        if (ww >= 70 && ww <= 79) return "snow";
        if (ww >= 80 && ww <= 90) return "shower";
        if (ww >= 91 && ww <= 99) return "thunder";
        return null;
    }

    return { setSnaps, getSnaps, saveSnapshot, calcMetrics, getSnapshotCount, clearSnapshots, getHorizonStats };
})();