# -*- coding: utf-8 -*-
"""leadlag_study.py -- исследование «паровозика»: ведёт ли BTC альты на 1m и даёт ли отставание (zG) предсказуемое догоняющее движение.
Данные: 1m свечи Binance (data-api.binance.vision) за DAYS суток по парам из /tmp/klcache/*_5m_1000.json. Только stdlib.
Часть 1: корреляция 1m-доходностей альта[t] и BTC[t-L], L=0..5 (L>0: BTC ведёт), лучший лаг, доля суток с лучшим лагом > 0.
Часть 2: событийный тест. В каждую минуту t: окно n=90 прошлых доходностей -> rho, beta, zB (ход BTC за k=3 мин в сигмах), zG (отставание альта).
  Событие: |zB| >= ZB_MIN. Смотрим ход альта в сторону BTC за h=3,5,10 мин ПОСЛЕ t (bps). Корзины по zG, отдельно rho >= 0.6; одно событие на пару за 5 минут.
  Train = первые 60% времени, test = последние 40%. Запуск: python3 leadlag_study.py [DAYS] ; вывод ASCII, JSON в /tmp/ll_result.json."""
import glob, json, math, os, sys, time, urllib.request
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
N = 90; K = 3; HS = (3, 5, 10); ZB_MIN = 1.5; COOL = 5
CACHE = "/tmp/ll_cache"; os.makedirs(CACHE, exist_ok=True)
BASE = "https://data-api.binance.vision/api/v3/klines"


def fetch(sym):
    fn = "%s/%s.json" % (CACHE, sym)
    if os.path.exists(fn) and time.time() - os.path.getmtime(fn) < 6 * 3600: return {int(k): v for k, v in json.load(open(fn)).items()}
    end = int(time.time() // 60 * 60 * 1000); start = end - DAYS * 86400000; out = {}; t = start
    while t < end:
        u = "%s?symbol=%sUSDT&interval=1m&limit=1000&startTime=%d" % (BASE, sym, t)
        for a in range(3):
            try: raw = json.load(urllib.request.urlopen(u, timeout=15)); break
            except Exception: raw = None; time.sleep(1.5)
        if not raw: break
        for k in raw: out[int(k[0])] = float(k[4])
        t = int(raw[-1][0]) + 60000
        time.sleep(0.12)
    json.dump({str(k): v for k, v in out.items()}, open(fn, "w"))
    return out


def corr(x, y):
    n = len(x)
    if n < 50: return None
    mx = sum(x) / n; my = sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return None if sx == 0 or sy == 0 else sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def aligned(ca, cb):
    ts = sorted(set(ca) & set(cb)); return ts


def series(ca, cb):
    ts = aligned(ca, cb); T = []; pa = []; pb = []
    for t in ts: T.append(t); pa.append(ca[t]); pb.append(cb[t])
    return T, pa, pb


def part1(sym, T, pa, pb):
    ra = [math.log(pa[i] / pa[i - 1]) if T[i] - T[i - 1] == 60000 else None for i in range(1, len(T))]
    rb = [math.log(pb[i] / pb[i - 1]) if T[i] - T[i - 1] == 60000 else None for i in range(1, len(T))]
    def cl(L, lo=0, hi=None):
        xs = []; ys = []
        for i in range(max(L, lo), hi if hi is not None else len(ra)):
            if ra[i] is None or rb[i - L] is None: continue
            xs.append(ra[i]); ys.append(rb[i - L])
        return corr(xs, ys)
    cs = [cl(L) for L in range(6)]
    if cs[0] is None: return None
    best = max(range(6), key=lambda L: cs[L] if cs[L] is not None else -9)
    # по суткам
    day = 1440; nd = len(ra) // day; nlag = 0; used = 0
    for d in range(nd):
        c = [cl(L, d * day, (d + 1) * day) for L in range(4)]
        if None in c: continue
        used += 1
        if max(range(4), key=lambda L: c[L]) > 0 and c[max(range(4), key=lambda L: c[L])] > c[0] + 0.02: nlag += 1
    return {"c": [None if x is None else round(x, 3) for x in cs], "best": best, "days_lag": nlag, "days": used}


def events(sym, T, pa, pb):
    n = len(T); la = [math.log(x) for x in pa]; lb = [math.log(x) for x in pb]
    ra = [0.0] + [la[i] - la[i - 1] for i in range(1, n)]; rb = [0.0] + [lb[i] - lb[i - 1] for i in range(1, n)]
    ok = [True] + [T[i] - T[i - 1] == 60000 for i in range(1, n)]
    P = lambda x: [0.0] + [sum_ for sum_ in __import__("itertools").accumulate(x)]
    Sa = P(ra); Sb = P(rb); Saa = P([x * x for x in ra]); Sbb = P([x * x for x in rb]); Sab = P([x * y for x, y in zip(ra, rb)])
    bad = [0] + list(__import__("itertools").accumulate([0 if o else 1 for o in ok]))
    out = []; last = -999; hmax = max(HS)
    for t in range(N + 1, n - hmax):
        lo = t - N + 1                                    # окно доходностей lo..t
        if bad[t + 1] - bad[lo] > 0 or bad[t + hmax + 1] - bad[t + 1] > 0: continue
        m = N; ma = (Sa[t + 1] - Sa[lo]) / m; mb = (Sb[t + 1] - Sb[lo]) / m
        va = (Saa[t + 1] - Saa[lo]) / m - ma * ma; vb = (Sbb[t + 1] - Sbb[lo]) / m - mb * mb; cv = (Sab[t + 1] - Sab[lo]) / m - ma * mb
        if va <= 0 or vb <= 0: continue
        rho = cv / math.sqrt(va * vb); beta = cv / vb; vr = va - cv * cv / vb
        sb_k = sum(rb[t - K + 1:t + 1]); sa_k = sum(ra[t - K + 1:t + 1])
        zB = sb_k / (math.sqrt(vb) * math.sqrt(K))
        if abs(zB) < ZB_MIN or t - last < COOL: continue
        dr = 1 if sb_k > 0 else -1
        gap = (beta * sb_k - sa_k) * dr; zG = gap / (math.sqrt(vr) * math.sqrt(K)) if vr > 0 else 0.0
        fw = [dr * (la[t + h] - la[t]) * 1e4 for h in HS]; fb = [dr * (lb[t + h] - lb[t]) * 1e4 for h in HS]
        out.append((T[t], rho, beta, zB, zG, fw, fb)); last = t
    return out


def stat(xs):
    n = len(xs)
    if n == 0: return (0, None, None, None)
    m = sum(xs) / n
    if n < 3: return (n, m, None, None)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)); hit = sum(1 for x in xs if x > 0) / n
    return (n, m, m / (sd / math.sqrt(n)) if sd > 0 else None, hit)


def fm(v, f="%.1f"): return "-" if v is None else f % v


def main():
    syms = sorted(os.path.basename(p).split("_")[0] for p in glob.glob("/tmp/klcache/*_5m_1000.json")); syms = [s for s in syms if s != "BTC"]
    print("pairs", len(syms), "days", DAYS); sys.stdout.flush()
    cb = fetch("BTC"); print("btc candles", len(cb)); sys.stdout.flush()
    allev = []; res1 = {}
    for s in syms:
        try: ca = fetch(s)
        except Exception as e: print("skip", s, str(e)[:60]); continue
        if len(ca) < 3000: print("skip short", s, len(ca)); continue
        T, pa, pb = series(ca, cb)
        p1 = part1(s, T, pa, pb)
        if p1: res1[s] = p1
        for e in events(s, T, pa, pb): allev.append((s,) + e)
    print("\n== PART1: corr(alt[t], BTC[t-L]) L=0..5, best lag, days with lag>0 ==")
    for s, p in sorted(res1.items(), key=lambda kv: -kv[1]["c"][0]):
        print("%-6s %s best=%d days_lag=%d/%d" % (s, " ".join(fm(x, "%.2f") for x in p["c"]), p["best"], p["days_lag"], p["days"]))
    nb = sum(1 for p in res1.values() if p["best"] > 0); print("pairs with best lag>0: %d of %d" % (nb, len(res1)))
    avg = [sum(p["c"][L] for p in res1.values()) / len(res1) for L in range(6)]; print("avg corr by lag:", " ".join("%.3f" % x for x in avg))
    if not allev: print("no events"); return
    tmin = min(e[1] for e in allev); tmax = max(e[1] for e in allev); tcut = tmin + 0.6 * (tmax - tmin)
    print("\n== PART2: events |zB|>=%.1f (k=%d min), n=%d total; fwd alt move in BTC direction, bps (h=%s min) ==" % (ZB_MIN, K, len(allev), ",".join(map(str, HS))))
    buckets = [("zG<0", lambda e: e[5] < 0), ("0<=zG<1", lambda e: 0 <= e[5] < 1), ("1<=zG<2", lambda e: 1 <= e[5] < 2), ("zG>=2", lambda e: e[5] >= 2)]
    def rep(title, evs):
        print("-- %s" % title)
        print("%-16s %5s | %s" % ("bucket", "n", " | ".join("h=%d mean tstat hit" % h for h in HS)))
        for name, f in [("ALL", lambda e: True)] + buckets:
            sel = [e for e in evs if f(e)]; row = []
            for i, h in enumerate(HS):
                n, m, t, hit = stat([e[6][i] for e in sel]); row.append("%6s %5s %4s" % (fm(m), fm(t), fm(hit, "%.2f")))
            print("%-16s %5d | %s" % (name, len(sel), " | ".join(row)))
        base = [[e[7][i] for e in evs] for i in range(len(HS))]
        print("%-16s %5d | %s" % ("BTC itself", len(evs), " | ".join("%6s" % fm(sum(b) / len(b)) if b else "-" for b in base)))
    for nm, sub in (("rho>=0.6", lambda e: e[2] >= 0.6), ("rho<0.6", lambda e: e[2] < 0.6)):
        E = [e for e in allev if sub(e)]
        rep("ALL TIME, %s" % nm, E)
    sig = lambda e: e[2] >= 0.6 and e[5] >= 1.0
    tr = [e for e in allev if e[1] <= tcut]; te = [e for e in allev if e[1] > tcut]
    print("\n== SIGNAL rho>=0.6 & zG>=1.0 (train 60%% / test 40%%) vs same rho without zG filter ==")
    for nm, evs in (("train", tr), ("test", te)):
        for lab, f in (("signal", sig), ("rho>=0.6 any zG", lambda e: e[2] >= 0.6), ("rho>=0.6 & zG<1", lambda e: e[2] >= 0.6 and e[5] < 1.0)):
            sel = [e for e in evs if f(e)]; row = []
            for i, h in enumerate(HS):
                n, m, t, hit = stat([e[6][i] for e in sel]); row.append("%6s t%5s hit%4s" % (fm(m), fm(t), fm(hit, "%.2f")))
            print("%-5s %-17s n=%4d | %s" % (nm, lab, len(sel), " | ".join(row)))
    # по парам: сигнал, h=5
    print("\n== per pair, signal events, mean fwd 5m bps (n>=8) ==")
    per = {}
    for e in allev:
        if sig(e): per.setdefault(e[0], []).append(e[6][1])
    for s, xs in sorted(per.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        if len(xs) >= 8: print("%-6s n=%3d mean=%6.1f hit=%.2f" % (s, len(xs), sum(xs) / len(xs), sum(1 for x in xs if x > 0) / len(xs)))
    json.dump({"p1": res1, "n_events": len(allev), "days": DAYS}, open("/tmp/ll_result.json", "w"))
    print("DONE")


main()
