"""classic_rules.py — правила пользователя (вход по закрытию за EMA20, паттерн включает трейлинг под предыдущей свечой, БУ с замком) на одной паре.
Запуск: python classic_rules.py [SYMBOL] [PAGES]"""
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
print("%s 15m, %d свечей; подбор до %s, проверка после" % (SYM, len(df), datetime.datetime.fromtimestamp(SPLIT / 1000, datetime.UTC).date()))
hdr = "%-52s %5s %7s %6s %4s %7s %7s %12s %12s %6s %7s %7s" % ("вариант", "n", "net%", "avg", "win", "gross", "без5", "подбор", "проверка", "мес+", "лонг", "шорт")


def run(lab, **kw):
    P = dict(cs.PANEL, **kw)
    T = [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]
    n = len(T)
    if not n: print("%-52s n=0" % lab); return None
    net = sum(x["net"] for x in T); q = {}
    for x in T: q[d0(x["t_in"])] = q.get(d0(x["t_in"]), 0) + x["net"]
    ins = sum(x["net"] for x in T if x["t_in"] < SPLIT)
    sd = {"L": 0.0, "S": 0.0}
    for x in T: sd[x["side"]] += x["net"]
    print("%-52s %5d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+12.1f %+12.1f %2d/%-2d %+7.1f %+7.1f" % (
        lab, n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, sum(x["gross"] for x in T),
        net - sum(sorted((x["net"] for x in T), reverse=True)[:5]), ins, net - ins, sum(v > 0 for v in q.values()), len(q), sd["L"], sd["S"]))
    return T


EM = {"cross200": "пересечение EMA20×EMA200", "close20": "закрытие за EMA20 после пересечения", "state20": "любое закрытие за EMA20"}
for be in (1.5, 1.0):
    print("\n== БУ при +%.1f%%, замок 0.4%%, стоп за свечой ≥1.5%% (подбор — первые 60%% времени)" % be)
    print(hdr)
    for em, pmode, rev in itertools.product(("cross200", "close20", "state20"), ("off", "trail"), (True, False)):
        run("%s | паттерн-%s | развор.=%s" % (em, "трейл" if pmode == "trail" else "нет", "да" if rev else "нет"),
            entry_mode=em, pat_mode=pmode, rev_exit=rev, be_trigger=be, be_lock=0.4)
print("\n== Правила пользователя (close20 + паттерн-трейл), стоп за свечой: влияние минимальной дистанции")
print(hdr)
for ms in (0.5, 1.0, 1.5, 2.5):
    for rev in (True, False):
        run("min стоп %.1f%% | развор.=%s" % (ms, "да" if rev else "нет"), entry_mode="close20", pat_mode="trail", rev_exit=rev, be_trigger=1.5, be_lock=0.4, min_stop_pct=ms)
