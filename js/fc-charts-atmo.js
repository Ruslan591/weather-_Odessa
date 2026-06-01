function addMultiLineCrosshair(svgEl, allSeries, pad, iW, iH, W, times) {
    const ns = "http://www.w3.org/2000/svg";
    const crossV = document.createElementNS(ns, "line");
    crossV.setAttribute("stroke", "rgba(255,255,255,0.3)");
    crossV.setAttribute("stroke-width", "1");
    crossV.setAttribute("stroke-dasharray", "3 3");
    crossV.style.display = "none";
    svgEl.appendChild(crossV);

    const dots = allSeries.map(s => {
        const dot = document.createElementNS(ns, "circle");
        dot.setAttribute("r", "4");
        dot.setAttribute("fill", s.color);
        dot.setAttribute("stroke", "#111");
        dot.setAttribute("stroke-width", "2");
        dot.style.display = "none";
        svgEl.appendChild(dot);
        return dot;
    });

    function getIdx(mx) {
        let best = 0, bestDist = Infinity;
        allSeries[0].pts.forEach((p, i) => {
            if(!p) return;
            const dist = Math.abs(p.x - mx);
            if(dist < bestDist) { bestDist = dist; best = i; }
        });
        return best;
    }

    function showTip(e, idx) {
        let tip = document.getElementById("fcTooltip");
        if(!tip){
            tip = document.createElement("div");
            tip.id = "fcTooltip";
            tip.style.cssText = `position:fixed;z-index:999;pointer-events:none;background:rgba(20,20,20,0.97);border:1px solid #333;border-radius:10px;padding:10px 14px;font-size:12px;color:#eee;min-width:150px;box-shadow:0 4px 24px rgba(0,0,0,0.5);transition:opacity 0.1s;`;
            document.body.appendChild(tip);
        }
        const t = times[idx] ? new Date(times[idx]) : null;
        const timeStr = t && !isNaN(t) ? t.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}) : "";
        const rows = allSeries.map(s => {
            const v = s.data[idx];
            const extra = s.extraData ? (s.extraData[idx] != null ? ` <span style="color:#888;font-size:10px;">${windDir(s.extraData[idx])}</span>` : "") : "";
            return `<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:5px;"><span style="color:${s.color};font-size:11px;">${s.label}</span><span style="font-weight:700;">${v!=null ? v.toFixed(1)+s.unit : '\u2014'}${extra}</span></div>`;
        }).join("");
        tip.innerHTML = `<div style="color:#888;margin-bottom:4px;font-size:11px;">${timeStr}</div>${rows}`;
        tip.style.opacity = "1";
        const cx = e.clientX ?? (e.touches ? e.touches[0].clientX : 0);
        const cy = e.clientY ?? (e.touches ? e.touches[0].clientY : 0);
        const tipW = 170;
        tip.style.left = (cx + tipW + 20 > window.innerWidth ? cx - tipW - 12 : cx + 12) + "px";
        tip.style.top  = (cy - 50) + "px";
    }

    function move(mx, e) {
        const idx = getIdx(mx);
        const baseX = allSeries[0].pts[idx] ? allSeries[0].pts[idx].x : (pad.l + mx);
        crossV.setAttribute("x1", baseX); crossV.setAttribute("y1", pad.t);
        crossV.setAttribute("x2", baseX); crossV.setAttribute("y2", pad.t + iH);
        crossV.style.display = "";
        allSeries.forEach((s, si) => {
            const p = s.pts[idx];
            if(p){ dots[si].setAttribute("cx", p.x); dots[si].setAttribute("cy", p.y); dots[si].style.display = ""; }
            else  dots[si].style.display = "none";
        });
        showTip(e, idx);
    }

    function hide() {
        crossV.style.display = "none";
        dots.forEach(d => d.style.display = "none");
        const tip = document.getElementById("fcTooltip");
        if(tip) tip.style.opacity = "0";
    }

    svgEl.addEventListener("mousemove", e => {
        const rect = svgEl.getBoundingClientRect();
        move((e.clientX - rect.left) * W / rect.width, e);
    });
    svgEl.addEventListener("mouseleave", hide);
    svgEl.addEventListener("touchmove", e => {
        const touch = e.touches[0];
        const rect = svgEl.getBoundingClientRect();
        move((touch.clientX - rect.left) * W / rect.width, touch);
        e.preventDefault();
    }, { passive: false });
    svgEl.addEventListener("touchend", hide);
}

// =============================================
// ПРОФИЛЬ АТМОСФЕРЫ: НУЛЕВАЯ ИЗОТЕРМА
// =============================================
function calcFreezeHeight(h) {
    const lvls = [
        [0,    h.temperature_2m        ?? null],
        [1500, h.temperature_850hPa    ?? null],
        [3000, h.temperature_700hPa    ?? null],
        [5500, h.temperature_500hPa    ?? null],
    ].filter(([,t]) => t != null);
    if(lvls.length < 2) return null;
    if(lvls[0][1] <= 0) return 0;
    if(lvls[lvls.length-1][1] >= 0) return lvls[lvls.length-1][0];
    for(let i = 0; i < lvls.length-1; i++){
        const [h1,t1] = lvls[i], [h2,t2] = lvls[i+1];
        if(t1 >= 0 && t2 <= 0) return Math.round(h1 + (h2-h1) * t1 / (t1-t2));
    }
    return null;
}

function renderFreezeLevel(hours, times) {
    const wrap = document.getElementById("fcChartWrap");
    const statsBox = document.getElementById("fcStats");
    if(!wrap) return;
    const data = hours.map(h => calcFreezeHeight(h));
    const vAll = data.filter(v => v != null && !isNaN(v));
    if(!vAll.length){
        wrap.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных уровней давления</div>`;
        if(statsBox) statsBox.innerHTML = ""; return;
    }
    const W=320, H=160, pad={t:24,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r, iH=H-pad.t-pad.b;
    let vMin=Math.max(0,Math.min(...vAll)-300), vMax=Math.max(...vAll)+300;
    const tMin=new Date(times[0]).getTime(), tMax_=new Date(times[times.length-1]).getTime();
    const px = t => pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py = v => pad.t+(1-(v-vMin)/(vMax-vMin))*iH;
    const validPts = times.map((t,i) => data[i]!=null ? {x:px(t),y:py(data[i])} : null).filter(Boolean);
    let seg=[], linePath="";
    times.forEach((t,i) => {
        if(data[i]!=null) seg.push({x:px(t),y:py(data[i])});
        else if(seg.length){ linePath+=smooth(seg); seg=[]; }
    });
    if(seg.length) linePath+=smooth(seg);
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){
        const v=vMin+(vMax-vMin)*(1-i/4), y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${(v/1000).toFixed(1)}км</text>`;
    }
    const REF_LVLS=[{h:0,col:"#74b9ff",l:"0м"},{h:1500,col:"#4488aa",l:"850hPa"},{h:3000,col:"#336688",l:"700hPa"}];
    let refs="";
    REF_LVLS.forEach(r=>{ if(r.h<vMin||r.h>vMax) return; const y=py(r.h);
        refs+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="${r.col}" stroke-width="0.8" stroke-dasharray="3 3" stroke-opacity="0.5"/>
            <text x="${pad.l+iW-2}" y="${y-2}" text-anchor="end" font-size="7.5" fill="${r.col}" opacity="0.6">${r.l}</text>`; });
    const FC_DAY_NAMES=["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${(x+xE)/2}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW;
        nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    // Область заливки под кривой
    const aFill = linePath + ` L${validPts[validPts.length-1].x},${py(vMin)} L${validPts[0].x},${py(vMin)} Z`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs><linearGradient id="frzGrad" x1="0" y1="${pad.t}" x2="0" y2="${pad.t+iH}" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#74b9ff" stop-opacity="0.25"/><stop offset="100%" stop-color="#74b9ff" stop-opacity="0"/>
        </linearGradient></defs>
        ${yGrid}${xGrid}${nowLine}${refs}
        <path d="${aFill}" fill="url(#frzGrad)" stroke="none"/>
        <path d="${linePath}" fill="none" stroke="#74b9ff" stroke-width="2.5"/>
        ${yLabels}${xLabels}</svg>`;
    const svgEl=wrap.querySelector("svg");
    const cfg={label:"0°C изотерма",unit:" м",color:"#74b9ff"};
    if(svgEl) addCrosshair(svgEl,validPts,pad,iW,iH,W,"#74b9ff",data,times,cfg,true);
    const min=Math.min(...vAll),max=Math.max(...vAll),avg=Math.round(vAll.reduce((a,b)=>a+b,0)/vAll.length);
    const iMin=data.indexOf(min),iMax=data.indexOf(max);
    const tFmt=idx=>{ if(idx<0||!times[idx]) return ""; const d=new Date(times[idx]); return isNaN(d)?"":d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}); };
    const snowH=data.filter(v=>v!=null&&v<500).length;
    if(statsBox){ statsBox.style.display="grid"; statsBox.innerHTML=`
        <div class="fc-stat-card"><div class="fc-stat-label">Минимум</div><div class="fc-stat-value" style="color:#74b9ff;">${(min/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMin)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Максимум</div><div class="fc-stat-value" style="color:#ff8f00;">${(max/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMax)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Среднее</div><div class="fc-stat-value" style="color:#ccc;">${(avg/1000).toFixed(2)} км</div><div class="fc-stat-time">&nbsp;</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Снег у земли</div><div class="fc-stat-value" style="color:#74b9ff;">${snowH} ч</div><div class="fc-stat-time">&lt;500м</div></div>`; }
}

function renderTempProfile(hours, times) {
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {key:"temperature_2m",    label:"2м",   color:"#ff8f00"},
        {key:"temperature_850hPa",label:"850",  color:"#fdcb6e"},
        {key:"temperature_700hPa",label:"700",  color:"#00cec9"},
        {key:"temperature_500hPa",label:"500",  color:"#a29bfe"},
    ];
    const W=320,H=160,pad={t:24,r:10,b:28,l:38};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMin=Infinity,vMax=-Infinity;
    LEVELS.forEach(lv=>hours.forEach(h=>{ const v=h[lv.key]; if(v!=null){vMin=Math.min(vMin,v);vMax=Math.max(vMax,v);} }));
    if(vMin===Infinity){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных уровней давления</div>`; return; }
    const spr=vMax-vMin||4; vMin-=spr*0.12; vMax+=spr*0.12;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-(v-vMin)/(vMax-vMin))*iH;
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMin+(vMax-vMin)*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(0)}°</text>`; }
    let zeroLine="";
    if(vMin<0&&vMax>0){ const yZ=py(0);
        zeroLine=`<line x1="${pad.l}" y1="${yZ}" x2="${pad.l+iW}" y2="${yZ}" stroke="rgba(116,185,255,0.45)" stroke-width="1.2" stroke-dasharray="4 3"/>
            <text x="${pad.l-4}" y="${yZ+4}" text-anchor="end" font-size="9" fill="#74b9ff">0°</text>`; }
    const FC_DAY_NAMES=["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${(x+xE)/2}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW;
        nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths="";
    const allPts={};
    LEVELS.forEach(lv=>{ const dArr=hours.map(h=>h[lv.key]??null);
        const pts=times.map((t,i)=>dArr[i]!=null?{x:px(t),y:py(dArr[i])}:null);
        let seg=[],d="";
        pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        allPts[lv.key]=pts; });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:14px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:${lv.color};"><span style="display:inline-block;width:14px;height:2px;background:${lv.color};border-radius:1px;vertical-align:middle;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">${yGrid}${xGrid}${nowLine}${zeroLine}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){
        const allSeries=LEVELS.map(lv=>({
            label:lv.label, color:lv.color, unit:"°",
            data:hours.map(h=>h[lv.key]??null),
            pts:allPts[lv.key]
        }));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times);
    }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.key]:null; return `
            <div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div>
            <div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+'°':'—'}</div>
            <div class="fc-stat-time">сейчас</div></div>`; }).join(""); }
}

function renderWindProfile(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {spd:"wind_speed_10m",   dir:"wind_direction_10m",   label:"10м",  color:"#8bc34a"},
        {spd:"windspeed_850hPa", dir:"winddirection_850hPa", label:"850",  color:"#00cec9"},
        {spd:"windspeed_500hPa", dir:"winddirection_500hPa", label:"500",  color:"#a29bfe"},
    ];
    const W=320,H=160,pad={t:24,r:10,b:28,l:38};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMax=0;
    LEVELS.forEach(lv=>hours.forEach(h=>{ const v=h[lv.spd]; if(v!=null) vMax=Math.max(vMax,v); }));
    if(!vMax){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных</div>`; return; }
    vMax=Math.ceil((vMax+2)/5)*5;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-v/vMax)*iH;
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMax*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(0)}</text>`; }
    const FC_DAY_NAMES=["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${(x+xE)/2}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}:00</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW;
        nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths="",arrows="";
    const allPts={};
    LEVELS.forEach(lv=>{
        const sArr=hours.map(h=>h[lv.spd]??null), dArr=hours.map(h=>h[lv.dir]??null);
        const pts=times.map((t,i)=>sArr[i]!=null?{x:px(t),y:py(sArr[i])}:null);
        let seg=[],d="";
        pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        times.forEach((t,i)=>{ if(i%4!==0) return; const s=sArr[i],dir=dArr[i]; if(s==null||dir==null) return;
            const x=px(t),y=py(s),rad=(dir+180)*Math.PI/180,dx=Math.sin(rad)*5,dy=-Math.cos(rad)*5;
            arrows+=`<line x1="${x}" y1="${y}" x2="${x+dx}" y2="${y+dy}" stroke="${lv.color}" stroke-width="1.2" stroke-opacity="0.65"/>
                <circle cx="${x+dx}" cy="${y+dy}" r="1.3" fill="${lv.color}" opacity="0.5"/>`; });
        allPts[lv.spd]=pts; });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:14px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:${lv.color};"><span style="display:inline-block;width:14px;height:2px;background:${lv.color};border-radius:1px;vertical-align:middle;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <text x="${pad.l}" y="${pad.t-8}" font-size="8" fill="#444">м/с</text>
        ${yGrid}${xGrid}${nowLine}${paths}${arrows}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){
        const allSeries=LEVELS.map(lv=>({
            label:lv.label, color:lv.color, unit:" м/с",
            data:hours.map(h=>h[lv.spd]??null),
            pts:allPts[lv.spd],
            extraData:hours.map(h=>h[lv.dir]??null)
        }));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times);
    }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.spd]:null,dir=h?h[lv.dir]:null;
            return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div>
            <div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+' м/с':'—'}</div>
            <div class="fc-stat-time">${dir!=null?windDir(dir)+' '+dir.toFixed(0)+'°':'&nbsp;'}</div></div>`; }).join(""); }
}

// =============================================
// MAIN LINE CHART
// =============================================

// ─── УРОВНИ (обновлённые) ────────────────────────────────────────────────
// Используются в renderTempProfile, renderWindProfile, calcFreezeHeight

function calcFreezeHeight(h) {
    const lvls = [
        [0,    h.temperature_2m        ?? null],
        [750,  h.temperature_925hPa    ?? null],
        [1500, h.temperature_850hPa    ?? null],
        [3000, h.temperature_700hPa    ?? null],
        [5500, h.temperature_500hPa    ?? null],
    ].filter(([,t]) => t != null);
    if(lvls.length < 2) return null;
    if(lvls[0][1] <= 0) return 0;
    if(lvls[lvls.length-1][1] >= 0) return lvls[lvls.length-1][0];
    for(let i = 0; i < lvls.length-1; i++){
        const [h1,t1] = lvls[i], [h2,t2] = lvls[i+1];
        if(t1 >= 0 && t2 <= 0) return Math.round(h1 + (h2-h1) * t1 / (t1-t2));
    }
    return null;
}

// ─── ОБЩИЕ ХЕЛПЕРЫ ───────────────────────────────────────────────────────
const FC_DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];

function _xAxis(times, px, pad, iH, H) {
    let xGrid="", xLabels="";
    times.forEach((t,i) => {
        const d=new Date(t), hr=d.getHours(), x=px(t);
        if(hr===0){
            xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0);
            const xE=nxt?px(nxt):pad.l+parseInt(times.length);
            xLabels+=`<text x="${((x+(nxt?px(nxt):x+40))/2).toFixed(1)}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`;
        }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`;
    });
    return {xGrid, xLabels};
}

function _nowLine(times, px, pad, iH) {
    const nowTs=Date.now();
    const tMin=new Date(times[0]).getTime(), tMax_=new Date(times[times.length-1]).getTime();
    if(nowTs<tMin||nowTs>tMax_) return "";
    const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*(/* iW computed outside */0);
    // используем прямой расчёт
    return `<!-- nowline placeholder -->`;
}

function _makePx(times, pad, iW) {
    const tMin=new Date(times[0]).getTime(), tMax_=new Date(times[times.length-1]).getTime();
    return t => pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
}

function _nowLineX(times, px, pad, iH) {
    const nowTs=Date.now();
    const tMin=new Date(times[0]).getTime(), tMax_=new Date(times[times.length-1]).getTime();
    if(nowTs<tMin||nowTs>tMax_) return "";
    const xN=px(new Date(nowTs).toISOString().slice(0,16));
    return `<line x1="${nowTs}" y1="${pad.t}" x2="${nowTs}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`;
}

// ─── renderFreezeLevel ───────────────────────────────────────────────────
function renderFreezeLevel(hours, times) {
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const data=hours.map(h=>calcFreezeHeight(h));
    const vAll=data.filter(v=>v!=null&&!isNaN(v));
    if(!vAll.length){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных уровней давления</div>`; if(statsBox) statsBox.innerHTML=""; return; }
    const W=320,H=160,pad={t:24,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMin=Math.max(0,Math.min(...vAll)-300),vMax=Math.max(...vAll)+300;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-(v-vMin)/(vMax-vMin))*iH;
    const validPts=times.map((t,i)=>data[i]!=null?{x:px(t),y:py(data[i])}:null).filter(Boolean);
    let seg=[],linePath="";
    times.forEach((t,i)=>{ if(data[i]!=null) seg.push({x:px(t),y:py(data[i])}); else if(seg.length){linePath+=smooth(seg);seg=[];} });
    if(seg.length) linePath+=smooth(seg);
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMin+(vMax-vMin)*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${(v/1000).toFixed(1)}км</text>`; }
    const REF=[{h:0,col:"#74b9ff",l:"0м"},{h:1500,col:"#4488aa",l:"850"},  {h:3000,col:"#336688",l:"700"}];
    let refs=""; REF.forEach(r=>{ if(r.h<vMin||r.h>vMax) return; const y=py(r.h);
        refs+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="${r.col}" stroke-width="0.8" stroke-dasharray="3 3" stroke-opacity="0.5"/>
            <text x="${pad.l+iW-2}" y="${y-2}" text-anchor="end" font-size="7.5" fill="${r.col}" opacity="0.6">${r.l}</text>`; });
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    const aFill=validPts.length>1?linePath+` L${validPts[validPts.length-1].x},${py(vMin)} L${validPts[0].x},${py(vMin)} Z`:"";
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">
        <defs><linearGradient id="frzGrad" x1="0" y1="${pad.t}" x2="0" y2="${pad.t+iH}" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#74b9ff" stop-opacity="0.25"/><stop offset="100%" stop-color="#74b9ff" stop-opacity="0"/></linearGradient></defs>
        ${yGrid}${xGrid}${nowLine}${refs}
        ${aFill?`<path d="${aFill}" fill="url(#frzGrad)" stroke="none"/>`:""}
        <path d="${linePath}" fill="none" stroke="#74b9ff" stroke-width="2.5"/>
        ${yLabels}${xLabels}</svg>`;
    const svgEl=wrap.querySelector("svg");
    const cfg={label:"0°C изотерма",unit:" м",color:"#74b9ff"};
    if(svgEl) addCrosshair(svgEl,validPts,pad,iW,iH,W,"#74b9ff",data,times,cfg,true);
    const min=Math.min(...vAll),max=Math.max(...vAll),avg=Math.round(vAll.reduce((a,b)=>a+b,0)/vAll.length);
    const iMin=data.indexOf(min),iMax=data.indexOf(max);
    const tFmt=idx=>{ if(idx<0||!times[idx]) return ""; const d=new Date(times[idx]); return isNaN(d)?"":d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}); };
    const snowH=data.filter(v=>v!=null&&v<500).length;
    if(statsBox){ statsBox.style.display="grid"; statsBox.innerHTML=`
        <div class="fc-stat-card"><div class="fc-stat-label">Минимум</div><div class="fc-stat-value" style="color:#74b9ff;">${(min/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMin)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Максимум</div><div class="fc-stat-value" style="color:#ff8f00;">${(max/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMax)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Среднее</div><div class="fc-stat-value" style="color:#ccc;">${(avg/1000).toFixed(2)} км</div><div class="fc-stat-time">&nbsp;</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Снег у земли</div><div class="fc-stat-value" style="color:#74b9ff;">${snowH} ч</div><div class="fc-stat-time">&lt;500м</div></div>`; }
}

// ─── renderTempProfile ───────────────────────────────────────────────────
function renderTempProfile(hours, times) {
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {key:"temperature_2m",    label:"2м",  color:"#ff8f00"},
        {key:"temperature_925hPa",label:"925", color:"#ff6b6b"},
        {key:"temperature_850hPa",label:"850", color:"#fdcb6e"},
        {key:"temperature_700hPa",label:"700", color:"#55efc4"},
        {key:"temperature_500hPa",label:"500", color:"#74b9ff"},
        {key:"temperature_300hPa",label:"300", color:"#a29bfe"},
    ];
    const W=320,H=160,pad={t:24,r:10,b:28,l:38};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMin=Infinity,vMax=-Infinity;
    LEVELS.forEach(lv=>hours.forEach(h=>{ const v=h[lv.key]; if(v!=null){vMin=Math.min(vMin,v);vMax=Math.max(vMax,v);} }));
    if(vMin===Infinity){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных уровней давления</div>`; return; }
    const spr=vMax-vMin||4; vMin-=spr*0.12; vMax+=spr*0.12;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-(v-vMin)/(vMax-vMin))*iH;
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMin+(vMax-vMin)*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(0)}°</text>`; }
    let zeroLine="";
    if(vMin<0&&vMax>0){ const yZ=py(0); zeroLine=`<line x1="${pad.l}" y1="${yZ}" x2="${pad.l+iW}" y2="${yZ}" stroke="rgba(116,185,255,0.45)" stroke-width="1.2" stroke-dasharray="4 3"/><text x="${pad.l-4}" y="${yZ+4}" text-anchor="end" font-size="9" fill="#74b9ff">0°</text>`; }
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths=""; const allPts={};
    LEVELS.forEach(lv=>{ const dArr=hours.map(h=>h[lv.key]??null);
        let seg=[],d="";
        const pts=times.map((t,i)=>dArr[i]!=null?{x:px(t),y:py(dArr[i])}:null);
        pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        allPts[lv.key]=pts; });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;vertical-align:middle;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">${yGrid}${xGrid}${nowLine}${zeroLine}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=LEVELS.map(lv=>({label:lv.label,color:lv.color,unit:"°",data:hours.map(h=>h[lv.key]??null),pts:allPts[lv.key]}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.key]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+'°':'—'}</div><div class="fc-stat-time">сейчас</div></div>`; }).join(""); }
}

// ─── renderWindProfile ───────────────────────────────────────────────────
function renderWindProfile(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {spd:"wind_speed_10m",   dir:"wind_direction_10m",   label:"10м",  color:"#8bc34a"},
        {spd:"windspeed_925hPa", dir:"winddirection_925hPa", label:"925",  color:"#55efc4"},
        {spd:"windspeed_850hPa", dir:"winddirection_850hPa", label:"850",  color:"#00cec9"},
        {spd:"windspeed_700hPa", dir:"winddirection_700hPa", label:"700",  color:"#fdcb6e"},
        {spd:"windspeed_500hPa", dir:"winddirection_500hPa", label:"500",  color:"#74b9ff"},
        {spd:"windspeed_300hPa", dir:"winddirection_300hPa", label:"300",  color:"#a29bfe"},
    ];
    const W=320,H=160,pad={t:24,r:10,b:28,l:38};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMax=0;
    LEVELS.forEach(lv=>hours.forEach(h=>{ const v=h[lv.spd]; if(v!=null) vMax=Math.max(vMax,v); }));
    if(!vMax){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:160px;color:#555;font-size:13px;">нет данных</div>`; return; }
    vMax=Math.ceil((vMax+2)/5)*5;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-v/vMax)*iH;
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMax*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(0)}</text>`; }
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths="",arrows=""; const allPts={};
    LEVELS.forEach(lv=>{
        const sArr=hours.map(h=>h[lv.spd]??null), dArr=hours.map(h=>h[lv.dir]??null);
        const pts=times.map((t,i)=>sArr[i]!=null?{x:px(t),y:py(sArr[i])}:null);
        let seg=[],d=""; pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        times.forEach((t,i)=>{ if(i%4!==0) return; const s=sArr[i],dir=dArr[i]; if(s==null||dir==null) return;
            const x=px(t),y=py(s),rad=(dir+180)*Math.PI/180,dx=Math.sin(rad)*5,dy=-Math.cos(rad)*5;
            arrows+=`<line x1="${x}" y1="${y}" x2="${x+dx}" y2="${y+dy}" stroke="${lv.color}" stroke-width="1.2" stroke-opacity="0.65"/><circle cx="${x+dx}" cy="${y+dy}" r="1.3" fill="${lv.color}" opacity="0.5"/>`; });
        allPts[lv.spd]=pts; });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;vertical-align:middle;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;"><text x="${pad.l}" y="${pad.t-8}" font-size="8" fill="#444">м/с</text>${yGrid}${xGrid}${nowLine}${paths}${arrows}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=LEVELS.map(lv=>({label:lv.label,color:lv.color,unit:" м/с",data:hours.map(h=>h[lv.spd]??null),pts:allPts[lv.spd],extraData:hours.map(h=>h[lv.dir]??null)}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.spd]:null,dir=h?h[lv.dir]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+' м/с':'—'}</div><div class="fc-stat-time">${dir!=null?windDir(dir)+' '+dir.toFixed(0)+'°':'&nbsp;'}</div></div>`; }).join(""); }
}

// ─── renderWindBarbs ─────────────────────────────────────────────────────
function renderWindBarbs(hours, times) {
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {spd:"windspeed_300hPa", dir:"winddirection_300hPa", geo:"geopotential_height_300hPa", defH:9000, label:"300 гПа"},
        {spd:"windspeed_500hPa", dir:"winddirection_500hPa", geo:"geopotential_height_500hPa", defH:5500, label:"500 гПа"},
        {spd:"windspeed_700hPa", dir:"winddirection_700hPa", geo:"geopotential_height_700hPa", defH:3000, label:"700 гПа"},
        {spd:"windspeed_850hPa", dir:"winddirection_850hPa", geo:"geopotential_height_850hPa", defH:1500, label:"850 гПа"},
        {spd:"wind_speed_10m",   dir:"wind_direction_10m",   geo:null,                          defH:10,   label:"10 м"},
    ];
    const W=320,H=178,pad={t:10,r:10,b:24,l:58};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=LEVELS.length, rowH=iH/nL;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    function spdColor(v){ if(v==null||v<1) return "#333"; if(v<5) return "#74b9ff"; if(v<10) return "#55efc4"; if(v<15) return "#fdcb6e"; if(v<20) return "#ff9f5c"; return "#ff6b6b"; }
    function spdLen(v){ if(v==null||v<1) return 0; return Math.min(15,Math.max(5,v*0.75)); }
    function arrowSvg(cx,cy,spd,dir){
        if(spd==null||dir==null||spd<0.5) return `<circle cx="${cx}" cy="${cy}" r="1.5" fill="#333"/>`;
        const col=spdColor(spd),len=spdLen(spd);
        const toRad=(dir+180)*Math.PI/180;
        const dx=Math.sin(toRad)*len,dy=-Math.cos(toRad)*len;
        const x1=cx-dx/2,y1=cy-dy/2,x2=cx+dx/2,y2=cy+dy/2;
        const hLen=3.5,hA=0.55;
        const h1x=x2-hLen*Math.sin(toRad-hA),h1y=y2+hLen*Math.cos(toRad-hA);
        const h2x=x2-hLen*Math.sin(toRad+hA),h2y=y2+hLen*Math.cos(toRad+hA);
        return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${col}" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="${x2.toFixed(1)}" y1="${y2.toFixed(1)}" x2="${h1x.toFixed(1)}" y2="${h1y.toFixed(1)}" stroke="${col}" stroke-width="1.8" stroke-linecap="round"/>
            <line x1="${x2.toFixed(1)}" y1="${y2.toFixed(1)}" x2="${h2x.toFixed(1)}" y2="${h2y.toFixed(1)}" stroke="${col}" stroke-width="1.8" stroke-linecap="round"/>`;
    }
    let arrows="",hLines="",yLabels="",xGrid="",xLabels="";
    LEVELS.forEach((lv,li)=>{
        const cy=pad.t+(li+0.5)*rowH, y0=pad.t+li*rowH, y1=pad.t+(li+1)*rowH;
        hLines+=`<rect x="${pad.l}" y="${y0}" width="${iW}" height="${rowH}" fill="${li%2===0?'rgba(255,255,255,0.015)':'rgba(0,0,0,0)'}"/><line x1="${pad.l}" y1="${y1}" x2="${pad.l+iW}" y2="${y1}" stroke="#1e1e1e" stroke-width="0.8"/>`;
        let realH=null;
        if(lv.geo){ for(let hi=0;hi<hours.length;hi++){ const g=hours[hi][lv.geo]; if(g!=null){realH=Math.round(g);break;} } }
        const hStr=realH!=null?`${(realH/1000).toFixed(1)}км`:`~${(lv.defH/1000).toFixed(1)}км`;
        yLabels+=`<text x="${pad.l-4}" y="${cy-5}" text-anchor="end" font-size="8.5" fill="#888">${lv.label}</text><text x="${pad.l-4}" y="${cy+7}" text-anchor="end" font-size="8" fill="#4a6a7a">${hStr}</text>`;
    });
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#333" stroke-dasharray="2 3"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${H-10}" text-anchor="middle" font-size="8" fill="#555" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-1}" text-anchor="middle" font-size="7.5" fill="#444">${hr}h</text>`; });
    times.forEach((t,i)=>{ const d=new Date(t); if(d.getHours()%3!==0) return;
        const x=px(t);
        LEVELS.forEach((lv,li)=>{ const cy=pad.t+(li+0.5)*rowH; const h=hours[i]; arrows+=arrowSvg(x,cy,h[lv.spd],h[lv.dir]); }); });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" stroke-dasharray="3 3"/>`; }
    const legendHtml=`<div style="display:flex;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;font-size:10px;"><span style="color:#555;">м/с:</span><span style="color:#74b9ff;">■&lt;5</span><span style="color:#55efc4;">■5-10</span><span style="color:#fdcb6e;">■10-15</span><span style="color:#ff9f5c;">■15-20</span><span style="color:#ff6b6b;">■20+</span></div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">${hLines}${xGrid}${nowLine}${arrows}${yLabels}${xLabels}</svg>${legendHtml}`;
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        function angleDiff(a,b){ if(a==null||b==null) return null; let d=((b-a)+360)%360; if(d>180) d-=360; return d; }
        function veerLabel(diff){ if(diff==null) return {t:"—",c:"#555",s:""}; if(Math.abs(diff)<15) return {t:"Нейтральный",c:"#aaa",s:""}; if(diff>0) return {t:`Вирация +${Math.round(diff)}°`,c:"#ff9f5c",s:"тёплая адвекция ↑"}; return {t:`Ротация ${Math.round(diff)}°`,c:"#74b9ff",s:"холодная адвекция ↓"}; }
        const v1=veerLabel(angleDiff(h.wind_direction_10m, h.winddirection_850hPa));
        const v2=veerLabel(angleDiff(h.winddirection_850hPa, h.winddirection_500hPa));
        const g850=h.geopotential_height_850hPa, g500=h.geopotential_height_500hPa;
        statsBox.innerHTML=`
        <div class="fc-stat-card"><div class="fc-stat-label">850 гПа</div><div class="fc-stat-value" style="color:#00cec9;">${g850!=null?Math.round(g850)+' м':'~1500 м'}</div><div class="fc-stat-time">высота уровня</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">500 гПа</div><div class="fc-stat-value" style="color:#74b9ff;">${g500!=null?Math.round(g500)+' м':'~5500 м'}</div><div class="fc-stat-time">высота уровня</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">10м → 850: ${v1.t}</div><div class="fc-stat-value" style="color:${v1.c};font-size:13px;">${v1.s}</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">850 → 500: ${v2.t}</div><div class="fc-stat-value" style="color:${v2.c};font-size:13px;">${v2.s}</div></div>`; }
}

// ─── renderGeopotentialChart ──────────────────────────────────────────────
function renderGeopotentialChart(hours, times) {
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {key:"geopotential_height_200hPa", label:"200", color:"#fdcb6e", refLow:11400,refHigh:12300},
        {key:"geopotential_height_250hPa", label:"250", color:"#fd79a8", refLow:9800, refHigh:10600},
        {key:"geopotential_height_300hPa", label:"300", color:"#a29bfe", refLow:8800, refHigh:9500},
        {key:"geopotential_height_500hPa", label:"500", color:"#74b9ff", refLow:5400, refHigh:5700},
        {key:"geopotential_height_700hPa", label:"700", color:"#55efc4", refLow:2850, refHigh:3150},
        {key:"geopotential_height_850hPa", label:"850", color:"#ff8f00", refLow:1350, refHigh:1600},
    ];
    const W=320,H=220,pad={t:24,r:10,b:28,l:50};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=LEVELS.length, trackH=iH/nL;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#333" stroke-dasharray="2 3"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-8}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" stroke-dasharray="3 3"/>`; }
    let hLines="",paths="",yLabels="",fills="",clipDefs="";
    const allPts={};
    LEVELS.forEach((lv,li)=>{
        const y0=pad.t+li*trackH, yMid=y0+trackH/2, y1=pad.t+(li+1)*trackH;
        clipDefs+=`<clipPath id="clip${li}"><rect x="${pad.l}" y="${y0}" width="${iW}" height="${trackH}"/></clipPath>`;
        hLines+=`<rect x="${pad.l}" y="${y0+1}" width="${iW}" height="${trackH-2}" fill="${li%2===0?'rgba(255,255,255,0.012)':'rgba(0,0,0,0)'}"/><line x1="${pad.l}" y1="${y1}" x2="${pad.l+iW}" y2="${y1}" stroke="#1e1e1e" stroke-width="0.8"/>`;
        const data=hours.map(h=>h[lv.key]??null);
        const valid=data.filter(v=>v!=null); if(!valid.length) return;
        const vMin=Math.min(...valid),vMax=Math.max(...valid),spr=vMax-vMin||50;
        const lo=vMin-spr*0.15,hi=vMax+spr*0.15;
        const innerH=trackH-6;
        const pyL=v=>y0+3+(1-(v-lo)/(hi-lo))*innerH;
        const refMid=(lv.refLow+lv.refHigh)/2;
        const yRef=pyL(refMid);
        const pts=times.map((t,i)=>data[i]!=null?{x:px(t),y:pyL(data[i])}:null);
        allPts[lv.key]=pts;
        let seg=[],d=""; pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        const validPts=pts.filter(Boolean);
        if(d&&validPts.length>1){
            const fp=d+` L${validPts[validPts.length-1].x},${yRef} L${validPts[0].x},${yRef} Z`;
            fills+=`<path d="${fp}" fill="${lv.color}" fill-opacity="0.12" clip-path="url(#clip${li})"/>`;
        }
        hLines+=`<line x1="${pad.l}" y1="${yRef}" x2="${pad.l+iW}" y2="${yRef}" stroke="${lv.color}" stroke-width="0.5" stroke-dasharray="2 4" stroke-opacity="0.3"/>`;
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${yMid+3}" text-anchor="end" font-size="8.5" fill="${lv.color}">${lv.label}</text>`;
    });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;font-size:10px;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;"></span>${lv.label}</span>`).join("")}<span style="color:#444;">· выше пунктира=гребень</span></div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;"><defs>${clipDefs}</defs>${hLines}${xGrid}${nowLine}${fills}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=LEVELS.map(lv=>({label:lv.label+' гПа',color:lv.color,unit:" м",data:hours.map(h=>h[lv.key]??null),pts:allPts[lv.key]||times.map(()=>null)}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        function synLabel(key,refLow,refHigh){ const v=h[key]; if(v==null) return {t:"—",c:"#555",s:""}; const mid=(refLow+refHigh)/2,pct=Math.round(((v-mid)/(refHigh-refLow))*200); if(v>refHigh) return {t:"Гребень +"+Math.abs(pct)+"%",c:"#ff8f00",s:"антициклон"}; if(v<refLow) return {t:"Ложбина −"+Math.abs(pct)+"%",c:"#74b9ff",s:"циклон"}; return {t:`Норма (${Math.round(v)} м)`,c:"#aaa",s:""}; }
        function detectRidgeTrough(key){ const vals=hours.map(h=>h[key]); const events=[]; for(let i=2;i<vals.length-2;i++){ const v=vals[i],p1=vals[i-1],p2=vals[i-2],n1=vals[i+1],n2=vals[i+2]; if(v==null||p1==null||n1==null) continue; if(v<=p1&&v<=p2&&v<=n1&&v<=n2) events.push({type:'trough',time:times[i],val:Math.round(v)}); if(v>=p1&&v>=p2&&v>=n1&&v>=n2) events.push({type:'ridge',time:times[i],val:Math.round(v)}); } return events; }
        const events500=detectRidgeTrough("geopotential_height_500hPa");
        const nextEvent=events500.find(e=>new Date(e.time).getTime()>=Date.now());
        const evStr=nextEvent?`${nextEvent.type==='trough'?'⬇️ Ложбина':'⬆️ Гребень'} ${new Date(nextEvent.time).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})} Z=${nextEvent.val}м`:"нет чётких экстремумов";
        const iNow6=Math.min(iNow+6,hours.length-1);
        const z500now=hours[iNow]?.geopotential_height_500hPa, z500_6h=hours[iNow6]?.geopotential_height_500hPa;
        const tendency=z500now!=null&&z500_6h!=null?z500_6h-z500now:null;
        const tendStr=tendency!=null?(tendency>10?`▲ +${Math.round(tendency)}м/6ч → гребень`:tendency<-10?`▼ ${Math.round(tendency)}м/6ч → ложбина`:"→ стабильно"):"—";
        const s5=synLabel("geopotential_height_500hPa",5400,5700);
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Ближайший экстремум Z500</div><div class="fc-stat-value" style="color:#74b9ff;font-size:12px;">${evStr}</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Тенденция Z500</div><div class="fc-stat-value" style="color:#fdcb6e;font-size:13px;">${tendStr}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">500 гПа</div><div class="fc-stat-value" style="color:${s5.c};font-size:13px;">${s5.t}</div><div class="fc-stat-time">${s5.s}</div></div>
        ${LEVELS.map(lv=>{ const v=h[lv.key]; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label} гПа</div><div class="fc-stat-value" style="color:${lv.color};font-size:13px;">${v!=null?Math.round(v)+' м':'—'}</div></div>`; }).join("")}`; }
}

// ─── renderVerticalVelocity ───────────────────────────────────────────────
// ─── renderVerticalVelocity ───────────────────────────────────────────────
function renderVerticalVelocity(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {key:"vertical_velocity_850hPa", label:"850 гПа", color:"#ff8f00"},
        {key:"vertical_velocity_700hPa", label:"700 гПа", color:"#55efc4"},
        {key:"vertical_velocity_500hPa", label:"500 гПа", color:"#74b9ff"},
    ];
    const W=320,H=165,pad={t:28,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    let vMin=Infinity,vMax=-Infinity;
    LEVELS.forEach(lv=>hours.forEach(h=>{ const v=h[lv.key]; if(v!=null){vMin=Math.min(vMin,v);vMax=Math.max(vMax,v);} }));
    if(vMin===Infinity){ wrap.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:165px;color:#555;font-size:13px;">нет данных vertical_velocity</div>`; return; }
    const spr=Math.max(Math.abs(vMin),Math.abs(vMax),0.05);
    vMin=-spr*1.2; vMax=spr*1.2;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-(v-vMin)/(vMax-vMin))*iH;
    const yZ=py(0);
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=vMin+(vMax-vMin)*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="8.5" fill="#555">${v.toFixed(2)}</text>`; }
    const zoneUp=`<rect x="${pad.l}" y="${pad.t}" width="${iW}" height="${yZ-pad.t}" fill="rgba(255,107,107,0.06)"/>`;
    const zoneDn=`<rect x="${pad.l}" y="${yZ}" width="${iW}" height="${pad.t+iH-yZ}" fill="rgba(116,185,255,0.06)"/>`;
    const zeroLine=`<line x1="${pad.l}" y1="${yZ}" x2="${pad.l+iW}" y2="${yZ}" stroke="rgba(255,255,255,0.2)" stroke-width="1.2"/>
        <text x="${pad.l+4}" y="${pad.t+10}" font-size="8" fill="rgba(255,107,107,0.5)">↑ восходящее</text>
        <text x="${pad.l+4}" y="${pad.t+iH-4}" font-size="8" fill="rgba(116,185,255,0.5)">↓ нисходящее</text>`;
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0);
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-8}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths="",fills=""; const allPts={};
    LEVELS.forEach(lv=>{
        const data=hours.map(h=>h[lv.key]??null);
        const pts=times.map((t,i)=>data[i]!=null?{x:px(t),y:py(data[i])}:null);
        let seg=[],d=""; pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d){ const validPts=pts.filter(Boolean);
            if(validPts.length>1){ const fp=d+` L${validPts[validPts.length-1].x},${yZ} L${validPts[0].x},${yZ} Z`; fills+=`<path d="${fp}" fill="${lv.color}" fill-opacity="0.08"/>`; }
            paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`; }
        allPts[lv.key]=pts; });
    const crossId="omgCross"+Date.now();
    const crossSvg=`<line id="${crossId}" x1="0" y1="${pad.t}" x2="0" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.4)" stroke-width="1" stroke-dasharray="3 3" style="display:none;"/>`;
    const legendHtml=`<div style="display:flex;justify-content:center;gap:12px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;font-size:10px;">${LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;"></span>${lv.label}</span>`).join("")}<span style="color:#555;">· Па/с, − = вверх · касание = детали</span></div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;touch-action:none;">${yGrid}${xGrid}${zoneUp}${zoneDn}${zeroLine}${nowLine}${fills}${paths}${crossSvg}${yLabels}${xLabels}</svg>${legendHtml}`;

    // ── helpers ──────────────────────────────────────────────────────────
    function omegaLabel(v){
        if(v==null) return {t:"—",c:"#555",s:""};
        if(v<-0.5)  return {t:"Мощный подъём",   c:"#ff4444",s:"ливни, грозы, возможен град"};
        if(v<-0.2)  return {t:"Умеренный подъём", c:"#ff8f00",s:"осадки вероятны"};
        if(v<-0.05) return {t:"Слабый подъём",    c:"#fdcb6e",s:"облачность развивается"};
        if(v< 0.05) return {t:"Нейтрально",       c:"#aaa",   s:"без выраженных процессов"};
        if(v< 0.2)  return {t:"Слабый спуск",     c:"#74b9ff",s:"без осадков"};
        if(v< 0.5)  return {t:"Умеренный спуск",  c:"#4488ff",s:"прояснение"};
        return              {t:"Мощный спуск",     c:"#0055ff",s:"жара, инверсия, антициклон"};
    }

    function sign(v,thr=0.05){ if(v==null) return 0; if(v<-thr) return -1; if(v>thr) return 1; return 0; }

    function analyzeOmega(w850,w700,w500){
        const s8=sign(w850),s7=sign(w700),s5=sign(w500);
        const strong=v=>v!=null&&Math.abs(v)>0.3;
        const mod=v=>v!=null&&Math.abs(v)>0.1;
        const allDn=s8>0&&s7>0&&s5>0, allUp=s8<0&&s7<0&&s5<0;
        if(allDn){
            if(strong(w850)&&strong(w700)&&strong(w500))
                return {title:"Мощный антициклон",color:"#0055ff",
                    desc:"Интенсивный субсиденс охватывает всю тропосферу от земли до 500 гПа. Воздух опускаясь нагревается — устойчивая инверсия температуры. Жара, небо ясное. Конвекция и грозы полностью исключены. Ночью возможен приземный радиационный туман или дымка из-за накопления влаги под инверсией."};
            if(mod(w850)&&mod(w700)&&mod(w500))
                return {title:"Антициклонический субсиденс",color:"#4488ff",
                    desc:"Опускание воздуха во всей тропосфере. Облака растворяются снизу вверх. Осадков нет. Устойчивая погода на 12-24ч вперёд. При длительном субсиденсе накапливаются аэрозоли и дымка у земли — видимость может ухудшаться к утру."};
            return {title:"Слабый субсиденс",color:"#74b9ff",
                desc:"Слабое нисходящее движение во всех слоях тропосферы. Погода стабильная, без осадков. Возможна переменная облачность, но конвективного развития не ожидается."};
        }
        if(allUp){
            if(strong(w850)&&strong(w700)&&strong(w500))
                return {title:"Мощная конвекция",color:"#ff2222",
                    desc:"Восходящее движение охватывает всю тропосферу — от земли до 500 гПа. Классический признак глубокой конвективной ячейки. Ливни, интенсивные грозы, возможен крупный град и шквалы. Характерно для суперячеек и мезомасштабных конвективных систем."};
            if(mod(w850)&&mod(w700)&&mod(w500))
                return {title:"Умеренная конвекция",color:"#ff8f00",
                    desc:"Восходящее движение во всей толще тропосферы. Осадки вероятны, особенно во второй половине дня. Кучево-дождевые облака развиваются по всей высоте. Грозы возможны, преимущественно одиночные ячейки."};
            return {title:"Слабая конвекция",color:"#fdcb6e",
                desc:"Слабый подъём воздуха на всех уровнях. Кучевая облачность развивается, возможен кратковременный дождь. Полноценных гроз маловероятно. Конвекция ограниченная, без глубокого вертикального развития."};
        }
        // Расслоение
        if(s8>0&&s7>0&&s5<0)
            return {title:"Блокирующий антициклон",color:"#6c5ce7",
                desc:"Субсиденс в нижней и средней тропосфере (850-700 гПа) при восходящем движении наверху (500 гПа). Инверсия субсиденса запирает влагу у земли. Туман и смог в утренние часы, особенно в долинах и над морем. Кучевые облака образуются, но не развиваются выше уровня инверсии."};
        if(s8<0&&s7<0&&s5>0)
            return {title:"Фронтальный подъём / тёплая адвекция",color:"#fd79a8",
                desc:"Подъём воздуха в нижней тропосфере (850-700 гПа) при субсиденсе сверху (500 гПа). Типично для тёплого фронта: у земли поднимается влажный воздух, формируются слоисто-дождевые облака. Обложные осадки без гроз, монотонный дождь. Температура постепенно повышается."};
        if(s8>0&&s7<0&&s5<0)
            return {title:"Конвекция подавлена",color:"#00b894",
                desc:"Подъём у земли (850 гПа) блокируется нисходящим потоком выше 700 гПа. «Лопнувшая» конвекция: кучевые облака образуются, но не развиваются в грозовые. Конвективный предел чётко выражен по высоте. Кратковременный ливень из конвективного облака возможен, но без грозовой активности."};
        if(s8<0&&s7>0&&s5>0)
            return {title:"Приземная / бризовая конвекция",color:"#e17055",
                desc:"Восходящее движение только у земли (850 гПа), выше — субсиденс. Термическая или бризовая конвекция без глубокого вертикального развития. Кучевые облака образуются ближе к полудню над сушей, к вечеру рассеиваются над морем. Грозы маловероятны."};
        if(s8<0&&s7>0&&s5<0)
            return {title:"Слоистая нестабильность",color:"#a29bfe",
                desc:"Нестабильность сосредоточена в среднем слое (700 гПа) при стабильных низах и верхах. Волновые облака или слоисто-дождевой фронт. Характерно для струйного течения с волновой активностью. Осадки слабые, преимущественно в виде мороси или обложного дождя."};
        if(s8>0&&s7<0&&s5>0)
            return {title:"Волновое возмущение",color:"#55efc4",
                desc:"Нисходящее движение в нижнем слое и наверху при подъёме в среднем слое (700 гПа). Признак баротропной волны или орографического возмущения в тропосфере. Погода переходная, возможна волновая облачность без осадков. Состояние кратковременное."};
        return {title:"Смешанный режим",color:"#aaa",
            desc:"Разнонаправленные вертикальные движения на разных уровнях. Переходное состояние атмосферы — смена синоптического режима или прохождение фронта. Прогнозировать погоду только по омеге сложно: обратитесь к геопотенциалу и термодинамике."};
    }

    // ── period analysis ────────────────────────────────────────────────────
    function getDayBuckets(){
        const buckets=[],seen=new Map();
        times.forEach((t,i)=>{
            const d=new Date(t);
            const key=d.getFullYear()*10000+d.getMonth()*100+d.getDate();
            if(!seen.has(key)){
                const now=new Date();
                const isTd=d.toDateString()===now.toDateString();
                const tm=new Date(now); tm.setDate(now.getDate()+1);
                const isTm=d.toDateString()===tm.toDateString();
                const lbl=isTd?'Сегодня':isTm?'Завтра':(FC_DAY_NAMES[d.getDay()]+' '+d.getDate());
                seen.set(key,buckets.length);
                buckets.push({label:lbl,indices:[]});
            }
            buckets[seen.get(key)].indices.push(i);
        });
        return buckets;
    }

    function analyzeOmegaPeriod(indices){
        const v850=[],v700=[],v500=[];
        indices.forEach(i=>{
            const h=hours[i];
            if(h?.vertical_velocity_850hPa!=null) v850.push(h.vertical_velocity_850hPa);
            if(h?.vertical_velocity_700hPa!=null) v700.push(h.vertical_velocity_700hPa);
            if(h?.vertical_velocity_500hPa!=null) v500.push(h.vertical_velocity_500hPa);
        });
        if(!v850.length) return null;
        const avg=arr=>arr.reduce((a,b)=>a+b,0)/arr.length;
        const avg850=avg(v850),avg700=v700.length?avg(v700):null,avg500=v500.length?avg(v500):null;
        let hoursUp=0,hoursDn=0,hoursNeut=0;
        indices.forEach(i=>{
            const h=hours[i];
            const w850=h?.vertical_velocity_850hPa??null,w700=h?.vertical_velocity_700hPa??null,w500=h?.vertical_velocity_500hPa??null;
            const ups=[w850,w700,w500].filter(v=>v!=null&&v<-0.05).length;
            const dns=[w850,w700,w500].filter(v=>v!=null&&v>0.05).length;
            if(ups>=2) hoursUp++; else if(dns>=2) hoursDn++; else hoursNeut++;
        });
        return {dominant:analyzeOmega(avg850,avg700,avg500),avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total:indices.length};
    }

    let _activePeriod=null;

    function renderPeriodStats(label,indices){
        if(!statsBox) return;
        _activePeriod=label;
        const res=analyzeOmegaPeriod(indices);
        const bar=document.getElementById('fcOmegaPeriodBar');
        if(bar) bar.querySelectorAll('button').forEach(btn=>{
            const active=btn.textContent.trim()===label;
            btn.style.borderColor=active?'#74b9ff':'#333';
            btn.style.color=active?'#74b9ff':'#666';
            btn.style.background=active?'rgba(116,185,255,0.12)':'transparent';
        });
        if(!res){statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;color:#555;">нет данных</div>`;return;}
        const {dominant,avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total}=res;
        const upPct=Math.round(hoursUp/total*100),dnPct=Math.round(hoursDn/total*100),neuPct=100-Math.round(hoursUp/total*100)-Math.round(hoursDn/total*100);
        const RECS=[
            ['конвекц',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['фронт',  ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['подъём', ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['антицикл',['⬆️ Геопотенциал Z500']],
            ['субсиденс',['⬆️ Геопотенциал Z500']],
            ['Смешанный',['⬆️ Геопотенциал Z500','💨 Профиль ветра']],
            ['Волновое',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['нестаб', ['🌡️ Профиль темп.','💨 Профиль ветра']],
        ];
        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">Период: ${label}</div>
            <div class="fc-stat-value" style="color:${dominant.color};font-size:13px;margin-bottom:6px;">${dominant.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${dominant.desc}</div>
            <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin:8px 0 3px;">
                <div style="flex:${hoursUp||0.1};background:#ff8f00;"></div>
                <div style="flex:${hoursNeut||0.1};background:#333;"></div>
                <div style="flex:${hoursDn||0.1};background:#4488ff;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:9px;color:#666;margin-bottom:6px;">
                <span style="color:#ff8f00;">▲ ${upPct}% подъём</span>
                <span>${neuPct}% нейтр.</span>
                <span style="color:#4488ff;">${dnPct}% ▼</span>
            </div>
            <div style="font-size:10px;color:#666;">
                Ср.омега · 850:<span style="color:#ff8f00;">${avg850.toFixed(3)}</span>${avg700!=null?` · 700:<span style="color:#55efc4;">${avg700.toFixed(3)}</span>`:''}${avg500!=null?` · 500:<span style="color:#74b9ff;">${avg500.toFixed(3)}</span>`:''}
            </div>
            ${recs.length?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;font-size:10px;color:#777;">Для уточнения: <span style="color:#aaa;">${recs.join(' · ')}</span></div>`:''}
        </div>`;
    }

    // ── period analysis ────────────────────────────────────────────────────
    function getDayBuckets(){
        const buckets=[],seen=new Map();
        times.forEach((t,i)=>{
            const d=new Date(t);
            const key=d.getFullYear()*10000+d.getMonth()*100+d.getDate();
            if(!seen.has(key)){
                const now=new Date();
                const isTd=d.toDateString()===now.toDateString();
                const tm=new Date(now); tm.setDate(now.getDate()+1);
                const isTm=d.toDateString()===tm.toDateString();
                const lbl=isTd?'Сегодня':isTm?'Завтра':(FC_DAY_NAMES[d.getDay()]+' '+d.getDate());
                seen.set(key,buckets.length);
                buckets.push({label:lbl,indices:[]});
            }
            buckets[seen.get(key)].indices.push(i);
        });
        return buckets;
    }

    function analyzeOmegaPeriod(indices){
        const v850=[],v700=[],v500=[];
        indices.forEach(i=>{
            const h=hours[i];
            if(h?.vertical_velocity_850hPa!=null) v850.push(h.vertical_velocity_850hPa);
            if(h?.vertical_velocity_700hPa!=null) v700.push(h.vertical_velocity_700hPa);
            if(h?.vertical_velocity_500hPa!=null) v500.push(h.vertical_velocity_500hPa);
        });
        if(!v850.length) return null;
        const avg=arr=>arr.reduce((a,b)=>a+b,0)/arr.length;
        const avg850=avg(v850),avg700=v700.length?avg(v700):null,avg500=v500.length?avg(v500):null;
        let hoursUp=0,hoursDn=0,hoursNeut=0;
        indices.forEach(i=>{
            const h=hours[i];
            const w850=h?.vertical_velocity_850hPa??null,w700=h?.vertical_velocity_700hPa??null,w500=h?.vertical_velocity_500hPa??null;
            const ups=[w850,w700,w500].filter(v=>v!=null&&v<-0.05).length;
            const dns=[w850,w700,w500].filter(v=>v!=null&&v>0.05).length;
            if(ups>=2) hoursUp++; else if(dns>=2) hoursDn++; else hoursNeut++;
        });
        return {dominant:analyzeOmega(avg850,avg700,avg500),avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total:indices.length};
    }

    let _activePeriod=null;

    function renderPeriodStats(label,indices){
        if(!statsBox) return;
        _activePeriod=label;
        const res=analyzeOmegaPeriod(indices);
        const bar=document.getElementById('fcOmegaPeriodBar');
        if(bar) bar.querySelectorAll('button').forEach(btn=>{
            const active=btn.textContent.trim()===label;
            btn.style.borderColor=active?'#74b9ff':'#333';
            btn.style.color=active?'#74b9ff':'#666';
            btn.style.background=active?'rgba(116,185,255,0.12)':'transparent';
        });
        if(!res){statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;color:#555;">нет данных</div>`;return;}
        const {dominant,avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total}=res;
        const upPct=Math.round(hoursUp/total*100),dnPct=Math.round(hoursDn/total*100),neuPct=100-Math.round(hoursUp/total*100)-Math.round(hoursDn/total*100);
        const RECS=[
            ['конвекц',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['фронт',  ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['подъём', ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['антицикл',['⬆️ Геопотенциал Z500']],
            ['субсиденс',['⬆️ Геопотенциал Z500']],
            ['Смешанный',['⬆️ Геопотенциал Z500','💨 Профиль ветра']],
            ['Волновое',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['нестаб', ['🌡️ Профиль темп.','💨 Профиль ветра']],
        ];
        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">Период: ${label}</div>
            <div class="fc-stat-value" style="color:${dominant.color};font-size:13px;margin-bottom:6px;">${dominant.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${dominant.desc}</div>
            <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin:8px 0 3px;">
                <div style="flex:${hoursUp||0.1};background:#ff8f00;"></div>
                <div style="flex:${hoursNeut||0.1};background:#333;"></div>
                <div style="flex:${hoursDn||0.1};background:#4488ff;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:9px;color:#666;margin-bottom:6px;">
                <span style="color:#ff8f00;">▲ ${upPct}% подъём</span>
                <span>${neuPct}% нейтр.</span>
                <span style="color:#4488ff;">${dnPct}% ▼</span>
            </div>
            <div style="font-size:10px;color:#666;">
                Ср.омега · 850:<span style="color:#ff8f00;">${avg850.toFixed(3)}</span>${avg700!=null?` · 700:<span style="color:#55efc4;">${avg700.toFixed(3)}</span>`:''}${avg500!=null?` · 500:<span style="color:#74b9ff;">${avg500.toFixed(3)}</span>`:''}
            </div>
            ${recs.length?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;font-size:10px;color:#777;">Для уточнения: <span style="color:#aaa;">${recs.join(' · ')}</span></div>`:''}
        </div>`;
    }

    // ── period analysis ─────────────────────────────────────────────────────
    function analyzeOmegaPeriod(indices){
        const v850=[],v700=[],v500=[];
        indices.forEach(i=>{
            const h=hours[i];
            if(h?.vertical_velocity_850hPa!=null) v850.push(h.vertical_velocity_850hPa);
            if(h?.vertical_velocity_700hPa!=null) v700.push(h.vertical_velocity_700hPa);
            if(h?.vertical_velocity_500hPa!=null) v500.push(h.vertical_velocity_500hPa);
        });
        if(!v850.length) return null;
        const avg=arr=>arr.reduce((a,b)=>a+b,0)/arr.length;
        const avg850=avg(v850),avg700=v700.length?avg(v700):null,avg500=v500.length?avg(v500):null;
        let hoursUp=0,hoursDn=0,hoursNeut=0;
        indices.forEach(i=>{
            const h=hours[i];
            const w850=h?.vertical_velocity_850hPa??null,w700=h?.vertical_velocity_700hPa??null,w500=h?.vertical_velocity_500hPa??null;
            const ups=[w850,w700,w500].filter(v=>v!=null&&v<-0.05).length;
            const dns=[w850,w700,w500].filter(v=>v!=null&&v>0.05).length;
            if(ups>=2) hoursUp++; else if(dns>=2) hoursDn++; else hoursNeut++;
        });
        return {dominant:analyzeOmega(avg850,avg700,avg500),avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total:indices.length};
    }

    function periodLabel(){
        if(!times.length) return '';
        const d0=new Date(times[0]),d1=new Date(times[times.length-1]);
        const fmt=d=>d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'});
        const now=new Date();
        if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return 'Сегодня';
        const tm=new Date(now); tm.setDate(now.getDate()+1);
        if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return 'Завтра';
        if(d0.toDateString()===d1.toDateString()) return fmt(d0);
        return fmt(d0)+' – '+fmt(d1);
    }

    function renderPeriodStats(){
        if(!statsBox) return;
        const allIdx=times.map((_,i)=>i);
        const res=analyzeOmegaPeriod(allIdx);
        if(!res){statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;color:#555;">нет данных</div>`;return;}
        const {dominant,avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total}=res;
        const upPct=Math.round(hoursUp/total*100),dnPct=Math.round(hoursDn/total*100),neuPct=100-Math.round(hoursUp/total*100)-Math.round(hoursDn/total*100);
        const RECS=[
            ['конвекц',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['фронт',  ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['подъём', ['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['антицикл',['⬆️ Геопотенциал Z500']],
            ['субсиденс',['⬆️ Геопотенциал Z500']],
            ['Смешанный',['⬆️ Геопотенциал Z500','💨 Профиль ветра']],
            ['Волновое',['⬆️ Геопотенциал Z500','🌡️ Профиль темп.']],
            ['нестаб', ['🌡️ Профиль темп.','💨 Профиль ветра']],
        ];
        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${periodLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${dominant.color};font-size:13px;margin-bottom:6px;">${dominant.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${dominant.desc}</div>
            <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;margin:8px 0 3px;">
                <div style="flex:${hoursUp||0.1};background:#ff8f00;"></div>
                <div style="flex:${hoursNeut||0.1};background:#333;"></div>
                <div style="flex:${hoursDn||0.1};background:#4488ff;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:9px;color:#666;margin-bottom:6px;">
                <span style="color:#ff8f00;">▲ ${upPct}% подъём</span>
                <span>${neuPct}% нейтр.</span>
                <span style="color:#4488ff;">${dnPct}% ▼</span>
            </div>
            <div style="font-size:10px;color:#666;">
                Ср.омега · 850:<span style="color:#ff8f00;">${avg850.toFixed(3)}</span>${avg700!=null?` · 700:<span style="color:#55efc4;">${avg700.toFixed(3)}</span>`:''}${avg500!=null?` · 500:<span style="color:#74b9ff;">${avg500.toFixed(3)}</span>`:''}
            </div>
            ${recs.length?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;font-size:10px;color:#777;">Для уточнения: <span style="color:#aaa;">${recs.join(' · ')}</span></div>`:''}
        </div>`; }

    // ── обновление карточек (почасовой) ──────────────────────────────────
    function renderStats(idx){
        if(!statsBox) return;
        const h=hours[idx];
        const t=times[idx]?new Date(times[idx]):null;
        const timeStr=t&&!isNaN(t)?t.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}):"";
        const w850=h?.vertical_velocity_850hPa??null;
        const w700=h?.vertical_velocity_700hPa??null;
        const w500=h?.vertical_velocity_500hPa??null;
        const o8=omegaLabel(w850),o7=omegaLabel(w700),o5=omegaLabel(w500);
        const an=analyzeOmega(w850,w700,w500);
        statsBox.style.display="grid";
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;padding:4px 8px;">
            <div class="fc-stat-label" style="font-size:11px;color:#666;">${timeStr||'сейчас'}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">850 гПа</div>
            <div class="fc-stat-value" style="color:${o8.c};font-size:12px;">${w850!=null?w850.toFixed(3)+' Па/с':'—'}</div>
            <div class="fc-stat-time" style="color:${o8.c};">${o8.t}</div>
            <div class="fc-stat-time">${o8.s}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">700 гПа</div>
            <div class="fc-stat-value" style="color:${o7.c};font-size:12px;">${w700!=null?w700.toFixed(3)+' Па/с':'—'}</div>
            <div class="fc-stat-time" style="color:${o7.c};">${o7.t}</div>
            <div class="fc-stat-time">${o7.s}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">500 гПа</div>
            <div class="fc-stat-value" style="color:${o5.c};font-size:12px;">${w500!=null?w500.toFixed(3)+' Па/с':'—'}</div>
            <div class="fc-stat-time" style="color:${o5.c};">${o5.t}</div>
            <div class="fc-stat-time">${o5.s}</div>
        </div>
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label">Синоптический анализ</div>
            <div class="fc-stat-value" style="color:${an.color};font-size:13px;margin-bottom:6px;">${an.title}</div>
            <div style="font-size:11px;line-height:1.55;color:#888;">${an.desc}</div>
        </div>`; }

    // ── touch/mouse handler ───────────────────────────────────────────────
    const svgEl=wrap.querySelector("svg");
    if(svgEl){
        const crossEl=document.getElementById(crossId);
        function getIdx(clientX){
            const rect=svgEl.getBoundingClientRect();
            const mx=(clientX-rect.left)*W/rect.width;
            let best=0,bestDist=Infinity;
            times.forEach((t,i)=>{ const d=Math.abs(px(t)-mx); if(d<bestDist){bestDist=d;best=i;} });
            return best;
        }
        function onMove(clientX){
            const idx=getIdx(clientX);
            if(crossEl){ const xc=px(times[idx]); crossEl.setAttribute("x1",xc); crossEl.setAttribute("x2",xc); crossEl.style.display=""; }
            renderStats(idx);
        }
        function onEnd(){
            if(crossEl) crossEl.style.display="none";
            renderPeriodStats();
        }
        svgEl.addEventListener("mousemove",e=>onMove(e.clientX));
        svgEl.addEventListener("mouseleave",onEnd);
        svgEl.addEventListener("touchmove",e=>{ e.preventDefault(); onMove(e.touches[0].clientX); },{passive:false});
        svgEl.addEventListener("touchend",onEnd);
    }

    // начальный рендер — анализ периода
    renderPeriodStats();
}

// ─── renderPolarVortex ────────────────────────────────────────────────────
function renderPolarVortex(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const GEO_LEVELS=[
        {key:"geopotential_height_10hPa",  label:"10 гПа",  color:"#ff6b6b"},
        {key:"geopotential_height_30hPa",  label:"30 гПа",  color:"#fd79a8"},
        {key:"geopotential_height_50hPa",  label:"50 гПа",  color:"#a29bfe"},
        {key:"geopotential_height_100hPa", label:"100 гПа", color:"#74b9ff"},
    ];
    const W=320,H=170,pad={t:28,r:10,b:28,l:50};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=GEO_LEVELS.length,trackH=iH/nL;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#333" stroke-dasharray="2 3"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+(nxt?px(nxt):pad.l+iW))/2).toFixed(1)}" y="${pad.t-8}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let hLines="",paths="",yLabels=""; const allPts={};
    GEO_LEVELS.forEach((lv,li)=>{
        const y0=pad.t+li*trackH,yMid=y0+trackH/2,y1=pad.t+(li+1)*trackH;
        hLines+=`<rect x="${pad.l}" y="${y0+1}" width="${iW}" height="${trackH-2}" fill="${li%2===0?'rgba(255,255,255,0.01)':'rgba(0,0,0,0)'}"/><line x1="${pad.l}" y1="${y1}" x2="${pad.l+iW}" y2="${y1}" stroke="#1e1e1e" stroke-width="0.8"/>`;
        const data=hours.map(h=>h[lv.key]??null);
        const valid=data.filter(v=>v!=null); if(!valid.length) return;
        const vMin=Math.min(...valid),vMax=Math.max(...valid),spr=vMax-vMin||100;
        const lo=vMin-spr*0.15,hi=vMax+spr*0.15,innerH=trackH-6;
        const pyL=v=>y0+3+(1-(v-lo)/(hi-lo))*innerH;
        const pts=times.map((t,i)=>data[i]!=null?{x:px(t),y:pyL(data[i])}:null);
        allPts[lv.key]=pts;
        let seg=[],d=""; pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${yMid+3}" text-anchor="end" font-size="8.5" fill="${lv.color}">${lv.label}</text>`; });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;font-size:10px;">${GEO_LEVELS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">${hLines}${xGrid}${nowLine}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=GEO_LEVELS.map(lv=>({label:lv.label,color:lv.color,unit:" м",data:hours.map(h=>h[lv.key]??null),pts:allPts[lv.key]||times.map(()=>null)}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        const t10=h?.temperature_10hPa,t50=h?.temperature_50hPa;
        function pvLabel(t){ if(t==null) return {l:"—",c:"#555",s:""}; if(t>-40) return {l:"Разрушен",c:"#ff6b6b",s:"риск ВСП → холод через 2-4 нед."}; if(t>-55) return {l:"Ослаблен",c:"#fd79a8",s:"возможны вторжения холода"}; if(t>-70) return {l:"Умеренный",c:"#fdcb6e",s:"умеренная изоляция"}; return {l:"Сильный",c:"#74b9ff",s:"защита от арктических вторжений"}; }
        const pv=pvLabel(t10);
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Полярный вихрь (10 гПа)</div><div class="fc-stat-value" style="color:${pv.c};font-size:13px;">${pv.l}</div><div class="fc-stat-time">${pv.s}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 10 гПа</div><div class="fc-stat-value" style="color:#ff6b6b;">${t10!=null?t10.toFixed(1)+'°':'—'}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 50 гПа</div><div class="fc-stat-value" style="color:#a29bfe;">${t50!=null?t50.toFixed(1)+'°':'—'}</div></div>`; }
}
