# -*- coding: utf-8 -*-
"""reach_1m_check.py -- замер: сколько спорных свечей (цель и стоп в одной 5m-свече) и как меняется статистика цели, если спорную свечу разобрать на 1m.
Берёт закрытые позиции (отбой от линии, ордер с chan) из всех POS_DIR вида /opt/trading-bot/positions*, считает исход по целям GRID двумя способами:
 A (как сейчас, tg_target.simulate): в спорной свече засчитывается стоп; B: спорная 5m-свеча разбирается по 1m, если и в 1m обе сразу, остаётся стоп.
Ничего не меняет в боте, только печатает сравнение. Запуск: cd /opt/tg-notify && python3 reach_1m_check.py [dir ...]"""
import glob, json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_target as TG
GRID = TG.GRID; HOR = TG.HORIZON; BAR = TG.BAR_MS; BASE = TG.BASE
_c1 = {}


def k1(sym, t0):
    """1m свечи окна [t0, t0+5m) (5 штук)."""
    key = (sym, t0)
    if key in _c1: return _c1[key]
    sy = sym if sym.endswith("USDT") else sym + "USDT"; out = []
    for _ in range(3):
        try:
            out = json.load(urllib.request.urlopen("%s?symbol=%s&interval=1m&limit=5&startTime=%d" % (BASE, sy, t0), timeout=20)); break
        except Exception: time.sleep(1)
    _c1[key] = [k for k in out if t0 <= k[0] < t0 + BAR]; time.sleep(0.05); return _c1[key]


def sim_b(ks, sym, side, line, H, entry, stop):
    """Как TG.simulate, но спорную 5m-свечу разбирает по 1m. Возвращает (res, amb) где amb[f] in {None, 'tp', 'stop', 'both'} - что показал разбор спорной свечи (если она была решающей)."""
    s = 1 if side == "long" else -1; risk = abs(entry - stop)
    if risk <= 0 or len(ks) < HOR: return None, None
    ks = ks[:HOR]; res = {}; amb = {}
    for f in GRID:
        tp = line + s * f * H; gain = (tp - entry) * s; key = "%.2f" % f; amb[key] = None
        if gain <= 0.05 * risk: res[key] = None; continue
        out = None
        for k in ks:
            hi, lo = float(k[2]), float(k[3]); hs = (lo <= stop) if s > 0 else (hi >= stop); ht = (hi >= tp) if s > 0 else (lo <= tp)
            if hs and ht:                                   # спорная свеча: разбор по 1m
                first = "both"
                for m in k1(sym, int(k[0])):
                    mh, ml = float(m[2]), float(m[3]); ms = (ml <= stop) if s > 0 else (mh >= stop); mt = (mh >= tp) if s > 0 else (ml <= tp)
                    if ms and mt: first = "both"; break
                    if ms: first = "stop"; break
                    if mt: first = "tp"; break
                amb[key] = first; out = round(gain / risk, 3) if first == "tp" else -1.0; break
            if hs: out = -1.0; break
            if ht: out = round(gain / risk, 3); break
        if out is None: out = round((float(ks[-1][4]) - entry) * s / risk, 3)
        res[key] = out
    return res, amb


def pick(rows, key):
    """Выбор цели как TG.choose: по сегментам (counter x узкий/широкий), лучшая доля по среднему R, из близких (TOL) ближняя."""
    hs = sorted(r["hatr"] for r in rows); thr = hs[len(hs) // 2]; out = {}
    for c in (0, 1):
        for wide in (False, True):
            seg = [r for r in rows if r["counter"] == c and ((r["hatr"] >= thr) == wide)]; st = {}
            for f in GRID:
                xs = [r[key]["%.2f" % f] for r in seg if r[key].get("%.2f" % f) is not None]
                if len(xs) >= TG.MIN_N: st[f] = (sum(xs) / len(xs), sum(x > 0 for x in xs) / len(xs), len(xs))
            nm = ("против" if c else "по тренду") + (", широкий" if wide else ", узкий")
            if not st: out[nm] = (len(seg), None); continue
            best = max(v[0] for v in st.values()); f = min(k for k, v in st.items() if v[0] >= best - TG.TOL); out[nm] = (len(seg), (f, st[f][1], st[f][0], st[f][2]))
    return out


def main():
    dirs = sys.argv[1:] or sorted(d for d in glob.glob("/opt/trading-bot/positions*") if os.path.exists(os.path.join(d, "positions.json")) and os.path.exists(os.path.join(d, "orders.json")))
    now = int(time.time() * 1000); seen = set(); todo = []
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
            seen.add(k); todo.append((d, p, o))
    print("счетов: %d, позиций для замера: %d" % (len(dirs), len(todo)), flush=True)
    rows = []; amb_n = {"%.2f" % f: {"tp": 0, "stop": 0, "both": 0, "valid": 0} for f in GRID}
    for i, (d, p, o) in enumerate(todo):
        ks = TG._fetch(p["sym"], p["t_in"])
        if len(ks) < HOR: continue
        ch = o["chan"]; t = int(p["t_in"])
        try:
            R = ch["upper"]["p1"] + ch["upper"]["s"] * (t - ch["upper"]["t1"]); S = ch["lower"]["p1"] + ch["lower"]["s"] * (t - ch["lower"]["t1"]); H = R - S; long = p["side"] == "long"; line = S if long else R
            if H <= 0: continue
            a = TG.simulate(ks, p["side"], line, H, float(p["entry"]), float(p["stop0"])); b, amb = sim_b(ks, p["sym"], p["side"], line, H, float(p["entry"]), float(p["stop0"]))
        except Exception: continue
        if a is None or b is None: continue
        ct = str(o.get("ctype") or ""); counter = int((long and "down" in ct) or ((not long) and "up" in ct))
        rows.append({"hatr": H / float(o["atr"]), "counter": counter, "A": a, "B": b})
        for key, v in amb.items():
            if a.get(key) is not None:
                amb_n[key]["valid"] += 1
                if v: amb_n[key][v] += 1
        if (i + 1) % 25 == 0: print("  обработано %d/%d" % (i + 1, len(todo)), flush=True)
    print("\nпозиций в замере: %d\n" % len(rows))
    print("Спорные свечи (цель и стоп в одной 5m-свече) по целям:")
    for f in GRID:
        key = "%.2f" % f; x = amb_n[key]; v = x["valid"]; sp = x["tp"] + x["stop"] + x["both"]
        print("  цель %-5s: сделок %3d, спорных %3d (%4.1f%%); по 1m: цель первой %3d, стоп первым %3d, всё ещё вместе %3d" % (TG.FR_RU[f][:5], v, sp, 100.0 * sp / v if v else 0, x["tp"], x["stop"], x["both"]))
    print("\nСтатистика по целям (все сделки): доля цели / средний R, A = как сейчас, B = со спуском на 1m")
    for f in GRID:
        key = "%.2f" % f; xa = [r["A"][key] for r in rows if r["A"].get(key) is not None]; xb = [r["B"][key] for r in rows if r["B"].get(key) is not None]
        if xa: print("  цель %-5s: n=%3d  A: %2d%% / %+.2f R   B: %2d%% / %+.2f R" % (TG.FR_RU[f][:5], len(xa), 100 * sum(x > 0 for x in xa) / len(xa), sum(xa) / len(xa), 100 * sum(x > 0 for x in xb) / len(xb), sum(xb) / len(xb)))
    print("\nВыбор цели по сегментам (как в боте):")
    pa = pick([dict(r, A=r["A"]) for r in rows], "A"); pb = pick(rows, "B")
    for nm in pa:
        def fmt(v): return "n/a (мало данных, n=%d)" % v[0] if v[1] is None else "%s, доходит %d%%, %+.2f R (n=%d)" % (TG.FR_RU[v[1][0]], round(v[1][1] * 100), v[1][2], v[1][3])
        print("  %-22s A: %s\n  %-22s B: %s" % (nm, fmt(pa[nm]), "", fmt(pb[nm])))


if __name__ == "__main__": main()
