FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

# 1. Извлечь data_time из raw и передать в build_prompt
OLD1 = '''    days = aggregate_days(raw)'''
NEW1 = '''    days = aggregate_days(raw)
    data_time = raw.get("data_time")
    if data_time:
        print(f"  [AI] \u0414\u0430\u043d\u043d\u044b\u0435 open-meteo: {data_time}")'''

assert OLD1 in src, "OLD1 not found"
src = src.replace(OLD1, NEW1, 1)
print("patch1 OK")

# 2. Передать data_time в build_prompt
OLD2 = '''    prompt = build_prompt(days, marine=marine)'''
NEW2 = '''    prompt = build_prompt(days, marine=marine, data_time=data_time)'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)
print("patch2 OK")

# 3. Добавить data_time в сигнатуру build_prompt и в промпт
OLD3 = '''def build_prompt(days, marine=None):'''
NEW3 = '''def build_prompt(days, marine=None, data_time=None):'''

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)
print("patch3 OK")

# 4. Добавить строку в промпт после "Время генерации"
OLD4 = '''    lines = [
        f"\u0412\u0440\u0435\u043c\u044f \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438: {now_str}",
        f"\u041c\u0435\u0441\u0442\u043e: \u041e\u0434\u0435\u0441\u0441\u0430, \u0423\u043a\u0440\u0430\u0438\u043d\u0430 (46.43\u00b0N, 30.74\u00b0E, \u043f\u043e\u0431\u0435\u0440\u0435\u0436\u044c\u0435 \u0427\u0451\u0440\u043d\u043e\u0433\u043e \u043c\u043e\u0440\u044f)",'''
NEW4 = '''    # Форматируем время данных open-meteo для промпта
    if data_time:
        try:
            dt_parsed = datetime.strptime(data_time[:16], "%Y-%m-%dT%H:%M")
            data_time_str = dt_parsed.strftime("%d.%m.%Y %H:%M \u043c\u0435\u0441\u0442\u043d\u043e\u0433\u043e")
        except Exception:
            data_time_str = data_time
    else:
        data_time_str = "\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e"

    lines = [
        f"\u0412\u0440\u0435\u043c\u044f \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438: {now_str}",
        f"\u0414\u0430\u043d\u043d\u044b\u0435 open-meteo \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u044b: {data_time_str}",
        f"\u041c\u0435\u0441\u0442\u043e: \u041e\u0434\u0435\u0441\u0441\u0430, \u0423\u043a\u0440\u0430\u0438\u043d\u0430 (46.43\u00b0N, 30.74\u00b0E, \u043f\u043e\u0431\u0435\u0440\u0435\u0436\u044c\u0435 \u0427\u0451\u0440\u043d\u043e\u0433\u043e \u043c\u043e\u0440\u044f)",'''

assert OLD4 in src, "OLD4 not found"
src = src.replace(OLD4, NEW4, 1)
print("patch4 OK")

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("ALL OK")
