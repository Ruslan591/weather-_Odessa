import json, urllib.request, datetime, collections, bisect
P = "/opt/trading-bot/positions_regr/"
items = json.load(open(P + "shadow.json"))["items"]
t0 = json.load(open(P + "shadow_bal.json"))["t0"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M")
rows = []
for x in items:
    if x.get("var") != "A": continue
    st = x.get("status"); s = (x.get("p") if st in ("closed", "open") else x.get("cf")) or {}
    if not s.get("t_out") or s.get("net_pct") is None: continue
    rows.append(dict(sn=x.get("sn"), sym=x.get("sym"), side=x.get("side"), tf=x.get("tf"), kind=(x.get("kind") or "")[:3], tin=s["t_in"], tout=s["t_out"], net=s["net_pct"], R=s.get("r_mult"), st=st))
rows.sort(key=lambda r: r["tin"])
print("closed A rows", len(rows), "from", ts(rows[0]["tin"]), "to", ts(rows[-1]["tin"]), "n since t0", sum(1 for r in rows if r["tin"] >= t0))
a = rows[0]["tin"] - 6 * 3600000
K = []
cur = a
while True:
    u = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=1000&startTime=%d" % cur
    d = json.load(urllib.request.urlopen(u, timeout=30))
    if not d: break
    K += d; cur = d[-1][0] + 900000
    if len(d) < 1000: break
T = [k[0] for k in K]; C = [float(k[4]) for k in K]
print("btc bars", len(K), ts(T[0]), ts(T[-1]))
def ret(t, bars):
    i = bisect.bisect_right(T, t) - 1
    if i - bars < 0: return None
    return (C[i - 1] / C[i - 1 - bars] - 1) * 100
for r in rows:
    sg = 1 if r["side"] == "long" else -1
    for nm, b in (("h1", 4), ("h2", 8), ("h4", 16)):
        v = ret(r["tin"], b); r[nm] = None if v is None else sg * v   # >0 BTC moves in favor of our side
# equity by day buckets (no slot limit, cumulative net %)
print("--- cumulative net% by 3h bucket of exit (all A closed)")
cum = 0; bk = collections.OrderedDict()
for r in sorted(rows, key=lambda r: r["tout"]):
    cum += r["net"]; k = ts(r["tout"] // 10800000 * 10800000); bk[k] = (round(cum, 2), bk.get(k, (0, 0))[1] + 1)
print(" ".join("%s:%s/%d" % (k, v[0], v[1]) for k, v in bk.items()))
print("--- filter grid: block if BTC moves against our side more than thr (within horizon); kept_n kept_sum blocked_n blocked_sum | all, then 5m only, then 15m+")
def grid(sub, label):
    tot = sum(r["net"] for r in sub)
    print(label, "n", len(sub), "sum", round(tot, 2), "avg", round(tot / max(1, len(sub)), 3))
    for nm in ("h1", "h2", "h4"):
        out = []
        for thr in (0.0, 0.2, 0.3, 0.5, 0.8):
            kept = [r for r in sub if r[nm] is None or r[nm] >= -thr]; bl = [r for r in sub if r[nm] is not None and r[nm] < -thr]
            out.append("%.1f:%d/%.1f|%d/%.1f" % (thr, len(kept), sum(r["net"] for r in kept), len(bl), sum(r["net"] for r in bl)))
        print("  ", nm, " ".join(out))
grid(rows, "ALL"); grid([r for r in rows if r["tf"] == "5m"], "5m"); grid([r for r in rows if r["tf"] != "5m"], "15m+")
grid([r for r in rows if r["tin"] >= t0], "since t0")
print("--- since t0 rows: sn sym side tf in net h1 h2 h4")
for r in rows:
    if r["tin"] >= t0: print(r["sn"], r["sym"], r["side"], r["tf"], r["kind"], ts(r["tin"]), round(r["net"], 2), *(None if r[k] is None else round(r[k], 2) for k in ("h1", "h2", "h4")))
