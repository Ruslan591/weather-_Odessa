# -*- coding: utf-8 -*-
"""Развороты после стопа («пробой, надо было идти за ним»): после сделки, закрытой по стопу, открываем сделку в ПРОТИВОПОЛОЖНУЮ сторону.
Варианты входа: сразу по цене выхода (рынок, издержки как у рыночного входа) или после подтверждения: 2 минутные свечи подряд закрылись за уровнем стопа. Стоп нового входа на R (как у исходной сделки) от входа, остальное по правилам счёта
(движок pos.step, кэш минутных путей). Итог в R новой сделки. Данные те же (in-sample), обе половины рядом. Запуск на VPS как entry_study.py."""
import copy, gzip, json, os, sys, urllib.request
os.environ["POS_DIR"] = "/tmp/rev_pos"; os.makedirs("/tmp/rev_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/rev_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
S = [p for p in snap["closed"] if p.get("reason") == "stop" and cache.get(str(p["id"])) and p.get("t_out")]
allp = [p for p in snap["closed"] if p.get("t_out")]; ids = sorted(p["id"] for p in snap["closed"]); half = ids[len(ids) // 2]
print("стопов с путями: %d из %d закрытых; сумма этих стопов %+.1f R\n" % (len(S), len(snap["closed"]), sum(p["r_mult"] or 0 for p in S)))


def run(p, confirm):
    sd0 = 1 if p["side"] == "long" else -1; sd = -sd0; R = p["R"]
    ks = [k for k in cache[str(p["id"])]["ks"] if k[0] >= (p["t_out"] // 60000) * 60000]
    lvl = p["exit"]; start = 0
    if confirm:                                                   # две минутные свечи подряд закрылись за уровнем стопа (в сторону пробоя)
        c = 0; start = None
        for i, k in enumerate(ks):
            c = c + 1 if (k[4] > lvl if sd > 0 else k[4] < lvl) else 0
            if c >= confirm: start = i + 1; break
        if start is None or start >= len(ks): return None
    k0 = ks[start - 1] if start else ks[0]
    E = (k0[4] if confirm else lvl) * (1 + sd * pos.SLIP / 100)
    q = {x: copy.deepcopy(p[x]) for x in ("sym", "stake", "lev", "atr1h", "max_h", "thesis", "src") if x in p}
    q.update(id=p["id"], side="long" if sd > 0 else "short", rule="reverse", t_in=k0[0] + 60000, entry=E, px_signal=E, stop0=E - sd * R, stop=E - sd * R, tp=E + sd * 2 * R, R=R, R_pct=R / E * 100, be_r=1.0, lock_pct=0.2,
             be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False, trail_dist=1.5 * (p.get("atr1h") or 0), hi=E, lo=E, status="open", fee_in=pos.FEE, fee_tp=0.02, last_t=0)
    for k in ks[start:]:
        pos.step(q, k)
        if q["status"] != "open": break
    if q["status"] == "open": pos.close(q, ks[-1][4], ks[-1][0] + 60000, "time", True)
    return q["net_pct"] / p["R_pct"], q["reason"]


for confirm, lab in ((0, "сразу по цене выхода"), (2, "после 2 минутных закрытий за уровнем стопа")):
    rs = [(p, run(p, confirm)) for p in S]; rs = [(p, r) for p, r in rs if r is not None]
    tot = sum(r[0] for p, r in rs); h1 = sum(r[0] for p, r in rs if p["id"] < half)
    print("разворот %-44s: сделок %3d, сумма %+6.1f R (1/2: %+6.1f / %+6.1f), на сделку %+.2f R, стоп %3.0f%%, цель %3.0f%%" % (lab, len(rs), tot, h1, tot - h1, tot / max(1, len(rs)),
          100 * sum(r[1] == "stop" for p, r in rs) / max(1, len(rs)), 100 * sum(r[1] == "target" for p, r in rs) / max(1, len(rs))))
    for rule in sorted({p.get("rule") for p, r in rs}):
        g = [(p, r) for p, r in rs if p.get("rule") == rule]
        print("   правило исходной сделки %-12s n=%3d  разворот %+6.1f R (на сделку %+.2f R); сами стопы были %+6.1f R" % (rule, len(g), sum(r[0] for p, r in g), sum(r[0] for p, r in g) / len(g), sum(p["r_mult"] or 0 for p, r in g)))
