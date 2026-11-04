# -*- coding: utf-8 -*-
"""Отложенные лимитные заявки Claude (бумага) по правилам пользователя (2026-11-03). Реальных ордеров НЕ ставит.
Правила (5m, каналы classic_trendline: автоканал по двум экстремумам + параллельный клон):
  chan_top    нисходящий канал: ПРОДАЖА лимитом на верхней границе (в следующую свечу), стоп выше на max(1.2 ATR, 0.5%), цель у нижней границы (минус буфер 0.1 ATR).
  chan_bottom восходящий канал: ПОКУПКА лимитом на нижней границе, зеркально.
  retest_up   пробой нисходящего канала вверх (первое закрытие выше верхней линии + 0.2 ATR): ПОКУПКА лимитом на пробитом уровне (прежнее сопротивление:
              максимум 24 свечей до пробоя, иначе сама линия), стоп ниже уровня на max(1.2 ATR, 0.5%), цель = уровень + max(высота канала, 2 риска).
  retest_down зеркально: пробой восходящего канала вниз, ПРОДАЖА на пробитой поддержке.
Заявка живёт 12 свечей (пробой: 24); на каждой закрытой свече пересчитывается: цена изменилась больше чем на 0.15 ATR или условия исчезли -> отмена и новая заявка.
Исполнение: сквозь уровень (low < цена для покупки, high > цена для продажи) по минутным свечам; мейкер 0.02% на входе и на цели, стоп - тейкер (как в pos.py).
Слоты: пока открыто SLOTS позиций, новые заявки не ставятся, а когда исполнилась заявка и слоты заполнились - остальные отменяются.
Команды: scan [--dry] | loop | list. Данные: orders.json (POS_DIR). Позиции создаются в positions.json через pos.py (поля src=chan, fee_in, fee_tp)."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pos
D = pos.D; OF = os.path.join(D, "orders.json"); LOG = os.path.join(D, "chan.log"); STF = os.path.join(D, "chan_state.json")
CLASSIC = os.environ.get("CLASSIC_DIR", "/opt/trading-bot/classic")
PAIRS = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT APT ATOM PHA ZEC NEAR TREE ANIME IOST REZ NIL HAEDAL".split()
TFM = 300000; MAK = 0.02
STOP_ATR = 1.2; MIN_RISK = 0.5; TPBUF = 0.1
VALID_A = 12; VALID_B = 24; MAXPEND = 8; SLOTS = 3; MAXH = 24
DIST_A = (0.0, 3.0); DIST_B = (0.3, 4.0); KEEP_ATR = 0.15
RULE_RU = {"chan_top": "нисходящий канал: продажа на верхней границе", "chan_bottom": "восходящий канал: покупка на нижней границе",
           "retest_up": "пробой нисходящего канала вверх: покупка на ретесте пробитого уровня", "retest_down": "пробой восходящего канала вниз: продажа на ретесте пробитого уровня"}
STATUS_RU = {"pending": "активна", "filled": "исполнена", "cancelled": "отменена", "expired": "истекла"}

def log(m):
    with open(LOG, "a", encoding="utf-8") as f: f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S", time.gmtime()), m))
def load_orders():
    try: return json.load(open(OF, encoding="utf-8"))
    except Exception: return []
def save_orders(o):
    tmp = OF + ".tmp"; json.dump(o, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, OF)
def load_state():
    try: return json.load(open(STF))
    except Exception: return {"last": {}}
def save_state(s):
    tmp = STF + ".tmp"; json.dump(s, open(tmp, "w")); os.replace(tmp, STF)

def analyze(sym, now):
    import numpy as np
    if CLASSIC not in sys.path: sys.path.insert(0, CLASSIC)
    import classic_trendline as tl
    d = [k for k in pos.kl(sym + "USDT", "5m", 500) if int(k[0]) + TFM <= now]; M = len(d)
    if M < 220: return None
    t = [int(k[0]) for k in d]; o = np.array([float(k[1]) for k in d]); h = np.array([float(k[2]) for k in d]); l = np.array([float(k[3]) for k in d]); c = np.array([float(k[4]) for k in d])
    atr = np.zeros(M); a = None
    for i in range(1, M):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])); a = tr if a is None else a + (tr - a) / 14; atr[i] = a
    hh, ll = tl.anchor_series(o, h, l, c); piv = tl.pivots(hh, ll)
    lows = [q for q in piv if q["k"] == "L"]; highs = [q for q in piv if q["k"] == "H"]
    def st_at(i): return tl.structure_at(hh, ll, c, atr, i, [q for q in lows if q["conf"] <= i][-8:], [q for q in highs if q["conf"] <= i][-8:])
    return dict(t=t, o=o, h=h, l=l, c=c, atr=atr, M=M, st_at=st_at, tl=tl)

def ldict(ln, t):
    i1 = int(ln[0]); return {"t1": t[i1], "p1": float(ln[1]), "s": float(ln[4]) / TFM}
def mk(sym, rule, side, price, stop, tp, a, t_placed, valid, chan, level=None, key=None, ctype="", **extra):
    o = dict(sym=sym, rule=rule, side=side, price=float(price), stop=float(stop), tp=float(tp), atr=float(a), tf="5m", placed_t=int(t_placed),
             expire_t=int(t_placed + valid * TFM), status="pending", chan=chan, level=level, key=key, ctype=ctype, checked_t=int(t_placed - 60000))
    o.update(extra); return o
def tok(ms): return "@@%d@@" % ms
def P(x): return "%.5g" % x
def basis_of(A, st, i):
    """Из чего построен канал: две опорные вершины главной линии, третья точка (параллельная линия), число касаний, ширина в ATR."""
    import numpy as np
    ch = st.get("channel")
    if not ch or ch["kind"] not in ("down", "up"): return None
    t = A["t"]; h = A["h"]; l = A["l"]; kind = ch["kind"]
    main = ch["upper"] if kind == "down" else ch["lower"]; i1, p1, i2, p2, s_ = main
    idx = np.arange(i1, i2 + 1); mp = p1 + s_ * (idx - i1)
    if kind == "down": k = int(np.argmax(mp - l[i1:i2 + 1])); third = (t[i1 + k], float(l[i1 + k]), "L3"); names = ("H1", "H2")
    else: k = int(np.argmax(h[i1:i2 + 1] - mp)); third = (t[i1 + k], float(h[i1 + k]), "H3"); names = ("L1", "L2")
    return {"kind": kind, "main": "upper" if kind == "down" else "lower",
            "anchors": [{"t": t[i1], "p": float(p1), "n": names[0]}, {"t": t[i2], "p": float(p2), "n": names[1]}], "third": {"t": third[0], "p": third[1], "n": third[2]},
            "touch_main": int(ch["t_main"]), "touch_clone": int(ch["t_clone"]), "width_atr": round(float(ch["width"]), 2), "score": round(float(ch["score"]), 1)}
def chan_text(b):
    n1, n2 = b["anchors"]; th = b["third"]
    return "%s канал на 5m: главная линия (%s) по точкам %s %s (%s) и %s %s (%s), параллельная линия через %s %s (%s). Ширина %.1f ATR, касаний главной линии %d, параллельной %d." % (
        "Нисходящий" if b["kind"] == "down" else "Восходящий", "верхняя" if b["main"] == "upper" else "нижняя", n1["n"], tok(n1["t"]), P(n1["p"]), n2["n"], tok(n2["t"]), P(n2["p"]),
        th["n"], tok(th["t"]), P(th["p"]), b["width_atr"], b["touch_main"], b["touch_clone"])
def risk_text(a, price, risk, stop, side):
    by = "1.2 ATR(5m) = %s" % P(STOP_ATR * a) if STOP_ATR * a >= MIN_RISK / 100 * price else "0.5%% цены = %s" % P(MIN_RISK / 100 * price)
    return "Стоп %s уровня на max(1.2 ATR, 0.5%% цены): взято %s, стоп %s (риск %.2f%%)." % ("выше" if side == "short" else "ниже", by, P(stop), risk / price * 100)

def propose(sym, A):
    out = []; M = A["M"]; i = M - 1; t = A["t"]; c = A["c"]; h = A["h"]; l = A["l"]; tl = A["tl"]; a = float(A["atr"][i])
    if a <= 0: return out
    tp_ = t[i] + TFM
    st = A["st_at"](i)
    if st and st["type"] in ("channel_down", "channel_up") and st.get("lower") and st.get("upper"):
        S, R = st["lower"], st["upper"]; Sn = float(tl.at(S, i + 1)); Rn = float(tl.at(R, i + 1)); b = basis_of(A, st, i)
        if (Rn - Sn) >= 1.5 * a and b:
            ch = {"type": st["type"], "upper": ldict(R, t), "lower": ldict(S, t)}
            down = st["type"] == "channel_down"
            price = Rn if down else Sn; dist = abs(price - float(c[i])) / a; risk = max(STOP_ATR * a, MIN_RISK / 100 * price)
            stop = price + risk if down else price - risk; tp = (Sn + TPBUF * a) if down else (Rn - TPBUF * a)
            good = (price - tp >= risk) if down else (tp - price >= risk)
            ok_side = (price >= float(c[i])) if down else (price <= float(c[i]))
            if DIST_A[0] <= dist <= DIST_A[1] and good and ok_side:
                why = [chan_text(b),
                       "Цена сейчас %s, до %s границы канала %.1f ATR; лимит %s стоит на границе, спроецированной на следующую свечу: %s (ATR 5m = %s)." % (P(float(c[i])), "верхней" if down else "нижней", dist, "продажи" if down else "покупки", P(price), P(a)),
                       risk_text(a, price, risk, stop, "short" if down else "long"),
                       "Цель = %s граница канала на следующей свече %s 0.1 ATR = %s; соотношение цель/риск %.1f." % ("нижняя" if down else "верхняя", "плюс" if down else "минус", P(tp), abs(price - tp) / risk),
                       "Заявка живёт %d свечей (до %s). На каждой закрытой свече пересчёт: граница сместилась больше чем на 0.15 ATR или условия исчезли - отмена и новая заявка." % (VALID_A, tok(tp_ + (VALID_A - 1) * TFM))]
                out.append(mk(sym, "chan_top" if down else "chan_bottom", "short" if down else "long", price, stop, tp, a, tp_, VALID_A, ch, ctype=st["type"], basis=b, why=why, atr_c=float(c[i])))
    st1 = A["st_at"](i - 1)
    if st1 and st1.get("lower") and st1.get("upper") and st1["type"] in ("channel_down", "channel_up"):
        Ri = float(tl.at(st1["upper"], i)); Rp = float(tl.at(st1["upper"], i - 1)); Si = float(tl.at(st1["lower"], i)); Sp = float(tl.at(st1["lower"], i - 1))
        ch = {"type": st1["type"], "upper": ldict(st1["upper"], t), "lower": ldict(st1["lower"], t)}; b = basis_of(A, st1, i - 1)
        up = st1["type"] == "channel_down" and c[i] > Ri + 0.2 * a and c[i - 1] <= Rp + 0.2 * a
        dn = st1["type"] == "channel_up" and c[i] < Si - 0.2 * a and c[i - 1] >= Sp - 0.2 * a
        if (up or dn) and b:
            if up:
                ext = int(i - 24 + int(h[i - 24:i].argmax())); level = float(h[ext]); src = "максимум 24 свечей до пробоя"
                if level > c[i] - 0.3 * a: level = Ri; src = "сама линия канала (максимум окна слишком близко к цене)"
                dist = (float(c[i]) - level) / a; line = Ri
            else:
                ext = int(i - 24 + int(l[i - 24:i].argmin())); level = float(l[ext]); src = "минимум 24 свечей до пробоя"
                if level < c[i] + 0.3 * a: level = Si; src = "сама линия канала (минимум окна слишком близко к цене)"
                dist = (level - float(c[i])) / a; line = Si
            risk = max(STOP_ATR * a, MIN_RISK / 100 * level); width = Ri - Si
            if DIST_B[0] <= dist <= DIST_B[1]:
                side = "long" if up else "short"; stop = level - risk if up else level + risk; move = max(width, 2 * risk); tp = level + move if up else level - move
                lv = {"p": level, "t_from": t[i - 24], "t_to": t[i - 1], "t_ext": t[ext], "src": src}
                bo = {"t": t[i], "close": float(c[i]), "line": line, "dir": "up" if up else "down"}
                why = [chan_text(b),
                       "Пробой: свеча %s закрылась на %s %s границы канала (%s) больше чем на 0.2 ATR; предыдущая свеча была внутри канала." % (tok(t[i]), P(float(c[i])), "выше верхней" if up else "ниже нижней", P(line)),
                       "Уровень: %s (окно %s - %s) = %s. %s." % (src, tok(t[i - 24]), tok(t[i - 1]), P(level), "Бывшее сопротивление становится поддержкой" if up else "Бывшая поддержка становится сопротивлением"),
                       "Цена %s уровня на %.1f ATR; лимит %s ждёт возврата (ретеста) на уровень %s." % ("выше" if up else "ниже", dist, "покупки" if up else "продажи", P(level)),
                       risk_text(a, level, risk, stop, side),
                       "Цель = уровень %s max(высота канала %s, 2 риска %s) = %s." % ("плюс" if up else "минус", P(width), P(2 * risk), P(tp)),
                       "Заявка живёт %d свечей (до %s). Отмена, если свеча закроется %s уровня на 0.7 ATR (пробой не удержался)." % (VALID_B, tok(tp_ + (VALID_B - 1) * TFM), "ниже" if up else "выше")]
                out.append(mk(sym, "retest_up" if up else "retest_down", side, level, stop, tp, a, tp_, VALID_B, ch, lv, key="%s|%s|%d" % (sym, "retest_up" if up else "retest_down", t[i]),
                              ctype=st1["type"], basis=b, why=why, breakout=bo))
    return out

def cycle(dry=False):
    now = int(time.time() * 1000); stt = load_state(); props = {}; closes = {}
    for sym in PAIRS:
        try:
            A = analyze(sym, now)
            if not A: continue
            ti = A["t"][A["M"] - 1]; closes[sym] = (float(A["c"][A["M"] - 1]), float(A["atr"][A["M"] - 1]), ti)
            if stt["last"].get(sym) == ti: continue
            props[sym] = (ti, propose(sym, A))
        except Exception as e:
            log("scan %s error: %s" % (sym, e))
    # fills for pending orders (no lock while fetching)
    pend = [o for o in load_orders() if o["status"] == "pending"]; fills = {}; expired = []
    for o in pend:
        try:
            d = pos.kl(o["sym"] + "USDT", "1m", 1000, o["checked_t"] + 60000); d = [k for k in d if int(k[0]) + 60000 <= now]
            last = o["checked_t"]
            for k in d:
                ot = int(k[0])
                if ot >= o["expire_t"]: expired.append((o["id"], o["expire_t"])); break
                if ot < o["placed_t"]: continue
                op, hi, lo = float(k[1]), float(k[2]), float(k[3]); last = ot
                if (o["side"] == "long" and lo < o["price"]) or (o["side"] == "short" and hi > o["price"]):
                    fills[o["id"]] = (ot, min(o["price"], op) if o["side"] == "long" else max(o["price"], op)); break
            o["_last"] = last
        except Exception as e:
            log("fill-check %s error: %s" % (o["sym"], e))
    at1 = {}
    for oid in fills:
        o = next(x for x in pend if x["id"] == oid)
        try: at1[oid] = pos.atr1h(o["sym"] + "USDT")
        except Exception: at1[oid] = o["atr"] * 3.46
    if dry:
        for sym, (ti, ps) in props.items():
            for p in ps: print("PROPOSAL", sym, p["rule"], p["side"], "price %.6g stop %.6g tp %.6g dist_atr %.2f" % (p["price"], p["stop"], p["tp"], abs(p["price"] - closes[sym][0]) / closes[sym][1]))
        print("pairs scanned %d, with proposals %d, pending %d" % (len(closes), sum(1 for v in props.values() if v[1]), len(pend))); return
    with pos.lock():
        orders = load_orders(); ps_ = pos.load(); by_id = {o["id"]: o for o in orders}
        def n_open(): return sum(1 for p in ps_ if p["status"] == "open")
        def cancel(o, why, t=None): o.update(status="cancelled", reason=why, t_end=t or now)
        for o in pend:  # update checked_t
            cur = by_id.get(o["id"])
            if cur and cur["status"] == "pending" and "_last" in o: cur["checked_t"] = max(cur["checked_t"], o["_last"])
        for oid, et in expired:
            cur = by_id.get(oid)
            if cur and cur["status"] == "pending": cur.update(status="expired", reason="время жизни заявки истекло", t_end=et)
        for oid, (ft, fp) in sorted(fills.items(), key=lambda kv: kv[1][0]):  # earlier fill first
            o = by_id.get(oid)
            if not o or o["status"] != "pending": continue
            sym = o["sym"] + "USDT"
            if any(p["status"] == "open" and p["sym"] == sym for p in ps_): cancel(o, "по паре уже есть позиция", ft); continue
            if n_open() >= SLOTS: cancel(o, "слоты заняты", ft); continue
            side = 1 if o["side"] == "long" else -1; R = abs(fp - o["stop"])
            if R <= 0 or (side > 0 and o["stop"] >= fp) or (side < 0 and o["stop"] <= fp): cancel(o, "стоп по ту сторону входа", ft); continue
            a1 = at1.get(oid, o["atr"] * 3.46)
            th = "Лимит %s %s по правилу «%s», выставлен %s UTC на %.6g, исполнен %s UTC (сквозь уровень)." % (o["side"], o["sym"], RULE_RU[o["rule"]], pos.tstr(o["placed_t"]), o["price"], pos.tstr(ft))
            p = {"id": max([x["id"] for x in ps_] + [0]) + 1, "sym": sym, "side": o["side"], "t_in": ft, "entry": fp, "px_signal": o["price"], "stop0": o["stop"], "stop": o["stop"], "tp": o["tp"],
                 "R": R, "R_pct": R / fp * 100, "be_r": 1.0, "lock_pct": 0.2, "be_px": fp + side * R, "lock_px": fp * (1 + side * 0.2 / 100), "armed": False,
                 "trail_dist": 1.5 * a1, "atr1h": a1, "max_h": MAXH, "stake": pos.STAKE, "lev": pos.LEV, "thesis": th, "last_t": (ft // 60000) * 60000, "hi": fp, "lo": fp, "status": "open",
                 "src": "chan", "order_id": o["id"], "rule": o["rule"], "placed_t": o["placed_t"], "fee_in": MAK, "fee_tp": MAK}
            ps_.append(p); o.update(status="filled", fill_t=ft, fill_px=fp, pos_id=p["id"], t_end=ft)
            log("FILLED order %d %s %s %.6g -> position #%d" % (o["id"], o["sym"], o["side"], fp, p["id"]))
            if n_open() >= SLOTS:
                for x in orders:
                    if x["status"] == "pending" and x["id"] != o["id"]: cancel(x, "слоты заняты: исполнилась заявка %s" % o["sym"], ft)
        pos.save(ps_)
        pend_now = [x for x in orders if x["status"] == "pending"]
        for sym, (ti, props_) in props.items():
            c0, a0, _ = closes[sym]; stt["last"][sym] = ti
            cur_o = [x for x in pend_now if x["sym"] == sym]
            for x in cur_o:  # failed retest / channel gone
                if x["rule"] in ("retest_up", "retest_down"):
                    lv = x["level"]["p"]
                    if (x["side"] == "long" and c0 < lv - 0.7 * a0) or (x["side"] == "short" and c0 > lv + 0.7 * a0): cancel(x, "пробой не удержался (закрытие за уровнем)", ti + TFM)
            pend_sym = [x for x in orders if x["status"] == "pending" and x["sym"] == sym]
            for p in props_:
                if p["key"] and any(x.get("key") == p["key"] for x in orders): continue  # событие пробоя уже обработано
                same = [x for x in pend_sym if x["rule"] == p["rule"] and x["side"] == p["side"]]
                if same and abs(same[0]["price"] - p["price"]) <= KEEP_ATR * a0: continue
                for x in same: cancel(x, "пересчёт: граница сместилась", ti + TFM)
                if n_open() >= SLOTS or sum(1 for x in orders if x["status"] == "pending") >= MAXPEND: continue
                if any(pp["status"] == "open" and pp["sym"] == sym + "USDT" for pp in ps_): continue
                p["id"] = max([x["id"] for x in orders] + [0]) + 1; orders.append(p); pend_sym.append(p)
                log("PLACED order %d %s %s %s %.6g stop %.6g tp %.6g" % (p["id"], sym, p["rule"], p["side"], p["price"], p["stop"], p["tp"]))
            for x in [x for x in pend_sym if x["status"] == "pending" and x["rule"] in ("chan_top", "chan_bottom") and not any(pp["rule"] == x["rule"] and pp["side"] == x["side"] for pp in props_)]:
                cancel(x, "условия исчезли (канал, расстояние или цель)", ti + TFM)
        # слоты заполнены: лишние заявки не держим
        if n_open() >= SLOTS:
            for x in orders:
                if x["status"] == "pending": cancel(x, "слоты заняты")
        save_orders(orders); save_state(stt)

def pair_view(sym):
    """Разметка сканера по паре (без заявки): что бот видит на 5m - канал, опорные точки, линии."""
    sym = (sym or "").upper().replace("USDT", "")
    if sym not in PAIRS: return {"error": "пара не из списка сканера"}
    now = int(time.time() * 1000); A = analyze(sym, now)
    if not A: return {"error": "мало данных по паре"}
    i = A["M"] - 1; t = A["t"]; st = A["st_at"](i); lo = max(0, A["M"] - 300)
    cand = [[t[j], float(A["o"][j]), float(A["h"][j]), float(A["l"][j]), float(A["c"][j])] for j in range(lo, A["M"])]
    chan = None; b = None; typ = st["type"] if st else "none"
    if st and st.get("upper") and st.get("lower"):
        chan = {"type": typ, "upper": ldict(st["upper"], t), "lower": ldict(st["lower"], t)}; b = basis_of(A, st, i)
    txt = {"channel_down": "нисходящий канал", "channel_up": "восходящий канал", "range": "боковой диапазон", "none": "ничего не найдено", "other": "отдельные линии S/R без канала"}.get(typ, typ)
    why = [chan_text(b)] if b else ["Тип разметки: %s." % txt]
    return {"sym": sym, "type": typ, "type_ru": txt, "cand": cand, "chan": chan, "basis": b, "why": why, "px": float(A["c"][i]), "atr": float(A["atr"][i]), "ts": now, "rule_ru": "разметка сканера: " + txt}

_cache = {}
def _cand(sym):
    t = time.time(); c = _cache.get(sym)
    if c and t - c[0] < 20: return c[1]
    d = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in pos.kl(sym + "USDT", "5m", 300)]; _cache[sym] = (t, d); return d
def orders_view():
    os_ = load_orders(); now = int(time.time() * 1000); pend = []; rec = []
    for o in os_:
        if o["status"] == "pending":
            q = dict(o); cand = _cand(o["sym"]); q["cand"] = cand; px = cand[-1][4]; q["px"] = px
            q["risk_pct"] = abs(o["price"] - o["stop"]) / o["price"] * 100; q["dist_pct"] = abs(o["price"] - px) / px * 100; q["rule_ru"] = RULE_RU.get(o["rule"], o["rule"]); pend.append(q)
        else:
            q = {k: o.get(k) for k in ("id", "sym", "side", "rule", "price", "placed_t", "t_end", "status", "reason", "pos_id")}; q["status_ru"] = STATUS_RU.get(o["status"], o["status"]); rec.append(q)
    rec.sort(key=lambda x: -(x.get("t_end") or 0)); pend.sort(key=lambda x: x["dist_pct"])
    return {"pending": pend, "recent": rec[:12], "pairs": PAIRS, "ts": now}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "scan": cycle(dry="--dry" in sys.argv)
    elif cmd == "loop":
        while True:
            try: cycle()
            except Exception as e: log("cycle error: %s" % e)
            time.sleep(20)
    else:
        for o in load_orders(): print(o["id"], o["sym"], o["rule"], o["side"], "%.6g" % o["price"], o["status"], pos.tstr(o["placed_t"]), o.get("reason", ""))
