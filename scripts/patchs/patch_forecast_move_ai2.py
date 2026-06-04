FILE = 'forecast.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Найти AI скрипт блок
marker = '// \u2500\u2500 AI-\u0430\u043d\u0430\u043b\u0438\u0437'
idx_marker = src.find(marker)
assert idx_marker != -1, "AI marker not found"

# Найти <script> перед маркером
idx_open = src.rfind('<script>', 0, idx_marker)
# Найти </script> после маркера
idx_close = src.find('</script>', idx_marker) + len('</script>')

ai_block = src[idx_open:idx_close]

# Убрать блок из текущего места (+ возможный \n)
rest = src[idx_close:]
if rest.startswith('\n'): rest = rest[1:]
src2 = src[:idx_open] + rest

# Вставить перед </body>
assert '</body>' in src2, "</body> not found"
src2 = src2.replace('</body>', ai_block + '\n</body>', 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src2)
print("OK, lines:", src2.count('\n'))