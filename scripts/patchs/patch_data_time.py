FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD1 = '''def fetch_one_model(model):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&models={model}"
        f"&forecast_days=7"
        f"&timezone={TIMEZONE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())'''

NEW1 = '''def fetch_one_model(model):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&current=temperature_2m"
        f"&models={model}"
        f"&forecast_days=7"
        f"&timezone={TIMEZONE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())'''

assert OLD1 in src, "OLD1 not found"
src = src.replace(OLD1, NEW1, 1)
print("patch1 OK")

OLD2 = '''def fetch_ensemble():
    all_hourly = []
    times = None
    for model in FORECAST_MODELS:
        try:
            data = fetch_one_model(model)
            h = data.get("hourly", {})
            if not h.get("time"): continue
            if times is None: times = h["time"]
            all_hourly.append(h)
            print(f"  [AI] ok {model}")
        except Exception as e:
            print(f"  [AI] skip {model}: {e}")
    if not all_hourly:
        raise RuntimeError("\u041d\u0438 \u043e\u0434\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c \u043d\u0435 \u043e\u0442\u0432\u0435\u0442\u0438\u043b\u0430")'''

NEW2 = '''def fetch_ensemble():
    all_hourly = []
    times = None
    data_time = None
    for model in FORECAST_MODELS:
        try:
            data = fetch_one_model(model)
            h = data.get("hourly", {})
            if not h.get("time"): continue
            if times is None: times = h["time"]
            if data_time is None:
                cur = data.get("current", {})
                data_time = cur.get("time")
            all_hourly.append(h)
            print(f"  [AI] ok {model}")
        except Exception as e:
            print(f"  [AI] skip {model}: {e}")
    if not all_hourly:
        raise RuntimeError("\u041d\u0438 \u043e\u0434\u043d\u0430 \u043c\u043e\u0434\u0435\u043b\u044c \u043d\u0435 \u043e\u0442\u0432\u0435\u0442\u0438\u043b\u0430")'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)
print("patch2 OK")

OLD3 = '''    return {"hourly": merged}'''
NEW3 = '''    return {"hourly": merged, "data_time": data_time}'''

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)
print("patch3 OK")

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("ALL OK")
