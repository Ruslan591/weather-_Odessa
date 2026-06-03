function renderForecastChart(hours, times){
    if(_fcParam === "winddir")      return renderForecastWindDir(hours, times);
    if(_fcParam === "cloud")        return renderForecastCloud(hours, times);
    if(_fcParam === "prob")         return renderForecastProb(hours, times);
    if(_fcParam === "temp_profile") return renderTempProfile(hours, times);
    if(_fcParam === "wind_profile") return renderWindProfile(hours, times);
    if(_fcParam === "freeze")       return renderFreezeLevel(hours, times);
    if(_fcParam === "wind_barbs")   return renderWindBarbs(hours, times);
    if(_fcParam === "geo_height")   return renderGeopotentialChart(hours, times);
    if(_fcParam === "vert_vel")     return renderVerticalVelocity(hours, times);
    if(_fcParam === "polar_vortex")    return renderPolarVortex(hours, times);
    if(_fcParam === "humidity_profile") return renderHumidityProfile(hours, times);
    if(_fcParam === "cloud_profile")    return renderCloudProfile(hours, times);
    const _cfgCheck = FC_PARAMS.find(p => p.key === _fcParam);
    if(_cfgCheck && _cfgCheck.marine) return renderMarineChart(times, _cfgCheck);

    const wrap     = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;

    const cfg  = FC_PARAMS.find(p => p.key === _fcParam);
    const data = hours.map(h => cfg.field(h));

    const W = 320, H = 160;
    const pad = { t:24, r:10, b:28, l:38 };
    const iW  = W - pad.l - pad.r;
    const iH  = H - pad.t - pad.b;

    const vAll = data.filter(v => v != null && !isNaN(v));
    if(!vAll.length){
        wrap.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных для модели ${weatherModel}</div>`;
        if(statsBox) statsBox.innerHTML = "";
        return;
    }

    let vMin = Math.min(...vAll), vMax = Math.max(...vAll);
    const spread = vMax - vMin || 1;
    vMin -= spread * 0.3;
    vMax += spread * 0.3;
    if (cfg.key === "wind" || cfg.key === "rain") vMin = Math.max(0, vMin);
    if (cfg.key === "humidity") vMax = Math.min(100, vMax);

    const tMin = new Date(times[0]).getTime();
    const tMax = new Date(times[times.length - 1]).getTime();
    const px = t => pad.l + (new Date(t).getTime() - tMin) / (tMax - tMin) * iW;
    const py = v => pad.t + (1 - (v - vMin) / (vMax - vMin)) * iH;

    const pts = times.map((t, i) => ({ x: px(t), y: py(data[i] ?? vMin) }));
    const linePath = smooth(pts);

    const x0 = pts[0].x,            y0 = pts[0].y;
    const xN = pts[pts.length-1].x, yN = pts[pts.length-1].y;
    const areaPath = linePath + ` L${xN},${yN} L${x0},${y0} Z`;

    let yGrid = "", yLabels = "";
    for(let i = 0; i <= 4; i++){
        const v = vMin + (vMax - vMin) * (1 - i / 4);
        const y = pad.t + iH * i / 4;
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(cfg.key==="pressure"?0:1)}</text>`;
    }
    // Нулевая линия для LI и CIN
    let zeroLine = "";
    if((cfg.key === "li" || cfg.key === "cin") && vMin < 0 && vMax > 0){
        const yZero = pad.t + (1 - (0 - vMin) / (vMax - vMin)) * iH;
        zeroLine = `<line x1="${pad.l}" y1="${yZero}" x2="${pad.l+iW}" y2="${yZero}"
                          stroke="rgba(255,255,255,0.35)" stroke-width="1.2" stroke-dasharray="4 3"/>
                    <text x="${pad.l-4}" y="${yZero+4}" text-anchor="end" font-size="9" fill="#aaa">0</text>`;
    }

    const FC_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
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
            const dayLabel = `${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}`;
            xLabels += `<text x="${xMid}" y="${pad.t - 6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${dayLabel}</text>`;
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

    const gradY0 = Math.min(y0, yN);
    const gradY1 = Math.max(y0, yN) + iH * 0.4;
    const gradId = "fcGrad_" + cfg.key;

    // Лента неопределённости ансамбля
    const _rangeField = cfg.key === "temp"     ? "temperature_2m"      :
                        cfg.key === "pressure" ? "pressure_msl"        :
                        cfg.key === "humidity" ? "relative_humidity_2m":
                        cfg.key === "wind"     ? "wind_speed_10m"      :
                        cfg.key === "rain"     ? "rain"                :
                        cfg.key === "prob"     ? "precip_prob" : null;
    let bandPath = "";
    if (_rangeField && weatherModel === "ensemble" &&
        hours.length && hours[0]._range && hours[0]._range[_rangeField]) {
        const clamp = v => Math.max(vMin, Math.min(vMax, v));
        const hiPts = hours.map((h, i) => ({
            x: px(times[i]),
            y: py(clamp(h._range[_rangeField] ? h._range[_rangeField].max : data[i]))
        }));
        const loPts = hours.map((h, i) => ({
            x: px(times[i]),
            y: py(clamp(h._range[_rangeField] ? h._range[_rangeField].min : data[i]))
        }));
        const loRev = loPts.slice().reverse();
        const bandD = "M " + hiPts.map(p => p.x + "," + p.y).join(" L ") +
                      " L " + loRev.map(p => p.x + "," + p.y).join(" L ") + " Z";
        bandPath = `<path d="${bandD}" fill="${cfg.color}" fill-opacity="0.13" stroke="none"/>`;
    }

    const trendLine = weatherModel !== "ensemble"
        ? `<line x1="${x0}" y1="${y0}" x2="${xN}" y2="${yN}"
                 stroke="${cfg.color}" stroke-opacity="0.22" stroke-width="1.5" stroke-dasharray="4 3"/>`
        : "";

    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs>
            <linearGradient id="${gradId}" x1="0" y1="${gradY0}" x2="0" y2="${gradY1}"
                            gradientUnits="userSpaceOnUse">
                <stop offset="0%"   stop-color="${cfg.color}" stop-opacity="${weatherModel === 'ensemble' ? '0.15' : '0.32'}"/>
                <stop offset="100%" stop-color="${cfg.color}" stop-opacity="0"/>
            </linearGradient>
        </defs>
        ${yGrid}${xGrid}${nowLine}${zeroLine}
        ${bandPath}
        ${weatherModel !== "ensemble" ? `<path d="${areaPath}" fill="url(#${gradId})" stroke="none"/>` : ""}
        ${trendLine}
        <path d="${linePath}" fill="none" stroke="${cfg.color}" stroke-width="2.5"/>
        ${yLabels}${xLabels}
    </svg>`;

    // Лента порывов для ветра
    const svgEl = wrap.querySelector("svg");
    if(cfg.key === "wind" && svgEl){
        const gustData = hours.map(h => h.wind_gusts_10m ?? null);
        const gustValid = gustData.filter(v => v != null);
        if(gustValid.length){
            const ns = "http://www.w3.org/2000/svg";
            const gustPts = times.map((t, i) => ({
                x: px(t),
                y: py(Math.min(vMax, gustData[i] ?? data[i]))
            }));
            const windPts = pts;
            const revWind = windPts.slice().reverse();
            const bandD = "M " + gustPts.map(p => p.x + "," + p.y).join(" L ") +
                          " L " + revWind.map(p => p.x + "," + p.y).join(" L ") + " Z";
            const band = document.createElementNS(ns, "path");
            band.setAttribute("d", bandD);
            band.setAttribute("fill", "#ff9f5c");
            band.setAttribute("fill-opacity", "0.18");
            band.setAttribute("stroke", "none");
            // Вставить перед последним элементом (перекрестие ещё не добавлено)
            svgEl.insertBefore(band, svgEl.lastChild);
            // Пунктирная линия порывов
            const gustLine = document.createElementNS(ns, "polyline");
            gustLine.setAttribute("points", gustPts.map(p => p.x + "," + p.y).join(" "));
            gustLine.setAttribute("fill", "none");
            gustLine.setAttribute("stroke", "#ff9f5c");
            gustLine.setAttribute("stroke-width", "1.2");
            gustLine.setAttribute("stroke-dasharray", "3 3");
            gustLine.setAttribute("stroke-opacity", "0.7");
            svgEl.insertBefore(gustLine, svgEl.lastChild);
        }
    }
    let _tooltipRange = null;
    if(_rangeField && weatherModel === "ensemble" && hours.length && hours[0]._range && hours[0]._range[_rangeField]){
        _tooltipRange = hours.map(h => {
            const r = h._range && h._range[_rangeField];
            return r ? { min: r.min, max: r.max } : null;
        });
    }
    let _gustData = null;
    if(cfg.key === "wind") _gustData = hours.map(h => h.wind_gusts_10m ?? null);
    if(svgEl) addCrosshair(svgEl, pts, pad, iW, iH, W, cfg.color, data, times, cfg, true, _tooltipRange, _gustData);

    // Статистика
    const start = vAll[0], end = vAll[vAll.length-1];
    const min = Math.min(...vAll), max = Math.max(...vAll);
    const delta = end - start;
    const avg = vAll.reduce((a,b)=>a+b,0) / vAll.length;
    const f = (v, dec=1) => v.toFixed(dec) + cfg.unit;

    const iMin = data.indexOf(min), iMax = data.indexOf(max);
    const tFmt = idx => {
        if(idx < 0 || !times[idx]) return "";
        const d = new Date(times[idx]);
        return isNaN(d) ? "" : d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    };

    if(statsBox){
        statsBox.style.display = "grid";
        let card4 = "";

        if(cfg.key === "temp"){
            const amplitude = max - min;
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Амплитуда</div>
                <div class="fc-stat-value" style="color:#fdcb6e;">${amplitude.toFixed(1)}°</div>
                <div class="fc-stat-time">макс − мин</div>
            </div>`;
        } else if(cfg.key === "pressure"){
            const trendC = delta > 0 ? "#ff6b6b" : delta < 0 ? "#74b9ff" : "#888";
            const trendWord = delta > 0 ? "↑ рост" : delta < 0 ? "↓ падение" : "→ стабильно";
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Тенденция</div>
                <div class="fc-stat-value" style="color:${trendC};">${delta>0?"+":""}${delta.toFixed(1)} гПа</div>
                <div class="fc-stat-time">${trendWord}</div>
            </div>`;
            
            }
         else if(cfg.key === "humidity"){
            const highCount = data.filter(v => v != null && v > 80).length;
            const highPct   = Math.round(highCount / data.filter(v => v != null).length * 100);
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Влажно (>80%)</div>
                <div class="fc-stat-value" style="color:#00bcd4;">${highCount} ч</div>
                <div class="fc-stat-time">${highPct}% времени</div>
            </div>`;
        } else if(cfg.key === "wind"){
            const calmCount  = data.filter(v => v != null && v < 1).length;
            const strongCount= data.filter(v => v != null && v >= 10).length;
            const gustVals   = hours.map(h => h.wind_gusts_10m).filter(v => v != null);
            const maxGust    = gustVals.length ? Math.max(...gustVals) : null;
            if(maxGust != null){
                card4 = `
                <div class="fc-stat-card">
                    <div class="fc-stat-label">Макс. порыв</div>
                    <div class="fc-stat-value" style="color:#ff9f5c;">${maxGust.toFixed(1)} м/с</div>
                    <div class="fc-stat-time">&nbsp;</div>
                </div>`;
            } else if(strongCount > 0){
                card4 = `
                <div class="fc-stat-card">
                    <div class="fc-stat-label">Сильный (≥10)</div>
                    <div class="fc-stat-value" style="color:#ff9f5c;">${strongCount} ч</div>
                    <div class="fc-stat-time">м/с и выше</div>
                </div>`;
            } else {
                card4 = `
                <div class="fc-stat-card">
                    <div class="fc-stat-label">Штиль (&lt;1 м/с)</div>
                    <div class="fc-stat-value" style="color:#74b9ff;">${calmCount} ч</div>
                    <div class="fc-stat-time">из ${data.filter(v=>v!=null).length} ч</div>
                </div>`;
            }
        } else if(cfg.key === "cape"){
            const highConv  = data.filter(v => v != null && v > 1000).length;
            const modConv   = data.filter(v => v != null && v > 300 && v <= 1000).length;
            const capeColor = max > 2000 ? "#ff4444" : max > 1000 ? "#ff9f5c" : max > 300 ? "#fdcb6e" : "#55efc4";
            const capeWord  = max > 2000 ? "Экстремальная" : max > 1000 ? "Высокая" : max > 300 ? "Умеренная" : "Слабая";
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Нестабильность</div>
                <div class="fc-stat-value" style="color:${capeColor};">${capeWord}</div>
                <div class="fc-stat-time">пик ${max.toFixed(0)} Дж/кг</div>
            </div>`;
        } else if(cfg.key === "li"){
            const unstableH = data.filter(v => v != null && v < 0).length;
            const severeH   = data.filter(v => v != null && v < -4).length;
            const liColor   = min < -4 ? "#ff4444" : min < -2 ? "#ff9f5c" : min < 0 ? "#fdcb6e" : "#55efc4";
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Нестаб. часов</div>
                <div class="fc-stat-value" style="color:${liColor};">${unstableH} ч</div>
                <div class="fc-stat-time">LI<0 · сильн: ${severeH} ч</div>
            </div>`;
        } else if(cfg.key === "cin"){
            const blockedH  = data.filter(v => v != null && v < -200).length;
            const openH     = data.filter(v => v != null && v > -50).length;
            const cinColor  = min < -200 ? "#a29bfe" : min < -100 ? "#fd79a8" : "#55efc4";
            card4 = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Открыто (>-50)</div>
                <div class="fc-stat-value" style="color:#55efc4;">${openH} ч</div>
                <div class="fc-stat-time">заблок (<-200): ${blockedH} ч</div>
            </div>`;
        } else if(cfg.key === "rain"){
            const rainHours = data.filter(v => v != null && v > 0).length;
            const totalHours= data.filter(v => v != null).length;
            const dryPct    = Math.round((totalHours - rainHours) / totalHours * 100);
            const total     = data.reduce((a,v) => a + (v ?? 0), 0);
            const iPeak     = data.indexOf(max);
            statsBox.innerHTML = `
            <div class="fc-stat-card">
                <div class="fc-stat-label">Сумма</div>
                <div class="fc-stat-value" style="color:#448aff;">${total.toFixed(1)} мм</div>
                <div class="fc-stat-time">за период</div>
            </div>
            <div class="fc-stat-card">
                <div class="fc-stat-label">Часов с дождём</div>
                <div class="fc-stat-value" style="color:#448aff;">${rainHours} ч</div>
                <div class="fc-stat-time">из ${totalHours} ч</div>
            </div>
            <div class="fc-stat-card">
                <div class="fc-stat-label">Пик</div>
                <div class="fc-stat-value" style="color:#74b9ff;">${max.toFixed(1)} мм/ч</div>
                <div class="fc-stat-time">${tFmt(iPeak)}</div>
            </div>
            <div class="fc-stat-card">
                <div class="fc-stat-label">Без осадков</div>
                <div class="fc-stat-value" style="color:#5fe08f;">${dryPct}%</div>
                <div class="fc-stat-time">времени</div>
            </div>`;
            return;
        }

        statsBox.innerHTML = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Минимум</div>
            <div class="fc-stat-value" style="color:${cfg.color};">${f(min)}</div>
            <div class="fc-stat-time">${tFmt(iMin)}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Максимум</div>
            <div class="fc-stat-value" style="color:${cfg.color};">${f(max)}</div>
            <div class="fc-stat-time">${tFmt(iMax)}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Среднее</div>
            <div class="fc-stat-value" style="color:#ccc;">${f(avg)}</div>
            <div class="fc-stat-time">${vAll.length} значений</div>
        </div>
        ${card4}`;
    }
}

// =============================================
// МОРСКОЙ ПРОГНОЗ
// =============================================
function renderMarineChart(times, cfg){
    const wrap     = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;

    if(!window._marineByTime){
        wrap.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:160px;
            color:#555;font-size:13px;">🌊 Загрузка морских данных…</div>`;
        if(statsBox) statsBox.innerHTML = "";
        return;
    }

    const data = times.map(t => {
        const m = window._marineByTime[t];
        return m ? (cfg.field(m) ?? null) : null;
    });
    const dirData = (cfg.key === "wave") ? times.map(t => {
        const m = window._marineByTime[t];
        return m ? (m.wave_direction ?? null) : null;
    }) : null;

    const vAll = data.filter(v => v != null && !isNaN(v));
    if(!vAll.length){
        wrap.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:160px;
            color:#555;font-size:13px;">🌊 Нет морских данных для этого района</div>`;
        if(statsBox) statsBox.innerHTML = "";
        return;
    }

    const W = 320, H = 160;
    const pad = { t:24, r:10, b:28, l:38 };
    const iW  = W - pad.l - pad.r;
    const iH  = H - pad.t - pad.b;

    let vMin = 0, vMax = Math.max(...vAll);
    vMax += vMax * 0.2 || 0.5;
    if(cfg.key === "wave" || cfg.key === "swell") vMax = Math.max(vMax, 0.6);

    const tMin = new Date(times[0]).getTime();
    const tMax_t= new Date(times[times.length-1]).getTime();
    const px = t => pad.l + (new Date(t).getTime() - tMin) / (tMax_t - tMin) * iW;
    const py = v => pad.t + (1 - (v - vMin) / (vMax - vMin)) * iH;

    const pts = times.map((t, i) => ({ x: px(t), y: py(data[i] ?? 0) }));
    const linePath = smooth(pts.filter((_, i) => data[i] != null));

    const x0 = pts[0].x, y0 = pts[0].y;
    const xN = pts[pts.length-1].x, yN = pts[pts.length-1].y;
    const areaPath = linePath + ` L${xN},${H-pad.b} L${x0},${H-pad.b} Z`;

    let yGrid = "", yLabels = "";
    for(let i = 0; i <= 4; i++){
        const v = vMin + (vMax - vMin) * (1 - i / 4);
        const y = pad.t + iH * i / 4;
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(1)}</text>`;
    }

    // Горизонтальные уровни шторма
    const STORM_LEVELS = [
        { h: 0.5, label:"0.5", col:"#fdcb6e" },
        { h: 1.5, label:"1.5", col:"#ff9f5c" },
        { h: 3.0, label:"3.0", col:"#ff4d4d" },
    ];
    let stormLines = "";
    if(cfg.key === "wave" || cfg.key === "swell"){
        STORM_LEVELS.forEach(sl => {
            if(sl.h <= vMax){
                const ys = py(sl.h);
                stormLines += `<line x1="${pad.l}" y1="${ys}" x2="${pad.l+iW}" y2="${ys}"
                    stroke="${sl.col}" stroke-width="0.8" stroke-dasharray="3 3" stroke-opacity="0.5"/>
                    <text x="${pad.l+iW-2}" y="${ys-2}" text-anchor="end" font-size="7.5" fill="${sl.col}" opacity="0.7">${sl.label}м</text>`;
            }
        });
    }

    const FC_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid = "", xLabels = "";
    times.forEach((t, i) => {
        const d = new Date(t); const hr = d.getHours(); const x = px(t);
        if(hr === 0){
            xGrid += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nextMidnight = times.slice(i+1).find(t2 => new Date(t2).getHours() === 0);
            const xEnd = nextMidnight ? px(nextMidnight) : pad.l + iW;
            xLabels += `<text x="${(x+xEnd)/2}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`;
        }
        if(hr % 6 === 0)
            xLabels += `<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`;
    });

    const nowTs = Date.now();
    let nowLine = "";
    if(nowTs >= tMin && nowTs <= tMax_t){
        const xNow = pad.l + (nowTs - tMin) / (tMax_t - tMin) * iW;
        nowLine = `<line x1="${xNow}" y1="${pad.t}" x2="${xNow}" y2="${pad.t+iH}"
            stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`;
    }

    // Стрелки направления волны (только для "wave")
    let arrowsSvg = "";
    if(dirData){
        times.forEach((t, i) => {
            if(i % 3 !== 0) return;
            const dir = dirData[i];
            if(dir == null) return;
            const x = px(t);
            const y = pad.t + iH / 2;
            const rad = (dir + 180) * Math.PI / 180;
            const dx = Math.sin(rad) * 7, dy = -Math.cos(rad) * 7;
            arrowsSvg += `<line x1="${x}" y1="${y}" x2="${x+dx}" y2="${y+dy}"
                stroke="${cfg.color}" stroke-width="1.5" stroke-opacity="0.5"/>
                <circle cx="${x+dx*0.85}" cy="${y+dy*0.85}" r="1.5" fill="${cfg.color}" opacity="0.4"/>`;
        });
    }

    const gradId = "marineGrad_" + cfg.key;
    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs>
            <linearGradient id="${gradId}" x1="0" y1="${pad.t}" x2="0" y2="${pad.t+iH}" gradientUnits="userSpaceOnUse">
                <stop offset="0%" stop-color="${cfg.color}" stop-opacity="0.28"/>
                <stop offset="100%" stop-color="${cfg.color}" stop-opacity="0"/>
            </linearGradient>
        </defs>
        ${yGrid}${xGrid}${nowLine}${stormLines}
        <path d="${areaPath}" fill="url(#${gradId})" stroke="none"/>
        ${arrowsSvg}
        <path d="${linePath}" fill="none" stroke="${cfg.color}" stroke-width="2.5"/>
        ${yLabels}${xLabels}
    </svg>`;

    const svgEl = wrap.querySelector("svg");
    if(svgEl) addCrosshair(svgEl, pts, pad, iW, iH, W, cfg.color, data, times, cfg, false);

    // Статистика
    const min = Math.min(...vAll), max = Math.max(...vAll);
    const avg = vAll.reduce((a,b)=>a+b,0)/vAll.length;
    const iMax = data.indexOf(max);
    const tFmt = idx => {
        if(idx < 0 || !times[idx]) return "";
        const d = new Date(times[idx]);
        return isNaN(d) ? "" : d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    };
    // Третья карточка: зависит от типа параметра
    let thirdCard = "";
    if(cfg.key === "wave" || cfg.key === "swell"){
        const waveLabel = max < 0.1 ? "Штиль" : max < 0.5 ? "Рябь" :
                          max < 1.25 ? "Слабое волнение" : max < 2.5 ? "Умеренное" :
                          max < 4.0 ? "Значительное" : "Сильное волнение";
        const waveColor = max < 0.1 ? "#55efc4" : max < 0.5 ? "#74b9ff" :
                          max < 1.25 ? "#00cec9" : max < 2.5 ? "#fdcb6e" :
                          max < 4.0 ? "#ff9f5c" : "#ff4d4d";
        thirdCard = `<div class="fc-stat-card">
            <div class="fc-stat-label">Состояние</div>
            <div class="fc-stat-value" style="color:${waveColor};font-size:11px;">${waveLabel}</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>`;
    } else if(cfg.key === "wave_per"){
        const perLabel = avg < 5 ? "Короткая" : avg < 8 ? "Средняя" :
                         avg < 12 ? "Длинная (зыбь)" : "Океанская зыбь";
        const perColor = avg < 5 ? "#74b9ff" : avg < 8 ? "#00cec9" :
                         avg < 12 ? "#fdcb6e" : "#a29bfe";
        thirdCard = `<div class="fc-stat-card">
            <div class="fc-stat-label">Тип волны</div>
            <div class="fc-stat-value" style="color:${perColor};font-size:11px;">${perLabel}</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>`;
    }

    if(statsBox){
        statsBox.style.display = "grid";
        const sstLabel = avg < 14 ? "Холодная" : avg < 18 ? "Прохладная" :
                         avg < 22 ? "Тёплая" : avg < 26 ? "Комфортная" : "Горячая";
        const sstColor = avg < 14 ? "#74b9ff" : avg < 18 ? "#00cec9" :
                         avg < 22 ? "#fdcb6e" : avg < 26 ? "#ff9f5c" : "#ff4d4d";
        const card1 = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Максимум</div>
            <div class="fc-stat-value" style="color:${cfg.color};">${max.toFixed(1)}${cfg.unit}</div>
            <div class="fc-stat-time">${tFmt(iMax)}</div>
        </div>`;
        const card2 = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Среднее</div>
            <div class="fc-stat-value" style="color:#ccc;">${avg.toFixed(1)}${cfg.unit}</div>
            <div class="fc-stat-time">${vAll.length} значений</div>
        </div>`;
        const card3 = cfg.key === "sst" ? `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Оценка</div>
            <div class="fc-stat-value" style="color:${sstColor};font-size:11px;">${sstLabel}</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>` : thirdCard;
        statsBox.innerHTML = card1 + card2 + card3;
    }
}

// =============================================
// СИНОПТИЧЕСКИЙ ДИАГНОЗ
// =============================================
function synopticDiagnosis(hours) {
    if (hours.length < 4) return [];

    const pVals  = hours.map(h => h.pressure_msl).filter(v => v != null);
    if (pVals.length < 4) return [];

    const n      = hours.length;
    const dp3    = pVals[Math.min(3, pVals.length - 1)] - pVals[0];
    const dpTotal= pVals[pVals.length - 1] - pVals[0];
    const dpMin  = Math.min(...pVals) - pVals[0];
    const pAvg   = pVals.reduce((a, b) => a + b, 0) / pVals.length;
    const pMinIdx= pVals.indexOf(Math.min(...pVals));
    const dpAfter= pVals[pVals.length - 1] - pVals[pMinIdx];

    const MONTHS = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'];
    function fmtTime(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getHours().toString().padStart(2,'0')}:00`;
    }
    function degToCompass(deg) {
        if (deg == null) return "—";
        const dirs = ['С','ССВ','СВ','ВСВ','В','ВЮВ','ЮВ','ЮЮВ','Ю','ЮЮЗ','ЮЗ','ЗЮЗ','З','ЗСЗ','СЗ','ССЗ'];
        return dirs[Math.round(deg / 22.5) % 16];
    }

    const pMinHourIdx = hours.reduce((best, h, i) => {
        if (h.pressure_msl == null) return best;
        return (best === -1 || h.pressure_msl < hours[best].pressure_msl) ? i : best;
    }, -1);
    const pMinTime = pMinHourIdx >= 0 ? hours[pMinHourIdx].time : null;

    function findDropStart() {
        for (let i = 3; i < hours.length; i++) {
            const p0 = hours[i-3].pressure_msl, p1 = hours[i].pressure_msl;
            if (p0 != null && p1 != null && p0 - p1 > 0.8) return hours[Math.max(0,i-3)].time;
        }
        return hours[0].time;
    }
    function findRecoveryEnd() {
        const pMin = pVals[pMinIdx];
        for (let i = pMinHourIdx + 1; i < hours.length; i++) {
            if ((hours[i].pressure_msl ?? 0) - pMin >= 3) return hours[i].time;
        }
        return hours[hours.length - 1].time;
    }

    const dropStart   = findDropStart();
    const recoveryEnd = findRecoveryEnd();

    const wDir   = hours.map(h => h.wind_direction_10m);
    let windShift = 0;
    for (let i = 1; i < wDir.length; i++) {
        if (wDir[i] == null || wDir[i-1] == null) continue;
        let d = wDir[i] - wDir[i-1];
        if (d > 180)  d -= 360;
        if (d < -180) d += 360;
        windShift += d;
    }

    function meanDir(dirs) {
        const v = dirs.filter(x => x != null);
        if (!v.length) return null;
        const sr = v.reduce((s, d) => s + Math.sin(d * Math.PI/180), 0) / v.length;
        const cr = v.reduce((s, d) => s + Math.cos(d * Math.PI/180), 0) / v.length;
        return ((Math.atan2(sr, cr) * 180/Math.PI) + 360) % 360;
    }
    function meanTemp(hs) {
        const v = hs.map(h => h.temperature_2m).filter(x => x != null);
        return v.length ? v.reduce((a,b) => a+b, 0)/v.length : null;
    }

    const initDir  = meanDir(wDir.slice(0, Math.floor(n/3)));
    const finalDir = meanDir(wDir.slice(Math.floor(2*n/3)));
    const tFirst   = meanTemp(hours.slice(0, Math.floor(n/3)));
    const tLast    = meanTemp(hours.slice(Math.floor(2*n/3)));

    const cloudVals= hours.map(h => h.cloud_cover).filter(v => v != null);
    const rhVals   = hours.map(h => h.relative_humidity_2m).filter(v => v != null);
    const avgCloud = cloudVals.length ? cloudVals.reduce((a,b) => a+b, 0)/cloudVals.length : 0;
    const avgRH    = rhVals.length    ? rhVals.reduce((a,b) => a+b, 0)/rhVals.length       : 0;

    const initFromSW  = initDir  != null && initDir  >= 150 && initDir  <= 270;
    const initFromSE  = initDir  != null && initDir  >= 60  && initDir  <= 200;
    const initFromS   = initDir  != null && initDir  >= 160 && initDir  <= 240;
    const finalFromN  = finalDir != null && (finalDir >= 300 || finalDir <= 60);
    const frontPassed = pMinIdx < n * 0.4 && dpAfter > 2;
    const tDrop       = (tFirst != null && tLast != null) ? tLast - tFirst : 0;

    const result = [];

    // --- Циклон / антициклон ---
    if (dp3 < -3 || dpTotal < -7 || dpMin < -7) {
        result.push({ icon: "🌀", label: "Приближение циклона",
            sub: `начало ${fmtTime(dropStart)} · минимум ${fmtTime(pMinTime)} · ${Math.abs(dpMin).toFixed(1)} гПа`,
            color: "#74b9ff" });
    } else if (dp3 > 3 || dpTotal > 8) {
        result.push({ icon: "⬆", label: "Рост давления / антициклон",
            sub: `+${dpTotal.toFixed(1)} гПа`, color: "#ff9f5c" });
    } else if (pAvg >= 1020 && avgCloud < 35 && Math.min(...pVals) >= 1015 && hours.length >= 48) {
        result.push({ icon: "☀", label: "Антициклональная блокировка",
            sub: `P ср. ${Math.round(pAvg)} гПа, малооблачно`, color: "#fdcb6e" });
    }

    // --- Фронты ---
    if (frontPassed && finalFromN) {
        result.push({ icon: "❄️", label: "Холодный фронт",
            sub: `завершение прохождения ${fmtTime(pMinTime)} · ветер поворачивает на ${degToCompass(finalDir)} · восстановление до ${fmtTime(recoveryEnd)}`,
            color: "#00e5ff" });
    } else if (dpMin < -5 && windShift > 60 && initFromSW) {
        result.push({ icon: "❄️", label: "Холодный фронт",
            sub: `начало ${fmtTime(dropStart)} · прохождение ${fmtTime(pMinTime)} · ветер поворачивает на ${degToCompass(finalDir)}`,
            color: "#00e5ff" });
    } else if (dpTotal < -2 && Math.abs(windShift) < 50 && initFromSE && avgRH > 78 && avgCloud > 55) {
        result.push({ icon: "〰️", label: "Тёплый фронт",
            sub: `начало ${fmtTime(dropStart)} · прохождение ${fmtTime(pMinTime)} · ветер ${degToCompass(initDir)}`,
            color: "#ff8f00" });
    }

    // --- Тёплый сектор ---
    if (Math.abs(dpTotal) < 3 && initFromS && avgRH > 70 && tFirst != null && tFirst > 14
        && !result.some(r => r.label.includes("фронт") || r.label.includes("Фронт"))) {
        result.push({ icon: "🌤️", label: "Тёплый сектор",
            sub: `ветер ${degToCompass(initDir)}, T ≈ ${tFirst.toFixed(0)}°C, влажно`, color: "#fdcb6e" });
    }

    // --- Фронт окклюзии ---
    if (dpMin < -8 && Math.abs(windShift) < 40 && avgCloud > 70) {
        result.push({ icon: "⚡", label: "Фронт окклюзии",
            sub: `пик ${fmtTime(pMinTime)} · сильные осадки, шквалы, резкий перепад давления ${Math.abs(dpMin).toFixed(1)} гПа`,
            color: "#a29bfe" });
    }

    // --- Вторжение холодного воздуха ---
    if (dpAfter > 3 && tDrop < -5 && finalFromN) {
        result.push({ icon: "🧊", label: "Вторжение холодного воздуха",
            sub: `начало ${fmtTime(pMinTime)} · похолодание ${Math.abs(tDrop).toFixed(0)}°C · ветер ${degToCompass(finalDir)}`, color: "#00cec9" });
    }

    return result;
}

// =============================================
// WIND DIRECTION
// =============================================
function renderForecastWindDir(hours, times){
    const wrap     = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;
    const zeroLine = "";

    const cfg  = FC_PARAMS.find(p => p.key === "winddir");
    const data = hours.map(h => h.wind_direction_10m);
    const spds = hours.map(h => h.wind_speed_10m);

    const W = 320, H = 160;
    const pad = { t:24, r:10, b:28, l:34 };
    const iW  = W - pad.l - pad.r;
    const iH  = H - pad.t - pad.b;

    const tMin = new Date(times[0]).getTime();
    const tMax = new Date(times[times.length - 1]).getTime();
    const px = t => pad.l + (new Date(t).getTime() - tMin) / (tMax - tMin || 1) * iW;
    const py = v => pad.t + (1 - v / 360) * iH;

    const yRumbs = [
        [0,"С"],[45,"СВ"],[90,"В"],[135,"ЮВ"],
        [180,"Ю"],[225,"ЮЗ"],[270,"З"],[315,"СЗ"],[360,"С"]
    ];
    let yGrid = "", yLabels = "";
    for(const [deg, lbl] of yRumbs){
        const y = py(deg);
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${lbl}</text>`;
    }

    const WD_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
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
            xLabels += `<text x="${xMid}" y="${pad.t - 6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${WD_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`;
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

    const W_STOPS = [
        {offset:0,    color:"#7ec8ff"},
        {offset:0.13, color:"#67d7a7"},
        {offset:0.36, color:"#ffd166"},
        {offset:0.57, color:"#ff9f5c"},
        {offset:1,    color:"#ff6b6b"},
    ];
    const vMax = 25;
    function gradCol(spd){
        const t = Math.min(spd ?? 0, vMax) / vMax;
        const stops = W_STOPS;
        const cl = Math.max(0, Math.min(1, t));
        for(let i = 1; i < stops.length; i++){
            const a = stops[i-1], b = stops[i];
            if(cl <= b.offset){
                const u = (cl - a.offset) / (b.offset - a.offset);
                const hex = s => [parseInt(s.slice(1,3),16), parseInt(s.slice(3,5),16), parseInt(s.slice(5,7),16)];
                const [r1,g1,b1] = hex(a.color), [r2,g2,b2] = hex(b.color);
                const r = Math.round(r1+(r2-r1)*u);
                const g = Math.round(g1+(g2-g1)*u);
                const bv= Math.round(b1+(b2-b1)*u);
                return "#"+[r,g,bv].map(v=>v.toString(16).padStart(2,"0")).join("");
            }
        }
        return stops[stops.length-1].color;
    }

    const pts = times.map((t, i) => ({ x: px(t), y: py(data[i] ?? 0) }));
    const connPts = pts.filter((_,i) => data[i] != null).map(p => `${p.x},${p.y}`).join(" ");
    const connectLine = connPts
        ? `<polyline points="${connPts}" fill="none" stroke="${cfg.color}" stroke-width="1" stroke-opacity="0.2" stroke-dasharray="3 3"/>`
        : "";

    let arrows = "";
    times.forEach((t, i) => {
        const dir = data[i];
        if(dir == null || isNaN(dir)) return;
        const col = gradCol(spds[i]);
        const x = px(t);
        const y = py(dir);
        const rot = dir + 180;
        arrows += `<g transform="translate(${x},${y}) rotate(${rot})">
            <line x1="0" y1="-5" x2="0" y2="5" stroke="${col}" stroke-width="1.8" stroke-linecap="round"/>
            <polyline points="-2.5,-1 0,-5 2.5,-1" fill="none" stroke="${col}" stroke-width="1.8" stroke-linejoin="round"/>
        </g>`;
    });

    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        ${yGrid}${xGrid}${nowLine}${zeroLine}${connectLine}${arrows}
        ${yLabels}${xLabels}
    </svg>`;

    // Перекрестие (только вертикальная линия — scatter)
    const svgEl = wrap.querySelector("svg");
    if(svgEl) addCrosshair(svgEl, pts, pad, iW, iH, W, cfg.color, data, times, cfg, false);

    // Статистика
    if(statsBox){
        const dirs8 = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"];
        const rumbCounts = {};
        data.filter(v => v != null).forEach(v => {
            const r = dirs8[Math.round(v / 45) % 8];
            rumbCounts[r] = (rumbCounts[r] || 0) + 1;
        });
        const dominant = Object.entries(rumbCounts).sort((a,b) => b[1]-a[1])[0] || ["-", 0];
        let sinSum = 0, cosSum = 0, cnt = 0;
        data.forEach(v => { if(v != null){ sinSum += Math.sin(v*Math.PI/180); cosSum += Math.cos(v*Math.PI/180); cnt++; } });
        const meanDeg = cnt ? ((Math.atan2(sinSum/cnt, cosSum/cnt) * 180/Math.PI) + 360) % 360 : 0;
        const meanRumb = dirs8[Math.round(meanDeg / 45) % 8];
        const spdVals = spds.filter(v => v != null);
        const avgSpd = spdVals.length ? spdVals.reduce((a,b)=>a+b,0)/spdVals.length : null;
        const maxSpd = spdVals.length ? Math.max(...spdVals) : null;

        statsBox.style.display = "grid";
        statsBox.innerHTML = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Доминирующий</div>
            <div class="fc-stat-value" style="color:${cfg.color};">${dominant[0]}</div>
            <div class="fc-stat-time">${dominant[1]} ч</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Среднее</div>
            <div class="fc-stat-value" style="color:#ccc;">${meanRumb}</div>
            <div class="fc-stat-time">${Math.round(meanDeg)}°</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Сред. скорость</div>
            <div class="fc-stat-value" style="color:#8bc34a;">${avgSpd != null ? avgSpd.toFixed(1) : "-"} м/с</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Макс. скорость</div>
            <div class="fc-stat-value" style="color:#ff9f5c;">${maxSpd != null ? maxSpd.toFixed(1) : "-"} м/с</div>
            <div class="fc-stat-time">&nbsp;</div>
        </div>`;
    }
}

// =============================================
// CLOUD COVER
// =============================================
function renderForecastCloud(hours, times){
    const wrap     = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;
    const zeroLine = "";

    const W = 320, H = 160;
    const pad = { t:24, r:10, b:28, l:34 };
    const iW  = W - pad.l - pad.r;
    const iH  = H - pad.t - pad.b;

    const tMin = new Date(times[0]).getTime();
    const tMax = new Date(times[times.length - 1]).getTime();
    const px = t => pad.l + (new Date(t).getTime() - tMin) / (tMax - tMin || 1) * iW;
    const py = v => pad.t + (1 - Math.max(0, Math.min(100, v)) / 100) * iH;

    const layers = [
        { field: h => h.cloud_cover_high ?? 0, color:"#cdd7e0", label:"Верхний" },
        { field: h => h.cloud_cover_mid  ?? 0, color:"#8fa8bf", label:"Средний" },
        { field: h => h.cloud_cover_low  ?? 0, color:"#4a6fa5", label:"Нижний"  },
    ];

    let yGrid = "", yLabels = "";
    [0, 25, 50, 75, 100].forEach(v => {
        const y = py(v);
        yGrid   += `<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v}</text>`;
    });

    const CL_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
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
            xLabels += `<text x="${xMid}" y="${pad.t - 6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${CL_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`;
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

    function makeArea(dataArr){
        const pts = times.map((t, i) => ({ x: px(t), y: py(dataArr[i]) }));
        const line = smooth(pts);
        const x0 = pts[0].x, xN = pts[pts.length-1].x;
        const bottom = pad.t + iH;
        return { line, area: line + ` L${xN},${bottom} L${x0},${bottom} Z`, pts };
    }

    let defs = "", areas = "", lines = "";
    const layerPts = [];
    layers.forEach((layer, i) => {
        const data = hours.map(layer.field);
        const { line, area, pts } = makeArea(data);
        layerPts.push(pts);
        const gid = `cloudGrad_${i}`;
        defs  += `<linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stop-color="${layer.color}" stop-opacity="0.55"/>
            <stop offset="100%" stop-color="${layer.color}" stop-opacity="0.08"/>
        </linearGradient>`;
        areas += `<path id="cloudArea_${i}" d="${area}" fill="url(#${gid})" stroke="none"/>`;
        lines += `<path id="cloudLine_${i}" d="${line}" fill="none" stroke="${layer.color}" stroke-width="1.5" stroke-opacity="0.8"/>`;
    });

    wrap.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs>${defs}</defs>
        ${yGrid}${xGrid}${nowLine}${zeroLine}
        ${areas}${lines}
        ${yLabels}${xLabels}
    </svg>
    <div style="display:flex;gap:10px;justify-content:center;padding:0;margin-top:-8px;flex-wrap:wrap;">
        ${layers.map((l, i) => `
        <button id="cloudLegBtn_${i}" onclick="toggleCloudLayer(${i})"
            style="display:flex;align-items:center;gap:5px;background:none;border:none;
                   padding:3px 8px;border-radius:20px;cursor:pointer;
                   outline:1px solid ${l.color}44;transition:opacity 0.2s;">
            <span style="display:inline-block;width:10px;height:6px;border-radius:2px;
                         background:${l.color};opacity:0.8;flex-shrink:0;"></span>
            <span style="font-size:11px;color:${l.color};">${l.label}</span>
        </button>`).join("")}
    </div>`;

// Переключение видимости ярусов
    const _cloudVisible = [true, true, true];
    window.toggleCloudLayer = function(i){
        _cloudVisible[i] = !_cloudVisible[i];
        const vis = _cloudVisible[i] ? "" : "none";
        const area = document.getElementById(`cloudArea_${i}`);
        const line = document.getElementById(`cloudLine_${i}`);
        const btn  = document.getElementById(`cloudLegBtn_${i}`);
        if(area) area.style.display = vis;
        if(line) line.style.display = vis;
        if(btn)  btn.style.opacity  = _cloudVisible[i] ? "1" : "0.35";
    };

    // Перекрестие для облачности — используем total cloud cover pts
    const totalData = hours.map(h => h.cloud_cover ?? 0);
    const totalPts  = times.map((t, i) => ({ x: px(t), y: py(totalData[i]) }));
    const cloudCfg  = FC_PARAMS.find(p => p.key === "cloud");
    const svgEl = wrap.querySelector("svg");
    if(svgEl){
        // Кастомный тултип для облачности с тремя ярусами
        const ns = "http://www.w3.org/2000/svg";
        const crossV = document.createElementNS(ns, "line");
        crossV.setAttribute("stroke", "rgba(255,255,255,0.3)");
        crossV.setAttribute("stroke-width", "1");
        crossV.setAttribute("stroke-dasharray", "3 3");
        crossV.style.display = "none";
        svgEl.appendChild(crossV);
        const dot = document.createElementNS(ns, "circle");
        dot.setAttribute("r", "4");
        dot.setAttribute("fill", cloudCfg.color);
        dot.setAttribute("stroke", "#111");
        dot.setAttribute("stroke-width", "2");
        dot.style.display = "none";
        svgEl.appendChild(dot);

        function moveCloud(mx, clientX, clientY){
            let best = 0, bestDist = Infinity;
            totalPts.forEach((p, i) => {
                const dist = Math.abs(p.x - mx);
                if(dist < bestDist){ bestDist = dist; best = i; }
            });
            const p = totalPts[best];
            crossV.setAttribute("x1", p.x); crossV.setAttribute("y1", pad.t);
            crossV.setAttribute("x2", p.x); crossV.setAttribute("y2", pad.t + iH);
            crossV.style.display = "";
            dot.setAttribute("cx", p.x); dot.setAttribute("cy", p.y);
            dot.style.display = "";

            let tip = document.getElementById("fcTooltip");
            if(!tip){
                tip = document.createElement("div");
                tip.id = "fcTooltip";
                tip.style.cssText = `position:fixed;z-index:999;pointer-events:none;
                    background:rgba(20,20,20,0.97);border:1px solid #333;border-radius:10px;
                    padding:10px 14px;font-size:12px;color:#eee;min-width:140px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.5);transition:opacity 0.1s;`;
                document.body.appendChild(tip);
            }
            const h = hours[best];
            const t2 = times[best] ? new Date(times[best]) : null;
            const timeStr = t2 && !isNaN(t2)
                ? t2.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})
                : "";
            tip.innerHTML = `
                <div style="color:#888;margin-bottom:6px;font-size:11px;">${timeStr}</div>
                <div style="font-size:15px;font-weight:800;color:#b0bec5;margin-bottom:6px;">${h.cloud_cover != null ? Math.round(h.cloud_cover) : "-"}% <span style="font-size:11px;color:#666;">общая</span></div>
                ${layers.map(l => `<div style="color:${l.color};font-size:12px;">${l.label}: ${l.field(h).toFixed(0)}%</div>`).join("")}
            `;
            tip.style.opacity = "1";
            const tipW = 160;
            const left = clientX + tipW + 20 > window.innerWidth ? clientX - tipW - 12 : clientX + 12;
            tip.style.left = left + "px";
            tip.style.top  = (clientY - 40) + "px";
        }

        function hideCloud(){
            crossV.style.display = "none";
            dot.style.display = "none";
            fcHideTooltip();
        }

        svgEl.addEventListener("mousemove", e => {
            const rect = svgEl.getBoundingClientRect();
            moveCloud((e.clientX - rect.left) * W / rect.width, e.clientX, e.clientY);
        });
        svgEl.addEventListener("mouseleave", hideCloud);
        svgEl.addEventListener("touchmove", e => {
            const touch = e.touches[0];
            const rect = svgEl.getBoundingClientRect();
            moveCloud((touch.clientX - rect.left) * W / rect.width, touch.clientX, touch.clientY);
            e.preventDefault();
        }, { passive: false });
        svgEl.addEventListener("touchend", hideCloud);
    }

    if(statsBox){
        const total  = hours.map(h => h.cloud_cover ?? 0);
        const avg    = Math.round(total.reduce((a,b)=>a+b,0) / total.length);
        const clear  = total.filter(v => v < 20).length;
        const overcast = total.filter(v => v > 80).length;
        const avgHigh = Math.round(hours.map(h => h.cloud_cover_high ?? 0).reduce((a,b)=>a+b,0) / hours.length);
        statsBox.style.display = "grid";
        statsBox.innerHTML = `
        <div class="fc-stat-card">
            <div class="fc-stat-label">Средняя</div>
            <div class="fc-stat-value" style="color:#b0bec5;">${avg}%</div>
            <div class="fc-stat-time">за период</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Ясно (&lt;20%)</div>
            <div class="fc-stat-value" style="color:#ffd166;">${clear} ч</div>
            <div class="fc-stat-time">из ${total.length} ч</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Пасмурно (&gt;80%)</div>
            <div class="fc-stat-value" style="color:#778ca3;">${overcast} ч</div>
            <div class="fc-stat-time">из ${total.length} ч</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">Верхний ярус</div>
            <div class="fc-stat-value" style="color:#cdd7e0;">${avgHigh}%</div>
            <div class="fc-stat-time">среднее</div>
        </div>`;
    }
}

// =============================================
// ENSEMBLE
// =============================================

// Глобальное хранилище срезов по моделям (для ленты неопределённости)
let _ensembleRanges = null; // массив {min, max} по индексу часа для текущего параметра
