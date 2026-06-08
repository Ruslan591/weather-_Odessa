FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD1 = "r'\x01 \u043c\u0435\u0442\u0440\u043e\u0432 \u0432 \u0441\u0435\u043a\u0443\u043d\u0434\u0443'"
NEW1 = "r'\\1 \u043c\u0435\u0442\u0440\u043e\u0432 \u0432 \u0441\u0435\u043a\u0443\u043d\u0434\u0443'"
OLD2 = "r'\x01 \u043c\u0438\u043b\u043b\u0438\u043c\u0435\u0442\u0440\u0430'"
NEW2 = "r'\\1 \u043c\u0438\u043b\u043b\u0438\u043c\u0435\u0442\u0440\u0430'"
assert OLD1 in src, "OLD1 not found"
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD1, NEW1, 1)
src = src.replace(OLD2, NEW2, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
