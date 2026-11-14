# -*- coding: utf-8 -*-
"""Три исследования по кэшу минутных путей (scripts/paths_cache.py), реальный движок pos.step, правила выхода счёта как есть. Те же данные (in-sample) там, где нет честной проверки «вперёд».
A. Динамические уровни: на момент входа находим ближайшие локальные экстремумы 5m за последние 2 часа ПО ХОДУ сделки (для шорта опоры под входом, для лонга сопротивления над входом), берём первый уровень
   на расстоянии 0.3..1.5 R. Варианты: закрыть всё лимитом чуть до уровня, закрыть половину (остаток по правилам счёта), перенести стоп в плюс после касания.
B. Допуск по классам, проверка «вперёд» (walk-forward): класс допускается, пока среднее по последним W закрытым сделкам класса (закрытым ДО входа текущей) не хуже порога; пробный период первые N сделок класса.
C. Закрытие более старой позиции при открытии новой в том же направлении (идея пользователя): если старая в плюсе >= x R, закрыть её по рынку в момент открытия новой; если в минусе, подтянуть ей стоп до -cut R.
Запуск на VPS как entry_study.py."""
import copy, gzip, json, os, sys, urllib.request, statistics as st
os.environ["POS_DIR"] = "/tmp/three_pos"; os.makedirs("/tmp/three_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/three_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(REAL + "/orders.json", encoding="utf-8"))}
T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"]))
    if not c or not c["ks"] or p.get("entry") is None: continue
    last_t = (p["t_in"] // 60000) * 60000
    ks = [k for k in c["ks"] if k[0] > last_t]; pre = [k for k in c["ks"] if k[0] <= last_t]
    if len(ks) >= 5: T.append(dict(p=p, o=orders.get(p.get("order_id")) or {}, ks=ks, pre=pre, sd=1 if p["side"] == "long" else -1, last_t=last_t))
T.sort(key=lambda t: t["p"]["t_in"]); N = len(T); ids = sorted(t["p"]["id"] for t in T); half = ids[N // 2]
print("сделок с путями: %d\n" % N)


def build(t):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; R = p0["R"]
    q = {x: copy.deepcopy(p0[x]) for x in ("id", "sym", "side", "stake", "lev", "atr1h", "max_h", "thesis", "rule", "src", "fee_in", "fee_tp") if x in p0}
    q.update(t_in=p0["t_in"], entry=E, px_signal=E, stop0=p0["stop0"], stop=p0["stop0"], tp=p0["tp"], R=R, R_pct=p0["R_pct"], be_r=1.0, lock_pct=0.2, be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False,
             trail_dist=1.5 * (p0.get("atr1h") or 0), hi=E, lo=E, status="open", last_t=0)
    if p0.get("xr"): q["xr"] = p0["xr"]
    return q


def finish(q, t):
    if q["status"] == "open": pos.close(q, t["ks"][-1][4], t["ks"][-1][0] + 60000, "time", True)
    return q


def play(t):
    q = build(t)
    for k in t["ks"]:
        pos.step(q, k)
        if q["status"] != "open": break
    return finish(q, t)


def rr(q, t): return q["net_pct"] / t["p"]["R_pct"]


BASEQ = [play(t) for t in T]; BASE = [rr(q, t) for q, t in zip(BASEQ, T)]
print("Базовая симуляция (правила счёта): сумма %+.1f R (факт %+.1f R)\n" % (sum(BASE), sum(t["p"]["r_mult"] or 0 for t in T)))


def summ(label, rs, ex=""):
    tot = sum(rs); h1 = sum(r for r, t in zip(rs, T) if t["p"]["id"] < half)
    print("%-58s сумма %+7.1f R (1/2: %+6.1f / %+6.1f) | на сделку %+5.2f %s" % (label, tot, h1, tot - h1, tot / N, ex))


# ---------------- A. динамические уровни ----------------
def bars5(pre):
    g = {}
    for k in pre: g.setdefault(k[0] // 300000, []).append(k)
    out = []
    for b in sorted(g):
        v = g[b]
        if len(v) < 5: continue
        out.append((b * 300000, v[0][1], max(x[2] for x in v), min(x[3] for x in v), v[-1][4]))
    return out[-24:]


def first_level(t):
    sd = t["sd"]; E = t["p"]["entry"]; R = t["p"]["R"]; B = bars5(t["pre"]); lv = []
    for i in range(2, len(B) - 2):
        if sd < 0 and B[i][3] < min(B[i - 2][3], B[i - 1][3]) and B[i][3] <= min(B[i + 1][3], B[i + 2][3]): lv.append(B[i][3])      # шорт: опоры = локальные минимумы под входом
        if sd > 0 and B[i][2] > max(B[i - 2][2], B[i - 1][2]) and B[i][2] >= max(B[i + 1][2], B[i + 2][2]): lv.append(B[i][2])      # лонг: сопротивления = локальные максимумы над входом
    c = [(abs(x - E) / R, x) for x in lv if sd * (x - E) > 0.3 * R * 0 and (x - E) * sd >= 0.3 * R and (x - E) * sd <= 1.5 * R]
    return min(c)[1] if c else None


def play_level(t, mode, lvl, buf=0.1):
    q = build(t); sd = t["sd"]; E = q["entry"]; R = q["R"]; Ls = lvl - sd * buf * R; done = False
    for k in t["ks"]:
        pos.step(q, k)
        if q["status"] != "open": break
        if not done and ((k[2] >= Ls) if sd > 0 else (k[3] <= Ls)):
            done = True
            if mode == "close": pos.close(q, Ls, k[0] + 60000, "target", False); break
            if mode == "half": pos.partial(q, Ls, k[0] + 60000, 0.5, "sr")
            if mode == "be":
                ns = E + sd * 0.15 * R
                if (ns - q["stop"]) * sd > 0: q["stop"] = ns
    return finish(q, t)


print("== A. Динамические уровни (ближайший локальный экстремум по ходу сделки, 0.3..1.5 R от входа)")
LV = [first_level(t) for t in T]; has = [i for i, l in enumerate(LV) if l is not None]
print("   уровень найден у %d из %d сделок; у них базовая сумма %+.1f R (остальные %+.1f R)" % (len(has), N, sum(BASE[i] for i in has), sum(BASE) - sum(BASE[i] for i in has)))
for mode, lab in (("close", "закрыть ВСЁ у уровня"), ("half", "закрыть ПОЛОВИНУ у уровня"), ("be", "стоп в плюс (+0.15 R) после касания уровня")):
    rs = list(BASE)
    for i in has: rs[i] = rr(play_level(T[i], mode, LV[i]), T[i])
    summ("   %s" % lab, rs, "| на сделках с уровнем: %+.1f R (было %+.1f R)" % (sum(rs[i] for i in has), sum(BASE[i] for i in has)))

# ---------------- B. допуск по классам, проверка вперёд ----------------
def klass(t):
    o = t["o"]; c = trade_mgr.classify(o) if o else "other"
    if c == "other" or c.startswith("limit_"):
        rg = (o.get("regime") or {}).get("regime") if o else None
        rel = "flat" if rg in (None, "flat") else ("with" if (rg == "down") == (t["sd"] < 0) else "against")
        return "%s|%s" % (o.get("rule") or c, rel)
    return c


print("\n== B. Допуск по классам, проверка вперёд (история только закрытая ДО входа; фактические итоги, без движка)")
K = [klass(t) for t in T]
print("   классов: %d; сделок в классах: %s" % (len(set(K)), ", ".join("%s %d" % (c, K.count(c)) for c in sorted(set(K), key=lambda c: -K.count(c))[:8])))
act = [t["p"]["r_mult"] or 0 for t in T]
for W, thr, N0 in ((15, -0.15, 8), (20, -0.15, 10), (20, 0.0, 10), (30, -0.1, 10), (15, 0.0, 6)):
    adm = []; half_sz = []
    for i, t in enumerate(T):
        c = K[i]; hist = [(T[j]["p"]["t_out"], act[j]) for j in range(i) if K[j] == c and T[j]["p"]["t_out"] < t["p"]["t_in"]]
        hist.sort(); last = [r for _, r in hist[-W:]]
        ok = len(hist) < N0 or (sum(last) / max(1, len(last)) >= thr)
        adm.append(ok); half_sz.append(1.0 if ok else 0.5)
    tot_skip = sum(a for a, ok in zip(act, adm) if ok); tot_half = sum(a * h for a, h in zip(act, half_sz)); n_ok = sum(adm)
    print("   окно %2d, порог %+.2f R, пробный период %2d: допущено %3d из %d, сумма %+6.1f R (все %+.1f R); вместо отказа половинный размер: %+6.1f R" % (W, thr, N0, n_ok, N, tot_skip, sum(act), tot_half))
fin = {}
for i, t in enumerate(T): fin.setdefault(K[i], []).append(act[i])
print("   итог по классам (все сделки): " + "; ".join("%s n=%d %+.1f R" % (c, len(v), sum(v)) for c, v in sorted(fin.items(), key=lambda x: sum(x[1]))[:10]))

# ---------------- C. закрытие более старой позиции при открытии новой в том же направлении ----------------
print("\n== C. Новая позиция в том же направлении (другая пара) -> старую закрыть по рынку, если в плюсе; убыточной подтянуть стоп")
close_t = [q["t_out"] if q["status"] == "closed" else 10 ** 18 for q in BASEQ]
ev = {}
for i, A in enumerate(T):
    for j, B in enumerate(T):
        if j == i or B["sd"] != A["sd"] or B["p"]["sym"] == A["p"]["sym"]: continue
        tb = B["p"]["t_in"]
        if A["p"]["t_in"] < tb < close_t[i]:
            if i not in ev or tb < ev[i]: ev[i] = tb
print("   позиций, у которых в открытом состоянии появилась новая в ту же сторону: %d из %d" % (len(ev), N))


def play_rot(t, tb, thr, cut):
    q = build(t); sd = t["sd"]; E = q["entry"]; R = q["R"]; acted = False; prev = None
    for k in t["ks"]:
        if not acted and k[0] + 60000 > tb and prev is not None:
            acted = True; ur = sd * (prev[4] / E - 1) * 100 / q["R_pct"]
            if thr is not None and ur >= thr: pos.close(q, prev[4], k[0], "rot", True); break
            if cut is not None and ur < 0:
                ns = E - sd * cut * R
                if (ns - q["stop"]) * sd > 0 and (sd * (prev[4] - ns) > 0): q["stop"] = ns
        pos.step(q, k)
        if q["status"] != "open": break
        prev = k
    return finish(q, t)


for thr, cut in ((0.0, None), (0.2, None), (0.5, None), (0.0, 0.5), (0.2, 0.5), (None, 0.5)):
    rs = list(BASE)
    for i, tb in ev.items(): rs[i] = rr(play_rot(T[i], tb, thr, cut), T[i])
    nrot = sum(1 for i in ev if rs[i] != BASE[i])
    lab = "   закрыть в плюсе >= %s R%s" % ("%.1f" % thr if thr is not None else "-", ", убыточной стоп до -%.1f R" % cut if cut else "")
    summ(lab, rs, "| изменено позиций %d, на них: %+.1f R (было %+.1f R)" % (nrot, sum(rs[i] for i in ev if rs[i] != BASE[i]), sum(BASE[i] for i in ev if rs[i] != BASE[i])))
