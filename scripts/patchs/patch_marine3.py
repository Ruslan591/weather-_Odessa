FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

# 1. main(): замена вызова aggregate_marine
OLD = '''    marine_raw = fetch_marine()
    marine = aggregate_marine(marine_raw)
    if marine:
        print(f"  [AI] Marine: SST={marine.get('sst')}°C wave={marine.get('wave_height_max')}м")'''
NEW = '''    marine_raw = fetch_marine()
    marine_dates = [d["date"] for d in days]
    marine = aggregate_marine_days(marine_raw, marine_dates)
    if marine:
        first_key = marine_dates[0]
        first = marine.get(first_key)
        if first:
            print(f"  [AI] Marine: SST={first.get('sst')}°C wave={first.get('wave_height_max')}м")'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# 2. build_prompt: замена секции "СОСТОЯНИЕ ЧЁРНОГО МОРЯ"
OLD2 = '''    # Marine данные в промпт
    if marine:
        now_local = datetime.now(timezone.utc).astimezone()
        today_str = now_local.strftime("%Y-%m-%d")
        lines += [
            "СОСТОЯНИЕ ЧЁРНОГО МОРЯ (сегодня, точка 8 км от берега):",
        ] + fmt_marine(marine, today_str=today_str) + [""]'''
NEW2 = '''    # Marine данные в промпт (по дням, как и суша)
    if marine:
        lines += ["СОСТОЯНИЕ ЧЁРНОГО МОРЯ ПО ДНЯМ (точка 8 км от берега):", ""]
        for i, d in enumerate(days):
            m = marine.get(d["date"])
            if not m: continue
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            label = day_labels[i] if i < len(day_labels) else f"День +{i}"
            lines.append(f"-- {label} ({dt.strftime('%d.%m')}) --")
            lines += fmt_marine(m)
        lines.append("")'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK3")
