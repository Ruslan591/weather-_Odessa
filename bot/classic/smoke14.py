import json, sys, time, warnings, urllib.request
warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/trading-bot/classic")
import pandas as pd, classic_strategy as cs
d = json.load(urllib.request.urlopen("https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval=4h&limit=1000", timeout=20))
df = pd.DataFrame(d).iloc[:, [0,1,2,3,4,5,6]]; df.columns = ["t","o","h","l","c","v","ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
USER = dict(tf="4h", entry_mode="stages", entry_trigger="open", tp_r=0.0, max_bars=0, rev_exit=True, stop_mode="prev", min_stop_pct=3.0, min_stop_atr=3.0, be_trigger=1.8, be_lock=1.1, trail_mode="none", trail_dist=0.7, pat_mode="trail", pat_min=2.0, fee=0.05, pat_filter="none")
now = int(time.time() * 1000)
def st(*ts): return [{"t": t, "p": 0, "w": 3 if i else 12, "f": "none"} for i, t in enumerate(ts)]
for name, stg in (("cross50", st("cross50")), ("cross200", st("cross200")), ("cross20", st("cross20")), ("tl_breakout (канал/треугольник робота)", st("tl_breakout")), ("tl_bounce", st("tl_bounce")),
                  ("pattern → ema200_side + ema50_trend", st("pattern", "ema200_side", "ema50_trend")), ("pattern → macd_sign + stoch_dir (как у пользователя)", st("pattern", "macd_sign", "stoch_dir"))):
    try:
        tr = cs.simulate(df, now, dict(cs.PARAMS, **USER, sym="ZECUSDT", stages=stg))
        print("OK  %-52s сделок %2d, net %+7.2f%%" % (name, len(tr), sum(x["net"] for x in tr)))
    except Exception as e: print("ERR", name, repr(e)[:150])
