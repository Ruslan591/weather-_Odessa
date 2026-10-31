# -*- coding: utf-8 -*-
"""Test2 (control + out-of-sample periods): pivots by rolling window (LuxAlgo-style, length = bars on each side) vs current percent-deviation ZigZag.
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


def zz_prefix(h, l, depth, dev, back):
    """Version BEFORE the 2026-10-31 fix (control): candidate too close to previous pivot is not moved."""
    n, dv = len(h), dev / 100.0
    piv, d, ei, ep, last_i = [], 0, 0, 0.0, -10 ** 9
    hi_i = lo_i = 0
    for i in range(n):
        if d == 0:
            if h[i] > h[hi_i]: hi_i = i
            if l[i] < l[lo_i]: lo_i = i
            if hi_i != lo_i and h[hi_i] / l[lo_i] - 1 >= dv:
                if hi_i > lo_i:
                    piv.append(dict(i=lo_i, p=float(l[lo_i]), k="L", conf=i)); d, ei, ep = 1, hi_i, h[hi_i]
                else:
                    piv.append(dict(i=hi_i, p=float(h[hi_i]), k="H", conf=i)); d, ei, ep = -1, lo_i, l[lo_i]
                last_i = piv[-1]["i"]
            continue
        if d == 1:
            if h[i] > ep: ei, ep = i, h[i]
            elif ep - l[i] >= ep * dv and i - ei >= back and ei - last_i >= depth:
                piv.append(dict(i=ei, p=float(ep), k="H", conf=i)); last_i = ei; d = -1
                j = ei + 1 + int(np.argmin(l[ei + 1:i + 1])); ei, ep = j, l[j]
        else:
            if l[i] < ep: ei, ep = i, l[i]
            elif h[i] - ep >= ep * dv and i - ei >= back and ei - last_i >= depth:
                piv.append(dict(i=ei, p=float(ep), k="L", conf=i)); last_i = ei; d = 1
                j = ei + 1 + int(np.argmax(h[ei + 1:i + 1])); ei, ep = j, h[j]
    return piv

d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
runs5 = [r for r in d["runs"] if r.get("track") == "vp" and r["cfg"].get("tf") == "5m" and r.get("stop_ms") is None]
seen = set(); R = []
for r in runs5:
    if r["sym"] not in seen: seen.add(r["sym"]); R.append(r)
DAY = 86400000
T0 = now - 30 * DAY
async def ld(sym):
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
    try:
        df, _ = await cp.fetch_back(sym, "5m", T0 - 2400 * 300000)
        return df[df["t"] >= T0 - 2300 * 300000].reset_index(drop=True)
    finally:
        await cp.SES.close()
DATA = {}
for r in R:
    try: DATA[r["sym"]] = asyncio.run(ld(r["sym"]))
    except Exception as e: print("load fail", r["sym"], e)
print("pairs loaded:", len(DATA))

def tail_sets(df, anc_n, fn, dp, dv, bk, tail_from_ms, end_n):
    s = int(np.searchsorted(df["t"].values, T0)) - anc_n
    sub = df.iloc[s:end_n].reset_index(drop=True)
    pv = fn(sub["h"].values, sub["l"].values, dp, dv, bk); t = sub["t"].values
    return {(int(t[p["i"]]), p["k"]) for p in pv if p["conf"] < len(sub) and t[p["i"]] >= tail_from_ms}

print("\n== CONTROL: pivot-set stability (Jaccard) over 6 different end points x anchors 1000/1300/2000, tail 800 candles ==")
for name, fn, (dp, dv, bk) in (("PRE-FIX 12/0.2/3", zz_prefix, (12, 0.2, 3)), ("FIXED 12/0.2/3", ZZ_CUR, (12, 0.2, 3)), ("PRE-FIX 12/0.6/3", zz_prefix, (12, 0.6, 3)), ("FIXED 12/0.6/3", ZZ_CUR, (12, 0.6, 3)), ("win L=12", zz_window, (12, 0, 0)), ("win L=24", zz_window, (24, 0, 0))):
    WL[0] = dp
    jac = []
    for sym, df in DATA.items():
        n = len(df)
        for back_days in (0, 3, 6, 9, 12, 15):
            end_n = n - back_days * 288
            tfrom = int(df["t"].values[end_n - 800])
            S = [tail_sets(df, a, fn, dp, dv, bk, tfrom, end_n) for a in ANCH]
            for x in range(3):
                for y in range(x + 1, 3):
                    u = S[x] | S[y]; jac.append(len(S[x] & S[y]) / len(u) if u else 1.0)
    jac = np.array(jac)
    print("%-17s mean Jaccard %.3f  share of pairs with Jaccard<1: %.1f%%  min %.3f  (n=%d)" % (name, jac.mean(), 100.0 * (jac < 0.9999).mean(), jac.min(), len(jac)))

print("\n== OUT-OF-SAMPLE: trades by 10-day period, real run settings, anchor 1300 ==")
res = {}
for mname, fn, wl in (("FIXED cur", ZZ_CUR, 12), ("win L=12", zz_window, 12), ("win L=24", zz_window, 24), ("win L=36", zz_window, 36)):
    WL[0] = wl; vpm.zigzag = fn
    allt = []
    for r in R:
        sym = r["sym"]; df = DATA.get(sym)
        if df is None: continue
        s = int(np.searchsorted(df["t"].values, T0)) - 1300
        sub = df.iloc[max(s, 0):].reset_index(drop=True)
        P = dict(cs.PARAMS, **dict(r["cfg"], sym=sym)); P["sim_from_ms"] = T0
        try: trs = cs.simulate(sub, now, P)
        except Exception as e: print("sim fail", sym, e); trs = []
        allt += [dict(sym=sym, t=x["t_in"], net=x["net"], op=x["open"]) for x in trs]
    line = []
    for k, (a, b) in enumerate(((T0, T0 + 10 * DAY), (T0 + 10 * DAY, T0 + 20 * DAY), (T0 + 20 * DAY, now + DAY))):
        sel = [x for x in allt if a <= x["t"] < b and not x["op"]]
        pos = [x for x in sel if x["net"] > 0]
        by = {}
        for x in sel: by[x["sym"]] = by.get(x["sym"], 0.0) + x["net"]
        best = sorted(by.items(), key=lambda z: -z[1])[:1]
        line.append("P%d n %d win %d net %+.1f%% (best pair %s %+.1f)" % (k + 1, len(sel), len(pos), sum(x["net"] for x in sel), best[0][0][:5] if best else "-", best[0][1] if best else 0))
    print("%-10s | %s" % (mname, " | ".join(line)))
vpm.zigzag = ZZ_CUR
print("DONE")
