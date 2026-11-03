import sys, time, random, statistics as S
sys.path.insert(0, "/tmp/bt")
import bt
from bt import *
random.seed(5)
MAK = 0.02; TAK = 0.05; SL = 0.02
def run_order(D, i, L, a1, k, tp_r, valid=8, maxh=24):
    # sell limit at L placed after closed candle i. fill if high > L (strict). stop L+k*a1 (stop-market), target tp_r*R below (limit). returns (R_mult, why) or None if unfilled/unfinished
    d = D["d"]; n = len(d); stop = L + k * a1; R = stop - L; Rp = R / L * 100; tp = L - tp_r * R
    fj = None
    for j in range(i + 1, min(i + 1 + valid, n)):
        if d[j][2] > L: fj = j; break
    if fj is None: return ("nofill", None)
    t_in = d[fj][0]
    # fill candle: only stop check (conservative), no target
    if d[fj][2] >= stop:
        net = -(stop * (1 + SL / 100) / L - 1) * 100 - MAK - TAK
        return ("fill", net / Rp, "stop")
    for q in range(fj + 1, n):
        t, o, h, l, c = d[q]
        if h >= stop:
            ex = max(stop, o) * (1 + SL / 100); net = -(ex / L - 1) * 100 - MAK - TAK; return ("fill", net / Rp, "stop")
        if l <= tp:
            net = (L / tp - 1) * 100 - MAK - MAK; return ("fill", net / Rp, "tp")
        if (t + 900000 - t_in) / 3600000.0 >= maxh:
            ex = c * (1 + SL / 100); net = -(ex / L - 1) * 100 - MAK - TAK; return ("fill", net / Rp, "time")
    return None
P = {s: prep(s) for s in SHORT}
elig = {}; real = []
for s in SHORT:
    D = P[s]; d = D["d"]; e = []
    for i in range(100, len(d) - 400):
        T = d[i][0] + 900000
        j1 = D["idx1"].get((T // 3600000) * 3600000 - 3600000); j4 = D["idx4"].get((T // 14400000) * 14400000 - 14400000)
        if j1 is None or j4 is None or j1 not in D["s1"] or j4 not in D["s4"]: continue
        if D["s1"][j1] > -2 or D["s4"][j4] > -2: continue
        a1 = D["a1"][j1]; e20h = D["e20h"][j1]; px = d[i][4]
        dist = (e20h - px) / a1
        if dist < 0.2 or dist > 3.0: continue
        e.append((i, a1, e20h, px, dist))
    elig[s] = e
    last = -99
    for (i, a1, e20h, px, dist) in e:
        if i - last < 8: continue
        last = i; real.append((s, i, a1, e20h, dist))
print("real level orders (EMA20 1h above price, trend -2/-2, one per 8 candles per pair):", len(real), "eligible candles", sum(len(v) for v in elig.values()), flush=True)
def stat(rs):
    if not rs: return "n=0"
    w = [r for r in rs if r > 0]; l = [-r for r in rs if r <= 0]
    return "n=%d win=%.0f%% avgR=%+.2f PF=%.2f SE=%.2f" % (len(rs), 100 * len(w) / len(rs), S.mean(rs), (sum(w) / sum(l)) if l else 99, S.pstdev(rs) / len(rs) ** 0.5)
for k in [0.5, 1.0, 1.5, 2.5]:
    for tp_r in [1.5, 2.0, 3.0]:
        fr = []; nf = 0; ctl = []; cnf = 0; nreal = 0
        for (s, i, a1, e20h, dist) in real:
            r = run_order(P[s], i, e20h, a1, k, tp_r); nreal += 1
            if r and r[0] == "nofill": nf += 1
            elif r: fr.append(r[1])
            # control: 3 random eligible candles on the same pair, level = price + dist*a1' (same distance in ATR)
            for _ in range(3):
                i2, a2, e2, px2, d2 = random.choice(elig[s])
                L2 = px2 + dist * a2
                r2 = run_order(P[s], i2, L2, a2, k, tp_r)
                if r2 and r2[0] == "nofill": cnf += 1
                elif r2: ctl.append(r2[1])
        print("k=%.1f tp=%.1fR | LEVEL: fill %.0f%% %s | CONTROL(random time, same distance): fill %.0f%% %s" % (k, tp_r, 100 * len(fr) / nreal, stat(fr), 100 * len(ctl) / (3 * nreal), stat(ctl)), flush=True)
