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
    rows.append(dict(sn=x.get("sn"), sym=x.get("sym"), side=x.get("side"), tf=x.get("tf"), kind=(x.get("kind") or "")[:3], tin=s["t_in"], tout=s["t_out"], net=s["net_pct"], reg=rg.get("regime"), rs=rg.get("strength") or 0, why=s.get("reason")))
rows.sort(key=lambda r: r["tin"])
mid = rows[len(rows) // 2]["tin"]
def mdd(sub):
    c = pk = dd = 0
    for r in sorted(sub, key=lambda r: r["tout"]):
        c += r["net"]; pk = max(pk, c); dd = min(dd, c - pk)
    return dd
al = lambda r: (r["side"] == "long" and r["reg"] == "up") or (r["side"] == "short" and r["reg"] == "down")
F = collections.OrderedDict([
 ("F0 none", lambda r: True),
 ("F1 not flat", lambda r: r["reg"] != "flat"),
 ("F2 not 5m", lambda r: r["tf"] != "5m"),
 ("F3 aligned only", al),
 ("F4 not flat & not 5m", lambda r: r["reg"] != "flat" and r["tf"] != "5m"),
 ("F5 not flat & s>=0.8", lambda r: r["reg"] != "flat" and r["rs"] >= 0.8),
 ("F6 flat only if 1h+", lambda r: not (r["reg"] == "flat" and r["tf"] in ("5m", "15m"))),
 ("F7 aligned & not 5m", lambda r: al(r) and r["tf"] != "5m"),
])
print("filter | all n/sum/maxDD | 1st half n/sum | 2nd half n/sum | since t0 n/sum/maxDD | blocked all n/sum")
for nm, f in F.items():
    k = [r for r in rows if f(r)]; b = [r for r in rows if not f(r)]
    h1 = [r for r in k if r["tin"] < mid]; h2 = [r for r in k if r["tin"] >= mid]; s0 = [r for r in k if r["tin"] >= t0]
    print(nm, "|", len(k), round(sum(r["net"] for r in k), 1), round(mdd(k), 1), "|", len(h1), round(sum(r["net"] for r in h1), 1), "|", len(h2), round(sum(r["net"] for r in h2), 1), "|",
          len(s0), round(sum(r["net"] for r in s0), 1), round(mdd(s0), 1), "|", len(b), round(sum(r["net"] for r in b), 1))
print("--- flat by tf: n sum avg")
g = collections.defaultdict(lambda: [0, 0.0])
for r in rows:
    if r["reg"] == "flat": g[r["tf"]][0] += 1; g[r["tf"]][1] += r["net"]
print({k: (v[0], round(v[1], 1)) for k, v in g.items()})
print("--- regime by 6h bucket (count of signals): shows when market was flat")
bk = collections.OrderedDict()
for r in rows:
    k = ts(r["tin"] // 21600000 * 21600000)[:5] + "h"; bk.setdefault(k, collections.Counter())[r["reg"]] += 1
print(" ".join("%s:%s" % (k, "/".join("%s%d" % (a[0], n) for a, n in v.items())) for k, v in bk.items()))
print("--- since t0 chronological (by exit): sn sym side tf kind reg rs net cum why")
c = 0
for r in sorted([r for r in rows if r["tin"] >= t0], key=lambda r: r["tout"]):
    c += r["net"]; print(r["sn"], r["sym"], r["side"], r["tf"], r["kind"], r["reg"], r["rs"], "in", ts(r["tin"]), "out", ts(r["tout"]), round(r["net"], 2), round(c, 2), r["why"])
