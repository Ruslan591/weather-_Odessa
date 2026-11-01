# -*- coding: utf-8 -*-
"""Stranica rezultatov WF-skanera. Slushaet TOLKO 127.0.0.1:18094 (kak drugie paneli; dostup cherez SSH-forward). Tolko chtenie sqlite."""
import os, json, time, sqlite3, statistics
from aiohttp import web
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("WF_DB") or os.path.join(HERE, "wfscan.db")
PORT = int(os.environ.get("WF_PORT") or 18094)
TFM = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720, "1d": 1440}
DAYS_DEF = {"1m": 30, "3m": 60, "5m": 120, "15m": 240, "30m": 360, "1h": 540, "2h": 720, "4h": 900, "6h": 1000, "8h": 1000, "12h": 1000, "1d": 1000}

def q(sql, args=()):
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10); c.row_factory = sqlite3.Row
    try: return [dict(r) for r in c.execute(sql, args)]
    finally: c.close()

def cur_run():
    r = q("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1"); return r[0] if r else None

async def api_state(req):
    run = cur_run()
    if not run: return web.json_response({"run": None})
    rid = run["run_id"]; pairs = json.loads(run["pairs"]); tfs = json.loads(run["tfs"]); days = json.loads(run["days"])
    rows = q("SELECT sym, tf, verdict, elapsed, rows FROM jobs WHERE run_id=?", (rid,))
    cnt = {}
    for r in rows: cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
    total = len(pairs) * len(tfs); done = len(rows)
    st = q("SELECT v FROM state WHERE k='current'"); cur = json.loads(st[0]["v"]) if st else None
    # otsenka ostavshegosya vremeni: mediana po TF; dlya TF bez dannyh - po sekundam na stroku
    by_tf = {}
    for r in rows:
        if r["elapsed"] and r["verdict"] != "ERR": by_tf.setdefault(r["tf"], []).append(r["elapsed"])
    tot_el = sum(r["elapsed"] or 0 for r in rows if r["verdict"] != "ERR"); tot_rows = sum(r["rows"] or 0 for r in rows if r["verdict"] != "ERR")
    rate = (tot_el / tot_rows) if tot_rows else None
    done_keys = {(r["sym"], r["tf"]) for r in rows}; eta = 0.0; ok_eta = True
    for tf in tfs:
        left = sum(1 for s in pairs if (s, tf) not in done_keys)
        if not left: continue
        if tf in by_tf: eta += left * statistics.median(by_tf[tf])
        elif rate: eta += left * rate * (days.get(tf, 100) * 1440 / TFM[tf])
        else: ok_eta = False
    return web.json_response({"run": run, "pairs": pairs, "tfs": tfs, "total": total, "done": done, "counts": cnt, "current": cur, "eta_s": (eta if ok_eta and run["status"] == "running" else None), "now": int(time.time() * 1000)})

async def api_rows(req):
    run = cur_run()
    if not run: return web.json_response([])
    return web.json_response(q("SELECT run_id,sym,tf,status,verdict,reason,oos_sum,oos_fee2,oos_n,ho_net,ho_n,ho_fee2,grid_oos_mean,grid_ho_mean,ho_pos_share,corr_mean,price_ho,t_days,rows,elapsed,finished_ms FROM jobs WHERE run_id=?", (run["run_id"],)))

async def api_job(req):
    run = cur_run()
    if not run: return web.json_response({})
    r = q("SELECT * FROM jobs WHERE run_id=? AND sym=? AND tf=?", (run["run_id"], req.query.get("sym", ""), req.query.get("tf", "")))
    if not r: return web.json_response({})
    r = r[0]; r["data"] = json.loads(r["data"]) if r["data"] else None
    return web.json_response(r)

async def index(req): return web.Response(text=HTML, content_type="text/html")

HTML = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WF-сканер</title>
<style>
:root{color-scheme:dark light;--bg:#14161a;--fg:#e6e6e6;--mut:#8b93a1;--card:#1d2026;--bd:#2c313a;--ok:#1f9d55;--bad:#c0392b;--nd:#59616e;--err:#b8860b}
@media (prefers-color-scheme:light){:root{--bg:#f5f6f8;--fg:#1b1e23;--mut:#5d6675;--card:#fff;--bd:#d6dae1}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.35 system-ui,sans-serif;padding:10px}
h1{font-size:16px;margin:0 0 6px}h2{font-size:14px;margin:14px 0 6px}.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:8px 10px;margin-bottom:8px}
.mut{color:var(--mut)}.bar{height:8px;background:var(--bd);border-radius:4px;overflow:hidden;margin:6px 0}.bar i{display:block;height:100%;background:var(--ok)}
.wrap{overflow-x:auto}table{border-collapse:collapse;white-space:nowrap}th,td{padding:3px 6px;border-bottom:1px solid var(--bd);text-align:right}th{cursor:pointer;color:var(--mut);position:sticky;top:0;background:var(--card)}td:first-child,th:first-child{text-align:left}
.m td,.m th{text-align:center;padding:2px 4px}.m td:first-child{text-align:left}.c{display:inline-block;min-width:22px;border-radius:4px;padding:1px 4px;color:#fff;cursor:pointer}
.PASS{background:var(--ok)}.FAIL{background:var(--bad)}.NODATA{background:var(--nd)}.ERR{background:var(--err)}.PEND{background:transparent;color:var(--mut);border:1px dashed var(--bd)}
.pos{color:#2ecc71}.neg{color:#e74c3c}select,input{background:var(--card);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:4px 6px;margin-right:4px}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;padding:10px;overflow:auto}#modal>div{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px;max-width:980px;margin:0 auto}
button{background:var(--card);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:4px 10px}
</style></head><body>
<h1>WF-сканер: подбор настроек Профиля (walk-forward)</h1>
<div class="card" id="st">загрузка…</div>
<div class="card"><b>Как читать.</b> Для каждой пары и таймфрейма история делится на 6 равных частей (u): три окна «подбор 2u → тест 1u» со сдвигом u и отложенный отрезок — последняя u (выбор по нему не делался).
Сетка из 48 настроек (ZigZag, стоп, RR, LVN, HVN), выбор по сумме net% на подборе (не меньше 6 сделок). <b>PASS</b>, если одновременно: сумма трёх тестов &gt; 0, плюс минимум в 2 из 3 тестов, то же при удвоенных издержках,
отложенный отрезок &gt; 0 (и при удвоенных издержках), и результат лучше среднего по сетке. <b>NODATA</b> — мало истории или меньше 25 сделок вне выборки. net% — сумма по закрытым сделкам, без плеча, комиссия 0.05% за сторону, проскальзывания нет.
<span class="mut">Внимание: проверок несколько сотен, часть PASS случайна — каждый PASS нужно перепроверять на новых данных.</span></div>
<h2>Матрица</h2><div class="card wrap"><table class="m" id="mx"></table></div>
<h2>Таблица</h2><div class="card"><div style="margin-bottom:6px">
<select id="fv"><option value="">все вердикты</option><option>PASS</option><option>FAIL</option><option>NODATA</option><option>ERR</option></select>
<select id="ft"><option value="">все ТФ</option></select><input id="fp" placeholder="пара" size="8"></div><div class="wrap"><table id="tb"></table></div></div>
<div id="modal"><div id="md"></div></div>
<script>
const TFS=["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"];let ROWS=[],ST=null,SORT=["finished_ms",-1];
const $=id=>document.getElementById(id);const f1=x=>x==null?"–":(x>0?"+":"")+Number(x).toFixed(1);const cls=x=>x==null?"":x>0?"pos":x<0?"neg":"";
const dt=ms=>new Date(ms).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
const hm=s=>s==null?"?":(s>=3600?Math.floor(s/3600)+" ч "+Math.round(s%3600/60)+" мин":Math.round(s/60)+" мин");
function el(t,a,txt){const e=document.createElement(t);if(a)for(const k in a)e.setAttribute(k,a[k]);if(txt!=null)e.textContent=txt;return e}
async function J(u){const r=await fetch(u);return r.json()}
async function load(){try{ST=await J("/api/state");ROWS=await J("/api/rows");draw()}catch(e){$("st").textContent="нет связи: "+e}}
function draw(){const s=ST;if(!s||!s.run){$("st").textContent="прогонов ещё нет";return}
 const c=s.counts||{},cu=s.current,p=Math.round(100*s.done/s.total);const box=$("st");box.textContent="";
 box.append(el("div",null,"Прогон #"+s.run.run_id+" ("+s.run.status+"), начат "+dt(s.run.started_ms)+". Готово "+s.done+" из "+s.total+" ("+p+"%). PASS "+(c.PASS||0)+" · FAIL "+(c.FAIL||0)+" · NODATA "+(c.NODATA||0)+" · ERR "+(c.ERR||0)));
 const b=el("div",{class:"bar"});b.append(el("i",{style:"width:"+p+"%"}));box.append(b);
 if(s.run.status==="running"&&cu&&cu.sym){const sec=Math.round((s.now-(cu.job_started||s.now))/1000);box.append(el("div",{class:"mut"},"Сейчас: "+cu.sym+" "+cu.tf+" — "+(cu.phase==="fetch"?"загрузка данных":"конфигурация "+cu.i+"/"+cu.n)+", "+sec+" с; оценка до конца: "+hm(s.eta_s)+" (грубо)"))}
 const age=cu&&cu.ts?Math.round((s.now-cu.ts)/1000):null;if(s.run.status==="running"&&age!=null&&age>900)box.append(el("div",{class:"neg"},"Нет обновлений "+hm(age)+" — проверь, что сканер работает"));
 const mx=$("mx");mx.textContent="";const hd=el("tr");hd.append(el("th",null,"пара"));TFS.filter(t=>s.tfs.includes(t)).forEach(t=>hd.append(el("th",null,t)));mx.append(hd);
 const idx={};ROWS.forEach(r=>idx[r.sym+"|"+r.tf]=r);
 s.pairs.forEach(sym=>{const tr=el("tr");tr.append(el("td",null,sym.replace("USDT","")));TFS.filter(t=>s.tfs.includes(t)).forEach(t=>{const r=idx[sym+"|"+t];const td=el("td");const v=r?r.verdict:"PEND";const sp=el("span",{class:"c "+v,title:r?(r.reason||""):"ожидает"},v==="PASS"?"P":v==="FAIL"?"F":v==="NODATA"?"–":v==="ERR"?"E":"·");if(r)sp.onclick=()=>show(sym,t);td.append(sp);tr.append(td)});mx.append(tr)});
 const ft=$("ft");if(ft.options.length<2)TFS.filter(t=>s.tfs.includes(t)).forEach(t=>ft.append(el("option",null,t)));
 table()}
const COLS=[["sym","пара"],["tf","ТФ"],["verdict","вердикт"],["oos_sum","тесты Σ"],["oos_fee2","тесты ×2 изд."],["oos_n","сделок"],["ho_net","отлож."],["ho_n","сд."],["ho_fee2","отлож. ×2"],["grid_oos_mean","сетка ср. тесты"],["grid_ho_mean","сетка ср. отлож."],["ho_pos_share","доля +"],["corr_mean","корр."],["price_ho","цена отлож. %"],["t_days","дней"],["elapsed","сек"]];
function table(){const v=$("fv").value,t=$("ft").value,p=$("fp").value.trim().toUpperCase();let rs=ROWS.filter(r=>(!v||r.verdict===v)&&(!t||r.tf===t)&&(!p||r.sym.includes(p)));
 const k=SORT[0],d=SORT[1];rs.sort((a,b)=>{const x=a[k],y=b[k];if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return(x>y?1:x<y?-1:0)*d});
 const tb=$("tb");tb.textContent="";const h=el("tr");COLS.forEach(c=>{const th=el("th",null,c[1]+(SORT[0]===c[0]?(SORT[1]>0?" ▲":" ▼"):""));th.onclick=()=>{SORT=[c[0],SORT[0]===c[0]?-SORT[1]:-1];table()};h.append(th)});tb.append(h);
 rs.slice(0,400).forEach(r=>{const tr=el("tr");COLS.forEach(c=>{const x=r[c[0]];const td=el("td");if(c[0]==="verdict"){const sp=el("span",{class:"c "+x,title:r.reason||""},x);sp.onclick=()=>show(r.sym,r.tf);td.append(sp)}else if(["oos_sum","oos_fee2","ho_net","ho_fee2","grid_oos_mean","grid_ho_mean","price_ho"].includes(c[0])){td.textContent=f1(x);td.className=cls(x)}else if(c[0]==="ho_pos_share"||c[0]==="corr_mean")td.textContent=x==null?"–":Number(x).toFixed(2);else if(c[0]==="elapsed")td.textContent=x==null?"–":Math.round(x);else td.textContent=x==null?"–":x;tr.append(td)});tb.append(tr)})}
["fv","ft","fp"].forEach(i=>$(i).addEventListener("input",table));
async function show(sym,tf){const r=await J("/api/job?sym="+encodeURIComponent(sym)+"&tf="+encodeURIComponent(tf));const m=$("md");m.textContent="";
 const x=el("button",null,"закрыть");x.onclick=()=>$("modal").style.display="none";m.append(x);m.append(el("h2",null,sym+" "+tf+" — "+r.verdict));m.append(el("div",{class:"mut"},r.reason||""));
 const d=r.data;if(!d){m.append(el("div",null,"подробностей нет"));$("modal").style.display="block";return}
 m.append(el("div",null,"история: "+d.T_days+" дн., единица окна u = "+d.u_days+" дн.; ZigZag A/B/C = "+Object.entries(d.zz).map(([k,v])=>k+":"+v.join("/")).join("  ")));
 const t1=el("table"),h1=el("tr");["окно","цена %","выбранная настройка","подбор Σ (сд.)","тест Σ (сд.)","тест ×2","корр.","сетка: ср./мед./доля+"].forEach(c=>h1.append(el("th",null,c)));t1.append(h1);
 d.folds.forEach((f,i)=>{const tr=el("tr");[["тест "+(i+1)],[f1(f.price)],[f.chosen||"—"],[f.tr?f1(f.tr[0])+" ("+f.tr[1]+")":"–"],[f.te?f1(f.te[0])+" ("+f.te[1]+")":"–"],[f.te2!=null?f1(f.te2):"–"],[f.corr!=null?f.corr.toFixed(2):"–"],[f1(f.grid.mean)+" / "+f1(f.grid.median)+" / "+Math.round(100*f.grid.share_pos)+"%"]].forEach((c,j)=>{const td=el("td",null,c[0]);if([4,5].includes(j)&&c[0]!=="–")td.className=cls(parseFloat(c[0]));tr.append(td)});t1.append(tr)});
 const F=d.final;if(F&&F.chosen){const tr=el("tr");[["отложен."],[f1(F.price)],[F.chosen],[f1(F.tr[0])+" ("+F.tr[1]+")"],[f1(F.ho[0])+" ("+F.ho[1]+")"],[f1(F.ho2)],["–"],[f1(F.grid.mean)+" / "+f1(F.grid.median)+" / "+Math.round(100*F.grid.share_pos)+"%"]].forEach((c,j)=>{const td=el("td",null,c[0]);if([4,5].includes(j))td.className=cls(parseFloat(c[0]));tr.append(td)});t1.append(tr)}
 const w1=el("div",{class:"wrap"});w1.append(t1);m.append(w1);
 if(F&&F.neigh){m.append(el("h2",null,"Соседние значения итоговой настройки (подбор / отложенный)"));const t=el("table");F.neigh.forEach(n=>{const tr=el("tr");tr.append(el("td",null,n[0]));const a=el("td",null,f1(n[1]));a.className=cls(n[1]);const b=el("td",null,f1(n[2]));b.className=cls(n[2]);tr.append(a);tr.append(b);t.append(tr)});const w=el("div",{class:"wrap"});w.append(t);m.append(w)}
 m.append(el("h2",null,"Вся сетка (net% по окнам; в скобках сделки)"));const t2=el("table"),h2=el("tr");["настройка","под.1","тест1","под.2","тест2","под.3","тест3","посл.подбор","отлож."].forEach(c=>h2.append(el("th",null,c)));t2.append(h2);
 d.grid.slice().sort((a,b)=>b.w[7][0]-a.w[7][0]).forEach(g=>{const tr=el("tr");tr.append(el("td",null,g.c));g.w.forEach(w=>{const td=el("td",null,f1(w[0])+" ("+w[1]+")");td.className=cls(w[0]);tr.append(td)});t2.append(tr)});const w2=el("div",{class:"wrap"});w2.append(t2);m.append(w2);
 $("modal").style.display="block"}
load();setInterval(load,20000);
</script></body></html>"""

app = web.Application()
app.add_routes([web.get("/", index), web.get("/api/state", api_state), web.get("/api/rows", api_rows), web.get("/api/job", api_job)])
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=PORT, print=lambda *a: print("wfscan panel on 127.0.0.1:%d" % PORT, flush=True))
