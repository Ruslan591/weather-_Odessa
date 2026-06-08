FILE = 'ai_analysis.html'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''  <div id="videoWrap" style="display:none;margin-bottom:20px">
    <video controls playsinline preload="none"
      style="width:100%;max-width:340px;border-radius:14px;display:block;margin:0 auto;box-shadow:0 4px 24px rgba(0,0,0,0.6)">
      <source id="videoSrc" src="" type="video/mp4">
    </video>
  </div>
  <div id="statusBar" class="status-bar" style="display:none">'''
NEW = '''  <div id="videoWrap" style="display:none;margin-bottom:12px">
    <video controls playsinline preload="none"
      style="width:100%;max-width:340px;border-radius:14px;display:block;margin:0 auto;box-shadow:0 4px 24px rgba(0,0,0,0.6)">
      <source id="videoSrc" src="" type="video/mp4">
    </video>
  </div>
  <button class="pres-btn hidden" id="presBtnTop" onclick="openPresentation()" style="margin-bottom:16px">
    \u25b6 \u041f\u0440\u0435\u0437\u0435\u043d\u0442\u0430\u0446\u0438\u044f
  </button>
  <div id="statusBar" class="status-bar" style="display:none">'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# Показываем верхнюю кнопку когда блоки загружены
OLD2 = '''        document.getElementById('presBtn').classList.remove('hidden');'''
NEW2 = '''        document.getElementById('presBtn').classList.remove('hidden');
        document.getElementById('presBtnTop').classList.remove('hidden');'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
