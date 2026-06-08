FILE = 'ai_analysis.html'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD1 = '''  <div id="statusBar" class="status-bar" style="display:none">'''
NEW1 = '''  <div id="videoWrap" style="display:none;margin-bottom:20px">
    <video controls playsinline preload="none"
      style="width:100%;max-width:340px;border-radius:14px;display:block;margin:0 auto;box-shadow:0 4px 24px rgba(0,0,0,0.6)">
      <source id="videoSrc" src="" type="video/mp4">
    </video>
  </div>
  <div id="statusBar" class="status-bar" style="display:none">'''
assert OLD1 in src, "OLD1 not found"
src = src.replace(OLD1, NEW1, 1)

OLD2 = '''loadBlocksMeta();'''
NEW2 = '''loadBlocksMeta();
(function(){
  var url='https://ruslan591.github.io/weather-_Odessa/data/forecast_video.mp4?_='+Date.now();
  document.getElementById('videoSrc').src=url;
  document.getElementById('videoWrap').style.display='block';
})();'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
