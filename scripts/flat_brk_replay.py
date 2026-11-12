# -*- coding: utf-8 -*-
"""Прогон правила flat_brk (50% на +0.4R, остаток в БУ с комиссиями) задним числом по закрытым позициям счёта regr.
Запуск на VPS: cd /opt/trading-bot/positions && POS_DIR=/opt/trading-bot/positions_regr /opt/trading-bot/venv/bin/python flat_brk_replay.py [id_from id_to]
Берёт позицию, сбрасывает состояние, ставит xr=flat_brk и гонит pos.step по 1m свечам от входа. Перенос стопа на S/R (pos._update) не воспроизводится."""
import sys, json, copy
import pos
a = int(sys.argv[1]) if len(sys.argv) > 1 else 227; b = int(sys.argv[2]) if len(sys.argv) > 2 else 232
ps = json.load(open(pos.F)); om = {o["id"]: o for o in json.load(open(pos.F.replace("positions.json", "orders.json")))}
tot0 = tot1 = 0.0
for p0 in ps:
    if not (a <= p0["id"] <= b) or p0["status"] != "closed": continue
    o = om.get(p0.get("order_id")) or {}
    p = copy.deepcopy(p0)
    for k in ("parts", "rem", "tp1_done", "tp1_t", "armed_t", "trail_act", "trail_t", "t_out", "exit", "reason", "net_pct", "r_mult", "pnl_usd", "mfe_pct", "mae_pct", "stop_hist"): p.pop(k, None)
    p.update(status="open", stop=p["stop0"], armed=False, hi=p["entry"], lo=p["entry"], xr="flat_brk")
    t0 = (int(p0["t_in"]) // 60000) * 60000; tend = int(p0["t_out"]) + 3600000 * 6
    d = pos.kl(p0["sym"], "1m", 1000, t0)
    for k in d:
        if int(k[0]) < t0: continue
        pos.step(p, k)
        if p["status"] != "open": break
        if int(k[0]) > tend: break
    n1 = p.get("net_pct"); print("#%d %s %s %s/%s | real: %s %.3f net %.3f R | rule: %s net %s (%s) parts %d" % (p0["id"], p0["sym"], p0["side"], o.get("setup"), (o.get("regime") or {}).get("regime"), p0.get("reason"), p0.get("r_mult"), p0.get("net_pct"), p.get("reason") or "open", n1, p.get("r_mult"), len(p.get("parts", []))))
    tot0 += p0.get("net_pct") or 0; tot1 += n1 or 0
print("TOTAL net%% real %.3f rule %.3f" % (tot0, tot1))
