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
    rg = x.get("rg") or {}
    rows.append(dict(sn=x.get("sn"), sym=x.get("sym"), side=x.get("side"), tf=x.get("tf"), kind=(x.get("kind") or "")[:3], tin=s["t_in"], tout=s["t_out"], net=s["net_pct"], reg=rg.get("regime")))
rows.sort(key=lambda r: r["tin"])
def cnt(r, W, pool): return sum(1 for q in pool if q is not r and q["side"] == r["side"] and 0 < r["tin"] - q["tin"] <= W * 60000)
five = [r for r in rows if r["tf"] == "5m"]
print("5m rows", len(five), "sum", round(sum(r["net"] for r in five), 2), "since t0", sum(1 for r in five if r["tin"] >= t0), round(sum(r["net"] for r in five if r["tin"] >= t0), 2))
print("--- 5m burst: skip 5m if >=N other 5m same-side signals in last W min: kept n/sum | blocked n/sum | since t0 blocked n/sum")
for W in (30, 60, 90):
    out = []
    for N in (2, 3, 4, 5):
        bl = [r for r in five if cnt(r, W, five) >= N]; kp = [r for r in five if r not in bl]
        b0 = [r for r in bl if r["tin"] >= t0]
        out.append("N%d:%d/%.1f|%d/%.1f|%d/%.1f" % (N, len(kp), sum(r["net"] for r in kp), len(bl), sum(r["net"] for r in bl), len(b0), sum(r["net"] for r in b0)))
    print("  W", W, " ".join(out))
print("--- 5m burst blocked list (W60 N3):")
for r in five:
    if cnt(r, 60, five) >= 3: print("  ", r["sn"], r["sym"], r["side"], r["kind"], r["reg"], ts(r["tin"]), round(r["net"], 2))
print("--- bre vs bou by tf/side since beginning (n sum), 1h+ only")
g = collections.defaultdict(lambda: [0, 0.0])
for r in rows:
    if r["tf"] in ("1h", "4h"): g[(r["tf"], r["side"], r["kind"], r["reg"])][0] += 1; g[(r["tf"], r["side"], r["kind"], r["reg"])][1] += r["net"]
for k, v in sorted(g.items()): print("  ", "/".join(k), v[0], round(v[1], 1))
