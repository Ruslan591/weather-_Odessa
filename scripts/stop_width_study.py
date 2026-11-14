# -*- coding: utf-8 -*-
"""Комиссии и ширина стопа по кэшу путей (scripts/paths_cache.py), реальный движок pos.step.
1) Сколько съедают комиссии и проскальзывание: итог сделок до и после издержек.
2) Что меняет более широкий стоп (k x от фактического) при той же точке входа: цель либо растёт пропорционально (RR как был), либо остаётся на месте (абсолютная).
Итог в % от суммы позиции (net_pct), потому что R меняется; также стоп%/цель%. Те же данные (in-sample), смотреть обе половины. Запуск на VPS как entry_study.py."""
import copy, gzip, json, os, sys, urllib.request
os.environ["POS_DIR"] = "/tmp/swstudy_pos"; os.makedirs("/tmp/swstudy_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/swstudy_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"]))
    if not c or not c["ks"] or p.get("entry") is None: continue
    last_t = (p["t_in"] // 60000) * 60000; ks = [k for k in c["ks"] if k[0] > last_t]
    if len(ks) >= 5: T.append(dict(p=p, ks=ks, sd=1 if p["side"] == "long" else -1))
N = len(T); ids = sorted(t["p"]["id"] for t in T); half = ids[N // 2]

act = [t["p"] for t in T]
gross = [((p["exit"] / p["entry"] - 1) * 100 * (1 if p["side"] == "long" else -1)) for p in act]
net = [p["net_pct"] for p in act]; cost = [g - n for g, n in zip(gross, net)]
print("== 1. Издержки (фактические сделки, %d шт.)" % N)
print("  сумма до издержек %+.1f%%, издержки %.1f%%, итог %+.1f%% (от суммы позиции); издержки на сделку %.3f%%, медианный риск R %.2f%% => издержки около %.2f R на сделку" % (
    sum(gross), sum(cost), sum(net), sum(cost) / N, sorted(p["R_pct"] for p in act)[N // 2], sum(c / p["R_pct"] for c, p in zip(cost, act)) / N))
print("  итог в R: %+.1f R; до издержек было бы %+.1f R (разница %.1f R)" % (sum(p["r_mult"] or 0 for p in act), sum(g / p["R_pct"] for g, p in zip(gross, act)), sum(c / p["R_pct"] for c, p in zip(cost, act))))
bt = {}
for t in T: bt.setdefault(t["p"].get("rule"), []).append(t["p"])
for r, g in sorted(bt.items(), key=lambda x: -len(x[1])):
    print("  %-12s n=%3d  до издержек %+6.1f%%  издержки %5.1f%%  итог %+6.1f%%" % (r, len(g), sum(((p["exit"] / p["entry"] - 1) * 100 * (1 if p["side"] == "long" else -1)) for p in g), sum(((p["exit"] / p["entry"] - 1) * 100 * (1 if p["side"] == "long" else -1)) - p["net_pct"] for p in g), sum(p["net_pct"] for p in g)))


def build(t, k, rr):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; R = p0["R"] * k; S = E - sd * R; tp = E + sd * abs(p0["tp"] - E) * (k if rr else 1.0)
    q = {x: copy.deepcopy(p0[x]) for x in ("id", "sym", "side", "stake", "lev", "atr1h", "max_h", "thesis", "rule", "src", "fee_in", "fee_tp") if x in p0}
    q.update(t_in=p0["t_in"], entry=E, px_signal=E, stop0=S, stop=S, tp=tp, R=R, R_pct=R / E * 100, be_r=1.0, lock_pct=0.2, be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False,
             trail_dist=1.5 * (p0.get("atr1h") or 0), hi=E, lo=E, status="open", last_t=0)
    if p0.get("xr"): q["xr"] = p0["xr"]
    return q


def play(t, k, rr):
    q = build(t, k, rr)
    for kk in t["ks"]:
        pos.step(q, kk)
        if q["status"] != "open": break
    if q["status"] == "open": pos.close(q, t["ks"][-1][4], t["ks"][-1][0] + 60000, "time", True)
    return q


print("\n== 2. Ширина стопа (вход как был; итог в %% от суммы позиции; k = во сколько раз стоп шире фактического)")
print("%-34s %9s %8s %8s %8s %8s %8s %8s" % ("вариант", "сумма %", "1 пол.", "2 пол.", "на сд.", "стоп%", "цель%", "БУ/трейл%"))
for rr in (True, False):
    for k in (1.0, 1.25, 1.5, 2.0, 3.0):
        qs = [play(t, k, rr) for t in T]; tot = sum(q["net_pct"] for q in qs)
        h1 = sum(q["net_pct"] for q, t in zip(qs, T) if t["p"]["id"] < half)
        n = len(qs); st = 100 * sum(q["reason"] == "stop" for q in qs) / n; tg = 100 * sum(q["reason"] == "target" for q in qs) / n; be = 100 * sum(str(q["reason"]).startswith("trail") for q in qs) / n
        print("%-34s %+9.1f %+8.1f %+8.1f %+8.3f %7.0f%% %7.0f%% %8.0f%%" % ("k=%.2f, цель %s" % (k, "x k (RR как был)" if rr else "на месте"), tot, h1, tot - h1, tot / n, st, tg, be))
