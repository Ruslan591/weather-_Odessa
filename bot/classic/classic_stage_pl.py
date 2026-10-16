"""classic_stage_pl.py — полные сделки (с выходом, безубытком, паттерн-трейлингом) для лучших цепочек уровней фильтра входа, ZEC 15m."""
import json, os, sys, time, datetime, warnings, urllib.request
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
SYM = "ZECUSDT"; STEP = 900 * 1000; now = int(time.time() * 1000)
parts, end = [], None
for _ in range(40):
    u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=15m&limit=1000" % SYM + ("&endTime=%d" % end if end else "")
    d = json.load(urllib.request.urlopen(u, timeout=20))
    if not d: break
    parts.insert(0, d); end = int(d[0][0]) - 1
df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
pre = cs.prepare(df, now)
START = int(df.t.iloc[0]) + 450 * STEP; SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m")
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
TR = {"t": "pattern", "f": "none"}; C20 = {"t": "close_ema20", "w": 12}
SETS = [
    ("паттерн → закрытие за EMA20", [TR, C20]),
    ("паттерн → закр. за EMA20 → объём ≥1.2×", [TR, C20, {"t": "volume", "p": 1.2, "w": 6}]),
    ("паттерн → закр. за EMA20 → сильное тело", [TR, C20, {"t": "strong_body", "p": 0.8, "w": 6}]),
    ("паттерн → закр. за EMA20 → слом структуры", [TR, C20, {"t": "break_swing", "w": 6}]),
    ("паттерн → сильное тело ≥0.8 ATR", [TR, {"t": "strong_body", "p": 0.8, "w": 12}]),
]
EXITS = [
    ("выход: паттерн-трейлинг, БУ 1.5/0.4", dict(pat_mode="trail", be_trigger=1.5, be_lock=0.4)),
    ("выход: без паттернов (стоп/БУ/разворот), БУ 1.5/0.4", dict(pat_mode="off", be_trigger=1.5, be_lock=0.4)),
    ("выход: трейл 3 ATR после БУ 1.5/0.4", dict(pat_mode="off", be_trigger=1.5, be_lock=0.4, trail_mode="atr", trail_dist=3.0)),
]
hdr = "%-44s %5s %7s %6s %4s %7s %7s %12s %12s %6s %7s %7s" % ("цепочка уровней", "n", "net%", "avg", "win", "gross", "без5", "подбор", "проверка", "мес+", "лонг", "шорт")
best = None
for en, ekw in EXITS:
    print("\n== " + en + "; стоп за свечой ≥1.5%, разворот по обратному сигналу = да")
    print(hdr)
    for name, st in SETS:
        P = dict(cs.PANEL, entry_mode="stages", stages=st, rev_exit=True, **ekw)
        T = [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]
        n = len(T)
        if not n: print("%-44s n=0" % name); continue
        net = sum(x["net"] for x in T); q = {}
        for x in T: q[d0(x["t_in"])] = q.get(d0(x["t_in"]), 0) + x["net"]
        ins = sum(x["net"] for x in T if x["t_in"] < SPLIT); sd = {"L": 0.0, "S": 0.0}
        for x in T: sd[x["side"]] += x["net"]
        ex5 = net - sum(sorted((x["net"] for x in T), reverse=True)[:5])
        print("%-44s %5d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+12.1f %+12.1f %2d/%-2d %+7.1f %+7.1f" % (
            name, n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T), ex5, ins, net - ins,
            sum(v > 0 for v in q.values()), len(q), sd["L"], sd["S"]), flush=True)
lo, hi = int(pd.Timestamp("2026-10-14 12:00", tz="UTC").value // 10**6), int(pd.Timestamp("2026-10-16 00:00", tz="UTC").value // 10**6)
P = dict(cs.PANEL, entry_mode="stages", stages=SETS[1][1], rev_exit=True, pat_mode="trail", be_trigger=1.5, be_lock=0.4)
print("\nПример 14–16.10 (UTC+3): паттерн → закр. за EMA20 → объём ≥1.2×, паттерн-трейлинг")
for x in cs.simulate(df, now, P, pre):
    if x["t_out"] >= lo and x["t_in"] <= hi:
        print("  %s %s %.1f -> %s %.1f  %-22s net %+.2f%% %s" % ("ШОРТ" if x["side"] == "S" else "ЛОНГ", L3(x["t_in"]), x["p_in"], L3(x["t_out"]), x["p_out"], x["reason"], x["net"], "(открыта)" if x["open"] else ""))
