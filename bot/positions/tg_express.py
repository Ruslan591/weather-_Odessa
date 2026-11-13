# -*- coding: utf-8 -*-
"""tg_express.py -- мнение бота («заходить сейчас или ждать») для режима «Экспресс слежение». Только stdlib, без побочных эффектов.
Правила прозрачные (не предсказание): 5 условий по последней закрытой свече у линии канала + 6-е: BTC на 1m не против сделки (tg_btc1m). Вход «по рынку» оценивается по текущей цене закрытия.
Цель берётся из tg_target.choose (статистика дальности отбоя, самообучение); без него - середина канала.
Подключается из tg_bot.py через try/except: удалить файл -> бот работает без мнения."""
try: import tg_target as TG
except Exception: TG = None
try: import tg_review as RV     # пороги с коррекцией по опыту (tg_corr.json); удалить файл -> исходные пороги
except Exception: RV = None
try: import tg_btc1m as B1      # фильтр по BTC 1m (свечи, EMA9, RSI14, блокировки); удалить файл или {"enabled": false} в tg_btc1m.json -> без фильтра
except Exception: B1 = None
try: import tg_regime as RG     # режим рынка BTC 1h: фильтр по течению (RG.cond); удалить файл или tg_regime_cfg.json {"filter": false} -> без фильтра
except Exception: RG = None
import json, os
RSI5_CFG = os.path.join(os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr"), "tg_rsi5.json")
BRKCR_CFG = os.path.join(os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr"), "tg_brk_cr.json")


def _rcfg():
    """Фильтр RSI(14) 5m для ОТБОЯ: шорт только при RSI > short (65, лучше > 70), лонг только при RSI < long (35, лучше < 30). Выключить: POS_DIR/tg_rsi5.json {"enabled": false}; пороги там же."""
    c = {"enabled": True, "short": 65.0, "long": 35.0, "round": False, "brk_short_lo": 38.0, "brk_short_hi": 50.0, "brk_short_no": 35.0, "brk_long_lo": 50.0, "brk_long_hi": 62.0, "brk_long_no": 65.0}
    try: c.update(json.load(open(RSI5_CFG, encoding="utf-8")))
    except Exception: pass
    return c


def _brk_cr_cfg():
    """Фильтр «пробой ПРОТИВ режима рынка BTC 1h» (лонг при падающем, шорт при растущем), разбор #243-251, 2026-11-13: такой пробой берём только сильный и свежий:
    тело последней свечи >= body (0.6 диапазона) и закрытий за линией не больше nmax (5, без погони). Выключить: POS_DIR/tg_brk_cr.json {"enabled": false}; пороги там же."""
    c = {"enabled": True, "body": 0.6, "nmax": 5}
    try: c.update(json.load(open(BRKCR_CFG, encoding="utf-8")))
    except Exception: pass
    return c


def _rsi5_pair(w, kl):
    """(RSI сейчас, RSI на предыдущей закрытой свече) на 5m или (None, None)."""
    L = w.get("last") or {}
    try:
        t = int(L.get("t") or 0); c = float(L.get("c"))
        xs = [float(k[4]) for k in (kl or []) if int(k[0]) < t] + [c]
    except Exception: return None, None
    if len(xs) < 61: return None, None
    return _rsi_xs(xs), _rsi_xs(xs[:-1])


def _rsi5(w, kl, n=14):
    """RSI(14) по Уайлдеру на 5m: закрытия свечей до последней закрытой + её close (w.last.c); None, если свечей мало."""
    L = w.get("last") or {}
    try:
        t = int(L.get("t") or 0); c = float(L.get("c"))
        xs = [float(k[4]) for k in (kl or []) if int(k[0]) < t] + [c]
    except Exception: return None
    if len(xs) < 60: return None
    return _rsi_xs(xs)


def _rsi_xs(xs, n=14):
    xs = xs[-300:]; g = [max(xs[i] - xs[i - 1], 0.0) for i in range(1, len(xs))]; l = [max(xs[i - 1] - xs[i], 0.0) for i in range(1, len(xs))]
    ag = sum(g[:n]) / n; al = sum(l[:n]) / n
    for i in range(n, len(g)): ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _rsi5_cond(side, r, rp=None):
    """ОТБОЙ: SHORT только при RSI 5m > short (65) и RSI закругляется вниз (меньше, чем на предыдущей свече); LONG только при RSI < long (35) и закругляется вверх.
    rp = RSI предыдущей закрытой свечи (None -> закругление не проверяется). Условие (ok, good, bad) или None (выключено / нет данных)."""
    c = _rcfg()
    if r is None or not c.get("enabled", True): return None
    rd = bool(c.get("round", False)) and rp is not None
    if side == "short":
        th = float(c["short"]); rnd = (r < rp) if rd else True
        good = "RSI 5m %.0f: перегрев для шорта (> %g)%s%s" % (r, th, ", сильный" if r > 70 else "", (", закругляется вниз (%.0f → %.0f)" % (rp, r)) if rd else "")
        if r <= th: bad = "RSI 5m %.0f: шорт только при RSI > %g (нет перегрева, цена может пробить канал)" % (r, th)
        else: bad = "RSI 5m %.0f > %g, но ещё не закруглился вниз (%.0f → %.0f): ждём" % (r, th, rp or 0, r)
        return (r > th and rnd, good, bad)
    th = float(c["long"]); rnd = (r > rp) if rd else True
    good = "RSI 5m %.0f: перепродано для лонга (< %g)%s%s" % (r, th, ", сильный" if r < 30 else "", (", закругляется вверх (%.0f → %.0f)" % (rp, r)) if rd else "")
    if r >= th: bad = "RSI 5m %.0f: лонг только при RSI < %g (нет перепроданности, цена может пробить канал)" % (r, th)
    else: bad = "RSI 5m %.0f < %g, но ещё не закруглился вверх (%.0f → %.0f): ждём" % (r, th, rp or 0, r)
    return (r < th and rnd, good, bad)


def _rsi5_brk(side, r):
    """ПРОБОЙ (спецификация 2026-11-11, сделка #225): ловим свежий импульс, нужен запас хода. SHORT (пробой нижней линии): RSI 5m в 38..50, ниже 35 - запрещено;
    LONG (пробой верхней линии): RSI 5m в 50..62, выше 65 - запрещено. Пороги в tg_rsi5.json (brk_short_lo/hi/no, brk_long_lo/hi/no); выключить {"brk": false}."""
    c = _rcfg()
    if r is None or not c.get("enabled", True) or not c.get("brk", True): return None
    if side == "short": lo, hi, no = float(c["brk_short_lo"]), float(c["brk_short_hi"]), float(c["brk_short_no"])
    else: lo, hi, no = float(c["brk_long_lo"]), float(c["brk_long_hi"]), float(c["brk_long_no"])
    if side == "short":
        if r < no: return (False, "", "RSI 5m %.0f уже ниже %g: движение сделано, пробой вниз не торгуем" % (r, no))
    elif r > no: return (False, "", "RSI 5m %.0f уже выше %g: движение сделано, пробой вверх не торгуем" % (r, no))
    ok = lo <= r <= hi
    return (ok, "RSI 5m %.0f в зоне %g-%g: есть запас хода %s" % (r, lo, hi, "вниз" if side == "short" else "вверх"), "RSI 5m %.0f вне зоны %g-%g: нет свежего импульса / нет запаса хода" % (r, lo, hi))


def rsi5_line(w, kl):
    """Строка для постов слежения (не экспресс): RSI 5m (со стрелкой) и допуск по сторонам для отбоя и пробоя; "" если нет данных."""
    r, rp = _rsi5_pair(w, kl)
    if r is None: return ""
    mk = lambda x: "—" if not x else ("✅" if x[0] else "⛔")
    ar = "↘" if r < rp else ("↗" if r > rp else "→")
    return "📈 RSI 5m: %.0f%s | отбой: SHORT %s LONG %s | пробой: SHORT %s LONG %s" % (r, ar, mk(_rsi5_cond("short", r, rp)), mk(_rsi5_cond("long", r, rp)), mk(_rsi5_brk("short", r)), mk(_rsi5_brk("long", r)))


_DEF = {"wick_min": 0.4, "dist_max": 0.9, "rr_add": 0.0, "rr_add_counter": 0.0, "brk_n_min": 2, "brk_body_min": 0.3, "brk_beyond_max": 1.5}


def _C():
    try: return RV.corr() if RV else dict(_DEF)
    except Exception: return dict(_DEF)


def _f(x, d=0.0):
    try: return float(x)
    except Exception: return d


def _fmt(p):
    p = float(p)
    if p >= 1000: return "%.1f" % p
    if p >= 10: return "%.3f" % p
    if p >= 1: return "%.4f" % p
    return "%.5f" % p


def _btc1m(side, setup="bounce"):
    """Условие (ok, good, bad) по BTC 1m для стороны сделки или None, если выключено / нет данных (фильтр тогда не применяется)."""
    if not B1: return None
    try: g = B1.gate(side, setup)
    except Exception: g = None
    return (g["ok"], g["good"], g["bad"], g["snap"]) if g else None


def _regime(side):
    """Условие (ok, good, bad) по режиму рынка 1h или None; и снимок режима для записи."""
    if not RG: return None, None
    try: return RG.cond(side), RG.snap()
    except Exception: return None, None


def verdict(w, kl=None):
    """w: элемент tg_watch.json (слежение). Возвращает {call: enter|wait, text, feat, plan, geo, t, sym, side} или None, если данных нет."""
    L = w.get("last") or {}
    if L.get("Rn") is None or not L.get("atr"): return None
    a = _f(L["atr"]); o, h, l, c = (_f(L[k]) for k in ("o", "h", "l", "c")); R, S = _f(L["Rn"]), _f(L["Sn"]); H = R - S
    if a <= 0 or H <= 0: return None
    up = (w.get("line") or ("upper" if w.get("side") == "short" else "lower")) == "upper"
    s = -1 if up else 1                      # направление отбоя: от нижней линии - вверх (LONG), от верхней - вниз (SHORT)
    line = R if up else S
    st = w.get("state") or w.get("state0") or "touch"; nb = int(w.get("n_beyond") or 0)
    rng = max(h - l, 1e-12)
    dist = (c - line) * s / a                # >0: цена внутри канала от линии, в ATR
    wick = ((min(o, c) - l) if s > 0 else (h - max(o, c))) / rng      # хвост в сторону линии (отбой)
    cpos = ((c - l) if s > 0 else (h - c)) / rng                      # где закрылась: 1 = у дальнего от линии края свечи
    favor = (c - o) * s > 0
    risk = max(1.2 * a, 0.005 * c)
    counter = bool(w.get("counter")); sh = w.get("shift"); C = _C(); need = (1.0 + C["rr_add_counter"]) if counter else (0.8 + C["rr_add"])
    tgt = None
    if TG:
        try: tgt = TG.choose(H / a, counter)
        except Exception: tgt = None
    f = tgt["f"] if tgt else 0.5
    tp = line + s * f * H; opp = (S + 0.1 * a) if s < 0 else (R - 0.1 * a)
    rr_t = (tp - c) * s / risk; rr_opp = (opp - c) * s / risk
    reaction = (favor and cpos >= 0.5 and wick >= max(0.0, C["wick_min"] - 0.4)) or wick >= C["wick_min"]
    ftxt = {0.25: "1/4", 0.33: "1/3", 0.5: "1/2", 0.75: "3/4", 1.0: "линия"}.get(f, "%.2f" % f)
    conds = [
        (st not in ("cross", "break"), "закрытий за линией нет" if st == "touch" else "за линию не закрывались",
         "свеча(и) закрылись за линией: риск пробоя"),
        (-0.15 <= dist <= C["dist_max"], "цена у линии (%+.2f ATR)" % dist, "цена в %.2f ATR от линии: %s" % (dist, "поздно" if dist > C["dist_max"] else "за линией")),
        (reaction, "есть реакция от линии (хвост %d%%)" % round(wick * 100), "реакции от линии пока нет (хвост %d%%)" % round(wick * 100)),
        (rr_t >= need, "до цели %s R:R %.1f" % (ftxt, rr_t), "до цели %s R:R %.1f < %.1f" % (ftxt, rr_t, need)),
        (sh is None or abs(sh) < 0.5, "канал стабилен", "канал перестроился (%+.1f ATR)" % (sh or 0)),
    ]
    b1 = _btc1m("long" if s > 0 else "short", "bounce")
    if b1: conds.append(b1[:3])
    rgc, rgs = _regime("long" if s > 0 else "short")
    if rgc: conds.append(rgc)
    r5, r5p = _rsi5_pair(w, kl); r5c = _rsi5_cond("long" if s > 0 else "short", r5, r5p)
    if r5c: conds.append(r5c)
    call = "enter" if all(x[0] for x in conds) else "wait"
    side = "long" if s > 0 else "short"; stop = c - s * risk
    plan = {"side": side, "entry": c, "stop": stop, "tp": tp, "f": f, "rr": round(rr_t, 2), "rr_opp": round(rr_opp, 2)}
    lines = ["%s %s" % ("✓" if ok else "✗", good if ok else bad) for ok, good, bad in conds]
    if call == "enter":
        head = "🧠 Моё мнение: ✅ можно заходить — %s по рынку ~%s, стоп %s, цель %s (%s канала), R:R %.1f" % (side.upper(), _fmt(c), _fmt(stop), _fmt(tp), ftxt, rr_t)
        if counter: head += "\n⚠️ против тренда канала"
    else:
        why = next(bad for ok, good, bad in conds if not ok)
        head = "🧠 Моё мнение: ⏳ ждём — %s" % why
    text = head + "\n" + "\n".join(lines)
    try: cn = RV.corr_note() if RV else ""
    except Exception: cn = ""
    if cn: text += "\n" + cn
    if tgt: text += "\n🎯 Если заходить: " + tgt["text"] + (" ≈ %s" % _fmt(tp))
    feat = {"dist": round(dist, 3), "wick": round(wick, 3), "cpos": round(cpos, 3), "favor": int(favor), "rr": round(rr_t, 2), "st": st, "counter": int(counter), "width": round(H / a, 2), "nb": nb, "rsi5": None if r5 is None else round(r5, 1)}
    geo = {"line": line, "H": H, "risk": risk, "a": a}
    return {"call": call, "text": text, "feat": feat, "plan": plan, "geo": geo, "t": int(L.get("t") or 0), "sym": w.get("sym"), "side": side, "b1": b1[3] if b1 else None, "rg": rgs}


def verdict_break(w, kl=None):
    """Мнение по ПРОБОЮ линии (для Автоордера): пробой формируется, когда >=2 свечи подряд закрылись за линией (состояние break).
    Дополняет verdict (отбой): у отбоя условие «за линию не закрывались», поэтому вместе они не пересекаются.
    Условия: (1) >=2 закрытия за линией, последняя свеча за линией; (2) не гонимся: цена за линией на 0.2..1.5 ATR; (3) последняя свеча идёт в сторону пробоя (тело >=30% диапазона);
    (4) R:R до цели 0.5 высоты канала за линией >= 1.0; (5) канал не перестроился >=0.5 ATR. Вход по рынку по close, стоп max(1.2 ATR, 0.5%). Пороги начальные.
    Возвращает {call: enter|wait|None, text, plan{side, entry, stop, tp, target}} или None, если пробоя нет (состояние не break)."""
    L = w.get("last") or {}
    if L.get("Rn") is None or not L.get("atr"): return None
    st = w.get("state") or w.get("state0") or "touch"
    if st != "break": return None
    a = _f(L["atr"]); o, h, l, c = (_f(L[k]) for k in ("o", "h", "l", "c")); R, S = _f(L["Rn"]), _f(L["Sn"]); H = R - S; C = _C()
    if a <= 0 or H <= 0: return None
    up = (w.get("line") or ("upper" if w.get("side") == "short" else "lower")) == "upper"
    s = 1 if up else -1                      # направление пробоя: через верхнюю - вверх (LONG), через нижнюю - вниз (SHORT)
    line = R if up else S
    rng = max(h - l, 1e-12); beyond = (c - line) * s / a; body = (c - o) * s / rng
    risk = max(1.2 * a, 0.005 * c); tp = line + s * 0.5 * H; rr = (tp - c) * s / risk; sh = w.get("shift")
    conds = [
        (int(w.get("n_beyond") or 0) >= int(C["brk_n_min"]), "%d закрытия за линией подряд" % int(w.get("n_beyond") or 0), "закрытий за линией меньше %d" % int(C["brk_n_min"])),
        (0.2 <= beyond <= C["brk_beyond_max"], "цена за линией на %.2f ATR" % beyond, "цена за линией на %.2f ATR: %s" % (beyond, "ещё не ушла" if beyond < 0.2 else "уже далеко, в погоню не идём")),
        (body >= C["brk_body_min"], "последняя свеча идёт в сторону пробоя (тело %d%%)" % round(body * 100), "последняя свеча не поддерживает пробой (тело %d%%)" % round(body * 100)),
        (rr >= 1.0, "до цели 0.5 канала R:R %.1f" % rr, "до цели 0.5 канала R:R %.1f < 1.0" % rr),
        (sh is None or abs(sh) < 0.5, "канал стабилен", "канал перестроился (%+.1f ATR)" % (sh or 0)),
    ]
    b1 = _btc1m("long" if s > 0 else "short", "breakout")
    if b1: conds.append(b1[:3])
    rgc, rgs = _regime("long" if s > 0 else "short")
    if rgc: conds.append(rgc)
    r5 = _rsi5(w, kl); r5c = _rsi5_brk("long" if s > 0 else "short", r5)
    if r5c: conds.append(r5c)
    cr = _brk_cr_cfg(); rgm = (rgs or {}).get("regime"); nb_ = int(w.get("n_beyond") or 0); against = bool(rgm) and ((s > 0 and rgm == "down") or (s < 0 and rgm == "up"))
    if cr.get("enabled", True) and against:   # пробой против режима: только сильная свеча и без погони (в разборах такие пробои чаще всего уходили в стоп сразу после входа)
        bmin, nmax = float(cr["body"]), int(cr["nmax"]); okc = body >= bmin and nb_ <= nmax
        if body < bmin: bad = "пробой против режима рынка (%s): тело свечи %d%% < %d%%, слабый импульс" % ("лонг при падающем" if s > 0 else "шорт при растущем", round(body * 100), round(bmin * 100))
        else: bad = "пробой против режима рынка: %d закрытий за линией (> %d), это погоня за ушедшей ценой" % (nb_, nmax)
        conds.append((okc, "пробой против режима рынка, но свежий и сильный: тело %d%%, закрытий за линией %d" % (round(body * 100), nb_), bad))
    call = "enter" if all(x[0] for x in conds) else "wait"
    side = "long" if s > 0 else "short"; stop = c - s * risk
    plan = {"side": side, "entry": c, "stop": stop, "tp": tp, "target": "h05", "rr": round(rr, 2)}
    feat = {"beyond": round(beyond, 3), "body": round(body, 3), "rr": round(rr, 2), "n": int(w.get("n_beyond") or 0), "width": round(H / a, 2), "counter": int(bool(w.get("counter"))), "rsi5": None if r5 is None else round(r5, 1)}
    if against: feat["cr"] = 1
    lines = ["%s %s" % ("✓" if ok else "✗", good if ok else bad) for ok, good, bad in conds]
    if call == "enter": head = "💥 Пробой линии: ✅ можно заходить — %s по рынку ~%s, стоп %s, цель %s (0.5 высоты канала за линией), R:R %.1f" % (side.upper(), _fmt(c), _fmt(stop), _fmt(tp), rr)
    else: head = "💥 Пробой линии формируется: ⏳ ждём — %s" % next(bad for ok, good, bad in conds if not ok)
    return {"call": call, "text": head + "\n" + "\n".join(lines), "plan": plan, "feat": feat, "t": int(L.get("t") or 0), "sym": w.get("sym"), "side": side, "b1": b1[3] if b1 else None, "rg": rgs}
