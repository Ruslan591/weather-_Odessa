# PATCH 2: connect_analysis.py

FILE = 'js/fc-charts-atmo.js'
with open(FILE, 'r', encoding='utf-8') as f:
    src = f.read()

# ═══════════════════════════════════════════
# 1. renderTempProfile statsBox
# ═══════════════════════════════════════════
OLD_TEMP = '''    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        statsBox.innerHTML=LEVELS.map(lv=>{ const v=h?h[lv.key]:null; return `<div class="fc-stat-card"><div class="fc-stat-label">${lv.label}</div><div class="fc-stat-value" style="color:${lv.color};">${v!=null?v.toFixed(1)+'°':'—'}</div><div class="fc-stat-time">сейчас</div></div>`; }).join(""); }
}'''

NEW_TEMP = '''    if(statsBox){
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
}'''

assert OLD_TEMP in src, "OLD_TEMP not found"
src = src.replace(OLD_TEMP, NEW_TEMP, 1)

# ═══════════════════════════════════════════
# 2. renderFreezeLevel statsBox
# ═══════════════════════════════════════════
OLD_FREEZE = '''    if(statsBox){ statsBox.style.display="grid"; statsBox.innerHTML=`
        <div class="fc-stat-card"><div class="fc-stat-label">Минимум</div><div class="fc-stat-value" style="color:#74b9ff;">${(min/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMin)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Максимум</div><div class="fc-stat-value" style="color:#ff8f00;">${(max/1000).toFixed(2)} км</div><div class="fc-stat-time">${tFmt(iMax)}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Среднее</div><div class="fc-stat-value" style="color:#ccc;">${(avg/1000).toFixed(2)} км</div><div class="fc-stat-time">&nbsp;</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">Снег у земли</div><div class="fc-stat-value" style="color:#74b9ff;">${snowH} ч</div><div class="fc-stat-time">&lt;500м</div></div>`; }'''

NEW_FREEZE = '''    if(statsBox){ statsBox.style.display="grid";
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
        <div class="fc-stat-card"><div class="fc-stat-label">Снег у земли</div><div class="fc-stat-value" style="color:#74b9ff;">${snowH} ч</div><div class="fc-stat-time">&lt;500м</div></div>`; }'''

assert OLD_FREEZE in src, "OLD_FREEZE not found"
src = src.replace(OLD_FREEZE, NEW_FREEZE, 1)

# ═══════════════════════════════════════════
# 3. renderWindBarbs statsBox — добавить analysis card
# ═══════════════════════════════════════════
OLD_WB = '''    if(statsBox){ statsBox.style.display="grid";
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
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">850 → 500: ${v2.t}</div><div class="fc-stat-value" style="color:${v2.c};font-size:13px;">${v2.s}</div></div>`; }'''

NEW_WB = '''    if(statsBox){ statsBox.style.display="grid";
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
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">850 → 500: ${v2.t}</div><div class="fc-stat-value" style="color:${v2.c};font-size:13px;">${v2.s}</div></div>`; }'''

assert OLD_WB in src, "OLD_WB not found"
src = src.replace(OLD_WB, NEW_WB, 1)

# ═══════════════════════════════════════════
# 4. renderPolarVortex statsBox
# ═══════════════════════════════════════════
OLD_PV = '''    if(statsBox){ statsBox.style.display="grid";
        const now=Date.now(); let iNow=times.map(t=>new Date(t).getTime()).findIndex(t=>t>=now); if(iNow<0) iNow=0;
        const h=hours[iNow];
        const t10=h?.temperature_10hPa,t50=h?.temperature_50hPa;
        function pvLabel(t){ if(t==null) return {l:"—",c:"#555",s:""}; if(t>-40) return {l:"Разрушен",c:"#ff6b6b",s:"риск ВСП → холод через 2-4 нед."}; if(t>-55) return {l:"Ослаблен",c:"#fd79a8",s:"возможны вторжения холода"}; if(t>-70) return {l:"Умеренный",c:"#fdcb6e",s:"умеренная изоляция"}; return {l:"Сильный",c:"#74b9ff",s:"защита от арктических вторжений"}; }
        const pv=pvLabel(t10);
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;"><div class="fc-stat-label">Полярный вихрь (10 гПа)</div><div class="fc-stat-value" style="color:${pv.c};font-size:13px;">${pv.l}</div><div class="fc-stat-time">${pv.s}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 10 гПа</div><div class="fc-stat-value" style="color:#ff6b6b;">${t10!=null?t10.toFixed(1)+'°':'—'}</div></div>
        <div class="fc-stat-card"><div class="fc-stat-label">T 50 гПа</div><div class="fc-stat-value" style="color:#a29bfe;">${t50!=null?t50.toFixed(1)+'°':'—'}</div></div>`; }'''

NEW_PV = '''    if(statsBox){ statsBox.style.display="grid";
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
        <div class="fc-stat-card"><div class="fc-stat-label">T 50 гПа</div><div class="fc-stat-value" style="color:#a29bfe;">${t50!=null?t50.toFixed(1)+'°':'—'}</div></div>`; }'''

assert OLD_PV in src, "OLD_PV not found"
src = src.replace(OLD_PV, NEW_PV, 1)

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(src)
print("Patch 2 done — 4 renderers connected")