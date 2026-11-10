# -*- coding: utf-8 -*-
"""edge_control.py -- корректный контроль к edge_study: тот же МОМЕНТ входа.
(а) обратное направление: тот же вход и те же дистанции стопа/цели, но сторона противоположная (отбой или пробой линии выигрывает чаще?);
(б) другие пары в тот же момент: 3 случайные пары из набора, сторона та же, дистанции в ATR те же (рыночный дрейф и кластеры по времени сокращаются в парной разнице).
Меры: dATR (ход в ATR, позиция фиксированная), win%, R. Парная разница реальный минус контроль по сделкам, с ошибкой.
Запуск: cd /opt/tg-notify && python3 edge_control.py"""
import glob, json, math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edge_study import kl, sim, stat, BAR, HOR


def atr14(ks):
    tr = []
    for i in range(1, len(ks)):
        h, l, pc = float(ks[i][2]), float(ks[i][3]), float(ks[i - 1][4]); tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr[-14:]) / max(1, len(tr[-14:]))


def paired(diffs, name):
    n = len(diffs)
    if n < 2: print("   %s: n<2" % name); return
    mu = sum(diffs) / n; sd = math.sqrt(sum((x - mu) ** 2 for x in diffs) / (n - 1)); print("   %s: n=%d, средняя разница dATR %+.2f ± %.2f (%.1f σ)" % (name, n, mu, sd / math.sqrt(n), mu / (sd / math.sqrt(n)) if sd else 0))


def main():
    dirs = sorted(d for d in glob.glob("/opt/trading-bot/positions*") if os.path.exists(os.path.join(d, "positions.json")) and os.path.exists(os.path.join(d, "orders.json")))
    now = int(time.time() * 1000); seen = set(); T = []
    for d in dirs:
        try: pos = json.load(open(os.path.join(d, "positions.json"))); orders = {o["id"]: o for o in json.load(open(os.path.join(d, "orders.json")))}
        except Exception: continue
        for p in pos:
            if p.get("t_out") is None: continue
            o = orders.get(p.get("order_id"))
            if not o or not o.get("chan") or o.get("setup") == "breakout" or o.get("rule") in ("retest_up", "retest_down") or not o.get("atr"): continue
            if now - int(p["t_in"]) < (HOR + 3) * BAR: continue
            k = (p["sym"], int(p["t_in"]), p["side"])
            if k in seen: continue
            seen.add(k); T.append((p, o))
    T.sort(key=lambda x: int(x[0]["t_in"])); syms = sorted({p["sym"] for p, _ in T}); rnd = random.Random(11)
    print("сделок: %d, пар: %d" % (len(T), len(syms)), flush=True)
    real = []; flip = []; cross = []; pd_flip = []; pd_cross = []; by_side = {"long": [], "short": []}; by_side_flip = {"long": [], "short": []}
    for n_, (p, o) in enumerate(T):
        t_in = int(p["t_in"]); ks = kl(p["sym"], t_in - 30 * BAR, 30 + HOR + 6); fw = [k for k in ks if k[0] > t_in]
        if len(fw) < HOR: continue
        s = 1 if p["side"] == "long" else -1; a = float(o["atr"]); entry = float(p["entry"]); stop_d = abs(entry - float(p["stop0"])); tp_d = abs(float(o["tp"]) - entry)
        if stop_d <= 0 or tp_d <= 0.05 * stop_d: continue
        def one(fwx, ent, sd, d_stop, d_tp, atr):
            mv, out = sim(fwx, sd, ent, ent - sd * d_stop, ent + sd * d_tp); return (mv / atr, mv / d_stop, 1 if out == "tp" else 0)
        r0 = one(fw, entry, s, stop_d, tp_d, a); r1 = one(fw, entry, -s, stop_d, tp_d, a)
        real.append(r0); flip.append(r1); pd_flip.append(r0[0] - r1[0]); by_side[p["side"]].append(r0); by_side_flip[p["side"]].append(r1)
        cs = []
        for sy in rnd.sample([x for x in syms if x != p["sym"]], 4):
            kx = kl(sy, t_in - 30 * BAR, 30 + HOR + 6); fx = [k for k in kx if k[0] > t_in]; px = [k for k in kx if k[0] + BAR <= t_in]
            if len(fx) < HOR or len(px) < 20: continue
            ax = atr14(px); ent = float(px[-1][4])
            if ax <= 0: continue
            cs.append(one(fx, ent, s, stop_d / a * ax, tp_d / a * ax, ax))
            if len(cs) == 3: break
        if cs:
            cross += cs; pd_cross.append(r0[0] - sum(c[0] for c in cs) / len(cs))
        if (n_ + 1) % 25 == 0: print("  обработано %d/%d" % (n_ + 1, len(T)), flush=True)
    print("\nРезультаты (стоп и цель = реальные дистанции сделки; без сопровождения; комиссии не учтены):")
    print("   реальный вход у линии:                 %s" % stat(real))
    print("   обратная сторона в тот же момент:      %s" % stat(flip))
    print("   другие пары в тот же момент (3 на сд.): %s" % stat(cross))
    paired(pd_flip, "реальный минус обратная сторона")
    paired(pd_cross, "реальный минус другие пары     ")
    print("\nПо стороне (реальный / обратная сторона):")
    for sd in ("long", "short"): print("   %-5s реальный: %s\n   %-5s обратная: %s" % (sd.upper(), stat(by_side[sd]), "", stat(by_side_flip[sd])))


if __name__ == "__main__": main()
