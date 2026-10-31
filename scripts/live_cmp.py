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


print("\n== реальное окно бота: якорь = старт прогона - 1300 свечей, настройки каждого прогона 5m ==")
def ts3(ms): return dt.datetime.fromtimestamp(ms / 1000 + 3 * 3600, dt.timezone.utc).strftime("%d.%m %H:%M")
tot = {"OLD": [0, 0.0], "NEW": [0, 0.0]}
for r in runs5:
    sym = r["sym"]; anc = r["start_ms"] - 1300 * 300000
    async def ld():
        cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        try:
            df, _ = await cp.fetch_back(sym, "5m", anc - 300 * 300000)
            return df[df["t"] >= anc].reset_index(drop=True)
        finally:
            await cp.SES.close()
    df = asyncio.run(ld())
    out = {}
    for zname, zz in (("OLD", zz_old), ("NEW", zigzag_fixed)):
        vpm.zigzag = zz
        P = dict(cs.PARAMS, **dict(r["cfg"], sym=sym)); P["sim_from_ms"] = r["start_ms"]
        trs = cs.simulate(df, now, P); out[zname] = trs
        C = [x for x in trs if not x["open"]]
        tot[zname][0] += len(trs); tot[zname][1] += sum(x["net"] for x in C)
    print("%-10s OLD n %d net %+.2f%% | NEW n %d net %+.2f%%" % (sym, len(out["OLD"]), sum(x["net"] for x in out["OLD"] if not x["open"]), len(out["NEW"]), sum(x["net"] for x in out["NEW"] if not x["open"])))
    if sym in ("PHAUSDT", "REZUSDT", "CHIPUSDT"):
        for zname in ("OLD", "NEW"):
            for x in out[zname]:
                print("    %s %s %s %s in %s out %s net %+.2f%% %s" % (zname, sym, x["side"], x.get("tag", ""), ts3(x["t_in"]), ts3(x["t_out"]) if x.get("t_out") else "-", x["net"], "OPEN" if x["open"] else ""))
vpm.zigzag = zz_old
print("TOTAL", tot)
print("DONE")
