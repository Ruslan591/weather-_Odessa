FILE = 'ai_analysis.html'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''fetch('data/forecast_analysis_claude.json?t=' + Date.now())
  .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })'''
NEW = '''fetch('https://raw.githubusercontent.com/Ruslan591/weather-_Odessa/main/data/forecast_analysis_claude.json?_=' + Date.now(), { cache: 'no-store' })
  .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")