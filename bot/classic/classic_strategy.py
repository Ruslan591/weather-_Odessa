"""classic_strategy.py — стратегия «пересечение EMA20 × EMA200», 15m, лонг и шорт (симуляция по истории, бумага).
Вход: по открытию свечи, следующей за свечой пересечения (сигнал только по ЗАКРЫТОЙ свече).
Начальный стоп: последний подтверждённый pivot (для лонга pivot-low ниже входа, для шорта pivot-high выше входа).
+BE_TRIGGER% в нашу сторону → стоп в безубыток (цена входа). Далее стоп-трейлинг по последним подтверждённым pivot.
Выход: стоп, либо обратное пересечение (разворот: закрытие и вход в другую сторону).
Внутри одной свечи считаем консервативно: сначала проверяется стоп, потом движение в плюс."""
import classic_analysis as an

PARAMS = dict(tf="15m", be_trigger=1.0, fee=0.05, window_h=24, notional=100.0, warmup=200)


def _last_piv(piv, kind, maxconf, ok):
    for q in reversed(piv):
        if q["k"] == kind and q["conf"] <= maxconf and ok(q["p"]):
            return q["p"]
    return None


def simulate(df, now_ms, P=PARAMS):
    T = len(df)
    live = T > 0 and df.ct.iloc[-1] > now_ms
    M = T - 1 if live else T
    if M < P["warmup"] + 30:
        return []
    closed = df.iloc[:M].reset_index(drop=True)
    ind = an.indicators(closed)
    piv = an.find_pivots(closed)
    e20, e200 = ind["ema20"].values, ind["ema200"].values
    o, h, l, c, t = df.o.values, df.h.values, df.l.values, df.c.values, df.t.values
    fee2 = 2 * P["fee"]
    trades, pos, pend = [], None, None

    def finish(i, price, reason):
        nonlocal pos
        s = 1 if pos["side"] == "L" else -1
        gross = s * (price / pos["p_in"] - 1) * 100
        pos.update(i_out=i, t_out=int(t[i]), p_out=float(price), reason=reason,
                   gross=gross, net=gross - fee2, open=False)
        trades.append(pos)
        pos = None

    for i in range(1, T):
        if pend:
            side, pend = pend, None
            if pos and pos["side"] != side:
                finish(i, o[i], "разворот")
            if pos is None:
                entry = float(o[i])
                if side == "L":
                    st = _last_piv(piv, "L", i - 1, lambda p: p < entry)
                else:
                    st = _last_piv(piv, "H", i - 1, lambda p: p > entry)
                if st is not None:
                    pos = dict(side=side, i_in=i, t_in=int(t[i]), p_in=entry, stop0=st, stop=st, stage="init",
                               risk=abs(entry - st) / entry * 100, mfe=0.0, mae=0.0, be=False)
        if pos:
            L_ = pos["side"] == "L"
            e = pos["p_in"]
            hit = (l[i] <= pos["stop"]) if L_ else (h[i] >= pos["stop"])
            adv = (l[i] / e - 1) * 100 if L_ else (1 - h[i] / e) * 100
            fav = (h[i] / e - 1) * 100 if L_ else (1 - l[i] / e) * 100
            pos["mae"] = min(pos["mae"], adv)
            if hit:
                if L_:
                    px = o[i] if o[i] <= pos["stop"] else pos["stop"]
                else:
                    px = o[i] if o[i] >= pos["stop"] else pos["stop"]
                nm = {"init": "стоп (pivot)", "be": "безубыток", "trail": "трейлинг"}[pos["stage"]]
                finish(i, px, nm)
            else:
                pos["mfe"] = max(pos["mfe"], fav)
                if (not pos["be"]) and fav >= P["be_trigger"]:
                    pos["be"], pos["stop"], pos["stage"] = True, e, "be"
                if pos["be"] and i < M:
                    if L_:
                        q = _last_piv(piv, "L", i, lambda p: p > pos["stop"] and p < c[i])
                        if q is not None: pos["stop"], pos["stage"] = q, "trail"
                    else:
                        q = _last_piv(piv, "H", i, lambda p: p < pos["stop"] and p > c[i])
                        if q is not None: pos["stop"], pos["stage"] = q, "trail"
        if P["warmup"] <= i < M:
            pr, cu = e20[i - 1] - e200[i - 1], e20[i] - e200[i]
            if pr <= 0 < cu: pend = "L"
            elif pr >= 0 > cu: pend = "S"
    if pos:
        s = 1 if pos["side"] == "L" else -1
        gross = s * (c[T - 1] / pos["p_in"] - 1) * 100
        pos.update(i_out=T - 1, t_out=int(t[T - 1]), p_out=float(c[T - 1]), reason="открыта", gross=gross,
                   net=gross - fee2, open=True)
        trades.append(pos)
    return trades


def pack(trades):
    out = []
    for x in trades:
        d = {k: x[k] for k in ("side", "t_in", "t_out", "reason", "be", "open")}
        for k in ("p_in", "p_out", "stop0", "stop"):
            d[k] = an._r(float(x[k]))
        for k in ("risk", "gross", "net", "mfe", "mae"):
            d[k] = round(float(x[k]), 3)
        out.append(d)
    return out
