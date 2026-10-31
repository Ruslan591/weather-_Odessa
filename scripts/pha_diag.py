# -*- coding: utf-8 -*-
"""Диагностика Профиля по одной монете: python3 pha_diag.py SYM DAYS  (запуск на VPS, пишет в stdout)
A) сигналы с текущими настройками прогона (как видит бот) и с vp_start=auto
B) трассировка состояния Профиля 30.10 перед разгоном
C) предсказывают ли сигналы разгон: точность и охват против фона
"""
import sys, os, json, asyncio, time, urllib.request, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np
import classic_panel as cp, classic_strategy as cs, classic_vp as vpm

SYM = sys.argv[1] if len(sys.argv) > 1 else "PHAUSDT"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 120
TF = "5m"; TFMS = 300000
now = int(time.time() * 1000)


def ts(ms): return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%d.%m %H:%M")


d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
run = [r for r in d["runs"] if r.get("sym") == SYM and r.get("track") == "vp" and r["cfg"].get("tf") == TF and r.get("stop_ms") is None][0]
cfg_now = {k: v for k, v in run["cfg"].items() if k.startswith(("vp_", "zz_"))}
print("run", run["id"], "cfg:", {k: cfg_now[k] for k in sorted(cfg_now) if k not in ("vp_starts",)})

import aiohttp


async def _go():
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try:
        return await cp.fetch_back(SYM, TF, now - DAYS * 86400000)
    finally:
        await cp.SES.close()


df, _ = asyncio.run(_go())
df = df[df["t"] >= now - DAYS * 86400000].reset_index(drop=True)
print("bars", len(df), ts(int(df["t"].iloc[0])), "->", ts(int(df["t"].iloc[-1])))
pre = cs.prepare(df, now)
M = pre["M"]; t, o, h, l, c, atr = pre["t"], pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"]


def P_of(extra):
    return dict(cs.PARAMS, **dict({"tf": TF, "sym": SYM}, **extra))


# ---- метки «хороший вход» (рост >=5% за 12 ч, просадка до пика <1%) ----
HZ = 144
good_L = np.zeros(M, bool); good_S = np.zeros(M, bool)
for i in range(M - HZ - 1):
    seg_h = h[i + 1:i + 1 + HZ]; seg_l = l[i + 1:i + 1 + HZ]
    k = int(np.argmax(seg_h)); gain = seg_h[k] / c[i] - 1
    dd = (seg_l[:k + 1].min() / c[i] - 1) if k >= 0 else 0
    good_L[i] = gain >= 0.05 and dd > -0.01
    k2 = int(np.argmin(seg_l)); loss = 1 - seg_l[k2] / c[i]
    up_ = (seg_h[:k2 + 1].max() / c[i] - 1)
    good_S[i] = loss >= 0.05 and up_ < 0.01
valid = M - HZ - 1
print("base rate good_L %.1f%%  good_S %.1f%% (bars %d)" % (100 * good_L[:valid].mean(), 100 * good_S[:valid].mean(), valid))


def clusters(g):
    idx = np.nonzero(g[:valid])[0]; out = []
    for i in idx:
        if out and i - out[-1][1] <= 12: out[-1][1] = i
        else: out.append([i, i])
    return out


CL_L, CL_S = clusters(good_L), clusters(good_S)
print("clusters (merged gaps<=12 bars): L %d (%.1f/month)  S %d" % (len(CL_L), len(CL_L) / (DAYS / 30), len(CL_S)))


def evaluate(name, extra):
    t0 = time.time()
    sig, chan, tags, over = vpm.vp_signals(pre, P_of(extra))
    idx = sorted(sig)
    L = [i for i in idx if sig[i] == "L" and i < valid]; S = [i for i in idx if sig[i] == "S" and i < valid]
    pl = np.mean([good_L[i] for i in L]) * 100 if L else 0; ps = np.mean([good_S[i] for i in S]) * 100 if S else 0
    # охват кластеров: был ли L-сигнал за 12 свечей до начала кластера или внутри него
    caught = sum(1 for a, b in CL_L if any(a - 12 <= i <= b for i in L))
    caughtS = sum(1 for a, b in CL_S if any(a - 12 <= i <= b for i in S))
    bytag = {}
    for i in idx:
        bytag[(sig[i], tags[i])] = bytag.get((sig[i], tags[i]), 0) + 1
    print("[%s] %.0fs signals L %d (%.2f/day) hit %.1f%% | S %d hit %.1f%% | cluster recall L %d/%d S %d/%d | by tag %s" % (
        name, time.time() - t0, len(L), len(L) / DAYS, pl, len(S), ps, caught, len(CL_L), caughtS, len(CL_S), bytag))
    return sig, chan, tags, over


cfg_auto = dict(cfg_now); cfg_auto["vp_start"] = "auto"
r_now = evaluate("cfg PHA now (vp_start=%s)" % cfg_now.get("vp_start"), cfg_now)
r_auto = evaluate("cfg PHA now, vp_start=auto", cfg_auto)
r_def = evaluate("defaults 5m", {})

# ---- сигналы за последние 6 суток ----
for name, r in (("now", r_now), ("auto", r_auto), ("default", r_def)):
    sig, chan, tags, over = r
    rec = [(ts(int(t[i])), sig[i], tags[i]) for i in sorted(sig) if t[i] >= now - 6 * 86400000]
    print("signals last 6d [%s]: %d" % (name, len(rec)), rec[-25:])

# ---- B) трассировка 30.10 ----
P = vpm.__dict__  # noqa
pr = {k: cfg_now.get(k, dd_) for k, dd_ in vpm.VPD.items()}
depth, dev, back = int(pr["zz_depth"]), float(pr["zz_dev"]), int(pr["zz_back"])
piv = vpm.zigzag(h[:M], l[:M], depth, dev, back)
rows = int(pr["vp_rows"]); vaP = float(pr["vp_va"]); hv, lv = float(pr["vp_hvn"]), float(pr["vp_lvn"])
ms0 = int(dt.datetime(2026, 10, 30, 5, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
ms1 = int(dt.datetime(2026, 10, 30, 16, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
start_ov = None
if pr["vp_start"] not in (None, "", "auto"):
    ms_ = int(dt.datetime.strptime(str(pr["vp_start"])[:16].replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    start_ov = int(np.searchsorted(t, ms_))
print("\nTRACE %s: price/ATR%%/mode/channel/profile (every 30 min), start_ov=%s" % (SYM, start_ov))
pk = 0; HP, LP = [], []
Wm = max(60, depth * 4)
for i in range(Wm, M):
    while pk < len(piv) and piv[pk]["conf"] <= i:
        (HP if piv[pk]["k"] == "H" else LP).append(piv[pk]); pk += 1
    if not (ms0 <= t[i] <= ms1) or (int(t[i]) // TFMS) % 6 != 0: continue
    if len(HP) < 2 or len(LP) < 2: print(ts(int(t[i])), "few pivots"); continue
    H1, H2, L1, L2 = HP[-2], HP[-1], LP[-2], LP[-1]
    flat = abs(H1["p"] - H2["p"]) / H2["p"] * 100 <= float(pr["vp_flat_delta"]) and abs(L1["p"] - L2["p"]) / L2["p"] * 100 <= float(pr["vp_flat_delta"])
    mode = None
    if flat:
        mode = "flat"; ub, lb = max(H1["p"], H2["p"]), min(L1["p"], L2["p"]); a0 = min(H1["i"], H2["i"], L1["i"], L2["i"]); u_i, l_i = ub, lb
    else:
        sH = (H2["p"] - H1["p"]) / max(1, H2["i"] - H1["i"]); sL = (L2["p"] - L1["p"]) / max(1, L2["i"] - L1["i"])
        if sH * sL > 0 and abs(sH - sL) <= float(pr["vp_par"]) * max(abs(sH), abs(sL)):
            u_i = H2["p"] + sH * (i - H2["i"]); l_i = L2["p"] + sL * (i - L2["i"])
            if u_i > l_i: mode = "trend"; a0 = piv[pk - 2]["i"] if pk >= 2 else min(H1["i"], L1["i"])
    if mode is None:
        print(ts(int(t[i])), "c=%.5f no channel (slopes H %.2e L %.2e, flat=%s) lastH %s lastL %s" % (c[i], (H2["p"] - H1["p"]) / max(1, H2["i"] - H1["i"]), (L2["p"] - L1["p"]) / max(1, L2["i"] - L1["i"]), flat, ts(int(t[H2["i"]])), ts(int(t[L2["i"]])))); continue
    if start_ov is not None and start_ov < i - 10: a0 = start_ov
    a_ = atr[i]
    pf = vpm.profile(h, l, pre["v"], a0, i, rows, vaP, hv, lv) if i - a0 >= 3 else None
    if pf is None: print(ts(int(t[i])), mode, "no profile"); continue
    print(ts(int(t[i])), "c=%.5f atr%%=%.2f %s lo=%.5f up=%.5f | profile from %s: poc %.5f val %.5f vah %.5f hvn %d lvn %d | (c-VAL)/atr %.1f (VAH-c)/atr %.1f (c-lo)/atr %.1f (up-c)/atr %.1f" % (
        c[i], 100 * a_ / c[i], mode, l_i, u_i, ts(int(t[a0])), pf["poc"], pf["val"], pf["vah"], len(pf["hvn"]), len(pf.get("lvn", [])),
        (c[i] - pf["val"]) / a_, (pf["vah"] - c[i]) / a_, (c[i] - l_i) / a_, (u_i - c[i]) / a_))
print("DONE")
