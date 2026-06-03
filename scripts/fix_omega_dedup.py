# FIX: убрать дублированный код v1+v2 из renderVerticalVelocity

FILE = 'js/fc-charts-atmo.js'

with open(FILE, 'r', encoding='utf-8') as f:
    src = f.read()

# Вырезаем всё от первого getDayBuckets (v1 мусор) до конца блока
START = '    function getDayBuckets(){\n        const buckets=[],seen=new Map();\n        times.forEach((t,i)=>{\n            const d=new Date(t);\n            const key=d.getFullYear()*10000+d.getMonth()*100+d.getDate();\n            if(!seen.has(key)){\n                const now=new Date();\n                const isTd=d.toDateString()===now.toDateString();\n                const tm=new Date(now); tm.setDate(now.getDate()+1);\n                const isTm=d.toDateString()===tm.toDateString();\n                const lbl=isTd?\'Сегодня\':isTm?\'Завтра\':(FC_DAY_NAMES[d.getDay()]+\' \'+d.getDate());\n                seen.set(key,buckets.length);\n                buckets.push({label:lbl,indices:[]});\n            }\n            buckets[seen.get(key)].indices.push(i);\n        });\n        return buckets;\n    }'
END   = '    // начальный рендер — анализ периода\n    renderPeriodStats();\n}'

assert START in src, "START not found"
assert END   in src, "END not found"

i1 = src.index(START)
i2 = src.index(END, i1) + len(END)

# Чистый итоговый блок — только v2
NEW = '''    // ── period analysis ─────────────────────────────────────────────────────
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
        if(!times.length) return \'\';
        const d0=new Date(times[0]),d1=new Date(times[times.length-1]);
        const fmt=d=>d.toLocaleString(\'ru-RU\',{day:\'2-digit\',month:\'2-digit\'});
        const now=new Date();
        if(d0.toDateString()===now.toDateString()&&d1.toDateString()===now.toDateString()) return \'Сегодня\';
        const tm=new Date(now); tm.setDate(now.getDate()+1);
        if(d0.toDateString()===tm.toDateString()&&d1.toDateString()===tm.toDateString()) return \'Завтра\';
        if(d0.toDateString()===d1.toDateString()) return fmt(d0);
        return fmt(d0)+\' – \'+fmt(d1);
    }

    function renderPeriodStats(){
        if(!statsBox) return;
        const allIdx=times.map((_,i)=>i);
        const res=analyzeOmegaPeriod(allIdx);
        if(!res){statsBox.innerHTML=`<div class="fc-stat-card" style="grid-column:1/-1;color:#555;">нет данных</div>`;return;}
        const {dominant,avg850,avg700,avg500,hoursUp,hoursDn,hoursNeut,total}=res;
        const upPct=Math.round(hoursUp/total*100),dnPct=Math.round(hoursDn/total*100),neuPct=100-Math.round(hoursUp/total*100)-Math.round(hoursDn/total*100);
        const RECS=[
            [\'конвекц\',[\'⬆️ Геопотенциал Z500\',\'🌡️ Профиль темп.\']],
            [\'фронт\',  [\'⬆️ Геопотенциал Z500\',\'🌡️ Профиль темп.\']],
            [\'подъём\', [\'⬆️ Геопотенциал Z500\',\'🌡️ Профиль темп.\']],
            [\'антицикл\',[\'⬆️ Геопотенциал Z500\']],
            [\'субсиденс\',[\'⬆️ Геопотенциал Z500\']],
            [\'Смешанный\',[\'⬆️ Геопотенциал Z500\',\'💨 Профиль ветра\']],
            [\'Волновое\',[\'⬆️ Геопотенциал Z500\',\'🌡️ Профиль темп.\']],
            [\'нестаб\', [\'🌡️ Профиль темп.\',\'💨 Профиль ветра\']],
        ];
        const recs=[...new Set(RECS.filter(([k])=>dominant.title.includes(k)).flatMap(([,v])=>v))];
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
            <div class="fc-stat-label" style="font-size:11px;color:#666;">${timeStr||\'сейчас\'}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">850 гПа</div>
            <div class="fc-stat-value" style="color:${o8.c};font-size:12px;">${w850!=null?w850.toFixed(3)+\' Па/с\':\'—\'}</div>
            <div class="fc-stat-time" style="color:${o8.c};">${o8.t}</div>
            <div class="fc-stat-time">${o8.s}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">700 гПа</div>
            <div class="fc-stat-value" style="color:${o7.c};font-size:12px;">${w700!=null?w700.toFixed(3)+\' Па/с\':\'—\'}</div>
            <div class="fc-stat-time" style="color:${o7.c};">${o7.t}</div>
            <div class="fc-stat-time">${o7.s}</div>
        </div>
        <div class="fc-stat-card">
            <div class="fc-stat-label">500 гПа</div>
            <div class="fc-stat-value" style="color:${o5.c};font-size:12px;">${w500!=null?w500.toFixed(3)+\' Па/с\':\'—\'}</div>
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
}'''

result = src[:i1] + NEW + src[i2:]

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(result)

print(f"OK: вырезано {i2-i1} chars, вставлено {len(NEW)} chars")