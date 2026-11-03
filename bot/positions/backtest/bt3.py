import sys, time
sys.path.insert(0, "/tmp/bt")
import bt
from bt import *
P = {s: prep(s) for s in SHORT}
sg = {s: signals(s, P[s], "short") for s in SHORT}
def run(v, mo=2, tr=None):
    trs = []
    for s in SHORT:
        for g in sg[s]:
            r = sim(P[s], g, v)
            if r: trs.append(r)
    return portfolio(trs, mo, 0, None, tr)
def mon(acc):
    m = {}
    for a in acc: m.setdefault(time.strftime("%m", time.gmtime(a["t_in"] / 1000)), []).append(a["R"])
    return " ".join("%s:%d/%+.1f" % (k, len(x), sum(x)) for k, x in sorted(m.items()))
print("=== trigger x stop width (2 open, cap 6%)")
for k in [0.25, 1.25, 1.5, 1.75, 2.5]:
    for tr in [None, "retest", "break"]:
        acc = run(V(k=k, cap=6.0), 2, tr); s = stats(acc)
        print(fmt("k=%.2f %s" % (k, tr or "both"), s)); 
print("=== by month, k=1.5 both vs k=0.25 both")
for k in [0.25, 1.5]:
    print("k=%.2f months(n/totR):" % k, mon(run(V(k=k, cap=6.0))))
print("=== k=1.5 combos")
for name, v, tr in [("k1.5 partial", V(k=1.5, cap=6.0, partial=True), None), ("k1.5 tp2", V(k=1.5, cap=6.0, tp=2.0), None), ("k1.5 tp5", V(k=1.5, cap=6.0, tp=5.0), None), ("k1.5 maxh48", V(k=1.5, cap=6.0, maxh=48), None), ("k1.5 no trail", V(k=1.5, cap=6.0, trail=None), None), ("k1.5 3open", V(k=1.5, cap=6.0), None)]:
    mo = 3 if "3open" in name else 2
    print(fmt(name, stats(run(v, mo, tr))))
print("=== stop by 24h structure + k, break only / both")
for n_, k in [(96, 0.25), (96, 0.75)]:
    for tr in [None, "break"]:
        print(fmt("n=%d k=%.2f %s" % (n_, k, tr or "both"), stats(run(V(n=n_, k=k, cap=6.0), 2, tr))))
# standard error note
acc = run(V(k=0.25, cap=6.0)); import statistics as S
rs = [a["R"] for a in acc]; print("k0.25 R std %.2f n=%d SE=%.3f" % (S.pstdev(rs), len(rs), S.pstdev(rs) / len(rs) ** 0.5))
acc = run(V(k=1.5, cap=6.0)); rs = [a["R"] for a in acc]; print("k1.5 R std %.2f n=%d SE=%.3f avg=%+.3f" % (S.pstdev(rs), len(rs), S.pstdev(rs) / len(rs) ** 0.5, sum(rs) / len(rs)))
