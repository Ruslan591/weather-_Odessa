FILE = 'forecast.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Убрать старый скрипт между nav.js и models.js
OLD = '<script src="nav.js"></script>\n<script>\n// \u2500\u2500 AI-\u0430\u043d\u0430\u043b\u0438\u0437'
# Ищем позицию вручную
idx1 = src.find('<script src="nav.js"></script>')
idx2 = src.find('<script src="models.js"></script>')
assert idx1 != -1, "nav.js not found"
assert idx2 != -1, "models.js not found"

# Вырезаем всё между nav.js и models.js
src = src[:idx1 + len('<script src="nav.js"></script>\n')] + src[idx2:]

# Вставляем правильный скрипт перед закрывающим </body>
AI_SCRIPT = '''<script>
// AI-анализ
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
            var genAt = d.generated_at ? formatAiTime(d.generated_at) : '—';
            var chkAt = d.last_checked ? formatAiTime(d.last_checked) : '—';
            var statusLine = d.changed
                ? '<div style="color:#555;font-size:10px;margin-bottom:10px;">🟢 Обновлён: ' + genAt + '</div>'
                : '<div style="color:#555;font-size:10px;margin-bottom:10px;">⚪ Проверено: ' + chkAt + ' · данные не изменились с ' + genAt + '</div>';
            body.innerHTML = statusLine + markdownToHtml(d.text || '');
        })
        .catch(function(){
            body.innerHTML = '<div style="color:#555;font-size:11px;">Анализ ещё не сгенерирован.<br>Будет доступен после следующего прогона моделей.</div>';
        });
}
function formatAiTime(iso){
    try{ return new Date(iso).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); }
    catch(e){ return iso; }
}
function markdownToHtml(text){
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/^## .️ (.+)$/gm,'<h4 style="color:#fdcb6e;font-size:12px;margin:12px 0 4px;">⚠️ $1</h4>')
        .replace(/^## (.+)$/gm,'<h4 style="color:#aaa;font-size:12px;margin:12px 0 4px;border-top:1px solid #1e1e1e;padding-top:8px;">$1</h4>')
        .replace(/[*][*](.+?)[*][*]/g,'<b style="color:#ccc;">$1</b>')
        .replace(/\n\n/g,'</p><p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/\n/g,' ')
        .replace(/^/,'<p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/$/,'</p>');
}
</script>
'''

OLD2 = '</body>\n</html>'
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, AI_SCRIPT + '</body>\n</html>', 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")