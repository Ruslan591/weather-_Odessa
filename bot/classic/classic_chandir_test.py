"""classic_chandir_test.py [PAIRS] [TFS] -- compare channel-direction rule (chan_dir) off/on for bot channels (tl_both, old+fast).
Rule: ascending channel -> bounce long only, breakout short only; descending -> opposite. Run from a dir where the NEW classic_strategy.py is first in sys.path."""
import sys, os
sys.path.insert(0, os.environ.get("CD_DIR", "/opt/trading-bot/classic"))
sys.path.insert(1, "/opt/trading-bot/classic")
import pandas as pd
import classic_strategy as cs, classic_learn as L
pairs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["NEARUSDT", "SOLUSDT", "BTCUSDT", "ZECUSDT", "BNBUSDT"]
tfs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["15m", "1h", "2h", "4h"]
B = "/opt/trading-bot/classic/pairs"
print("strategy file:", cs.__file__, "has chan_dir:", hasattr(cs, "chan_dir"), flush=True)
acc = {}
for sym in pairs:
    for tf in tfs:
        f1 = "%s/%s/klines_%s.csv" % (B, sym, tf)
        if not os.path.exists(f1):
            continue
        df = pd.read_csv(f1); now = int(df.ct.iloc[-1]) + 10 ** 6
        pre0 = None
        for src in ("old", "fast"):
            for cd in (False, True):
                P0 = L.base_params(sym, tf)
                stg = [{"t": "tl_both", "p": 0, "w": 0, "f": "none"}]
                P = dict(P0, tl_src=src, stages=stg, entry_mode="stages", stop_mode="prev", tp_mode="r", tp_r=2.0, sym=sym, chan_dir=cd)
                try:
                    pre = cs.prepare(df, now)
                    T = cs.simulate(df, now, P, pre=pre)
                    m = L.metrics(T, None, None)
                except Exception as e:
                    print(sym, tf, src, cd, "err", repr(e)[:120], flush=True); continue
                r = acc.setdefault((src, cd), {"n": 0, "net": 0.0, "plus": 0, "cells": 0, "dd": 0.0})
                r["n"] += m["n"]; r["net"] += m["net"]; r["cells"] += 1; r["plus"] += 1 if m["net"] > 0 else 0; r["dd"] = max(r["dd"], m["dd"])
                print("%s %s src=%s chan_dir=%s trades=%d net=%+.1f dd=%.1f" % (sym, tf, src, cd, m["n"], m["net"], m["dd"]), flush=True)
print("=== SUMMARY (sum over pairs x tfs) ===")
for k in sorted(acc):
    r = acc[k]
    print("src=%s chan_dir=%s trades=%d net%%=%+.1f cells_plus=%d/%d maxDD=%.1f" % (k[0], k[1], r["n"], r["net"], r["plus"], r["cells"], r["dd"]))
