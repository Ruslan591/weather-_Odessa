"""classic_fc_filters.py TF [PAIRS,..] — быстрый канал (tl_bounce, tl_src=fast) + по одному подтверждающему фильтру; итог по парам: проверка (последние 30% истории)."""
import sys, os, json
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L
tf = sys.argv[1]
base = "/opt/trading-bot/classic/pairs"
pairs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["NEARUSDT"]
FILT = [None, ("ema200_side", 0, 0), ("ema50_trend", 0, 0), ("macd_sign", 0, 0), ("stoch_dir", 0, 0), ("rsi_band", 0, 0), ("pullback_ema20", 0, 0), ("ema50_slope", 0, 0),
        ("volume", 0, 6), ("strong_body", 0, 6), ("close_ema20", 0, 6), ("ema20_slope", 0, 6), ("macd_turn", 0, 6), ("break_trigger", 0, 6)]
acc = {}
for sym in pairs:
    fn = "%s/%s/klines_%s.csv" % (base, sym, tf)
    if not os.path.exists(fn):
        continue
    df = pd.read_csv(fn); now = int(df.ct.iloc[-1]) + 10 ** 6
    P0 = L.base_params(sym, tf); pre = cs.prepare(df, now)
    warm = int(P0.get("warmup", 200)); t0, t1 = int(df.t.iloc[warm]), int(df.t.iloc[-1]); cut = int(t0 + 0.7 * (t1 - t0))
    for f in FILT:
        stg = [{"t": "tl_bounce", "p": 0, "w": 0, "f": "none"}] + ([{"t": f[0], "p": f[1], "w": f[2], "f": "none"}] if f else [])
        P = dict(P0, tl_src="fast", stages=stg, entry_mode="stages", stop_mode="channel", tp_mode="channel", sym=sym)
        try:
            T = cs.simulate(df, now, P, pre=pre)
            a, b = L.metrics(T, None, cut), L.metrics(T, cut, None)
        except Exception as e:
            print(sym, f, "err", repr(e)[:120]); continue
        k = f[0] if f else "(без фильтра)"
        r = acc.setdefault(k, {"na": 0, "nta": 0.0, "nb": 0, "ntb": 0.0, "ddb": 0.0, "plus": 0, "pairs": 0})
        r["na"] += a["n"]; r["nta"] += a["net"]; r["nb"] += b["n"]; r["ntb"] += b["net"]; r["ddb"] = max(r["ddb"], b["dd"]); r["pairs"] += 1; r["plus"] += 1 if b["net"] > 0 else 0
    print(sym, tf, "готово", flush=True)
print("TF %s, пар %d | фильтр: подбор (сд, %%net) | проверка (сд, %%net, макс DD, пар в плюсе)" % (tf, len(pairs)))
for k, r in sorted(acc.items(), key=lambda kv: -kv[1]["ntb"]):
    print("%-16s %5d %+8.1f | %5d %+8.1f  DD%5.1f  %d/%d" % (k, r["na"], r["nta"], r["nb"], r["ntb"], r["ddb"], r["plus"], r["pairs"]))
