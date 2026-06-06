FILE = '/storage/emulated/0/Documents/weather/ai_analysis.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Находим сломанный split с буквальным переносом строки внутри regex
OLD = 'function blockTextToHtml(text) {\n  text = text.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\');\n  text = text.replace(/\\*\\*(.+?)\\*\\*/g,\'<b>$1</b>\').replace(/\\*(.+?)\\*/g,\'<em>$1</em>\');\n  var parts = text.split(/\n\n+/);\n  return parts.map(function(p){ return \'<p>\' + p.trim() + \'</p>\'; }).join(\'\');\n}'

NEW = 'function blockTextToHtml(text) {\n  text = text.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\');\n  text = text.replace(/\\*\\*(.+?)\\*\\*/g,\'<b>$1</b>\').replace(/\\*(.+?)\\*/g,\'<em>$1</em>\');\n  var parts = text.split(/\\n\\n+/);\n  return parts.map(function(p){ return \'<p>\' + p.trim() + \'</p>\'; }).join(\'\');\n}'

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
