# -*- coding: utf-8 -*-
"""Walk-forward podbor nastroek Profilya po odnoy pare (default PHAUSDT, 5m). ASCII output.
Windows: S = now-120d. Folds k=0..2: train [S+20k, S+20k+40), test [S+20k+40, S+20k+60). Holdout = last 20d (final pick on train [now-60d, now-20d)).
Usage: python wf_pha.py [SYMBOL]"""
import sys, os, json, asyncio, time, itertools, urllib.request
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, pandas as pd, aiohttp
import classic_panel as cp, classic_strategy as cs, classic_vp as vpm
SYM = sys.argv[1] if len(sys.argv) > 1 else "PHAUSDT"
now = int(time.time() * 1000); DAY = 86400000
S = now - 120 * DAY; HO = now - 20 * DAY
FOLDS = [(S + 20 * k * DAY, S + (20 * k + 40) * DAY, S + (20 * k + 60) * DAY) for k in range(3)]  # train_from, test_from, test_to
LAST_TRAIN = (now - 60 * DAY, HO)
d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
live = [x for x in d["runs"] if x.get("track") == "vp" and x["cfg"].get("tf") == "5m" and x["sym"] == SYM and x.get("stop_ms") is None][0]
BASE = {k: v for k, v in live["cfg"].items() if k not in ("vp_start", "vp_starts", "vp_since")}
BASE["vp_start"] = "auto"; BASE["vp_starts"] = {}
async def ld():
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
    try:
        df, _ = await cp.fetch_back(SYM, "5m", S - 1600 * 300000)
        return df[df["t"] >= S - 1500 * 300000].reset_index(drop=True)
    finally: await cp.SES.close()
DF = asyncio.run(ld()); print("rows", len(DF), "pair", SYM)
def px(ms):
    i = int(np.searchsorted(DF["t"].values, ms)); i = min(i, len(DF) - 1); return float(DF["c"].values[i])
def sim(over, fee=0.05):
    P = dict(cs.PARAMS, **dict(BASE, **over, sym=SYM)); P["sim_from_ms"] = S; P["fee"] = fee
    try: trs = cs.simulate(DF, now, P)
    except Exception as e: print("sim fail", over, e); return []
    return [dict(t=x["t_in"], net=x["net"], op=bool(x["open"]), side=x["side"], tag=x.get("tag", "")) for x in trs]
def win(trs, a, b):
    sel = [x for x in trs if a <= x["t"] < b and not x["op"]]
    return round(sum(x["net"] for x in sel), 2), len(sel)
ZZ = {"A": (12, 0.2, 3), "B": (12, 0.6, 3), "C": (18, 0.4, 3)}
AX = dict(zz=list(ZZ), sl=[1.0, 2.0], rr=[2.0, 3.0], lvn=[0.35, 0.5], hvn=[1.5, 3.0])
def cfg_over(c):
    zz, sl, rr, lvn, hvn = c; dp, dv, bk = ZZ[zz]
    return dict(zz_depth=dp, zz_dev=dv, zz_back=bk, vp_sl_atr=sl, vp_rr=rr, vp_lvn=lvn, vp_hvn=hvn)
GRID = list(itertools.product(AX["zz"], AX["sl"], AX["rr"], AX["lvn"], AX["hvn"]))
name = lambda c: "zz%s sl%.1f rr%.1f lvn%.2f hvn%.1f" % c
RES = {}; t0 = time.time()
for i, c in enumerate(GRID):
    RES[c] = sim(cfg_over(c))
    if i % 8 == 7: print("grid %d/%d  %.0fs" % (i + 1, len(GRID), time.time() - t0), flush=True)
def rk(a): return pd.Series(a).rank().values
def spear(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0: return float("nan")
    return float(np.corrcoef(rk(a), rk(b))[0, 1])
MINN = 8
print("\n== FOLDS (net%% = sum of closed-trade net, no leverage; train 40d, test 20d; min train trades %d) ==" % MINN)
oos = []; chosen = []; corrs = []; marg = {}
for k, (a, b, e) in enumerate(FOLDS):
    tr = {c: win(RES[c], a, b) for c in GRID}; te = {c: win(RES[c], b, e) for c in GRID}
    ok = [c for c in GRID if tr[c][1] >= MINN]
    best = max(ok, key=lambda c: tr[c][0]) if ok else None
    corr = spear([tr[c][0] for c in ok], [te[c][0] for c in ok]); corrs.append(corr)
    allte = np.array([te[c][0] for c in GRID])
    print("fold %d  price test window %+.1f%%  grid test: mean %+.1f median %+.1f best %+.1f worst %+.1f  share>0 %.0f%%  corr(train,test) %.2f" % (k + 1, (px(e) / px(b) - 1) * 100, allte.mean(), np.median(allte), allte.max(), allte.min(), 100 * (allte > 0).mean(), corr))
    if best:
        wfe = ((te[best][0] / 20.0) / (tr[best][0] / 40.0)) if tr[best][0] > 0 else float("nan")
        print("   chosen %s | train %+.1f (n %d) | TEST %+.1f (n %d) | WFE %.2f" % (name(best), tr[best][0], tr[best][1], te[best][0], te[best][1], wfe))
        oos.append(te[best][0]); chosen.append(best)
    for c in GRID:
        for ai, v in zip(("zz", "sl", "rr", "lvn", "hvn"), c): marg.setdefault((ai, v), []).append(te[c][0])
print("OOS sum of chosen: %+.1f over %d folds (grid-average choice would give %+.1f)" % (sum(oos), len(oos), sum(np.mean([win(RES[c], b, e)[0] for c in GRID]) for (a, b, e) in FOLDS)))
print("corr(train,test) per fold:", ["%.2f" % x for x in corrs])
print("\n== marginal mean TEST net by parameter value (all 3 folds x grid) ==")
for (ai, v), xs in sorted(marg.items(), key=lambda z: (z[0][0], str(z[0][1]))): print("  %s=%s  mean %+.2f  (n %d)" % (ai, v, np.mean(xs), len(xs)))
print("\n== BASELINES on same test windows ==")
live_over = {k: v for k, v in live["cfg"].items() if k.startswith(("vp_", "zz_")) and k not in ("vp_start", "vp_starts", "vp_since")}
base_trs = {"current PHA cfg": sim(live_over), "defaults (no vp_ overrides)": sim({k: vpm.VPD[k] for k in vpm.VPD if k not in ("vp_start", "vp_starts")} | dict(zz_depth=12, zz_dev=0.6, zz_back=3, vp_rows=48, vp_va=70.0))}
for nm, trs in base_trs.items():
    r = [win(trs, b, e) for (a, b, e) in FOLDS]
    print("  %-30s tests %s sum %+.1f" % (nm, " / ".join("%+.1f(n%d)" % x for x in r), sum(x[0] for x in r)))
print("\n== FINAL PICK on train [now-60d, now-20d) and HOLDOUT (last 20d, never used) ==")
tr = {c: win(RES[c], *LAST_TRAIN) for c in GRID}; ok = [c for c in GRID if tr[c][1] >= MINN]
fin = max(ok, key=lambda c: tr[c][0]) if ok else None
if fin:
    ho = win(RES[fin], HO, now + DAY); allho = np.array([win(RES[c], HO, now + DAY)[0] for c in GRID])
    print("final %s | train %+.1f (n %d) | HOLDOUT %+.1f (n %d) | price %+.1f%% | grid holdout mean %+.1f median %+.1f share>0 %.0f%%" % (name(fin), tr[fin][0], tr[fin][1], ho[0], ho[1], (px(now) / px(HO) - 1) * 100, allho.mean(), np.median(allho), 100 * (allho > 0).mean()))
    hs = sorted([x["net"] for x in RES[fin] if HO <= x["t"] and not x["op"]], reverse=True)
    if hs: print("   holdout trades: wins %d of %d, top3 net %+.1f of total %+.1f" % (sum(1 for x in hs if x > 0), len(hs), sum(hs[:3]), sum(hs)))
    p2 = sim(cfg_over(fin), fee=0.10); print("   double fees (0.10/side): train %+.1f holdout %+.1f" % (win(p2, *LAST_TRAIN)[0], win(p2, HO, now + DAY)[0]))
    print("   neighbours (one step): train / holdout")
    for ai, ax_i in zip(("zz", "sl", "rr", "lvn", "hvn"), range(5)):
        for v in AX[ai]:
            if v == fin[ax_i]: continue
            nb = list(fin); nb[ax_i] = v; nb = tuple(nb)
            print("     %s=%s: %+.1f / %+.1f" % (ai, v, win(RES[nb], *LAST_TRAIN)[0], win(RES[nb], HO, now + DAY)[0]))
    for k, c in enumerate(chosen):
        p3 = sim(cfg_over(c), fee=0.10); a, b, e = FOLDS[k]
        print("   fold %d chosen with double fees: test %+.1f (fee 0.05: %+.1f)" % (k + 1, win(p3, b, e)[0], win(RES[c], b, e)[0]))
json.dump({"folds": FOLDS, "chosen": [list(c) for c in chosen], "final": list(fin) if fin else None}, open("/tmp/wf_pha.json", "w"))
print("DONE")
