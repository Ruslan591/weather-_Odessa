FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = """    text = re.sub(r'(?i)индекс\\s+LI', 'индекс неустойчивости', text)
    text = re.sub(r'LI', 'индекс неустойчивости', text)"""
NEW = """    text = re.sub(r'(?i)индекс\\s+LI', 'индекс неустойчивости', text)
    text = re.sub(r'\\bLI\\b', 'индекс неустойчивости', text)"""
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
