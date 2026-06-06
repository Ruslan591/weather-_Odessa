FILE = '/storage/emulated/0/Documents/weather/ai_analysis.html'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# ── 1. CSS: добавляем стили презентации перед </style> ──
OLD_CSS = '''  .font-btn:hover { background: var(--btn-hover); color: var(--text); }
</style>'''

NEW_CSS = '''  .font-btn:hover { background: var(--btn-hover); color: var(--text); }

  /* ── Кнопка презентации ── */
  .pres-btn {
    width: 100%; padding: 12px; margin-bottom: 16px;
    background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
    border: 1px solid #2a5a7a; border-radius: 10px; color: #4fc3f7;
    font-family: 'Helvetica Neue', sans-serif; font-size: 14px; font-weight: 600;
    cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;
    transition: opacity .15s, transform .1s; letter-spacing: .03em;
  }
  .pres-btn:hover { opacity: .85; }
  .pres-btn:active { transform: scale(.98); }
  .pres-btn.hidden { display: none; }

  /* ── Режим презентации ── */
  .presentation {
    display: none; position: fixed; inset: 0; z-index: 200;
    background: #080c14; flex-direction: column;
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }
  .presentation.active { display: flex; }
  .pres-bg { position: absolute; inset: 0; z-index: 0; }

  .pres-header {
    position: relative; z-index: 10; display: flex; align-items: center;
    padding: 12px 16px; gap: 12px;
    background: linear-gradient(to bottom, rgba(0,0,0,.7), transparent);
  }
  .pres-close {
    background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2);
    color: #ccc; border-radius: 8px; padding: 6px 14px; font-size: 13px;
    cursor: pointer; transition: background .15s;
  }
  .pres-close:hover { background: rgba(255,255,255,.2); }
  .pres-block-title {
    flex: 1; text-align: center; font-size: 15px; font-weight: 700;
    color: #fff; letter-spacing: .05em; text-transform: uppercase; opacity: .9;
  }
  .pres-block-icon { font-size: 22px; }

  .pres-progress { position: relative; z-index: 10; display: flex; gap: 4px; padding: 0 16px 8px; }
  .pres-seg { flex: 1; height: 3px; border-radius: 2px; background: rgba(255,255,255,.2); overflow: hidden; }
  .pres-seg-fill { height: 100%; background: #4fc3f7; width: 0%; transition: width .1s linear; }
  .pres-seg.done .pres-seg-fill { width: 100%; }
  .pres-seg.active .pres-seg-fill { background: #fff; }

  .pres-body {
    position: relative; z-index: 10; flex: 1; overflow: hidden;
    display: flex; flex-direction: column; padding: 0 16px 12px;
  }
  .pres-chart-wrap {
    height: 160px; margin-bottom: 12px; opacity: 0;
    transition: opacity .4s; flex-shrink: 0;
  }
  .pres-chart-wrap.visible { opacity: 1; }
  .pres-chart { width: 100%; height: 100%; }

  .pres-text-card {
    flex: 1; background: rgba(10,20,40,.75); border: 1px solid rgba(79,195,247,.2);
    border-radius: 12px; padding: 16px; overflow-y: auto;
    backdrop-filter: blur(8px); font-size: 15px; line-height: 1.7; color: #d4e8ff;
  }
  .pres-text-card b { color: #fff; }
  .pres-text-card p { margin-bottom: 10px; }
  .pres-text-card.warn-card { border-color: rgba(255,160,60,.4); }

  .pres-footer {
    position: relative; z-index: 10; padding: 10px 16px 16px;
    background: linear-gradient(to top, rgba(0,0,0,.7), transparent);
    display: flex; flex-direction: column; gap: 8px;
  }
  .pres-audio { width: 100%; height: 32px; accent-color: #4fc3f7; }
  .pres-nav { display: flex; gap: 8px; justify-content: center; }
  .pres-nav-btn {
    background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2);
    color: #ccc; border-radius: 8px; padding: 8px 20px; font-size: 14px;
    cursor: pointer; transition: background .15s;
  }
  .pres-nav-btn:hover { background: rgba(255,255,255,.2); color: #fff; }
  .pres-nav-btn:disabled { opacity: .3; cursor: default; }
  .pres-nav-btn.play-btn {
    background: rgba(79,195,247,.15); border-color: rgba(79,195,247,.4); color: #4fc3f7;
    min-width: 120px; display: flex; align-items: center; justify-content: center; gap: 6px;
  }
  .pres-nav-btn.play-btn:hover { background: rgba(79,195,247,.25); }
</style>'''

assert OLD_CSS in src, "OLD_CSS not found"
src = src.replace(OLD_CSS, NEW_CSS, 1)

# ── 2. HTML: кнопка + блок презентации перед </body> ──
OLD_BODY = '''<script>
// ── Theme ──────────────────────────────────────────────────────────────────'''

NEW_BODY = '''<!-- ── Кнопка презентации ── -->
<button class="pres-btn hidden" id="presBtn" onclick="openPresentation()">
  ▶ Презентация по блокам
</button>

<!-- ── Presentation overlay ── -->
<div class="presentation" id="presentation">
  <canvas class="pres-bg" id="presBg"></canvas>
  <div class="pres-header">
    <button class="pres-close" onclick="closePresentation()">✕ Закрыть</button>
    <div class="pres-block-title" id="presTitle"></div>
    <div class="pres-block-icon" id="presIcon"></div>
  </div>
  <div class="pres-progress" id="presProgress"></div>
  <div class="pres-body">
    <div class="pres-chart-wrap" id="presChartWrap">
      <canvas class="pres-chart" id="presChart"></canvas>
    </div>
    <div class="pres-text-card" id="presText"></div>
  </div>
  <div class="pres-footer">
    <audio class="pres-audio" id="presAudio" preload="none"></audio>
    <div class="pres-nav">
      <button class="pres-nav-btn" id="prevBtn" onclick="presNav(-1)">← Назад</button>
      <button class="pres-nav-btn play-btn" id="playBtn" onclick="presTogglePlay()">▶ Слушать</button>
      <button class="pres-nav-btn" id="nextBtn" onclick="presNav(1)">Вперёд →</button>
    </div>
  </div>
</div>

<script>
// ── Theme ──────────────────────────────────────────────────────────────────'''

assert OLD_BODY in src, "OLD_BODY not found"
src = src.replace(OLD_BODY, NEW_BODY, 1)

# ── 3. JS: добавляем презентационный код перед закрывающим </script> ──
OLD_JS = '''  .catch(function() {
    document.getElementById('content').innerHTML =
      '<div class="error-msg">Анализ ещё не сгенерирован.<br>Запустите <code>generate_ai_analysis.py</code> вручную.</div>';
  });
</script>'''

NEW_JS = '''  .catch(function() {
    document.getElementById('content').innerHTML =
      '<div class="error-msg">Анализ ещё не сгенерирован.<br>Запустите <code>generate_ai_analysis.py</code> вручную.</div>';
  });

// ── Загрузка мета блоков ───────────────────────────────────────────────────
var _blocksMeta = null;
var _analysisData = null;

function loadBlocksMeta() {
  fetch('https://raw.githubusercontent.com/Ruslan591/weather-_Odessa/main/data/blocks/blocks_meta.json?_=' + Date.now(), {cache:'no-store'})
    .then(function(r){ return r.ok ? r.json() : Promise.reject(); })
    .then(function(meta) {
      if (meta.blocks && meta.blocks.length > 0) {
        _blocksMeta = meta;
        document.getElementById('presBtn').classList.remove('hidden');
      }
    })
    .catch(function(){});
}

// Перехватываем успешную загрузку analysisData чтобы сохранить её
var _origFetch = fetch;
// Данные сохраняются в обработчике ниже через глобальную переменную

// ── Presentation engine ────────────────────────────────────────────────────
var _presIdx = 0;
var _presBlocks = [];
var _presAudioEl = null;
var _bgAnim = null;

var BLOCK_THEMES = {
  today:    { from: '#0a1628', to: '#0d2137', accent: '#4fc3f7' },
  tomorrow: { from: '#0e1a10', to: '#162818', accent: '#81c784' },
  next3:    { from: '#1a1000', to: '#251808', accent: '#ffb74d' },
  warnings: { from: '#200800', to: '#2d0e00', accent: '#ff7043' },
  trend:    { from: '#0d0d20', to: '#151530', accent: '#ce93d8' },
};

function openPresentation() {
  if (!_blocksMeta || !_blocksMeta.blocks.length) return;
  _presBlocks = _blocksMeta.blocks;
  _presIdx = 0;
  buildProgress();
  document.getElementById('presentation').classList.add('active');
  document.body.style.overflow = 'hidden';
  _presAudioEl = document.getElementById('presAudio');
  _presAudioEl.addEventListener('ended', presOnEnd);
  _presAudioEl.addEventListener('timeupdate', presOnTime);
  startBgAnim();
  showBlock(0);
}

function closePresentation() {
  document.getElementById('presentation').classList.remove('active');
  document.body.style.overflow = '';
  if (_presAudioEl) { _presAudioEl.pause(); _presAudioEl.src = ''; }
  if (_bgAnim) { cancelAnimationFrame(_bgAnim); _bgAnim = null; }
}

function buildProgress() {
  var wrap = document.getElementById('presProgress');
  wrap.innerHTML = '';
  _presBlocks.forEach(function(_, i) {
    var seg = document.createElement('div');
    seg.className = 'pres-seg'; seg.id = 'seg_' + i;
    seg.innerHTML = '<div class="pres-seg-fill" id="segfill_' + i + '"></div>';
    wrap.appendChild(seg);
  });
}

function showBlock(idx) {
  var block = _presBlocks[idx];
  if (!block) return;
  var theme = BLOCK_THEMES[block.key] || BLOCK_THEMES.today;

  document.getElementById('presTitle').textContent = block.title;
  document.getElementById('presIcon').textContent = block.icon;

  _presBlocks.forEach(function(_, i) {
    var seg = document.getElementById('seg_' + i);
    seg.className = 'pres-seg' + (i < idx ? ' done' : i === idx ? ' active' : '');
    document.getElementById('segfill_' + i).style.width = (i < idx ? '100%' : '0%');
  });

  var textEl = document.getElementById('presText');
  textEl.className = 'pres-text-card' + (block.key === 'warnings' ? ' warn-card' : '');
  textEl.innerHTML = blockTextToHtml(block.text || '');
  textEl.scrollTop = 0;

  _presAudioEl.pause();
  _presAudioEl.src = 'https://raw.githubusercontent.com/Ruslan591/weather-_Odessa/main/' + block.path + '?_=' + Date.now();
  _presAudioEl.load();
  document.getElementById('playBtn').textContent = '▶ Слушать';

  document.getElementById('prevBtn').disabled = (idx === 0);
  document.getElementById('nextBtn').disabled = (idx === _presBlocks.length - 1);

  drawBlockChart(block, theme);
  updateBgTheme(theme);
}

function blockTextToHtml(text) {
  text = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  text = text.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\*(.+?)\*/g,'<em>$1</em>');
  var parts = text.split(/\n\n+/);
  return parts.map(function(p){ return '<p>' + p.trim() + '</p>'; }).join('');
}

function presTogglePlay() {
  if (_presAudioEl.paused) {
    _presAudioEl.play();
    document.getElementById('playBtn').textContent = '⏸ Пауза';
  } else {
    _presAudioEl.pause();
    document.getElementById('playBtn').textContent = '▶ Слушать';
  }
}

function presNav(dir) {
  _presAudioEl.pause();
  var next = _presIdx + dir;
  if (next >= 0 && next < _presBlocks.length) {
    _presIdx = next;
    showBlock(_presIdx);
  }
}

function presOnEnd() {
  document.getElementById('playBtn').textContent = '▶ Слушать';
  var next = _presIdx + 1;
  if (next < _presBlocks.length) {
    _presIdx = next;
    showBlock(_presIdx);
    setTimeout(function() {
      _presAudioEl.play();
      document.getElementById('playBtn').textContent = '⏸ Пауза';
    }, 800);
  }
}

function presOnTime() {
  var dur = _presAudioEl.duration;
  if (!dur || isNaN(dur)) return;
  var pct = (_presAudioEl.currentTime / dur) * 100;
  var fill = document.getElementById('segfill_' + _presIdx);
  if (fill) fill.style.width = pct + '%';
}

// ── Графики ────────────────────────────────────────────────────────────────
function drawBlockChart(block, theme) {
  var wrap = document.getElementById('presChartWrap');
  var canvas = document.getElementById('presChart');
  canvas.width  = wrap.offsetWidth  || 340;
  canvas.height = wrap.offsetHeight || 160;
  var ctx = canvas.getContext('2d');
  var W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  var data = getChartData(block);
  if (!data) { wrap.classList.remove('visible'); return; }

  // Фон
  var bg = ctx.createLinearGradient(0,0,0,H);
  bg.addColorStop(0,'rgba(10,20,40,0.55)'); bg.addColorStop(1,'rgba(5,10,20,0.75)');
  ctx.fillStyle = bg;
  ctx.beginPath(); if(ctx.roundRect) ctx.roundRect(0,0,W,H,10); else ctx.rect(0,0,W,H); ctx.fill();

  var pad = {t:28, b:28, l:34, r:10};
  var cW = W-pad.l-pad.r, cH = H-pad.t-pad.b;
  var vals = data.values, xLabels = data.xLabels, n = vals.length;

  // Сетка
  ctx.strokeStyle = 'rgba(255,255,255,0.07)'; ctx.lineWidth = 1;
  for (var gi=0; gi<=3; gi++) {
    var gy = pad.t + (cH/3)*gi;
    ctx.beginPath(); ctx.moveTo(pad.l,gy); ctx.lineTo(W-pad.r,gy); ctx.stroke();
  }

  // Заголовок и единицы
  ctx.fillStyle = 'rgba(255,255,255,0.45)';
  ctx.font = '11px Helvetica Neue, sans-serif'; ctx.textAlign = 'left';
  ctx.fillText(data.label, pad.l, 16);

  // X-метки
  ctx.fillStyle = 'rgba(255,255,255,0.4)'; ctx.textAlign = 'center';
  for (var xi=0; xi<n; xi++) {
    ctx.fillText(xLabels[xi], pad.l + (n>1 ? (xi/(n-1))*cW : cW/2), H-8);
  }

  var validVals = vals.filter(function(v){ return v !== null; });
  if (!validVals.length) {
    ctx.fillStyle='rgba(255,255,255,0.2)'; ctx.textAlign='center'; ctx.font='13px sans-serif';
    ctx.fillText('Нет данных', W/2, H/2); return;
  }

  var minV = Math.min.apply(null,validVals)-2, maxV = Math.max.apply(null,validVals)+2;
  var range = maxV-minV || 1;
  function toY(v){ return pad.t + cH - ((v-minV)/range)*cH; }
  function toX(i){ return n>1 ? pad.l + (i/(n-1))*cW : pad.l+cW/2; }

  if (data.type === 'bar') {
    var bw = Math.min(40, (cW/n)*0.55);
    for (var bi=0; bi<n; bi++) {
      if (vals[bi]===null) continue;
      var bx = toX(bi)-bw/2, by = toY(vals[bi]), bh = (pad.t+cH)-by;
      var gr = ctx.createLinearGradient(0,by,0,pad.t+cH);
      gr.addColorStop(0,theme.accent); gr.addColorStop(1,theme.accent+'33');
      ctx.fillStyle = gr;
      ctx.beginPath(); if(ctx.roundRect) ctx.roundRect(bx,by,bw,bh,3); else ctx.rect(bx,by,bw,bh); ctx.fill();
      ctx.fillStyle='rgba(255,255,255,0.8)'; ctx.textAlign='center'; ctx.font='bold 11px sans-serif';
      ctx.fillText(Math.round(vals[bi]), bx+bw/2, by-4);
    }
  } else {
    // line
    ctx.strokeStyle=theme.accent; ctx.lineWidth=2.5; ctx.lineJoin='round';
    ctx.beginPath(); var started=false;
    for (var li=0; li<n; li++) {
      if (vals[li]===null) continue;
      if (!started){ ctx.moveTo(toX(li),toY(vals[li])); started=true; } else { ctx.lineTo(toX(li),toY(vals[li])); }
    }
    ctx.stroke();
    var ag=ctx.createLinearGradient(0,pad.t,0,pad.t+cH);
    ag.addColorStop(0,theme.accent+'44'); ag.addColorStop(1,theme.accent+'00');
    ctx.fillStyle=ag; ctx.beginPath(); started=false;
    for (var ai=0; ai<n; ai++) {
      if (vals[ai]===null) continue;
      if (!started){ ctx.moveTo(toX(ai),pad.t+cH); ctx.lineTo(toX(ai),toY(vals[ai])); started=true; } else { ctx.lineTo(toX(ai),toY(vals[ai])); }
    }
    if (n>1) ctx.lineTo(toX(n-1),pad.t+cH); ctx.closePath(); ctx.fill();
    for (var pi=0; pi<n; pi++) {
      if (vals[pi]===null) continue;
      ctx.fillStyle=theme.accent; ctx.beginPath(); ctx.arc(toX(pi),toY(vals[pi]),4,0,Math.PI*2); ctx.fill();
      ctx.fillStyle='#fff'; ctx.beginPath(); ctx.arc(toX(pi),toY(vals[pi]),2,0,Math.PI*2); ctx.fill();
      ctx.fillStyle='rgba(255,255,255,0.85)'; ctx.textAlign='center'; ctx.font='11px sans-serif';
      ctx.fillText(Math.round(vals[pi])+'°', toX(pi), toY(vals[pi])-8);
    }
  }
  ctx.textAlign='left';
  wrap.classList.add('visible');
}

function getChartData(block) {
  // Пытаемся извлечь данные из текста блока
  var text = block.text || '';
  if (block.key === 'today' || block.key === 'tomorrow') {
    return getTempRange(text, block.key);
  }
  if (block.key === 'next3') {
    return getNext3Data(text);
  }
  if (block.key === 'warnings') {
    return getWarningsData(text);
  }
  if (block.key === 'trend') {
    return getTrendData(text);
  }
  return null;
}

function getTempRange(text, key) {
  // Ищем ночь/день/ощущ
  var night=null, day=null, eve=null;
  var m;
  m = text.match(/(\d{1,2})[°\u00b0]\s*C\s*ночью|ночью\s*(-?\d{1,2})/i);
  if (m) night = parseInt(m[1]||m[2]);
  m = text.match(/(\d{1,2})[°\u00b0]\s*C\s*дн|дн[её]м\s*(\d{1,2})|до\s*(\d{1,2})[°\u00b0]\s*C/i);
  if (m) day = parseInt(m[1]||m[2]||m[3]);
  m = text.match(/вечером\s*(\d{1,2})|(\d{1,2})[°\u00b0]\s*C\s*вечером/i);
  if (m) eve = parseInt(m[1]||m[2]);
  // fallback: ищем min..max
  if (!day) {
    m = text.match(/(-?\d{1,2})\u2026(\d{1,2})|от\s+(-?\d{1,2}).*до\s+(\d{1,2})/);
    if (m) { night=parseInt(m[1]||m[3]); day=parseInt(m[2]||m[4]); }
  }
  var vals=[night,eve,day];
  var labels=['Ночь','Вечер','День'];
  if (!eve) { vals=[night,day]; labels=['Ночь','День']; }
  return { type:'bar', label:'\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 (\u00b0C)', xLabels:labels, values:vals };
}

function getNext3Data(text) {
  var nums=[], labels=['+2','+3','+4'];
  var re=/до\s+(\d{1,2})[°\u00b0]|(\d{1,2})\u2026(\d{1,2})/g, m;
  while((m=re.exec(text))!==null && nums.length<3) {
    if(m[1]) nums.push(parseInt(m[1]));
    else if(m[2]&&m[3]) nums.push((parseInt(m[2])+parseInt(m[3]))/2);
  }
  while(nums.length<3) nums.push(null);
  return { type:'bar', label:'\u041e\u0436\u0438\u0434\u0430\u0435\u043c\u0430\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 (\u00b0C)', xLabels:labels, values:nums };
}

function getWarningsData(text) {
  var cape=null, li=null;
  var mc=text.match(/CAPE[^\d]*(\d{2,4})/i); if(mc) cape=parseInt(mc[1]);
  var ml=text.match(/LI[^\d-]*(-?\d{1,2})/i); if(ml) li=Math.abs(parseInt(ml[1]))*100;
  if(!cape && !li) return null;
  return {
    type:'bar', label:'CAPE / |LI|×100',
    xLabels:['CAPE','|LI|×100'],
    values:[cape, li]
  };
}

function getTrendData(text) {
  var vals=[], re=/до\s+(\d{1,2})[°\u00b0]|(\d{1,2})\u2013(\d{1,2})[°\u00b0]/g, m;
  while((m=re.exec(text))!==null && vals.length<4) {
    if(m[1]) vals.push(parseInt(m[1]));
    else if(m[2]&&m[3]) vals.push((parseInt(m[2])+parseInt(m[3]))/2);
  }
  while(vals.length<4) vals.push(null);
  return { type:'line', label:'\u0422\u0435\u043d\u0434\u0435\u043d\u0446\u0438\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b (\u00b0C)', xLabels:['+1','+2','+3','+4'], values:vals };
}

// ── Анимированный фон ──────────────────────────────────────────────────────
var _bgTheme = BLOCK_THEMES.today;
var _bgParticles = [];

function updateBgTheme(t) { _bgTheme = t; }

function initParticles() {
  _bgParticles = [];
  for (var i=0; i<50; i++) {
    _bgParticles.push({
      x: Math.random(), y: Math.random(),
      r: Math.random()*1.5+0.5,
      vx: (Math.random()-.5)*0.0002, vy: (Math.random()-.5)*0.0002,
      a: Math.random()*0.5+0.1,
    });
  }
}

function startBgAnim() {
  initParticles();
  var canvas = document.getElementById('presBg');
  function frame() {
    var W=canvas.width=canvas.offsetWidth, H=canvas.height=canvas.offsetHeight;
    if (!W||!H) { _bgAnim=requestAnimationFrame(frame); return; }
    var ctx=canvas.getContext('2d');
    var g=ctx.createLinearGradient(0,0,0,H);
    g.addColorStop(0,_bgTheme.from); g.addColorStop(1,_bgTheme.to);
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
    _bgParticles.forEach(function(p) {
      p.x+=p.vx; p.y+=p.vy;
      if(p.x<0)p.x=1; if(p.x>1)p.x=0;
      if(p.y<0)p.y=1; if(p.y>1)p.y=0;
      var hex=Math.round(p.a*255).toString(16).padStart(2,'0');
      ctx.beginPath(); ctx.arc(p.x*W,p.y*H,p.r,0,Math.PI*2);
      ctx.fillStyle=_bgTheme.accent+hex; ctx.fill();
    });
    _bgAnim=requestAnimationFrame(frame);
  }
  _bgAnim=requestAnimationFrame(frame);
}

// Загружаем мета блоков сразу
loadBlocksMeta();
</script>'''

assert OLD_JS in src, "OLD_JS not found"
src = src.replace(OLD_JS, NEW_JS, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("ai_analysis.html patched OK")
print("Total size:", len(src), "chars")
