FILE = 'forecast.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# 1. Добавить вкладку после fcAlertsBlock
OLD = '''    <div id="fcAlertsBlock" style="margin-top:8px;"></div>
</div>'''
NEW = '''    <div id="fcAlertsBlock" style="margin-top:8px;"></div>
    <!-- AI-анализ вкладка -->
    <div style="margin-top:10px;max-width:340px;margin-left:auto;margin-right:auto;">
        <button id="aiTabBtn" onclick="toggleAiTab()"
            style="width:100%;padding:9px 14px;border-radius:10px;border:1px solid #252525;
            background:#111;color:#888;font-size:12px;cursor:pointer;text-align:left;
            touch-action:manipulation;display:flex;align-items:center;gap:8px;">
            <span style="font-size:14px;">🤖</span>
            <span>Синоптический анализ ИИ</span>
            <span id="aiTabArrow" style="margin-left:auto;font-size:10px;color:#555;">▾</span>
        </button>
        <div id="aiTabContent" style="display:none;margin-top:4px;background:#0e0e0e;
            border-radius:10px;border:1px solid #1e1e1e;padding:12px 14px;">
            <div id="aiTabBody" style="color:#888;font-size:11px;">Загрузка...</div>
        </div>
    </div>
</div>'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# 2. Добавить скрипт перед </body>
OLD2 = '<script src="nav.js"></script>'
NEW2 = '''<script src="nav.js"></script>
<script>
// ── AI-анализ ────────────────────────────────────────────────────────────────
var _aiLoaded = false;
function toggleAiTab(){
    var content = document.getElementById('aiTabContent');
    var arrow   = document.getElementById('aiTabArrow');
    var btn     = document.getElementById('aiTabBtn');
    var open    = content.style.display === 'none';
    content.style.display = open ? 'block' : 'none';
    arrow.textContent = open ? '▴' : '▾';
    btn.style.color   = open ? '#aaa' : '#888';
    if(open && !_aiLoaded) loadAiAnalysis();
}
function loadAiAnalysis(){
    _aiLoaded = true;
    var body = document.getElementById('aiTabBody');
    fetch('data/forecast_analysis.json?t=' + Date.now())
        .then(function(r){ return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function(d){
            var changed = d.changed;
            var genAt   = d.generated_at ? formatAiTime(d.generated_at) : '—';
            var chkAt   = d.last_checked ? formatAiTime(d.last_checked) : '—';
            var statusLine = changed
                ? '<div style="color:#555;font-size:10px;margin-bottom:10px;">🟢 Обновлён: ' + genAt + '</div>'
                : '<div style="color:#555;font-size:10px;margin-bottom:10px;">⚪ Проверено: ' + chkAt + ' · данные не изменились с ' + genAt + '</div>';
            var html = statusLine + markdownToHtml(d.text || '');
            body.innerHTML = html;
        })
        .catch(function(e){
            body.innerHTML = '<div style="color:#555;font-size:11px;">Анализ ещё не сгенерирован.<br>Будет доступен после следующего прогона моделей.</div>';
        });
}
function formatAiTime(iso){
    try{
        var d = new Date(iso);
        return d.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    } catch(e){ return iso; }
}
function markdownToHtml(text){
    // ## Заголовки → <h4>, **bold** → <b>, параграфы
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/^## ⚠️ (.+)$/gm,'<h4 style="color:#fdcb6e;font-size:12px;margin:12px 0 4px;">⚠️ $1</h4>')
        .replace(/^## (.+)$/gm,'<h4 style="color:#aaa;font-size:12px;margin:12px 0 4px;border-top:1px solid #1e1e1e;padding-top:8px;">$1</h4>')
        .replace(/\*\*(.+?)\*\*/g,'<b style="color:#ccc;">$1</b>')
        .replace(/\n\n/g,'</p><p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/\n/g,' ')
        .replace(/^/,'<p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/$/,'</p>');
}
</script>'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")