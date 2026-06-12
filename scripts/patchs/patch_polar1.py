FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''    "windspeed_200hPa","winddirection_200hPa",
    "temperature_50hPa","temperature_30hPa","temperature_10hPa",
])'''
NEW = '''    "windspeed_200hPa","winddirection_200hPa",
    "windspeed_100hPa","winddirection_100hPa",
    "windspeed_50hPa","winddirection_50hPa",
    "temperature_50hPa","temperature_30hPa","temperature_10hPa",
])'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK1")
