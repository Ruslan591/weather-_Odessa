# -*- coding: utf-8 -*-
"""Исследование входа по кэшу минутных путей (scripts/paths_cache.py).
Часть 1: как часто цена сначала уходит ПРОТИВ нас (в долях R: 0.25 / 0.5 / 0.75), возвращается ли потом в нашу сторону (до стопа), что говорит порядок событий.
Часть 2: что было бы при другом входе (реальный движок pos.step, правила выхода счёта как есть): E0 рынок как было; E1 лимит лучше цены сигнала на d*R, ждать W минут;
E2 дождаться отката против нас d*R и входа по рынку на первой свече-подтверждении (закрытие за экстремумом предыдущей минуты); E3 только свеча-подтверждение без отката.
Стоп и цель остаются теми же уровнями цены; итог в R исходной сделки (net_pct / R_pct заявки), нет входа = 0. Данные те же (in-sample), перебор небольшой, смотреть обе половины.
Запуск на VPS (рядом pos.py exit_cfg.py decisions.py trade_mgr.py): cd /tmp/estudy && python3 entry_study.py"""
import copy, gzip, json, os, sys, urllib.request, statistics as st
os.environ["POS_DIR"] = "/tmp/estudy_pos"; os.makedirs("/tmp/estudy_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/estudy_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(REAL + "/orders.json", encoding="utf-8"))}
MAK = 0.02

T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"]))
    if not c or not c["ks"] or p.get("entry") is None: continue
    last_t = (p["t_in"] // 60000) * 60000
    ks = [k for k in c["ks"] if k[0] > last_t]
    if len(ks) < 5: continue
    o = orders.get(p.get("order_id")) or {}
    T.append(dict(p=p, ks=ks, last_t=last_t, cls=trade_mgr.classify(o) if o else "other", sd=1 if p["side"] == "long" else -1))
print("сделок с путями: %d из %d\n" % (len(T), len(snap["closed"])))

# ---------- часть 1 ----------
def excursions(t):
    p = t["p"]; E = p["entry"]; R = p["R"]; sd = t["sd"]; S = p["stop0"]; tp = p["tp"]
    adv = [0.0]; fav = [0.0]; ia = {}; iy = {}; stop_i = None; tp_i = None
    a = 0.0; f = 0.0
    for i, k in enumerate(t["ks"]):
        o, h, l, cl = k[1], k[2], k[3], k[4]
        ea = ((E - l) if sd > 0 else (h - E)) / R; ef = ((h - E) if sd > 0 else (E - l)) / R
        ea = max(0.0, ea); ef = max(0.0, ef)
        order_adv_first = (cl >= o) if sd > 0 else (cl <= o)     # свеча в нашу сторону: сначала ход против, затем в нашу
        for x in (0.25, 0.5, 0.75, 1.0):
            if x not in ia and ea >= x: ia[x] = (i, 0 if order_adv_first else 1)
        for y in (0.5, 1.0):
            if y not in iy and ef >= y: iy[y] = (i, 1 if order_adv_first else 0)
        if stop_i is None and ((l <= S) if sd > 0 else (h >= S)): stop_i = i
        if tp_i is None and ((h >= tp) if sd > 0 else (l <= tp)): tp_i = i
        if stop_i is not None or tp_i is not None or k[0] >= p["t_out"]: break
    return ia, iy, stop_i, tp_i


N = len(T); ex = [excursions(t) for t in T]
print("== Часть 1. Куда идёт цена сразу после входа (все %d сделок)" % N)
for x in (0.25, 0.5, 0.75):
    n = sum(1 for ia, _, _, _ in ex if x in ia)
    ret5 = ret10 = stp = 0
    for ia, iy, s_i, tp_i in ex:
        if x not in ia: continue
        a_pos = ia[x]
        for y, name in ((0.5, "r5"), (1.0, "r10")):
            if y in iy and (iy[y][0], iy[y][1]) > (a_pos[0], a_pos[1]) and (s_i is None or iy[y][0] <= s_i):
                if name == "r5": ret5 += 1
                else: ret10 += 1
        if s_i is not None: stp += 1
    print("  уходила против на >=%.2f R: %3d сделок (%2.0f%%); из них потом дошла до +0.5R до стопа: %3.0f%%, до +1R: %3.0f%%, закончилось стопом: %3.0f%%" % (x, n, 100 * n / N, 100 * ret5 / max(1, n), 100 * ret10 / max(1, n), 100 * stp / max(1, n)))
base5 = sum(1 for _, iy, _, _ in ex if 0.5 in iy); base10 = sum(1 for _, iy, _, _ in ex if 1.0 in iy)
print("  без условия: до +0.5R доходит %.0f%%, до +1R %.0f%% (всех сделок)" % (100 * base5 / N, 100 * base10 / N))
first_adv = sum(1 for ia, iy, _, _ in ex if 0.5 in ia and (0.5 not in iy or ia[0.5] < iy[0.5]))
first_fav = sum(1 for ia, iy, _, _ in ex if 0.5 in iy and (0.5 not in ia or iy[0.5] < ia[0.5]))
print("  первым достигается: -0.5R раньше +0.5R у %d сделок (%.0f%%), +0.5R раньше -0.5R у %d (%.0f%%), ни то ни другое у %d" % (first_adv, 100 * first_adv / N, first_fav, 100 * first_fav / N, N - first_adv - first_fav))
print("  по классам: доля сделок с уходом против >=0.5R / дошли до +1R:")
for cl in sorted({t["cls"] for t in T}):
    ids = [i for i, t in enumerate(T) if t["cls"] == cl]
    print("    %-18s n=%3d  против>=0.5R %3.0f%%  до +1R %3.0f%%" % (cl, len(ids), 100 * sum(0.5 in ex[i][0] for i in ids) / len(ids), 100 * sum(1.0 in ex[i][1] for i in ids) / len(ids)))

# ---------- часть 2 ----------
def newpos(t, E, fee_in, t_start):
    p0 = t["p"]; sd = t["sd"]; S = p0["stop0"]; R = abs(E - S)
    q = {k: copy.deepcopy(p0[k]) for k in ("id", "sym", "side", "stake", "lev", "atr1h", "max_h", "thesis", "rule", "src") if k in p0}
    q.update(t_in=t_start, entry=E, px_signal=E, stop0=S, stop=S, tp=p0["tp"], R=R, R_pct=R / E * 100, be_r=1.0, lock_pct=0.2, be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False,
             trail_dist=1.5 * (p0.get("atr1h") or 0), hi=E, lo=E, status="open", fee_in=fee_in, fee_tp=MAK if fee_in == MAK else MAK, last_t=0)
    if p0.get("xr"): q["xr"] = p0["xr"]
    return q


def run_from(q, ks):
    for k in ks:
        pos.step(q, k)
        if q["status"] != "open": break
    if q["status"] == "open":
        pos.close(q, ks[-1][4], ks[-1][0] + 60000, "time", True)
    return q


def e0(t):
    p0 = t["p"]; q = newpos(t, p0["entry"], p0.get("fee_in", pos.FEE), p0["t_in"]); q["R_pct"] = p0["R_pct"]; q["R"] = p0["R"]
    return run_from(q, t["ks"])


def e1(t, d, W):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; R = p0["R"]; L = E - sd * d * R; tp = p0["tp"]
    for i, k in enumerate(t["ks"][:W]):
        if (k[2] >= tp) if sd > 0 else (k[3] <= tp): return None
        if (k[3] <= L) if sd > 0 else (k[2] >= L):
            q = newpos(t, L, MAK, k[0]); return run_from(q, t["ks"][i:])
    return None


def e2(t, d, W):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; R = p0["R"]; S = p0["stop0"]; tp = p0["tp"]; reached = d <= 0
    ks = t["ks"]
    for i, k in enumerate(ks[:W]):
        if (k[2] >= tp) if sd > 0 else (k[3] <= tp): return None
        if (k[3] <= S) if sd > 0 else (k[2] >= S): return None
        if not reached and (((E - k[3]) if sd > 0 else (k[2] - E)) >= d * R): reached = True
        if reached and i > 0:
            pv = ks[i - 1]; ok = (k[4] > pv[2] and k[4] > k[1]) if sd > 0 else (k[4] < pv[3] and k[4] < k[1])
            if ok and ((k[4] > S) if sd > 0 else (k[4] < S)):
                q = newpos(t, k[4] * (1 + sd * pos.SLIP / 100), pos.FEE, k[0] + 60000)
                if abs(q["entry"] - S) <= 0: return None
                return run_from(q, ks[i + 1:]) if i + 1 < len(ks) else None
    return None


def score(fn, label):
    rs = {}; filled = 0
    for i, t in enumerate(T):
        q = fn(t)
        if q is None or q["status"] != "closed": continue
        filled += 1; rs[i] = (q["net_pct"] / t["p"]["R_pct"], q["reason"])
    tot = sum(r for r, _ in rs.values()); ids = sorted(t["p"]["id"] for t in T); half = ids[len(ids) // 2]
    h1 = sum(rs[i][0] for i in rs if T[i]["p"]["id"] < half); h2 = tot - h1
    sub = sum(base_r[i] for i in rs)
    stopp = 100 * sum(1 for r in rs.values() if r[1] == "stop") / max(1, filled)
    avg = tot / max(1, filled)
    print("%-44s вход %3d из %d | сумма %+7.1f R (1/2 пол: %+6.1f / %+6.1f) | на сделку %+5.2f | стоп %3.0f%% | эти же сделки как было: %+6.1f R" % (label, filled, N, tot, h1, h2, avg, stopp, sub))
    return rs


print("\n== Часть 2. Что было бы при другом входе (стоп и цель те же уровни, выходы как у счёта)")
base_q = [e0(t) for t in T]; base_r = {i: q["net_pct"] / T[i]["p"]["R_pct"] for i, q in enumerate(base_q) if q["status"] == "closed"}
print("E0 рынок как было (в движке): сумма %+.1f R, фактически %+.1f R\n" % (sum(base_r.values()), sum(t["p"]["r_mult"] or 0 for t in T)))
for W in (15, 45, 120):
    for d in (0.25, 0.5, 0.75): score(lambda t: e1(t, d, W), "E1 лимит лучше на %.2fR, ждать %d мин" % (d, W))
print()
for W in (15, 45, 120):
    for d in (0.25, 0.5, 0.75): score(lambda t: e2(t, d, W), "E2 откат %.2fR + свеча-подтверждение, %d мин" % (d, W))
print()
for W in (5, 15, 45): score(lambda t: e2(t, 0, W), "E3 только свеча-подтверждение, %d мин" % W)
