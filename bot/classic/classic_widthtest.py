"""classic_widthtest.py — как предел ширины канала робота (tl_max_w, в ATR) меняет сделки на реальной истории пары."""
import sys, os, json
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
sym = sys.argv[1] if len(sys.argv) > 1 else "NEARUSDT"; tf = sys.argv[2] if len(sys.argv) > 2 else "2h"
try:
    c = json.load(open("/opt/trading-bot/classic/config.json"))
    print("config.json: tl_min_w=%s tl_max_w=%s tf=%s stages=%s" % (c.get("tl_min_w"), c.get("tl_max_w"), c.get("tf"), [x.get("t") for x in c.get("stages", []) if x.get("t")]))
except Exception as e:
    print("config err", e)
df = pd.read_csv("/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)); now = int(df.ct.iloc[-1]) + 10 ** 6
P0 = L.base_params(sym, tf); pre = cs.prepare(df, now)
warm = int(P0.get("warmup", 200)); t0, t1 = int(df.t.iloc[warm]), int(df.t.iloc[-1]); cut = int(t0 + 0.7 * (t1 - t0))
atr = pre.get("atr")
print("%-6s %5s %9s %9s | подбор: сд %%net  DD | проверка: сд %%net  DD" % ("maxW", "сд", "шир.ср,%", "шир.макс,%"))
for mw in [14, 10, 8, 6, 5, 4, 3]:
    P = dict(P0, tl_max_w=float(mw)); T = cs.simulate(df, now, P, pre=pre); pk = cs.pack(T)
    w = [(x["chl"][1] - x["chl"][0]) / x["p_in"] * 100 for x in pk if x.get("chl")]
    a, b = L.metrics(T, None, cut), L.metrics(T, cut, None)
    print("%-6s %5d %9.1f %9.1f | %3d %+7.1f %5.1f | %3d %+7.1f %5.1f" % (mw, len(T), np.mean(w) if w else 0, max(w) if w else 0, a["n"], a["net"], a["dd"], b["n"], b["net"], b["dd"]))
