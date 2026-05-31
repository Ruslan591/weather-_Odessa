function getEnsembleModels() {
    return MODEL_REGISTRY.filter(function(m) { return m.ensemble; }).map(function(m) { return m.id; });
}

// Кэш весов загруженных с GitHub
var _modelWeights = null;

async function loadModelWeights() {
    if (_modelWeights) return _modelWeights;
    try {
        var r = await fetch("data/model_weights.json", { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        _modelWeights = await r.json();
    } catch(e) {
        console.warn("model_weights.json не загружен:", e.message);
        _modelWeights = null;
    }
    return _modelWeights;
}

var _modelBias = null;

async function loadModelBias() {
    if (_modelBias) return _modelBias;
    try {
        var r = await fetch("data/model_bias.json", { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        _modelBias = (await r.json()).models || {};
    } catch(e) {
        console.warn("model_bias.json не загружен:", e.message);
        _modelBias = {};
    }
    return _modelBias;
}

var _pwsBias = null;

async function loadPwsBias() {
    if (_pwsBias) return _pwsBias;
    try {
        var r = await fetch("data/ensemble_accuracy_synop.json", { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        var acc = await r.json();
        _pwsBias = {
            overall:    (acc && acc.overall)    ? acc.overall    : {},
            byHorizon:  (acc && acc.byHorizon)  ? acc.byHorizon  : {},
            byHourUTC:  (acc && acc.byHourUTC)  ? acc.byHourUTC  : {},
        };
    } catch(e) {
        console.warn("ensemble_accuracy_synop.json не загружен:", e.message);
        _pwsBias = { overall: {}, byHorizon: {}, byHourUTC: {} };
    }
    return _pwsBias;
}

function applyBias(value, key, biasOverall, byHorizon, horizonH, byHourUTC, hourUTC) {
    if (value == null) return value;
    var b = null;
    if (byHourUTC != null && hourUTC != null) {
        var h0 = Math.floor(hourUTC / 3) * 3;
        var h1 = (h0 + 3) % 24;
        var b0 = ((byHourUTC[String(h0)] || {})[key] || {}).bias;
        var b1 = ((byHourUTC[String(h1)] || {})[key] || {}).bias;
        if (b0 != null && b1 != null) {
            var t = (hourUTC - h0) / 3;
            b = b0 + (b1 - b0) * t;
        } else if (b0 != null) {
            b = b0;
        } else if (b1 != null) {
            b = b1;
        }
    }
    if (b == null && byHorizon != null && horizonH != null) {
        var hKey = String(Math.max(0, Math.round(horizonH)));
        b = ((byHorizon[hKey] || {})[key] || {}).bias;
    }
    if (b == null) b = (biasOverall[key] || {}).bias;
    if (b == null) return value;
    if (key === "windDir") return ((value - b) % 360 + 360) % 360;
    var result = Math.round((value - b) * 10) / 10;
    if (key === "wind" || key === "windGust") result = Math.max(0, result);
    if (key === "humidity") result = Math.min(100, Math.max(0, result));
    return result;
}

function smoothByHorizon(byHorizon) {
    var hNums = Object.keys(byHorizon).map(Number).sort(function(a,b){return a-b;});
    var result = {};
    hNums.forEach(function(h, i) {
        result[String(h)] = {};
        var src = byHorizon[String(h)];
        Object.keys(src).forEach(function(key) {
            var vals = [];
            for (var di = -2; di <= 2; di++) {
                var ni = i + di;
                if (ni >= 0 && ni < hNums.length) {
                    var v = (byHorizon[String(hNums[ni])][key] || {}).bias;
                    if (v != null) vals.push(v);
                }
            }
            result[String(h)][key] = { bias: vals.length ? vals.reduce(function(a,b){return a+b;},0) / vals.length : null };
        });
    });
    return result;
}

var _BIAS_FIELD_MAP = {
    temperature_2m:      "temp",
    apparent_temperature:"temp",
    dew_point_2m:        "temp",
    pressure_msl:        "pressure",
    wind_speed_10m:      "wind",
    wind_gusts_10m:      "wind",
    wind_direction_10m:  "windDir",
    cloud_cover:         "cloudcover",
    visibility:          "visibility",
};

function debiasModelHours(modelId, hours, modelBiasData) {
    if (!hours || !hours.length || !modelBiasData[modelId]) return hours;
    var mb = modelBiasData[modelId];
    var monthKey = String(new Date().getMonth() + 1).padStart(2, "0");
    var byMonth  = (mb.byMonth && mb.byMonth[monthKey]) || {};
    var overall  = mb.overall || {};

    return hours.map(function(h) {
        var hc = Object.assign({}, h);
        Object.keys(_BIAS_FIELD_MAP).forEach(function(field) {
            var param = _BIAS_FIELD_MAP[field];
            var val = hc[field];
            if (val == null) return;
            var b = ((byMonth[param] || overall[param] || {}).bias);
            if (b == null) return;
            if (param === "windDir") {
                hc[field] = ((val - b) % 360 + 360) % 360;
            } else if (param === "wind") {
                hc[field] = Math.max(0, Math.round((val - b) * 10) / 10);
            } else {
                hc[field] = Math.round((val - b) * 10) / 10;
            }
        });
        return hc;
    });
}

function getSeasonKey() {
    var now = new Date();
    var m = now.getMonth() + 1;
    var y = now.getFullYear();
    var s = m===12||m<=2 ? "DJF" : m<=5 ? "MAM" : m<=8 ? "JJA" : "SON";
    var sy = m === 12 ? y + 1 : y;
    return { season: s, seasonKey: sy+"-"+s, monthKey: y+"-"+String(m).padStart(2,"0") };
}

// Консенсусный топ-3 для параметра из 4 источников
function getConsensusTop3(weights, paramKey, succeededModels) {
    var keys = getSeasonKey();
    var sources = [
        weights.allSeasons  && weights.allSeasons[keys.season]             && weights.allSeasons[keys.season][paramKey],
        weights.seasonal    && weights.seasonal[keys.seasonKey]            && weights.seasonal[keys.seasonKey][paramKey],
        weights.allMonths   && weights.allMonths[String(new Date().getMonth()+1).padStart(2,"0")] && weights.allMonths[String(new Date().getMonth()+1).padStart(2,"0")][paramKey],
        weights.monthly     && weights.monthly[keys.monthKey]              && weights.monthly[keys.monthKey][paramKey]
    ].filter(Boolean);

    if (!sources.length) return null;

    // Считаем консенсусный score: позиция в каждом источнике → чем ниже позиция тем лучше
    var scores = {};
    succeededModels.forEach(function(m) { scores[m] = { score: 0, count: 0, mae: 0 }; });

    sources.forEach(function(src) {
        src.forEach(function(entry, idx) {
            if (!succeededModels.includes(entry.model)) return;
            if (!scores[entry.model]) scores[entry.model] = { score: 0, count: 0, mae: 0 };
            // Позиция 0=лучший → score = (3 - idx) / 3
            scores[entry.model].score += (src.length - idx) / src.length;
            scores[entry.model].mae   += entry.mae;
            scores[entry.model].count++;
        });
    });

    // Топ-3 по консенсусному score
    var ranked = succeededModels
        .filter(function(m) { return scores[m] && scores[m].count > 0; })
        .sort(function(a, b) { return scores[b].score - scores[a].score; })
        .slice(0, 3);

    if (!ranked.length) return null;

    // Веса обратно пропорционально среднему MAE
    var avgMae = {};
    ranked.forEach(function(m) { avgMae[m] = scores[m].count > 0 ? scores[m].mae / scores[m].count : 1; });
    var wTotal = ranked.reduce(function(s, m) { return s + 1 / avgMae[m]; }, 0);
    var result = {};
    ranked.forEach(function(m) { result[m] = (1 / avgMae[m]) / wTotal; });
    return result;
}

function getModelWeights(mw, succeededModels) {
    // Fallback — равные веса
    var equal = {};
    succeededModels.forEach(function(m) { equal[m] = 1 / succeededModels.length; });
    if (!mw) return { byParam: null, equal: equal };

    var PARAM_FIELDS = {
        temp:       ["temperature_2m","apparent_temperature","dew_point_2m"],
        pressure:   ["pressure_msl"],
        wind:       ["wind_speed_10m","wind_gusts_10m"],
        windDir:    ["wind_direction_10m"],
        cloudcover: ["cloud_cover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
                     "shortwave_radiation","relative_humidity_2m"],
        precip:     ["rain","showers","snowfall","snow_depth","precip_prob"],
        phenomena:  ["weather_code"]
    };

    var byParam = {};
    Object.keys(PARAM_FIELDS).forEach(function(paramKey) {
        var top3 = getConsensusTop3(mw, paramKey, succeededModels);
        PARAM_FIELDS[paramKey].forEach(function(field) {
            byParam[field] = top3 || equal;
        });
    });

    return { byParam: byParam, equal: equal };
}

function parseHourly(h) {
    return h.time.map(function(t, i) {
        return {
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
            precip_prob:           h.precipitation_probability ? h.precipitation_probability[i] : null,
            snowfall:              h.snowfall[i],
            snow_depth:            h.snow_depth[i],
            shortwave_radiation:   h.shortwave_radiation[i],
            direct_radiation:      h.direct_radiation ? h.direct_radiation[i] : null,
            diffuse_radiation:     h.diffuse_radiation ? h.diffuse_radiation[i] : null,
            dew_point_2m:          h.dew_point_2m[i],
            runoff:                h.runoff ? h.runoff[i] : null,
            cloud_cover:           h.cloud_cover[i],
            cloud_cover_low:       h.cloud_cover_low[i],
            cloud_cover_mid:       h.cloud_cover_mid[i],
            cloud_cover_high:      h.cloud_cover_high[i],
            cape:                  h.cape ? h.cape[i] : null,
            uv_index:              h.uv_index ? h.uv_index[i] : null,
            lifted_index:          h.lifted_index ? h.lifted_index[i] : null,
            convective_inhibition: h.convective_inhibition ? h.convective_inhibition[i] : null,
            temperature_850hPa:   h.temperature_850hPa   ? h.temperature_850hPa[i]   : null,
            temperature_700hPa:   h.temperature_700hPa   ? h.temperature_700hPa[i]   : null,
            temperature_500hPa:   h.temperature_500hPa   ? h.temperature_500hPa[i]   : null,
            dewpoint_850hPa:      h.dewpoint_850hPa      ? h.dewpoint_850hPa[i]      : null,
            dewpoint_700hPa:      h.dewpoint_700hPa      ? h.dewpoint_700hPa[i]      : null,
            windspeed_850hPa:     h.windspeed_850hPa     ? h.windspeed_850hPa[i]     : null,
            windspeed_500hPa:     h.windspeed_500hPa     ? h.windspeed_500hPa[i]     : null,
            winddirection_850hPa: h.winddirection_850hPa ? h.winddirection_850hPa[i] : null,
            winddirection_500hPa: h.winddirection_500hPa ? h.winddirection_500hPa[i] : null,
        };
    });
}

function mergeEnsemble(allModelHours, weights, models) {
    var numericFields = [
        "temperature_2m","apparent_temperature","pressure_msl","relative_humidity_2m",
        "wind_speed_10m","wind_gusts_10m","rain","showers","precip_prob","snowfall",
        "snow_depth","cloud_cover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
        "shortwave_radiation","dew_point_2m","visibility","cape","uv_index",
        "lifted_index","convective_inhibition",
        "temperature_850hPa","temperature_700hPa","temperature_500hPa",
        "windspeed_850hPa","windspeed_500hPa"
    ];
    var base = allModelHours[models[0]];
    if (!base) return [];

    return base.map(function(baseH, i) {
        var merged = { time: baseH.time };

        numericFields.forEach(function(f) {
            var fw = (weights.byParam && weights.byParam[f]) ? weights.byParam[f] : weights.equal;
            var sum = 0, wSum = 0;
            Object.keys(fw).forEach(function(m) {
                var mh = allModelHours[m];
                if (!mh) return;
                var v = mh[i] ? mh[i][f] : null;
                if (v != null && !isNaN(v)) { sum += v * fw[m]; wSum += fw[m]; }
            });
            merged[f] = wSum > 0 ? sum / wSum : null;
        });

        // Направление ветра — векторное среднее
        var sx = 0, sy = 0, wSum2 = 0;
        var dfw = (weights.byParam && weights.byParam["wind_direction_10m"]) ? weights.byParam["wind_direction_10m"] : weights.equal;
        Object.keys(dfw).forEach(function(m) {
            var mh = allModelHours[m];
            if (!mh || !mh[i]) return;
            var d = mh[i].wind_direction_10m;
            if (d != null) {
                var rad = d * Math.PI / 180;
                sx += Math.sin(rad) * dfw[m];
                sy += Math.cos(rad) * dfw[m];
                wSum2 += dfw[m];
            }
        });
        merged.wind_direction_10m = wSum2 > 0
            ? ((Math.atan2(sx / wSum2, sy / wSum2) * 180 / Math.PI) + 360) % 360
            : null;
        // Направление ветра на уровнях давления — векторное среднее
        ["winddirection_850hPa","winddirection_500hPa"].forEach(function(dirField){
            var sx2=0,sy2=0,ws2=0;
            models.forEach(function(m){
                var mh=allModelHours[m]; if(!mh||!mh[i]) return;
                var d=mh[i][dirField];
                if(d!=null){ var r=d*Math.PI/180; sx2+=Math.sin(r); sy2+=Math.cos(r); ws2++; }
            });
            merged[dirField]=ws2>0?((Math.atan2(sx2/ws2,sy2/ws2)*180/Math.PI)+360)%360:null;
        });
        // weather_code — взвешенный мажоритарный
        var codeCounts = {};
        var cfw = (weights.byParam && weights.byParam["weather_code"]) ? weights.byParam["weather_code"] : weights.equal;
        Object.keys(cfw).forEach(function(m) {
            var mh = allModelHours[m];
            if (!mh || !mh[i]) return;
            var c = mh[i].weather_code;
            if (c != null) codeCounts[c] = (codeCounts[c] || 0) + cfw[m];
        });
        var bestCode = 0, bestW = -1;
        Object.keys(codeCounts).forEach(function(c) {
            if (codeCounts[c] > bestW) { bestW = codeCounts[c]; bestCode = parseInt(c); }
        });
        merged.weather_code = bestCode;

        // Диапазон по всем параметрам для ленты неопределённости
        merged._range = {};
        numericFields.forEach(function(f) {
            var vals = models.map(function(m) {
                var mh = allModelHours[m];
                return (mh && mh[i] && mh[i][f] != null) ? mh[i][f] : null;
            }).filter(function(v){ return v != null; });
            if (vals.length > 1) {
                merged._range[f] = { min: Math.min.apply(null, vals), max: Math.max.apply(null, vals) };
            }
        });
        // Для ветра — диапазон скоростей
        var wSpds = models.map(function(m) {
            var mh = allModelHours[m];
            return (mh && mh[i]) ? mh[i].wind_speed_10m : null;
        }).filter(function(v){ return v != null; });
        if (wSpds.length > 1) {
            merged._range.wind_speed_10m = { min: Math.min.apply(null, wSpds), max: Math.max.apply(null, wSpds) };
        }

        return merged;
    });
}

// =============================================
// DEBUG: АРИФМЕТИКА АНСАМБЛЯ
// =============================================
function getBiasInfo(key, bias, horizonH, hourUTC) {
    var b = null, src = "—";
    if (bias.byHourUTC && hourUTC != null) {
        var h0 = Math.floor(hourUTC / 3) * 3;
        var h1 = (h0 + 3) % 24;
        var b0 = ((bias.byHourUTC[String(h0)] || {})[key] || {}).bias;
        var b1 = ((bias.byHourUTC[String(h1)] || {})[key] || {}).bias;
        if (b0 != null && b1 != null) {
            var t = (hourUTC - h0) / 3;
            b = b0 + (b1 - b0) * t;
            src = "byHour " + h0 + "→" + h1;
        } else if (b0 != null) { b = b0; src = "byHour " + h0; }
        else if (b1 != null)   { b = b1; src = "byHour " + h1; }
    }
    if (b == null && bias.byHorizon && horizonH != null) {
        var hKey = String(Math.max(0, Math.round(horizonH)));
        b = ((bias.byHorizon[hKey] || {})[key] || {}).bias;
        if (b != null) src = "byHorizon " + hKey + "ч";
    }
    if (b == null) {
        b = (bias.overall[key] || {}).bias;
        if (b != null) src = "overall";
    }
    return { bias: b, src: src };
}

function renderEnsembleDebug(p) {
    var el = document.getElementById("ensembleDebug");
    if (!el) return;
    var models = p.models, failed = p.failed, weights = p.weights;
    var bias = p.bias, rawH = p.rawHours, corrH = p.corrHours;
    var times = p.times, snapTime = p.snapTime;

    var html = '<div style="margin:16px 0 24px;padding:12px 10px;background:#0b0b0b;' +
        'border:1px solid #1e1e1e;border-radius:12px;font-size:11px;color:#aaa;">';
    html += '<div style="font-size:10px;color:#3a3a3a;font-weight:700;letter-spacing:0.08em;' +
        'margin-bottom:10px;">🔬 АРИФМЕТИКА АНСАМБЛЯ</div>';

    // --- 1. Статус моделей ---
    html += '<div style="margin-bottom:10px;">' +
        '<div style="font-size:10px;color:#444;margin-bottom:5px;">Загрузка моделей:</div>' +
        '<div style="display:flex;flex-wrap:wrap;gap:4px;">';
    models.forEach(function(m) {
        var ok = !failed.includes(m);
        html += '<span style="padding:2px 7px;border-radius:8px;font-size:9px;' +
            (ok ? 'background:#0f1f0f;color:#5fe08f;border:1px solid #1a3a1a;'
                : 'background:#1f0f0f;color:#ff6b6b;border:1px solid #3a1a1a;') +
            '">' + m + (ok ? ' ✓' : ' ✗') + '</span>';
    });
    html += '</div></div>';

// --- 2. Веса моделей по параметрам ---
    var wByParam = weights.byParam;
    var _mShort = {
        'ecmwf_ifs':'ECMWF', 'icon_eu':'ICON-EU', 'icon_global':'ICON-G',
        'ukmo_global_deterministic_10km':'UKMO', 'meteofrance_arpege_europe':'ARPEGE',
        'gfs_global':'GFS', 'gem_global':'GEM', 'cma_grapes_global':'CMA'
    };
    function shortM(id){ return _mShort[id] || id.replace(/_global|_deterministic/g,'').replace(/_/g,'-').toUpperCase().slice(0,8); }

    html += '<div style="margin-bottom:10px;">' +
        '<div style="font-size:10px;color:#444;margin-bottom:5px;">Веса моделей (top-3 по консенсусу MAE):</div>';

    if (!wByParam) {
        html += '<div style="color:#555;font-size:10px;">model_weights.json не загружен → равные веса</div>';
    } else {
        var shownParams = [
            { f: 'temperature_2m', l: 'Темп' },
            { f: 'wind_speed_10m', l: 'Ветер' },
            { f: 'pressure_msl',   l: 'Давл' },
            { f: 'cloud_cover',    l: 'Облак' },
            { f: 'rain',           l: 'Осадки' },
        ];
        // Таблица: параметр | 1-е место | 2-е место | 3-е место
        html += '<table style="border-collapse:collapse;width:100%;font-size:10px;">' +
            '<thead><tr style="color:#333;">' +
            '<th style="padding:2px 4px;text-align:left;font-weight:500;width:38px;"></th>' +
            '<th style="padding:2px 4px;text-align:center;color:#ffd166;font-weight:600;">① </th>' +
            '<th style="padding:2px 4px;text-align:center;color:#aaa;font-weight:500;">② </th>' +
            '<th style="padding:2px 4px;text-align:center;color:#666;font-weight:400;">③ </th>' +
            '</tr></thead><tbody>';

        shownParams.forEach(function(sp, si) {
            var fw = wByParam[sp.f] || weights.equal;
            var sorted = Object.entries(fw).sort(function(a,b){ return b[1]-a[1]; }).slice(0, 3);
            var rowBg = si % 2 ? 'background:#0d0d0d;' : '';
            html += '<tr style="border-top:1px solid #111;' + rowBg + '">' +
                '<td style="padding:3px 4px;color:#444;font-size:9px;white-space:nowrap;">' + sp.l + '</td>';
            [0,1,2].forEach(function(rank) {
                var e = sorted[rank];
                if (!e) { html += '<td></td>'; return; }
                var pct = Math.round(e[1] * 100);
                var namCol = rank === 0 ? '#ccc' : rank === 1 ? '#888' : '#555';
                var pctCol = rank === 0 ? '#ffd166' : rank === 1 ? '#aaa' : '#666';
                // мини-бар
                var barW = pct; // % от ширины ячейки
                html += '<td style="padding:3px 4px;text-align:center;">' +
                    '<div style="font-size:9px;color:' + namCol + ';white-space:nowrap;line-height:1.2;">' +
                        shortM(e[0]) +
                    '</div>' +
                    '<div style="height:3px;background:#1a1a1a;border-radius:2px;margin:2px 2px 0;">' +
                        '<div style="width:' + barW + '%;height:100%;background:' + pctCol + ';border-radius:2px;"></div>' +
                    '</div>' +
                    '<div style="font-size:9px;color:' + pctCol + ';font-weight:700;line-height:1.3;">' + pct + '%</div>' +
                '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
    }
    html += '</div>';

    // --- 3. Смещение (overall) ---
    html += '<div style="margin-bottom:10px;">' +
        '<div style="font-size:10px;color:#444;margin-bottom:5px;">' +
        'Смещение bias (overall из ensemble_accuracy_synop.json):</div>' +
        '<div style="display:flex;flex-wrap:wrap;gap:4px;">';
    var bKeys = [
        {k:'temp',    l:'T'},
        {k:'pressure',l:'P'},
        {k:'wind',    l:'Ветер'},
        {k:'windGust',l:'Порывы'},
        {k:'humidity',l:'Влаж'},
        {k:'windDir', l:'Напр°'}
    ];
    var hasBias = false;
    bKeys.forEach(function(bk) {
        var ob = (bias.overall[bk.k] || {}).bias;
        if (ob == null) return;
        hasBias = true;
        var sign = ob >= 0 ? '+' : '';
        var col = Math.abs(ob) < 0.1 ? '#555' : ob > 0 ? '#ff6b6b' : '#74b9ff';
        html += '<span style="padding:2px 8px;border-radius:7px;background:#141414;border:1px solid #222;">' +
            '<span style="color:#444;">' + bk.l + ': </span>' +
            '<span style="color:' + col + ';">' + sign + ob.toFixed(3) + '</span></span>';
    });
    if (!hasBias) html += '<span style="color:#333;">ensemble_accuracy_synop.json не загружен</span>';
    html += '</div></div>';

    // --- 4. Почасовая таблица ---
    var showN = Math.min(rawH.length, 24);
    html += '<div style="font-size:10px;color:#444;margin-bottom:5px;">' +
        'Почасовые данные — сырое → Δ (поправка) → итог:</div>' +
        '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">' +
        '<table style="border-collapse:collapse;font-size:9.5px;width:100%;min-width:520px;">' +
        '<thead><tr style="color:#333;border-bottom:1px solid #1a1a1a;">' +
        '<th style="padding:3px 4px;text-align:left;font-weight:600;">Время</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#ff8f00;">T сыр</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#4169e1;">ΔT</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#ff8f00;font-weight:700;">T итог</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#8bc34a;">V сыр</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#4169e1;">ΔV</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#8bc34a;font-weight:700;">V итог</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#4aa3ff;">P сыр</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#4169e1;">ΔP</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#4aa3ff;font-weight:700;">P итог</th>' +
        '<th style="padding:3px 4px;text-align:right;color:#333;">Источник</th>' +
        '</tr></thead><tbody>';

    for (var i = 0; i < showN; i++) {
        var raw  = rawH[i];
        var corr = corrH[i];
        var tObj = new Date(times[i]);
        var hourUTC  = tObj.getUTCHours();
        var horizonH = (tObj.getTime() - snapTime) / 3600000;
        var biT = getBiasInfo('temp',     bias, horizonH, hourUTC);
        var biW = getBiasInfo('wind',     bias, horizonH, hourUTC);
        var biP = getBiasInfo('pressure', bias, horizonH, hourUTC);

        function fmtDelta(b) {
            if (b == null) return '<td style="padding:3px 4px;text-align:right;color:#333;">—</td>';
            var sign = b >= 0 ? '+' : '';
            var col = Math.abs(b) < 0.05 ? '#333' : b > 0 ? '#ff6b6b' : '#74b9ff';
            // bias хранится как "на сколько модель завышает" → поправка = −bias
            return '<td style="padding:3px 4px;text-align:right;color:' + col + ';">' +
                (b >= 0 ? '−' : '+') + Math.abs(b).toFixed(2) + '</td>';
        }

        var timeStr = tObj.toLocaleString('ru-RU',
            {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
        html += '<tr style="border-bottom:1px solid #111;' + (i%2?'background:#0d0d0d':'') + '">' +
            '<td style="padding:3px 4px;color:#3a3a3a;">' + timeStr + '</td>' +
            '<td style="padding:3px 4px;text-align:right;color:#8a5f00;">' +
                (raw.temperature_2m!=null ? raw.temperature_2m.toFixed(1) : '—') + '</td>' +
            fmtDelta(biT.bias) +
            '<td style="padding:3px 4px;text-align:right;font-weight:700;color:#ff8f00;">' +
                (corr.temperature_2m!=null ? corr.temperature_2m.toFixed(1) : '—') + '</td>' +
            '<td style="padding:3px 4px;text-align:right;color:#5a8a2a;">' +
                (raw.wind_speed_10m!=null ? raw.wind_speed_10m.toFixed(1) : '—') + '</td>' +
            fmtDelta(biW.bias) +
            '<td style="padding:3px 4px;text-align:right;font-weight:700;color:#8bc34a;">' +
                (corr.wind_speed_10m!=null ? corr.wind_speed_10m.toFixed(1) : '—') + '</td>' +
            '<td style="padding:3px 4px;text-align:right;color:#2a6a9a;">' +
                (raw.pressure_msl!=null ? raw.pressure_msl.toFixed(1) : '—') + '</td>' +
            fmtDelta(biP.bias) +
            '<td style="padding:3px 4px;text-align:right;font-weight:700;color:#4aa3ff;">' +
                (corr.pressure_msl!=null ? corr.pressure_msl.toFixed(1) : '—') + '</td>' +
            '<td style="padding:3px 4px;text-align:right;color:#2a2a2a;font-size:8.5px;">' +
                biT.src + '</td>' +
            '</tr>';
    }
    html += '</tbody></table></div></div>';
    el.innerHTML = html;
    el.style.display = '';
}

async function loadEnsemble() {
    loadMarine(); // параллельно, не await
    var models = getEnsembleModels();
    if (!models.length) return;

    var mw            = await loadModelWeights();
    var bias          = await loadPwsBias();
    var modelBiasData = await loadModelBias();
    if (bias.byHorizon && Object.keys(bias.byHorizon).length > 2) {
    bias = { overall: bias.overall, byHorizon: smoothByHorizon(bias.byHorizon), byHourUTC: bias.byHourUTC };
}

    // Показываем веса в заголовке
    var infoStr = "";
    document.getElementById("modelName").innerText = "Ансамбль ⚡";

    var HOURLY_PARAMS = "temperature_2m,apparent_temperature,pressure_msl,relative_humidity_2m," +
        "weather_code,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m," +
        "precipitation,precipitation_probability,showers,snowfall,snow_depth," +
        "shortwave_radiation,direct_radiation,diffuse_radiation,dew_point_2m,runoff," +
        "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,cape,uv_index," +
        "lifted_index,convective_inhibition," +
        "temperature_850hPa,temperature_700hPa,temperature_500hPa," +
        "dewpoint_850hPa,dewpoint_700hPa," +
        "windspeed_850hPa,windspeed_500hPa,winddirection_850hPa,winddirection_500hPa";

    var fetches = models.map(function(m) {
        var url = "https://api.open-meteo.com/v1/forecast?latitude=46.43&longitude=30.74" +
    "&hourly=" + HOURLY_PARAMS +
    "&models=" + m +
    "&forecast_days=" + Math.max(5, Math.ceil(forecastHours / 24) + 1) + "&wind_speed_unit=ms&timezone=auto"
        return fetch(url)
            .then(function(r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
            .then(function(data) { return { model: m, data: data }; })
            .catch(function(e) { return { model: m, error: e.message }; });
    });

    var results = await Promise.all(fetches);

    var allModelHours = {};
    var baseTimes = null;

    results.forEach(function(res) {
        if (res.error || !res.data || !res.data.hourly) return;
        if (!baseTimes) baseTimes = res.data.hourly.time;
        var parsed = parseHourly(res.data.hourly);
        allModelHours[res.model] = debiasModelHours(res.model, parsed, modelBiasData);
    });

    var succeededModels = models.filter(function(m) { return allModelHours[m] != null; });
    if (!succeededModels.length || !baseTimes) {
        document.getElementById("forecast").innerHTML =
            '<div style="padding:20px;text-align:center;color:#ff8f43;">⚠️ Не удалось загрузить модели ансамбля</div>';
        return;
    }

    // Пересчитываем веса только для успешных моделей
    var succeededWeights = getModelWeights(mw, succeededModels);
    var ensembleHours = mergeEnsemble(allModelHours, succeededWeights, succeededModels);
    var snapTime = new Date(baseTimes[0]).getTime();
    var rawEnsembleHours = ensembleHours.map(function(h){ return Object.assign({}, h); });
    ensembleHours = ensembleHours.map(function(h, idx) {
        var horizonH = (new Date(baseTimes[idx]).getTime() - snapTime) / 3600000;
        var hourUTC  = new Date(baseTimes[idx]).getUTCHours();
        return Object.assign({}, h, {
            temperature_2m:       applyBias(h.temperature_2m,       "temp",     bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
            pressure_msl:         applyBias(h.pressure_msl,         "pressure", bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
            wind_speed_10m:       applyBias(h.wind_speed_10m,       "wind",     bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
            wind_gusts_10m:       applyBias(h.wind_gusts_10m,       "windGust", bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
            wind_direction_10m:   applyBias(h.wind_direction_10m,   "windDir",  bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
            relative_humidity_2m: applyBias(h.relative_humidity_2m, "humidity", bias.overall, bias.byHorizon, horizonH, bias.byHourUTC, hourUTC),
        });
    });



    // Обрезаем по времени
    var nowTime = Date.now();
    var timesDates = baseTimes.map(function(t){ return new Date(t); });
    var hoursToShow = forecastHours;
    var startIndex = 0;
    for (var si = 0; si < timesDates.length; si++) {
        if (timesDates[si].getTime() >= nowTime) { startIndex = si; break; }
    }
    startIndex = Math.max(0, startIndex - 1);

    var lastValid = ensembleHours.length - 1;
    for (var li = ensembleHours.length - 1; li >= 0; li--) {
        if (ensembleHours[li].temperature_2m != null) { lastValid = li; break; }
    }
    var endIndex = Math.min(startIndex + hoursToShow, lastValid + 1);

    _fcHours = ensembleHours.slice(startIndex, endIndex);
    _fcTimes = baseTimes.slice(startIndex, endIndex);
    window._fcAllHours = ensembleHours;
    window._fcAllTimes = baseTimes;

    buildFcParamRow();
    buildFcDayRow();
    renderForecastChart(_fcHours, _fcTimes);
    renderAlertsBlock(_fcHours);

    // Рендерим часовые карточки (те же что для обычной модели)
    const lastDayKeyE = baseTimes[endIndex - 1].slice(0, 10);
const fullDayEndE = Math.min(
    baseTimes.findLastIndex(t => t.slice(0, 10) === lastDayKeyE) + 1,
    ensembleHours.length
);
renderForecastDays(ensembleHours.slice(0, fullDayEndE), baseTimes.slice(0, fullDayEndE));

    var dbgFailed = models.filter(function(m){ return !succeededModels.includes(m); });

    // Сохраняем полные массивы для синхронизации с кнопками дней
    window._dbgBase = {
        models:   models,
        failed:   dbgFailed,
        weights:  succeededWeights,
        bias:     bias,
        rawAll:   rawEnsembleHours,
        corrAll:  ensembleHours,
        timesAll: baseTimes,
        snapTime: snapTime
    };

    renderEnsembleDebug({
        models:    models,
        failed:    dbgFailed,
        weights:   succeededWeights,
        bias:      bias,
        rawHours:  rawEnsembleHours.slice(startIndex, endIndex),
        corrHours: _fcHours,
        times:     _fcTimes,
        snapTime:  snapTime
    });
}

// =============================================
// ПРЕДУПРЕЖДЕНИЯ И ОКНО ХОРОШЕЙ ПОГОДЫ
// =============================================
