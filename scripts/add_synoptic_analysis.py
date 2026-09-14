# add_synoptic_analysis.py

FILE = 'js/fc-charts-atmo.js'
with open(FILE, 'r', encoding='utf-8') as f:
    src = f.read()

# ═══════════════════════════════════════════════════════════
# 1. Добавить analyzeGeopotential + analyzeWindProfile
#    перед // ─── renderWindProfile
# ═══════════════════════════════════════════════════════════
ANCHOR1 = '// ─── renderWindProfile ───────────────────────────────────────────────────\nfunction renderWindProfile(hours, times){'

NEW_FUNCS = '''// ─── analyzeGeopotential ─────────────────────────────────────────────────────
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
function renderWindProfile(hours, times){'''

assert ANCHOR1 in src, "ANCHOR1 not found"
src = src.replace(ANCHOR1, NEW_FUNCS, 1)

# ═══════════════════════════════════════════════════════════
# 2. renderGeoPeriodStats — добавить текстовой анализ
# ═══════════════════════════════════════════════════════════
OLD_GEO = '''        statsBox.style.display=\'grid\';
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
        </div>`; }'''

NEW_GEO = '''        const geoAn=analyzeGeopotential(avgZ5,trend,thick,ridges,troughs);
        statsBox.style.display=\'grid\';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${geoPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${geoAn.color};font-size:13px;margin-bottom:6px;">${geoAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${geoAn.desc}</div>
            <div style="font-size:10px;color:${trendCol};margin-bottom:3px;">${trendLbl} · Z500: ${Math.round(avgZ5)} м</div>
            <div style="font-size:10px;color:#666;margin-bottom:3px;">${thick!=null?`Мощность: ${Math.round(thick)} м ${thickLbl} · `:\'\'} Гребней: ${ridges}, Ложбин: ${troughs}</div>
            <div style="font-size:10px;color:#555;">${nextEvStr}</div>
            <div style="margin-top:8px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo(\'vert_vel\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                    <button onclick="window._fcGoTo(\'wind_barbs\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">🌀 Разрез ветра</button>
                </div>
            </div>
        </div>`; }'''

assert OLD_GEO in src, "OLD_GEO not found"
src = src.replace(OLD_GEO, NEW_GEO, 1)

# ═══════════════════════════════════════════════════════════
# 3. renderWindPeriodStats — добавить текстовой анализ
# ═══════════════════════════════════════════════════════════
OLD_WIND = '''        statsBox.style.display=\'grid\';
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
        </div>`; }'''

NEW_WIND = '''        const windAn=analyzeWindProfile(shear,veerN,avg(hours.map(h=>h.windspeed_300hPa??null)),avg(hours.map(h=>h.windspeed_850hPa??null)));
        statsBox.style.display=\'grid\';
        statsBox.innerHTML=`
        <div class="fc-stat-card" style="grid-column:1/-1;">
            <div class="fc-stat-label" style="margin-bottom:4px;">${windPlLabel()} · <span style="color:#444;font-size:9px;">касание = почасовой</span></div>
            <div class="fc-stat-value" style="color:${windAn.color};font-size:13px;margin-bottom:6px;">${windAn.title}</div>
            <div style="font-size:10px;line-height:1.55;color:#888;margin-bottom:8px;">${windAn.desc}</div>
            <div style="font-size:10px;color:#777;margin-bottom:3px;">${veerLbl}</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px;">
                ${avgs.map(lv=>`<span style="font-size:10px;color:${lv.color};">${lv.label}: <b>${lv.spd.toFixed(1)}</b><span style="color:#444;"> м/с</span></span>`).join(\' · \')}
            </div>
            <div style="margin-top:6px;border-top:1px solid #252525;padding-top:6px;">
                <div style="font-size:10px;color:#555;margin-bottom:4px;">Для уточнения:</div>
                <div style="display:flex;gap:5px;flex-wrap:wrap;">
                    <button onclick="window._fcGoTo(\'geo_height\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">⬆️ Геопотенциал Z500</button>
                    <button onclick="window._fcGoTo(\'vert_vel\')" style="padding:3px 9px;border-radius:8px;border:1px solid #252525;background:#111;color:#888;font-size:10px;cursor:pointer;touch-action:manipulation;">💨 Омега ω</button>
                </div>
            </div>
        </div>`; }'''

assert OLD_WIND in src, "OLD_WIND not found"
src = src.replace(OLD_WIND, NEW_WIND, 1)

# ═══════════════════════════════════════════════════════════
# 4. Фикс NAV-маппинга в omega renderPeriodStats
# ═══════════════════════════════════════════════════════════
OLD_NAV = "        const NAV={'⬆️ Геопотенциал Z500':'Геопотенциал','🌡️ Профиль темп.':'уровни','💨 Профиль ветра':'ветра'};"
NEW_NAV = "        const NAV={'⬆️ Геопотенциал Z500':'geo_height','🌡️ Профиль темп.':'temp_profile','💨 Профиль ветра':'wind_barbs'};"
assert OLD_NAV in src, "OLD_NAV not found"
src = src.replace(OLD_NAV, NEW_NAV, 1)

# ═══════════════════════════════════════════════════════════
# 5. Фикс _fcGoTo → fcSwitchParam
# ═══════════════════════════════════════════════════════════
OLD_NAV2 = """// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(hint){
    const row=document.getElementById('fcParamRow');
    if(!row) return;
    const clean=s=>s.toLowerCase().replace(/[^а-яёa-z0-9]/gi,'');
    const h=clean(hint);
    const btns=row.querySelectorAll('button');
    for(const b of btns){ if(clean(b.textContent).includes(h)){b.click();return;} }
};"""
NEW_NAV2 = """// ─── Global navigation helper ──────────────────────────────────────────────
window._fcGoTo = function(key){
    if(typeof fcSwitchParam==='function') fcSwitchParam(key);
};"""
assert OLD_NAV2 in src, "OLD_NAV2 not found"
src = src.replace(OLD_NAV2, NEW_NAV2, 1)

with open(FILE, 'w', encoding='utf-8') as f:
    f.write(src)
print("Done — 5 patches applied")