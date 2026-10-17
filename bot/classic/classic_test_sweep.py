"""Проверка: фильтр pat_filter=sweep в classic_strategy совпадает с независимой реализацией (как в classic_sess.py)."""
import json, os, sys, time, urllib.request, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
now = int(time.time() * 1000)
parts, end = [], None
for _ in range(6):
    u = "https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval=15m&limit=1000" + ("&endTime=%d" % end if end else "")
    d = json.load(urllib.request.urlopen(u, timeout=20)); parts.insert(0, d); end = int(d[0][0]) - 1
df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
pre = cs.prepare(df, now)
def ind(N):
    def p(i, side):
        l, h, c = pre["l"], pre["h"], pre["c"]
        if i < N + 3: return False
        if side == "L":
            prev = l[i - 3 - N:i - 2].min(); return l[i - 2:i + 1].min() < prev and c[i] > prev
        prev = h[i - 3 - N:i - 2].max(); return h[i - 2:i + 1].max() > prev and c[i] < prev
    return p
base = cs.stage_signals(pre, dict(cs.PARAMS, stages=[{"t": "pattern", "f": "none"}]))
for name, N in (("sweep", 48), ("sweep16", 16)):
    got = cs.stage_signals(pre, dict(cs.PARAMS, stages=[{"t": "pattern", "f": name}]))
    exp = {i: v for i, v in base.items() if ind(N)(i, v[0])}
    print(name, "в стратегии:", len(got), "независимо:", len(exp), "совпадают:", set(got) == set(exp), "| всего паттернов:", len(base))
print(len(pre["pfeat"][0]) if pre["pfeat"] else "нет pfeat")
