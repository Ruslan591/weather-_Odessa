FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    days = aggregate_days(raw)
    if not days:
        print("  [AI] \u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u0434\u043b\u044f \u0430\u043d\u0430\u043b\u0438\u0437\u0430")
        return'''
NEW = '''    days = aggregate_days(raw)
    if not days:
        print("  [AI] \u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u0434\u043b\u044f \u0430\u043d\u0430\u043b\u0438\u0437\u0430")
        return

    # \u0421\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u043c \u0430\u0433\u0440\u0435\u0433\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u043f\u043e \u0434\u043d\u044f\u043c
    _days_file = os.path.join(BASE_DIR, "data", "forecast_days.json")
    with open(_days_file, "w", encoding="utf-8") as _f:
        json.dump(days, _f, ensure_ascii=False, indent=2)'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
