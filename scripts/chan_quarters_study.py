# -*- coding: utf-8 -*-
"""chan_quarters_study.py [TF] [DAYS] -- бэктест входа лимитом на разной глубине регрессионного канала (ADXAE Regression Channel Auto, 40-350 по |R|, sigma n-2).
Зона задаётся в сигмах от линии регрессии (u = (цена - линия)/sigma): границы канала +-2, внутренние линии +-1, центр 0 (4 части).
Лимит лонга стоит на u = -d, лимит шорта на u = +d, d in {2, 1.5, 1, 0.5}. Режимы: with = только по направлению канала (лонг в растущем, шорт в падающем, как у бота), counter = против (лонг в падающем, шорт в растущем).
Цели: mid = линия регрессии, opp1 = противоположная линия 1 sigma, opp = противоположная граница минус 0.1 ATR. Стоп: bot = max(1.2 ATR, 0.5%), edge = за внешней границей на 0.5 sigma (не меньше 1 ATR и 0.3%).
Канал на свече i строится по свечам <= i-1; лимит живёт одну свечу, цена уровня должна быть в пределах 0..3 ATR от предыдущего закрытия. Комиссии и симулятор как в chan_tv_study.py (импортируется кодом).
Контроль: та же геометрия в ATR в случайных местах (DRAWS раз). Запуск: python chan_quarters_study.py 5m 30  (рядом лежит chan_tv_study.py)."""
import sys, os, time
import numpy as np
TF = sys.argv[1] if len(sys.argv) > 1 else "5m"
DAYS = sys.argv[2] if len(sys.argv) > 2 else "30"
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "chan_tv_study.py"), encoding="utf-8").read().rstrip()
assert src.endswith("main()"); src = src[:-len("main()")]
sys.argv = ["chan_tv_study.py", TF, DAYS]
ns = {"__name__": "chan_tv_study"}; exec(compile(src, "chan_tv_study.py", "exec"), ns)
klines, atr14, ch_regression, real_trades, control_trades, fmt = (ns[k] for k in ("klines", "atr14", "ch_regression", "real_trades", "control_trades", "fmt"))
SYMS, WARM = ns["SYMS"], ns["WARM"]
if os.environ.get("QSYNTH"): SYMS = SYMS[:1]; DRAWS = 3; ns["DRAWS"] = DRAWS
MODES = ("with", "counter"); DS = (2.0, 1.5, 1.0, 0.5); TGTS = ("mid", "opp1", "opp"); STOPS = ("bot", "edge")


def gen_zone(c, atr, up, lw, dr, mode, d, tgt, stopm):
    out = []
    for i in range(WARM, len(c)):
        if np.isnan(up[i]) or np.isnan(lw[i]) or dr[i] == 0:
            continue
        a = atr[i - 1]; U, L = up[i], lw[i]
        if U - L < 1.5 * a:
            continue
        mid = (U + L) / 2; sd = (U - L) / 4
        for side in (1, -1):
            if (mode == "with") != (side == dr[i]):
                continue
            lv = mid - side * d * sd
            dist = (c[i - 1] - lv) * side / a
            if not 0 <= dist <= 3:
                continue
            tg = mid if tgt == "mid" else (mid + side * sd if tgt == "opp1" else (U if side > 0 else L) - side * 0.1 * a)
            if (tg - lv) * side <= 0:
                continue
            if stopm == "bot":
                risk = max(1.2 * a, 0.005 * lv)
            else:
                risk = max(((mid - side * 2.5 * sd) - lv) * -side, a, 0.003 * lv)
            out.append(dict(side=side, i0=i, life=1, level=lv, stop=lv - side * risk, tgt=tg, cancel=None, maxb=48, dist=dist, rk=risk / a, tgd=abs(tg - lv) / a, cd=0.0))
    return out


def main():
    t0 = time.time(); acc = {}; rng = np.random.default_rng(11)
    for si, sym in enumerate(SYMS):
        a = ns["synth"](si) if os.environ.get("QSYNTH") else klines(sym, TF, int(DAYS))
        if len(a) < WARM + 600:
            print(sym, "short data", len(a), flush=True); continue
        o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]; atr = atr14(h, l, c); n = len(c)
        up, lw, dr = ch_regression(h, l, c, atr)
        print("%s bars %d channel-bars %d  %.0fs" % (sym, n, int((dr != 0).sum()), time.time() - t0), flush=True)
        for mode in MODES:
            for d in DS:
                for tgt in TGTS:
                    for stp in STOPS:
                        ords = gen_zone(c, atr, up, lw, dr, mode, d, tgt, stp)
                        A = acc.setdefault((mode, d, tgt, stp), dict(nord=0, att=0, real=[], ctl=[], rA=[], rB=[]))
                        A["nord"] += len(ords); rt, att = real_trades(o, h, l, c, ords); A["att"] += att
                        A["real"] += rt; A["ctl"] += control_trades(o, h, l, c, atr, ords, rng)
                        A["rA"] += [x for x in rt if x["i0"] < n // 2]; A["rB"] += [x for x in rt if x["i0"] >= n // 2]
    print("\n==== regression channel, TF %s, %s days, pairs %d; net after fees; control = same ATR geometry at random bars x%d ====" % (TF, DAYS, len(SYMS), DRAWS))
    rows = []
    for k, A in acc.items():
        if len(A["real"]) < 30:
            continue
        net = np.array([x["gross"] - x["fee"] for x in A["real"]]); cn = np.array([x["gross"] - x["fee"] for x in A["ctl"]]) if A["ctl"] else np.array([0.0])
        se = np.sqrt(net.var() / len(net) + cn.var() / max(len(cn), 1)); hn = lambda r: np.mean([x["gross"] - x["fee"] for x in r]) if r else float("nan")
        rows.append((net.mean() - cn.mean(), k, len(net), 100 * (net > 0).mean(), net.mean(), cn.mean(), se, hn(A["rA"]), hn(A["rB"])))
    rows.sort(key=lambda r: -r[0])
    print("%-8s %4s %-5s %-5s | %5s %5s %8s %8s %7s | %7s %7s" % ("mode", "d", "tgt", "stop", "fills", "win%", "net", "control", "diff/se", "half1", "half2"))
    for r in rows:
        k = r[1]; print("%-8s %4.1f %-5s %-5s | %5d %5.1f %+8.3f %+8.3f %+7.2f | %+7.3f %+7.3f" % (k[0], k[1], k[2], k[3], r[2], r[3], r[4], r[5], r[0] / r[6] if r[6] else 0, r[7], r[8]))
    print("\nDONE %.0fs" % (time.time() - t0), flush=True)


main()
