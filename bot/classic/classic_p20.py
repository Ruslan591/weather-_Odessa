"""classic_p20.py — вход «паттерн разворота → первое закрытие за EMA20», выход трейлингом под предыдущей свечой (правила пользователя), ZEC 15m.
Запуск: python classic_p20.py [SYMBOL] [PAGES]"""
import json, os, sys, time, datetime, itertools, warnings, urllib.request
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
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
print("%s 15m, %d свечей; подбор до %s, проверка после; паттернов с признаками: %d" % (SYM, len(df), datetime.datetime.fromtimestamp(SPLIT / 1000, datetime.UTC).date(), len(pre["pfeat"])))
hdr = "%-50s %5s %7s %6s %4s %7s %7s %12s %12s %6s %7s %7s" % ("вариант", "n", "net%", "avg", "win", "gross", "без5", "подбор", "проверка", "мес+", "лонг", "шорт")
res = []


def run(lab, **kw):
    P = dict(cs.PANEL, entry_mode="pattern20", **kw)
    T = [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]
    n = len(T)
    if not n: print("%-50s n=0" % lab); return None
    net = sum(x["net"] for x in T); q = {}
    for x in T: q[d0(x["t_in"])] = q.get(d0(x["t_in"]), 0) + x["net"]
    ins = sum(x["net"] for x in T if x["t_in"] < SPLIT)
    sd = {"L": 0.0, "S": 0.0}
    for x in T: sd[x["side"]] += x["net"]
    ex5 = net - sum(sorted((x["net"] for x in T), reverse=True)[:5])
    print("%-50s %5d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+12.1f %+12.1f %2d/%-2d %+7.1f %+7.1f" % (
        lab, n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T), ex5, ins, net - ins,
        sum(v > 0 for v in q.values()), len(q), sd["L"], sd["S"]))
    res.append((lab, kw, net, ins, net - ins, ex5, n))
    return T


FL = ("none", "level", "volume", "extreme", "level+volume")
for be in (1.5, 1.0):
    print("\n== БУ при +%.1f%%, замок 0.4%%, стоп за свечой ≥1.5%%; выход — паттерн-трейлинг под предыдущей свечой" % be)
    print(hdr)
    for flt in FL:
        for k in (6, 12, 24):
            for rev in (True, False):
                run("%s | K=%d | разворот=%s" % (flt, k, "да" if rev else "нет"), pat_mode="trail", arm_k=k, pat_filter=flt, rev_exit=rev, be_trigger=be, be_lock=0.4)
print("\n== Для сравнения: те же входы, но без паттерн-трейлинга (выход только стоп/БУ/разворот), БУ 1.5%")
print(hdr)
for flt in ("none", "level"):
    for k in (12,):
        run("%s | K=%d | без паттерн-трейлинга, разворот=да" % (flt, k), pat_mode="off", arm_k=k, pat_filter=flt, rev_exit=True, be_trigger=1.5, be_lock=0.4)
rob = [r for r in res if r[3] > 0 and r[4] > 0 and r[5] > 0]
print("\nвариантов %d; устойчивых (плюс на подборе, на проверке и без 5 лучших сделок): %d" % (len(res), len(rob)))
for r in sorted(rob, key=lambda r: -(r[3] + r[4]))[:8]:
    print("  %-50s net %+.1f подбор %+.1f проверка %+.1f без5 %+.1f n=%d" % (r[0], r[2], r[3], r[4], r[5], r[6]))
lo, hi = int(pd.Timestamp("2026-10-14 12:00", tz="UTC").value // 10**6), int(pd.Timestamp("2026-10-16 00:00", tz="UTC").value // 10**6)
for title, kw in (("все паттерны, K=12, паттерн-трейлинг, разворот=да, БУ 1.5%/0.4%", dict(pat_mode="trail", arm_k=12, pat_filter="none", rev_exit=True, be_trigger=1.5, be_lock=0.4)),):
    P = dict(cs.PANEL, entry_mode="pattern20", **kw)
    T = [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]
    print("\nПример 14–16.10 (UTC+3): " + title)
    for x in T:
        if x["t_out"] >= lo and x["t_in"] <= hi:
            print("  %s %s %.1f -> %s %.1f  %-22s net %+.2f%% %s" % ("ШОРТ" if x["side"] == "S" else "ЛОНГ", L3(x["t_in"]), x["p_in"], L3(x["t_out"]), x["p_out"], x["reason"], x["net"], "(открыта)" if x["open"] else ""))
