"""classic_entry2.py — варианты ТОЧКИ ВХОДА на одной паре (по умолчанию ZECUSDT 15m). Выход и разворот по обратному пересечению EMA20/EMA200 общие.
Запуск: python classic_entry2.py [SYMBOL] [PAGES]. Подбор — первые 60% времени, проверка — последние 40%."""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
import classic_analysis as an

SYM = sys.argv[1] if len(sys.argv) > 1 else "ZECUSDT"
PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 40
STEP = 900 * 1000
now = int(time.time() * 1000)


def fetch(tf, pages):
    parts, end = [], None
    for _ in range(pages):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (SYM, tf) + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
        if len(d) < 1000: break
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


df = fetch("15m", PAGES); d4 = fetch("4h", 4)
pre = cs.prepare(df, now)
M, o, h, l, c, e20, e200, atr = pre["M"], pre["o"], pre["h"], pre["l"], pre["c"], pre["e20"], pre["e200"], pre["atr"]
ct = df.ct.values
START = int(df.t.iloc[0]) + 450 * STEP
SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")
print("%s 15m: %d свечей, оценка %s..%s, подбор до %s" % (SYM, len(df), d0(START), d0(now), d0(SPLIT)))

c4 = d4.iloc[:-1] if d4.ct.iloc[-1] > now else d4
c4 = c4.reset_index(drop=True)
x50, x200 = an.ema(c4.c, 50).values, an.ema(c4.c, 200).values
sc4v = (np.where(c4.c.values > x200, 1, -1) + np.where(x50 > x200, 1, -1)).astype(float)
idx4 = np.searchsorted(c4.ct.values, ct[:M], side="right") - 1
SC4 = np.where(idx4 >= 0, sc4v[np.clip(idx4, 0, None)], 0.0)
W = cs.PARAMS["warmup"]
trend = np.where(e20[:M] > e200[:M], 1, -1)
cross_i = [i for i in range(1, M) if (e20[i - 1] - e200[i - 1]) * (e20[i] - e200[i]) <= 0 and trend[i] != trend[i - 1]]
since = np.zeros(M, int)
for i in range(1, M):
    since[i] = 0 if trend[i] != trend[i - 1] else since[i - 1] + 1


def sig_confirm(k):
    out = {}
    for i in range(W, M):
        if since[i] == k:
            if trend[i] == 1 and c[i] > e20[i]: out[i] = "L"
            elif trend[i] == -1 and c[i] < e20[i]: out[i] = "S"
    return out


def sig_pullback(minbars):
    out = {}
    for i in range(W, M):
        if since[i] < minbars: continue
        if trend[i] == 1 and l[i] <= e20[i] < c[i] and c[i] > o[i]: out[i] = "L"
        elif trend[i] == -1 and h[i] >= e20[i] > c[i] and c[i] < o[i]: out[i] = "S"
    return out


def sig_donchian(n):
    out = {}
    for i in range(max(W, n), M):
        if trend[i] == 1 and c[i] > h[i - n:i].max(): out[i] = "L"
        elif trend[i] == -1 and c[i] < l[i - n:i].min(): out[i] = "S"
    return out


VAR = [
    ("0 пересечение (как есть)", None, None),
    ("1 пересечение + 4h не против", None, lambda side, i: SC4[i] * (1 if side == "L" else -1) >= 0),
    ("2 подтверждение: +2 свечи после пересечения", sig_confirm(2), None),
    ("3 подтверждение: +8 свечей после пересечения", sig_confirm(8), None),
    ("4 откат к EMA20 (тренд ≥3 свечей)", sig_pullback(3), None),
    ("5 откат к EMA20 (тренд ≥12 свечей)", sig_pullback(12), None),
    ("6 пробой Donchian 48 (12 ч)", sig_donchian(48), None),
    ("7 пробой Donchian 96 (24 ч)", sig_donchian(96), None),
]
EXITS = [
    ("выход: стоп prev≥1.5%, БУ+1%, без трейла", dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, be_trigger=1.0, trail_mode="none")),
    ("выход: то же + трейл 3 ATR", dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, be_trigger=1.0, trail_mode="atr", trail_dist=3.0)),
]


def stat(T):
    n = len(T)
    if not n: return None
    net = sum(x["net"] for x in T)
    q = {}
    for x in T:
        k = d0(x["t_in"])[:7]; q[k] = q.get(k, 0) + x["net"]
    ins = [x for x in T if x["t_in"] < SPLIT]; oos = [x for x in T if x["t_in"] >= SPLIT]
    side = {"L": 0.0, "S": 0.0}
    for x in T: side[x["side"]] += x["net"]
    return (n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T),
            net - sum(sorted((x["net"] for x in T), reverse=True)[:5]),
            sum(x["net"] for x in ins), len(ins), sum(x["net"] for x in oos), len(oos),
            sum(v > 0 for v in q.values()), len(q), side["L"], side["S"])


for en, P in EXITS:
    print("\n=== " + en)
    print("%-46s %4s %7s %6s %4s %7s %7s %12s %12s %6s %7s %7s" % ("вход", "n", "net%", "avg", "win", "gross", "без5", "подбор(n)", "проверка(n)", "мес+", "лонг", "шорт"))
    for name, sg_, flt in VAR:
        T = [x for x in cs.simulate(df, now, P, pre, flt, sg_) if x["t_in"] >= START]
        s = stat(T)
        if not s: print("%-46s n=0" % name); continue
        print("%-46s %4d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+7.1f(%3d) %+7.1f(%3d) %2d/%-2d %+7.1f %+7.1f" % ((name,) + s))
