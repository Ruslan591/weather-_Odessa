"""chan_tv_study.py TF DAYS [classic] -- backtest of channel bounce (with trend) and breakout+retest limit orders,
channels from TradingView ports: regression (ADXAE, auto length by |R|, +-2 sigma) and Willy S/R channels (pivot pairs + parallel + quality),
baseline: classic_trendline.auto_channel (if classic arg). Each real result is compared with a CONTROL: same ATR geometry
(distance to level, stop, target, life) at RANDOM bars. No lookahead: channel at bar i is built from bars <= i-1.
Fees: entry maker 0.02, target maker 0.02, stop/time taker 0.05 (per side, %). Stop checked before target."""
import sys, os, json, time, urllib.request
import numpy as np

TF = sys.argv[1] if len(sys.argv) > 1 else "15m"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 90
USE_CLASSIC = "classic" in sys.argv[3:]
SYNTH = "synth" in sys.argv[3:]
ONLY = [a[5:].split(",") for a in sys.argv[3:] if a.startswith("only=")]
ONLY = ONLY[0] if ONLY else None
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "BNBUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT", "LTCUSDT", "DOTUSDT"]
if SYNTH:
    SYMS = SYMS[:2]
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
FEE_M, FEE_T = 0.02, 0.05
WARM = 400
DRAWS = 5


def klines(sym, tf, days):
    step = {"5m": 300000, "15m": 900000, "1h": 3600000}[tf]
    need = int(days * 86400000 / step) + 1
    end, parts = None, []
    while need > 0:
        lim = min(1000, need)
        d = None
        for b in BASES:
            u = "%s/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (b, sym, tf, lim) + ("&endTime=%d" % end if end else "")
            try:
                d = json.load(urllib.request.urlopen(u, timeout=20))
                break
            except Exception:
                d = None
        if not d:
            break
        parts.insert(0, d)
        end = int(d[0][0]) - 1
        need -= len(d)
        if len(d) < lim:
            break
    rows = [r for p in parts for r in p][:-1]  # last candle is unclosed
    return np.array([[float(x) for x in r[:6]] for r in rows])


def synth(seed):
    rng = np.random.default_rng(seed)
    n = 6000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n) + 0.0002 * np.sin(np.arange(n) / 300)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.0015, n)))
    l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.0015, n)))
    return np.c_[np.arange(n), o, h, l, c, np.ones(n)]


def atr14(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    a = np.zeros_like(tr)
    a[:n] = tr[:n].mean()
    for i in range(n, len(tr)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


# ---------------- channels: each returns (upper[], lower[], dir[]) valued AT bar i from data <= i-1 ----------------
def ch_regression(h, l, c, atr, lo_n=40, hi_n=350, k=2.0, flat=0.03):
    n = len(c)
    up = np.full(n, np.nan); lw = up.copy(); dr = np.zeros(n, int)
    xs = np.arange(hi_n, dtype=float)
    Sx = np.cumsum(xs); Sxx = np.cumsum(xs * xs)
    Ls = np.arange(lo_n, hi_n + 1); idx = Ls - 1
    for i in range(hi_n + 1, n):
        y = c[i - hi_n:i][::-1]
        Sy = np.cumsum(y); Sxy = np.cumsum(xs * y); Syy = np.cumsum(y * y)
        vx = Sxx[idx] - Sx[idx] ** 2 / Ls
        vy = Syy[idx] - Sy[idx] ** 2 / Ls
        cv = Sxy[idx] - Sx[idx] * Sy[idx] / Ls
        ok = (vx > 0) & (vy > 0)
        r = np.where(ok, np.abs(cv) / np.sqrt(np.where(ok, vx * vy, 1.0)), -1.0)
        m = int(np.argmax(r))
        if r[m] < 0:
            continue
        Lb = int(Ls[m]); rev = cv[m] / vx[m]
        sse = max(vy[m] - rev * cv[m], 0.0)
        sd = np.sqrt(sse / max(Lb - 2, 1))
        meanY = Sy[idx[m]] / Lb; meanX = (Lb - 1) / 2.0
        nxt = meanY - rev * meanX - rev  # regression value at bar i
        slope = -rev
        up[i] = nxt + k * sd; lw[i] = nxt - k * sd
        th = flat * atr[i - 1]
        dr[i] = 1 if slope > th else (-1 if slope < -th else 0)
    return up, lw, dr


def _find(basePs, baseIs, oppPs, oppIs, i, upc, atr_i, minb, maxb, minq, qw, h, l):
    best, bq = None, 0.0
    sz = len(basePs)
    for a in range(sz - 1, max(0, sz - 8) - 1, -1):
        for b in range(a - 1, max(0, a - 5) - 1, -1):
            x1, y1, x2, y2 = baseIs[b], basePs[b], baseIs[a], basePs[a]
            span = x2 - x1
            if span < minb or span > maxb:
                continue
            if (upc and y2 <= y1) or ((not upc) and y2 >= y1):
                continue
            sl = (y2 - y1) / span
            offs = [oppPs[k] - (y1 + sl * (oppIs[k] - x1)) for k in range(len(oppPs)) if oppIs[k] >= x1]
            if not offs:
                continue
            off = max(offs) if upc else min(offs)
            if (upc and off <= 0) or ((not upc) and off >= 0):
                continue
            tot = i - x1
            if tot <= 0:
                continue
            cl = min(tot, qw)
            bars = np.arange(i - cl + 1, i + 1)
            bl = y1 + sl * (bars - x1); pl = bl + off; tol = atr_i * 0.05
            if upc:
                inn = (l[bars] >= bl - tol) & (h[bars] <= pl + tol)
            else:
                inn = (h[bars] <= bl + tol) & (l[bars] >= pl - tol)
            q = inn.sum() / cl
            if q >= minq and q > bq:
                bq = q; best = (x1, y1, x2, y2, off)
    return best, bq


def ch_willy(h, l, c, atr, piv=10, minb=10, maxb=400, minq=0.55):
    """returns two series: up channels and down channels"""
    n = len(c)
    S = {k: [np.full(n, np.nan), np.full(n, np.nan)] for k in ("up", "dn")}
    hiP, hiI, loP, loI = [], [], [], []
    st = {"up": None, "dn": None}; qual = {"up": 0.0, "dn": 0.0}
    for i in range(n):
        for key in ("up", "dn"):
            s = st[key]
            if s:
                x1, y1, x2, y2, off = s
                b = y1 + (y2 - y1) / (x2 - x1) * (i - x1)
                if key == "up":
                    S[key][0][i] = b + off; S[key][1][i] = b
                else:
                    S[key][0][i] = b; S[key][1][i] = b + off
        p = i - piv
        newHi = newLo = False
        if p >= piv:
            if h[p] >= h[p - piv:i + 1].max() and (h[p - piv:p] < h[p]).all():
                hiP.append(h[p]); hiI.append(p); newHi = True
            if l[p] <= l[p - piv:i + 1].min() and (l[p - piv:p] > l[p]).all():
                loP.append(l[p]); loI.append(p); newLo = True
            hiP[:] = hiP[-40:]; hiI[:] = hiI[-40:]; loP[:] = loP[-40:]; loI[:] = loI[-40:]
        for key in ("up", "dn"):
            if st[key] and i - st[key][2] > maxb:
                st[key] = None; qual[key] = 0.0
        if (newHi or newLo) and i >= max(piv * 4, 50):
            if len(loP) >= 2:
                r, q = _find(loP, loI, hiP, hiI, i, True, atr[i], minb, maxb, minq, min(maxb, 500), h, l)
                if r and q > qual["up"] * 0.7:
                    st["up"] = r; qual["up"] = q
            if len(hiP) >= 2:
                r, q = _find(hiP, hiI, loP, loI, i, False, atr[i], minb, maxb, minq, min(maxb, 500), h, l)
                if r and q > qual["dn"] * 0.7:
                    st["dn"] = r; qual["dn"] = q
    n_up = np.where(np.isnan(S["up"][0]), 0, 1); n_dn = np.where(np.isnan(S["dn"][0]), 0, -1)
    return (S["up"][0], S["up"][1], n_up), (S["dn"][0], S["dn"][1], n_dn)


def ch_classic(o, h, l, c, atr):
    sys.path.insert(0, "/opt/trading-bot/classic")
    import classic_trendline as T
    hh, ll = T.anchor_series(o, h, l, c)
    pv = T.pivots(hh, ll)
    n = len(c)
    up = np.full(n, np.nan); lw = up.copy(); dr = np.zeros(n, int)
    for i, st in T._walk(hh, ll, c, atr, pv, n):
        if st and st.get("lower") and st.get("upper") and st["type"] in ("channel_up", "channel_down"):
            up[i] = T.at(st["upper"], i); lw[i] = T.at(st["lower"], i)
            dr[i] = 1 if st["type"] == "channel_up" else -1
    return up, lw, dr



def ch_afd(h, l, c, atr, swing=8, pool=10, horizon=600, volw=14, cont=0.10, minw=0.5, maxw=8.0, allow=0.0, pend_wait=20):
    """Auto Trend Channels [AFD] (layer 0 only): strict pivots (confirmed swing bars later), channel = line through two same-side pivots
    + parallel through the farthest opposite pivot between them; width 0.5..8 avgTR, all bars between anchors contained (0.1 avgTR);
    becomes ACTIVE at the first close inside; ends (watch) at a close beyond a boundary. One active channel at a time."""
    n = len(c)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); tr[0] = h[0] - l[0]
    sma = np.full(n, np.nan)
    cs = np.cumsum(tr)
    for i in range(volw - 1, n):
        sma[i] = (cs[i] - (cs[i - volw] if i >= volw else 0.0)) / volw
    up = np.full(n, np.nan); lw = up.copy(); dr = np.zeros(n, int)
    highs, lows, pending, used = [], [], [], {}
    active = None

    def lower_at(ch, x):
        base = ch["ap"] + ch["slope"] * (x - ch["ai"])
        return base if ch["dir"] == 1 else base - ch["w"]

    def upper_at(ch, x):
        base = ch["ap"] + ch["slope"] * (x - ch["ai"])
        return base + ch["w"] if ch["dir"] == 1 else base

    for i in range(n):
        if active:
            up[i] = upper_at(active, i); lw[i] = lower_at(active, i); dr[i] = active["dir"]
        vol = sma[i]
        for k in [k for k, v in used.items() if i - v > horizon]:
            del used[k]
        pending[:] = [p for p in pending if i - p["ai"] <= horizon and i - p["built"] <= pend_wait]
        if active:
            if i - active["ai"] > horizon:
                active = None
            elif i > active["avail"]:
                if c[i] > upper_at(active, i) + allow * active["vol"] or c[i] < lower_at(active, i) - allow * active["vol"]:
                    active = None
        ctr = i - swing
        newp = None
        if ctr - swing >= 0:
            sh = h[ctr - swing:i + 1]; sl = l[ctr - swing:i + 1]
            hp = bool((sh < h[ctr]).sum() == len(sh) - 1)
            lp = bool((sl > l[ctr]).sum() == len(sl) - 1)
            if hp != lp:
                newp = (ctr, h[ctr], "H") if hp else (ctr, l[ctr], "L")
                (highs if hp else lows).append((ctr, h[ctr] if hp else l[ctr]))
        for arr in (highs, lows):
            while arr and (i - arr[0][0] > horizon or len(arr) > pool):
                arr.pop(0)
        if newp and not np.isnan(vol) and vol > 0:
            same, opp = (highs, lows) if newp[2] == "H" else (lows, highs)
            d = -1 if newp[2] == "H" else 1
            ci, cp = newp[0], newp[1]
            for (ai, ap) in same[:-1]:
                if not (ci - ai >= 2 * swing and i - ai <= horizon and d * (cp - ap) > 0):
                    continue
                slope = (cp - ap) / (ci - ai)
                w, bi = 0.0, None
                for (pi_, pp) in opp:
                    if ai < pi_ < ci:
                        r = d * (pp - (ap + slope * (pi_ - ai)))
                        if r > w:
                            w, bi = r, pi_
                if bi is None or w < minw * vol or w > maxw * vol:
                    continue
                ch = dict(ai=ai, ap=ap, ci=ci, bi=bi, dir=d, slope=slope, w=w, vol=vol, built=i, key=(d, ai, bi, ci))
                xs = np.arange(ai, ci + 1)
                base = ap + slope * (xs - ai)
                upp = base + w if d == 1 else base
                low = base if d == 1 else base - w
                if (h[ai:ci + 1] > upp + cont * vol).any() or (l[ai:ci + 1] < low - cont * vol).any():
                    continue
                pending.append(ch)
            while len(pending) > 32:
                pending.pop(0)
        if active is None and not np.isnan(vol):
            best, bk = None, None
            for p in pending:
                if p["key"] in used:
                    continue
                lo_, hi_ = lower_at(p, i), upper_at(p, i)
                if not (lo_ <= c[i] <= hi_):
                    continue
                dist = abs(c[i] - (lo_ + p["w"] * 0.5)) / p["w"]
                k = (p["ci"], -dist, p["ci"] - p["ai"], -p["bi"], p["dir"])
                if bk is None or k > bk:
                    best, bk = p, k
            if best is not None:
                pending.remove(best)
                best["avail"] = i
                used[best["key"]] = best["ai"]
                active = best
    return up, lw, dr

# ---------------- orders and simulation ----------------
def gen_bounce(c, atr, up, lw, dr, tgt_mode):
    out = []
    for i in range(WARM, len(c)):
        if np.isnan(up[i]) or np.isnan(lw[i]) or dr[i] == 0:
            continue
        a = atr[i - 1]; U, L = up[i], lw[i]
        if U - L < 1.5 * a:
            continue
        if dr[i] > 0:
            side, lv, d = 1, L, (c[i - 1] - L) / a
        else:
            side, lv, d = -1, U, (U - c[i - 1]) / a
        if not 0 <= d <= 3:
            continue
        risk = max(1.2 * a, 0.005 * lv); stop = lv - side * risk
        if tgt_mode == "opp":
            tg = U - 0.1 * a if side > 0 else L + 0.1 * a
        else:
            tg = (U + L) / 2
        if (tg - lv) * side <= 0:
            continue
        out.append(dict(side=side, i0=i, life=1, level=lv, stop=stop, tgt=tg, cancel=None, maxb=48, dist=d, rk=risk / a, tgd=abs(tg - lv) / a, cd=0.0))
    return out


def gen_retest(c, atr, up, lw, dr):
    out = []
    for i in range(WARM + 2, len(c)):
        j = i - 1
        if np.isnan(up[j]) or np.isnan(lw[j]) or dr[j] == 0 or np.isnan(up[j - 1]):
            continue
        a = atr[j]; buf = 0.2 * a
        if dr[j] < 0 and c[j] > up[j] + buf and c[j - 1] <= up[j - 1] + 0.2 * atr[j - 1]:
            side, lv = 1, up[j]; d = (c[j] - lv) / a
        elif dr[j] > 0 and c[j] < lw[j] - buf and c[j - 1] >= lw[j - 1] - 0.2 * atr[j - 1]:
            side, lv = -1, lw[j]; d = (lv - c[j]) / a
        else:
            continue
        if not 0.3 <= d <= 4:
            continue
        w = up[j] - lw[j]
        if w < 1.5 * a:
            continue
        risk = max(1.2 * a, 0.005 * lv); stop = lv - side * risk
        tg = lv + side * max(w, 2 * risk); cancel = lv - side * 0.7 * a
        out.append(dict(side=side, i0=i, life=24, level=lv, stop=stop, tgt=tg, cancel=cancel, maxb=48, dist=d, rk=risk / a, tgd=abs(tg - lv) / a, cd=0.7))
    return out


def run_order(o, h, l, c, od):
    s, lv, n = od["side"], od["level"], len(c)
    for j in range(od["i0"], min(od["i0"] + od["life"], n)):
        if (s > 0 and l[j] < lv) or (s < 0 and h[j] > lv):
            entry = min(lv, o[j]) if s > 0 else max(lv, o[j])
            stop, tgt = od["stop"], od["tgt"]
            for k in range(j, min(j + od["maxb"] + 1, n)):
                if (s > 0 and l[k] <= stop) or (s < 0 and h[k] >= stop):
                    ex = (min(stop, o[k]) if s > 0 else max(stop, o[k])) if k > j else stop
                    return dict(fill=j, exit=k, gross=s * (ex - entry) / entry * 100, fee=FEE_M + FEE_T, why="S")
                if k > j and ((s > 0 and h[k] >= tgt) or (s < 0 and l[k] <= tgt)):
                    return dict(fill=j, exit=k, gross=s * (tgt - entry) / entry * 100, fee=FEE_M * 2, why="T")
            k = min(j + od["maxb"], n - 1)
            return dict(fill=j, exit=k, gross=s * (c[k] - entry) / entry * 100, fee=FEE_M + FEE_T, why="X")
        cp = od.get("cancel")
        if cp is not None and ((s > 0 and c[j] < cp) or (s < 0 and c[j] > cp)):
            return None
    return None


def real_trades(o, h, l, c, orders):
    res, busy, att = [], -1, 0
    for od in sorted(orders, key=lambda x: x["i0"]):
        if od["i0"] <= busy:
            continue
        att += 1
        r = run_order(o, h, l, c, od)
        if r:
            busy = r["exit"]; r["i0"] = od["i0"]; res.append(r)
    return res, att


def control_trades(o, h, l, c, atr, orders, rng):
    res, n = [], len(c)
    for od in orders:
        for _ in range(DRAWS):
            j = int(rng.integers(WARM, n - od["life"] - od["maxb"] - 2))
            a = atr[j - 1]; s = od["side"]
            lv = c[j - 1] - s * od["dist"] * a
            cd = dict(side=s, i0=j, life=od["life"], level=lv, stop=lv - s * od["rk"] * a, tgt=lv + s * od["tgd"] * a,
                      cancel=(lv - s * od["cd"] * a) if od["cd"] else None, maxb=od["maxb"])
            r = run_order(o, h, l, c, cd)
            if r:
                res.append(r)
    return res


def fmt(rows, nord, ndraw=1):
    if not rows:
        return "fills 0"
    net = np.array([x["gross"] - x["fee"] for x in rows]); gr = np.array([x["gross"] for x in rows])
    return "fills %5d (%4.1f%%) win %4.1f%% gross %+6.3f net %+6.3f%% (se %.3f)" % (len(net), 100.0 * len(net) / max(nord * ndraw, 1), 100.0 * (net > 0).mean(), gr.mean(), net.mean(), net.std() / np.sqrt(len(net)))


def main():
    t0 = time.time()
    acc = {}
    rng = np.random.default_rng(7)
    for sym_i, sym in enumerate(SYMS):
        a = synth(sym_i) if SYNTH else klines(sym, TF, DAYS)
        if len(a) < WARM + 600:
            print(sym, "short data", len(a), flush=True); continue
        t, o, h, l, c = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        atr = atr14(h, l, c); n = len(c)
        chans = {}
        if ONLY is None or "regr" in ONLY:
            chans["regr"] = ch_regression(h, l, c, atr)
        if ONLY is None or "willy" in ONLY:
            wu, wd = ch_willy(h, l, c, atr)
            chans["willy_up"] = wu; chans["willy_dn"] = wd
        if ONLY is None or "afd" in ONLY:
            chans["afd"] = ch_afd(h, l, c, atr)
        if "afd" in chans and "regr" in chans:
            ua, la, da = chans["afd"]; ur, lr, dg = chans["regr"]
            agree = (da != 0) & (da == dg)
            chans["combo_afd"] = (ua, la, np.where(agree, da, 0))
            chans["combo_regr"] = (ur, lr, np.where(agree, dg, 0))
        if USE_CLASSIC and sym_i < 8:
            try:
                chans["classic"] = ch_classic(o, h, l, c, atr)
            except Exception as e:
                print("classic fail", repr(e)[:150], flush=True)
        print("%s bars %d  time %.0fs  channel-bars: %s" % (sym, n, time.time() - t0, {k: int((v[2] != 0).sum()) for k, v in chans.items()}), flush=True)
        for name, (up, lw, dr) in chans.items():
            rules = [("bounce/opp", gen_bounce(c, atr, up, lw, dr, "opp")), ("bounce/mid", gen_bounce(c, atr, up, lw, dr, "mid")), ("retest", gen_retest(c, atr, up, lw, dr))]
            for rname, ords in rules:
                A = acc.setdefault((name, rname), dict(nord=0, real=[], ctl=[], nA=0, rA=[], rB=[]))
                A["nord"] += len(ords)
                rt, att = real_trades(o, h, l, c, ords)
                A["att"] = A.get("att", 0) + att
                ct = control_trades(o, h, l, c, atr, ords, rng)
                A["real"] += rt; A["ctl"] += ct
                A["rA"] += [x for x in rt if x["i0"] < n // 2]; A["rB"] += [x for x in rt if x["i0"] >= n // 2]
    print("\n==== TF %s, %d days, pairs %d. net = after fees. control = same ATR geometry at random bars (x%d) ====" % (TF, DAYS, len(SYMS), DRAWS))
    for (name, rname), A in sorted(acc.items()):
        print("\n[%s | %s] orders %d" % (name, rname, A["nord"]))
        print("  REAL    ", fmt(A["real"], A.get("att", 1)), " (orders placed w/o open pos: %d)" % A.get("att", 0))
        print("  CONTROL ", fmt(A["ctl"], A["nord"], DRAWS))
        print("  halves  first:", fmt(A["rA"], 1).split(" net ")[-1] if A["rA"] else "-", "| second:", fmt(A["rB"], 1).split(" net ")[-1] if A["rB"] else "-")
    print("\nDONE %.0fs" % (time.time() - t0), flush=True)


main()
