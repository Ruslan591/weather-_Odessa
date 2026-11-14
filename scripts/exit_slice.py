# -*- coding: utf-8 -*-
"""Срез по закрытым сделкам: как далеко уходит цена в нашу сторону (MFE в R), как часто достигается порог безубытка, чем кончаются такие сделки,
и что было бы при закрытии целиком на заданном уровне R (грубо, по MFE, комиссии учтены по полям fee_in/fee_tp). Не бэктест правил: описание того, что было.
Запуск на VPS: /opt/trading-bot/venv/bin/python exit_slice.py [id_from] [id_to]. Только чтение."""
import json, sys, urllib.request, statistics as st

POS = "/opt/trading-bot/positions_regr"
A = int(sys.argv[1]) if len(sys.argv) > 1 else 237
B = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(POS + "/orders.json", encoding="utf-8"))}
cfg = json.load(open(POS + "/exit_cfg.json", encoding="utf-8"))
print("exit_cfg: stop %s | BE trig %s %s, lock %s %s | trail on=%s start=%s %s %s | tp %s %s | tp1 on=%s" % (cfg["stop"], cfg["be"]["trig"], cfg["be"]["val"], cfg["be"]["lock_val"], cfg["be"]["lock_unit"],
      cfg["trail"]["on"], cfg["trail"]["start"], cfg["trail"]["val"], cfg["trail"]["unit"], cfg["tp"]["mode"], cfg["tp"]["val"], cfg["tp1"]["on"]))
rows = []
for p in snap["closed"]:
    if not (A <= p["id"] <= B) or not p.get("R_pct"): continue
    o = orders.get(p.get("order_id")) or {}; rg = (o.get("regime") or {}).get("regime")
    sgn = "short" if p["side"] == "short" else "long"
    with_reg = None if rg in (None, "flat") else ((rg == "down") == (sgn == "short"))
    cost = ((p.get("fee_in") or 0) + (p.get("fee_tp") or 0)) / (p.get("stake") or 1) * 100
    rows.append(dict(id=p["id"], sym=p["sym"], side=sgn, reason=str(p["reason"]), net=p["net_pct"], Rp=p["R_pct"], R=p["r_mult"], mfe=(p.get("mfe_pct") or 0) / p["R_pct"],
                     mae=(p.get("mae_pct") or 0) / p["R_pct"], cost=cost / p["R_pct"], setup=o.get("setup"), with_reg=with_reg, counter=o.get("counter"), rule=p.get("rule")))
n = len(rows); ids = [r["id"] for r in rows]
print("\nсделок %d (id %d..%d), стоп %.0f%%, trail/БУ %.0f%%, цель %.0f%%, средний R %+.2f, сумма %+.1f R, средний риск R_pct %.2f%% (мин %.2f, макс %.2f)" % (
    n, min(ids), max(ids), 100 * sum(r["reason"] == "stop" for r in rows) / n, 100 * sum(r["reason"].startswith("trail") for r in rows) / n, 100 * sum(r["reason"] == "target" for r in rows) / n,
    sum(r["R"] for r in rows) / n, sum(r["R"] for r in rows), sum(r["Rp"] for r in rows) / n, min(r["Rp"] for r in rows), max(r["Rp"] for r in rows)))
print("\nДо какого уровня доходила цена в нашу сторону (MFE в R), доля сделок:")
for x in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0): print("  MFE >= %.2f R : %3.0f%%  (%d из %d)" % (x, 100 * sum(r["mfe"] >= x for r in rows) / n, sum(r["mfe"] >= x for r in rows), n))
print("  медиана MFE %.2f R, медиана MAE %.2f R" % (st.median(r["mfe"] for r in rows), st.median(r["mae"] for r in rows)))
hit = [r for r in rows if r["mfe"] >= cfg["be"]["val"]]; no = [r for r in rows if r["mfe"] < cfg["be"]["val"]]
print("\nДошли до порога БУ (%.1f R): %d сделок. Чем кончились: %s; средний итог %+.2f R, итог в %% %+.2f; средний MFE %.2f R" % (cfg["be"]["val"], len(hit), {k: sum(r["reason"].startswith(k) for r in hit) for k in ("trail", "stop", "target")},
      sum(r["R"] for r in hit) / max(1, len(hit)), sum(r["net"] for r in hit) / max(1, len(hit)), sum(r["mfe"] for r in hit) / max(1, len(hit))))
print("Не дошли: %d сделок, стоп %.0f%%, средний итог %+.2f R, средний MFE %.2f R, из них MFE от 0.5 до порога: %d" % (len(no), 100 * sum(r["reason"] == "stop" for r in no) / max(1, len(no)), sum(r["R"] for r in no) / max(1, len(no)),
      sum(r["mfe"] for r in no) / max(1, len(no)), sum(0.5 <= r["mfe"] < cfg["be"]["val"] for r in no)))
print("\nЕсли бы закрывать ЦЕЛИКОМ при достижении уровня X (R), остальное как было (грубо по MFE, минус комиссии сделки):")
base = sum(r["R"] for r in rows)
print("  как есть: сумма %+.1f R, средний %+.2f R" % (base, base / n))
for x in (0.3, 0.5, 0.75, 1.0, 1.5, 2.0):
    tot = sum((x - r["cost"]) if r["mfe"] >= x else r["R"] for r in rows)
    print("  закрытие на %.2f R: сумма %+.1f R, средний %+.2f R, срабатывает в %3.0f%% сделок" % (x, tot, tot / n, 100 * sum(r["mfe"] >= x for r in rows) / n))
print("  (для справки: средняя комиссия сделки %.2f R)" % (sum(r["cost"] for r in rows) / n))


def grp(title, f):
    print("\n== " + title)
    keys = sorted({f(r) for r in rows}, key=str)
    for k in keys:
        g = [r for r in rows if f(r) == k]; m = len(g)
        print("  %-30s n=%3d  стоп %3.0f%%  средний R %+.2f  MFE: медиана %.2f R, >=0.5R %3.0f%%, >=1R %3.0f%%  MAE медиана %.2f R" % (k, m, 100 * sum(r["reason"] == "stop" for r in g) / m, sum(r["R"] for r in g) / m,
              st.median(r["mfe"] for r in g), 100 * sum(r["mfe"] >= 0.5 for r in g) / m, 100 * sum(r["mfe"] >= 1 for r in g) / m, st.median(r["mae"] for r in g)))


grp("пробой / отбой", lambda r: r["setup"])
grp("по режиму рынка (with) / против", lambda r: {True: "по режиму", False: "против режима", None: "режим flat/нет"}[r["with_reg"]])
grp("по каналу / против канала (counter)", lambda r: "против канала" if r["counter"] else "по каналу")
grp("вход (правило)", lambda r: r["rule"])
grp("класс: setup + режим", lambda r: "%s / %s" % (r["setup"], {True: "по режиму", False: "против режима", None: "flat"}[r["with_reg"]]))
