"""classic_chan_diag.py - какие каналы дают убытки: разбор сделок текущих правил по геометрии канала (ширина в ATR, положение входа в канале, причина выхода)."""
import sys, os, json
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
pairs = (sys.argv[1] if len(sys.argv) > 1 else "ZECUSDT,BTCUSDT,SOLUSDT,NEARUSDT").split(",")
tfs = (sys.argv[2] if len(sys.argv) > 2 else "2h,4h,6h,12h").split(",")
rows = []
for sym in pairs:
    for tf in tfs:
        df = pd.read_csv("/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)); now = int(df.ct.iloc[-1]) + 10 ** 6
        P = L.base_params(sym, tf); pre = cs.prepare(df, now); T = cs.simulate(df, now, P, pre=pre); atr = pre["atr"]
        for x in T:
            if not x.get("chl"): continue
            lo, up = x["chl"][0], x["chl"][1]; a = float(atr[max(0, x["i_in"] - 1)])
            w = (up - lo) / a if a > 0 else np.nan
            pos = ((x["p_in"] - lo) if x["side"] == "L" else (up - x["p_in"])) / (up - lo) if up > lo else np.nan
            rows.append(dict(sym=sym, tf=tf, side=x["side"], net=x["net"], reason=x["reason"], w=w, pos=pos, risk=x.get("risk", np.nan), bars=x["i_out"] - x["i_in"] if "i_out" in x else np.nan))
D = pd.DataFrame(rows)
print("trades:", len(D), "| avg net %.3f | win %.0f%% | sum %.1f" % (D.net.mean(), (D.net > 0).mean() * 100, D.net.sum()))
def tab(col, bins, labels):
    D["b"] = pd.cut(D[col], bins, labels=labels)
    g = D.groupby("b", observed=True).net.agg(n="count", win=lambda s: (s > 0).mean() * 100, avg="mean", sum="sum")
    print("\nby", col); print(g.round(2).to_string())
tab("w", [0, 3, 5, 7, 10, 14.01], ["<3", "3-5", "5-7", "7-10", "10-14"])
tab("pos", [-5, 0.0, 0.1, 0.25, 0.5, 5], ["<0 (below line)", "0-0.1", "0.1-0.25", "0.25-0.5", ">0.5"])
print("\nby exit reason"); print(D.groupby("reason").net.agg(n="count", avg="mean", sum="sum").round(2).to_string())
print("\nby side"); print(D.groupby("side").net.agg(n="count", win=lambda s: (s > 0).mean() * 100, avg="mean", sum="sum").round(2).to_string())
print("\nby tf"); print(D.groupby("tf").net.agg(n="count", win=lambda s: (s > 0).mean() * 100, avg="mean", sum="sum").round(2).to_string())
print("\nrisk pct quantiles:", D.risk.quantile([.1, .5, .9]).round(2).tolist(), "| width ATR quantiles:", D.w.quantile([.1, .5, .9]).round(1).tolist())
