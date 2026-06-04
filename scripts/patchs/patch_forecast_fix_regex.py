FILE = 'forecast.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Найти и заменить всю функцию markdownToHtml
idx = src.find('function markdownToHtml(text){')
assert idx != -1, "markdownToHtml not found"
idx_end = src.find('}\n</script>', idx) + 1
assert idx_end != -1, "end not found"

old_func = src[idx:idx_end]
new_func = '''function markdownToHtml(text){
    return text
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/^## (.+)$/gm,function(m,t){
            if(t.indexOf('\u26a0')===0) return '<h4 style="color:#fdcb6e;font-size:12px;margin:12px 0 4px;">'+t+'</h4>';
            return '<h4 style="color:#aaa;font-size:12px;margin:12px 0 4px;border-top:1px solid #1e1e1e;padding-top:8px;">'+t+'</h4>';
        })
        .replace(/[*][*](.+?)[*][*]/g,'<b style="color:#ccc;">$1</b>')
        .split('\\n\\n').join('</p><p style="margin:0 0 6px;line-height:1.6;">')
        .split('\\n').join(' ')
        .replace(/^/,'<p style="margin:0 0 6px;line-height:1.6;">')
        .replace(/$/,'</p>');
}'''

src = src[:idx] + new_func + src[idx_end:]
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK, lines:", src.count('\n'))