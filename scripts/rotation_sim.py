# -*- coding: utf-8 -*-
"""Анализатор параллельных позиций и стоп по структуре, по кэшу путей (scripts/paths_cache.py), реальный движок pos.step.
A. Все позиции живут ОДНОВРЕМЕННО (по минутам, входы как в истории). На закрытии каждой 5m свечи смотрим группы позиций в одну сторону (>=2 открытых). Кандидат: в плюсе >= min_r (R) и «в своём лучшем положении»
   (откат от собственного максимума хода не больше tol R). Из кандидатов закрываем ОДНУ по рынку: выбор по правилу (sel). Варианты правила: low_ur (меньше всего прибыли), low_mfe (меньше всего ходила), old (самая старая), hi_ur (больше всего прибыли), all (все кандидаты).
B. Стоп по структуре: ближайший противоположный экстремум 5m (за последние 2 часа до входа) на расстоянии lo..hi R от входа, стоп за ним на buf R; иначе стоп как был. Итог в % суммы позиции и в R исходной сделки.
Те же данные (in-sample), обе половины рядом. Запуск на VPS как entry_study.py."""
import copy, gzip, json, os, sys, urllib.request
os.environ["POS_DIR"] = "/tmp/rot_pos"; os.makedirs("/tmp/rot_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/rot_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"]))
    if not c or not c["ks"] or p.get("entry") is None: continue
    last_t = (p["t_in"] // 60000) * 60000
    ks = [k for k in c["ks"] if k[0] > last_t]; pre = [k for k in c["ks"] if k[0] <= last_t]
    if len(ks) >= 5: T.append(dict(p=p, ks=ks, pre=pre, kmap={k[0]: k for k in ks}, sd=1 if p["side"] == "long" else -1, last_t=last_t))
N = len(T); ids = sorted(t["p"]["id"] for t in T); half = ids[N // 2]
print("сделок с путями: %d\n" % N)


def build(t, stop=None):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; S = stop if stop is not None else p0["stop0"]; R = abs(E - S)
    q = {x: copy.deepcopy(p0[x]) for x in ("id", "sym", "side", "stake", "lev", "atr1h", "max_h", "thesis", "rule", "src", "fee_in", "fee_tp") if x in p0}
    q.update(t_in=p0["t_in"], entry=E, px_signal=E, stop0=S, stop=S, tp=p0["tp"], R=R, R_pct=R / E * 100, be_r=1.0, lock_pct=0.2, be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False,
             trail_dist=1.5 * (p0.get("atr1h") or 0), hi=E, lo=E, status="open", last_t=0)
    if p0.get("xr"): q["xr"] = p0["xr"]
    return q


def single(t, stop=None):
    q = build(t, stop)
    for k in t["ks"]:
        pos.step(q, k)
        if q["status"] != "open": break
    if q["status"] == "open": pos.close(q, t["ks"][-1][4], t["ks"][-1][0] + 60000, "time", True)
    return q


BASEQ = [single(t) for t in T]
rn = lambda q, t: q["net_pct"] / t["p"]["R_pct"]
BASE = [rn(q, t) for q, t in zip(BASEQ, T)]
print("База (как в счёте): сумма %+.1f R (1/2: %+.1f / %+.1f); итог в %% суммы позиции %+.1f%%\n" % (sum(BASE), sum(r for r, t in zip(BASE, T) if t["p"]["id"] < half), sum(r for r, t in zip(BASE, T) if t["p"]["id"] >= half), sum(q["net_pct"] for q in BASEQ)))

# ---------- A. анализатор ----------
tmin = min(t["p"]["t_in"] for t in T) // 60000 * 60000; tmax = max(t["ks"][-1][0] for t in T)


def lockstep(min_r, tol, sel, same_dir=True, per_cycle_one=True):
    Q = [build(t) for t in T]; done = [False] * N; res = [None] * N; rot = 0
    order = sorted(range(N), key=lambda i: T[i]["p"]["t_in"]); nxt = 0; active = []
    m = tmin
    while m <= tmax:
        while nxt < N and T[order[nxt]]["last_t"] + 60000 <= m: active.append(order[nxt]); nxt += 1
        px_now = {}
        for i in list(active):
            k = T[i]["kmap"].get(m)
            if k is None: continue
            pos.step(Q[i], k); px_now[i] = k[4]
            if Q[i]["status"] != "open": active.remove(i); res[i] = Q[i]
        if (m // 60000) % 5 == 4 and len(active) >= 2:
            cand = {}
            for i in active:
                if i not in px_now: continue
                q = Q[i]; sd = T[i]["sd"]; E = q["entry"]
                ur = sd * (px_now[i] / E - 1) * 100 / q["R_pct"]; mfe = ((q["hi"] - E) if sd > 0 else (E - q["lo"])) / q["R"]
                if ur >= min_r and mfe - ur <= tol: cand[i] = (ur, mfe)
            groups = {}
            for i in active: groups.setdefault(T[i]["sd"] if same_dir else 0, []).append(i)
            for g, mem in groups.items():
                if len(mem) < 2: continue
                c = [i for i in mem if i in cand]
                if not c: continue
                if sel == "low_ur": pick = [min(c, key=lambda i: cand[i][0])]
                elif sel == "low_mfe": pick = [min(c, key=lambda i: cand[i][1])]
                elif sel == "old": pick = [min(c, key=lambda i: T[i]["p"]["t_in"])]
                elif sel == "hi_ur": pick = [max(c, key=lambda i: cand[i][0])]
                else: pick = c if len(c) < len(mem) else sorted(c, key=lambda i: cand[i][0])[1:]       # all: оставляем хотя бы одну позицию
                for i in pick:
                    pos.close(Q[i], px_now[i], m + 60000, "rot", True); active.remove(i); res[i] = Q[i]; rot += 1
        m += 60000
    for i in range(N):
        if res[i] is None:
            if Q[i]["status"] == "open": pos.close(Q[i], T[i]["ks"][-1][4], T[i]["ks"][-1][0] + 60000, "time", True)
            res[i] = Q[i]
    rs = [rn(res[i], T[i]) for i in range(N)]
    return rs, rot


print("== A. Анализатор параллельных позиций (в одну сторону, закрытие по рынку на закрытии 5m свечи)")
print("   база: %+.1f R" % sum(BASE))
for sel in ("low_ur", "low_mfe", "old", "hi_ur", "all"):
    for min_r, tol in ((0.3, 0.15), (0.5, 0.15), (0.5, 9.0), (0.3, 9.0)):
        rs, rot = lockstep(min_r, tol, sel)
        h1 = sum(r for r, t in zip(rs, T) if t["p"]["id"] < half)
        print("   выбор %-8s | в плюсе >= %.1f R, откат от своего максимума <= %s: закрыто %3d позиций, сумма %+7.1f R (1/2: %+6.1f / %+6.1f), к базе %+6.1f R" % (sel, min_r, "%.2f R" % tol if tol < 9 else "любой", rot, sum(rs), h1, sum(rs) - h1, sum(rs) - sum(BASE)))
rs, rot = lockstep(0.5, 0.15, "low_ur", same_dir=False)
print("   (группа = все позиции независимо от стороны, low_ur, 0.5/0.15): закрыто %d, сумма %+.1f R, к базе %+.1f R" % (rot, sum(rs), sum(rs) - sum(BASE)))


# ---------- B. стоп по структуре ----------
def bars5(pre):
    g = {}
    for k in pre: g.setdefault(k[0] // 300000, []).append(k)
    out = []
    for b in sorted(g):
        v = g[b]
        if len(v) < 5: continue
        out.append((b * 300000, v[0][1], max(x[2] for x in v), min(x[3] for x in v), v[-1][4]))
    return out[-24:]


def struct_stop(t, lo, hi, buf):
    sd = t["sd"]; E = t["p"]["entry"]; R0 = t["p"]["R"]; B = bars5(t["pre"]); lv = []
    for i in range(2, len(B) - 2):
        if sd < 0 and B[i][2] > max(B[i - 2][2], B[i - 1][2]) and B[i][2] >= max(B[i + 1][2], B[i + 2][2]): lv.append(B[i][2])      # шорт: экстремумы над входом
        if sd > 0 and B[i][3] < min(B[i - 2][3], B[i - 1][3]) and B[i][3] <= min(B[i + 1][3], B[i + 2][3]): lv.append(B[i][3])      # лонг: экстремумы под входом
    c = [x for x in lv if (-(x - E) * sd) >= lo * R0 and (-(x - E) * sd) <= hi * R0]
    if not c: return None
    x = min(c, key=lambda v: abs(v - E))
    return x - sd * buf * R0     # шорт: выше уровня, лонг: ниже уровня


print("\n== B. Стоп по структуре (за ближайшим противоположным экстремумом 5m, найденным до входа; иначе стоп как был)")
for lo, hi, buf in ((0.5, 2.0, 0.1), (0.5, 1.5, 0.1), (0.7, 2.5, 0.1), (0.5, 2.0, 0.3)):
    tot = 0.0; totpct = 0.0; used = 0; h1 = 0.0; stops = 0
    for t, bq in zip(T, BASEQ):
        s = struct_stop(t, lo, hi, buf)
        if s is None: q = bq
        else: q = single(t, s); used += 1
        r = q["net_pct"] / t["p"]["R_pct"]; tot += r; totpct += q["net_pct"]; stops += q["reason"] == "stop"
        if t["p"]["id"] < half: h1 += r
    print("   уровень на %.1f..%.1f R, запас %.1f R: структурный стоп у %3d из %d, сумма %+7.1f R (1/2: %+6.1f / %+6.1f), итог в %% суммы позиции %+6.1f%% (база %+.1f%%), стоп %3.0f%%" % (
        lo, hi, buf, used, N, tot, h1, tot - h1, totpct, sum(q["net_pct"] for q in BASEQ), 100 * stops / N))
