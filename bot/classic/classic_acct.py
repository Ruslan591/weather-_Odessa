"""classic_acct.py — счета «как на бирже» для трёх сторон сравнения: Вы (рисунки), Бот (авто-детектор), Вместе (оба согласны).

Два взгляда на одни и те же сделки (net — результат сделки в % от цены уже после комиссии):
  sim_account  — «Счёт»: реалистично. Старт 7 $, плечо 5x, изолированная маржа. Каждая позиция по минимальной ставке 6 $ (маржа 1.20 $), несколько
                 позиций одновременно, пока занято не больше 70 % баланса (на 7 $ — до 4), остальное — запас на просадку. Сигнал без свободной маржи
                 пропускается. Ликвидация позиции, если цена ушла против входа на (1/плечо − поддерживающая маржа) ≈ 19.6 % (по mae сделки).
  sim_signals  — «Все сигналы»: каждый сигнал учтён отдельно, ставка та же (6 $). Показывает, сколько денег нужно на старте, чтобы взять все сигналы:
                 пик одновременной маржи (с тем же запасом 30 %) + максимальная просадка.
  joint_trades — «Вместе»: сигнал робота и сигнал по рисунку совпали (пара, ТФ, сторона, вход в пределах 3 свечей, позиции пересекаются);
                 в сделку идёт та из двух, что вошла позже (момент, когда согласие состоялось).
"""
LEV = 5.0
START = 7.0
MIN_NOTIONAL = 6.0   # минимальная ставка (размер позиции) — на каждую сделку
MAX_USE = 0.70       # одновременно в марже не больше 70 % баланса, остальное — запас на просадку
MMR = 0.004
LIQ_PCT = (1.0 / LEV - MMR) * 100.0  # 19.6 %


def _r(v, n=2):
    return round(float(v), n)


def _liq_price(side, p):
    return p * (1 - LIQ_PCT / 100.0) if side == "L" else p * (1 + LIQ_PCT / 100.0)


def _pnl(x, stake, margin):
    return -margin if (x.get("mae") or 0.0) <= -LIQ_PCT else stake * x["net"] / 100.0


def sim_account(trades, start=START, lev=LEV, stake=MIN_NOTIONAL, use=MAX_USE):
    """Каждая позиция — минимальная ставка stake (маржа stake/lev). Новая позиция открывается, пока занятая маржа с ней не превышает use×баланс
    (по реализованному балансу); сигнал без свободной маржи пропускается. Несколько позиций одновременно."""
    ts = sorted(trades, key=lambda x: x["t_in"])
    margin = stake / lev
    bal = float(start)
    openp, taken = [], []
    st = {"wins": 0, "liqs": 0, "skipped": 0, "maxc": 0}

    def settle(upto):
        nonlocal bal
        done = sorted([p for p in openp if (not p["x"]["open"]) and p["x"]["t_out"] <= upto], key=lambda p: p["x"]["t_out"])
        for p in done:
            bal = max(bal + p["pnl"], 0.0)
            st["wins"] += 1 if p["pnl"] > 0 else 0
            st["liqs"] += 1 if p["liq"] else 0
            p["rec"]["bal_after"] = _r(bal)
            openp.remove(p)

    for x in ts:
        settle(x["t_in"])
        if (len(openp) + 1) * margin > use * bal + 1e-9:
            st["skipped"] += 1
            continue
        liq = (x.get("mae") or 0.0) <= -LIQ_PCT
        pnl = _pnl(x, stake, margin)
        rec = {"sym": x.get("sym"), "tf": x.get("tf"), "side": x["side"], "sig": x.get("sig"), "t_in": x["t_in"], "t_out": x["t_out"], "p_in": x["p_in"],
               "net": x["net"], "open": bool(x["open"]), "notional": _r(stake), "margin": _r(margin), "pnl": _r(pnl), "liq": liq, "be": bool(x.get("be")), "bal_after": None,
               "run": x.get("run"), "kt": x.get("t_sig", x["t_in"])}
        openp.append({"x": x, "pnl": pnl, "liq": liq, "rec": rec})
        taken.append(rec)
        st["maxc"] = max(st["maxc"], len(openp))
    settle(float("inf"))
    cur = []
    for p in openp:
        x = p["x"]
        cur.append({"sym": x.get("sym"), "tf": x.get("tf"), "side": x["side"], "p_in": x["p_in"], "mark": x["p_out"], "liq_price": float("%.6g" % _liq_price(x["side"], x["p_in"])),
                    "stop": x["stop"], "tp": x.get("tp"), "notional": _r(stake), "margin": _r(margin), "upnl": _r(p["pnl"]),
                    "roe": _r(p["pnl"] / margin * 100.0), "be": bool(x["be"]), "t_in": x["t_in"], "sig": x.get("sig"),
                    "run": x.get("run"), "kt": x.get("t_sig", x["t_in"])})  # run+kt+side — адрес позиции для кнопок «Закрыть» / «Стоп»
    unreal = sum(p["pnl"] for p in openp)
    margin_used = len(openp) * margin
    equity = bal + unreal
    closed = [t for t in taken if not t["open"]]
    can = int(use * bal / margin + 1e-9)
    status = "ликвидация: счёт обнулён" if (bal <= 0 and st["liqs"]) else ("баланс слишком мал для минимальной позиции" if can < 1 and not openp else "активен")
    return {"start": start, "lev": lev, "stake": _r(stake), "margin_each": _r(margin), "use": use, "max_pos": can, "balance": _r(bal), "unreal": _r(unreal), "equity": _r(equity),
            "margin": _r(margin_used), "available": _r(max(bal - margin_used, 0.0)), "ret_pct": _r((equity - start) / start * 100.0), "pnl": _r(equity - start),
            "taken": len(taken), "closed": len(closed), "wins": st["wins"], "win_pct": _r(st["wins"] / len(closed) * 100.0, 0) if closed else None,
            "skipped": st["skipped"], "maxc": st["maxc"], "liqs": st["liqs"], "status": status, "positions": cur, "log": taken[-200:][::-1]}


def sim_signals(trades, now_ms, stake=MIN_NOTIONAL, lev=LEV, use=MAX_USE):
    """Каждый сигнал учтён отдельно, ставка stake. Нужно на старте: пик одновременной маржи (с запасом: занято не больше use баланса) + максимальная просадка."""
    margin = stake / lev
    items = [(x, _pnl(x, stake, margin)) for x in trades]
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
    need = peak * margin / use + dd
    return {"n": n, "wins": wins, "win_pct": _r(wins / n * 100.0, 0) if n else None, "open": sum(1 for x, _ in items if x["open"]),
            "total": _r(total), "notional": _r(stake), "margin": _r(margin), "use": use, "peak": peak, "peak_margin": _r(peak * margin), "peak_need": _r(peak * margin / use),
            "max_dd": _r(dd), "need": _r(need), "roi": _r(total / need * 100.0) if need > 0 else None}


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
