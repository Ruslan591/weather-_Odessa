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
    if(statsBox){ statsBox.style.display="grid";
        const _frQ=Math.max(1,Math.floor(vAll.length/4));
        const _frTrend=vAll.length>4?Math.round(vAll.slice(-_frQ).reduce((a,b)=>a+b,0)/_frQ-vAll.slice(0,_frQ).reduce((a,b)=>a+b,0)/_frQ):0;
        const _frAn=analyzeFreezeLevel(avg,_frTrend,min,max);
        function _frLabel(){ const d0=new Date(times[0]),now=new Date(); if(d0.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()) return 'Завтра'; return d0.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); }
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_frLabel()}</div>
            <div class="fc-stat-value" style="color:${_frAn.color};font-size:13px;margin-bottom:6px;">${_frAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${_frAn.desc}</div>
        </div>
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
    if(statsBox){
        function _tpAvg(key){ const vs=hours.map(h=>h[key]??null).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; }
        function _tpLabel(){ const d0=new Date(times[0]),d1=new Date(times[times.length-1]),now=new Date(); if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return 'Завтра'; const fmt=d=>d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); return fmt(d0); }
        const _tpAn=analyzeTempProfile(_tpAvg('temperature_2m'),_tpAvg('temperature_925hPa'),_tpAvg('temperature_850hPa'),_tpAvg('temperature_700hPa'),_tpAvg('temperature_500hPa'));
        const _tp2m=_tpAvg('temperature_2m'),_tp850=_tpAvg('temperature_850hPa'),_tp700=_tpAvg('temperature_700hPa'),_tp500=_tpAvg('temperature_500hPa');
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_tpLabel()}</div>
            <div class="fc-stat-value" style="color:${_tpAn.color};font-size:13px;margin-bottom:6px;">${_tpAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${_tpAn.desc}</div>
            <div style="display:flex;flex-wrap:wrap;gap:8px;font-size:10px;">
                ${_tp2m!=null?`<span style="color:#ff8f00;">2м: <b>${_tp2m.toFixed(1)}°</b></span>`:''}
                ${_tp850!=null?`<span style="color:#fdcb6e;">850: <b>${_tp850.toFixed(1)}°</b></span>`:''}
                ${_tp700!=null?`<span style="color:#55efc4;">700: <b>${_tp700.toFixed(1)}°</b></span>`:''}
                ${_tp500!=null?`<span style="color:#74b9ff;">500: <b>${_tp500.toFixed(1)}°</b></span>`:''}
            </div>
            <div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo('cape')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">⚡ CAPE</button>
                    <button onclick="window._fcGoTo('vert_vel')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                </div>
            </div>
        </div>`; }
}

// ─── analyzeTempProfile ──────────────────────────────────────────────────────
function analyzeTempProfile(avgT2m, avgT925, avgT850, avgT700, avgT500){
    const lr_low = (avgT2m!=null&&avgT850!=null)?(avgT2m-avgT850)/1.5:null;
    const lr_mid = (avgT850!=null&&avgT500!=null)?(avgT850-avgT500)/4.0:null;
    const invLow  = avgT850!=null&&avgT2m!=null&&avgT850>avgT2m+3;
    const invMid  = avgT700!=null&&avgT850!=null&&avgT700>avgT850+2;
    const warmMass = avgT850!=null&&avgT850>15;
    const coldMass = avgT850!=null&&avgT850<0;
    const veryCold = avgT850!=null&&avgT850<-10;
    if(invLow)
        return {title:"Приземная инверсия",color:"#e17055",
            desc:"Температура у земли ниже, чем на 850 гПа — классическая приземная инверсия. Конвекция полностью подавлена. Вероятен туман, дымка, смог. Облачность низкая слоистая. Грозы исключены."};
    if(lr_mid!=null&&lr_mid>8)
        return {title:"Суперадиабатический градиент",color:"#ff0000",
            desc:"Вертикальный температурный градиент превышает сухоадиабатический — крайняя конвективная нестабильность. Вероятны мощные грозы, смерчи, крупный град. Немедленно проверьте CAPE и CIN."};
    if(lr_mid!=null&&lr_mid>6.5)
        return {title:"Нестабильная стратификация",color:"#ff6b6b",
            desc:"Крутой вертикальный температурный градиент — условия для активной конвекции. При достаточной влажности и триггере (фронт, прогрев) вероятны грозы, ливни, шквалы. Оцените CAPE и CIN."};
    if(lr_mid!=null&&lr_mid>5&&warmMass)
        return {title:"Тёплая умеренно нестабильная масса",color:"#fd79a8",
            desc:"Тёплый воздух на 850 гПа с умеренным вертикальным градиентом. Конвективный потенциал умеренный — грозы возможны во второй половине дня при дополнительном прогреве."};
    if(veryCold)
        return {title:"Арктическое вторжение",color:"#0984e3",
            desc:"Крайне холодный воздух на уровне 850 гПа. Арктическая воздушная масса. При осадках возможен снег до уровня моря. Интенсивный приземной прогрев даёт послефронтальную конвекцию."};
    if(coldMass)
        return {title:"Холодная воздушная масса",color:"#a29bfe",
            desc:"Холодный воздух на 850 гПа. Конвекция усиливается при дневном прогреве. Кратковременные ливни и отдельные грозы во второй половине дня. Ночью — стабилизация."};
    if(invMid)
        return {title:"Инверсия на 700 гПа",color:"#fdcb6e",
            desc:"Задавливающий слой инверсии на средней тропосфере. Конвекция ограничена — мелкие кучевые без мощного вертикального развития. Грозы маловероятны, осадки слабые."};
    if(lr_mid!=null&&lr_mid<3)
        return {title:"Устойчивая стратификация",color:"#55efc4",
            desc:"Слабый вертикальный температурный градиент — атмосфера устойчива. Конвекция подавлена. Осадки возможны как обложной дождь при наличии фронта. Грозы маловероятны."};
    return {title:"Нейтральная стратификация",color:"#aaa",
        desc:"Умеренный вертикальный температурный профиль — атмосфера в условно-нейтральном состоянии. Конвекция возможна при дополнительном триггере. Оцените CAPE и влажность."};
}

// ─── analyzeFreezeLevel ───────────────────────────────────────────────────────
function analyzeFreezeLevel(avgFreeze, trend, minFreeze, maxFreeze){
    const range=maxFreeze-minFreeze;
    if(avgFreeze>4500)
        return {title:"Очень высокая нулевая изотерма",color:"#ff6b6b",
            desc:"Изотерма 0°C исключительно высоко — жаркая тропическая воздушная масса. Снег в регионе исключён. Высокий риск тепловой конвекции и гроз. Повышенное испарение, тепловой дискомфорт."};
    if(avgFreeze>3500&&trend>300)
        return {title:"Рост нулевой изотермы",color:"#fdcb6e",
            desc:"Высокая и продолжающая расти изотерма — тёплая масса наступает. Потепление продолжается. Риска снега нет, возможны летние конвективные грозы при достаточной влажности."};
    if(avgFreeze>3500)
        return {title:"Высокая нулевая изотерма",color:"#ff8f00",
            desc:"Нулевая изотерма выше нормы — тёплый воздух господствует. Все осадки в жидком виде. При высокой влажности возможны грозы преимущественно во второй половине дня."};
    if(avgFreeze<300)
        return {title:"Изотерма у поверхности",color:"#0055ff",
            desc:"Нулевая изотерма практически у земли — сильное арктическое вторжение. Снегопад, гололёд, обледенение. Крайне опасные условия. Температура у земли ниже нуля."};
    if(avgFreeze<1000&&trend<-300)
        return {title:"Резкое опускание изотермы",color:"#74b9ff",
            desc:"Нулевая изотерма низко и быстро опускается — активный холодный фронт. Осадки переходят в мокрый снег и снег. Гололедица возможна при температуре у земли около нуля."};
    if(avgFreeze<1500)
        return {title:"Низкая нулевая изотерма",color:"#a29bfe",
            desc:"Нулевая изотерма ниже нормы — холодная воздушная масса. При осадках возможен мокрый снег на возвышенностях и ночью у моря. Температура у земли около нуля при облачности."};
    if(range>900)
        return {title:"Значительное колебание изотермы",color:"#00cec9",
            desc:`Нулевая изотерма колеблется на ${Math.round(range)} м — смена воздушных масс. Возможен переход осадков от дождя к мокрому снегу. Следите за температурой у земли в ночные часы.`};
    if(Math.abs(trend)>400)
        return {title:trend>0?"Потепление — рост изотермы":"Похолодание — опускание изотермы",
            color:trend>0?"#ff8f00":"#74b9ff",
            desc:trend>0?`Нулевая изотерма поднимается (+${Math.round(trend)} м за период) — тёплая масса наступает. Риск замерзания снижается.`:`Нулевая изотерма опускается (${Math.round(trend)} м за период) — холодеет. Следите за переходом осадков в снег.`};
    return {title:"Нулевая изотерма в норме",color:"#aaa",
        desc:"Уровень нулевой изотермы в пределах нормы. Осадки преимущественно жидкие. Устойчивые температурные условия без резких смен воздушных масс."};
}

// ─── analyzeWindBarbs ─────────────────────────────────────────────────────────
function analyzeWindBarbs(veer10_850, veer850_500, avgSpd850, avgSpd500, avgSpd300){
    const warmLow  = veer10_850!=null  && veer10_850>30;
    const coldLow  = veer10_850!=null  && veer10_850<-30;
    const warmMid  = veer850_500!=null && veer850_500>30;
    const coldMid  = veer850_500!=null && veer850_500<-30;
    const strongJet= avgSpd300!=null   && avgSpd300>25;
    const strongLow= avgSpd850!=null   && avgSpd850>12;
    if(warmLow&&warmMid)
        return {title:"Тёплая адвекция на всей высоте",color:"#ff9f5c",
            desc:"Вирация ветра с высотой на всех уровнях — интенсивная тёплая адвекция. Предфронтальный тёплый сектор или гребень. Слоистая облачность, обложные осадки. При достаточном CAPE — высокий конвективный потенциал."};
    if(coldLow&&coldMid)
        return {title:"Холодная адвекция на всей высоте",color:"#74b9ff",
            desc:"Ротация ветра с высотой на всех уровнях — активная холодная адвекция. Тыловая часть циклона или прохождение холодного фронта. Послефронтальные ливни, порывы ветра, прояснения после фронта."};
    if(warmLow&&coldMid)
        return {title:"Окклюзия / слоистая адвекция",color:"#fd79a8",
            desc:"Тёплая адвекция внизу и холодная на средних уровнях — структура окклюдированного фронта. Смешанные осадки, нестабильность. Уточните по геопотенциалу."};
    if(coldLow&&warmMid)
        return {title:"Термическое расслоение",color:"#a29bfe",
            desc:"Холодный воздух у земли при тёплом на средних уровнях. Инверсия подавляет конвекцию. Туман или низкая облачность при слабом приземном ветре. Осадки слабые слоистые."};
    if(strongJet&&!warmLow&&!coldLow)
        return {title:"Струйное течение / нейтральная адвекция",color:"#fdcb6e",
            desc:"Мощная струя на верхних уровнях без значительной термической адвекции у земли. Дивергенция под струёй может активизировать восходящие движения. Следите за геопотенциалом."};
    if(warmLow&&!warmMid&&!coldMid)
        return {title:"Тёплая адвекция в нижней тропосфере",color:"#fdcb6e",
            desc:"Вирация ветра от земли до 850 гПа — тёплая адвекция в нижнем слое. Слоистая облачность ниже 850 гПа, морось или слабый дождь. Характерно для тёплого фронта на расстоянии."};
    if(coldLow&&!warmMid&&!coldMid)
        return {title:"Холодная адвекция в нижней тропосфере",color:"#b2bec3",
            desc:"Ротация ветра у земли и на 850 гПа — холодная адвекция в нижнем слое. Прояснение после фронта или начало похолодания. Ветер порывистый при конвективной погоде."};
    if(strongLow)
        return {title:"Интенсивный горизонтальный перенос",color:"#55efc4",
            desc:"Высокие скорости ветра без выраженного вращения — интенсивный перенос воздушной массы. Погода определяется источником воздуха. Гроз нет при отсутствии сдвига и нестабильности."};
    return {title:"Нейтральный поток",color:"#aaa",
        desc:"Слабая адвекция на всех уровнях. Нейтральный вертикальный профиль ветра. Погода определяется крупномасштабным синоптическим фоном без выраженных динамических процессов."};
}

// ─── analyzePolarVortex ───────────────────────────────────────────────────────
function analyzePolarVortex(avgT10, avgT50, trend10){
    const t = avgT10 ?? avgT50;
    if(t==null) return {title:"Нет данных",color:"#555",desc:"Данные стратосферных уровней недоступны."};
    if(t>-30)
        return {title:"Внезапное стратосферное потепление",color:"#ff0000",
            desc:"Критический нагрев стратосферы — вихрь разрушается или смещается. Риск вторжения арктического воздуха в умеренные широты через 2-6 недель. Вероятны аномальные холода в Европе при южном смещении вихря."};
    if(t>-45)
        return {title:"Ослабленный полярный вихрь",color:"#ff6b6b",
            desc:"Полярный вихрь значительно ослаблен. Повышен риск прорывов холодного воздуха и блокирующих антициклонов в Европе. Возможны значительные температурные аномалии в ближайшие 2-4 недели."};
    if(t>-60)
        return {title:"Умеренный полярный вихрь",color:"#fdcb6e",
            desc:"Полярный вихрь в умеренном состоянии. Небольшой риск прорывов холода. Погода в умеренных широтах относительно нормальная, но возможны кратковременные вторжения холодных масс."};
    if(t>-75)
        return {title:"Сильный полярный вихрь",color:"#74b9ff",
            desc:"Полярный вихрь интенсивный, хорошо организован. Надёжная изоляция арктического воздуха. Зима в умеренных широтах без аномальных холодов. Типичная зональная циркуляция."};
    return {title:"Исключительно сильный вихрь",color:"#0055ff",
        desc:"Рекордно низкие температуры стратосферы — полярный вихрь максимально интенсивен. Полная изоляция Арктики. Мягкая зима в Европе, тёплые аномалии в умеренных широтах."};
}

// ─── analyzeGeopotential ─────────────────────────────────────────────────────
function analyzeGeopotential(avgZ500, trend, thickness, ridges, troughs){
    const norm=5550, anom=avgZ500-norm;
    const thickNorm=3950, thickAnom=thickness!=null?thickness-thickNorm:null;
    const warm=thickAnom!=null&&thickAnom>120, cold=thickAnom!=null&&thickAnom<-120;
    // Мощный гребень
    if(anom>150&&trend>30)
        return {title:"Нарастающий антициклон",color:"#ff8f00",
            desc:"Геопотенциал Z500 значительно выше нормы и продолжает расти — формируется мощный антициклонический гребень. Фронтальные системы заблокированы. Ожидается длительная ясная, жаркая погода. Ночью возможна инверсия и туман при высокой влажности."};
    if(anom>150&&trend<-30)
        return {title:"Гребень разрушается",color:"#fdcb6e",
            desc:"Геопотенциал пока выше нормы, но быстро падает — антициклонический гребень ослабевает. В ближайшие 12-18ч начнётся ухудшение: нарастание облачности, усиление ветра. Следите за траекторией ложбины по геопотенциалу."};
    if(anom>150)
        return {title:"Антициклонический гребень",color:"#ff8f00",
            desc:"Устойчивое поле высокого геопотенциала — гребень блокирует фронтальные системы. Ясная погода, слабый ветер, осадков нет. При длительном блокировании возможны накопление аэрозолей и ухудшение видимости у земли."};
    // Ложбина
    if(anom<-150&&trend<-30)
        return {title:"Углубляющаяся ложбина",color:"#3355ff",
            desc:"Геопотенциал Z500 ниже нормы и продолжает падать — ложбина активно углубляется. Ухудшение погоды нарастает: усиление ветра, обложные осадки, возможны грозы при достаточной неустойчивости. Проверьте омегу для оценки зон подъёма."};
    if(anom<-150&&cold)
        return {title:"Холодная ложбина",color:"#74b9ff",
            desc:"Глубокая ложбина с холодным воздухом в ядре. Активная конвекция при прогреве нижнего слоя: ливни, грозы, возможен крупный град. Холодный фронт или тыловая часть циклона. Оцените омегу и CAPE для прогноза интенсивности."};
    if(anom<-150)
        return {title:"Циклоническая ложбина",color:"#4488ff",
            desc:"Поле пониженного геопотенциала — развитая ложбина. Активная циклоническая погода: облачность, осадки, ветер. При наличии восходящих движений на 850 гПа возможны интенсивные осадки."};
    // Сильные тренды при нейтральном фоне
    if(trend>50)
        return {title:"Быстрый рост Z500",color:"#fdcb6e",
            desc:"Геопотенциал Z500 резко растёт — гребень наступает. Ожидается быстрое улучшение погоды в течение 6-12ч: рассеивание облачности, прекращение осадков, снижение ветра."};
    if(trend<-50)
        return {title:"Резкое падение Z500",color:"#74b9ff",
            desc:"Геопотенциал Z500 резко падает — активная ложбина приближается. Быстрое ухудшение: нарастание облачности, усиление ветра, осадки. Для прогноза интенсивности проверьте омегу."};
    // Термодинамика при нейтральном давлении
    if(warm&&ridges===0&&troughs===0)
        return {title:"Тёплое ядро / слабый фон",color:"#e17055",
            desc:"Тропосферный слой теплее нормы при нейтральном геопотенциале. Конвективный потенциал умеренный: во второй половине дня возможны кучево-дождевые облака и кратковременные ливни при достаточной влажности."};
    if(cold&&ridges===0&&troughs===0)
        return {title:"Холодное ядро / слабый фон",color:"#a29bfe",
            desc:"Тропосферный слой холоднее нормы при нейтральном геопотенциале. Послефронтальная холодная масса. Неустойчивость усиливается при дневном прогреве — вероятны кратковременные ливни и порывистый ветер."};
    // Нейтраль
    const actStr=ridges+troughs>0?` Экстремумов: гребней ${ridges}, ложбин ${troughs}.`:"";
    return {title:"Нейтральный фон",color:"#aaa",
        desc:`Геопотенциал Z500 близок к климатической норме, тренд слабо выражен.${actStr} Умеренная синоптическая активность без явных блокировок. Погода определяется локальными факторами и мелкомасштабными возмущениями.`};
}

// ─── analyzeWindProfile ──────────────────────────────────────────────────────
function analyzeWindProfile(shear, veerDeg, avgSpd300, avgSpd850){
    const strongJet=avgSpd300!=null&&avgSpd300>28;
    const modJet=avgSpd300!=null&&avgSpd300>18;
    const strongShear=shear!=null&&shear>9;
    const modShear=shear!=null&&shear>4;
    const warmAdv=veerDeg!=null&&veerDeg>20;
    const coldAdv=veerDeg!=null&&veerDeg<-20;
    const strongFlow=avgSpd850!=null&&avgSpd850>12;
    if(strongJet&&strongShear&&warmAdv)
        return {title:"Активная струя / тёплая адвекция",color:"#ff6b6b",
            desc:"Мощное струйное течение на 300 гПа с сильным вертикальным сдвигом и вирацией ветра. Дивергенция под струёй стимулирует восходящие движения. Тёплая адвекция усиливает нестабильность — высокий риск организованной конвекции. При CAPE > 500 Дж/кг вероятны суперячейки и гром."};
    if(strongJet&&strongShear&&coldAdv)
        return {title:"Струйное течение / холодная адвекция",color:"#74b9ff",
            desc:"Интенсивная струя с сильным сдвигом и ротацией ветра — холодная адвекция под струей. Тыловая часть циклона или активный холодный фронт. Нестабильные ливни с порывами ветра за фронтом. Оцените омегу."};
    if(strongJet&&!strongShear)
        return {title:"Струйное течение",color:"#fdcb6e",
            desc:"Интенсивное струйное течение на 300 гПа без сильного приземного сдвига. Дивергенция под струёй может активизировать циклогенез. Следите за геопотенциалом Z500 для оценки развития системы."};
    if(strongShear&&warmAdv)
        return {title:"Сильный сдвиг / тёплая адвекция",color:"#ff9f5c",
            desc:"Значительный вертикальный сдвиг ветра с вирацией — тёплая адвекция. Классические условия для организованной конвекции. При CAPE > 300 Дж/кг вероятны мультиячейковые грозы с градом."};
    if(strongShear&&coldAdv)
        return {title:"Сильный сдвиг / холодная адвекция",color:"#a29bfe",
            desc:"Сильный сдвиг с ротацией ветра — холодная адвекция в тылу циклона. Конвекция приземного нагрева при ясном небе. Послефронтальные ливни без длительных гроз, возможен шквал."};
    if(strongShear)
        return {title:"Сильный вертикальный сдвиг",color:"#ff8f00",
            desc:"Значительное изменение скорости ветра с высотой без явной термической адвекции. Условия для наклонной конвекции. При наличии влажности и подъёма возможны конвективные осадки."};
    if(modShear&&warmAdv)
        return {title:"Умеренный сдвиг / тёплая адвекция",color:"#fdcb6e",
            desc:"Умеренный вертикальный сдвиг с вирацией ветра — признак тёплой адвекции. Слоистая облачность, возможны обложные осадки у фронта. Конвективная активность ограниченная."};
    if(modShear&&coldAdv)
        return {title:"Умеренный сдвиг / холодная адвекция",color:"#b2bec3",
            desc:"Умеренная ротация ветра с высотой — холодная адвекция слабой интенсивности. Возможно слоистое облакообразование с моросью. Прохождение слабого фронта или тылового потока."};
    if(strongFlow)
        return {title:"Сильный однородный поток",color:"#55efc4",
            desc:"Высокие скорости ветра без значительного сдвига и адвекции. Синоптически обусловленный перенос воздушной массы. Ветер у земли может быть порывистым за счёт турбулентного перемешивания."};
    return {title:"Слабый однородный поток",color:"#aaa",
            desc:"Слабый вертикальный сдвиг ветра, нейтральная адвекция. Атмосферное течение однородное без ярко выраженных термодинамических процессов. Погодная ситуация спокойная, определяется крупномасштабным синоптическим фоном."};
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
    function windPlLabel(){ if(!times.length) return ''; const d0=new Date(times[0]),d1=new Date(times[times.length-1]); const fmt=d=>d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); const now=new Date(); if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return 'Завтра'; return fmt(d0); }

    function renderWindPeriodStats(){
        if(!statsBox) return;
        const avg=arr=>arr.filter(v=>v!=null).reduce((a,b)=>a+b,0)/(arr.filter(v=>v!=null).length||1);
        // Средние скорости
        const avgs=LEVELS.map(lv=>({ label:lv.label, color:lv.color, spd:avg(hours.map(h=>h[lv.spd]??null)), maxSpd:Math.max(...hours.map(h=>h[lv.spd]??0)) }));
        // Сдвиг 850→500 (прокси нестабильности)
        const spd850=avg(hours.map(h=>h.windspeed_850hPa??null)), spd500=avg(hours.map(h=>h.windspeed_500hPa??null));
        const shear=spd500-spd850;
        const shearLbl=shear>8?'🌀 Сильный вертикальный сдвиг → нестабильность':shear>4?'↑ Умеренный сдвиг':'→ Слабый сдвиг, однородный поток';
        const shearCol=shear>8?'#ff9f5c':shear>4?'#fdcb6e':'#aaa';
        // Адвекция: вирация/ротация 850→500
        function circAvg(dirs){ const n=dirs.filter(v=>v!=null).length; if(!n) return null; const sx=dirs.filter(v=>v!=null).reduce((s,d)=>s+Math.sin(d*Math.PI/180),0)/n, sy=dirs.filter(v=>v!=null).reduce((s,d)=>s+Math.cos(d*Math.PI/180),0)/n; return (Math.atan2(sx,sy)*180/Math.PI+360)%360; }
        const dir850=circAvg(hours.map(h=>h.winddirection_850hPa??null)), dir500=circAvg(hours.map(h=>h.winddirection_500hPa??null));
        const veer=dir850!=null&&dir500!=null?((dir500-dir850+360)%360):null;
        const veerN=veer!=null?(veer>180?veer-360:veer):null;
        const veerLbl=veerN==null?'—':veerN>20?`🌡️ Вирация +${Math.round(veerN)}° → тёплая адвекция`:veerN<-20?`❄️ Ротация ${Math.round(veerN)}° → холодная адвекция`:'→ Нейтральная адвекция';
        const windAn=analyzeWindProfile(shear,veerN,avg(hours.map(h=>h.windspeed_300hPa??null)),avg(hours.map(h=>h.windspeed_850hPa??null)));
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${windPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${windAn.color};font-size:13px;margin-bottom:6px;">${windAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${windAn.desc}</div>
            <div style="font-size:10px;color:#777;margin-bottom:3px;">${veerLbl}</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px;">
                ${avgs.map(lv=>`<span style="font-size:10px;color:${lv.color};">${lv.label}: <b>${lv.spd.toFixed(1)}</b><span style="color:#444;"> м/с</span></span>`).join(' · ')}
            </div>
            <div style="margin-top:6px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo('geo_height')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">⬆️ Геопотенциал Z500</button>
                    <button onclick="window._fcGoTo('vert_vel')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                </div>
            </div>
        </div>`; }

    function renderWindHourStats(iNow){
        if(!statsBox) return;
        const h=hours[iNow];
        statsBox.style.display="grid";
        statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;padding:4px 8px;"><div class="fc-stat-label" style="font-size:11px;color:#666;">${new Date(times[iNow]).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}</div></div>`+LEVELS.map(lv=>{ const v=h?h[lv.spd]:null,dir=h?h[lv.dir]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+' м/с':'—'}</div><div class="fc-stat-time">${dir!=null?windDir(dir)+' '+dir.toFixed(0)+'°':'&nbsp;'}</div></div>`; }).join("");
    }

    if(statsBox){
        renderWindPeriodStats();
        const svgWind=wrap.querySelector("svg");
        if(svgWind){ svgWind.addEventListener("touchmove",e=>{e.preventDefault(); const rect=svgWind.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgWind.viewBox.baseVal.width-48; const mx=(e.touches[0].clientX-rect.left)*svgWind.viewBox.baseVal.width/rect.width-38; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderWindHourStats(b2); },{passive:false}); svgWind.addEventListener("touchend",()=>renderWindPeriodStats()); svgWind.addEventListener("mousemove",e=>{ const rect=svgWind.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgWind.viewBox.baseVal.width-48; const mx=(e.clientX-rect.left)*svgWind.viewBox.baseVal.width/rect.width-38; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderWindHourStats(b2); }); svgWind.addEventListener("mouseleave",()=>renderWindPeriodStats()); }
    }
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
        function _wbCircDiff(kA,kB){ const ds=hours.map(h=>angleDiff(h[kA],h[kB])).filter(v=>v!=null); if(!ds.length) return null; const sx=ds.reduce((s,d)=>s+Math.sin(d*Math.PI/180),0)/ds.length,sy=ds.reduce((s,d)=>s+Math.cos(d*Math.PI/180),0)/ds.length; let r=(Math.atan2(sx,sy)*180/Math.PI+360)%360; return r>180?r-360:r; }
        function _wbAvgSpd(key){ const vs=hours.map(h=>h[key]??null).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; }
        function _wbLabel(){ const d0=new Date(times[0]),now=new Date(); if(d0.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()) return 'Завтра'; return d0.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); }
        const _wb_v10_850=_wbCircDiff('wind_direction_10m','winddirection_850hPa');
        const _wb_v850_500=_wbCircDiff('winddirection_850hPa','winddirection_500hPa');
        const _wbAn=analyzeWindBarbs(_wb_v10_850,_wb_v850_500,_wbAvgSpd('windspeed_850hPa'),_wbAvgSpd('windspeed_500hPa'),_wbAvgSpd('windspeed_300hPa'));
        const v1=veerLabel(angleDiff(h.wind_direction_10m, h.winddirection_850hPa));
        const v2=veerLabel(angleDiff(h.winddirection_850hPa, h.winddirection_500hPa));
        const g850=h.geopotential_height_850hPa, g500=h.geopotential_height_500hPa;
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_wbLabel()}</div>
            <div class="fc-stat-value" style="color:${_wbAn.color};font-size:13px;margin-bottom:6px;">${_wbAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${_wbAn.desc}</div>
        </div>
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
    // ── helpers ─────────────────────────────────────────────────────────────
    function synLabel(key,refLow,refHigh,h){ const v=h[key]; if(v==null) return {t:"—",c:"#555",s:""}; const mid=(refLow+refHigh)/2,pct=Math.round(((v-mid)/(refHigh-refLow))*200); if(v>refHigh) return {t:"Гребень +"+Math.abs(pct)+"%",c:"#ff8f00",s:"антициклон"}; if(v<refLow) return {t:"Ложбина −"+Math.abs(pct)+"%",c:"#74b9ff",s:"циклон"}; return {t:`Норма (${Math.round(v)} м)`,c:"#aaa",s:""}; }
    function detectRidgeTrough(key){ const vals=hours.map(h=>h[key]); const events=[]; for(let i=2;i<vals.length-2;i++){ const v=vals[i],p1=vals[i-1],p2=vals[i-2],n1=vals[i+1],n2=vals[i+2]; if(v==null||p1==null||n1==null) continue; if(v<=p1&&v<=p2&&v<=n1&&v<=n2) events.push({type:'trough',time:times[i],val:Math.round(v)}); if(v>=p1&&v>=p2&&v>=n1&&v>=n2) events.push({type:'ridge',time:times[i],val:Math.round(v)}); } return events; }
    function geoPlLabel(){ if(!times.length) return ''; const d0=new Date(times[0]),d1=new Date(times[times.length-1]); const fmt=d=>d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); const now=new Date(); if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return 'Завтра'; if(d0.toDateString()===d1.toDateString()) return fmt(d0); return fmt(d0)+' – '+fmt(d1); }

    function renderGeoPeriodStats(){
        if(!statsBox) return;
        const avg=arr=>arr.reduce((a,b)=>a+b,0)/arr.length;
        const z5all=hours.map(h=>h.geopotential_height_500hPa??null).filter(v=>v!=null);
        const z8all=hours.map(h=>h.geopotential_height_850hPa??null).filter(v=>v!=null);
        if(!z5all.length) return;
        const avgZ5=avg(z5all); const norm5=5550;
        const anom=avgZ5-norm5;
        const anomLbl=anom>80?'▲ Гребень':anom<-80?'▼ Ложбина':'→ Норма Z500';
        const anomCol=anom>80?'#ff8f00':anom<-80?'#74b9ff':'#aaa';
        // Тренд: первая четверть vs последняя
        const q=Math.max(1,Math.floor(z5all.length/4));
        const trend=avg(z5all.slice(-q))-avg(z5all.slice(0,q));
        const trendLbl=trend>40?`▲ +${Math.round(trend)}м → рост гребня`:trend<-40?`▼ ${Math.round(trend)}м → углубление ложбины`:'→ Z500 стабильный';
        const trendCol=trend>40?'#ff8f00':trend<-40?'#74b9ff':'#aaa';
        // Мощность (thickness 500-850)
        const thick=z8all.length===z5all.length&&z8all.length>0?avg(z5all.map((v,i)=>v-(z8all[i]||0))):null;
        const thickLbl=thick?(thick>4050?'→ тёплое ядро':thick<3850?'→ холодное ядро':'→ норма'):'';
        // Экстремумы
        const ev5=detectRidgeTrough('geopotential_height_500hPa');
        const ridges=ev5.filter(e=>e.type==='ridge').length, troughs=ev5.filter(e=>e.type==='trough').length;
        const nextEv=ev5.find(e=>new Date(e.time).getTime()>=Date.now());
        const nextEvStr=nextEv?`Ближайший: ${nextEv.type==='trough'?'⬇️ Ложбина':'⬆️ Гребень'} ${new Date(nextEv.time).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})} Z=${nextEv.val}м`:'чётких экстремумов нет';
        const geoAn=analyzeGeopotential(avgZ5,trend,thick,ridges,troughs);
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${geoPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${geoAn.color};font-size:13px;margin-bottom:6px;">${geoAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${geoAn.desc}</div>
            <div style="font-size:10px;color:${trendCol};margin-bottom:3px;">${trendLbl} · Z500: ${Math.round(avgZ5)} м</div>
            <div style="font-size:10px;color:#666;margin-bottom:3px;">${thick!=null?`Мощность: ${Math.round(thick)} м ${thickLbl} · `:''} Гребней: ${ridges}, Ложбин: ${troughs}</div>
            <div style="font-size:10px;color:#555;">${nextEvStr}</div>
            <div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo('vert_vel')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                    <button onclick="window._fcGoTo('wind_barbs')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">🌀 Разрез ветра</button>
                </div>
            </div>
        </div>`; }

    function renderGeoHourStats(iNow){
        if(!statsBox) return;
        const h=hours[iNow];
        const s5=synLabel('geopotential_height_500hPa',5400,5700,h);
        const events500=detectRidgeTrough('geopotential_height_500hPa');
        const nextEvent=events500.find(e=>new Date(e.time).getTime()>=Date.now());
        const evStr=nextEvent?`${nextEvent.type==='trough'?'⬇️ Ложбина':'⬆️ Гребень'} ${new Date(nextEvent.time).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})} Z=${nextEvent.val}м`:"нет чётких экстремумов";
        const iNow6=Math.min(iNow+6,hours.length-1);
        const z500now=hours[iNow]?.geopotential_height_500hPa, z500_6h=hours[iNow6]?.geopotential_height_500hPa;
        const tendency=z500now!=null&&z500_6h!=null?z500_6h-z500now:null;
        const tendStr=tendency!=null?(tendency>10?`▲ +${Math.round(tendency)}м/6ч → гребень`:tendency<-10?`▼ ${Math.round(tendency)}м/6ч → ложбина`:"→ стабильно"):"—";
        statsBox.style.display="grid";
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;padding:4px 8px;"><div class="fc-stat-label" style="font-size:11px;color:#666;">${new Date(times[iNow]).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Ближайший экстремум Z500</div><div class="fc-stat-value" style="color:#74b9ff;font-size:12px;">${evStr}</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Тенденция Z500</div><div class="fc-stat-value" style="color:#fdcb6e;font-size:13px;">${tendStr}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">500 гПа</div><div class="fc-stat-value" style="color:${s5.c};font-size:13px;">${s5.t}</div><div class="fc-stat-time">${s5.s}</div></div>
        ${LEVELS.map(lv=>{ const v=h[lv.key]; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label} гПа</div><div class="fc-stat-value" style="color:${lv.color};font-size:13px;">${v!=null?Math.round(v)+' м':'—'}</div></div>`; }).join("")}`; }

    if(statsBox){
        renderGeoPeriodStats();
        const svgGeo=wrap.querySelector("svg");
        if(svgGeo){ svgGeo.addEventListener("touchmove",e=>{e.preventDefault(); const rect=svgGeo.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgGeo.viewBox.baseVal.width-60; const mx=(e.touches[0].clientX-rect.left)*svgGeo.viewBox.baseVal.width/rect.width-50; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderGeoHourStats(b2); },{passive:false}); svgGeo.addEventListener("touchend",()=>renderGeoPeriodStats()); svgGeo.addEventListener("mousemove",e=>{ const rect=svgGeo.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgGeo.viewBox.baseVal.width-60; const mx=(e.clientX-rect.left)*svgGeo.viewBox.baseVal.width/rect.width-50; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderGeoHourStats(b2); }); svgGeo.addEventListener("mouseleave",()=>renderGeoPeriodStats()); }
    }
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
        const magMax=Math.max(Math.abs(w850||0),Math.abs(w700||0),Math.abs(w500||0));
        const nonZeroS=[s8,s7,s5].filter(s=>s!==0);
        const isMixed=nonZeroS.some(s=>s>0)&&nonZeroS.some(s=>s<0);
        if(magMax<0.025)
            return {title:"Нейтральный режим",color:"#636e72",
                desc:"Вертикальные движения практически отсутствуют. Атмосфера в квазистатическом состоянии — ни подъёма, ни субсиденса. Осадков и конвекции не ожидается."};
        if(isMixed&&magMax>0.07)
            return {title:"Фронтальная зона",color:"#e84393",
                desc:"Сильные разнонаправленные вертикальные движения — активная фронтальная зона. Вероятно прохождение атмосферного фронта: резкая смена погоды, облачность, осадки. Проверьте геопотенциал Z500 для определения направления движения фронта."};
        return {title:"Переходный режим",color:"#b2bec3",
            desc:"Умеренные разнонаправленные движения. Атмосфера перестраивается — возможен слабый фронт или смена синоптического режима. Для точного диагноза сравните с геопотенциалом Z500 и профилем ветра."};
    }

    // ── period analysis ────────────────────────────────────────────────────
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
        if(dominant.title.includes('Переход')||dominant.title.includes('Смеш')||dominant.title.includes('Фронт')){
            if(!recs.includes('⬆️ Геопотенциал Z500')) recs.push('⬆️ Геопотенциал Z500');
            if(!recs.includes('💨 Профиль ветра')) recs.push('💨 Профиль ветра');
        }
        // Тренд: первая и вторая половина периода по 850 гПа
        const _half=Math.floor(allIdx.length/2);
        const _hAvg=(sl,key)=>{ const vs=sl.map(i=>hours[i]?.[key]??null).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; };
        const _f1=_hAvg(allIdx.slice(0,_half),'vertical_velocity_850hPa'),_f2=_hAvg(allIdx.slice(_half),'vertical_velocity_850hPa');
        const trendNote=(_f1!=null&&_f2!=null&&Math.abs(_f2-_f1)>0.025)?(_f2<_f1?'↗ к концу периода нарастает подъём':'↘ к концу периода усиливается субсиденс'):'';
        // Nav кнопки
        const NAV={'⬆️ Геопотенциал Z500':'geo_height','🌡️ Профиль темп.':'temp_profile','💨 Профиль ветра':'wind_barbs'};
        const recBtns=recs.map(r=>`<button onclick="window._fcGoTo('${NAV[r]||r}')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">${r}</button>`).join('');
        statsBox.style.display='grid';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${periodLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${dominant.color};font-size:13px;margin-bottom:6px;">${dominant.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${dominant.desc}</div>
            ${trendNote?`<div style="font-size:10px;color:#a0a0a0;margin-top:4px;padding:3px 6px;background:rgba(255,255,255,0.03);border-radius:4px;">${trendNote}</div>`:''}
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
            ${recBtns?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;"><div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div><div style="display:flex;gap:5px;flex-wrap:wrap;">${recBtns}</div></div>`:''}
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
        const _pvVals=hours.map(h=>h?.temperature_10hPa??null).filter(v=>v!=null);
        const _pvAvg=_pvVals.length?_pvVals.reduce((a,b)=>a+b,0)/_pvVals.length:t10;
        const _pvQ=Math.max(1,Math.floor(_pvVals.length/4));
        const _pvTrend=_pvVals.length>4?_pvVals.slice(-_pvQ).reduce((a,b)=>a+b,0)/_pvQ-_pvVals.slice(0,_pvQ).reduce((a,b)=>a+b,0)/_pvQ:null;
        const _pvAn=analyzePolarVortex(_pvAvg,null,_pvTrend);
        const _pvTrendStr=_pvTrend!=null?(_pvTrend>2?`↑ нагрев +${_pvTrend.toFixed(1)}° → ослабление`:_pvTrend<-2?`↓ охлаждение ${_pvTrend.toFixed(1)}° → укрепление`:'→ стабильно'):'';
        function _pvPlLabel(){ const d0=new Date(times[0]),now=new Date(); if(d0.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()) return 'Завтра'; const fmt=d=>d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); return fmt(d0); }
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_pvPlLabel()} · сейчас: <span style="color:${pv.c};">${pv.l}</span></div>
            <div class="fc-stat-value" style="color:${_pvAn.color};font-size:13px;margin-bottom:6px;">${_pvAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:6px;">${_pvAn.desc}</div>
            ${_pvTrendStr?`<div style="font-size:10px;color:#777;">Тренд Т10: ${_pvTrendStr}</div>`:''}
        </div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 10 гПа</div><div class="fc-stat-value" style="color:#ff6b6b;">${t10!=null?t10.toFixed(1)+'°':'—'}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 50 гПа</div><div class="fc-stat-value" style="color:#a29bfe;">${t50!=null?t50.toFixed(1)+'°':'—'}</div></div>`; }
}

// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(key){
    if(typeof fcSwitchParam==='function') fcSwitchParam(key);
};
