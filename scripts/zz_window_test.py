# -*- coding: utf-8 -*-
"""Test: pivots by rolling window (LuxAlgo-style, length = bars on each side) vs current percent-deviation ZigZag.
Part A: pivot stability vs data-window anchor (1000/1300/2000 candles). Part B: trade-set stability with real run settings.
Output is ASCII only (bridge). Run on VPS: python3 zz_window_test.py"""
import sys, os, json, asyncio, time, urllib.request, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
from numpy.lib.stride_tricks import sliding_window_view as sw
import classic_panel as cp, classic_strategy as cs, classic_vp as vpm
now = int(time.time() * 1000)
ZZ_CUR = vpm.zigzag
WL = [12]
ANCH = (1000, 1300, 2000)

def zz_window(h, l, length, dev=0, back=0):
    L = int(WL[0]); n = len(h)
    if n < 2 * L + 1: return []
    H = sw(np.asarray(h, float), 2 * L + 1).argmax(axis=1) == L
    Lo = sw(np.asarray(l, float), 2 * L + 1).argmin(axis=1) == L
    cand = []
    for k in range(len(H)):
        i = k + L
        if H[k]: cand.append(dict(i=i, p=float(h[i]), k="H", conf=i + L))
        if Lo[k]: cand.append(dict(i=i, p=float(l[i]), k="L", conf=i + L))
    out = []
    for c in cand:
        if out and out[-1]["k"] == c["k"]:
            if (c["k"] == "H" and c["p"] > out[-1]["p"]) or (c["k"] == "L" and c["p"] < out[-1]["p"]):
                out[-1] = c
            continue
        out.append(c)
    return out

d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
runs5 = [r for r in d["runs"] if r.get("track") == "vp" and r["cfg"].get("tf") == "5m" and r.get("stop_ms") is None]
seen = set(); R = []
for r in runs5:
    if r["sym"] not in seen: seen.add(r["sym"]); R.append(r)
print("pairs:", [r["sym"] for r in R])
SIM_FROM = now - 10 * 86400000

async def ld(sym):
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    try:
        df, _ = await cp.fetch_back(sym, "5m", SIM_FROM - 2400 * 300000)
        return df[df["t"] >= SIM_FROM - 2300 * 300000].reset_index(drop=True)
    finally:
        await cp.SES.close()

DATA = {}
for r in R:
    try: DATA[r["sym"]] = asyncio.run(ld(r["sym"]))
    except Exception as e: print("load fail", r["sym"], e)

def piv_set(df, anc_n, fn, depth, dev, back):
    s = int(np.searchsorted(df["t"].values, SIM_FROM)) - anc_n
    if s < 0: return None
    sub = df.iloc[s:].reset_index(drop=True)
    pv = fn(sub["h"].values, sub["l"].values, depth, dev, back)
    t = sub["t"].values
    return {(int(t[p["i"]]), p["k"]) for p in pv if p["conf"] < len(sub)}, len(pv), len(sub)

print("\n== PART A: pivot sets in last 800 candles, anchors 1000/1300/2000 ==")
meths = [("cur 12/0.2/3", ZZ_CUR, (12, 0.2, 3)), ("cur 12/0.6/3", ZZ_CUR, (12, 0.6, 3)), ("win L=6", zz_window, (6, 0, 0)), ("win L=12", zz_window, (12, 0, 0)), ("win L=24", zz_window, (24, 0, 0))]
for name, fn, (dp, dv, bk) in meths:
    WL[0] = dp
    jac = []; cnt = []
    for sym, df in DATA.items():
        sets = []
        tmin = int(df["t"].values[-800])
        for a in ANCH:
            res = piv_set(df, a, fn, dp, dv, bk)
            if res is None: sets = None; break
            sets.append({x for x in res[0] if x[0] >= tmin}); 
        if not sets: continue
        cnt.append(len(sets[1]) / (800 * 5 / 1440.0))
        for x in range(3):
            for y in range(x + 1, 3):
                u = sets[x] | sets[y]
                jac.append(len(sets[x] & sets[y]) / len(u) if u else 1.0)
    print("%-14s pivots/day %.1f  mean Jaccard(anchor pairs) %.3f  min %.3f  (pairs=%d)" % (name, np.mean(cnt) if cnt else 0, np.mean(jac) if jac else 0, min(jac) if jac else 0, len(DATA)))

print("\n== PART B: trades from last 10d, real run settings, anchors 1000/1300/2000 ==")
for mname, fn in (("cur(fixed)", ZZ_CUR), ("win L=12", zz_window), ("win L=24", zz_window)):
    WL[0] = 24 if mname.endswith("24") else 12
    vpm.zigzag = fn
    tot = {a: [0, 0.0] for a in ANCH}; common = 0; union = 0; per = []
    for r in R:
        sym = r["sym"]; df = DATA.get(sym)
        if df is None: continue
        keys = {}
        for a in ANCH:
            s = int(np.searchsorted(df["t"].values, SIM_FROM)) - a
            sub = df.iloc[max(s, 0):].reset_index(drop=True)
            P = dict(cs.PARAMS, **dict(r["cfg"], sym=sym)); P["sim_from_ms"] = SIM_FROM
            try: trs = cs.simulate(sub, now, P)
            except Exception as e: print("sim fail", sym, a, e); trs = []
            keys[a] = {(x["side"], x["t_in"]) for x in trs}
            tot[a][0] += len(trs); tot[a][1] += sum(x["net"] for x in trs if not x["open"])
        u = set().union(*keys.values()); c = set.intersection(*keys.values())
        union += len(u); common += len(c)
        if u: per.append("%s %d/%d/%d" % (sym[:5], len(keys[1000]), len(keys[1300]), len(keys[2000])))
    print("%-11s n %s | net%% %s | common %d of union %d" % (mname, "/".join(str(tot[a][0]) for a in ANCH), "/".join("%+.1f" % tot[a][1] for a in ANCH), common, union))
    print("   per pair:", "; ".join(per))
vpm.zigzag = ZZ_CUR
print("DONE")
