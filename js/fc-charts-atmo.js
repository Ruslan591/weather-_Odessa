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
