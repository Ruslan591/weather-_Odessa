"""classic_diag.py — разбор устойчивости выбранных конфигураций: топ-сделки, по парам, по месяцам, без лучших сделок."""
import json, os, sys, time, datetime
import urllib.request
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs

TF = sys.argv[1] if len(sys.argv) > 1 else "1h"
STEP = {"15m": 900, "1h": 3600, "4h": 14400}[TF] * 1000
PAGES = 3
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
data = {s: None for s in pairs}
for s in pairs:
    df = fetch(s); data[s] = (df, cs.prepare(df, now))
START = max(d[0].t.iloc[0] for d in data.values()) + 450 * STEP
print("TF", TF, "с", datetime.datetime.utcfromtimestamp(START / 1000).date(), "по", datetime.datetime.utcfromtimestamp(now / 1000).date())
CFG = {
    "A prev1.5% БУ1.5 без трейла": dict(stop_mode="prev", min_stop_pct=1.5, be_trigger=1.5, trail_mode="none", trail_dist=0),
    "B pivot БУ1.5 без трейла": dict(stop_mode="pivot", be_trigger=1.5, trail_mode="none", trail_dist=0),
    "C prev1.5% БУ1.5 трейл4ATR": dict(stop_mode="prev", min_stop_pct=1.5, be_trigger=1.5, trail_mode="atr", trail_dist=4),
    "D prev1.5% БУ1.0 трейл4ATR": dict(stop_mode="prev", min_stop_pct=1.5, be_trigger=1.0, trail_mode="atr", trail_dist=4),
    "F как на панели (prev0.3% БУ1 трейл1ATR)": dict(stop_mode="prev", min_stop_pct=0.3, be_trigger=1.0, trail_mode="atr", trail_dist=1.0),
}
for name, extra in CFG.items():
    P = dict(cs.PARAMS, **extra); T = []
    for s, (df, pre) in data.items():
        for x in cs.simulate(df, now, P, pre):
            if x["t_in"] >= START: x["sym"] = s; T.append(x)
    T.sort(key=lambda x: -x["net"])
    n = len(T); net = sum(x["net"] for x in T)
    srt = sorted(x["net"] for x in T)
    print("\n=== %s: n=%d net=%+.1f gross=%+.1f медиана=%+.2f средняя=%+.2f" % (name, n, net, sum(x["gross"] for x in T), srt[n // 2], net / n))
    print("  без топ-1/3/5 сделок: %+.1f / %+.1f / %+.1f" % (net - sum(x["net"] for x in T[:1]), net - sum(x["net"] for x in T[:3]), net - sum(x["net"] for x in T[:5])))
    print("  топ-5:", [(x["sym"][:-4], x["side"], datetime.datetime.utcfromtimestamp(x["t_in"] / 1000).strftime("%m-%d"), round((x["t_out"] - x["t_in"]) / 86400000, 1), "д", round(x["net"], 1), x["reason"]) for x in T[:5]])
    print("  худшие-3:", [(x["sym"][:-4], x["side"], round(x["net"], 1), x["reason"]) for x in T[-3:]])
    byp, bym, bys = {}, {}, {}
    for x in T:
        byp[x["sym"][:-4]] = byp.get(x["sym"][:-4], 0) + x["net"]
        m = datetime.datetime.utcfromtimestamp(x["t_in"] / 1000).strftime("%Y-%m"); bym[m] = bym.get(m, 0) + x["net"]
        bys[x["side"]] = bys.get(x["side"], 0) + x["net"]
    print("  по парам:", {k: round(v, 1) for k, v in sorted(byp.items(), key=lambda kv: -kv[1])})
    print("  по месяцам входа:", {k: round(v, 1) for k, v in sorted(bym.items())})
    print("  по сторонам:", {k: round(v, 1) for k, v in bys.items()}, " открытых:", sum(1 for x in T if x["open"]), "сумма открытых: %+.1f" % sum(x["net"] for x in T if x["open"]))
    dur = sorted((x["t_out"] - x["t_in"]) / 86400000 for x in T)
    print("  длительность сделок, сут: медиана %.1f, макс %.1f" % (dur[n // 2], dur[-1]))
