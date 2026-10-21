"""classic_scan_ls.py - скан связок пара x ТФ на текущих правилах: Net по половинам года, лонги/шорты, БУ хуже входа.
usage: python classic_scan_ls.py new|old  (old = clone_between False: третья точка канала до текущей свечи)"""
import sys, os
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_trendline as tl
import classic_strategy as cs, classic_learn as L
mode = sys.argv[1] if len(sys.argv) > 1 else "new"
if mode == "old":
    tl.CFG["clone_between"] = False
pairs = ["ZECUSDT", "BTCUSDT", "SOLUSDT", "NEARUSDT", "BNBUSDT"]
tfs = ["15m", "30m", "1h", "2h", "4h", "6h", "12h"]
BE = "\u0431\u0435\u0437\u0443\u0431\u044b\u0442\u043e\u043a"
rows = []
print("mode", mode)
print("%-9s %-4s %4s %8s %8s %8s %8s %8s %5s" % ("pair", "tf", "n", "net", "H1", "H2", "long", "short", "BE<0"))
for sym in pairs:
    for tf in tfs:
        f = "/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)
        if not os.path.exists(f):
            continue
        try:
            df = pd.read_csv(f); now = int(df.ct.iloc[-1]) + 10 ** 6
            P = L.base_params(sym, tf); pre = cs.prepare(df, now); T = cs.simulate(df, now, P, pre=pre)
        except Exception as e:
            print(sym, tf, "ERR", str(e)[:80]); continue
        if not T:
            print("%-9s %-4s %4d" % (sym, tf, 0)); continue
        t0, t1 = min(x["t_in"] for x in T), max(x["t_in"] for x in T); mid = (t0 + t1) / 2
        net = sum(x["net"] for x in T)
        h1 = sum(x["net"] for x in T if x["t_in"] < mid); h2 = net - h1
        lg = sum(x["net"] for x in T if x["side"] == "L"); sh = net - lg
        bn = sum(1 for x in T if x["reason"] == BE and (1 if x["side"] == "L" else -1) * (x["p_out"] / x["p_in"] - 1) < 0)
        rows.append(dict(sym=sym, tf=tf, n=len(T), net=net, h1=h1, h2=h2, lg=lg, sh=sh, bn=bn))
        print("%-9s %-4s %4d %+8.1f %+8.1f %+8.1f %+8.1f %+8.1f %5d" % (sym, tf, len(T), net, h1, h2, lg, sh, bn), flush=True)
D = pd.DataFrame(rows)
print("\nsvyazok:", len(D), "| v pluse:", int((D.net > 0).sum()), "| mediana net %.1f | summa %.1f" % (D.net.median(), D.net.sum()))
print("H1>0: %d, H2>0: %d, obe>0: %d" % ((D.h1 > 0).sum(), (D.h2 > 0).sum(), ((D.h1 > 0) & (D.h2 > 0)).sum()))
print("long: summa %.1f, v pluse %d | short: summa %.1f, v pluse %d" % (D.lg.sum(), (D.lg > 0).sum(), D.sh.sum(), (D.sh > 0).sum()))
big = D[D.tf.isin(["2h", "4h", "6h", "12h"])]
print(">=2h: svyazok %d, v pluse %d, mediana %.1f, summa %.1f, long %.1f, short %.1f" % (len(big), (big.net > 0).sum(), big.net.median(), big.net.sum(), big.lg.sum(), big.sh.sum()))
print("po pare:"); print(D.groupby("sym")[["net", "lg", "sh"]].sum().round(1).to_string())
print("BE<0 vsego:", int(D.bn.sum()))
