# -*- coding: utf-8 -*-
"""exit_lab.py [DAYS] -- этап 1 «лаборатории выходов»: честное сравнение политик выхода на ОДНИХ И ТЕХ ЖЕ входах.

Наборы входов (вход по рынку на открытии свечи, комиссия входа тейкер 0.05%):
  rand - случайные свечи и стороны (покрывают все состояния рынка; ожидание любой политики около минус комиссии).
  chan - вход после касания границы скользящего канала Fixed N=60 по направлению (user: with + flat), закрытие свечи внутри канала.
Риск R = max(1.2 ATR, 0.5%) от входа. Политики:
  T k       - стоп -1R, цель +k R (мейкер 0.02%), максимум 48 свечей;
  TIME t    - стоп -1R, выход по рынку через t свечей;
  TR m      - стоп -1R, после +1R стоп в безубыток (+0.1R) и трейлинг m ATR от экстремума, максимум 96 свечей;
  PART      - половина на +1R (мейкер), остаток: безубыток и трейлинг, максимум 96 свечей;
  ORACLE    - не политика: лучший возможный выход по закрытиям в пределах 48 свечей (потолок, чтобы понимать масштаб).
В пределах свечи стоп проверяется раньше цели (консервативно); трейлинг и безубыток применяются со следующей свечи.
Результат: net% на сделку, netR, доля прибыльных, profit factor, две половины по времени, se. Свечи кэшируются в /tmp/fs/kl_*.npy для следующего этапа.
Запуск: python exit_lab.py 60  (рядом chan_fixed_study.py и chan_tv_study.py)."""
import sys, os, time
import numpy as np
DAYS = sys.argv[1] if len(sys.argv) > 1 else "60"
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "chan_fixed_study.py"), encoding="utf-8").read().rstrip()
assert src.endswith("main()"); src = src[:-len("main()")]
sys.argv = ["chan_fixed_study.py", "5m", DAYS, "60"]
ns = {"__name__": "chan_fixed_study", "__file__": os.path.join(here, "chan_fixed_study.py")}; exec(compile(src, "chan_fixed_study.py", "exec"), ns)
klines, atr14, build_slide, modeok_of = (ns[k] for k in ("klines", "atr14", "build_slide", "modeok_of"))
SYMS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "LINK", "AVAX", "SUI", "LTC", "DOT", "APT", "ATOM", "NEAR", "ZEC", "PHA", "TREE", "ANIME", "IOST", "REZ", "NIL", "HAEDAL", "PEPE", "TRX", "FIL"]
if os.environ.get("ESYNTH"): SYMS = SYMS[:3]
FEE_T, FEE_M = 0.05, 0.02; WARM = 400
POLS = [("T", 1.0), ("T", 1.5), ("T", 2.0), ("T", 3.0), ("TIME", 6), ("TIME", 12), ("TIME", 24), ("TIME", 48), ("TR", 1.0), ("TR", 2.0), ("TR", 3.0), ("PART", 1.5)]


def load(sym):
    p = "/tmp/fs/kl_%s_5m_%s.npy" % (sym, DAYS)
    if os.path.exists(p) and not os.environ.get("ESYNTH"): return np.load(p)
    a = ns["ns"]["synth"](SYMS.index(sym)) if os.environ.get("ESYNTH") else klines(sym + "USDT", "5m", int(DAYS))
    if len(a) and not os.environ.get("ESYNTH"):
        os.makedirs("/tmp/fs", exist_ok=True); np.save(p, a)
    return a


def sim(o, h, l, c, atr, i0, s, pol):
    n = len(c); e = float(o[i0]); a = float(atr[i0 - 1]); risk = max(1.2 * a, 0.005 * e); rpct = risk / e * 100
    stop = e - s * risk; kind = pol[0]
    if kind == "ORACLE":
        end = min(i0 + 48, n - 1); best = max(s * (c[k] - e) / e * 100 for k in range(i0, end + 1)); return best - FEE_T - FEE_T, rpct, 1
    if kind == "T":
        tgt = e + s * pol[1] * risk; L = 48
    elif kind == "TIME": L = pol[1]
    else: L = 96
    peak = e; armed = False; tp1 = False; part = 0.0
    last = min(i0 + L, n - 1)
    for j in range(i0, last + 1):
        if (s > 0 and l[j] <= stop) or (s < 0 and h[j] >= stop):
            ex = (min(stop, o[j]) if s > 0 else max(stop, o[j])) if j > i0 else stop
            g = s * (ex - e) / e * 100
            if kind == "PART" and tp1: return 0.5 * part + 0.5 * g - (FEE_T + 0.5 * FEE_M + 0.5 * FEE_T), rpct, j - i0
            return g - 2 * FEE_T, rpct, j - i0
        if kind == "T" and j > i0 and ((s > 0 and h[j] >= tgt) or (s < 0 and l[j] <= tgt)):
            return s * (tgt - e) / e * 100 - FEE_T - FEE_M, rpct, j - i0
        if kind == "PART" and not tp1 and j > i0 and ((s > 0 and h[j] >= e + s * risk) or (s < 0 and l[j] <= e + s * risk)):
            tp1 = True; part = 100.0 * risk / e; stop = e; armed = True
        ext = h[j] if s > 0 else l[j]
        peak = max(peak, ext) if s > 0 else min(peak, ext)
        if kind in ("TR", "PART"):
            if not armed and s * (peak - e) >= risk: armed = True; stop = e + s * 0.1 * risk if kind == "TR" else e
            if armed:
                m = pol[1] if kind == "TR" else 1.5
                ns_ = peak - s * m * a
                if (ns_ - stop) * s > 0: stop = ns_
    g = s * (c[last] - e) / e * 100
    if kind == "PART" and tp1: return 0.5 * part + 0.5 * g - (FEE_T + 0.5 * FEE_M + 0.5 * FEE_T), rpct, last - i0
    return g - 2 * FEE_T, rpct, last - i0


def main():
    t0 = time.time(); rng = np.random.default_rng(5); E = {"rand": [], "chan": []}; data = {}
    for sym in SYMS:
        a = load(sym)
        if len(a) < WARM + 600: print(sym, "short", len(a), flush=True); continue
        o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]; atr = atr14(h, l, c); n = len(c); data[sym] = (o, h, l, c, atr)
        for i in np.nonzero(rng.random(n) < 0.03)[0]:
            if WARM <= i < n - 110: E["rand"].append((sym, int(i), int(rng.choice([-1, 1])), i / n))
        mid, sd, dr, cid, exits, _ = build_slide(o, h, l, c, atr, 60); U = mid + 2 * sd; Lw = mid - 2 * sd; atrp = np.r_[atr[0], atr[:-1]]; wide = (U - Lw) >= 1.5 * atrp
        last = -99
        for j in range(WARM, n - 110):
            if cid[j] < 0 or not wide[j]: continue
            for s in (1, -1):
                if not (dr[j] == s or dr[j] == 0): continue
                if s > 0 and l[j] <= Lw[j] and c[j] > Lw[j]: ok = True
                elif s < 0 and h[j] >= U[j] and c[j] < U[j]: ok = True
                else: ok = False
                if ok and j - last >= 12: E["chan"].append((sym, j + 1, s, j / n)); last = j
        print("%s bars %d  %.0fs" % (sym, n, time.time() - t0), flush=True)
    print("\nentries: rand %d, chan %d\n" % (len(E["rand"]), len(E["chan"])))
    res = {}
    for name, ents in E.items():
        for pol in POLS + [("ORACLE", 0)]:
            net = []; rr = []; tm = []; late = []
            for (sym, i0, s, pos) in ents:
                o, h, l, c, atr = data[sym]
                g, rp, held = sim(o, h, l, c, atr, i0, s, pol); net.append(g); rr.append(g / rp); late.append(pos)
            res[(name, pol)] = (np.array(net), np.array(rr), np.array(late))
    for name in E:
        print("==== %s entries ====" % name)
        print("%-10s | %6s %5s %8s %7s %6s | %8s %8s | %7s" % ("policy", "n", "win%", "net%", "netR", "PF", "half1", "half2", "se"))
        for pol in POLS + [("ORACLE", 0)]:
            net, rr, pos = res[(name, pol)]; w = net[net > 0].sum(); lo = -net[net < 0].sum()
            print("%-10s | %6d %5.1f %+8.3f %+7.3f %6.2f | %+8.3f %+8.3f | %7.3f" % ("%s %s" % (pol[0], pol[1]), len(net), 100 * (net > 0).mean(), net.mean(), rr.mean(), w / max(lo, 1e-9), net[pos < 0.5].mean(), net[pos >= 0.5].mean(), net.std() / np.sqrt(len(net))))
        print()
    print("==== chan minus rand (does the channel entry carry anything under the same exit?) ====")
    for pol in POLS:
        a1 = res[("chan", pol)][0]; a0 = res[("rand", pol)][0]; se = np.sqrt(a1.var() / len(a1) + a0.var() / len(a0))
        print("%-10s diff %+7.3f  diff/se %+5.2f" % ("%s %s" % (pol[0], pol[1]), a1.mean() - a0.mean(), (a1.mean() - a0.mean()) / se))
    print("\nDONE %.0fs" % (time.time() - t0), flush=True)


main()
