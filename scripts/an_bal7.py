import json, datetime, collections
P = "/opt/trading-bot/positions_regr/"
items = json.load(open(P + "shadow.json"))["items"]
t0 = json.load(open(P + "shadow_bal.json"))["t0"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M")
rows = []
for x in items:
    if x.get("var") != "A": continue
    st = x.get("status"); s = (x.get("p") if st in ("closed", "open") else x.get("cf")) or {}
    if not s.get("t_out") or s.get("net_pct") is None: continue
    rg = x.get("rg") or {}; f = x.get("feat") or {}
    rows.append(dict(sn=x.get("sn"), sym=x.get("sym"), side=x.get("side"), tf=x.get("tf"), kind=(x.get("kind") or "")[:3], tin=s["t_in"], tout=s["t_out"], net=s["net_pct"],
                     reg=rg.get("regime"), rs=rg.get("strength"), why=s.get("reason"), width=f.get("width"), rr=f.get("rr"), st=st))
rows.sort(key=lambda r: r["tin"])
print("regimes", collections.Counter(r["reg"] for r in rows))
# phases by zigzag on cumulative net by exit
seq = sorted(rows, key=lambda r: r["tout"]); cum = 0; pts = []
for r in seq: cum += r["net"]; pts.append((r["tout"], cum, r))
TH = 6.0; ph = []; hi = lo = 0; hit = lit = 0; mode = 0
for i, (t, c, r) in enumerate(pts):
    if c > hi: hi, hit = c, i
    if c < lo: lo, lit = c, i
    if mode >= 0 and hi - c >= TH and hit < i: ph.append(("UP", 0, hit)); mode = -1; lo, lit = c, i
    elif mode <= 0 and c - lo >= TH and lit < i: ph.append(("DOWN", 0, lit)); mode = 1; hi, hit = c, i
print("--- turning points (zigzag %.0f%%):" % TH, [(k, ts(pts[i][0]), round(pts[i][1], 1)) for k, _, i in ph])
# drain windows between UP-peak and next DOWN-trough
tp = [(k, i) for k, _, i in ph]
print("--- DRAIN windows: breakdown")
for a, b in zip(tp, tp[1:]):
    if a[0] != "UP" or b[0] != "DOWN": continue
    sub = [pts[j][2] for j in range(a[1] + 1, b[1] + 1)]
    tot = sum(r["net"] for r in sub)
    print("DRAIN", ts(pts[a[1]][0]), "->", ts(pts[b[1]][0]), "trades", len(sub), "sum", round(tot, 1))
    g = collections.defaultdict(lambda: [0, 0.0])
    for r in sub:
        for key in ((r["tf"], r["side"], r["kind"]), ("reg", r["reg"], r["side"]), ("why", r["why"])):
            g[key][0] += 1; g[key][1] += r["net"]
    print("   ", "; ".join("%s n%d %.1f" % ("/".join(map(str, k)), v[0], v[1]) for k, v in sorted(g.items(), key=lambda kv: kv[1][1])[:8]))
print("--- UP windows: breakdown")
for a, b in zip(tp, tp[1:]):
    if a[0] != "DOWN" or b[0] != "UP": continue
    sub = [pts[j][2] for j in range(a[1] + 1, b[1] + 1)]
    print("UP", ts(pts[a[1]][0]), "->", ts(pts[b[1]][0]), "trades", len(sub), "sum", round(sum(r["net"] for r in sub), 1))
    g = collections.defaultdict(lambda: [0, 0.0])
    for r in sub:
        for key in ((r["tf"], r["side"], r["kind"]), ("reg", r["reg"], r["side"])):
            g[key][0] += 1; g[key][1] += r["net"]
    print("   ", "; ".join("%s n%d %.1f" % ("/".join(map(str, k)), v[0], v[1]) for k, v in sorted(g.items(), key=lambda kv: -kv[1][1])[:6]))
# overall breakdown
print("--- overall by tf/side/kind")
g = collections.defaultdict(lambda: [0, 0.0])
for r in rows: g[(r["tf"], r["side"], r["kind"])][0] += 1; g[(r["tf"], r["side"], r["kind"])][1] += r["net"]
for k, v in sorted(g.items()): print("  ", "/".join(k), v[0], round(v[1], 1), "avg", round(v[1] / v[0], 2))
# burst density: signals of any coin in previous W minutes (same side)
print("--- burst filter: skip if >=N other signals (same side) in last W min; kept n/sum | blocked n/sum")
for W in (30, 60, 120):
    out = []
    for N in (2, 3, 4, 6, 8):
        kept = []; bl = []
        for r in rows:
            c = sum(1 for q in rows if q is not r and q["side"] == r["side"] and 0 < r["tin"] - q["tin"] <= W * 60000)
            (bl if c >= N else kept).append(r)
        out.append("N%d:%d/%.1f|%d/%.1f" % (N, len(kept), sum(r["net"] for r in kept), len(bl), sum(r["net"] for r in bl)))
    print("  W", W, " ".join(out))
# per-coin repeat: skip if same sym+side had signal in last H hours
print("--- cooldown filter: skip if same sym+side signal in last H hours")
for H in (1, 2, 4):
    kept = []; bl = []
    for r in rows:
        dup = any(q is not r and q["sym"] == r["sym"] and q["side"] == r["side"] and 0 < r["tin"] - q["tin"] <= H * 3600000 for q in rows)
        (bl if dup else kept).append(r)
    print("  H", H, "kept", len(kept), round(sum(r["net"] for r in kept), 1), "blocked", len(bl), round(sum(r["net"] for r in bl), 1))
# regime alignment
print("--- regime x side (n, sum, avg) and by strength")
g = collections.defaultdict(lambda: [0, 0.0])
for r in rows:
    sb = "s>=0.8" if (r["rs"] or 0) >= 0.8 else ("s>=0.5" if (r["rs"] or 0) >= 0.5 else "s<0.5")
    g[(r["reg"], r["side"], sb)][0] += 1; g[(r["reg"], r["side"], sb)][1] += r["net"]
for k, v in sorted(g.items(), key=lambda kv: str(kv[0])): print("  ", "/".join(map(str, k)), v[0], round(v[1], 1), "avg", round(v[1] / v[0], 2))
# 5m only by hour of day (UTC)
print("--- 5m by UTC hour: n sum")
h = collections.defaultdict(lambda: [0, 0.0])
for r in rows:
    if r["tf"] == "5m": k = int(ts(r["tin"])[3:5]); h[k][0] += 1; h[k][1] += r["net"]
print(" ".join("%02d:%d/%.1f" % (k, v[0], v[1]) for k, v in sorted(h.items())))
