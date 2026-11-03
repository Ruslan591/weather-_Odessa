# Backtest of pos_watch.py triggers on 15m history (ASCII only)
import json, os, sys, time, urllib.request, statistics, itertools
BASE = "https://data-api.binance.vision/api/v3/klines"
CD = "/tmp/bt"; os.makedirs(CD, exist_ok=True)
DAYS = 150
SYMS = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT APT ATOM".split()
SHORT = "XRP DOGE ADA DOT APT ATOM SOL LINK AVAX SUI LTC BNB ETH".split()
COUNTER = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT".split()
FEE = 0.05; SLIP = 0.02

def fetch(sym):
    fn = "%s/%s_15m.json" % (CD, sym)
    if os.path.exists(fn) and time.time() - os.path.getmtime(fn) < 6 * 3600:
        return json.load(open(fn))
    now = int(time.time() * 1000); st = now - DAYS * 86400000; out = []
    while st < now:
        u = "%s?symbol=%sUSDT&interval=15m&limit=1000&startTime=%d" % (BASE, sym, st)
        for a in range(4):
            try: d = json.load(urllib.request.urlopen(u, timeout=20)); break
            except Exception as e: time.sleep(1.5); d = None
        if not d: break
        out += d; st = int(d[-1][0]) + 900000
        if len(d) < 1000: break
        time.sleep(0.15)
    out = [k for k in out if int(k[0]) + 900000 <= now]
    seen = set(); res = []
    for k in out:
        if k[0] in seen: continue
        seen.add(k[0]); res.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])])
    json.dump(res, open(fn, "w")); return res

def ema(v, n):
    k = 2.0 / (n + 1); e = v[0]; o = []
    for x in v: e = x * k + e * (1 - k); o.append(e)
    return o
def agg(d, ms):
    b = {}
    for k in d: b.setdefault(k[0] // ms, []).append(k)
    need = ms // 900000; res = []
    for key in sorted(b):
        g = b[key]
        if len(g) != need: continue
        res.append([key * ms, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4]])
    return res
def score_series(tf):
    c = [x[4] for x in tf]; sc = {}
    for j in range(258, len(c)):
        w = c[j - 258:j + 1]; e20 = ema(w, 20); e50 = ema(w, 50); e200 = ema(w, 200)
        sc[j] = (1 if w[-1] > e50[-1] else -1) + (1 if e20[-1] > e50[-1] else -1) + (1 if e50[-1] > e50[-6] else -1) + (1 if e50[-1] > e200[-1] else -1)
    return sc
def atr_series(tf):
    a = None; out = [None]
    for i in range(1, len(tf)):
        h, l, pc = tf[i][2], tf[i][3], tf[i - 1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc)); a = tr if a is None else a + (tr - a) / 14; out.append(a)
    return out

def prep(sym):
    d = fetch(sym)
    h1 = agg(d, 3600000); h4 = agg(d, 14400000)
    idx1 = {x[0]: j for j, x in enumerate(h1)}; idx4 = {x[0]: j for j, x in enumerate(h4)}
    return dict(d=d, h1=h1, h4=h4, idx1=idx1, idx4=idx4, s1=score_series(h1), s4=score_series(h4),
                a1=atr_series(h1), e20h=ema([x[4] for x in h1], 20), e15=ema([x[4] for x in d], 20))

def signals(sym, P, kind):
    # kind: short (trend short, retest+break), counter (long breakout, no trend check)
    D = P; d = D["d"]; n = len(d); out = []
    o = [x[1] for x in d]; h = [x[2] for x in d]; l = [x[3] for x in d]; c = [x[4] for x in d]; e15 = D["e15"]
    for i in range(100, n - 1):
        T = d[i][0] + 900000
        hb = (T // 3600000) * 3600000 - 3600000   # last closed 1h open
        if T % 3600000 != 0: hb = (T // 3600000) * 3600000 - 3600000
        j1 = D["idx1"].get(hb); b4 = (T // 14400000) * 14400000 - 14400000; j4 = D["idx4"].get(b4)
        if j1 is None or j4 is None or j1 not in D["s1"] or j4 not in D["s4"]: continue
        s1 = D["s1"][j1]; s4 = D["s4"][j4]; a1 = D["a1"][j1]; e20h = D["e20h"][j1]; px = c[i]
        if d[i + 1][0] != d[i][0] + 900000: continue
        if kind == "short":
            if s4 > -2 or s1 > -2: continue
            touch = any(h[k] >= e20h for k in range(i - 5, i + 1)); cross = c[i] < e15[i] and c[i - 1] >= e15[i - 1]; bear = c[i] < o[i]
            trig = None
            if touch and bear and cross: trig = "retest"
            if c[i] < min(l[i - 96:i]) and bear and (e20h - px) / a1 <= 3.0: trig = "break"
            side = -1
        else:
            if not (c[i] > max(h[i - 96:i]) and c[i] > o[i] and (px - e20h) / a1 <= 3.0): continue
            trig = "break-counter"; side = 1
        if not trig: continue
        out.append(dict(sym=sym, i=i, t=T, trig=trig, side=side, px=px, a1=a1, s4=s4, s1=s1))
    return out

def sim(D, sg, V):
    d = D["d"]; i = sg["i"]; side = sg["side"]; px = sg["px"]; a1 = sg["a1"]
    nlb = V["n"]; k = V["k"]
    if side < 0: stop = max(x[2] for x in d[i - nlb + 1:i + 1]) + k * a1
    else: stop = min(x[3] for x in d[i - nlb + 1:i + 1]) - k * a1
    entry = px * (1 + side * SLIP / 100.0)
    if (side < 0 and stop <= entry) or (side > 0 and stop >= entry): return None
    R = abs(entry - stop); Rp = R / entry * 100
    if Rp > V["cap"]: return None
    be_px = entry + side * R * V["be"]; lock_px = entry * (1 + side * V["lock"] / 100.0)
    tp = entry + side * R * V["tp"]; trail = V["trail"] * a1 if V["trail"] else None
    t_in = sg["t"]; armed = False; hi = entry; lo = entry; weight = 1.0; acc = 0.0; cur = stop
    def net(ex, market):
        e = ex * (1 - side * SLIP / 100.0) if market else ex
        return side * (e / entry - 1) * 100 - 2 * FEE
    for q in range(i + 1, len(d)):
        t, o, h, l, c = d[q]
        hit = (h >= cur) if side < 0 else (l <= cur)
        if hit:
            gap = max(cur, o) if side < 0 else min(cur, o)
            acc += weight * net(gap, True); return dict(t_in=t_in, t_out=t + 900000, Rp=Rp, net=acc, R=acc / Rp, why="trail" if armed else "stop", sym=sg["sym"], trig=sg["trig"])
        if (l <= tp) if side < 0 else (h >= tp):
            acc += weight * net(tp, False); return dict(t_in=t_in, t_out=t + 900000, Rp=Rp, net=acc, R=acc / Rp, why="target", sym=sg["sym"], trig=sg["trig"])
        hi = max(hi, h); lo = min(lo, l)
        if not armed and ((l <= be_px) if side < 0 else (h >= be_px)):
            armed = True
            cur = min(cur, lock_px) if side < 0 else max(cur, lock_px)
            if V["partial"]:
                acc += 0.5 * net(be_px, False); weight = 0.5
        if armed and trail:
            tr = lo + trail if side < 0 else hi - trail
            cur = min(cur, tr) if side < 0 else max(cur, tr)
        if V["maxh"] and (t + 900000 - t_in) / 3600000.0 >= V["maxh"]:
            acc += weight * net(c, True); return dict(t_in=t_in, t_out=t + 900000, Rp=Rp, net=acc, R=acc / Rp, why="time", sym=sg["sym"], trig=sg["trig"])
    return None

def portfolio(trs, maxopen, cool_h, skip_hours, trig_only, one_counter=False):
    trs = sorted(trs, key=lambda x: x["t_in"]); acc = []; last_stop = {}
    for t in trs:
        if trig_only and t["trig"] != trig_only: continue
        hr = time.gmtime(t["t_in"] / 1000).tm_hour + time.gmtime(t["t_in"] / 1000).tm_min / 60.0
        if skip_hours and skip_hours[0] <= hr < skip_hours[1] and time.gmtime(t["t_in"] / 1000).tm_wday < 5: continue
        open_ = [a for a in acc if a["t_out"] > t["t_in"]]
        if any(a["sym"] == t["sym"] for a in open_): continue
        if len(open_) >= maxopen: continue
        if cool_h and t["sym"] in last_stop and t["t_in"] - last_stop[t["sym"]] < cool_h * 3600000: continue
        acc.append(t)
        if t["why"] == "stop": last_stop[t["sym"]] = t["t_out"]
    # cooldown uses exit time of earlier trades, which may be after later t_in only if overlapping (excluded by same-pair rule)
    return acc

def stats(acc):
    if not acc: return None
    rs = [a["R"] for a in acc]; w = [r for r in rs if r > 0]; ls = [-r for r in rs if r <= 0]
    seq = sorted(acc, key=lambda a: a["t_out"]); cum = 0; pk = 0; dd = 0
    for a in seq: cum += a["R"]; pk = max(pk, cum); dd = max(dd, pk - cum)
    ts = sorted(a["t_in"] for a in acc); mid = ts[len(ts) // 2]
    h1 = [a["R"] for a in acc if a["t_in"] < mid]; h2 = [a["R"] for a in acc if a["t_in"] >= mid]
    return dict(n=len(rs), win=100.0 * len(w) / len(rs), avg=sum(rs) / len(rs), tot=sum(rs), pf=(sum(w) / sum(ls)) if ls else 99, dd=dd,
                a1=(sum(h1) / len(h1)) if h1 else 0, a2=(sum(h2) / len(h2)) if h2 else 0, medR=statistics.median(rs))

BASE_V = dict(n=8, k=0.25, cap=1.5, tp=3.0, be=1.0, lock=0.2, trail=1.5, maxh=24, partial=False)
def V(**kw):
    v = dict(BASE_V); v.update(kw); return v
# name: (V, maxopen, cooldown_h, skip_hours, trig_only)
VARS = [
 ("base live(3open)", V(), 3, 0, None, None),
 ("base 2open", V(), 2, 0, None, None),
 ("base 2open cap3", V(cap=3.0), 2, 0, None, None),
 ("retest only", V(), 2, 0, None, "retest"),
 ("break only", V(), 2, 0, None, "break"),
 ("stop k0.75", V(k=0.75, cap=3.0), 2, 0, None, None),
 ("stop k1.25", V(k=1.25, cap=3.0), 2, 0, None, None),
 ("stop 12h struct", V(n=48, cap=3.0), 2, 0, None, None),
 ("stop 24h struct", V(n=96, cap=3.0), 2, 0, None, None),
 ("partial50 at 1R", V(partial=True), 2, 0, None, None),
 ("partial + k0.75", V(partial=True, k=0.75, cap=3.0), 2, 0, None, None),
 ("partial + 24h", V(partial=True, n=96, cap=3.0), 2, 0, None, None),
 ("tp 2R", V(tp=2.0), 2, 0, None, None),
 ("tp 1.5R", V(tp=1.5), 2, 0, None, None),
 ("tp 5R", V(tp=5.0), 2, 0, None, None),
 ("no trail (BE only)", V(trail=None), 2, 0, None, None),
 ("be at 1.5R", V(be=1.5), 2, 0, None, None),
 ("maxh 12", V(maxh=12), 2, 0, None, None),
 ("maxh 48", V(maxh=48), 2, 0, None, None),
 ("cooldown 4h", V(), 2, 4, None, None),
 ("cooldown 8h", V(), 2, 8, None, None),
 ("skip 13-14.5 UTC wd", V(), 2, 0, (13.0, 14.5), None),
]
CVARS = [
 ("COUNTER base", V(), 1, 0, None, None),
 ("COUNTER k0.75", V(k=0.75, cap=3.0), 1, 0, None, None),
 ("COUNTER 24h stop", V(n=96, cap=3.0), 1, 0, None, None),
 ("COUNTER partial", V(partial=True), 1, 0, None, None),
 ("COUNTER tp 2R", V(tp=2.0), 1, 0, None, None),
 ("COUNTER 3open", V(), 3, 0, None, None),
]
def fmt(name, s):
    if not s: return "%-24s n=0" % name
    return "%-24s n=%3d win=%4.1f%% avgR=%+.2f totR=%+6.1f PF=%4.2f DD=%5.1fR medR=%+.2f | half1 %+.2f half2 %+.2f" % (name, s["n"], s["win"], s["avg"], s["tot"], s["pf"], s["dd"], s["medR"], s["a1"], s["a2"])

def main():
    t0 = time.time(); P = {}
    for s in SYMS:
        P[s] = prep(s); print("loaded", s, len(P[s]["d"]), "15m", len(P[s]["h4"]), "4h", flush=True)
    d0 = P["BTC"]["d"]
    st = [P["BTC"]["d"][i] for i in range(len(d0))]
    # test period start: first candle with score available
    first = min(P[s]["h4"][min(P[s]["s4"])][0] + 14400000 for s in SYMS)
    print("data from", time.strftime("%Y-%m-%d", time.gmtime(d0[0][0] / 1000)), "to", time.strftime("%Y-%m-%d %H:%M", time.gmtime(d0[-1][0] / 1000)), "test from", time.strftime("%Y-%m-%d", time.gmtime(first / 1000)))
    bc = [x[4] for x in d0 if x[0] >= first]; print("BTC change over test period %.1f%%, max drawdown-ish range %.1f..%.1f" % ((bc[-1] / bc[0] - 1) * 100, min(bc), max(bc)))
    sg = {s: signals(s, P[s], "short") for s in SHORT}
    cg = {s: signals(s, P[s], "counter") for s in COUNTER}
    print("signals short", sum(len(v) for v in sg.values()), "counter", sum(len(v) for v in cg.values()), flush=True)
    print("=== SHORT (trend, retest+break), 13 pairs")
    res = []
    for name, v, mo, cool, sk, tr in VARS:
        trs = []
        for s in SHORT:
            for g in sg[s]:
                r = sim(P[s], g, v)
                if r: trs.append(r)
        acc = portfolio(trs, mo, cool, sk, tr); st_ = stats(acc); print(fmt(name, st_), "cand=%d" % len(trs), flush=True)
        if name == "base 2open":
            bysym = {}
            for a in acc: bysym.setdefault(a["sym"], []).append(a["R"])
            print("   by symbol:", {k: (len(x), round(sum(x), 1)) for k, x in sorted(bysym.items())})
            bywhy = {}
            for a in acc: bywhy.setdefault(a["why"], []).append(a["R"])
            print("   by exit:", {k: (len(x), round(sum(x) / len(x), 2)) for k, x in bywhy.items()})
            mon = {}
            for a in acc: mon.setdefault(time.strftime("%Y-%m", time.gmtime(a["t_in"] / 1000)), []).append(a["R"])
            print("   by month:", {k: (len(x), round(sum(x), 1)) for k, x in sorted(mon.items())})
    print("=== COUNTER-TREND long breakout, 12 pairs")
    for name, v, mo, cool, sk, tr in CVARS:
        trs = []
        for s in COUNTER:
            for g in cg[s]:
                r = sim(P[s], g, v)
                if r: trs.append(r)
        acc = portfolio(trs, mo, cool, sk, tr); print(fmt(name, stats(acc)), "cand=%d" % len(trs), flush=True)
    print("done in %.0fs" % (time.time() - t0))
if __name__ == "__main__": main()
