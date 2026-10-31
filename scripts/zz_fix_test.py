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

print("\n== ZigZag старый/новый (настройки PHA: depth 12, dev 0.2, back 3), 60 суток, самый длинный период без пивотов ==")
dfs = {}
for sym in syms[:10]:
    try:
        dfs[sym] = asyncio.run(load(sym, 60))
    except Exception as e:
        print(sym, "load fail", repr(e)[:80]); continue
    df = dfs[sym]; h, l, t = df["h"].values, df["l"].values, df["t"].values
    a = zz_old(h, l, 12, 0.2, 3); b = zigzag_fixed(h, l, 12, 0.2, 3)
    print("%-10s bars %d | old pivots %4d maxgap %.1f d | new pivots %4d maxgap %.1f d" % (sym, len(df), len(a), maxgap_days(a, t, len(df)), len(b), maxgap_days(b, t, len(df))))

print("\n== PHA, 120 суток: сигналы Профиля (настройки PHA сейчас / по умолчанию 5m) ==")
df = asyncio.run(load("PHAUSDT", 120)); pre = cs.prepare(df, now); M = pre["M"]
t, h, l, c = pre["t"], pre["h"], pre["l"], pre["c"]
gl = labels(h, l, c, M); valid = M - 145
clus = []
for i in np.nonzero(gl[:valid])[0]:
    if clus and i - clus[-1][1] <= 12: clus[-1][1] = i
    else: clus.append([i, i])
print("фон good_L %.1f%%, кластеров разгона %d" % (100 * gl[:valid].mean(), len(clus)))
for name, zz in (("OLD", zz_old), ("NEW", zigzag_fixed)):
    vpm.zigzag = zz
    for cname, extra in (("PHA-cfg(vp_start=auto)", dict(cfg_pha, vp_start="auto")), ("defaults", {})):
        P = dict(cs.PARAMS, **dict({"tf": "5m", "sym": "PHAUSDT"}, **extra))
        t0 = time.time(); sig, chan, tags, over = vpm.vp_signals(pre, P)
        L = [i for i in sorted(sig) if sig[i] == "L" and i < valid]; S = [i for i in sorted(sig) if sig[i] == "S"]
        hit = 100 * np.mean([gl[i] for i in L]) if L else 0
        caught = sum(1 for a, b in clus if any(a - 12 <= i <= b for i in L))
        bt = {}
        for i in sig: bt[(sig[i], tags[i])] = bt.get((sig[i], tags[i]), 0) + 1
        rec = [(ts(int(t[i])), sig[i], tags[i]) for i in sorted(sig) if t[i] >= now - 6 * 86400000]
        print("[%s %s] %.0fs L %d (%.2f/day) hit %.1f%% | S %d | recall %d/%d | tags %s | last6d %d %s" % (name, cname, time.time() - t0, len(L), len(L) / 120, hit, len(S), caught, len(clus), bt, len(rec), rec[-12:]))
vpm.zigzag = zz_old
print("DONE")
