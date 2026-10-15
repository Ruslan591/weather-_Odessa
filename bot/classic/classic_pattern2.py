"""classic_pattern.py — выход по свечному паттерну разворота + вход после закрытия за EMA20 (идея пользователя), ZEC 15m.
Выход: лонг закрывается по медвежьему паттерну (падающая звезда, медвежье поглощение, вечерняя звезда), шорт — по бычьему (молот, бычье поглощение, утренняя звезда); исполнение по открытию следующей свечи.
Вход после паттерна: бычий паттерн «взводит» лонг, вход по открытию свечи после первого закрытия выше EMA20 (в пределах K свечей); медвежий — шорт, закрытие ниже EMA20. Входы по пересечению EMA20/EMA200 сохраняются.
Запуск: python classic_pattern.py [SYMBOL] [PAGES]"""
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
M, c, e20, e200 = pre["M"], pre["c"], pre["e20"], pre["e200"]
closed = df.iloc[:M].reset_index(drop=True)
ind = an.indicators(closed)
pats = an.detect_patterns(closed, ind)
bull, bear = set(), set()
for p in pats:
    if p["d"] > 0: bull.add(p["i"])
    elif p["d"] < 0: bear.add(p["i"])
START = int(df.t.iloc[0]) + 450 * STEP
SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
print("%s 15m: %d свечей, оценка %s..%s, подбор до %s; паттернов: бычьих %d, медвежьих %d" % (SYM, len(df), d0(START), d0(now), d0(SPLIT), len(bull), len(bear)))
W = cs.PARAMS["warmup"]


def cross_sigs():
    out = {}
    for i in range(W, M):
        pr, cu = e20[i - 1] - e200[i - 1], e20[i] - e200[i]
        if pr <= 0 < cu: out[i] = "L"
        elif pr >= 0 > cu: out[i] = "S"
    return out


def pat_sigs(K):
    out = {}
    for a in sorted(bull | bear):
        if a < W: continue
        up = a in bull
        for j in range(a + 1, min(a + 1 + K, M)):
            if (up and j in bear) or ((not up) and j in bull): break
            if (up and c[j] > e20[j]) or ((not up) and c[j] < e20[j]):
                out.setdefault(j, "L" if up else "S"); break
    return out


def exit_sigs():
    out = {}
    for i in bull: out[i] = "L"
    for i in bear: out.setdefault(i, "S")
    for i in bull & bear: out.pop(i, None)
    return out


EX = exit_sigs()
base = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, trail_mode="none", trail_dist=0.0, pat_exit=False)
BE1 = dict(base, be_trigger=1.0); NOBE = dict(base, be_trigger=999.0)
VAR = [("0 как сейчас (БУ+1%, без паттернов)", BE1, None)]
for pm in (3, 5, 8, 12):
    VAR += [("паттерн-выход при плюсе ≥%d%%, БУ+1%%" % pm, dict(BE1, pat_min=pm), EX),
            ("то же + перевход (K=12)", dict(BE1, pat_min=pm, rearm_k=12), EX),
            ("то же, без БУ + перевход (K=12)", dict(NOBE, pat_min=pm, rearm_k=12), EX)]


def stat(T):
    n = len(T)
    if not n: return None
    net = sum(x["net"] for x in T); q = {}
    for x in T:
        k = d0(x["t_in"])[:7]; q[k] = q.get(k, 0) + x["net"]
    ins = [x for x in T if x["t_in"] < SPLIT]; oos = [x for x in T if x["t_in"] >= SPLIT]
    sd = {"L": 0.0, "S": 0.0}
    for x in T: sd[x["side"]] += x["net"]
    pt = [x for x in T if x["reason"] == "паттерн"]
    return (n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T),
            net - sum(sorted((x["net"] for x in T), reverse=True)[:5]), sum(x["net"] for x in ins), len(ins),
            sum(x["net"] for x in oos), len(oos), sum(v > 0 for v in q.values()), len(q), len(pt), sum(x["net"] for x in pt))


print("%-44s %4s %7s %6s %4s %7s %7s %12s %12s %6s %5s" % ("вариант", "n", "net%", "avg", "win", "gross", "без5", "подбор(n)", "проверка(n)", "мес+", "паттерн-выходы"))
res = {}
for name, P, ex in VAR:
    T = [x for x in cs.simulate(df, now, P, pre, None, None, ex) if x["t_in"] >= START]
    res[name + str(P.get("pat_min")) + str(P.get("rearm_k")) + str(P["be_trigger"])] = T
    s = stat(T)
    print("%-44s %4d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+7.1f(%3d) %+7.1f(%3d) %2d/%-2d %3d шт %+7.1f" % ((name,) + s))
lo, hi = int(pd.Timestamp("2026-10-14 12:00", tz="UTC").value // 10**6), int(pd.Timestamp("2026-10-16 00:00", tz="UTC").value // 10**6)
for pm, be in ((5, 999.0), (8, 1.0)):
    P = dict(base, be_trigger=be, pat_min=pm, rearm_k=12)
    T = [x for x in cs.simulate(df, now, P, pre, None, None, EX) if x["t_in"] >= START]
    print("\nПример 14–15.10 (UTC+3): паттерн-выход при плюсе >= %d%%, БУ %s + перевход" % (pm, "нет" if be > 100 else "+1%"))
    for x in T:
        if x["t_out"] >= lo and x["t_in"] <= hi:
            print("  %s %s %.1f -> %s %.1f  %-10s net %+.2f%% %s" % ("ШОРТ" if x["side"] == "S" else "ЛОНГ", L3(x["t_in"]), x["p_in"], L3(x["t_out"]), x["p_out"], x["reason"], x["net"], "(открыта)" if x["open"] else ""))
