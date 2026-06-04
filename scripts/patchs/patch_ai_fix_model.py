FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '"model": "claude-sonnet-4-20250514",'
NEW = '"model": "claude-sonnet-4-5",'
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")