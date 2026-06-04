FILE = 'forecast.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Найти и вырезать блок AI скрипта (он сейчас в середине)
start_marker = '<script>\n// \u2500\u2500 AI-\u0430\u043d\u0430\u043b\u0438\u0437'
end_marker = '</script>\n\n<script src="js/fc-tooltip.js">'

idx_start = src.find('// \u2500\u2500 AI-\u0430\u043d\u0430\u043b\u0438\u0437')
# Найти открывающий <script> перед маркером
idx_script_open = src.rfind('<script>', 0, idx_start)
# Найти закрывающий </script> после маркера
idx_script_close = src.find('</script>', idx_start) + len('</script>')

assert idx_script_open != -1, "script open not found"
assert idx_script_close != -1, "script close not found"

# Вырезаем блок (включая \n после него)
ai_block = src[idx_script_open:idx_script_close]
# Убираем лишний \n после блока
src_without = src[:idx_script_open] + src[idx_script_close:].lstrip('\n')

# Вставляем перед </body>
AI_SCRIPT = '''<script>
// AI-анализ
var _aiLoaded = false;
function toggleAiTab(){
    var content = document.getElementById('aiTabContent');
    var arrow   = document.getElementById('aiTabArrow');
    var btn     = document.getElementById('aiTabBtn');
    var open    = content.style.display === 'none';
    content.style.display = open ? 'block' : 'none';
    arrow.textContent = open ? '\u25b4' : '\u25be';
    btn.style.color   = open ? '#aaa' : '#888';
    if(open && !_aiLoaded) loadAiAnalysis();
}
function loadAiAnalysis(){
    _aiLoaded = true;
    var body = document.getElementById('aiTabBody');
    fetch('data/forecast_analysis.json?t=' + Date.now())
        .then(function(r){ return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function(d){
            var genAt = d.generated_at ? formatAiTime(d.generated_at) : '\u2014';
            var chkAt = d.last_checked ? formatAiTime(d.last_checked) : '\u2014';
            var statusLine = d.changed
                ? '<div style="color:#555;font-size:10px;margin-bottom:10px;">\ud83d\udfe2 \u041e\u0431\u043d\u043e\u0432\u043b\u0451\u043d: ' + genAt + '</div>'
                : '<div style="color:#555;font-size:10px;margin-bottom:10px;">\u26aa \u041f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043e: ' + chkAt + ' \u00b7 \u0434\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c \u0441 ' + genAt + '</div>';
            body.innerHTML = statusLine + markdownToHtml(d.text || '');
        })
        .catch(function(){
            body.innerHTML = '<div style="color:#555;font-size:11px;">\u0410\u043d\u0430\u043b\u0438\u0437 \u0435\u0449\u0451 \u043d\u0435 \u0441\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u043d.</div>';
        });
}
function formatAiTime(iso){
    try{ return new Date(iso).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); }
    catch(e){ return iso; }
}
function markdownToHtml(text){
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/^## [*][*]\u26a0\ufe0f[*][*] (.+)$/gm,'<h4 style="color:#fdcb6e;font-size:12px;margin:12px 0 4px;">\u26a0\ufe0f $1</h4>')
        .replace(/^## (.+)$/gm,'<h4 style="color:#aaa;font-size:12px;margin:12px 0 4px;border-top:1px solid #1e1e1e;padding-top:8px;">$1</h4>')
        .replace(/[*][*](.+?)[*][*]/g,'<b style="color:#ccc;">$1</b>')
        .replace(/\n\n/g,'</p><p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/\n/g,' ')
        .replace(/^/,'<p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/$/,'</p>');
}
</script>
'''

assert '</body>' in src_without, "</body> not found"
src_final = src_without.replace('</body>', AI_SCRIPT + '</body>', 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src_final)
print("OK")