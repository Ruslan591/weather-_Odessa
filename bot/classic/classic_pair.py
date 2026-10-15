"""classic_pair.py — настройка выхода под ОДНУ пару. Запуск: python classic_pair.py SYMBOL TF PAGES
Подбор по первым 60% времени (in-sample), проверка на последних 40% (out-of-sample)."""
import json, os, sys, time, itertools, datetime, warnings, urllib.request
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs

SYM = sys.argv[1] if len(sys.argv) > 1 else "ZECUSDT"
TF = sys.argv[2] if len(sys.argv) > 2 else "15m"
PAGES = int(sys.argv[3]) if len(sys.argv) > 3 else 20
STEP = {"15m": 900, "1h": 3600, "4h": 14400}[TF] * 1000
now = int(time.time() * 1000)


def fetch():
    parts, end = [], None
    for _ in range(PAGES):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (SYM, TF) + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
        if len(d) < 1000: break
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


df = fetch(); pre = cs.prepare(df, now)
START = int(df.t.iloc[0]) + 450 * STEP
SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")
print("%s %s: %d свечей, оценка %s..%s (%.0f сут), подбор до %s, проверка после" % (SYM, TF, len(df), d0(START), d0(now), (now - START) / 86400000, d0(SPLIT)))


def run(P):
    return [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]


def st(T):
    n = len(T)
    if not n: return None
    net = sum(x["net"] for x in T)
    ins = [x for x in T if x["t_in"] < SPLIT]; oos = [x for x in T if x["t_in"] >= SPLIT]
    q = {}
    for x in T:
        k = d0(x["t_in"])[:7]; q[k] = q.get(k, 0) + x["net"]
    return dict(n=n, net=net, avg=net / n, win=sum(x["net"] > 0 for x in T) / n * 100, gross=sum(x["gross"] for x in T),
                ex5=net - sum(sorted((x["net"] for x in T), reverse=True)[:5]),
                ins=sum(x["net"] for x in ins), nins=len(ins), oos=sum(x["net"] for x in oos), noos=len(oos),
                mp=sum(v > 0 for v in q.values()), mn=len(q), risk=sum(x["risk"] for x in T) / n)


def lab(P):
    sm = "pivot" if P["stop_mode"] == "pivot" else "prev≥%s%s" % ("%.1f%%" % P["min_stop_pct"], "/%.1fATR" % P["min_stop_atr"] if P["min_stop_atr"] else "")
    tr = {"none": "без трейла", "pct": "трейл %.1f%%" % P["trail_dist"], "atr": "трейл %.0fATR" % P["trail_dist"], "pivot": "трейл pivot"}[P["trail_mode"]]
    be = "БУ ATR%.0f" % P["be_atr"] if P.get("be_atr") else "БУ+%.1f" % P["be_trigger"]
    return "%-18s %-9s %-12s" % (sm, be, tr)


def show(title, rows):
    print("\n== " + title)
    print("%-42s %4s %7s %6s %4s %7s %7s %12s %12s %5s" % ("вариант", "n", "net%", "avg", "win", "gross", "без5", "подбор(n)", "проверка(n)", "мес+"))
    for P, s in rows:
        print("%-42s %4d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+7.1f(%3d) %+7.1f(%3d) %2d/%-2d" % (lab(P), s["n"], s["net"], s["avg"], s["win"], s["gross"], s["ex5"], s["ins"], s["nins"], s["oos"], s["noos"], s["mp"], s["mn"]))


M = lambda **k: dict(cs.PARAMS, **k)
named = [
    ("Исходная постановка: стоп pivot, БУ+1%, трейл pivot", M(stop_mode="pivot", be_trigger=1.0, trail_mode="pivot")),
    ("Панель сейчас: prev≥0.3%, БУ+1%, трейл 1ATR", M(stop_mode="prev", min_stop_pct=0.3, be_trigger=1.0, trail_mode="atr", trail_dist=1.0)),
    ("Конфиг C: prev≥1.5%, БУ+1.5%, трейл 4ATR", M(stop_mode="prev", min_stop_pct=1.5, be_trigger=1.5, trail_mode="atr", trail_dist=4.0)),
]
rows = []
for nm, P in named:
    s = st(run(P))
    if s: rows.append((P, s))
show("ОПОРНЫЕ КОНФИГИ", rows)
stops = [("pivot", 0, 0)] + [("prev", p, 0) for p in (0.3, 0.6, 1.0, 1.5, 2.5)] + [("prev", 0.3, 2.0)]
trails = [("none", 0)] + [("pct", d) for d in (0.5, 1.0, 2.0)] + [("atr", d) for d in (1, 2, 3, 4)] + [("pivot", 0)]
allr = []
for (sm, mp, ma), be, (tm, td) in itertools.product(stops, (0.5, 1.0, 2.0, 3.0), trails):
    P = M(stop_mode=sm, min_stop_pct=mp, min_stop_atr=ma, be_trigger=be, trail_mode=tm, trail_dist=td)
    s = st(run(P))
    if s: allr.append((P, s))
print("\nвариантов: %d" % len(allr))
ranked = sorted(allr, key=lambda r: -r[1]["ins"])
show("ТОП-10 по результату на ПОДБОРЕ (смотри колонку «проверка» — это отложенные 40%)", ranked[:10])
show("ТОП-5 по результату на ПРОВЕРКЕ (только для понимания разброса)", sorted(allr, key=lambda r: -r[1]["oos"])[:5])
both = [r for r in allr if r[1]["ins"] > 0 and r[1]["oos"] > 0]
print("\nв плюсе и на подборе, и на проверке: %d из %d" % (len(both), len(allr)))
show("ЛУЧШИЕ из «в плюсе в обеих частях» по сумме", sorted(both, key=lambda r: -(r[1]["ins"] + r[1]["oos"]))[:8])
import statistics
print("\nмедиана результата по всем вариантам: подбор %+.1f, проверка %+.1f" % (statistics.median(r[1]["ins"] for r in allr), statistics.median(r[1]["oos"] for r in allr)))
