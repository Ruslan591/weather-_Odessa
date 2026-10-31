# -*- coding: utf-8 -*-
"""A/B: прежний ZigZag против исправленного (кандидат завис, если ближе depth свечей к прошлому пивоту)."""
import sys, os, json, asyncio, time, urllib.request, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
import classic_panel as cp, classic_strategy as cs, classic_vp as vpm
now = int(time.time() * 1000)
def ts(ms): return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%d.%m %H:%M")

def zigzag_fixed(h, l, depth, dev, back):
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
            if h[i] > ep:
                ei, ep = i, h[i]
            elif ep - l[i] >= ep * dv and i - ei >= back:
                if ei - last_i >= depth:
                    piv.append(dict(i=ei, p=float(ep), k="H", conf=i)); last_i = ei; d = -1
                    j = ei + 1 + int(np.argmin(l[ei + 1:i + 1])); ei, ep = j, l[j]
                else:  # вершина слишком близко к прошлому пивоту: берём самую высокую не ближе depth свечей от него
                    s = last_i + depth
                    if s <= i:
                        j = s + int(np.argmax(h[s:i + 1])); ei, ep = j, h[j]
        else:
            if l[i] < ep:
                ei, ep = i, l[i]
            elif h[i] - ep >= ep * dv and i - ei >= back:
                if ei - last_i >= depth:
                    piv.append(dict(i=ei, p=float(ep), k="L", conf=i)); last_i = ei; d = 1
                    j = ei + 1 + int(np.argmax(h[ei + 1:i + 1])); ei, ep = j, h[j]
                else:
                    s = last_i + depth
                    if s <= i:
                        j = s + int(np.argmin(l[s:i + 1])); ei, ep = j, l[j]
    return piv

zz_old = vpm.zigzag
d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
runs5 = [r for r in d["runs"] if r.get("track") == "vp" and r["cfg"].get("tf") == "5m" and r.get("stop_ms") is None]
syms = [r["sym"] for r in runs5]
print("5m vp pairs:", syms)
cfg_pha = {k: v for k, v in [r for r in runs5 if r["sym"] == "PHAUSDT"][0]["cfg"].items() if k.startswith(("vp_", "zz_"))}

async def load(sym, days):
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try:
        df, _ = await cp.fetch_back(sym, "5m", now - days * 86400000)
        return df[df["t"] >= now - days * 86400000].reset_index(drop=True)
    finally:
        await cp.SES.close()

def maxgap_days(piv, t, n):
    if not piv: return 99
    idx = [p["conf"] for p in piv] + [n - 1]
    return max(np.diff(idx)) * 5 / 1440.0

def labels(h, l, c, M, HZ=144):
    gl = np.zeros(M, bool)
    for i in range(M - HZ - 1):
        sh = h[i + 1:i + 1 + HZ]; sl = l[i + 1:i + 1 + HZ]; k = int(np.argmax(sh))
        gl[i] = sh[k] / c[i] - 1 >= 0.05 and sl[:k + 1].min() / c[i] - 1 > -0.01
    return gl


base_cfg = dict([r for r in runs5 if r["sym"] == "PHAUSDT"][0]["cfg"])
print("full PHA cfg non-vp keys:", {k: v for k, v in base_cfg.items() if not k.startswith(("vp_", "zz_"))})
SYMS = ["PHAUSDT", "REZUSDT", "TREEUSDT", "IOSTUSDT", "NILUSDT", "CHIPUSDT"]
DAYS = 60
res = {}
for sym in SYMS:
    df = asyncio.run(load(sym, DAYS + 6))
    sim_from = now - DAYS * 86400000
    mid = now - (DAYS // 2) * 86400000
    for zname, zz in (("OLD", zz_old), ("NEW", zigzag_fixed)):
        vpm.zigzag = zz
        for cname, extra in (("PHAcfg", dict(vp_start="auto")), ("default", None)):
            cfg = dict(base_cfg)
            if extra is None:
                for k in list(cfg):
                    if k.startswith(("vp_", "zz_")) and k != "vp_since": cfg.pop(k)
            else:
                cfg.update(extra)
            P = dict(cs.PARAMS, **dict(cfg, sym=sym)); P["sim_from_ms"] = sim_from
            t0 = time.time()
            try:
                trs = cs.simulate(df, now, P)
            except Exception as e:
                print(sym, zname, cname, "ERR", repr(e)[:150]); continue
            C = [x for x in trs if not x["open"]]
            def st(L):
                n = len(L); w = sum(1 for x in L if x["net"] > 0)
                return n, (100 * w / n if n else 0), sum(x["net"] for x in L)
            a = st(C); h1 = st([x for x in C if x["t_in"] < mid]); h2 = st([x for x in C if x["t_in"] >= mid])
            L_ = st([x for x in C if x["side"] == "L"]); S_ = st([x for x in C if x["side"] == "S"])
            res.setdefault((zname, cname), []).append((sym, a, h1, h2))
            print("%-9s %s %-7s %3.0fs n %3d win %4.0f%% sum %+7.1f%% | 1st half n %d %+6.1f%% | 2nd half n %d %+6.1f%% | L n %d %+6.1f%% S n %d %+6.1f%% open %d" % (
                sym, zname, cname, time.time() - t0, a[0], a[1], a[2], h1[0], h1[2], h2[0], h2[2], L_[0], L_[2], S_[0], S_[2], len(trs) - len(C)))
vpm.zigzag = zz_old
print("\nTOTAL over pairs")
for k, v in res.items():
    n = sum(x[1][0] for x in v); s_ = sum(x[1][2] for x in v); s1 = sum(x[2][2] for x in v); s2 = sum(x[3][2] for x in v)
    print(k, "trades", n, "sum net %+.1f%%" % s_, "avg/trade %+.2f%%" % (s_ / n if n else 0), "half1 %+.1f%% half2 %+.1f%%" % (s1, s2))
print("DONE")
