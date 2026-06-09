FILE = 'ai_analysis.html'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''  var url='https://ruslan591.github.io/weather-_Odessa/data/forecast_video.mp4?_='+Date.now();
  document.getElementById('videoSrc').src=url;
  document.getElementById('videoWrap').style.display='block';'''
NEW = '''  var url='https://ruslan591.github.io/weather-_Odessa/data/forecast_video.mp4?v='+Date.now();
  var vid = document.getElementById('videoSrc');
  var wrap = document.getElementById('videoWrap');
  vid.src = url;
  vid.parentElement.load();
  wrap.style.display='block';'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
