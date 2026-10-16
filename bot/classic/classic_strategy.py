"""classic_strategy.py — стратегия «пересечение EMA20 × EMA200», 15m, лонг и шорт (симуляция по истории, бумага).
Вход: по открытию свечи, следующей за свечой пересечения (сигнал только по ЗАКРЫТОЙ свече).
Начальный стоп (stop_mode):
  prev  — за экстремумом предыдущей свечи (лонг: её low, шорт: её high), но не ближе min_stop (в % и/или в ATR);
  pivot — на последнем подтверждённом pivot (старый вариант).
+be_trigger% в нашу сторону → стоп в безубыток (цена входа).
Трейлинг после безубытка (trail_mode): none | pct (экстремум − trail_dist%) | atr (экстремум − trail_dist·ATR) | pivot.
Выход: стоп, либо обратное пересечение (разворот: закрытие и вход в другую сторону).
Внутри одной свечи считаем консервативно: сначала проверяется стоп, потом движение в плюс.

Конструктор правил (все параметры задаются в config, см. DEFAULT_CFG / PANEL):
  entry_mode: cross200 (пересечение EMA20 и EMA200) | close20 (первое закрытие свечи за EMA20 после пересечения) | state20 (любое закрытие за EMA20, когда позиции нет)
  rev_exit: обратный сигнал входа закрывает позицию (разворот)
  stop_mode: prev (за экстремумом предыдущей свечи, не ближе min_stop_pct/min_stop_atr) | pct (фиксированный min_stop_pct) | pivot
  be_trigger (точка перехода в безубыток, %), be_lock (размер безубытка: стоп на вход ± be_lock%)
  trail_mode: none | pct | atr | pivot (после безубытка), trail_dist
  pat_mode: off | exit (паттерн закрывает позицию при плюсе >= pat_min%) | trail (паттерн включает трейлинг под минимумом/максимумом предыдущей свечи, не хуже безубытка)
  sim_from_ms: начать симуляцию «с нуля» с этого момента (для живой бумажной торговли)"""
import classic_analysis as an

PARAMS = dict(tf="15m", be_trigger=1.5, fee=0.05, window_h=240, notional=100.0, warmup=200,
              stop_mode="prev", min_stop_pct=1.5, min_stop_atr=0.0, trail_mode="none", trail_dist=0.0, be_atr=0.0, be_lock=0.3,
              entry_mode="cross200", rev_exit=True, pat_mode="off")

PANEL = dict(PARAMS, be_trigger=1.5, be_lock=0.4, entry_mode="cross200", rev_exit=True, pat_mode="off", pat_min=0.0)  # «рекомендованные» правила конструктора (лучшие по проверке на ZEC 15m; пользователь может менять)


def _last_piv(piv, kind, maxconf, ok):
    for q in reversed(piv):
        if q["k"] == kind and q["conf"] <= maxconf and ok(q["p"]):
            return q["p"]
    return None


def prepare(df, now_ms):
    T = len(df)
    live = T > 0 and df.ct.iloc[-1] > now_ms
    M = T - 1 if live else T
    pre = {"T": T, "M": M, "ok": False}
    if M < 230:
        return pre
    closed = df.iloc[:M].reset_index(drop=True)
    ind = an.indicators(closed)
    pats = an.detect_patterns(closed, ind)
    bu = {p["i"] for p in pats if p["d"] > 0}
    be_ = {p["i"] for p in pats if p["d"] < 0}
    exs = {i: "L" for i in bu - be_}
    exs.update({i: "S" for i in be_ - bu})
    pre.update(ok=True, exits=exs, piv=an.find_pivots(closed), e20=ind["ema20"].values, e200=ind["ema200"].values,
               atr=ind["atr"].values, o=df.o.values, h=df.h.values, l=df.l.values, c=df.c.values, t=df.t.values)
    return pre


def simulate(df, now_ms, P=PARAMS, pre=None, filt=None, sigs=None, exits=None):
    pre = pre or prepare(df, now_ms)
    pm = P.get("pat_mode")
    if pm in (None, "", "off"):
        pm = "exit" if (P.get("pat_exit") or exits is not None) else "off"
    if exits is None and pm in ("exit", "trail") and pre.get("ok"):
        exits = pre["exits"]
    if not pre["ok"] or pre["M"] < P["warmup"] + 30:
        return []
    T, M, piv = pre["T"], pre["M"], pre["piv"]
    e20, e200, atr = pre["e20"], pre["e200"], pre["atr"]
    o, h, l, c, t = pre["o"], pre["h"], pre["l"], pre["c"], pre["t"]
    fee2 = 2 * P["fee"]
    tm, td = P["trail_mode"], P["trail_dist"]
    trades, pos, pend, pexit, arm = [], None, None, False, None

    def finish(i, price, reason):
        nonlocal pos
        s = 1 if pos["side"] == "L" else -1
        gross = s * (price / pos["p_in"] - 1) * 100
        pos.update(i_out=i, t_out=int(t[i]), p_out=float(price), reason=reason, gross=gross, net=gross - fee2, open=False)
        trades.append(pos)
        pos = None

    i0 = 1
    if P.get("sim_from_ms"):
        i0 = max(1, int(t.searchsorted(P["sim_from_ms"])))
    for i in range(i0, T):
        if pexit:
            pexit = False
            if pos:
                sc_ = pos["side"]
                finish(i, o[i], "паттерн")
                if P.get("rearm_k", 0):
                    arm = ("S" if sc_ == "L" else "L", i - 1 + P["rearm_k"])
        if pend:
            (xc, side, allow), pend = pend, None
            if xc and pos and pos["side"] != xc:
                finish(i, o[i], "разворот")
            if pos is None and side and allow:
                entry = float(o[i])
                clamped = False
                if P["stop_mode"] == "pivot":
                    st = _last_piv(piv, "L", i - 1, lambda p: p < entry) if side == "L" else _last_piv(piv, "H", i - 1, lambda p: p > entry)
                elif P["stop_mode"] == "pct":
                    st = entry * (1 - P["min_stop_pct"] / 100) if side == "L" else entry * (1 + P["min_stop_pct"] / 100)
                else:
                    mind = max(entry * P["min_stop_pct"] / 100, P["min_stop_atr"] * atr[i - 1])
                    if side == "L":
                        st = min(l[i - 1], entry - mind); clamped = bool(st != l[i - 1])
                    else:
                        st = max(h[i - 1], entry + mind); clamped = bool(st != h[i - 1])
                if st is not None:
                    pos = dict(side=side, i_in=i, t_in=int(t[i]), p_in=entry, stop0=float(st), stop=float(st), stage="init",
                               risk=abs(entry - st) / entry * 100, mfe=0.0, mae=0.0, be=False, clamped=clamped, ext=entry, ptrail=False,
                               be_thr=(P.get("be_atr", 0) * atr[i - 1] / entry * 100) if P.get("be_atr", 0) else P["be_trigger"])
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
                finish(i, px, {"init": "стоп", "be": "безубыток", "trail": "трейлинг", "ptrail": "трейлинг по паттерну"}[pos["stage"]])
            else:
                pos["mfe"] = max(pos["mfe"], fav)
                pos["ext"] = max(pos["ext"], h[i]) if L_ else min(pos["ext"], l[i])
                if (not pos["be"]) and fav >= pos["be_thr"]:
                    pos["be"], pos["stop"], pos["stage"] = True, e * (1 + (1 if L_ else -1) * P.get("be_lock", 0) / 100), "be"
                if pos["be"] and i < M and tm != "none":
                    if tm == "pivot":
                        if L_:
                            q = _last_piv(piv, "L", i, lambda p: p > pos["stop"] and p < c[i])
                        else:
                            q = _last_piv(piv, "H", i, lambda p: p < pos["stop"] and p > c[i])
                    else:
                        d = pos["ext"] * td / 100 if tm == "pct" else td * atr[i]
                        q = pos["ext"] - d if L_ else pos["ext"] + d
                        if (L_ and not q > pos["stop"]) or ((not L_) and not q < pos["stop"]):
                            q = None
                    if q is not None:
                        pos["stop"], pos["stage"] = float(q), "trail"
                if pm == "trail" and exits is not None and i < M:
                    if exits.get(i) and exits[i] != pos["side"]:
                        pos["ptrail"] = True
                    if pos["ptrail"]:
                        lk = P.get("be_lock", 0) / 100
                        if L_:
                            cand = l[i]; bep = e * (1 + lk)
                            if c[i] > bep: cand = max(cand, bep)
                            if cand > pos["stop"] and cand < c[i]:
                                pos["stop"], pos["stage"] = float(cand), "ptrail"
                        else:
                            cand = h[i]; bep = e * (1 - lk)
                            if c[i] < bep: cand = min(cand, bep)
                            if cand < pos["stop"] and cand > c[i]:
                                pos["stop"], pos["stage"] = float(cand), "ptrail"
        if pm == "exit" and exits is not None and i < M and pos and exits.get(i) and exits[i] != pos["side"]:
            sg_ = 1 if pos["side"] == "L" else -1
            if sg_ * (c[i] / pos["p_in"] - 1) * 100 >= P.get("pat_min", 0):
                pexit = True
        if P["warmup"] <= i < M:
            em = P.get("entry_mode", "cross200")
            if em == "cross200":
                pr, cu = e20[i - 1] - e200[i - 1], e20[i] - e200[i]
            else:
                pr, cu = c[i - 1] - e20[i - 1], c[i] - e20[i]
            xc = "L" if pr <= 0 < cu else "S" if pr >= 0 > cu else None
            en = (xc if sigs is None else sigs.get(i))
            if em == "state20" and sigs is None:
                en = "L" if cu > 0 else "S" if cu < 0 else None
            if arm is not None:
                if i > arm[1]:
                    arm = None
                elif pos is None and ((arm[0] == "L" and c[i] > e20[i]) or (arm[0] == "S" and c[i] < e20[i])):
                    if en is None: en = arm[0]
                    arm = None
            rx = xc if P.get("rev_exit", True) else None
            if rx or en:
                pend = (rx, en, (filt is None) or (en is None) or bool(filt(en, i)))
    if pos:
        s = 1 if pos["side"] == "L" else -1
        gross = s * (c[T - 1] / pos["p_in"] - 1) * 100
        pos.update(i_out=T - 1, t_out=int(t[T - 1]), p_out=float(c[T - 1]), reason="открыта", gross=gross, net=gross - fee2, open=True)
        trades.append(pos)
    return trades


def pack(trades):
    out = []
    for x in trades:
        d = {k: x[k] for k in ("side", "t_in", "t_out", "reason")}
        for k in ("be", "open", "clamped"):
            d[k] = bool(x[k])
        for k in ("p_in", "p_out", "stop0", "stop"):
            d[k] = an._r(float(x[k]))
        for k in ("risk", "gross", "net", "mfe", "mae"):
            d[k] = round(float(x[k]), 3)
        out.append(d)
    return out
