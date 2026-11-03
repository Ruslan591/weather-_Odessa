# Channel-border limit orders across many pairs, first fill takes the slot, others cancelled. ASCII only.
import sys, os, json, time, random, statistics as S, urllib.request
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np
import classic_trendline as tl
from multiprocessing import Pool
BASE = "https://data-api.binance.vision/api/v3/klines"
CD = "/tmp/bt5"; os.makedirs(CD, exist_ok=True)
TF = sys.argv[1] if len(sys.argv) > 1 else "1h"; TFMS = {"15m": 900000, "1h": 3600000, "4h": 14400000}[TF]
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 300
SYMS = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT APT ATOM".split()
MAK = 0.02; TAK = 0.05; SL = 0.02
def fetch(sym):
    fn = "%s/%s_%s.json" % (CD, sym, TF)
    if os.path.exists(fn) and time.time() - os.path.getmtime(fn) < 6 * 3600: return json.load(open(fn))
    now = int(time.time() * 1000); st = now - DAYS * 86400000; out = []
    while st < now:
        u = "%s?symbol=%sUSDT&interval=%s&limit=1000&startTime=%d" % (BASE, sym, TF, st); d = None
        for a in range(4):
            try: d = json.load(urllib.request.urlopen(u, timeout=20)); break
            except Exception: time.sleep(1.5)
        if not d: break
        out += d; st = int(d[-1][0]) + TFMS
        if len(d) < 1000: break
    res = []; seen = set()
    for k in out:
        if int(k[0]) in seen or int(k[0]) + TFMS > now: continue
        seen.add(int(k[0])); res.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])])
    json.dump(res, open(fn, "w")); return res
def geom(sym):
    d = fetch(sym); t = np.array([x[0] for x in d]); o = np.array([x[1] for x in d]); h = np.array([x[2] for x in d]); l = np.array([x[3] for x in d]); c = np.array([x[4] for x in d])
    n = len(c); atr = np.zeros(n); a = None
    for i in range(1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])); a = tr if a is None else a + (tr - a) / 14; atr[i] = a
    hh, ll = tl.anchor_series(o, h, l, c); piv = tl.pivots(hh[:n], ll[:n]); orders = []
    for i, st in tl._walk(hh, ll, c, atr, piv, n, 60):
        if not st or not st.get("lower") or not st.get("upper") or st["type"] not in ("range", "channel_up", "channel_down"): continue
        a = atr[i - 1]
        if a <= 0: continue
        Si = tl.at(st["lower"], i); Ri = tl.at(st["upper"], i)
        if (Ri - Si) < 1.5 * a: continue
        px = c[i - 1]
        dl = (px - Si) / a; ds = (Ri - px) / a
        if 0.0 <= dl <= 2.5: orders.append((i, "L", dl, (Ri - Si) / a, st["type"]))
        if 0.0 <= ds <= 2.5: orders.append((i, "S", ds, (Ri - Si) / a, st["type"]))
    return sym, dict(t=t.tolist(), o=o.tolist(), h=h.tolist(), l=l.tolist(), c=c.tolist(), atr=atr.tolist(), orders=orders)
def trade(G, i, side, price, stop, tp, maxh):
    t, h, l, c = G["t"], G["h"], G["l"], G["c"]; n = len(c); sg = 1 if side == "L" else -1
    Rp = abs(price - stop) / price * 100
    if Rp <= 0: return None
    # fill candle: stop check only
    if (l[i] <= stop) if sg > 0 else (h[i] >= stop):
        net = sg * (stop * (1 - sg * SL / 100.0) / price - 1) * 100 - MAK - TAK; return dict(t_in=t[i], t_out=t[i] + TFMS, net=net, Rp=Rp, R=net / Rp, why="stop")
    for q in range(i + 1, n):
        if (l[q] <= stop) if sg > 0 else (h[q] >= stop):
            ex = min(stop, G["o"][q]) if sg > 0 else max(stop, G["o"][q]); ex = ex * (1 - sg * SL / 100.0)
            net = sg * (ex / price - 1) * 100 - MAK - TAK; return dict(t_in=t[i], t_out=t[q] + TFMS, net=net, Rp=Rp, R=net / Rp, why="stop")
        if (h[q] >= tp) if sg > 0 else (l[q] <= tp):
            net = sg * (tp / price - 1) * 100 - 2 * MAK; return dict(t_in=t[i], t_out=t[q] + TFMS, net=net, Rp=Rp, R=net / Rp, why="tp")
        if q - i >= maxh:
            ex = c[q] * (1 - sg * SL / 100.0); net = sg * (ex / price - 1) * 100 - MAK - TAK; return dict(t_in=t[i], t_out=t[q] + TFMS, net=net, Rp=Rp, R=net / Rp, why="time")
    return None
def make_orders(GG, m, tpbuf, ctl, rng):
    out = []
    for s, G in GG.items():
        ords = G["orders"]; n = len(G["c"])
        for (i, side, dist, width, typ) in ords:
            ii = i
            if ctl:
                ii = rng.randint(70, n - 2)
            a = G["atr"][ii - 1]; px = G["c"][ii - 1]
            if a <= 0: continue
            if side == "L":
                price = px - dist * a; stop = price - m * a; tp = price + (width - tpbuf) * a  # target = opposite line (width ATR above lower line), minus buffer
            else:
                price = px + dist * a; stop = price + m * a; tp = price - (width - tpbuf) * a
            if tp <= 0 or price <= 0 or stop <= 0: continue
            out.append((G["t"][ii], s, ii, side, price, stop, tp, typ))
    out.sort(key=lambda x: x[0]); return out
def portfolio(GG, orders, maxopen, maxh, rng, sides=None):
    open_ = []; trades = []; placed = 0; filled = 0; k = 0
    while k < len(orders):
        tt = orders[k][0]; grp = []
        while k < len(orders) and orders[k][0] == tt: grp.append(orders[k]); k += 1
        open_ = [(s, to) for (s, to) in open_ if to > tt]
        fl = []
        for (t_, s, i, side, price, stop, tp, typ) in grp:
            if sides and side not in sides: continue
            placed += 1
            G = GG[s]
            if side == "L" and not (G["l"][i] < price): continue
            if side == "S" and not (G["h"][i] > price): continue
            if any(x[0] == s for x in open_): continue
            fl.append((s, i, side, price, stop, tp, typ))
        slots = maxopen - len(open_)
        if slots <= 0 or not fl: filled += len(fl); continue
        rng.shuffle(fl); filled += len(fl)
        for (s, i, side, price, stop, tp, typ) in fl[:slots]:
            tr = trade(GG[s], i, side, price, stop, tp, maxh)
            if tr: tr["sym"] = s; tr["side"] = side; trades.append(tr); open_.append((s, tr["t_out"]))
    return trades, placed, filled
def stats(tr):
    if not tr: return "n=0"
    rs = [x["R"] for x in tr]; w = [r for r in rs if r > 0]; ls = [-r for r in rs if r <= 0]
    ts = sorted(x["t_in"] for x in tr); mid = ts[len(ts) // 2]
    h1 = [x["R"] for x in tr if x["t_in"] < mid]; h2 = [x["R"] for x in tr if x["t_in"] >= mid]
    return "n=%d win=%.0f%% avgR=%+.2f netpct=%+.3f PF=%.2f SE=%.2f half1 %+.2f half2 %+.2f tp%%=%.0f" % (len(rs), 100 * len(w) / len(rs), S.mean(rs), S.mean(x["net"] for x in tr), (sum(w) / sum(ls)) if ls else 99, S.pstdev(rs) / len(rs) ** 0.5,
        S.mean(h1) if h1 else 0, S.mean(h2) if h2 else 0, 100 * sum(1 for x in tr if x["why"] == "tp") / len(tr))
if __name__ == "__main__":
    t0 = time.time()
    with Pool(min(os.cpu_count() or 2, 6)) as p: res = p.map(geom, SYMS)
    GG = dict(res); print("TF", TF, "days", DAYS, "geometry done %.0fs" % (time.time() - t0), {s: (len(G["c"]), len(G["orders"])) for s, G in GG.items()}, flush=True)
    d0 = GG["BTC"]; print("period", time.strftime("%Y-%m-%d", time.gmtime(d0["t"][60] / 1000)), "..", time.strftime("%Y-%m-%d", time.gmtime(d0["t"][-1] / 1000)), "BTC %.1f%%" % ((d0["c"][-1] / d0["c"][60] - 1) * 100), flush=True)
    for mo in [1, 3]:
        for m in [0.3, 0.7, 1.2]:
            for tpb in [0.1]:
                maxh = 48
                rng = random.Random(1)
                tr, pl, fi = portfolio(GG, make_orders(GG, m, tpb, False, rng), mo, maxh, rng)
                print("maxopen=%d stop=+%.1fATR | REAL: fill %.1f%% (%d/%d) %s" % (mo, m, 100.0 * fi / max(1, pl), fi, pl, stats(tr)), flush=True)
                cs = []
                for sd in (11, 12, 13):
                    rng = random.Random(sd); ords = make_orders(GG, m, tpb, True, rng)
                    trc, plc, fic = portfolio(GG, ords, mo, maxh, rng); cs.append((trc, plc, fic))
                allc = [x for c_ in cs for x in c_[0]]
                print("                     | CTRL(3 seeds): fill %.1f%% %s" % (100.0 * sum(c_[2] for c_ in cs) / max(1, sum(c_[1] for c_ in cs)), stats(allc)), flush=True)
        # by side for the middle stop
    print("done %.0fs" % (time.time() - t0))
