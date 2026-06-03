FILE = 'js/fc-params.js'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''function buildFcParamRow(){
    const row = document.getElementById("fcParamRow");
    if(!row) return;
    let html = "";
    FC_GROUPS.forEach(g => {
        if(g.label) html += `<div style="width:100%;font-size:9px;color:#444;font-weight:700;letter-spacing:0.08em;padding:6px 2px 2px;text-transform:uppercase;">${g.label}</div>`;
        g.keys.forEach(key => {
            const p = FC_PARAMS.find(p => p.key === key);
            if(!p) return;
            html += `<button class="fc-param-btn${p.key === _fcParam ? " active" : ""}" data-key="${p.key}" style="--c:${p.color}" onclick="fcSwitchParam(\'${p.key}\')">${p.label}</button>`;
        });
    });
    row.innerHTML = html;
}'''
NEW = '''function buildFcParamRow(){
    const row = document.getElementById("fcParamRow");
    if(!row) return;

    // Основные параметры — горизонтальный скролл
    const mainGroup = FC_GROUPS[0];
    let html = `<div class="fc-main-params">`;
    mainGroup.keys.forEach(key => {
        const p = FC_PARAMS.find(p => p.key === key);
        if(!p) return;
        html += `<button class="fc-param-btn${p.key === _fcParam ? " active" : ""}" data-key="${p.key}" style="--c:${p.color}" onclick="fcSwitchParam(\'${p.key}\')">${p.label}</button>`;
    });
    html += `</div>`;

    // Аккордеоны для остальных групп
    FC_GROUPS.slice(1).forEach((g, gi) => {
        const gid = `fcGroup_${gi}`;
        const hasActive = g.keys.includes(_fcParam);
        html += `<div class="fc-group-accord${hasActive ? \' open\' : \'\'}" id="${gid}">`;
        html += `<div class="fc-group-header" onclick="toggleFcGroup(\'${gid}\')">`;
        html += `<span class="fc-group-label">${g.label}</span><span class="fc-group-arrow">▾</span></div>`;
        html += `<div class="fc-group-body"><div style="display:flex;flex-wrap:wrap;gap:6px;padding-bottom:8px;">`;
        g.keys.forEach(key => {
            const p = FC_PARAMS.find(p => p.key === key);
            if(!p) return;
            html += `<button class="fc-param-btn${p.key === _fcParam ? " active" : ""}" data-key="${p.key}" style="--c:${p.color}" onclick="fcSwitchParam(\'${p.key}\')">${p.label}</button>`;
        });
        html += `</div></div></div>`;
    });

    row.innerHTML = html;
}

function toggleFcGroup(gid){
    const el = document.getElementById(gid);
    if(el) el.classList.toggle(\'open\');
}'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")