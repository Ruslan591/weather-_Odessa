"""classic_sweep.py — перебор параметров стопа/безубытка/трейлинга на истории Binance (15m, ~30 суток)."""
import json, os, sys, time, itertools, urllib.request
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs

PAGES = 3
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    pairs = json.load(open(os.path.join(HERE, "pairs.json")))
except Exception:
    pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "ZECUSDT"]


def fetch(sym):
    parts, end = [], None
    for _ in range(PAGES):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=15m&limit=1000" % sym + ("&endTime=%d" % end if end else "")
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
START = now - int(26 * 86400000)  # считаем сделки, открытые после прогрева (~26 суток)
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
stops = [("pivot", 0, 0)] + [("prev", p, 0) for p in (0.2, 0.3, 0.5, 0.8)] + [("prev", 0.2, a) for a in (0.5, 1.0)]
trails = [("none", 0)] + [("pct", d) for d in (0.3, 0.5, 0.75, 1.0, 1.5)] + [("atr", d) for d in (1, 1.5, 2, 3)] + [("pivot", 0)]
for (sm, mp, ma), be, (tm, td) in itertools.product(stops, (0.5, 0.75, 1.0, 1.5), trails):
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


base_old = [r for r in rows if r[0]["stop_mode"] == "pivot" and r[0]["be_trigger"] == 1.0 and r[0]["trail_mode"] in ("pivot", "none")]
show("ТЕКУЩАЯ версия (стоп pivot, БУ+1%) для сравнения", base_old)
robust = [r for r in rows if r[1]["h1"] > 0 and r[1]["h2"] > 0 and r[1]["ex"] > 0]
show("ТОП-15 по net среди устойчивых (плюс в обеих половинах периода и без лучшей сделки)", sorted(robust, key=lambda r: -r[1]["net"])[:15])
show("ТОП-8 по net вообще (без фильтра устойчивости)", sorted(rows, key=lambda r: -r[1]["net"])[:8])
print("\nвсего вариантов", len(rows), "из них устойчивых", len(robust))
# сравнение трейлингов при фиксированных stop=prev(min0.3), БУ+1.0
fx = [r for r in rows if r[0]["stop_mode"] == "prev" and r[0]["min_stop_pct"] == 0.3 and r[0]["min_stop_atr"] == 0 and r[0]["be_trigger"] == 1.0]
show("ТРЕЙЛИНГ при stop=prev(min 0.3%), БУ+1.0", fx)
fx = [r for r in rows if r[0]["stop_mode"] == "prev" and r[0]["trail_mode"] == "none" and r[0]["be_trigger"] == 1.0 and r[0]["min_stop_atr"] == 0]
show("МИНИМАЛЬНАЯ ДИСТАНЦИЯ СТОПА без трейла, БУ+1.0", fx)
fx = [r for r in rows if r[0]["stop_mode"] == "prev" and r[0]["trail_mode"] == "none" and r[0]["min_stop_pct"] == 0.3 and r[0]["min_stop_atr"] == 0]
show("УРОВЕНЬ БЕЗУБЫТКА без трейла, stop=prev(min 0.3%)", fx)
