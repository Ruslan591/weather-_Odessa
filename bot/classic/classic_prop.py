"""classic_prop.py — вкладка «Вместе»: бот предлагает позиции, а пользователь решает — «Открыть» или «Отклонить».

Источник предложений — прогоны стороны «Бот» в режиме mode="propose" (пара «Только предлагает»): бот по ним ищет сигналы так же, как по парам
«Торгует сам», но свой счёт не ведёт. Сделка такого прогона, пока она открыта, — это предложение на экране. Решение пользователя пишется в
proposals.json (ключ run|t_in|side).

  opened   — «Открыть»: позиция идёт в счёт «Вместе» по цене на момент нажатия; выход тот же, что у сделки бота (стоп/безубыток/цель),
             результат пересчитан от цены входа пользователя; mae сдвинут на разницу входа (оценка, нужна только для проверки ликвидации).
  rejected — «Отклонить»: сделка бота идёт дальше только в статистике («чем бы кончилось»).
  missed   — предложение закрылось (стоп/цель), решения не было.
  pending  — предложение открыто, решения нет — показывается с кнопками.
Сделки, закрытые из-за остановки прогона без решения, в статистику не входят.
"""


def dkey(run, t_in, side):
    return "%s|%s|%s" % (run, int(t_in), side)


def _adj(x, d):
    """Сделка бота, как если бы вход был по цене p_dec в момент решения; выход тот же."""
    s = 1 if x["side"] == "L" else -1
    fee = (x.get("gross") or 0.0) - (x.get("net") or 0.0)
    p_dec = float(d["p_dec"])
    gross = s * (float(x["p_out"]) / p_dec - 1.0) * 100.0
    shift = s * (float(x["p_in"]) / p_dec - 1.0) * 100.0
    y = dict(x)
    y.update(t_in=int(d["t_dec"]), p_in=p_dec, gross=round(gross, 3), net=round(gross - fee, 3),
             mae=round(min((x.get("mae") or 0.0) + shift, 0.0), 3), src="вместе", t_sig=x["t_in"])
    if not x["open"]:
        y["t_out"] = max(int(x["t_out"]), int(d["t_dec"]))
    return y


def _man_close(y, c):
    """Ручное закрытие (кнопка или сработавший ручной стоп/трейлинг): выход по цене момента, результат от цены входа пользователя."""
    s = 1 if y["side"] == "L" else -1
    fee = (y.get("gross") or 0.0) - (y.get("net") or 0.0)
    px = float(c["px"])
    gross = s * (px / float(y["p_in"]) - 1.0) * 100.0
    z = dict(y)
    z.update(p_out=px, gross=round(gross, 3), net=round(gross - fee, 3), open=False, reason=c["reason"], t_out=max(int(c["ms"]), int(y["t_in"])), manual=True)
    return z


def _grp(L, key="net", stake=6.0):
    cl = [r for r in L if not r["open"]]
    w = sum(1 for r in cl if r[key] > 0)
    s = sum(r[key] for r in cl)
    return {"n": len(L), "open": len(L) - len(cl), "closed": len(cl), "wins": w, "win_pct": round(w * 100.0 / len(cl)) if cl else None,
            "net": round(s, 2), "pnl": round(stake * s / 100.0, 2)}


def build(pt, decs, now_ms, stake=6.0, man=None):
    """pt — сделки прогонов «Бот / только предлагает» (с полями sym, tf, run). decs — решения из proposals.json."""
    dm = {d["k"]: d for d in decs}
    pending, rows, accepted, allsig = [], [], [], []
    for x in sorted(pt, key=lambda t: t["t_in"]):
        d = dm.get(dkey(x["run"], x["t_in"], x["side"]))
        if d is None and x["reason"] == "остановлен":
            continue
        st = ("pending" if x["open"] else "missed") if d is None else ("opened" if d["dec"] == "open" else "rejected")
        y = _adj(x, d) if st == "opened" else x
        mc = (man or {}).get(dkey(x["run"], x["t_in"], x["side"])) if st == "opened" else None
        if mc and mc.get("close") and y["open"]:
            y = _man_close(y, mc["close"])
        allsig.append(x)
        if st == "opened":
            accepted.append(y)
        row = {"sym": x["sym"], "tf": x["tf"], "side": x["side"], "sig": x.get("sig"), "run": x["run"], "t_in": x["t_in"], "p_in": x["p_in"],
               "stop": x["stop"], "tp": x.get("tp"), "be": bool(x["be"]), "open": bool(y["open"]), "reason": y["reason"], "status": st,
               "net": y["net"], "net_bot": x["net"], "t_out": y["t_out"], "t_dec": d["t_dec"] if d else None, "p_dec": d["p_dec"] if d else None}
        if st == "pending":
            s = 1 if x["side"] == "L" else -1
            cur = float(x["p_out"])
            row["cur"] = cur
            row["move"] = round(s * (cur / float(x["p_in"]) - 1.0) * 100.0, 3)
            row["to_stop"] = round(abs(cur - float(x["stop"])) / cur * 100.0, 3)
            row["to_tp"] = round(abs(float(x["tp"]) - cur) / cur * 100.0, 3) if x.get("tp") else None
            row["rr"] = round(row["to_tp"] / row["to_stop"], 2) if row["to_tp"] and row["to_stop"] else None
            pending.append(row)
        else:
            rows.append(row)
    pending.sort(key=lambda r: -r["t_in"])
    rows.sort(key=lambda r: -r["t_in"])
    by = lambda s: [r for r in rows if r["status"] == s]
    dec_closed = [r for r in rows if r["status"] in ("opened", "rejected") and not r["open"]]
    right = sum(1 for r in dec_closed if (r["net"] > 0) == (r["status"] == "opened"))
    stats = {"opened": _grp(by("opened"), "net", stake), "rejected": _grp(by("rejected"), "net_bot", stake),
             "missed": _grp(by("missed"), "net_bot", stake), "pending": len(pending),
             "all": _grp(rows + pending, "net_bot", stake),
             "right": right, "decided_closed": len(dec_closed), "right_pct": round(right * 100.0 / len(dec_closed)) if dec_closed else None}
    return {"pending": pending, "rows": rows[:150], "stats": stats, "accepted": accepted, "allsig": allsig}
