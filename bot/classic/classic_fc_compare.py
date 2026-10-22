"""classic_fc_compare.py SYM TF — сделки по tl_bounce/tl_breakout: прежние каналы робота vs быстрый канал (tl_src=fast) на истории пары."""
import sys, json
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
sym = sys.argv[1] if len(sys.argv) > 1 else "NEARUSDT"; tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
df = pd.read_csv("/opt/trading-bot/classic/pairs/%s/klines_%s.csv" % (sym, tf)); now = int(df.ct.iloc[-1]) + 10 ** 6
P0 = L.base_params(sym, tf); pre = cs.prepare(df, now)
warm = int(P0.get("warmup", 200)); t0, t1 = int(df.t.iloc[warm]), int(df.t.iloc[-1]); cut = int(t0 + 0.7 * (t1 - t0))
print(sym, tf, "свечей", len(df))
print("%-26s %5s | подбор: сд  %%net   DD | проверка: сд  %%net   DD" % ("вариант", "сд"))
for trig in ["tl_bounce", "tl_breakout"]:
    for src in ["old", "fast"]:
        P = dict(P0, tl_src=src, stages=[{"t": trig, "p": 0, "w": 0, "f": "none"}], entry_mode="stages", stop_mode="channel", tp_mode="channel")
        try:
            T = cs.simulate(df, now, P, pre=pre)
            a, b = L.metrics(T, None, cut), L.metrics(T, cut, None)
            print("%-26s %5d | %3d %+7.1f %5.1f | %3d %+7.1f %5.1f" % (trig + " " + src, len(T), a["n"], a["net"], a["dd"], b["n"], b["net"], b["dd"]))
        except Exception as e:
            print(trig, src, "ошибка:", repr(e)[:200])
