# enhance_omega_analysis.py
# Запускать из корня проекта: python3 scripts/enhance_omega_analysis.py

FILE = 'js/fc-charts-atmo.js'
with open(FILE, 'r', encoding='utf-8') as f:
    src = f.read()

# ═══════════════════════════════════════════════════════════
# 1. analyzeOmega — улучшить fallthrough "Смешанный режим"
# ═══════════════════════════════════════════════════════════
OLD1 = '''        return {title:"Смешанный режим",color:"#aaa",
            desc:"Разнонаправленные вертикальные движения на разных уровнях. Переходное состояние атмосферы — смена синоптического режима или прохождение фронта. Прогнозировать погоду только по омеге сложно: обратитесь к геопотенциалу и термодинамике."};'''

NEW1 = '''        const magMax=Math.max(Math.abs(w850||0),Math.abs(w700||0),Math.abs(w500||0));
        const nonZeroS=[s8,s7,s5].filter(s=>s!==0);
        const isMixed=nonZeroS.some(s=>s>0)&&nonZeroS.some(s=>s<0);
        if(magMax<0.025)
            return {title:"Нейтральный режим",color:"#636e72",
                desc:"Вертикальные движения практически отсутствуют. Атмосфера в квазистатическом состоянии — ни подъёма, ни субсиденса. Осадков и конвекции не ожидается."};
        if(isMixed&&magMax>0.07)
            return {title:"Фронтальная зона",color:"#e84393",
                desc:"Сильные разнонаправленные вертикальные движения — активная фронтальная зона. Вероятно прохождение атмосферного фронта: резкая смена погоды, облачность, осадки. Проверьте геопотенциал Z500 для определения направления движения фронта."};
        return {title:"Переходный режим",color:"#b2bec3",
            desc:"Умеренные разнонаправленные движения. Атмосфера перестраивается — возможен слабый фронт или смена синоптического режима. Для точного диагноза сравните с геопотенциалом Z500 и профилем ветра."};'''

assert OLD1 in src, "OLD1 not found"
src = src.replace(OLD1, NEW1, 1)

# ═══════════════════════════════════════════════════════════
# 2. renderPeriodStats — кнопки навигации + тренд периода
# ═══════════════════════════════════════════════════════════
OLD2 = '''        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
        statsBox.style.display=\'grid\';
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
                Ср.омега · 850:<span style="color:#ff8f00;">${avg850.toFixed(3)}</span>${avg700!=null?` · 700:<span style="color:#55efc4;">${avg700.toFixed(3)}</span>`:\'\'}${avg500!=null?` · 500:<span style="color:#74b9ff;">${avg500.toFixed(3)}</span>`:\'\'}
            </div>
            ${recs.length?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;font-size:10px;color:#777;">Для уточнения: <span style="color:#aaa;">${recs.join(\' · \')}</span></div>`:\'\'}
        </div>`; }'''

NEW2 = '''        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
        if(dominant.title.includes(\'Переход\')||dominant.title.includes(\'Смеш\')||dominant.title.includes(\'Фронт\')){
            if(!recs.includes(\'⬆️ Геопотенциал Z500\')) recs.push(\'⬆️ Геопотенциал Z500\');
            if(!recs.includes(\'💨 Профиль ветра\')) recs.push(\'💨 Профиль ветра\');
        }
        // Тренд: первая и вторая половина периода по 850 гПа
        const _half=Math.floor(allIdx.length/2);
        const _hAvg=(sl,key)=>{ const vs=sl.map(i=>hours[i]?.[key]??null).filter(v=>v!=null); return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null; };
        const _f1=_hAvg(allIdx.slice(0,_half),\'vertical_velocity_850hPa\'),_f2=_hAvg(allIdx.slice(_half),\'vertical_velocity_850hPa\');
        const trendNote=(_f1!=null&&_f2!=null&&Math.abs(_f2-_f1)>0.025)?(_f2<_f1?\'↗ к концу периода нарастает подъём\':\'↘ к концу периода усиливается субсиденс\'):\'\';
        // Nav кнопки
        const NAV={\'⬆️ Геопотенциал Z500\':\'Геопотенциал\',\'🌡️ Профиль темп.\':\'уровни\',\'💨 Профиль ветра\':\'ветра\'};
        const recBtns=recs.map(r=>`<button onclick="window._fcGoTo(\'${NAV[r]||r}\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">${r}</button>`).join(\'\');
        statsBox.style.display=\'grid\';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${periodLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${dominant.color};font-size:13px;margin-bottom:6px;">${dominant.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;">${dominant.desc}</div>
            ${trendNote?`<div style="font-size:10px;color:#a0a0a0;margin-top:4px;padding:3px 6px;background:rgba(255,255,255,0.03);border-radius:4px;">${trendNote}</div>`:\'\'}
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
                Ср.омега · 850:<span style="color:#ff8f00;">${avg850.toFixed(3)}</span>${avg700!=null?` · 700:<span style="color:#55efc4;">${avg700.toFixed(3)}</span>`:\'\'}${avg500!=null?` · 500:<span style="color:#74b9ff;">${avg500.toFixed(3)}</span>`:\'\'}
            </div>
            ${recBtns?`<div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;"><div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div><div style="display:flex;gap:5px;flex-wrap:wrap;">${recBtns}</div></div>`:\'\'}
        </div>`; }'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

# ═══════════════════════════════════════════════════════════
# 3. renderGeopotentialChart — period analysis по умолчанию
# ═══════════════════════════════════════════════════════════
OLD3 = '''    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        function synLabel(key,refLow,refHigh){ const v=h[key]; if(v==null) return {t:"—",c:"#555",s:""}; const mid=(refLow+refHigh)/2,pct=Math.round(((v-mid)/(refHigh-refLow))*200); if(v>refHigh) return {t:"Гребень +"+Math.abs(pct)+"%",c:"#ff8f00",s:"антициклон"}; if(v<refLow) return {t:"Ложбина −"+Math.abs(pct)+"%",c:"#74b9ff",s:"циклон"}; return {t:`Норма (${Math.round(v)} м)`,c:"#aaa",s:""}; }
        function detectRidgeTrough(key){ const vals=hours.map(h=>h[key]); const events=[]; for(let i=2;i<vals.length-2;i++){ const v=vals[i],p1=vals[i-1],p2=vals[i-2],n1=vals[i+1],n2=vals[i+2]; if(v==null||p1==null||n1==null) continue; if(v<=p1&&v<=p2&&v<=n1&&v<=n2) events.push({type:\'trough\',time:times[i],val:Math.round(v)}); if(v>=p1&&v>=p2&&v>=n1&&v>=n2) events.push({type:\'ridge\',time:times[i],val:Math.round(v)}); } return events; }
        const events500=detectRidgeTrough("geopotential_height_500hPa");
        const nextEvent=events500.find(e=>new Date(e.time).getTime()>=Date.now());
        const evStr=nextEvent?`${nextEvent.type===\'trough\'?\'⬇️ Ложбина\':\'⬆️ Гребень\'} ${new Date(nextEvent.time).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})} Z=${nextEvent.val}м`:"нет чётких экстремумов";
        const iNow6=Math.min(iNow+6,hours.length-1);
        const z500now=hours[iNow]?.geopotential_height_500hPa, z500_6h=hours[iNow6]?.geopotential_height_500hPa;
        const tendency=z500now!=null&&z500_6h!=null?z500_6h-z500now:null;
        const tendStr=tendency!=null?(tendency>10?`▲ +${Math.round(tendency)}м/6ч → гребень`:tendency<-10?`▼ ${Math.round(tendency)}м/6ч → ложбина`:"→ стабильно"):"—";
        const s5=synLabel("geopotential_height_500hPa",5400,5700);
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Ближайший экстремум Z500</div><div class="fc-stat-value" style="color:#74b9ff;font-size:12px;">${evStr}</div></div>
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Тенденция Z500</div><div class="fc-stat-value" style="color:#fdcb6e;font-size:13px;">${tendStr}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">500 гПа</div><div class="fc-stat-value" style="color:${s5.c};font-size:13px;">${s5.t}</div><div class="fc-stat-time">${s5.s}</div></div>
        ${LEVELS.map(lv=>{ const v=h[lv.key]; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label} гПа</div><div class="fc-stat-value" style="color:${lv.color};font-size:13px;">${v!=null?Math.round(v)+\' м\':\'—\'}</div></div>`; }).join("")}`; }
}'''

NEW3 = '''    // ── helpers ─────────────────────────────────────────────────────────────
    function synLabel(key,refLow,refHigh,h){ const v=h[key]; if(v==null) return {t:"—",c:"#555",s:""}; const mid=(refLow+refHigh)/2,pct=Math.round(((v-mid)/(refHigh-refLow))*200); if(v>refHigh) return {t:"Гребень +"+Math.abs(pct)+"%",c:"#ff8f00",s:"антициклон"}; if(v<refLow) return {t:"Ложбина −"+Math.abs(pct)+"%",c:"#74b9ff",s:"циклон"}; return {t:`Норма (${Math.round(v)} м)`,c:"#aaa",s:""}; }
    function detectRidgeTrough(key){ const vals=hours.map(h=>h[key]); const events=[]; for(let i=2;i<vals.length-2;i++){ const v=vals[i],p1=vals[i-1],p2=vals[i-2],n1=vals[i+1],n2=vals[i+2]; if(v==null||p1==null||n1==null) continue; if(v<=p1&&v<=p2&&v<=n1&&v<=n2) events.push({type:\'trough\',time:times[i],val:Math.round(v)}); if(v>=p1&&v>=p2&&v>=n1&&v>=n2) events.push({type:\'ridge\',time:times[i],val:Math.round(v)}); } return events; }
    function geoPlLabel(){ if(!times.length) return \'\'; const d0=new Date(times[0]),d1=new Date(times[times.length-1]); const fmt=d=>d.toLocaleString(\'ru-RU\',{day:\'2-digit\',month:\'2-digit\'}); const now=new Date(); if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return \'Сегодня\'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return \'Завтра\'; if(d0.toDateString()===d1.toDateString()) return fmt(d0); return fmt(d0)+\' – \'+fmt(d1); }

    function renderGeoPeriodStats(){
        if(!statsBox) return;
        const avg=arr=>arr.reduce((a,b)=>a+b,0)/arr.length;
        const z5all=hours.map(h=>h.geopotential_height_500hPa??null).filter(v=>v!=null);
        const z8all=hours.map(h=>h.geopotential_height_850hPa??null).filter(v=>v!=null);
        if(!z5all.length) return;
        const avgZ5=avg(z5all); const norm5=5550;
        const anom=avgZ5-norm5;
        const anomLbl=anom>80?\'▲ Гребень\':anom<-80?\'▼ Ложбина\':\'→ Норма Z500\';
        const anomCol=anom>80?\'#ff8f00\':anom<-80?\'#74b9ff\':\'#aaa\';
        // Тренд: первая четверть vs последняя
        const q=Math.max(1,Math.floor(z5all.length/4));
        const trend=avg(z5all.slice(-q))-avg(z5all.slice(0,q));
        const trendLbl=trend>40?`▲ +${Math.round(trend)}м → рост гребня`:trend<-40?`▼ ${Math.round(trend)}м → углубление ложбины`:\'→ Z500 стабильный\';
        const trendCol=trend>40?\'#ff8f00\':trend<-40?\'#74b9ff\':\'#aaa\';
        // Мощность (thickness 500-850)
        const thick=z8all.length===z5all.length&&z8all.length>0?avg(z5all.map((v,i)=>v-(z8all[i]||0))):null;
        const thickLbl=thick?(thick>4050?\'→ тёплое ядро\':thick<3850?\'→ холодное ядро\':\'→ норма\'):\'\';
        // Экстремумы
        const ev5=detectRidgeTrough(\'geopotential_height_500hPa\');
        const ridges=ev5.filter(e=>e.type===\'ridge\').length, troughs=ev5.filter(e=>e.type===\'trough\').length;
        const nextEv=ev5.find(e=>new Date(e.time).getTime()>=Date.now());
        const nextEvStr=nextEv?`Ближайший: ${nextEv.type===\'trough\'?\'⬇️ Ложбина\':\'⬆️ Гребень\'} ${new Date(nextEv.time).toLocaleString(\'ru-RU\',{day:\'2-digit\',month:\'2-digit\',hour:\'2-digit\',minute:\'2-digit\'})} Z=${nextEv.val}м`:\'чётких экстремумов нет\';
        statsBox.style.display=\'grid\';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${geoPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${anomCol};font-size:13px;margin-bottom:4px;">${anomLbl}: ${Math.round(avgZ5)} м</div>
            <div style="font-size:10px;color:${trendCol};margin-bottom:4px;">${trendLbl}</div>
            <div style="font-size:10px;color:#666;margin-bottom:4px;">${thick!=null?`Мощность слоя: ${Math.round(thick)} м ${thickLbl} · `:\'\'} Гребней: ${ridges}, Ложбин: ${troughs}</div>
            <div style="font-size:10px;color:#777;">${nextEvStr}</div>
            <div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo(\'Омега\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                    <button onclick="window._fcGoTo(\'ветра\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">🌀 Профиль ветра</button>
                </div>
            </div>
        </div>`; }

    function renderGeoHourStats(iNow){
        if(!statsBox) return;
        const h=hours[iNow];
        const s5=synLabel(\'geopotential_height_500hPa\',5400,5700,h);
        const events500=detectRidgeTrough(\'geopotential_height_500hPa\');
        const nextEvent=events500.find(e=>new Date(e.time).getTime()>=Date.now());
        const evStr=nextEvent?`${nextEvent.type===\'trough\'?\'⬇️ Ложбина\':\'⬆️ Гребень\'} ${new Date(nextEvent.time).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})} Z=${nextEvent.val}м`:"нет чётких экстремумов";
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
        ${LEVELS.map(lv=>{ const v=h[lv.key]; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label} гПа</div><div class="fc-stat-value" style="color:${lv.color};font-size:13px;">${v!=null?Math.round(v)+\' м\':\'—\'}</div></div>`; }).join("")}`; }

    if(statsBox){
        renderGeoPeriodStats();
        const svgGeo=wrap.querySelector("svg");
        if(svgGeo){ svgGeo.addEventListener("touchmove",e=>{e.preventDefault(); const rect=svgGeo.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgGeo.viewBox.baseVal.width-60; const mx=(e.touches[0].clientX-rect.left)*svgGeo.viewBox.baseVal.width/rect.width-50; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderGeoHourStats(b2); },{passive:false}); svgGeo.addEventListener("touchend",()=>renderGeoPeriodStats()); svgGeo.addEventListener("mousemove",e=>{ const rect=svgGeo.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgGeo.viewBox.baseVal.width-60; const mx=(e.clientX-rect.left)*svgGeo.viewBox.baseVal.width/rect.width-50; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderGeoHourStats(b2); }); svgGeo.addEventListener("mouseleave",()=>renderGeoPeriodStats()); }
    }
}'''

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

# ═══════════════════════════════════════════════════════════
# 4. renderWindProfile — period analysis по умолчанию
# ═══════════════════════════════════════════════════════════
OLD4 = '''    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.spd]:null,dir=h?h[lv.dir]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+\' м/с\':\'—\'}</div><div class="fc-stat-time">${dir!=null?windDir(dir)+\' \'+dir.toFixed(0)+\'°\':\'&nbsp;\'}</div></div>`; }).join(""); }
}'''

NEW4 = '''    function windPlLabel(){ if(!times.length) return \'\'; const d0=new Date(times[0]),d1=new Date(times[times.length-1]); const fmt=d=>d.toLocaleString(\'ru-RU\',{day:\'2-digit\',month:\'2-digit\'}); const now=new Date(); if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return \'Сегодня\'; const tm=new Date(now); tm.setDate(now.getDate()+1); if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return \'Завтра\'; return fmt(d0); }

    function renderWindPeriodStats(){
        if(!statsBox) return;
        const avg=arr=>arr.filter(v=>v!=null).reduce((a,b)=>a+b,0)/(arr.filter(v=>v!=null).length||1);
        // Средние скорости
        const avgs=LEVELS.map(lv=>({ label:lv.label, color:lv.color, spd:avg(hours.map(h=>h[lv.spd]??null)), maxSpd:Math.max(...hours.map(h=>h[lv.spd]??0)) }));
        // Сдвиг 850→500 (прокси нестабильности)
        const spd850=avg(hours.map(h=>h.windspeed_850hPa??null)), spd500=avg(hours.map(h=>h.windspeed_500hPa??null));
        const shear=spd500-spd850;
        const shearLbl=shear>8?\'🌀 Сильный вертикальный сдвиг → нестабильность\':shear>4?\'↑ Умеренный сдвиг\':\'→ Слабый сдвиг, однородный поток\';
        const shearCol=shear>8?\'#ff9f5c\':shear>4?\'#fdcb6e\':\'#aaa\';
        // Адвекция: вирация/ротация 850→500
        function circAvg(dirs){ const n=dirs.filter(v=>v!=null).length; if(!n) return null; const sx=dirs.filter(v=>v!=null).reduce((s,d)=>s+Math.sin(d*Math.PI/180),0)/n, sy=dirs.filter(v=>v!=null).reduce((s,d)=>s+Math.cos(d*Math.PI/180),0)/n; return (Math.atan2(sx,sy)*180/Math.PI+360)%360; }
        const dir850=circAvg(hours.map(h=>h.winddirection_850hPa??null)), dir500=circAvg(hours.map(h=>h.winddirection_500hPa??null));
        const veer=dir850!=null&&dir500!=null?((dir500-dir850+360)%360):null;
        const veerN=veer!=null?(veer>180?veer-360:veer):null;
        const veerLbl=veerN==null?\'—\':veerN>20?`🌡️ Вирация +${Math.round(veerN)}° → тёплая адвекция`:veerN<-20?`❄️ Ротация ${Math.round(veerN)}° → холодная адвекция`:\'→ Нейтральная адвекция\';
        statsBox.style.display=\'grid\';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${windPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${shearCol};font-size:12px;margin-bottom:4px;">${shearLbl}</div>
            <div style="font-size:10px;color:#888;margin-bottom:6px;">${veerLbl}</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;">
                ${avgs.map(lv=>`<span style="font-size:10px;color:${lv.color};">${lv.label}: <b>${lv.spd.toFixed(1)}</b><span style="color:#444;"> м/с</span></span>`).join(\' · \')}
            </div>
            <div style="margin-top:6px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo(\'Геопотенциал\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">⬆️ Геопотенциал Z500</button>
                    <button onclick="window._fcGoTo(\'Омега\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                </div>
            </div>
        </div>`; }

    function renderWindHourStats(iNow){
        if(!statsBox) return;
        const h=hours[iNow];
        statsBox.style.display="grid";
        statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;padding:4px 8px;"><div class="fc-stat-label" style="font-size:11px;color:#666;">${new Date(times[iNow]).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}</div></div>`+LEVELS.map(lv=>{ const v=h?h[lv.spd]:null,dir=h?h[lv.dir]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+\' м/с\':\'—\'}</div><div class="fc-stat-time">${dir!=null?windDir(dir)+\' \'+dir.toFixed(0)+\'°\':\'&nbsp;\'}</div></div>`; }).join("");
    }

    if(statsBox){
        renderWindPeriodStats();
        const svgWind=wrap.querySelector("svg");
        if(svgWind){ svgWind.addEventListener("touchmove",e=>{e.preventDefault(); const rect=svgWind.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgWind.viewBox.baseVal.width-48; const mx=(e.touches[0].clientX-rect.left)*svgWind.viewBox.baseVal.width/rect.width-38; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderWindHourStats(b2); },{passive:false}); svgWind.addEventListener("touchend",()=>renderWindPeriodStats()); svgWind.addEventListener("mousemove",e=>{ const rect=svgWind.getBoundingClientRect(),tMin2=new Date(times[0]).getTime(),tMax2=new Date(times[times.length-1]).getTime(),iW2=svgWind.viewBox.baseVal.width-48; const mx=(e.clientX-rect.left)*svgWind.viewBox.baseVal.width/rect.width-38; let b2=0,bd=Infinity; times.forEach((t,i)=>{ const d=Math.abs((new Date(t).getTime()-tMin2)/(tMax2-tMin2)*iW2-mx); if(d<bd){bd=d;b2=i;} }); renderWindHourStats(b2); }); svgWind.addEventListener("mouseleave",()=>renderWindPeriodStats()); }
    }
}'''

assert OLD4 in src, "OLD4 not found"
src = src.replace(OLD4, NEW4, 1)

# ═══════════════════════════════════════════════════════════
# 5. Глобальная функция навигации — в конец файла
# ═══════════════════════════════════════════════════════════
src += '''
// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(hint){
    const row=document.getElementById(\'fcParamRow\');
    if(!row) return;
    const clean=s=>s.toLowerCase().replace(/[^а-яёa-z0-9]/gi,\'\');
    const h=clean(hint);
    const btns=row.querySelectorAll(\'button\');
    for(const b of btns){ if(clean(b.textContent).includes(h)){b.click();return;} }
};
'''

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(src)
print("Done — 5 patches applied")