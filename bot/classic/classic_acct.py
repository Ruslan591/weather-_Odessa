"""classic_acct.py — счета «как на бирже» для трёх сторон сравнения: Вы (рисунки), Бот (авто-детектор), Вместе (оба согласны).

Два взгляда на одни и те же сделки (net — результат сделки в % от цены уже после комиссии):
  sim_account  — «Счёт»: реалистично. Старт 7 $, плечо 5x, изолированная маржа, одна позиция в моменте; в сделку идёт весь баланс как маржа
                 (размер позиции = баланс × плечо, минимум 6 $). Сигнал, пришедший пока позиция открыта, пропускается. Ликвидация, если цена ушла
                 против входа на (1/плечо − поддерживающая маржа) ≈ 19.6 % (по mae сделки).
  sim_signals  — «Все сигналы»: каждый сигнал учтён отдельно, одинаковый размер позиции (как у счёта на старте: 7 $ × 5 = 35 $), без лимита
                 «одна позиция». Показывает, сколько денег нужно на старте, чтобы взять все сигналы: пик одновременной маржи + максимальная просадка.
  joint_trades — «Вместе»: сигнал робота и сигнал по рисунку совпали (пара, ТФ, сторона, вход в пределах 3 свечей, позиции пересекаются);
                 в сделку идёт та из двух, что вошла позже (момент, когда согласие состоялось).
"""
LEV = 5.0
START = 7.0
MIN_NOTIONAL = 6.0
MMR = 0.004
LIQ_PCT = (1.0 / LEV - MMR) * 100.0  # 19.6 %


def _r(v, n=2):
    return round(float(v), n)


def _liq_price(side, p):
    return p * (1 - LIQ_PCT / 100.0) if side == "L" else p * (1 + LIQ_PCT / 100.0)


def sim_account(trades, start=START, lev=LEV):
    ts = sorted(trades, key=lambda x: x["t_in"])
    bal = float(start)
    free_at = 0
    pos = None
    taken, skipped, wins, liqs, blocked = [], 0, 0, 0, False
    for x in ts:
        if pos is not None or x["t_in"] < free_at:
            skipped += 1
            continue
        notional = bal * lev
        if notional < MIN_NOTIONAL:
            blocked = True
            skipped += 1
            continue
        margin = bal
        liq = (x.get("mae") or 0.0) <= -LIQ_PCT
        pnl = -margin if liq else notional * x["net"] / 100.0
        rec = {"sym": x.get("sym"), "tf": x.get("tf"), "side": x["side"], "sig": x.get("sig"), "t_in": x["t_in"], "t_out": x["t_out"],
               "p_in": x["p_in"], "net": x["net"], "open": bool(x["open"]), "notional": _r(notional), "margin": _r(margin), "pnl": _r(pnl), "liq": liq}
        if x["open"]:
            pos = {"x": x, "margin": margin, "notional": notional, "pnl": pnl}
            rec["bal_after"] = None
        else:
            bal = max(bal + pnl, 0.0)
            free_at = x["t_out"]
            rec["bal_after"] = _r(bal)
            wins += 1 if pnl > 0 else 0
            liqs += 1 if liq else 0
        taken.append(rec)
    unreal = pos["pnl"] if pos else 0.0
    equity = bal + unreal
    margin_used = pos["margin"] if pos else 0.0
    cur = None
    if pos:
        x = pos["x"]
        cur = {"sym": x.get("sym"), "tf": x.get("tf"), "side": x["side"], "p_in": x["p_in"], "mark": x["p_out"], "liq_price": float("%.6g" % _liq_price(x["side"], x["p_in"])),
               "stop": x["stop"], "tp": x.get("tp"), "notional": _r(pos["notional"]), "margin": _r(pos["margin"]), "upnl": _r(unreal),
               "roe": _r(unreal / pos["margin"] * 100.0 if pos["margin"] else 0.0), "be": bool(x["be"]), "t_in": x["t_in"], "sig": x.get("sig")}
    closed = [t for t in taken if not t["open"]]
    status = "ликвидация: счёт обнулён" if (bal <= 0 and liqs) else ("баланс ниже минимальной позиции 6 $" if blocked and not pos else "активен")
    return {"start": start, "lev": lev, "balance": _r(bal), "unreal": _r(unreal), "equity": _r(equity), "margin": _r(margin_used),
            "available": _r(max(bal - margin_used, 0.0)), "ret_pct": _r((equity - start) / start * 100.0), "pnl": _r(equity - start),
            "taken": len(taken), "closed": len(closed), "wins": wins, "win_pct": _r(wins / len(closed) * 100.0, 0) if closed else None,
            "skipped": skipped, "liqs": liqs, "status": status, "pos": cur, "log": taken[-40:][::-1]}


def sim_signals(trades, now_ms, notional=START * LEV, lev=LEV):
    margin = notional / lev
    items = []
    for x in trades:
        liq = (x.get("mae") or 0.0) <= -LIQ_PCT
        items.append((x, -margin if liq else notional * x["net"] / 100.0))
    n = len(items)
    total = sum(p for _, p in items)
    wins = sum(1 for _, p in items if p > 0)
    ev = []
    for x, _ in items:
        ev.append((x["t_in"], 1))
        ev.append(((now_ms + 1) if x["open"] else x["t_out"], -1))
    ev.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    cum = pk = dd = 0.0
    for t, p in sorted(((x["t_out"], p) for x, p in items if not x["open"]), key=lambda e: e[0]):
        cum += p
        pk = max(pk, cum)
        dd = max(dd, pk - cum)
    need = peak * margin + dd
    return {"n": n, "wins": wins, "win_pct": _r(wins / n * 100.0, 0) if n else None, "open": sum(1 for x, _ in items if x["open"]),
            "total": _r(total), "notional": _r(notional), "margin": _r(margin), "peak": peak, "peak_margin": _r(peak * margin), "max_dd": _r(dd),
            "need": _r(need), "roi": _r(total / need * 100.0) if need > 0 else None}


def joint_trades(me, bot, tf_min):
    used = set()
    out = []
    for a in sorted(me, key=lambda t: t["t_in"]):
        tfm = tf_min.get(a.get("tf"), 15) * 60000
        best, bd = None, None
        for j, b in enumerate(bot):
            if j in used or b.get("sym") != a.get("sym") or b.get("tf") != a.get("tf") or b["side"] != a["side"]:
                continue
            d = abs(a["t_in"] - b["t_in"])
            if d > 3 * tfm:
                continue
            e, l = (a, b) if a["t_in"] <= b["t_in"] else (b, a)
            if (not e["open"]) and e["t_out"] <= l["t_in"]:
                continue
            if bd is None or d < bd:
                best, bd = j, d
        if best is not None:
            used.add(best)
            b = bot[best]
            later = a if a["t_in"] >= b["t_in"] else b
            d = dict(later)
            d["src"] = "вместе"
            out.append(d)
    return out
