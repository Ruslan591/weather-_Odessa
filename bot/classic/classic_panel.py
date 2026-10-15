"""classic_panel.py — панель «классического» бота (localhost:18093).
Шаг 1: графики + то, что бот «видит» (тренд по ТФ, pivot, уровни, индикаторы, свечные паттерны). Торговли пока нет."""
import asyncio, json, os, re, time
import aiohttp
from aiohttp import web
import pandas as pd
import classic_analysis as an

PORT = 18093
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
TTL = {"1m": 5, "5m": 10, "15m": 15, "30m": 20, "1h": 30, "4h": 60, "1d": 120}
ALLTF = ["5m", "15m", "1h", "4h", "1d"]
MTF = ["1d", "4h", "1h", "15m", "5m"]
HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS_FILE = os.path.join(HERE, "pairs.json")
DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "ZECUSDT"]
CACHE, LOCKS = {}, {}
SES = None


def load_pairs():
    try:
        with open(PAIRS_FILE) as f:
            p = json.load(f)
            if isinstance(p, list) and p:
                return p
    except Exception:
        pass
    return list(DEFAULT_PAIRS)


def save_pairs(p):
    with open(PAIRS_FILE, "w") as f:
        json.dump(p, f)


async def get_df(sym, tf):
    key = (sym, tf)
    lock = LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        c = CACHE.get(key)
        if c and time.time() - c[0] < TTL.get(tf, 30):
            return c[1]
        data, err = None, None
        for base in BASES:
            try:
                async with SES.get(base + "/api/v3/klines", params={"symbol": sym, "interval": tf, "limit": 1000}) as r:
                    if r.status != 200:
                        raise RuntimeError("%s %s %s" % (base, r.status, (await r.text())[:120]))
                    data = await r.json()
                break
            except Exception as e:
                err = e
        if data is None:
            if c:
                return c[1]
            raise RuntimeError(str(err))
        df = pd.DataFrame(data).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
        df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
        for col in "ohlcv":
            df[col] = df[col].astype(float)
        df["t"] = df["t"].astype("int64")
        df["ct"] = df["ct"].astype("int64")
        CACHE[key] = (time.time(), df)
        return df


def split_closed(df):
    now = time.time() * 1000
    if len(df) and df.ct.iloc[-1] > now:
        return df.iloc[:-1].reset_index(drop=True), df.iloc[-1]
    return df.reset_index(drop=True), None


def ok_sym(s):
    return bool(s) and re.fullmatch(r"[A-Z0-9]{5,15}", s) is not None


async def api_chart(req):
    sym, tf = req.query.get("sym", "BTCUSDT").upper(), req.query.get("tf", "15m")
    if not ok_sym(sym) or tf not in ALLTF:
        return web.json_response({"error": "bad params"}, status=400)
    try:
        df = await get_df(sym, tf)
        closed, live = split_closed(df)
        res = an.analyze(closed)
        res["live"] = None if live is None else {k: float(live[k]) for k in "ohlcv"} | {"t": int(live.t)}
        res["sym"], res["tf"] = sym, tf
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"error": str(e)[:300]}, status=502)


async def api_mtf(req):
    sym = req.query.get("sym", "BTCUSDT").upper()
    if not ok_sym(sym):
        return web.json_response({"error": "bad params"}, status=400)
    async def one(tf):
        try:
            closed, _ = split_closed(await get_df(sym, tf))
            return dict(an.summary(closed), tf=tf)
        except Exception as e:
            return {"tf": tf, "error": str(e)[:100]}
    rows = await asyncio.gather(*[one(tf) for tf in MTF])
    return web.json_response({"sym": sym, "rows": rows})


async def api_pairs(req):
    p = load_pairs()
    if req.method == "POST":
        j = await req.json()
        if j.get("add"):
            s = str(j["add"]).upper().strip().replace("/", "")
            if not s.endswith("USDT") and not s.endswith("USDC") and not s.endswith("BTC"):
                s += "USDT"
            if not ok_sym(s):
                return web.json_response({"error": "плохое имя пары"}, status=400)
            try:
                await get_df(s, "1h")
            except Exception as e:
                return web.json_response({"error": "пара не найдена на Binance: " + str(e)[:100]}, status=400)
            if s not in p:
                p.append(s)
        if j.get("del") and j["del"] in p and len(p) > 1:
            p.remove(j["del"])
        save_pairs(p)
    return web.json_response({"pairs": p})


async def index(req):
    return web.Response(text=HTML, content_type="text/html")


async def on_start(app):
    global SES
    SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))


async def on_stop(app):
    await SES.close()


HTML = r'''<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1"><title>Classic bot</title>
<style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px system-ui,sans-serif}
.t{display:flex;flex-wrap:wrap;gap:4px;padding:4px 6px}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:4px 8px;font-size:12px}
button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
#info{padding:2px 8px;font:11.5px ui-monospace,monospace;min-height:30px;color:#8b949e}
canvas{display:block;width:100%;touch-action:none}
#legend{padding:2px 8px;font-size:11px;color:#8b949e}
.card{margin:6px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px}
.card h4{margin:0 0 6px;font-size:13px;color:#e6edf3}
table{border-collapse:collapse;width:100%}td,th{padding:3px 6px;text-align:right;border-bottom:1px solid #21262d;font-size:12px}
td:first-child,th:first-child{text-align:left}
.up{color:#26a69a}.dn{color:#ef5350}.fl{color:#8b949e}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-weight:600}
.badge.up{background:#12332f}.badge.dn{background:#3a1b1d}.badge.fl{background:#262c34}
ul{margin:4px 0 0;padding-left:18px}
</style></head><body>
<div class=t id=pairs></div><div class=t id=tfs></div><div class=t id=opts></div>
<div id=info>загрузка…</div><canvas id=c></canvas>
<div id=legend>Паттерны: Мол=молот · ПЗ=падающая звезда · П↑/П↓=поглощение · УЗ/ВЗ=утренняя/вечерняя звезда · Д=доджи. Треугольники — подтверждённые pivot (с задержкой 5 свечей). Пунктирная справа — формирующаяся свеча (в анализе не участвует).</div>
<div class=card id=cTrend></div><div class=card id=cMtf></div><div class=card id=cLv></div><div class=card id=cPat></div>
<script>
const TFS=['5m','15m','1h','4h','1d'];
const OPTN={ema:'EMA',bb:'Bollinger',lv:'Уровни',pv:'Pivot',pt:'Паттерны',vol:'Объём',rsi:'RSI',macd:'MACD'};
const S={sym:localStorage.csym||'BTCUSDT',tf:localStorage.ctf||'15m',n:120,off:0,hover:-1,D:null,pairs:[],
 opt:Object.assign({ema:1,bb:0,lv:1,pv:1,pt:1,vol:1,rsi:1,macd:0},JSON.parse(localStorage.copt||'{}'))};
const G={start:0,end:0,bw:5,L:4};
const $=id=>document.getElementById(id);
const cl=(x,a,b)=>Math.max(a,Math.min(b,x));
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:a>=0.1?5:7;return p.toFixed(d)}
function fts(t,tf,full){const d=new Date(t),p=n=>String(n).padStart(2,'0');
 const dm=p(d.getDate())+'.'+p(d.getMonth()+1),hm=p(d.getHours())+':'+p(d.getMinutes());
 return tf==='1d'?dm:(full?dm+' '+hm:hm)}
function mk(){
 $('tfs').innerHTML='';TFS.forEach(t=>{const b=document.createElement('button');b.textContent=t;if(t===S.tf)b.className='on';b.onclick=()=>{S.tf=t;localStorage.ctf=t;S.off=0;S.hover=-1;S.D=null;mk();load()};$('tfs').appendChild(b)});
 $('opts').innerHTML='';Object.keys(OPTN).forEach(k=>{const b=document.createElement('button');b.textContent=OPTN[k];if(S.opt[k])b.className='on';b.onclick=()=>{S.opt[k]=S.opt[k]?0:1;localStorage.copt=JSON.stringify(S.opt);mk();draw()};$('opts').appendChild(b)});
 $('pairs').innerHTML='';S.pairs.forEach(p=>{const b=document.createElement('button');b.textContent=p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;localStorage.csym=p;S.off=0;S.hover=-1;S.D=null;mk();load();loadMtf()};$('pairs').appendChild(b)});
 const a=document.createElement('button');a.textContent='+';a.onclick=async()=>{const s=prompt('Пара (например SOL или PEPEUSDT):');if(!s)return;const r=await fetch('/api/pairs',{method:'POST',body:JSON.stringify({add:s})});const j=await r.json();if(j.error){alert(j.error);return}S.pairs=j.pairs;S.sym=s.toUpperCase().replace('/','').match(/USDT|USDC|BTC$/)?s.toUpperCase().replace('/',''):s.toUpperCase()+'USDT';localStorage.csym=S.sym;S.D=null;mk();load();loadMtf()};$('pairs').appendChild(a);
 const d=document.createElement('button');d.textContent='−';d.onclick=async()=>{if(!confirm('Убрать '+S.sym+' из списка?'))return;const r=await fetch('/api/pairs',{method:'POST',body:JSON.stringify({del:S.sym})});const j=await r.json();S.pairs=j.pairs;S.sym=S.pairs[0];localStorage.csym=S.sym;S.D=null;mk();load();loadMtf()};$('pairs').appendChild(d);
}
async function load(){
 const key=S.sym+S.tf;
 try{const r=await fetch('/api/chart?sym='+S.sym+'&tf='+S.tf);const j=await r.json();
  if(j.error){$('info').textContent='Ошибка: '+j.error;return}
  if(key!==S.sym+S.tf)return;
  const pn=S.D&&S.D.sym===j.sym&&S.D.tf===j.tf?S.D.t.length:0;
  if(S.off>0&&pn&&j.t.length!==pn)S.off+=j.t.length-pn;
  S.D=j;draw();cards()}catch(e){$('info').textContent='Ошибка: '+e}
}
async function loadMtf(){
 try{const r=await fetch('/api/mtf?sym='+S.sym);const j=await r.json();if(j.sym!==S.sym)return;
  const nm={up:['up','ВВЕРХ ▲'],down:['dn','ВНИЗ ▼'],flat:['fl','БОКОВИК ▬']};
  let h='<h4>Тренд по таймфреймам · '+S.sym+'</h4><table><tr><th>ТФ</th><th>Тренд</th><th>Счёт</th><th>RSI</th><th>vs EMA50</th><th>ATR%</th></tr>';
  const dirs=[];
  j.rows.forEach(x=>{if(x.error){h+='<tr><td>'+x.tf+'</td><td colspan=5>'+x.error+'</td></tr>';return}
   dirs.push(x.dir);const n=nm[x.dir];h+='<tr><td>'+x.tf+'</td><td><span class="badge '+n[0]+'">'+n[1]+'</span></td><td>'+(x.score>0?'+':'')+x.score+'/'+x.max+'</td><td>'+x.rsi.toFixed(0)+'</td><td class="'+(x.vs50>=0?'up':'dn')+'">'+(x.vs50>=0?'+':'')+x.vs50.toFixed(2)+'%</td><td>'+x.atrp.toFixed(2)+'</td></tr>'});
  h+='</table>';
  const u=dirs.filter(d=>d==='up').length,d=dirs.filter(d=>d==='down').length;
  h+='<div style="margin-top:6px;color:#8b949e">'+(u===dirs.length?'Все ТФ вверх — согласованный рост':d===dirs.length?'Все ТФ вниз — согласованное падение':'ТФ расходятся: вверх '+u+', вниз '+d+', боковик '+(dirs.length-u-d))+'</div>';
  $('cMtf').innerHTML=h}catch(e){}
}
function cards(){
 const D=S.D;if(!D)return;const T=D.trend;const nm={up:['up','ВВЕРХ ▲'],down:['dn','ВНИЗ ▼'],flat:['fl','БОКОВИК ▬']}[T.dir];
 let h='<h4>Что бот видит на '+D.sym+' '+D.tf+'</h4><span class="badge '+nm[0]+'">'+nm[1]+'</span> счёт '+(T.score>0?'+':'')+T.score+'/'+T.max+' · структура '+T.struct+' · ATR '+fmt(D.atr)+'<ul>';
 T.why.forEach(w=>{h+='<li class="'+(w[0]==='+'?'up':w[0]==='−'?'dn':'fl')+'">'+w+'</li>'});h+='</ul>';$('cTrend').innerHTML=h;
 const lv=D.levels,p=D.last;const sup=lv.filter(x=>x.p<=p).sort((a,b)=>b.p-a.p),res=lv.filter(x=>x.p>p).sort((a,b)=>a.p-b.p);
 let l='<h4>Уровни (кластеры pivot)</h4><table><tr><th>Тип</th><th>Цена</th><th>Расст.</th><th>Касаний</th><th>Возраст</th></tr>';
 res.slice(0,5).reverse().forEach(x=>{l+='<tr><td class=dn>сопр.</td><td>'+fmt(x.p)+'</td><td>+'+x.dist.toFixed(2)+'%</td><td>'+x.n+'</td><td>'+x.age+' св.</td></tr>'});
 l+='<tr><td colspan=5 style="color:#e6edf3">▸ цена '+fmt(p)+'</td></tr>';
 sup.slice(0,5).forEach(x=>{l+='<tr><td class=up>подд.</td><td>'+fmt(x.p)+'</td><td>'+x.dist.toFixed(2)+'%</td><td>'+x.n+'</td><td>'+x.age+' св.</td></tr>'});
 $('cLv').innerHTML=l+'</table>';
 const N=D.t.length;let q='<h4>Последние свечные паттерны</h4>';
 const ps=D.patterns.slice(-8).reverse();
 q+=ps.length?'<table>'+ps.map(x=>'<tr><td>'+fts(D.t[x.i],D.tf,true)+'</td><td>'+x.n+'</td><td class="'+(x.d>0?'up':x.d<0?'dn':'fl')+'">'+(x.d>0?'бычий':x.d<0?'медвежий':'нейтр.')+'</td><td>'+(N-1-x.i)+' св. назад</td></tr>').join('')+'</table>':'нет';
 $('cPat').innerHTML=q;
}
function draw(){
 const D=S.D;if(!D)return;
 const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=Math.round(cl(window.innerHeight*0.62,380,660));
 cv.style.height=H+'px';cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
 const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
 const N=D.t.length,live=D.live,total=N+(live?1:0);
 const A=(k,i)=>i<N?D[k][i]:live[k];
 const L=4,R=60,B=16,plotW=W-L-R;
 S.n=cl(S.n,20,500);S.off=cl(S.off,0,Math.max(0,total-20));
 const end=total-S.off,start=Math.max(0,end-S.n),cnt=end-start,slots=cnt+(S.off===0?3:0),bw=plotW/slots;
 G.start=start;G.end=end;G.bw=bw;G.L=L;
 const X=i=>L+(i-start+0.5)*bw;
 const panes=[{id:'main',w:5}];if(S.opt.vol)panes.push({id:'vol',w:1});if(S.opt.rsi)panes.push({id:'rsi',w:1.5});if(S.opt.macd)panes.push({id:'macd',w:1.5});
 const tw=panes.reduce((a,p)=>a+p.w,0),avail=H-B;let y=0;panes.forEach(p=>{p.y0=y;p.y1=y+avail*p.w/tw;y=p.y1});
 const P={};panes.forEach(p=>P[p.id]=p);
 g.font='10px system-ui';g.textBaseline='middle';
 // pane borders + labels
 panes.forEach((p,k)=>{if(k>0){g.strokeStyle='#30363d';g.beginPath();g.moveTo(0,p.y0+.5);g.lineTo(W,p.y0+.5);g.stroke()}});
 // ---- main
 const m=P.main;let hi=-1e99,lo=1e99;for(let i=start;i<end;i++){hi=Math.max(hi,A('h',i));lo=Math.min(lo,A('l',i))}
 const pad=(hi-lo)*0.05||hi*0.01;hi+=pad;lo-=pad;
 const py=p=>m.y0+6+(hi-p)/(hi-lo)*(m.y1-m.y0-12);
 g.strokeStyle='#1b222c';g.fillStyle='#6e7681';g.textAlign='left';
 for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5,yy=py(p);g.beginPath();g.moveTo(L,yy);g.lineTo(L+plotW,yy);g.stroke();g.fillText(fmt(p),L+plotW+4,yy)}
 // levels
 if(S.opt.lv)D.levels.forEach(x=>{if(x.p<lo||x.p>hi)return;const c=x.k==='S'?'38,166,154':'239,83,80';
  const y1=py(Math.min(x.hi,hi)),y2=py(Math.max(x.lo,lo));g.fillStyle='rgba('+c+',0.10)';g.fillRect(L,y1,plotW,Math.max(2,y2-y1));
  g.strokeStyle='rgba('+c+',0.7)';g.lineWidth=1;g.setLineDash(x.n>=3?[]:[4,3]);g.beginPath();g.moveTo(L,py(x.p));g.lineTo(L+plotW,py(x.p));g.stroke();g.setLineDash([]);
  g.fillStyle='rgba('+c+',0.95)';g.textAlign='left';g.fillText('×'+x.n,L+3,py(x.p)-5)});
 // bollinger
 if(S.opt.bb){g.fillStyle='rgba(88,166,255,0.07)';g.beginPath();let st=false;
  for(let i=start;i<Math.min(end,N);i++){if(D.bbu[i]==null)continue;const x=X(i),yy=py(D.bbu[i]);if(!st){g.moveTo(x,yy);st=true}else g.lineTo(x,yy)}
  for(let i=Math.min(end,N)-1;i>=start;i--){if(D.bbl[i]==null)continue;g.lineTo(X(i),py(D.bbl[i]))}g.closePath();g.fill();
  ['bbu','bbm','bbl'].forEach(k=>line(D[k],'rgba(88,166,255,'+(k==='bbm'?0.35:0.7)+')',1))}
 function line(arr,col,w){g.strokeStyle=col;g.lineWidth=w||1.2;g.beginPath();let on=false;
  for(let i=start;i<Math.min(end,N);i++){const v=arr[i];if(v==null){on=false;continue}const x=X(i),yy=py(v);if(!on){g.moveTo(x,yy);on=true}else g.lineTo(x,yy)}g.stroke();g.lineWidth=1}
 // candles
 for(let i=start;i<end;i++){const o=A('o',i),h=A('h',i),l=A('l',i),c=A('c',i),x=X(i),up=c>=o,col=up?'#26a69a':'#ef5350',bwid=Math.max(1,bw*0.7),isl=i>=N;
  g.strokeStyle=col;g.fillStyle=col;if(isl)g.globalAlpha=0.55;g.beginPath();g.moveTo(x,py(h));g.lineTo(x,py(l));g.stroke();
  const y1=py(Math.max(o,c)),y2=py(Math.min(o,c));if(isl){g.strokeRect(x-bwid/2,y1,bwid,Math.max(1,y2-y1))}else g.fillRect(x-bwid/2,y1,bwid,Math.max(1,y2-y1));g.globalAlpha=1}
 // ema
 if(S.opt.ema){line(D.ema20,'#e3b341',1.2);line(D.ema50,'#58a6ff',1.2);line(D.ema200,'#bc8cff',1.4)}
 // pivots
 if(S.opt.pv)D.pivots.forEach(p=>{if(p.i<start||p.i>=end)return;const x=X(p.i);g.fillStyle=p.k==='H'?'#f0883e':'#79c0ff';g.beginPath();
  if(p.k==='H'){const yy=py(D.h[p.i])-5;g.moveTo(x-3.5,yy-5);g.lineTo(x+3.5,yy-5);g.lineTo(x,yy)}else{const yy=py(D.l[p.i])+5;g.moveTo(x-3.5,yy+5);g.lineTo(x+3.5,yy+5);g.lineTo(x,yy)}g.fill()});
 // patterns
 if(S.opt.pt){g.textAlign='center';g.font='bold 9px system-ui';D.patterns.forEach(p=>{if(p.i<start||p.i>=end)return;const x=X(p.i);
  const col=p.d>0?'#3fb950':p.d<0?'#f85149':'#8b949e';g.fillStyle=col;
  if(p.d>0)g.fillText('▲'+p.c,x,py(D.l[p.i])+(S.opt.pv?24:14));else g.fillText(p.c+(p.d<0?'▼':''),x,py(D.h[p.i])-(S.opt.pv?24:14))});g.font='10px system-ui'}
 // last price
 const lp=live?live.c:D.c[N-1],lc=lp>=(live?live.o:D.o[N-1])?'#26a69a':'#ef5350';
 if(lp>=lo&&lp<=hi){g.strokeStyle=lc;g.setLineDash([2,3]);g.beginPath();g.moveTo(L,py(lp));g.lineTo(L+plotW,py(lp));g.stroke();g.setLineDash([]);
  g.fillStyle=lc;g.fillRect(L+plotW+1,py(lp)-7,R-2,14);g.fillStyle='#fff';g.textAlign='left';g.fillText(fmt(lp),L+plotW+4,py(lp))}
 // ---- volume
 if(P.vol){const p=P.vol;let mv=0;for(let i=start;i<end;i++)mv=Math.max(mv,A('v',i));
  for(let i=start;i<end;i++){const up=A('c',i)>=A('o',i),h=(A('v',i)/mv)*(p.y1-p.y0-8);g.fillStyle=up?'rgba(38,166,154,.55)':'rgba(239,83,80,.55)';g.fillRect(X(i)-Math.max(1,bw*0.7)/2,p.y1-h,Math.max(1,bw*0.7),h)}
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('Vol',6,p.y0+10)}
 // ---- rsi
 if(P.rsi){const p=P.rsi,ry=v=>p.y0+4+(100-v)/100*(p.y1-p.y0-8);
  g.strokeStyle='#30363d';g.setLineDash([3,3]);[30,70].forEach(v=>{g.beginPath();g.moveTo(L,ry(v));g.lineTo(L+plotW,ry(v));g.stroke()});g.setLineDash([]);
  g.strokeStyle='#d2a8ff';g.lineWidth=1.3;g.beginPath();let on=false;for(let i=start;i<Math.min(end,N);i++){const v=D.rsi[i];if(v==null)continue;const x=X(i);if(!on){g.moveTo(x,ry(v));on=true}else g.lineTo(x,ry(v))}g.stroke();g.lineWidth=1;
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('RSI14',6,p.y0+10);g.fillText('70',L+plotW+4,ry(70));g.fillText('30',L+plotW+4,ry(30))}
 // ---- macd
 if(P.macd){const p=P.macd;let mx=1e-12;for(let i=start;i<Math.min(end,N);i++){[D.macd[i],D.sig[i],D.hist[i]].forEach(v=>{if(v!=null)mx=Math.max(mx,Math.abs(v))})}
  const my=v=>p.y0+4+(1-v/mx)/2*(p.y1-p.y0-8);g.strokeStyle='#30363d';g.beginPath();g.moveTo(L,my(0));g.lineTo(L+plotW,my(0));g.stroke();
  for(let i=start;i<Math.min(end,N);i++){const v=D.hist[i];if(v==null)continue;g.fillStyle=v>=0?'rgba(38,166,154,.6)':'rgba(239,83,80,.6)';const a=my(v),b=my(0);g.fillRect(X(i)-Math.max(1,bw*0.7)/2,Math.min(a,b),Math.max(1,bw*0.7),Math.abs(a-b))}
  [['macd','#58a6ff'],['sig','#f0883e']].forEach(([k,c])=>{g.strokeStyle=c;g.beginPath();let on=false;for(let i=start;i<Math.min(end,N);i++){const v=D[k][i];if(v==null)continue;const x=X(i);if(!on){g.moveTo(x,my(v));on=true}else g.lineTo(x,my(v))}g.stroke()});
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('MACD',6,p.y0+10)}
 // ---- time axis
 g.fillStyle='#6e7681';g.textAlign='center';g.textBaseline='middle';const step=Math.max(1,Math.round(cnt/6));let lastDay=-1;
 for(let i=start;i<Math.min(end,N);i+=step){const t=D.t[i],d=new Date(t).getDate();g.fillText(fts(t,D.tf,d!==lastDay&&D.tf!=='1d'),X(i),H-7);lastDay=d}
 // ---- crosshair
 let hv=S.hover;if(hv>=start&&hv<end){const x=X(hv);g.strokeStyle='rgba(201,209,217,.4)';g.setLineDash([3,3]);g.beginPath();g.moveTo(x,0);g.lineTo(x,H-B);g.stroke();g.setLineDash([])}else hv=-1;
 info(hv>=0?hv:total-1);
}
function info(i){
 const D=S.D,N=D.t.length,live=D.live,isl=i>=N;const A=(k)=>isl?live[k]:D[k][i];
 const o=A('o'),h=A('h'),l=A('l'),c=A('c'),v=A('v'),ch=(c/o-1)*100;
 let s=D.sym+' '+D.tf+' '+fts(isl?live.t:D.t[i],D.tf,true)+(isl?' (live)':'')+'  O '+fmt(o)+' H '+fmt(h)+' L '+fmt(l)+' C '+fmt(c)+' ('+(ch>=0?'+':'')+ch.toFixed(2)+'%)  V '+v.toFixed(0);
 if(!isl){s+='  | EMA20 '+fmt(D.ema20[i])+' EMA50 '+fmt(D.ema50[i])+' EMA200 '+fmt(D.ema200[i])+' RSI '+(D.rsi[i]!=null?D.rsi[i].toFixed(1):'—');
  const ps=D.patterns.filter(p=>p.i===i);if(ps.length)s+='  | '+ps.map(p=>p.n).join(', ')}
 $('info').textContent=s;
}
// ---- interaction
const cv=$('c'),ptrs=new Map();let sx=0,so=0,moved=false,p0=0,pn=0;
const idxAt=x=>{const r=cv.getBoundingClientRect();return cl(G.start+Math.floor((x-r.left-G.L)/G.bw),G.start,G.end-1)};
cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
 if(ptrs.size===1){sx=e.clientX;so=S.off;moved=false}else if(ptrs.size===2){const a=[...ptrs.values()];p0=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);pn=S.n}});
cv.addEventListener('pointermove',e=>{
 if(!ptrs.has(e.pointerId)){if(e.pointerType==='mouse'&&S.D){S.hover=idxAt(e.clientX);draw()}return}
 ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
 if(ptrs.size===2){const a=[...ptrs.values()],d=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);S.n=cl(Math.round(pn*p0/Math.max(d,1)),20,500);moved=true;draw();return}
 const dx=e.clientX-sx;if(Math.abs(dx)>4)moved=true;if(moved){S.off=Math.round(so+dx/G.bw);draw()}});
const up=e=>{if(ptrs.size===1&&!moved&&S.D){S.hover=idxAt(e.clientX);draw()}ptrs.delete(e.pointerId)};
cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',e=>ptrs.delete(e.pointerId));
cv.addEventListener('wheel',e=>{e.preventDefault();S.n=cl(Math.round(S.n*(e.deltaY>0?1.15:0.87)),20,500);draw()},{passive:false});
window.addEventListener('resize',draw);
(async()=>{try{const r=await fetch('/api/pairs');S.pairs=(await r.json()).pairs;if(!S.pairs.includes(S.sym))S.sym=S.pairs[0]}catch(e){S.pairs=[S.sym]}
 mk();load();loadMtf();setInterval(load,10000);setInterval(loadMtf,60000)})();
</script></body></html>'''


def main():
    app = web.Application()
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.router.add_get("/", index)
    app.router.add_get("/api/chart", api_chart)
    app.router.add_get("/api/mtf", api_mtf)
    app.router.add_route("*", "/api/pairs", api_pairs)
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
