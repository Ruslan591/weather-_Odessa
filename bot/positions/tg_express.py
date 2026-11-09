# -*- coding: utf-8 -*-
"""tg_express.py -- мнение бота («заходить сейчас или ждать») для режима «Экспресс слежение». Только stdlib, без побочных эффектов.
Правила прозрачные (не предсказание): 5 условий по последней закрытой свече у линии канала. Вход «по рынку» оценивается по текущей цене закрытия.
Подключается из tg_bot.py через try/except: удалить файл -> бот работает без мнения."""


def _f(x, d=0.0):
    try: return float(x)
    except Exception: return d


def _fmt(p):
    p = float(p)
    if p >= 1000: return "%.1f" % p
    if p >= 10: return "%.3f" % p
    if p >= 1: return "%.4f" % p
    return "%.5f" % p


def verdict(w, kl=None):
    """w: элемент tg_watch.json (слежение). Возвращает {call: enter|wait, text, feat, plan, t} или None, если данных нет."""
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
    mid = S + 0.5 * H; opp = (S + 0.1 * a) if s < 0 else (R - 0.1 * a)
    rr_mid = (mid - c) * s / risk; rr_opp = (opp - c) * s / risk
    counter = bool(w.get("counter")); sh = w.get("shift"); need = 1.5 if counter else 1.2
    reaction = (favor and cpos >= 0.5) or wick >= 0.4
    conds = [
        (st in ("touch", "back"), "закрытий за линией нет" if st == "touch" else "выходила за линию и вернулась",
         "свеча(и) закрылись за линией: риск пробоя" if st in ("cross", "break") else "цена ушла от линии"),
        (-0.15 <= dist <= 0.9, "цена у линии (%+.2f ATR)" % dist, "цена в %.2f ATR от линии: %s" % (dist, "поздно" if dist > 0.9 else "за линией")),
        (reaction, "есть реакция от линии (хвост %d%%)" % round(wick * 100), "реакции от линии пока нет (хвост %d%%)" % round(wick * 100)),
        (rr_mid >= need, "до середины канала R:R %.1f" % rr_mid, "до середины канала R:R %.1f < %.1f" % (rr_mid, need)),
        (sh is None or abs(sh) < 0.5, "канал стабилен", "канал перестроился (%+.1f ATR)" % (sh or 0)),
    ]
    call = "enter" if all(x[0] for x in conds) else "wait"
    side = "long" if s > 0 else "short"; stop = c - s * risk
    plan = {"side": side, "entry": c, "stop": stop, "tp": mid, "rr": round(rr_mid, 2), "rr_opp": round(rr_opp, 2)}
    lines = ["%s %s" % ("✓" if ok else "✗", good if ok else bad) for ok, good, bad in conds]
    if call == "enter":
        head = "🧠 Моё мнение: ✅ можно заходить — %s по рынку ~%s, стоп %s, цель (середина) %s, R:R %.1f" % (side.upper(), _fmt(c), _fmt(stop), _fmt(mid), rr_mid)
        if counter: head += "\n⚠️ против тренда канала: цель консервативная"
    else:
        why = next(bad for ok, good, bad in conds if not ok)
        head = "🧠 Моё мнение: ⏳ ждём — %s" % why
    feat = {"dist": round(dist, 3), "wick": round(wick, 3), "cpos": round(cpos, 3), "favor": int(favor), "rr": round(rr_mid, 2), "st": st, "counter": int(counter), "width": round(H / a, 2), "nb": nb}
    return {"call": call, "text": head + "\n" + "\n".join(lines), "feat": feat, "plan": plan, "t": int(L.get("t") or 0), "sym": w.get("sym"), "side": side}
