"""classic_zec_diag.py — из чего складывается результат одной пары: топ-сделки, месяцы, просадка, серии. Запуск: SYMBOL TF PAGES"""
import json, os, sys, time, datetime, warnings, urllib.request
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
SYM, TF, PAGES = sys.argv[1], sys.argv[2], int(sys.argv[3])
STEP = {"15m": 900, "1h": 3600, "4h": 14400}[TF] * 1000
now = int(time.time() * 1000)
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
df = df.drop_duplicates("t").reset_index(drop=True); pre = cs.prepare(df, now)
START = int(df.t.iloc[0]) + 450 * STEP
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")
print(SYM, TF, "оценка", d0(START), "..", d0(now), "; цена ZEC от %.0f до %.0f, сейчас %.0f" % (df.l[df.t >= START].min(), df.h[df.t >= START].max(), df.c.iloc[-1]))
M = lambda **k: dict(cs.PARAMS, **k)
CFG = {
    "исходные правила БЕЗ трейла: стоп pivot, БУ+1%": M(stop_mode="pivot", be_trigger=1.0, trail_mode="none"),
    "стоп prev≥2.5%, БУ+1%, без трейла": M(stop_mode="prev", min_stop_pct=2.5, be_trigger=1.0, trail_mode="none"),
    "стоп prev≥1.5%, БУ+1%, без трейла": M(stop_mode="prev", min_stop_pct=1.5, be_trigger=1.0, trail_mode="none"),
    "стоп prev≥2.5%, БУ+3%, без трейла": M(stop_mode="prev", min_stop_pct=2.5, be_trigger=3.0, trail_mode="none"),
}
for name, P in CFG.items():
    T = [x for x in cs.simulate(df, now, P, pre) if x["t_in"] >= START]
    n = len(T); net = sum(x["net"] for x in T)
    byt = sorted(T, key=lambda x: -x["net"])
    print("\n=== %s: n=%d net=%+.1f прибыльных %d%% (БУ-выходы −0.1 считаются убытком)" % (name, n, net, sum(x["net"] > 0 for x in T) / n * 100))
    print("  топ-6 сделок:", [(x["side"], d0(x["t_in"])[2:], "%.0fд" % ((x["t_out"] - x["t_in"]) / 86400000), "%+.0f" % x["net"], x["reason"][:4]) for x in byt[:6]])
    print("  доля топ-5 в итоге: %.0f%%; без топ-5: %+.1f; без топ-10: %+.1f" % (sum(x["net"] for x in byt[:5]) / net * 100, net - sum(x["net"] for x in byt[:5]), net - sum(x["net"] for x in byt[:10])))
    cum, pk, dd, ddt = 0, 0, 0, None
    for x in sorted(T, key=lambda x: x["t_out"]):
        cum += x["net"]; pk = max(pk, cum)
        if pk - cum > dd: dd, ddt = pk - cum, d0(x["t_out"])
    run, mr = 0, 0
    for x in sorted(T, key=lambda x: x["t_in"]):
        run = run + 1 if x["net"] <= 0 else 0; mr = max(mr, run)
    bys = {}
    for x in T: bys[x["side"]] = bys.get(x["side"], 0) + x["net"]
    mm = {}
    for x in T:
        k = d0(x["t_in"])[:7]; mm[k] = mm.get(k, 0) + x["net"]
    print("  макс. просадка по накопленному результату: −%.1f п.п. (к %s); макс. серия подряд без прибыли: %d сделок; по сторонам: %s" % (dd, ddt, mr, {k: round(v) for k, v in bys.items()}))
    print("  по месяцам:", {k[2:]: round(v) for k, v in sorted(mm.items())})
    dur = sorted((x["t_out"] - x["t_in"]) / 86400000 for x in T)
    print("  длительность, сут: медиана %.1f, 90%% %.1f, макс %.1f; открытых сейчас: %s" % (dur[n // 2], dur[int(n * .9)], dur[-1], [(x["side"], round(x["net"], 1)) for x in T if x["open"]]))
