"""classic_compare.py - сравнение двух наборов параметров на всех связках пара x ТФ (годовая история в pairs/).
python classic_compare.py 'be_intrabar=1' [pairs] [tfs]   # A = текущие правила панели, B = A + переопределения"""
import sys, os, json, statistics, time
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
ov = {}
for kv in (sys.argv[1] if len(sys.argv) > 1 else "be_intrabar=1").split(","):
    k, v = kv.split("="); ov[k] = (float(v) if v.replace(".", "", 1).replace("-", "", 1).isdigit() else v)
    if k == "be_intrabar": ov[k] = bool(int(v))
pairs = (sys.argv[2] if len(sys.argv) > 2 else "ZECUSDT,BTCUSDT,SOLUSDT,NEARUSDT").split(",")
tfs = (sys.argv[3] if len(sys.argv) > 3 else "15m,30m,1h,2h,4h,6h,12h").split(",")
R = []
print("B = A +", ov)
print("%-8s %-4s | A: %4s %8s %6s | B: %4s %8s %6s" % ("pair", "tf", "n", "net%", "dd%", "n", "net%", "dd%"))
for sym in pairs:
    for tf in tfs:
        df = pd.read_csv("/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)); now = int(df.ct.iloc[-1]) + 10 ** 6
        P = L.base_params(sym, tf); pre = cs.prepare(df, now)
        TA = cs.simulate(df, now, P, pre=pre); TB = cs.simulate(df, now, dict(P, **ov), pre=pre)
        a, b = L.metrics(TA), L.metrics(TB)
        R.append((sym, tf, a, b, TA, TB))
        print("%-8s %-4s | %4d %+8.1f %6.1f | %4d %+8.1f %6.1f" % (sym, tf, a["n"], a["net"], a["dd"], b["n"], b["net"], b["dd"]), flush=True)
def summ(name, rows):
    if not rows: return
    na = [r[2]["net"] for r in rows]; nb = [r[3]["net"] for r in rows]
    print("%-10s combos %2d | A: sum %+8.1f median %+7.1f positive %2d | B: sum %+8.1f median %+7.1f positive %2d | maxDD median A %.1f B %.1f" % (
        name, len(rows), sum(na), statistics.median(na), sum(1 for x in na if x > 0), sum(nb), statistics.median(nb), sum(1 for x in nb if x > 0),
        statistics.median(r[2]["dd"] for r in rows), statistics.median(r[3]["dd"] for r in rows)))
print()
summ("all TF", R)
summ("from 1h", [r for r in R if r[1] in ("1h", "2h", "4h", "6h", "12h")])
summ("from 2h", [r for r in R if r[1] in ("2h", "4h", "6h", "12h")])
summ("under 1h", [r for r in R if r[1] in ("15m", "30m")])
for sym in pairs:
    summ(sym, [r for r in R if r[0] == sym])
# причины выхода (от 2h)
def reasons(idx):
    d = {}
    for r in R:
        if r[1] in ("2h", "4h", "6h", "12h"):
            for x in r[idx]:
                z = d.setdefault(x["reason"], [0, 0.0]); z[0] += 1; z[1] += x["net"]
    return d
ra, rb = reasons(4), reasons(5)
print("\nexit reasons (from 2h) A -> B: n / sum net")
for k in sorted(set(ra) | set(rb)):
    print("  %-14s %4d / %+8.1f  ->  %4d / %+8.1f" % (k.encode("ascii", "ignore").decode() or "reason", ra.get(k, [0, 0])[0], ra.get(k, [0, 0])[1], rb.get(k, [0, 0])[0], rb.get(k, [0, 0])[1]))
