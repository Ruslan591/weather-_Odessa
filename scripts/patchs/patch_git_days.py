FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    _days_file = os.path.join(BASE_DIR, "data", "forecast_days.json")
    with open(_days_file, "w", encoding="utf-8") as _f:
        json.dump(days, _f, ensure_ascii=False, indent=2)'''
NEW = '''    _days_file = os.path.join(BASE_DIR, "data", "forecast_days.json")
    with open(_days_file, "w", encoding="utf-8") as _f:
        json.dump(days, _f, ensure_ascii=False, indent=2)
    import subprocess as _sp
    _sp.run(["git", "-C", BASE_DIR, "add", "data/forecast_days.json"], capture_output=True)'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
