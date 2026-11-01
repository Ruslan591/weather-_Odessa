# -*- coding: utf-8 -*-
"""WF-skaner: walk-forward podbor nastroek Profilya (VP) po spisku par x vsem tajmframam. Rezultaty -> sqlite, stranica: wfscan_panel.py.
Zapusk: python wfscan.py [--new]   (bez --new prodolzhaet nezavershennyj progon). Smoke: WF_SMOKE=1 WF_DB=/tmp/smoke.db python wfscan.py
Metodika (kak scripts/wf_pha.py): okna proporcionalno istorii: S..S+6u; folds k=0..2: podbor [S+uk, S+u(k+2)) -> test [S+u(k+2), S+u(k+3)); otlozhennyj otrezok [S+5u, S+6u];
final'nyj vybor po [S+3u, S+5u). Setka 48 konfiguracij, kriterij vybora - summa net% pri >= MINN sdelok. Ne dotragivaetsya k zhivym botam: tolko chtenie koda classic_strategy/classic_vp."""
import sys, os, json, time, math, sqlite3, asyncio, itertools, pickle, traceback, statistics
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd, aiohttp
import classic_strategy as cs, classic_vp as vpm

HERE = os.path.dirname(os.path.abspath(__file__))
SMOKE = bool(os.environ.get("WF_SMOKE"))
DB = os.environ.get("WF_DB") or os.path.join(HERE, "wfscan.db")
CACHE = os.path.join(HERE, "cache_smoke" if SMOKE else "cache"); os.makedirs(CACHE, exist_ok=True)
BASE = json.load(open(os.path.join(HERE, "base_cfg.json")))
DAY = 86400000
PAIRS = ["PHAUSDT", "REZUSDT", "TREEUSDT", "IOSTUSDT", "ANIMEUSDT", "BMTUSDT", "CHIPUSDT", "ERAUSDT", "HAEDALUSDT", "KORUBUSDT", "NILUSDT", "SOXLBUSDT",
         "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "NEARUSDT", "ZECUSDT"]
TFS = ["15m", "5m", "1h", "30m", "4h", "2h", "6h", "8h", "12h", "1d", "3m", "1m"]  # poryadok obrabotki (TF-major)
DAYS = {"1m": 30, "3m": 60, "5m": 120, "15m": 240, "30m": 360, "1h": 540, "2h": 720, "4h": 900, "6h": 1000, "8h": 1000, "12h": 1000, "1d": 1000}
if SMOKE: PAIRS, TFS = ["PHAUSDT"], ["1d", "4h", "1m"]
TFM = cs.TF_MIN
MINN = 6; WARM = 600; JOB_CAP = 45 * 60; PACE = 0.8; MIN_TOTAL_TRADES = 25
BASEURL = "https://data-api.binance.vision"  # tolko ryn. dannye; api.binance.com ne trogaem - tam ves zhivogo bota

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

# ---------- sqlite ----------
def db():
    c = sqlite3.connect(DB, timeout=30); c.execute("PRAGMA journal_mode=WAL"); return c
def init_db():
    c = db()
    c.executescript("""CREATE TABLE IF NOT EXISTS runs(run_id INTEGER PRIMARY KEY, started_ms INTEGER, now_ms INTEGER, status TEXT, pairs TEXT, tfs TEXT, days TEXT);
    CREATE TABLE IF NOT EXISTS jobs(run_id INTEGER, sym TEXT, tf TEXT, status TEXT, verdict TEXT, reason TEXT, oos_sum REAL, oos_fee2 REAL, oos_n INTEGER, ho_net REAL, ho_n INTEGER, ho_fee2 REAL,
      grid_oos_mean REAL, grid_ho_mean REAL, ho_pos_share REAL, corr_mean REAL, price_ho REAL, t_days REAL, rows INTEGER, elapsed REAL, finished_ms INTEGER, data TEXT, PRIMARY KEY(run_id, sym, tf));
    CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);""")
    c.commit(); return c
def set_state(c, **kw):
    kw["ts"] = int(time.time() * 1000)
    c.execute("INSERT OR REPLACE INTO state VALUES('current', ?)", (json.dumps(kw),)); c.commit()

# ---------- dannye ----------
class Ban(Exception): pass
class BadSym(Exception): pass
async def http_get(ses, params):
    async with ses.get(BASEURL + "/api/v3/klines", params=params) as r:
        w = r.headers.get("x-mbx-used-weight-1m")
        if r.status in (418, 429): raise Ban(int(r.headers.get("Retry-After") or 120))
        if r.status == 400: raise BadSym((await r.text())[:100])
        if r.status != 200: raise RuntimeError("HTTP %s" % r.status)
        return await r.json(), (int(w) if w and w.isdigit() else 0)

async def fetch_df(sym, tf, start_ms, end_ms):
    tfms = TFM[tf] * 60000; out = []; cur = start_ms; fails = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as ses:
        while cur < end_ms:
            try:
                data, w = await http_get(ses, {"symbol": sym, "interval": tf, "startTime": cur, "endTime": end_ms, "limit": 1000})
            except Ban as b:
                wait = min(3600, int(b.args[0]) + 5); log("Binance prosit pauzu %ds (%s %s)" % (wait, sym, tf)); await asyncio.sleep(wait); continue
            except BadSym: raise
            except Exception as e:
                fails += 1
                if fails >= 4: raise
                await asyncio.sleep(10 * fails); continue
            fails = 0
            if not data: break
            out += data; cur = int(data[-1][0]) + tfms
            if w >= 2400: await asyncio.sleep(65)
            if len(data) < 1000: break
            await asyncio.sleep(PACE)
    if not out: raise RuntimeError("no klines")
    df = pd.DataFrame(out).iloc[:, [0, 1, 2, 3, 4, 5, 6]]; df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for col in "ohlcv": df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df[df["ct"] < end_ms].drop_duplicates("t").reset_index(drop=True)

def get_df(run_id, sym, tf, now_ms):
    fp = os.path.join(CACHE, "%d_%s_%s.pkl" % (run_id, sym, tf))
    if os.path.exists(fp):
        try: return pickle.load(open(fp, "rb"))
        except Exception: pass
    start = now_ms - DAYS[tf] * DAY - WARM * TFM[tf] * 60000 - 5 * TFM[tf] * 60000
    df = asyncio.run(fetch_df(sym, tf, start, now_ms))
    pickle.dump(df, open(fp, "wb")); return df

# ---------- setka ----------
def zz_axis(tf):
    tfm = TFM[tf]
    if tf in vpm.ZZ_DEF: dp, dv, bk = vpm.ZZ_DEF[tf]
    else:
        dv = round(0.6 * math.sqrt(tfm / 5.0), 2); dp, bk = (12, 3) if tfm <= 5 else (8, 2)
    return {"A": (dp, round(0.33 * dv, 2), bk), "B": (dp, dv, bk), "C": (int(round(1.5 * dp)), round(0.67 * dv, 2), bk)}
AX = dict(zz=["A", "B", "C"], sl=[1.0, 2.0], rr=[2.0, 3.0], lvn=[0.35, 0.5], hvn=[1.5, 3.0])
GRID = list(itertools.product(AX["zz"], AX["sl"], AX["rr"], AX["lvn"], AX["hvn"]))
if SMOKE: GRID = GRID[::12]
cname = lambda c: "zz%s sl%.1f rr%.1f lvn%.2f hvn%.1f" % c
def over(c, zz):
    k, sl, rr, lvn, hvn = c; dp, dv, bk = zz[k]
    return dict(zz_depth=dp, zz_dev=dv, zz_back=bk, vp_sl_atr=sl, vp_rr=rr, vp_lvn=lvn, vp_hvn=hvn)

def rk(a): return pd.Series(a).rank().values
def spear(a, b):
    if len(a) < 5 or np.std(a) == 0 or np.std(b) == 0: return None
    return float(np.corrcoef(rk(a), rk(b))[0, 1])

class Cap(Exception): pass

def run_job(c_db, run_id, sym, tf, df, now_ms, idx_info):
    tfms = TFM[tf] * 60000; days = DAYS[tf]; first = int(df["t"].iloc[0])
    S = max(now_ms - days * DAY, first + WARM * tfms); T = now_ms - S
    base_row = dict(rows=len(df), t_days=round(T / DAY, 1))
    if T < 0.3 * days * DAY:
        return dict(base_row, status="NODATA", verdict="NODATA", reason="история короткая: %.0f из %d дней" % (T / DAY, days))
    u = T / 6.0
    folds = [(S + u * k, S + u * (k + 2), S + u * (k + 3)) for k in range(3)]
    HO = S + u * 5; LT = (S + u * 3, HO)
    i0 = int(np.searchsorted(df["t"].values, S)); sub = df.iloc[max(0, i0 - 1000):].reset_index(drop=True)
    zz = zz_axis(tf)
    def px(ms):
        i = min(int(np.searchsorted(df["t"].values, ms)), len(df) - 1); return float(df["c"].values[i])
    def sim(ov, fee=None):
        P = dict(cs.PARAMS, **dict(BASE, **ov, sym=sym, tf=tf)); P["sim_from_ms"] = int(S)
        if fee is not None: P["fee"] = fee
        trs = cs.simulate(sub, now_ms, P)
        return [(x["t_in"], x["net"]) for x in trs if not x["open"]]
    def win(trs, a, b):
        sel = [n for (t, n) in trs if a <= t < b]; return round(sum(sel), 2), len(sel)
    RES = {}; t0 = time.time()
    for i, c in enumerate(GRID):
        RES[c] = sim(over(c, zz))
        if i % 4 == 3 or i == len(GRID) - 1:
            set_state(c_db, run_id=run_id, sym=sym, tf=tf, phase="grid", i=i + 1, n=len(GRID), job_started=int(t0 * 1000), idx=idx_info)
        if time.time() - t0 > JOB_CAP: raise Cap("лимит времени %d мин" % (JOB_CAP // 60))
    fold_out = []; oos = []; oos2 = []; corrs = []; chosen = []; grid_oos = 0.0
    for k, (a, b, e) in enumerate(folds):
        tr = {c: win(RES[c], a, b) for c in GRID}; te = {c: win(RES[c], b, e) for c in GRID}
        ok = [c for c in GRID if tr[c][1] >= MINN]; arr = np.array([te[c][0] for c in GRID]); grid_oos += float(arr.mean())
        f = dict(train=[a, b], test=[b, e], price=round((px(e) / px(b) - 1) * 100, 1), grid=dict(mean=round(float(arr.mean()), 2), median=round(float(np.median(arr)), 2), share_pos=round(float((arr > 0).mean()), 2)))
        if ok:
            best = max(ok, key=lambda c: tr[c][0]); f.update(chosen=cname(best), tr=list(tr[best]), te=list(te[best]))
            f["corr"] = spear([tr[c][0] for c in ok], [te[c][0] for c in ok]); corrs.append(f["corr"]); chosen.append(best); oos.append(te[best][0])
            t2 = sim(over(best, zz), fee=2 * float(BASE.get("fee", 0.05))); f["te2"] = win(t2, b, e)[0]; oos2.append(f["te2"])
        fold_out.append(f)
    tr = {c: win(RES[c], *LT) for c in GRID}; ok = [c for c in GRID if tr[c][1] >= MINN]
    fin = dict(window=[LT[0], now_ms], price=round((px(now_ms) / px(HO) - 1) * 100, 1))
    hoall = np.array([win(RES[c], HO, now_ms + DAY)[0] for c in GRID])
    fin["grid"] = dict(mean=round(float(hoall.mean()), 2), median=round(float(np.median(hoall)), 2), share_pos=round(float((hoall > 0).mean()), 2))
    ho_net = ho_n = ho2 = None
    if ok:
        best = max(ok, key=lambda c: tr[c][0]); hn = win(RES[best], HO, now_ms + DAY); ho_net, ho_n = hn
        ho2 = win(sim(over(best, zz), fee=2 * float(BASE.get("fee", 0.05))), HO, now_ms + DAY)[0]
        neigh = []
        for ai in range(5):
            for v in (AX["zz"], AX["sl"], AX["rr"], AX["lvn"], AX["hvn"])[ai]:
                if v == best[ai]: continue
                nb = list(best); nb[ai] = v; nb = tuple(nb)
                if nb not in RES: continue  # (v smoke-rezhime setka urezana)
                neigh.append([cname(nb), win(RES[nb], *LT)[0], win(RES[nb], HO, now_ms + DAY)[0]])
        fin.update(chosen=cname(best), tr=list(tr[best]), ho=[ho_net, ho_n], ho2=ho2, neigh=neigh)
    grid_tab = [dict(c=cname(c), w=[list(win(RES[c], a, b)) for (a, b, e) in folds for (a, b) in ((a, b), (b, e))] + [list(win(RES[c], *LT)), list(win(RES[c], HO, now_ms + DAY))]) for c in GRID]
    data = dict(S=int(S), T_days=round(T / DAY, 1), u_days=round(u / DAY, 1), zz={k: list(v) for k, v in zz.items()}, folds=fold_out, final=fin, grid=grid_tab,
                grid_order="w = [train1,test1,train2,test2,train3,test3,last_train,holdout], each [net%,n]")
    out = dict(base_row, data=data, status="OK", price_ho=fin["price"], grid_oos_mean=round(grid_oos, 2), grid_ho_mean=fin["grid"]["mean"], ho_pos_share=fin["grid"]["share_pos"],
               corr_mean=(round(float(np.mean([x for x in corrs if x is not None])), 2) if [x for x in corrs if x is not None] else None))
    if len(oos) < 3 or ho_net is None:
        return dict(out, verdict="NODATA", reason="в одном из окон подбора меньше %d сделок: выбирать не из чего" % MINN)
    oos_sum = round(sum(oos), 2); oos_fee2 = round(sum(oos2), 2); n_oos = sum(f["te"][1] for f in fold_out) + ho_n
    out.update(oos_sum=oos_sum, oos_fee2=oos_fee2, oos_n=n_oos, ho_net=ho_net, ho_n=ho_n, ho_fee2=ho2)
    if n_oos < MIN_TOTAL_TRADES: return dict(out, verdict="NODATA", reason="мало сделок вне выборки: %d < %d" % (n_oos, MIN_TOTAL_TRADES))
    fails = []
    if not oos_sum > 0: fails.append("сумма тестов не больше 0")
    if sum(1 for x in oos if x > 0) < 2: fails.append("плюс меньше чем в 2 из 3 тестов")
    if not oos_fee2 > 0: fails.append("при удвоенных издержках тесты не больше 0")
    if not ho_net > 0: fails.append("отложенный отрезок не больше 0")
    if not ho2 > 0: fails.append("отложенный при удвоенных издержках не больше 0")
    if not oos_sum > grid_oos: fails.append("не лучше средней конфигурации сетки")
    return dict(out, verdict=("PASS" if not fails else "FAIL"), reason=("; ".join(fails) if fails else "все критерии выполнены"))

# ---------- osnovnoj cikl ----------
def main():
    c = init_db(); new = "--new" in sys.argv
    row = c.execute("SELECT run_id, now_ms FROM runs WHERE status='running' ORDER BY run_id DESC LIMIT 1").fetchone()
    if row and not new: run_id, now_ms = row; log("prodolzhaem progon", run_id)
    else:
        if row: c.execute("UPDATE runs SET status='aborted' WHERE status='running'")
        now_ms = int(time.time() * 1000); run_id = int(time.time())
        c.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, now_ms, now_ms, "running", json.dumps(PAIRS), json.dumps(TFS), json.dumps(DAYS))); c.commit()
        for f in os.listdir(CACHE):
            try: os.remove(os.path.join(CACHE, f))
            except Exception: pass
        log("novyj progon", run_id)
    done = {(r[0], r[1]) for r in c.execute("SELECT sym, tf FROM jobs WHERE run_id=?", (run_id,))}
    todo = [(s, tf) for tf in TFS for s in PAIRS if (s, tf) not in done]; total = len(PAIRS) * len(TFS)
    log("zadach vsego %d, ostalos %d, setka %d, MINN %d" % (total, len(todo), len(GRID), MINN))
    for n, (sym, tf) in enumerate(todo):
        t0 = time.time(); idx = [total - len(todo) + n + 1, total]
        set_state(c, run_id=run_id, sym=sym, tf=tf, phase="fetch", i=0, n=len(GRID), job_started=int(t0 * 1000), idx=idx)
        try:
            df = get_df(run_id, sym, tf, now_ms)
            set_state(c, run_id=run_id, sym=sym, tf=tf, phase="grid", i=0, n=len(GRID), job_started=int(time.time() * 1000), idx=idx)
            r = run_job(c, run_id, sym, tf, df, now_ms, idx)
        except BadSym as e: r = dict(status="ERR", verdict="ERR", reason="нет такой пары на Binance: %s" % e)
        except Cap as e: r = dict(status="TIMEOUT", verdict="ERR", reason=str(e))
        except Exception as e:
            traceback.print_exc(); r = dict(status="ERR", verdict="ERR", reason=("%s: %s" % (type(e).__name__, e))[:200])
        el = round(time.time() - t0, 1)
        c.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, sym, tf, r.get("status"), r.get("verdict"), r.get("reason"), r.get("oos_sum"), r.get("oos_fee2"), r.get("oos_n"), r.get("ho_net"), r.get("ho_n"), r.get("ho_fee2"),
                   r.get("grid_oos_mean"), r.get("grid_ho_mean"), r.get("ho_pos_share"), r.get("corr_mean"), r.get("price_ho"), r.get("t_days"), r.get("rows"), el, int(time.time() * 1000),
                   json.dumps(r.get("data")) if r.get("data") else None))
        c.commit(); log("%s %s -> %s (%s) %.0fs" % (sym, tf, r.get("verdict"), r.get("reason"), el))
    c.execute("UPDATE runs SET status='done' WHERE run_id=?", (run_id,)); c.commit()
    set_state(c, run_id=run_id, phase="done"); log("GOTOVO")

if __name__ == "__main__":
    main()
