# -*- coding: utf-8 -*-
"""Подбор уровней правила «флэт + пробой» задним числом (счёт regr). Гонит pos.step по 1m свечам закрытых пробоев ордеров chan (setup=breakout).
Запуск на VPS (фоном): cd /opt/trading-bot/positions && POS_DIR=/opt/trading-bot/positions_regr PYTHONPATH=. /opt/trading-bot/venv/bin/python flat_brk_tune.py > /tmp/fbt_out.txt
Журнал решений НЕ пишется (decisions._write заглушен). Перенос стопа на S/R (pos._update) не воспроизводится. Выборка мала: результат - ориентир, не доказательство."""
import sys, json, copy, itertools, os, time
import pos, exit_cfg, decisions
decisions._write = lambda rec: None
BASE = exit_cfg.load()
EFIX = os.environ.get("EFIX") == "1"   # вход в момент снятия цены (placed_t-30с), а не approved_t (начало цикла)
CACHE = "/tmp/fbt_cache_fix.json" if EFIX else "/tmp/fbt_cache.json"
ps = json.load(open(pos.F)); om = {o["id"]: o for o in json.load(open(pos.F.replace("positions.json", "orders.json")))}
S = []
for p0 in ps:
    o = om.get(p0.get("order_id")) or {}
    if p0["status"] == "closed" and p0.get("src") == "chan" and o.get("setup") == "breakout" and p0["id"] >= int(os.environ.get("MINID", 200)):
        if EFIX and o.get("placed_t"): p0 = dict(p0, t_in=max(int(p0["t_in"]), int(o["placed_t"]) - 30000))
        S.append((p0, (o.get("regime") or {}).get("regime")))
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for p0, rg in S:
    k = str(p0["id"])
    if k not in cache:
        t0 = (int(p0["t_in"]) // 60000) * 60000
        cache[k] = [[int(c[0]), c[1], c[2], c[3], c[4]] for c in pos.kl(p0["sym"], "1m", 1000, t0) if int(c[0]) >= t0]
json.dump(cache, open(CACHE, "w"))
PAR = {}
def mkcfg(par):
    e = copy.deepcopy(BASE)
    e["tp1"].update(on=1, unit="r", val=par["tp1r"], part=par["part"])
    bm = par["be"]
    if bm[0] == "tp1": e["be"].update(on=1, trig="tp1", lock_unit=bm[1], lock_val=bm[2])
    elif bm[0] == "r": e["be"].update(on=1, trig="r", val=bm[1], lock_unit=bm[2], lock_val=bm[3])
    else: e["be"].update(on=0)
    tr = par["trail"]
    if tr[0] == "off": e["trail"].update(on=0)
    elif tr[0] == "be": e["trail"].update(on=1, start="be", unit="atr", val=tr[1])
    else: e["trail"].update(on=1, start="r", start_val=tr[1], unit="atr", val=tr[2])
    return e
CUR = [None]
def eff(p, c=None): return CUR[0] if (p.get("xr") == "T" and CUR[0] is not None) else BASE
exit_cfg.eff = eff
def sim(p0, par):
    p = copy.deepcopy(p0)
    for k in ("parts", "rem", "tp1_done", "tp1_t", "armed_t", "trail_act", "trail_t", "t_out", "exit", "reason", "net_pct", "r_mult", "pnl_usd", "mfe_pct", "mae_pct", "stop_hist"): p.pop(k, None)
    p.update(status="open", stop=p["stop0"], armed=False, hi=p["entry"], lo=p["entry"])
    if par is None: CUR[0] = None
    else: p["xr"] = "T"; CUR[0] = mkcfg(par)
    side = 1 if p["side"] == "long" else -1; npg = par.get("np") if par else None
    for k in cache[str(p0["id"])]:
        pos.step(p, k)
        if p["status"] != "open": break
        if npg and not p.get("tp1_done") and (k[0] + 60000 - p["t_in"]) >= npg[0] * 60000:
            fav = ((p["hi"] - p["entry"]) if side > 0 else (p["entry"] - p["lo"])) / p["R"]
            if fav < npg[1]: pos.close(p, float(k[4]), k[0] + 60000, "noprog", True); break
    return p.get("net_pct") if p["status"] == "closed" else 0.0, p.get("reason")
flat = [(p, r) for p, r in S if r == "flat"]; nonflat = [(p, r) for p, r in S if r != "flat"]
print("sample: breakout total %d, flat %d, other %d" % (len(S), len(flat), len(nonflat)))
print("ids flat:", [p["id"] for p, r in flat])
chk = [(p["id"], round(p["net_pct"], 3), round(sim(p, None)[0], 3)) for p, r in S]
print("sanity real vs sim(account cfg, no rule): ", chk)
def total(lst, par): return sum(sim(p, par)[0] for p, r in lst)
GR = dict(tp1r=[0.3, 0.4, 0.5, 0.6], part=[30, 40, 50],
          be=[("tp1", "pct", 0.09), ("tp1", "r", 0.0), ("tp1", "r", -0.15), ("tp1", "r", -0.3), ("tp1", "r", -0.5), ("r", 0.8, "pct", 0.09), ("r", 0.8, "r", -0.3), ("r", 1.0, "pct", 0.2), ("none",)],
          trail=[("be", 1.5), ("off",)], np=[None])
rows = []
for tp1r, part, be, trail, npg in itertools.product(GR["tp1r"], GR["part"], GR["be"], GR["trail"], GR["np"]):
    par = dict(tp1r=tp1r, part=part, be=be, trail=trail, np=npg)
    res = {p["id"]: sim(p, par)[0] for p, r in flat}
    tf = sum(res.values()); tn = sum(sim(p, par)[0] for p, r in nonflat) if nonflat else 0.0
    rows.append((tf, tn, par, res))
rows.sort(key=lambda x: -x[0])
base_flat = sum(sim(p, None)[0] for p, r in flat); base_non = sum(sim(p, None)[0] for p, r in nonflat)
print("BASELINE no rule (account cfg): flat %.3f other %.3f" % (base_flat, base_non))
P0 = dict(tp1r=0.4, part=50, be=("tp1", "pct", 0.09), trail=("be", 1.5), np=None)
r0 = {p["id"]: sim(p, P0)[0] for p, r in flat}
print("CURRENT rule P0: flat %.3f per-trade %s" % (sum(r0.values()), {k: round(v, 2) for k, v in r0.items()}))
print("TOP 15 by flat total (other = same rule applied to non-flat, for robustness only):")
for tf, tn, par, res in rows[:15]:
    print("flat %.3f other %.3f | %s | %s" % (tf, tn, json.dumps(par), {k: round(v, 2) for k, v in res.items()}))
print("TOP 8 keeping #231 >= 1.5%:")
n = 0
for tf, tn, par, res in rows:
    if res.get(231, 0) >= 1.5:
        print("flat %.3f other %.3f | %s | %s" % (tf, tn, json.dumps(par), {k: round(v, 2) for k, v in res.items()})); n += 1
        if n >= 8: break
# пути входа: R через 3/10/30 минут и максимум за 30 минут (по закрытиям 1m)
print("PATHS (R at +3/+10/+30 min, maxR first 30 min, real r_mult):")
for p0, rg in S:
    c = cache[str(p0["id"])]; side = 1 if p0["side"] == "long" else -1; e = p0["entry"]; R = p0["R"]
    def rr(m): return round((float(c[min(m, len(c) - 1)][4]) - e) * side / R, 2)
    mx = max((float(k[2]) - e) * side if side > 0 else (e - float(k[3])) for k in c[:30]) / R
    print("#%d %s %s %s r=%s | %s %s %s | max30 %.2f" % (p0["id"], p0["sym"], p0["side"], rg, p0.get("r_mult"), rr(3), rr(10), rr(30), mx))
