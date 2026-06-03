FILE = 'js/fc-charts-atmo.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(key){
    if(typeof fcSwitchParam==='function') fcSwitchParam(key);
};'''

NEW = '''// ─── renderHumidityProfile ───────────────────────────────────────────────
function renderHumidityProfile(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    const LEVELS=[
        {key:"relative_humidity_2m",    label:"2м",   color:"#74b9ff"},
        {key:"relative_humidity_850hPa",label:"850",  color:"#55efc4"},
        {key:"relative_humidity_700hPa",label:"700",  color:"#a29bfe"},
        {key:"relative_humidity_500hPa",label:"500",  color:"#fdcb6e"},
    ];
    const W=320,H=165,pad={t:24,r:10,b:28,l:38};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    // Проверка данных уровней
    const hasLevels=hours.some(h=>h.relative_humidity_850hPa!=null);
    const activeLevels=hasLevels?LEVELS:LEVELS.slice(0,1);
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    const py=v=>pad.t+(1-v/100)*iH;
    let yGrid="",yLabels="";
    for(let i=0;i<=4;i++){ const v=100*(1-i/4),y=pad.t+iH*i/4;
        yGrid+=`<line x1="${pad.l}" y1="${y}" x2="${pad.l+iW}" y2="${y}" stroke="#252525" stroke-width="1"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="#555">${v.toFixed(0)}%</text>`; }
    // Референсная линия 80% — порог насыщения
    const yRef=py(80);
    const refLine=`<line x1="${pad.l}" y1="${yRef}" x2="${pad.l+iW}" y2="${yRef}" stroke="#74b9ff" stroke-width="0.7" stroke-dasharray="3 4" stroke-opacity="0.4"/>
        <text x="${pad.l+iW-2}" y="${yRef-2}" text-anchor="end" font-size="7.5" fill="#74b9ff" opacity="0.5">80%</text>`;
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#444" stroke-dasharray="2 4"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+xE)/2).toFixed(1)}" y="${pad.t-6}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.3)" stroke-width="1.5" stroke-dasharray="4 3"/>`; }
    let paths=""; const allPts={};
    activeLevels.forEach(lv=>{
        const dArr=hours.map(h=>h[lv.key]??null);
        const pts=times.map((t,i)=>dArr[i]!=null?{x:px(t),y:py(Math.min(100,Math.max(0,dArr[i])))}:null);
        let seg=[],d="";
        pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="2"/>`;
        allPts[lv.key]=pts;
    });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:14px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;">${activeLevels.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;color:${lv.color};"><span style="display:inline-block;width:14px;height:2px;background:${lv.color};border-radius:1px;vertical-align:middle;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;">${yGrid}${xGrid}${nowLine}${refLine}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=activeLevels.map(lv=>({label:lv.label,color:lv.color,unit:"%",data:hours.map(h=>h[lv.key]??null),pts:allPts[lv.key]||times.map(()=>null)}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        function _hmAvg(key){ const vs=hours.map(h=>h[key]??null).filter(v=>v!=null); return vs.length?Math.round(vs.reduce((a,b)=>a+b,0)/vs.length):null; }
        function _hmLabel(){ const d0=new Date(times[0]),now=new Date(); if(d0.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()) return 'Завтра'; return d0.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); }
        const avg2m=_hmAvg('relative_humidity_2m');
        const avg850=_hmAvg('relative_humidity_850hPa');
        const avg700=_hmAvg('relative_humidity_700hPa');
        const avg500=_hmAvg('relative_humidity_500hPa');
        const hmAn=analyzeHumidityProfile(avg2m,avg850,avg700,avg500);
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_hmLabel()}</div>
            <div class="fc-stat-value" style="color:${hmAn.color};font-size:13px;margin-bottom:6px;">${hmAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${hmAn.desc}</div>
            <div style="margin-top:6px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Связанные параметры:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo('cloud_profile')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">☁️ Облачность</button>
                    <button onclick="window._fcGoTo('vert_vel')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                    <button onclick="window._fcGoTo('temp_profile')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">🌡️ Профиль Т</button>
                </div>
            </div>
        </div>
        ${activeLevels.map(lv=>{ const v=h?h[lv.key]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?Math.round(v)+'%':'—'}</div><div class="fc-stat-time">сейчас</div></div>`; }).join("")}`; }
}

// ─── analyzeHumidityProfile ──────────────────────────────────────────────────
function analyzeHumidityProfile(rh2m, rh850, rh700, rh500){
    const satLow  = rh850!=null&&rh850>85;
    const satMid  = rh700!=null&&rh700>80;
    const satHigh = rh500!=null&&rh500>70;
    const dryLow  = rh850!=null&&rh850<40;
    const dryMid  = rh700!=null&&rh700<35;
    const wet2m   = rh2m!=null&&rh2m>88;
    const dry2m   = rh2m!=null&&rh2m<45;
    if(satLow&&satMid&&satHigh)
        return {title:"Насыщение по всей толще",color:"#74b9ff",
            desc:"Относительная влажность выше порога насыщения на всех уровнях — атмосфера полностью увлажнена. Обложные осадки, туман, стойкая низкая облачность. Вероятны длительные дожди при наличии синоптического подъёма."};
    if(satLow&&satMid&&!satHigh)
        return {title:"Насыщение до средней тропосферы",color:"#55efc4",
            desc:"Высокая влажность в нижней и средней тропосфере. Условия для образования мощных кучево-дождевых облаков при наличии конвективного триггера. Грозы возможны — оцените нестабильность профиля температуры."};
    if(satLow&&!satMid)
        return {title:"Насыщение в нижней тропосфере",color:"#00cec9",
            desc:"Влажность высокая вблизи поверхности, но сухой слой выше 850 гПа ограничивает вертикальное развитие облаков. Вероятны низкая слоистая облачность, туман, морось. Грозы маловероятны."};
    if(satMid&&satHigh&&!satLow)
        return {title:"Сухой нижний слой / влажная средняя тропосфера",color:"#a29bfe",
            desc:"Сухой воздух у поверхности при высокой влажности выше — возможна поднятая слоистая облачность высокого яруса. Характерно для предфронтального потепления или адвекции влаги на высоте."};
    if(dryLow&&dryMid)
        return {title:"Сухая воздушная масса",color:"#fdcb6e",
            desc:"Низкая влажность в нижней и средней тропосфере — ксерофильная антициклональная масса. Ясно или малооблачно, осадки маловероятны. Испарение интенсивное, конвекция только при сильном прогреве."};
    if(wet2m&&dryLow)
        return {title:"Поверхностный влажный слой",color:"#b2bec3",
            desc:"Влажность у земли высокая, но выше — воздух сухой. Типично для ночного радиационного охлаждения — возможен туман, роса. Слоистые облака до 1–1.5 км, выше прояснение."};
    if(dry2m)
        return {title:"Сухой приземный слой",color:"#ff8f00",
            desc:"Очень низкая относительная влажность у поверхности — жаркая и сухая масса. Риск пожарной обстановки. Конвективная активность возможна при развитии мощных термиков, но осадки слабые."};
    if(satHigh&&!satMid)
        return {title:"Тропосферная сухая прослойка",color:"#636e72",
            desc:"Высокая влажность только на уровне 500 гПа — изолированный влажный слой в средней тропосфере. Возможны перистые облака, слабая конвекция не достигает поверхности."};
    return {title:"Умеренная влажность",color:"#aaa",
        desc:"Относительная влажность в пределах нормы на большинстве уровней. Облачность частичная, осадки возможны при наличии синоптического подъёма. Конвективный потенциал умеренный."};
}

// ─── renderCloudProfile ───────────────────────────────────────────────────
function renderCloudProfile(hours, times){
    const wrap=document.getElementById("fcChartWrap"), statsBox=document.getElementById("fcStats");
    if(!wrap) return;
    // Уровни облачности: surface-based + по уровням давления
    const LAYERS=[
        {key:"cloud_cover_low",  label:"Низкий",  sublabel:"<2км",   color:"#74b9ff"},
        {key:"cloud_cover_mid",  label:"Средний", sublabel:"2-6км",  color:"#a29bfe"},
        {key:"cloud_cover_high", label:"Высокий", sublabel:">6км",   color:"#fdcb6e"},
        {key:"cloud_cover",      label:"Общая",   sublabel:"total",  color:"#dfe6e9"},
    ];
    const W=320,H=190,pad={t:24,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=LAYERS.length, trackH=iH/nL;
    const tMin=new Date(times[0]).getTime(),tMax_=new Date(times[times.length-1]).getTime();
    const px=t=>pad.l+(new Date(t).getTime()-tMin)/(tMax_-tMin)*iW;
    let xGrid="",xLabels="";
    times.forEach((t,i)=>{ const d=new Date(t),hr=d.getHours(),x=px(t);
        if(hr===0){ xGrid+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t+iH}" stroke="#333" stroke-dasharray="2 3"/>`;
            const nxt=times.slice(i+1).find(t2=>new Date(t2).getHours()===0); const xE=nxt?px(nxt):pad.l+iW;
            xLabels+=`<text x="${((x+xE)/2).toFixed(1)}" y="${pad.t-8}" text-anchor="middle" font-size="8.5" fill="#777" font-weight="700">${FC_DAY_NAMES[d.getDay()]} ${d.getDate()}</text>`; }
        if(hr%6===0) xLabels+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#555">${hr}h</text>`; });
    const nowTs=Date.now(); let nowLine="";
    if(nowTs>=tMin&&nowTs<=tMax_){ const xN=pad.l+(nowTs-tMin)/(tMax_-tMin)*iW; nowLine=`<line x1="${xN}" y1="${pad.t}" x2="${xN}" y2="${pad.t+iH}" stroke="rgba(255,255,255,0.25)" stroke-width="1.5" stroke-dasharray="3 3"/>`; }
    let hLines="",fills="",paths="",yLabels="",clipDefs="";
    const allPts={};
    LAYERS.forEach((lv,li)=>{
        const y0=pad.t+li*trackH, yMid=y0+trackH/2, y1=pad.t+(li+1)*trackH;
        clipDefs+=`<clipPath id="ccClip${li}"><rect x="${pad.l}" y="${y0}" width="${iW}" height="${trackH}"/></clipPath>`;
        hLines+=`<rect x="${pad.l}" y="${y0+1}" width="${iW}" height="${trackH-2}" fill="${li%2===0?'rgba(255,255,255,0.01)':'rgba(0,0,0,0)'}"/>` +
            `<line x1="${pad.l}" y1="${y1}" x2="${pad.l+iW}" y2="${y1}" stroke="#1e1e1e" stroke-width="0.8"/>`;
        const data=hours.map(h=>h[lv.key]??null);
        const valid=data.filter(v=>v!=null); if(!valid.length){
            yLabels+=`<text x="${pad.l-4}" y="${yMid+3}" text-anchor="end" font-size="8" fill="#444">${lv.label}</text>`; return; }
        const innerH=trackH-4;
        // y: 0% = bottom, 100% = top of track
        const pyL=v=>y0+2+(1-v/100)*innerH;
        const yBase=pyL(0);
        const pts=times.map((t,i)=>data[i]!=null?{x:px(t),y:pyL(Math.min(100,Math.max(0,data[i])))}:null);
        allPts[lv.key]=pts;
        let seg=[],d=""; pts.forEach(p=>{ if(p) seg.push(p); else if(seg.length){d+=smooth(seg);seg=[];} });
        if(seg.length) d+=smooth(seg);
        const validPts=pts.filter(Boolean);
        if(d&&validPts.length>1){
            const fp=d+` L${validPts[validPts.length-1].x},${yBase} L${validPts[0].x},${yBase} Z`;
            fills+=`<path d="${fp}" fill="${lv.color}" fill-opacity="0.18" clip-path="url(#ccClip${li})"/>`;
        }
        if(d) paths+=`<path d="${d}" fill="none" stroke="${lv.color}" stroke-width="1.8"/>`;
        yLabels+=`<text x="${pad.l-4}" y="${yMid-2}" text-anchor="end" font-size="8.5" fill="${lv.color}">${lv.label}</text>` +
            `<text x="${pad.l-4}" y="${yMid+8}" text-anchor="end" font-size="7.5" fill="#444">${lv.sublabel}</text>`;
    });
    const legendHtml=`<div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;padding:5px 8px 4px;border-top:1px solid #1e1e1e;font-size:10px;">${LAYERS.map(lv=>`<span style="display:inline-flex;align-items:center;gap:4px;color:${lv.color};"><span style="display:inline-block;width:12px;height:2px;background:${lv.color};border-radius:1px;"></span>${lv.label}</span>`).join("")}</div>`;
    wrap.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="display:block;"><defs>${clipDefs}</defs>${hLines}${xGrid}${nowLine}${fills}${paths}${yLabels}${xLabels}</svg>${legendHtml}`;
    const svgEl=wrap.querySelector("svg");
    if(svgEl){ const allSeries=LAYERS.map(lv=>({label:lv.label,color:lv.color,unit:"%",data:hours.map(h=>h[lv.key]??null),pts:allPts[lv.key]||times.map(()=>null)}));
        addMultiLineCrosshair(svgEl,allSeries,pad,iW,iH,W,times); }
    if(statsBox){ statsBox.style.display="grid";
        function _ccAvg(key){ const vs=hours.map(h=>h[key]??null).filter(v=>v!=null); return vs.length?Math.round(vs.reduce((a,b)=>a+b,0)/vs.length):null; }
        function _ccLabel(){ const d0=new Date(times[0]),now=new Date(); if(d0.toDateString()===now.toDateString()) return 'Сегодня'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()) return 'Завтра'; return d0.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit'}); }
        const avgLow=_ccAvg('cloud_cover_low'),avgMid=_ccAvg('cloud_cover_mid');
        const avgHigh=_ccAvg('cloud_cover_high'),avgTotal=_ccAvg('cloud_cover');
        const ccAn=analyzeCloudProfile(avgLow,avgMid,avgHigh,avgTotal);
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${_ccLabel()}</div>
            <div class="fc-stat-value" style="color:${ccAn.color};font-size:13px;margin-bottom:6px;">${ccAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${ccAn.desc}</div>
            <div style="margin-top:6px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Связанные параметры:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo('humidity_profile')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💧 Влажность</button>
                    <button onclick="window._fcGoTo('vert_vel')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                    <button onclick="window._fcGoTo('geo_height')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">📈 Геопотенциал</button>
                </div>
            </div>
        </div>
        ${LAYERS.map(lv=>{ const v=h?h[lv.key]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?Math.round(v)+'%':'—'}</div><div class="fc-stat-time">${lv.sublabel}</div></div>`; }).join("")}`; }
}

// ─── analyzeCloudProfile ─────────────────────────────────────────────────────
function analyzeCloudProfile(ccLow, ccMid, ccHigh, ccTotal){
    const overcLow  = ccLow!=null&&ccLow>70;
    const overcMid  = ccMid!=null&&ccMid>60;
    const overcHigh = ccHigh!=null&&ccHigh>60;
    const clearLow  = ccLow!=null&&ccLow<20;
    const clearMid  = ccMid!=null&&ccMid<20;
    const clearHigh = ccHigh!=null&&ccHigh<20;
    const overcTotal= ccTotal!=null&&ccTotal>75;
    const clearTotal= ccTotal!=null&&ccTotal<25;
    if(overcLow&&overcMid&&overcTotal)
        return {title:"Мощная слоисто-дождевая система",color:"#74b9ff",
            desc:"Густая облачность нижнего и среднего ярусов — классический nimbostratus. Обложные осадки продолжительные. Видимость ограничена, вероятен туман под нижней кромкой. Характерно для фронтальных разделов."};
    if(overcLow&&!overcMid&&!overcHigh)
        return {title:"Низкая слоистая облачность",color:"#636e72",
            desc:"Облачность сосредоточена в нижнем ярусе — страты или стратокумулюсы. Моросящий дождь, туман, сниженная видимость. Верхние ярусы свободны — конвекция маловероятна без дополнительного подъёма."};
    if(overcHigh&&!overcLow&&!overcMid)
        return {title:"Высококучевая / перистая облачность",color:"#fdcb6e",
            desc:"Облачность только верхнего яруса — перисто-слоистые или высококучевые. Осадки до земли не достигают. Признак удалённого тёплого фронта или тропосферной влаги на высоте. Прямая инсоляция ослаблена."};
    if(overcMid&&overcHigh&&!overcLow)
        return {title:"Средняя и верхняя облачность",color:"#a29bfe",
            desc:"Плотные слои среднего и верхнего ярусов без выраженной нижней облачности. Возможны слабые обложные осадки, не достигающие поверхности. Характерно для удалённого фронта или антициклонального растекания."};
    if(clearTotal)
        return {title:"Ясно",color:"#ff8f00",
            desc:"Облачность минимальная на всех уровнях. Интенсивная солнечная радиация, высокое ультрафиолетовое излучение. Ночью — значительное радиационное охлаждение поверхности. Возможны термические грозы при прогреве."};
    if(clearLow&&clearMid&&overcHigh)
        return {title:"Ясно под перистыми",color:"#dfe6e9",
            desc:"Нижние ярусы чистые, верхний — перистая облачность. Видимость хорошая. Перистые свидетельствуют о высотном влажном потоке или приближении тёплого фронта за горизонтом прогноза."};
    if(overcLow&&overcMid&&overcHigh)
        return {title:"Полное затянутое небо",color:"#b2bec3",
            desc:"Сплошная облачность всех ярусов — глубокая влажная воздушная масса или активная фронтальная зона. Продолжительные осадки, минимальная инсоляция. Длительный период пасмурной погоды."};
    return {title:"Переменная облачность",color:"#aaa",
        desc:"Смешанная облачность без явного доминирования одного яруса. Переменные условия — чередование облачных и ясных промежутков. Конвективная активность умеренная, возможны кратковременные осадки."};
}

// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(key){
    if(typeof fcSwitchParam==='function') fcSwitchParam(key);
};'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")