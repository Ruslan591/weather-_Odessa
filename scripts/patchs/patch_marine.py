FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''def fetch_one_model(model):'''

NEW = '''MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
    "?latitude=46.35&longitude=30.90"
    "&hourly=wave_height,wave_direction,wave_period,"
    "wind_wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature"
    "&timezone=Europe/Kiev&forecast_days=3"
)

def fetch_marine():
    try:
        req = urllib.request.Request(MARINE_URL, headers={"User-Agent": "weather-verifier/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode())
        h = data.get("hourly", {})
        if not h.get("time"): return None
        times = h["time"]
        result = []
        for i, t in enumerate(times):
            result.append({
                "time":                  t,
                "wave_height":           h.get("wave_height",             [None]*len(times))[i],
                "wave_direction":        h.get("wave_direction",          [None]*len(times))[i],
                "wave_period":           h.get("wave_period",             [None]*len(times))[i],
                "wind_wave_height":      h.get("wind_wave_height",        [None]*len(times))[i],
                "swell_wave_height":     h.get("swell_wave_height",       [None]*len(times))[i],
                "swell_wave_period":     h.get("swell_wave_period",       [None]*len(times))[i],
                "sea_surface_temp":      h.get("sea_surface_temperature", [None]*len(times))[i],
            })
        return result
    except Exception as e:
        print(f"  [AI] Marine API error: {e}")
        return None

def aggregate_marine(marine_data):
    """Агрегат морских данных на сегодня (дневные часы 06-21)."""
    if not marine_data: return None
    import math
    now_local = datetime.now(timezone.utc).astimezone()
    today_str = now_local.strftime("%Y-%m-%d")
    day_recs = [r for r in marine_data
                if r["time"][:10] == today_str
                and 6 <= int(r["time"][11:13]) <= 21]
    if not day_recs:
        day_recs = [r for r in marine_data if r["time"][:10] == today_str]
    if not day_recs: return None

    def avg(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(sum(vals)/len(vals), 1) if vals else None

    def mx(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(max(vals), 1) if vals else None

    # Средняя температура воды за период
    sst_vals = [r["sea_surface_temp"] for r in day_recs if r.get("sea_surface_temp") is not None]
    sst = round(sum(sst_vals)/len(sst_vals), 1) if sst_vals else None

    # Среднее направление волны (векторное)
    dir_vals = [r["wave_direction"] for r in day_recs if r.get("wave_direction") is not None]
    if dir_vals:
        sx = sum(math.sin(math.radians(d)) for d in dir_vals)
        sy = sum(math.cos(math.radians(d)) for d in dir_vals)
        wave_dir = round((math.degrees(math.atan2(sx, sy)) + 360) % 360)
        dirs = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"]
        wave_dir_str = dirs[int((wave_dir+22.5)/45)%8]
    else:
        wave_dir_str = "?"

    return {
        "sst":              sst,
        "wave_height_max":  mx("wave_height"),
        "wave_height_avg":  avg("wave_height"),
        "wave_dir":         wave_dir_str,
        "wave_period":      avg("wave_period"),
        "wind_wave_max":    mx("wind_wave_height"),
        "swell_height_max": mx("swell_wave_height"),
        "swell_period":     avg("swell_wave_period"),
    }

def fmt_marine(m):
    """Строки данных моря для промпта."""
    if not m: return ["  Данные недоступны"]
    lines = []
    if m.get("sst") is not None:
        lines.append(f"  Температура воды: {m['sst']}°C")
    wh = m.get("wave_height_max")
    wa = m.get("wave_height_avg")
    if wh is not None:
        lines.append(f"  Высота волны: макс {wh}м, ср {wa}м, направление {m.get('wave_dir','?')}, период {m.get('wave_period')}с")
    if m.get("wind_wave_max") is not None:
        lines.append(f"  Ветровое волнение: {m['wind_wave_max']}м")
    if m.get("swell_height_max") is not None:
        lines.append(f"  Зыбь: {m['swell_height_max']}м, период {m.get('swell_period')}с")
    return lines

def fetch_one_model(model):'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# Добавляем marine в main() перед вызовом build_prompt
OLD2 = '''    days = aggregate_days(raw)
    if not days:
        print("  [AI] Нет данных для анализа")
        return

    # Проверяем изменились ли данные
    current_hash = data_hash(days)'''

NEW2 = '''    days = aggregate_days(raw)
    if not days:
        print("  [AI] Нет данных для анализа")
        return

    # Marine данные
    marine_raw = fetch_marine()
    marine = aggregate_marine(marine_raw)
    if marine:
        print(f"  [AI] Marine: SST={marine.get('sst')}°C wave={marine.get('wave_height_max')}м")

    # Проверяем изменились ли данные
    current_hash = data_hash(days)'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

# Передаём marine в build_prompt
OLD3 = '''    prompt = build_prompt(days)'''
NEW3 = '''    prompt = build_prompt(days, marine=marine)'''

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

# Добавляем marine в build_prompt сигнатуру и тело
OLD4 = '''def build_prompt(days):'''
NEW4 = '''def build_prompt(days, marine=None):'''

assert OLD4 in src, "OLD4 not found"
src = src.replace(OLD4, NEW4, 1)

# Добавляем блок моря в структуру промпта
OLD5 = '''    lines += [
        "СТРУКТУРА ОТВЕТА (строго, используй точные заголовки):",
    ] + struct + [
        "",
        "Не используй таблицы. Не повторяй цифры из данных дословно — интерпретируй их синоптически.",
    ]'''

NEW5 = '''    # Marine данные в промпт
    if marine:
        lines += [
            "СОСТОЯНИЕ ЧЁРНОГО МОРЯ (сегодня, точка 8 км от берега):",
        ] + fmt_marine(marine) + [""]

    lines += [
        "СТРУКТУРА ОТВЕТА (строго, используй точные заголовки):",
    ] + struct + [
        f"N. ## \U0001f30a Море — температура воды, волнение, условия на море (1-2 предложения)",
        "",
        "Не используй таблицы. Не повторяй цифры из данных дословно — интерпретируй их синоптически.",
    ]'''

assert OLD5 in src, "OLD5 not found"
src = src.replace(OLD5, NEW5, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
