import random, time, sys
sys.path.insert(0, "/tmp/bt")
import bt
from bt import *
random.seed(7)
def rand_signals(sym, P, p=1.0 / 12):
    d = P["d"]; out = []
    for i in range(100, len(d) - 1):
        T = d[i][0] + 900000
        j1 = P["idx1"].get((T // 3600000) * 3600000 - 3600000); j4 = P["idx4"].get((T // 14400000) * 14400000 - 14400000)
        if j1 is None or j4 is None or j1 not in P["s1"] or j4 not in P["s4"]: continue
        if P["s1"][j1] > -2 or P["s4"][j4] > -2: continue
        if d[i + 1][0] != d[i][0] + 900000: continue
        if random.random() > p: continue
        out.append(dict(sym=sym, i=i, t=T, trig="rand", side=-1, px=d[i][4], a1=P["a1"][j1], s4=P["s4"][j4], s1=P["s1"][j1]))
    return out
def run(P, sg, v, mo=2):
    trs = []
    for s in SHORT:
        for g in sg[s]:
            r = sim(P[s], g, v)
            if r: trs.append(r)
    acc = portfolio(trs, mo, 0, None, None); return acc
t0 = time.time(); P = {}
for s in SHORT: P[s] = prep(s)
print("prep done %.0fs" % (time.time() - t0), flush=True)
sg = {s: signals(s, P[s], "short") for s in SHORT}
rg = {s: rand_signals(s, P[s]) for s in SHORT}
print("trigger signals", sum(len(v) for v in sg.values()), "random trend-only signals", sum(len(v) for v in rg.values()), flush=True)
print("=== A. wider stops (trigger entries, 2 open, cap 6%)")
for k in [0.25, 0.75, 1.25, 1.75, 2.5, 3.5]:
    acc = run(P, sg, V(k=k, cap=6.0)); s = stats(acc)
    rp = sum(a["Rp"] for a in acc) / len(acc)
    print(fmt("k=%.2f" % k, s), "avgRisk%%=%.2f" % rp, flush=True)
print("=== B. gross (no fee, no slippage) vs net, trigger entries")
for k in [0.25, 1.25]:
    bt.FEE = 0.0; bt.SLIP = 0.0
    g = stats(run(P, sg, V(k=k, cap=6.0)))
    bt.FEE = 0.05; bt.SLIP = 0.02
    n = stats(run(P, sg, V(k=k, cap=6.0)))
    print("k=%.2f gross avgR=%+.2f PF=%.2f | net avgR=%+.2f PF=%.2f" % (k, g["avg"], g["pf"], n["avg"], n["pf"]), flush=True)
print("=== C. random entries inside the same trend filter (same exits), 3 seeds avg")
for k in [0.25, 1.25]:
    for name, S in [("trigger", sg), ("random", rg)]:
        s = stats(run(P, S, V(k=k, cap=6.0)))
        print("k=%.2f %-8s" % (k, name), fmt("", s), flush=True)
print("=== D. by trend score at entry (trigger, k=0.25 and 1.25): avgR when s4,s1 both -4 vs weaker")
for k in [0.25, 1.25]:
    acc_all = []
    for s in SHORT:
        for g in sg[s]:
            r = sim(P[s], g, V(k=k, cap=6.0))
            if r: r["strong"] = (g["s4"] == -4 and g["s1"] == -4); acc_all.append(r)
    acc = portfolio(acc_all, 2, 0, None, None)
    for lab, f in [("both -4", True), ("weaker", False)]:
        x = [a["R"] for a in acc if a["strong"] == f]
        if x: print("k=%.2f %-8s n=%d avgR=%+.2f" % (k, lab, len(x), sum(x) / len(x)), flush=True)
print("done %.0fs" % (time.time() - t0))
