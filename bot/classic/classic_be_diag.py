"""classic_be_diag.py - сколько выходов с пометкой 'безубыток' на самом деле убыточны и почему."""
import sys
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
rows = []
for sym in ["ZECUSDT", "BTCUSDT", "SOLUSDT", "NEARUSDT"]:
    for tf in ["2h", "4h", "6h", "12h"]:
        df = pd.read_csv("/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)); now = int(df.ct.iloc[-1]) + 10 ** 6
        P = L.base_params(sym, tf); pre = cs.prepare(df, now); T = cs.simulate(df, now, P, pre=pre)
        for x in T:
            if x["reason"] != "\u0431\u0435\u0437\u0443\u0431\u044b\u0442\u043e\u043a": continue
            s = 1 if x["side"] == "L" else -1
            rows.append(dict(net=x["net"], gross=s * (x["p_out"] / x["p_in"] - 1) * 100, bars=x["i_out"] - x["i_in"], mfe=x.get("mfe", np.nan), lock=P.get("be_lock"), trig=P.get("be_trigger")))
D = pd.DataFrame(rows)
print("BE exits:", len(D), "| be_trigger", D.trig.iloc[0], "be_lock", D.lock.iloc[0], "| fee round trip 0.10")
b = pd.cut(D.net, [-99, -1, -0.15, 0.15, 0.35, 99], labels=["< -1", "-1..-0.15", "-0.15..+0.15", "+0.15..+0.35", "> +0.35"])
print(D.groupby(b, observed=True).net.agg(n="count", sum="sum", avg="mean").round(2).to_string())
print("exit worse than entry (gross<0):", int((D.gross < 0).sum()), "| their sum net %.1f" % D[D.gross < 0].net.sum())
print("exit at lock level (gross between lock-0.05 and lock+0.05):", int(((D.gross - D.lock).abs() < 0.05).sum()))
print("held 1 bar:", int((D.bars <= 1).sum()), "| of them gross<0:", int(((D.bars <= 1) & (D.gross < 0)).sum()))
print("gross<0 : median gross %.2f, 10th pct %.2f, worst %.2f" % (D[D.gross < 0].gross.median(), D[D.gross < 0].gross.quantile(.1), D.gross.min()))
