let _fcDayOffset = null;

function buildFcDayRow(){
    const row = document.getElementById("fcDayRow");
    if(!row || !window._fcAllTimes) return;
    const DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    const now = new Date();
    const btns = [];
    for(let i = 0; i < 5; i++){
        const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
        const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
        const hasData = window._fcAllTimes.some(t => t.slice(0,10) === key);
        if(!hasData) break;
        const label = i===0 ? "Сегодня" : i===1 ? "Завтра"
            : `${String(d.getDate()).padStart(2,'0')}.${String(d.getMonth()+1).padStart(2,'0')}`;
        btns.push(`<button class="fc-day-btn${_fcDayOffset===i?' active':''}"
            onclick="fcSwitchDay(${i})">${label}</button>`);
    }
    row.innerHTML = btns.join("");
}

function fcSwitchDay(offset){
    _fcDayOffset = (_fcDayOffset === offset) ? null : offset;
    buildFcDayRow();
    applyFcDayFilter();
}

function applyFcDayFilter(){
    if(!window._fcAllHours || !window._fcAllTimes) return;
    let hrs, tms, idxs;
    if(_fcDayOffset === null){
        const nowTime = Date.now();
        const td = window._fcAllTimes.map(t => new Date(t));
        let si = td.findIndex(t => t.getTime() >= nowTime);
        if(si === -1) si = 0;
        si = Math.max(0, si - 1);
        const ei = Math.min(si + forecastHours, window._fcAllHours.length);
        idxs = Array.from({length: ei - si}, (_, k) => si + k);
        hrs = idxs.map(i => window._fcAllHours[i]);
        tms = idxs.map(i => window._fcAllTimes[i]);
    } else {
        const d = new Date();
        d.setDate(d.getDate() + _fcDayOffset);
        const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
        idxs = window._fcAllTimes.map((t,i) => t.slice(0,10)===key ? i : -1).filter(i => i>=0);
        if(!idxs.length) return;
        hrs = idxs.map(i => window._fcAllHours[i]);
        tms = idxs.map(i => window._fcAllTimes[i]);
    }
    _fcHours = hrs;
    _fcTimes = tms;
    renderForecastChart(_fcHours, _fcTimes);
    renderAlertsBlock(_fcHours);

    // Синхронизация таблицы арифметики ансамбля с выбранным днём
    if(window._dbgBase){
        const b = window._dbgBase;
        renderEnsembleDebug({
            models:    b.models,
            failed:    b.failed,
            weights:   b.weights,
            bias:      b.bias,
            rawHours:  idxs.map(i => b.rawAll[i]),
            corrHours: idxs.map(i => b.corrAll[i]),
            times:     idxs.map(i => b.timesAll[i]),
            snapTime:  b.snapTime
        });
    }
}

// =============================================
// TOOLTIP
// =============================================
