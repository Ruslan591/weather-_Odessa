function weatherAlerts(hours) {
    const alerts = [];

    hours.forEach((h, i) => {
        const t       = h.temperature_2m ?? 0;
        const feel    = h.apparent_temperature ?? t;
        const wind    = h.wind_speed_10m ?? 0;
        const gust    = h.wind_gusts_10m ?? wind;
        const vis     = h.visibility ?? 10000;
        const code    = h.weather_code ?? 0;
        const rain    = (h.rain ?? 0) + (h.showers ?? 0);
        const rh      = h.relative_humidity_2m ?? 50;
        const dew     = h.dew_point_2m ?? null;
        const cloud   = h.cloud_cover ?? 0;
        const cape    = h.cape ?? 0;
        const snow    = h.snowfall ?? 0;
        const time    = new Date(h.time);
        const hr      = time.getHours();
        const night   = hr < 7 || hr >= 22;
        const pKey    = h.time;

        // ── Конвективный анализ по всем доступным параметрам ──
        const li      = h.lifted_index          ?? 0;
        const cin     = h.convective_inhibition  ?? 0;
        const dewDep  = dew != null ? t - dew : 10;
        const shear   = gust - wind;  // приземный сдвиг (гусь − средний)

        // ── Давленческие уровни (850/700/500 гПа) ──
        const T850  = h.temperature_850hPa   ?? null;
        const T700  = h.temperature_700hPa   ?? null;
        const T500  = h.temperature_500hPa   ?? null;
        const Td850 = h.dewpoint_850hPa      ?? null;
        const Td700 = h.dewpoint_700hPa      ?? null;
        const ws850 = h.windspeed_850hPa     ?? null;
        const ws500 = h.windspeed_500hPa     ?? null;
        const wd850 = h.winddirection_850hPa ?? null;
        const wd500 = h.winddirection_500hPa ?? null;

        // K-Index = (T850−T500) + Td850 − (T700−Td700)
        // >25: рассеянные, >30: многочисленные, >35: обильные грозы
        let kIndex = null;
        if (T850 != null && T700 != null && T500 != null && Td850 != null && Td700 != null)
            kIndex = (T850 - T500) + Td850 - (T700 - Td700);

        // Totals-Totals = T850 + Td850 − 2×T500
        // >44: возможны, >50: вероятны сильные, >55: опасные грозы
        let ttIndex = null;
        if (T850 != null && T500 != null && Td850 != null)
            ttIndex = T850 + Td850 - 2 * T500;

        // Вертикальный сдвиг ветра 850–500 гПа (векторная разность, м/с)
        // >10: умеренный (организованная конвекция), >20: сильный (суперячейки)
        let vShear = null;
        if (ws850 != null && ws500 != null && wd850 != null && wd500 != null) {
            const toRad = d => d * Math.PI / 180;
            const u850 = -ws850 * Math.sin(toRad(wd850));
            const v850 = -ws850 * Math.cos(toRad(wd850));
            const u500 = -ws500 * Math.sin(toRad(wd500));
            const v500 = -ws500 * Math.cos(toRad(wd500));
            vShear = Math.sqrt((u850 - u500) ** 2 + (v850 - v500) ** 2);
        }

        const hasPressureData = kIndex != null || ttIndex != null;

        let cScore = 0;
        // CAPE — энергия подъёма
        if (cape > 200)  cScore += 1;
        if (cape > 500)  cScore += 1;
        if (cape > 1000) cScore += 1;
        if (cape > 2000) cScore += 1;
        // Lifted Index
        if (li <  0)  cScore += 1;
        if (li < -2)  cScore += 1;
        if (li < -4)  cScore += 1;
        // CIN — торможение конвекции
        if      (cin > -50)  cScore += 2;
        else if (cin > -100) cScore += 1;
        else if (cin < -200) cScore -= 3;
        // Влажность приземная
        if (rh > 65) cScore += 1;
        if (rh > 80) cScore += 1;
        // Дефицит точки росы
        if (dewDep < 5) cScore += 1;
        if (dewDep < 3) cScore += 1;
        // Сдвиг ветра приземный
        if (shear > 5)  cScore += 1;
        if (shear > 10) cScore += 1;
        // Дневной прогрев
        if (hr >= 11 && hr <= 20) cScore += 1;
        // Облачность (инсоляция)
        if (cloud < 70) cScore += 1;
        // K-Index
        if (kIndex != null) {
            if (kIndex > 25) cScore += 1;
            if (kIndex > 30) cScore += 1;
            if (kIndex > 35) cScore += 1;
        }
        // Totals-Totals
        if (ttIndex != null) {
            if (ttIndex > 44) cScore += 1;
            if (ttIndex > 50) cScore += 1;
            if (ttIndex > 55) cScore += 1;
        }
        // Вертикальный сдвиг 850–500 гПа
        if (vShear != null) {
            if (vShear > 10) cScore += 1;
            if (vShear > 20) cScore += 1;
        }

        // Пороги: при наличии данных по уровням давления повышаем (max доп. ~8 очков)
        const pB = hasPressureData ? 5 : 0;
        const thunderByCode = code >= 95;
        const thunderByCAPE = cScore >= (9  + pB) && cape > 500;
        const convLevel3    = cScore >= (8  + pB) && cape > 300 && !thunderByCode && !thunderByCAPE;
        const convLevel2    = cScore >= (6  + pB) && cape > 200 && !thunderByCode && !thunderByCAPE && !convLevel3;
        const convLevel1    = cScore >= (4  + pB) && cape > 100 && !thunderByCode && !thunderByCAPE && !convLevel3 && !convLevel2;

        if (thunderByCode || thunderByCAPE) {
            const severe = cape > 1500 || gust > 20;
            const tag    = thunderByCode ? "" : " [расч]";
            const liStr  = h.lifted_index != null ? h.lifted_index.toFixed(1) : "?";
            const cinStr = h.convective_inhibition != null ? h.convective_inhibition.toFixed(0) : "?";
            const kStr   = kIndex  != null ? ` · K ${kIndex.toFixed(0)}`    : "";
            const ttStr  = ttIndex != null ? ` · TT ${ttIndex.toFixed(0)}`  : "";
            const vsStr  = vShear  != null ? ` · Sh ${vShear.toFixed(0)}м/с` : "";
            alerts.push({
                time: pKey, icon: "⛈️",
                title: severe ? "Сильная гроза" : "Гроза",
                sub: `CAPE ${Math.round(cape)} · LI ${liStr} · CIN ${cinStr}${kStr}${ttStr}${vsStr} · балл ${cScore}${tag}`,
                level: severe ? "red" : "orange"
            });
        }
        if (convLevel3) {
            const tProb = Math.min(80, Math.round(
                30 + (cScore - (8 + pB)) * 15
                + (cape > 600 ? 10 : 0)
                + (li < -3   ?  5 : 0)
                + (kIndex  != null && kIndex  > 30 ? 10 : 0)
                + (ttIndex != null && ttIndex > 50 ?  5 : 0)
            ));
            const kStr  = kIndex  != null ? ` · K ${kIndex.toFixed(0)}`    : "";
            const ttStr = ttIndex != null ? ` · TT ${ttIndex.toFixed(0)}`  : "";
            const vsStr = vShear  != null ? ` · Sh ${vShear.toFixed(0)}м/с` : "";
            alerts.push({
                time: pKey, icon: "⛈️",
                title: `Возможна гроза ~${tProb}%`,
                sub: `CAPE ${Math.round(cape)} · LI ${li.toFixed(1)} · CIN ${cin.toFixed(0)}${kStr}${ttStr}${vsStr} · балл ${cScore}`,
                level: "orange"
            });
        }
        if (convLevel2) {
            const kStr  = kIndex  != null ? ` · K ${kIndex.toFixed(0)}`   : "";
            const ttStr = ttIndex != null ? ` · TT ${ttIndex.toFixed(0)}` : "";
            alerts.push({
                time: pKey, icon: "🌩️",
                title: "Условия для развития гроз",
                sub: `CAPE ${Math.round(cape)} · LI ${li.toFixed(1)} · CIN ${cin.toFixed(0)}${kStr}${ttStr} · балл ${cScore}`,
                level: "yellow"
            });
        }
        if (convLevel1) {
            const kStr  = kIndex  != null ? ` · K ${kIndex.toFixed(0)}`   : "";
            const ttStr = ttIndex != null ? ` · TT ${ttIndex.toFixed(0)}` : "";
            alerts.push({
                time: pKey, icon: "⚡",
                title: "Грозовое положение",
                sub: `CAPE ${Math.round(cape)} · LI ${li.toFixed(1)}${kStr}${ttStr} · балл ${cScore}`,
                level: "blue"
            });
        }

        // Торнадо / смерч — очень высокий CAPE + сильный сдвиг ветра
        if (cape > 2500 && gust > 25 && rain > 0) {
            alerts.push({
                time: pKey, icon: "🌪️",
                title: "Риск смерча/торнадо",
                sub: `CAPE ${Math.round(cape)} Дж/кг · порывы ${gust.toFixed(0)} м/с`,
                level: "red"
            });
        }

        // Ураган (ветер ≥ 33 м/с = шкала Бофора 12)
        if (gust >= 33) {
            alerts.push({
                time: pKey, icon: "🌀",
                title: "Ураган",
                sub: `порывы ${gust.toFixed(0)} м/с`,
                level: "red"
            });
        }

        // Шторм (ветер 20–32 м/с)
        if (gust >= 20 && gust < 33 && code < 95) {
            alerts.push({
                time: pKey, icon: "💨",
                title: gust >= 28 ? "Жестокий шторм" : "Шквалы",
                sub: `порывы ${gust.toFixed(0)} м/с`,
                level: gust >= 28 ? "red" : "orange"
            });
        }

        // Туман: видимость < 1 км ИЛИ dew_point близко к температуре
        const dewGap = dew != null ? t - dew : 99;
        if (vis < 1000) {
            alerts.push({
                time: pKey, icon: "🌫️",
                title: vis < 200 ? "Густой туман" : "Туман",
                sub: `видимость ${(vis / 1000).toFixed(1)} км · влажность ${Math.round(rh)}%`,
                level: vis < 200 ? "orange" : "yellow"
            });
        } else if (vis < 10000 && rh > 80) {
            alerts.push({
                time: pKey, icon: "🌁",
                title: rh > 90 ? "Дымка" : "Мгла",
                sub: `видимость ${(vis / 1000).toFixed(1)} км · влажность ${Math.round(rh)}%`,
                level: "yellow"
            });
        }

        // Заморозок: ночью/утром, t < 4°, ясно, тихо
        if (t < 4 && (night || hr < 10) && cloud < 30 && wind < 3) {
            const ground = t - 2; // температура поверхности ~на 2° ниже воздуха
            alerts.push({
                time: pKey, icon: "🧊",
                title: t < 0 ? "Мороз" : "Заморозок",
                sub: `${t.toFixed(1)}°C · на почве ≈ ${ground.toFixed(0)}°C`,
                level: t < 0 ? "orange" : "yellow"
            });
        }

        // Роса: dewGap мал, умеренная температура, тихо, утро
        if (dewGap <= 3 && t >= 4 && t < 18 && wind < 4 && (hr >= 3 && hr <= 10)) {
            alerts.push({
                time: pKey, icon: "💧",
                title: "Роса",
                sub: `точка росы ${dew != null ? dew.toFixed(1) : "?"}°C · разница ${dewGap.toFixed(1)}°`,
                level: "yellow"
            });
        }

        // Сильный снег
        if (snow > 2) {
            alerts.push({
                time: pKey, icon: "❄️",
                title: snow > 5 ? "Сильный снегопад" : "Снегопад",
                sub: `${snow.toFixed(1)} мм/ч`,
                level: snow > 5 ? "orange" : "yellow"
            });
        }

        // Ливень
        if (rain > 10 && code < 95) {
            alerts.push({
                time: pKey, icon: "🌧️",
                title: "Сильный ливень",
                sub: `${rain.toFixed(1)} мм/ч`,
                level: "orange"
            });
        }

        // Жара
        if (feel > 38) {
            alerts.push({
                time: pKey, icon: "🌡️",
                title: feel > 42 ? "Опасная жара" : "Сильная жара",
                sub: `ощущается ${feel.toFixed(0)}°C`,
                level: feel > 42 ? "red" : "orange"
            });
        }
    // Духота
        if (t > 25 && rh > 65 && !night) {
            const hi = t - (0.55 - 0.0055 * rh) * (t - 14.5);
            if (hi > 28) alerts.push({
                time: pKey, icon: "😰",
                title: hi > 35 ? "Сильная духота" : "Духота",
                sub: `T ${t.toFixed(0)}°C · влажность ${Math.round(rh)}%`,
                level: hi > 35 ? "orange" : "yellow"
            });
        }

        // Тропическая ночь
        if (night && t > 20) {
            alerts.push({
                time: pKey, icon: "🌙",
                title: "Тропическая ночь",
                sub: `T ${t.toFixed(1)}°C`,
                level: "yellow"
            });
        }
    });

// --- Резкое похолодание / потепление (за 12ч) ---
    for (let i = 12; i < hours.length; i++) {
        const t0 = hours[i-12].temperature_2m, t1 = hours[i].temperature_2m;
        if (t0 == null || t1 == null) continue;
        const dt = t1 - t0;
        if (dt < -8) {
            alerts.push({ time: hours[i].time, icon: "🥶",
                title: "Резкое похолодание",
                sub: `ΔT ${dt.toFixed(1)}°C за 12ч`, level: dt < -12 ? "orange" : "yellow" });
            break;
        }
        if (dt > 8) {
            alerts.push({ time: hours[i].time, icon: "🌡️",
                title: "Резкое потепление",
                sub: `ΔT +${dt.toFixed(1)}°C за 12ч`, level: "yellow" });
            break;
        }
    }

    // --- Длительные осадки (>=18ч подряд >= 0.3 мм/ч) ---
    { let rc = 0, rs = null;
      hours.forEach(h => {
        const r = (h.rain ?? 0) + (h.showers ?? 0);
        if (r >= 0.3) { if (!rs) rs = h.time; rc++; }
        else { if (rc >= 18) alerts.push({ time: rs, icon: "🌧️",
            title: "Длительные осадки", sub: `${rc}ч подряд`, level: "orange" });
          rc = 0; rs = null; }
      });
      if (rc >= 18) alerts.push({ time: rs, icon: "🌧️",
          title: "Длительные осадки", sub: `${rc}ч подряд`, level: "orange" });
    }

    // --- Сухой период (>=72ч без осадков при T>20) ---
    { let dc = 0, ds = null;
      hours.forEach(h => {
        const r = (h.rain ?? 0) + (h.showers ?? 0) + (h.snowfall ?? 0);
        if (r < 0.05 && (h.temperature_2m ?? 0) > 20) { if (!ds) ds = h.time; dc++; }
        else { dc = 0; ds = null; }
      });
      if (dc >= 72) alerts.push({ time: ds, icon: "🏜️",
          title: "Засушливый период", sub: `${dc}ч без осадков`, level: "yellow" });
    }

    // --- Шквальная линия (скачок P > 2 гПа/ч + порывы > 10 м/с) ---
    for (let i = 1; i < hours.length; i++) {
        const p0 = hours[i-1].pressure_msl, p1 = hours[i].pressure_msl;
        const g  = hours[i].wind_gusts_10m ?? 0;
        if (p0 != null && p1 != null && (p1 - p0) > 2 && g > 10) {
            alerts.push({ time: hours[i].time, icon: "⚡",
                title: "Шквальная линия",
                sub: `скачок P +${(p1-p0).toFixed(1)} гПа/ч · порывы ${g.toFixed(0)} м/с`,
                level: "orange" });
            break;
        }
    }

    // Убираем дубли: гроза — уникально по часу, остальные — по дню
    const seen = new Set();
    const deduped = alerts.filter(a => {
        const d = new Date(a.time);
        const isThunder = a.title === "Гроза" || a.title === "Сильная гроза";
        const bucket = isThunder
            ? `${a.title}_${d.toISOString().slice(0, 13)}`
            : `${a.title}_${d.toISOString().slice(0, 10)}`;
        if (seen.has(bucket)) return false;
        seen.add(bucket);
        return true;
    });

    return deduped;
}

function goodWeatherWindows(hours, minHours = 3) {
    const windows = [];
    let start = null, count = 0;

    hours.forEach((h, i) => {
        const wind  = h.wind_speed_10m ?? 0;
        const gust  = h.wind_gusts_10m ?? wind;
        const cloud = h.cloud_cover ?? 100;
        const rain  = (h.rain ?? 0) + (h.showers ?? 0);
        const code  = h.weather_code ?? 0;
        const t     = h.temperature_2m ?? 0;
        const vis   = h.visibility ?? 0;

        const good = wind < 6 && gust < 10 && cloud < 50 && rain < 0.1
                  && code < 45 && t > 8 && vis > 5000;

        if (good) {
            if (start === null) start = i;
            count++;
        } else {
            if (count >= minHours) {
                windows.push({ from: hours[start].time, to: hours[i - 1].time, len: count });
            }
            start = null; count = 0;
        }
    });
    if (count >= minHours) {
        windows.push({ from: hours[start].time, to: hours[hours.length - 1].time, len: count });
    }
    return windows;
}

function renderAlertsBlock(hours) {
    const container = document.getElementById("fcAlertsBlock");
    if (!container) return;

    const alerts   = weatherAlerts(hours);
    const synoptic = synopticDiagnosis(hours);   // ← добавлено
    const windows  = goodWeatherWindows(hours);

    const LEVEL_COLOR = { red: "#ff4d4d", orange: "#ff9f5c", yellow: "#ffd166", blue: "#74b9ff" };
    const LEVEL_BG    = { red: "rgba(255,77,77,0.08)", orange: "rgba(255,159,92,0.08)", yellow: "rgba(255,209,102,0.08)", blue: "rgba(116,185,255,0.08)" };

    let html = "";

    if (alerts.length === 0 && windows.length === 0 && synoptic.length === 0) {  // ← добавлено synoptic
        container.innerHTML = "";
        return;
    }

    // --- Синоптический диагноз (вверху, без привязки ко времени) ---
    if (synoptic.length) {
        html += `<div style="font-size:11px;color:#555;font-weight:700;letter-spacing:0.06em;margin-bottom:6px;padding:0 2px;">СИНОПТИКА</div>`;
        html += synoptic.map(d => `
            <div style="display:flex;align-items:center;gap:10px;
                         background:rgba(0,0,0,0.15);border:1px solid ${d.color}44;
                         border-radius:10px;padding:8px 12px;margin-bottom:6px;">
                <span style="font-size:20px;flex-shrink:0;">${d.icon}</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;font-weight:700;color:${d.color};">${d.label}</div>
                    <div style="font-size:11px;color:#666;margin-top:1px;">${d.sub}</div>
                </div>
            </div>`).join("");
    }

    if (alerts.length) {
        html += `<div style="font-size:11px;color:#555;font-weight:700;letter-spacing:0.06em;margin-bottom:6px;padding:0 2px;">ПРЕДУПРЕЖДЕНИЯ</div>`;
        html += alerts.map(a => {
            const d = new Date(a.time);
            const timeStr = d.toLocaleString("ru-RU", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" });
            const c  = LEVEL_COLOR[a.level] || "#aaa";
            const bg = LEVEL_BG[a.level]    || "rgba(100,100,100,0.08)";
            return `<div style="display:flex;align-items:center;gap:10px;
                         background:${bg};border:1px solid ${c}44;
                         border-radius:10px;padding:8px 12px;margin-bottom:6px;">
                <span style="font-size:20px;flex-shrink:0;">${a.icon}</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;font-weight:700;color:${c};">${a.title}</div>
                    <div style="font-size:11px;color:#666;margin-top:1px;">${a.sub}</div>
                </div>
                <div style="font-size:11px;color:#555;flex-shrink:0;text-align:right;">${timeStr}</div>
            </div>`;
        }).join("");
    }

    if (windows.length) {
        html += `<div style="font-size:11px;color:#555;font-weight:700;letter-spacing:0.06em;margin:${alerts.length ? "10px" : "0"} 0 6px;padding:0 2px;">ОКНО ХОРОШЕЙ ПОГОДЫ</div>`;
        html += windows.map(w => {
            const f  = new Date(w.from);
            const t2 = new Date(w.to);
            const fmt = d => d.toLocaleString("ru-RU", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" });
            return `<div style="display:flex;align-items:center;gap:10px;
                         background:rgba(95,224,143,0.08);border:1px solid rgba(95,224,143,0.3);
                         border-radius:10px;padding:8px 12px;margin-bottom:6px;">
                <span style="font-size:20px;flex-shrink:0;">🌤️</span>
                <div>
                    <div style="font-size:13px;font-weight:700;color:#5fe08f;">Хорошая погода · ${w.len} ч</div>
                    <div style="font-size:11px;color:#666;margin-top:1px;">${fmt(f)} — ${fmt(t2)}</div>
                </div>
            </div>`;
        }).join("");
    }

    container.innerHTML = html;
}

// =============================================
// WEATHER CODE & COMFORT
// =============================================
