"""classic_be.py — порог безубытка и «замок» (стоп = вход ± be_lock%), ZEC 15m. Запуск: python classic_be.py [SYMBOL] [PAGES]"""
import json, os, sys, time, datetime, warnings, urllib.request
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
SYM = sys.argv[1] if len(sys.argv) > 1 else "ZECUSDT"; PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 40
STEP = 900 * 1000; now = int(time.time() * 1000)
parts, end = [], None
for _ in range(PAGES):
    u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=15m&limit=1000" % SYM + ("&endTime=%d" % end if end else "")
    d = json.load(urllib.request.urlopen(u, timeout=20))
    if not d: break
    parts.insert(0, d); end = int(d[0][0]) - 1
    if len(d) < 1000: break
df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
pre = cs.prepare(df, now)
START = int(df.t.iloc[0]) + 450 * STEP; SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m")
base = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, trail_mode="none", trail_dist=0.0, pat_exit=False)
print("ZEC 15m, без паттернов; БУ = при плюсе ≥ порога стоп переносится на вход ± замок")
print("%-26s %4s %7s %6s %4s %7s %7s %12s %12s %6s %7s" % ("порог / замок", "n", "net%", "avg", "win", "gross", "без5", "подбор", "проверка", "мес+", "БУ-вых"))
for be in (1.0, 1.5, 2.0, 3.0, 5.0):
    for lk in (0.0, 0.12, 0.2, 0.3):
        T = [x for x in cs.simulate(df, now, dict(base, be_trigger=be, be_lock=lk), pre) if x["t_in"] >= START]
        n = len(T); net = sum(x["net"] for x in T); q = {}
        for x in T: q[d0(x["t_in"])] = q.get(d0(x["t_in"]), 0) + x["net"]
        ins = sum(x["net"] for x in T if x["t_in"] < SPLIT); oos = net - ins
        bes = [x for x in T if x["reason"] == "безубыток"]
        print("БУ+%.1f%% / замок %.2f%%      %4d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+12.1f %+12.1f %2d/%-2d %3d (%+.2f)" % (
            be, lk, n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T),
            net - sum(sorted((x["net"] for x in T), reverse=True)[:5]), ins, oos, sum(v > 0 for v in q.values()), len(q),
            len(bes), (sum(x["net"] for x in bes) / len(bes)) if bes else 0))
