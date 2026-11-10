# -*- coding: utf-8 -*-
"""edge_study.py -- где теряется результат отбоев от линии канала: стоп/цель, объём реакции, контекст BTC, контроль «случайный момент».
Берёт закрытые позиции (отбой, ордер с chan) со всех POS_DIR /opt/trading-bot/positions*, свечи 5m Binance. Ничего не меняет в боте, печатает сводку.
Результат сделки: симуляция входа по реальной цене entry, 48 свечей 5m, без сопровождения, комиссии не учтены, цель и стоп в одной свече = стоп.
Меры: win% (цель достигнута), dATR = средний ход цены в сторону сделки в ATR (при фиксированной позиции 6 $ прибыль пропорциональна ему и не зависит от дистанции стопа), R = средний результат в единицах риска.
Запуск: cd /opt/tg-notify && python3 edge_study.py"""
import glob, json, math, os, random, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = "https://data-api.binance.vision/api/v3/klines"; BAR = 300000; HOR = 48; PRE = 150


def kl(sym, t0, n):
    sy = sym if sym.endswith("USDT") else sym + "USDT"
    for _ in range(3):
        try: return json.load(urllib.request.urlopen("%s?symbol=%s&interval=5m&limit=%d&startTime=%d" % (BASE, sy, n, int(t0)), timeout=25))
        except Exception: time.sleep(1)
    return []


def sim(fw, s, entry, stop, tp):
    """fw - свечи после входа. Возвращает (move, outcome): move - ход в сторону сделки (цена), outcome tp|stop|end."""
    for k in fw[:HOR]:
        hi, lo = float(k[2]), float(k[3]); hs = (lo <= stop) if s > 0 else (hi >= stop); ht = (hi >= tp) if s > 0 else (lo <= tp)
        if hs: return (stop - entry) * s, "stop"
        if ht: return (tp - entry) * s, "tp"
    return (float(fw[min(len(fw), HOR) - 1][4]) - entry) * s, "end"


def stat(rows):
    """rows: [(move_atr, R, win)] -> строка n, win%, dATR ± se, R."""
    n = len(rows)
    if n == 0: return "n=0"
    m = [r[0] for r in rows]; mu = sum(m) / n; sd = math.sqrt(sum((x - mu) ** 2 for x in m) / (n - 1)) if n > 1 else 0
    return "n=%3d win %2d%% dATR %+.2f ±%.2f  R %+.2f" % (n, round(100 * sum(r[2] for r in rows) / n), mu, sd / math.sqrt(n) if n > 1 else 0, sum(r[1] for r in rows) / n)


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
    T.sort(key=lambda x: int(x[0]["t_in"]))
    print("сделок для проверки: %d (счетов %d)" % (len(T), len(dirs)), flush=True)
    # BTC 5m на весь период
    t_lo = int(T[0][0]["t_in"]) - 60 * BAR; t_hi = int(T[-1][0]["t_in"]) + BAR; btc = []; t = t_lo
    while t < t_hi:
        ch = kl("BTCUSDT", t, 1000)
        if not ch: break
        btc += [k for k in ch if not btc or k[0] > btc[-1][0]]; t = ch[-1][0] + BAR
        if len(ch) < 1000: break
    bi = {k[0]: i for i, k in enumerate(btc)}
    def btc_at(ts):
        j = (ts // BAR) * BAR - BAR      # последняя закрытая 5m свеча до входа
        i = bi.get(j)
        if i is None or i < 49: return None
        c = float(btc[i][4]); return {"r1": c / float(btc[i - 12][4]) - 1, "r4": c / float(btc[i - 48][4]) - 1, "rng": (max(float(k[2]) for k in btc[i - 11:i + 1]) - min(float(k[3]) for k in btc[i - 11:i + 1])) / c}
    rows = []; rnd = random.Random(7)
    for n_, (p, o) in enumerate(T):
        t_in = int(p["t_in"]); ks = kl(p["sym"], t_in - PRE * BAR, PRE + HOR + 6)
        fw = [k for k in ks if k[0] > t_in]; pre = [k for k in ks if k[0] + BAR <= t_in]
        if len(fw) < HOR or len(pre) < 40: continue
        s = 1 if p["side"] == "long" else -1; a = float(o["atr"]); entry = float(p["entry"]); ch = o["chan"]
        try:
            R_ = ch["upper"]["p1"] + ch["upper"]["s"] * (t_in - ch["upper"]["t1"]); S_ = ch["lower"]["p1"] + ch["lower"]["s"] * (t_in - ch["lower"]["t1"]); H = R_ - S_; line = S_ if s > 0 else R_
        except Exception: continue
        if H <= 0: continue
        sig = pre[-1]; so, sh, sl, sc, sv = (float(sig[i]) for i in (1, 2, 3, 4, 5)); vols = sorted(float(k[5]) for k in pre[-21:-1]); vmed = vols[len(vols) // 2] or 1e-12
        rows.append({"p": p, "o": o, "s": s, "a": a, "entry": entry, "line": line, "H": H, "fw": fw, "pre": pre, "t": t_in, "vr": sv / vmed,
                     "wick": (((min(so, sc) - sl) if s > 0 else (sh - max(so, sc))) / max(sh - sl, 1e-12)), "sig_ext": sl if s > 0 else sh, "btc": btc_at(t_in), "sym": p["sym"]})
        if (n_ + 1) % 40 == 0: print("  загружено %d/%d" % (n_ + 1, len(T)), flush=True)
    print("\nв анализе: %d сделок\n" % len(rows))
    def run(r, stop, tp):
        mv, out = sim(r["fw"], r["s"], r["entry"], stop, tp); risk = abs(r["entry"] - stop) or 1e-12
        return (mv / r["a"], mv / risk, 1 if out == "tp" else 0)
    def base(r): return run(r, float(r["p"]["stop0"]), float(r["o"]["tp"]))
    # 0. факт и база
    act = [(float(r["p"].get("r_mult") or 0), float(r["p"].get("r_mult") or 0), 1 if (r["p"].get("r_mult") or 0) > 0.15 else 0) for r in rows]
    print("0. Факт (реальные закрытия, r_mult):          ", "n=%d win %d%% R %+.2f" % (len(rows), round(100 * sum(x[2] for x in act) / len(act)), sum(x[1] for x in act) / len(act)))
    B = [base(r) for r in rows]; print("   База (реальные стоп и цель, без сопровождения):", stat(B))
    # 1. стоп / цель
    print("\n1. Стоп и цель (ATR от входа; R = результат / риск при данном стопе). Строки: стоп; столбцы: цель")
    def cands(r):
        out = {}
        sig_stop = (r["sig_ext"] - r["s"] * 0.1 * r["a"])
        for nm, st in (("0.5", r["entry"] - r["s"] * 0.5 * r["a"]), ("0.8", r["entry"] - r["s"] * 0.8 * r["a"]), ("1.0", r["entry"] - r["s"] * 1.0 * r["a"]), ("1.2", r["entry"] - r["s"] * 1.2 * r["a"]), ("1.5", r["entry"] - r["s"] * 1.5 * r["a"]),
                       ("за свечой", r["entry"] - r["s"] * min(1.5, max(0.4, (r["entry"] - sig_stop) * r["s"] / r["a"])) * r["a"])):
            for tn, tp in (("0.5", r["entry"] + r["s"] * 0.5 * r["a"]), ("0.8", r["entry"] + r["s"] * 0.8 * r["a"]), ("1.0", r["entry"] + r["s"] * 1.0 * r["a"]), ("1.5", r["entry"] + r["s"] * 1.5 * r["a"]),
                           ("1/4H", r["line"] + r["s"] * 0.25 * r["H"]), ("1/3H", r["line"] + r["s"] * 0.33 * r["H"]), ("1/2H", r["line"] + r["s"] * 0.5 * r["H"])):
                if (tp - r["entry"]) * r["s"] > 0.05 * abs(r["entry"] - st): out[(nm, tn)] = run(r, st, tp)
        return out
    C = [cands(r) for r in rows]; keys = sorted({k for c in C for k in c}, key=lambda k: (k[0], k[1]))
    def agg(idx, k): xs = [C[i][k] for i in idx if k in C[i]]; return xs
    allidx = list(range(len(rows))); tn = ["0.5", "0.8", "1.0", "1.5", "1/4H", "1/3H", "1/2H"]
    print("   средний dATR на сделку (чем больше, тем лучше; ориентир шума ±0.1):")
    print("   стоп \\ цель  " + "  ".join("%6s" % t for t in tn))
    for sn in ("0.5", "0.8", "1.0", "1.2", "1.5", "за свечой"):
        cells = []
        for t_ in tn:
            xs = agg(allidx, (sn, t_)); cells.append("%+6.2f" % (sum(x[0] for x in xs) / len(xs)) if len(xs) >= 20 else "     -")
        print("   %-11s  %s" % (sn, "  ".join(cells)))
    print("   доля целей, %:")
    for sn in ("0.5", "0.8", "1.0", "1.2", "1.5", "за свечой"):
        print("   %-11s  %s" % (sn, "  ".join(("%5d%%" % round(100 * sum(x[2] for x in agg(allidx, (sn, t_))) / len(agg(allidx, (sn, t_))))) if len(agg(allidx, (sn, t_))) >= 20 else "     -" for t_ in tn)))
    cut = int(len(rows) * 0.6); tr = list(range(cut)); te = list(range(cut, len(rows)))
    best = sorted(((sum(x[0] for x in agg(tr, k)) / len(agg(tr, k)), k) for k in keys if len(agg(tr, k)) >= 20), reverse=True)[:5]
    print("\n   Проверка на отложенной части (подбор на первых 60%% сделок по времени, оценка на последних 40%%; n обучения %d, теста %d):" % (len(tr), len(te)))
    for sc_, k in best: print("   лучший на обучении: стоп %-9s цель %-5s обучение dATR %+.2f -> тест %s" % (k[0], k[1], sc_, stat(agg(te, k))))
    print("   база на тесте: %s" % stat([B[i] for i in te]))
    # 2. объём
    print("\n2. Объём на свече реакции (последняя закрытая свеча до входа / медиана 20 предыдущих). База: реальные стоп и цель")
    for nm, f in (("<0.8", lambda r: r["vr"] < 0.8), ("0.8-1.5", lambda r: 0.8 <= r["vr"] < 1.5), (">=1.5", lambda r: r["vr"] >= 1.5), (">=2.5", lambda r: r["vr"] >= 2.5)):
        print("   объём %-8s %s" % (nm, stat([B[i] for i in allidx if f(rows[i])])))
    print("   хвост реакции (доля размаха свечи, сторона линии):")
    for nm, f in (("<0.2", lambda r: r["wick"] < 0.2), ("0.2-0.4", lambda r: 0.2 <= r["wick"] < 0.4), (">=0.4", lambda r: r["wick"] >= 0.4)):
        print("   хвост %-8s %s" % (nm, stat([B[i] for i in allidx if f(rows[i])])))
    # 3. BTC
    print("\n3. Контекст BTC: ход BTC за 1 ч / 4 ч в сторону сделки (+ = BTC идёт за сделкой). База: реальные стоп и цель; без пар BTC")
    ok = [i for i in allidx if rows[i]["btc"] and rows[i]["sym"] != "BTC"]
    for hz, key in (("1ч", "r1"), ("4ч", "r4")):
        al = [i for i in ok if rows[i]["btc"][key] * rows[i]["s"] > 0]; ag = [i for i in ok if rows[i]["btc"][key] * rows[i]["s"] <= 0]
        print("   BTC %s за сделкой: %s" % (hz, stat([B[i] for i in al]))); print("   BTC %s против:    %s" % (hz, stat([B[i] for i in ag])))
    vr = sorted(rows[i]["btc"]["rng"] for i in ok); thr = vr[len(vr) // 2] if vr else 0
    print("   волатильность BTC за 1 ч (размах, медиана %.2f%%): выше медианы: %s" % (thr * 100, stat([B[i] for i in ok if rows[i]["btc"]["rng"] >= thr]))); print("   ниже медианы: %s" % stat([B[i] for i in ok if rows[i]["btc"]["rng"] < thr]))
    # 4. контроль
    print("\n4. Контроль: те же пара, сторона, ATR, дистанции стопа и цели, но вход в СЛУЧАЙНЫЙ момент (5 на сделку из предыдущих часов)")
    real = []; plc = []
    for r in rows:
        stop_d = abs(r["entry"] - float(r["p"]["stop0"])); tp_d = abs(float(r["o"]["tp"]) - r["entry"])
        if tp_d <= 0.05 * stop_d: continue
        real.append(base(r)); pre = r["pre"]; allk = pre + r["fw"]; idxs = list(range(20, len(pre) - HOR - 1))
        if len(idxs) < 5: continue
        for j in rnd.sample(idxs, 5):
            ent = float(allk[j][4]); fwj = allk[j + 1:j + 1 + HOR]
            mv, out = sim(fwj, r["s"], ent, ent - r["s"] * stop_d, ent + r["s"] * tp_d); plc.append((mv / r["a"], mv / stop_d, 1 if out == "tp" else 0))
    print("   реальные входы у линии:  %s" % stat(real)); print("   случайные моменты:       %s" % stat(plc))
    print("   (если у линии не лучше случайного момента, канал сам по себе ничего не добавляет)")
    # 5. по парам и сторонам
    print("\n5. Разрез: по стороне, по типу (тренд/контртренд). База")
    for nm, f in (("LONG", lambda r: r["s"] > 0), ("SHORT", lambda r: r["s"] < 0)): print("   %-14s %s" % (nm, stat([B[i] for i in allidx if f(rows[i])])))
    ctr = lambda r: int((r["s"] > 0 and "down" in str(r["o"].get("ctype"))) or (r["s"] < 0 and "up" in str(r["o"].get("ctype"))))
    for nm, v in (("по тренду", 0), ("контртренд", 1)): print("   %-14s %s" % (nm, stat([B[i] for i in allidx if ctr(rows[i]) == v])))


if __name__ == "__main__": main()
