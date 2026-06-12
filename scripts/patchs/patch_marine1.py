FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    "wind_wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature"
    "&timezone=Europe/Kiev&forecast_days=3"
)'''
NEW = '''    "wind_wave_height,swell_wave_height,swell_wave_period,sea_surface_temperature"
    "&timezone=Europe/Kiev&forecast_days=5"
)'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''def aggregate_marine(marine_data):
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
    }'''
NEW2 = '''def _aggregate_marine_one_day(day_recs):
    import math
    if not day_recs: return None

    def avg(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(sum(vals)/len(vals), 1) if vals else None

    def mx(key):
        vals = [r[key] for r in day_recs if r.get(key) is not None]
        return round(max(vals), 1) if vals else None

    sst_vals = [r["sea_surface_temp"] for r in day_recs if r.get("sea_surface_temp") is not None]
    sst = round(sum(sst_vals)/len(sst_vals), 1) if sst_vals else None

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

def aggregate_marine_days(marine_data, dates):
    """Агрегаты моря по каждой дате из dates (список 'YYYY-MM-DD'), дневные часы 06-21."""
    if not marine_data: return {}
    result = {}
    for date in dates:
        day_recs = [r for r in marine_data
                    if r["time"][:10] == date
                    and 6 <= int(r["time"][11:13]) <= 21]
        if not day_recs:
            day_recs = [r for r in marine_data if r["time"][:10] == date]
        agg = _aggregate_marine_one_day(day_recs)
        if agg: result[date] = agg
    return result'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK1")
