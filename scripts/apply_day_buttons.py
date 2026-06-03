import sys, os

HTML = "/storage/emulated/0/Documents/weather/forecast.html"
CSS  = "/storage/emulated/0/Documents/weather/forecast.css"

def replace_once(text, old, new, label):
    if old not in text:
        print(f"  [!] НЕ НАЙДЕНО: {label}")
        return text, False
    if text.count(old) > 1:
        print(f"  [!] НАЙДЕНО НЕСКОЛЬКО ({text.count(old)}): {label} — заменяю первое")
    result = text.replace(old, new, 1)
    print(f"  [ok] {label}")
    return result, True

# ── forecast.html ─────────────────────────────────────────────────────────────
with open(HTML, encoding="utf-8") as f:
    html = f.read()

ok_all = True

# 1. Добавить fcDayRow перед fcParamRow
html, ok = replace_once(html,
    '    <div class="fc-param-row" id="fcParamRow"></div>',
    '    <div class="fc-day-row" id="fcDayRow"></div>\n    <div class="fc-param-row" id="fcParamRow"></div>',
    "1. fcDayRow в HTML"
)
ok_all = ok_all and ok

# 2. Добавить функции после fcSwitchParam
NEW_FUNCS = '''
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
            : `${DAY_NAMES[d.getDay()]} ${d.getDate()}`;
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
    let hrs, tms;
    if(_fcDayOffset === null){
        const nowTime = Date.now();
        const td = window._fcAllTimes.map(t => new Date(t));
        let si = td.findIndex(t => t.getTime() >= nowTime);
        if(si === -1) si = 0;
        si = Math.max(0, si - 1);
        const ei = Math.min(si + forecastHours, window._fcAllHours.length);
        hrs = window._fcAllHours.slice(si, ei);
        tms = window._fcAllTimes.slice(si, ei);
    } else {
        const d = new Date();
        d.setDate(d.getDate() + _fcDayOffset);
        const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
        const idxs = window._fcAllTimes.map((t,i) => t.slice(0,10)===key ? i : -1).filter(i => i>=0);
        if(!idxs.length) return;
        hrs = idxs.map(i => window._fcAllHours[i]);
        tms = idxs.map(i => window._fcAllTimes[i]);
    }
    _fcHours = hrs;
    _fcTimes = tms;
    renderForecastChart(_fcHours, _fcTimes);
    renderAlertsBlock(_fcHours);
}

// =============================================
// TOOLTIP
// ============================================='''

html, ok = replace_once(html,
    '// =============================================\n// TOOLTIP\n// =============================================',
    NEW_FUNCS,
    "2. buildFcDayRow / fcSwitchDay / applyFcDayFilter"
)
ok_all = ok_all and ok

# 3. Ensemble: добавить _fcAllTimes и buildFcDayRow
html, ok = replace_once(html,
    '    window._fcAllHours = ensembleHours;\n\n    buildFcParamRow();\n    renderForecastChart(_fcHours, _fcTimes);\n    renderAlertsBlock(_fcHours);',
    '    window._fcAllHours = ensembleHours;\n    window._fcAllTimes = baseTimes;\n\n    buildFcParamRow();\n    buildFcDayRow();\n    renderForecastChart(_fcHours, _fcTimes);\n    renderAlertsBlock(_fcHours);',
    "3. ensemble: _fcAllTimes + buildFcDayRow"
)
ok_all = ok_all and ok

# 4. Regular load: добавить _fcAllTimes и buildFcDayRow
html, ok = replace_once(html,
    '    _fcHours = hours.slice(startIndex, endIndex2);\n    _fcTimes = h.time.slice(startIndex, endIndex2);\n\n    buildFcParamRow();\n    renderForecastChart(_fcHours, _fcTimes);\n    renderAlertsBlock(_fcHours);',
    '    _fcHours = hours.slice(startIndex, endIndex2);\n    _fcTimes = h.time.slice(startIndex, endIndex2);\n    window._fcAllHours = hours;\n    window._fcAllTimes = h.time;\n\n    buildFcParamRow();\n    buildFcDayRow();\n    renderForecastChart(_fcHours, _fcTimes);\n    renderAlertsBlock(_fcHours);',
    "4. regular load: _fcAllTimes + buildFcDayRow"
)
ok_all = ok_all and ok

if ok_all:
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print("  forecast.html сохранён")
else:
    print("  forecast.html НЕ сохранён из-за ошибок")

# ── forecast.css ──────────────────────────────────────────────────────────────
CSS_ADD = """
.fc-day-row {
    display: flex;
    gap: 6px;
    margin-bottom: 8px;
    overflow-x: auto;
    scrollbar-width: none;
}
.fc-day-row::-webkit-scrollbar { display: none; }
.fc-day-btn {
    padding: 5px 13px;
    font-size: 12px;
    border-radius: 20px;
    background: #1c1c1c;
    color: #666;
    border: 1px solid #2a2a2a;
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
    transition: 0.15s;
}
.fc-day-btn:hover { color: #ccc; background: #252525; }
.fc-day-btn.active {
    background: #1a1a1a;
    color: #fff;
    border-color: #555;
    box-shadow: 0 0 0 1px #555 inset;
}
"""

if ".fc-day-row" in open(CSS, encoding="utf-8").read():
    print("  [!] forecast.css: .fc-day-row уже есть, пропускаю")
else:
    with open(CSS, "a", encoding="utf-8") as f:
        f.write(CSS_ADD)
    print("  [ok] 5. forecast.css: стили добавлены")

print("\nГотово." if ok_all else "\nЕСТЬ ОШИБКИ — проверь вывод выше.")
