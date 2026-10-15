"""classic_sweep.py — перебор параметров стопа/безубытка/трейлинга на истории Binance. Запуск: python classic_sweep.py [tf=15m] [pages=3]"""
import json, os, sys, time, itertools, urllib.request
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs

TF = sys.argv[1] if len(sys.argv) > 1 else "15m"
PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 3
STEP = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}[TF] * 1000
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    pairs = json.load(open(os.path.join(HERE, "pairs.json")))
except Exception:
    pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "ZECUSDT"]


def fetch(sym):
    parts, end = [], None
    for _ in range(PAGES):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (sym, TF) + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


now = int(time.time() * 1000)
data = {}
for s in pairs:
    try:
        df = fetch(s); data[s] = (df, cs.prepare(df, now))
    except Exception as e:
        print("skip", s, e)
span_d = (now - min(d[0].t.iloc[0] for d in data.values())) / 86400000
print("pairs", len(data), "history days %.1f" % span_d)
START = max(d[0].t.iloc[0] for d in data.values()) + 450 * STEP  # после прогрева EMA200
print("TF", TF, "оценка с", time.strftime("%Y-%m-%d", time.gmtime(START / 1000)), "(%.0f суток)" % ((now - START) / 86400000))
LAST10 = now - 240 * 3600 * 1000
MID = (START + now) // 2


def run(P):
    res = []
    for s, (df, pre) in data.items():
        for x in cs.simulate(df, now, P, pre):
            if x["t_in"] >= START:
                x["sym"] = s; res.append(x)
    return res


def stat(T):
    n = len(T)
    if not n: return None
    net = sum(x["net"] for x in T)
    byp = {}
    for x in T: byp[x["sym"]] = byp.get(x["sym"], 0) + x["net"]
    best = max(x["net"] for x in T)
    return dict(n=n, net=net, gross=sum(x["gross"] for x in T), win=sum(x["net"] > 0 for x in T) / n * 100,
                pp=sum(v > 0 for v in byp.values()), npair=len(byp), ex=net - best,
                h1=sum(x["net"] for x in T if x["t_in"] < MID), h2=sum(x["net"] for x in T if x["t_in"] >= MID),
                l10=sum(x["net"] for x in T if x["t_in"] >= LAST10), n10=sum(1 for x in T if x["t_in"] >= LAST10),
                risk=sum(x["risk"] for x in T) / n, clamp=sum(1 for x in T if x.get("clamped")) / n * 100)


combos = []
if TF == "15m":
    stops = [("pivot", 0, 0)] + [("prev", p, 0) for p in (0.2, 0.3, 0.5, 0.8)] + [("prev", 0.2, a) for a in (0.5, 1.0)]
    trails = [("none", 0)] + [("pct", d) for d in (0.3, 0.5, 0.75, 1.0, 1.5)] + [("atr", d) for d in (1, 1.5, 2, 3)] + [("pivot", 0)]
    bes = (0.5, 0.75, 1.0, 1.5)
else:
    stops = [("pivot", 0, 0)] + [("prev", p, 0) for p in (0.3, 0.6, 1.0, 1.5)] + [("prev", 0.3, a) for a in (0.5, 1.0)]
    trails = [("none", 0)] + [("pct", d) for d in (0.5, 1.0, 1.5, 2.0, 3.0)] + [("atr", d) for d in (1, 1.5, 2, 3, 4)] + [("pivot", 0)]
    bes = (0.5, 1.0, 1.5, 2.0, 3.0)
for (sm, mp, ma), be, (tm, td) in itertools.product(stops, bes, trails):
    combos.append(dict(cs.PARAMS, stop_mode=sm, min_stop_pct=mp, min_stop_atr=ma, be_trigger=be, trail_mode=tm, trail_dist=td))
rows = []
for P in combos:
    st = stat(run(P))
    if st: rows.append((P, st))


def label(P):
    sm = "pivot" if P["stop_mode"] == "pivot" else "prev(min %.1f%%%s)" % (P["min_stop_pct"], "+%.1fATR" % P["min_stop_atr"] if P["min_stop_atr"] else "")
    tr = {"none": "без трейла", "pct": "трейл %.2f%%" % P["trail_dist"], "atr": "трейл %.1fATR" % P["trail_dist"], "pivot": "трейл pivot"}[P["trail_mode"]]
    return "%-24s БУ+%.2f %-13s" % (sm, P["be_trigger"], tr)


def show(title, rr):
    print("\n==", title)
    print("%-52s %4s %7s %7s %4s %5s %7s %7s %7s %7s %5s" % ("вариант", "n", "net%", "gross%", "win", "пар+", "без_топ", "1пол", "2пол", "посл10д", "риск"))
    for P, s in rr:
        print("%-52s %4d %+7.1f %+7.1f %3.0f%% %2d/%-2d %+7.1f %+7.1f %+7.1f %+7.1f %5.2f" % (label(P), s["n"], s["net"], s["gross"], s["win"], s["pp"], s["npair"], s["ex"], s["h1"], s["h2"], s["l10"], s["risk"]))


cur = [r for r in rows if r[0]["stop_mode"] == "prev" and r[0]["be_trigger"] == 1.0 and r[0]["trail_mode"] == "atr" and r[0]["trail_dist"] == 1.0 and r[0]["min_stop_atr"] == 0]
show("БАЗА (как сейчас на панели: стоп prev, БУ+1%, трейл 1 ATR) — по мин. дистанции", cur)
base_old = [r for r in rows if r[0]["stop_mode"] == "pivot" and r[0]["be_trigger"] == 1.0 and r[0]["trail_mode"] in ("pivot", "none")]
show("Старая версия (стоп pivot, БУ+1%)", base_old)
robust = [r for r in rows if r[1]["h1"] > 0 and r[1]["h2"] > 0 and r[1]["ex"] > 0]
show("ТОП-12 по net среди устойчивых (плюс в обеих половинах и без лучшей сделки)", sorted(robust, key=lambda r: -r[1]["net"])[:12])
show("ТОП-8 по net вообще", sorted(rows, key=lambda r: -r[1]["net"])[:8])
print("\nвсего вариантов", len(rows), "из них устойчивых", len(robust))
if rows:
    st = stat(run(rows[0][0]))
    byside = {}
    for x in run(dict(cs.PARAMS)):
        byside.setdefault(x["side"], []).append(x["net"])
    print("база по сторонам:", {k: (len(v), round(sum(v), 1)) for k, v in byside.items()})
