"""classic_tfcheck.py — проверка, что все таймфреймы конструктора (1m…1d) грузятся и считаются: ZEC, 2 страницы свечей, правила EMA50+StochRSI (пробой, цель 3R)."""
import json, os, sys, time, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
now = int(time.time() * 1000)
STG = [{"t": "pattern", "p": 0, "w": 0, "f": "none"}, {"t": "ema50_trend", "p": 0, "w": 1, "f": "none"}, {"t": "ema50_pullback", "p": 0, "w": 1, "f": "none"}, {"t": "stochrsi_cross", "p": 0, "w": 1, "f": "none"}]
for tf in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"):
    try:
        parts, end = [], None
        for _ in range(2):
            u = "https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval=%s&limit=1000" % tf + ("&endTime=%d" % end if end else "")
            d = json.load(urllib.request.urlopen(u, timeout=20)); parts.insert(0, d); end = int(d[0][0]) - 1
        df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]; df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
        for k in "ohlcv": df[k] = df[k].astype(float)
        df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
        P = dict(cs.PARAMS, tf=tf, entry_mode="stages", entry_trigger="breakout", stop_mode="sig3", tp_r=3.0, rev_exit=False, be_trigger=30.0, be_lock=0.0, trail_mode="none", pat_mode="off", fee=0.09, stages=STG)
        tr = cs.simulate(df, now, P)
        span = (df.t.iloc[-1] - df.t.iloc[0]) / 86400000
        print("%-4s свечей %d (глубина %.1f сут) | сделок %d | ср. риск %.2f%% | сигналов-стадий OK" % (tf, len(df), span, len(tr), np.mean([x["risk"] for x in tr]) if tr else float("nan")), flush=True)
    except Exception as e:
        print("%-4s ОШИБКА: %s" % (tf, repr(e)[:200]), flush=True)
print("ГОТОВО", flush=True)
