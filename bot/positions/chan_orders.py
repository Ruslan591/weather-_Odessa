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
ИЗМЕНЕНИЕ 2026-11-04 (docs/topics/chan_orders.md, «Первоочередные задачи»): chan_top/chan_bottom ВЫКЛЮЧЕНЫ флагом CHAN_EDGE (по умолчанию 0, env CHAN_EDGE=1 включает), код сохранён.
Ретест теперь с подтверждением (путь Б): пробой границы канала -> только наблюдение (chan_events.json) -> возврат к пробитому уровню (касание) -> N=2 свечи подряд без закрытия за уровнем (допуск 0.2 ATR) -> лимит на уровне. Закрытие за уровнем = ложный пробой, сделки нет.
Задача 1 «тень»: в каждую заявку пишется снимок тренда (trend_shadow.py), правила от него не зависят. Отчёт по группам: python chan_orders.py report.
v3 (2026-11-05): уровень только структурный; отход от уровня >= 1 ATR и касание не раньше чем через 2 свечи; тень за уровнем > 1 ATR = ложный пробой; закрытие за уровнем ДО возврата = ложный пробой; заявки rv=3.
Команды: scan [--dry] | loop | list | report. Данные: orders.json (POS_DIR). Позиции создаются в positions.json через pos.py (поля src=chan, fee_in, fee_tp)."""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pos, trend_shadow
D = pos.D; OF = os.path.join(D, "orders.json"); LOG = os.path.join(D, "chan.log"); STF = os.path.join(D, "chan_state.json")
EVF = os.path.join(D, "chan_events.json")
CLASSIC = os.environ.get("CLASSIC_DIR", "/opt/trading-bot/classic")
PAIRS = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT APT ATOM PHA ZEC NEAR TREE ANIME IOST REZ NIL HAEDAL".split()
TFM = 300000; MAK = 0.02
STOP_ATR = 1.2; MIN_RISK = 0.5; TPBUF = 0.1
VALID_A = 12; VALID_B = 24; MAXPEND = 8; SLOTS = 3; MAXH = 24
DIST_A = (0.0, 3.0); DIST_B = (0.3, 4.0); KEEP_ATR = 0.15
# ретест с подтверждением (допущения на проверку пользователю, см. doc): N свечей, допуски в ATR на момент пробоя
CHAN_EDGE = os.environ.get("CHAN_EDGE", "0") == "1"   # chan_top / chan_bottom (лимит у границы заранее): выключены
# v3 (2026-11-05, решение пользователя "правки 1-3 да"): настоящий возврат, структурный уровень, предел тени. Серия rv=3 отдельно от rv=2.
CFGF = os.path.join(pos.D, "chan_cfg.json")
def struct_only():
    """Переключатель правки 2 (уровень только экстремум 24 свечей, наклонная линия канала не считается). По умолчанию ВЫКЛ (решение пользователя 2026-11-05). Читается каждый цикл из chan_cfg.json; команда: chan_orders.py cfg struct_only 1|0"""
    try: return bool(json.load(open(CFGF)).get("struct_only", 0))
    except Exception: return False
DEP_ATR = 1.0; MIN_GAP = 2; WICK_ATR = 1.0; RV = 3        # отход от уровня >= 1 ATR, касание не раньше чем через 2 свечи после пробоя, тень за уровнем <= 1 ATR
CONFIRM_N = 2; TOUCH_ATR = 0.2; TOL_ATR = 0.2; AWAY_ATR = 0.5; ENTRY_OFF = 0.1; STOP_PAD = 0.5; VALID_C = 12
RULE_RU = {"chan_top": "нисходящий канал: продажа на верхней границе", "chan_bottom": "восходящий канал: покупка на нижней границе",
           "retest_up": "пробой нисходящего канала вверх, возврат к уровню и подтверждение удержания: покупка у уровня", "retest_down": "пробой восходящего канала вниз, возврат к уровню и подтверждение удержания: продажа у уровня"}
STATUS_RU = {"pending": "активна", "filled": "исполнена", "cancelled": "отменена", "expired": "истекла"}

def log(m):
    with open(LOG, "a", encoding="utf-8") as f: f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S", time.gmtime()), m))
def load_orders():
    try: return json.load(open(OF, encoding="utf-8"))
    except Exception: return []
def save_orders(o):
    tmp = OF + ".tmp"; json.dump(o, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, OF)
def load_events():
    try: return json.load(open(EVF, encoding="utf-8"))
    except Exception: return []
def save_events(ev):
    now = int(time.time() * 1000); ev = [e for e in ev if e["status"] == "watch" or now - e.get("t_end", e["created_t"]) < 3 * 86400000][-300:]
    tmp = EVF + ".tmp"; json.dump(ev, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, EVF)
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

def propose(sym, A, evs):
    out = []; M = A["M"]; i = M - 1; t = A["t"]; c = A["c"]; h = A["h"]; l = A["l"]; tl = A["tl"]; a = float(A["atr"][i])
    if a <= 0: return out
    tp_ = t[i] + TFM
    st = A["st_at"](i)
    if CHAN_EDGE and st and st["type"] in ("channel_down", "channel_up") and st.get("lower") and st.get("upper"):
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
            ev_key = "%s|%s|%d" % (sym, "up" if up else "down", t[i])
            struct = not src.startswith("сама линия")
            if struct_only() and not struct and DIST_B[0] <= dist <= DIST_B[1] and not any(e["key"] == ev_key for e in evs):
                log("SKIP пробой %s %s: пробита только линия канала, экстремум 24 свечей не пробит (struct_only)" % (sym, "вверх" if up else "вниз"))
            if DIST_B[0] <= dist <= DIST_B[1] and (struct or not struct_only()) and not any(e["key"] == ev_key for e in evs):
                lv = {"p": level, "t_from": t[i - 24], "t_to": t[i - 1], "t_ext": t[ext], "src": src}
                bo = {"t": t[i], "close": float(c[i]), "line": line, "dir": "up" if up else "down"}
                evs.append(dict(key=ev_key, sym=sym, dir="up" if up else "down", level=level, t_break=int(t[i]), line=line, width=float(width), chan=ch, basis=b, lv=lv, bo=bo,
                                src=src, atr_b=a, ctype=st1["type"], status="watch", created_t=int(t[i]) + TFM))
                log("EVENT пробой %s %s уровень %.6g (линия %.6g) - наблюдаем, заявки нет" % (sym, "вверх" if up else "вниз", level, line))
    return out

def eval_events(sym, A, evs):
    """Путь Б: наблюдаемый пробой -> касание пробитого уровня -> N свечей без закрытия за уровнем -> заявка (иначе ложный пробой)."""
    out = []; t = A["t"]; c = A["c"]; h = A["h"]; l = A["l"]; M = A["M"]; i = M - 1; a = float(A["atr"][i])
    for e in evs:
        if e["sym"] != sym or e["status"] != "watch": continue
        tend = int(t[i]) + TFM
        try: jb = t.index(e["t_break"])
        except ValueError: e.update(status="expired", reason="пробой вне окна истории", t_end=tend); continue
        up = e["dir"] == "up"; lv = e["level"]; ab = e["atr_b"]
        if struct_only() and str(e.get("src", "")).startswith("сама линия"): e.update(status="expired", reason="v3: уровень - наклонная линия канала, не структура", t_end=tend); continue
        jt = None; dead = False
        for j in range(jb + 1, i + 1):
            if (up and c[j] < lv - TOL_ATR * ab) or ((not up) and c[j] > lv + TOL_ATR * ab):   # провал до возврата
                e.update(status="false", reason="ложный пробой: свеча %s закрылась за уровнем до возврата" % pos.tstr(t[j]), t_end=tend); dead = True; break
            dep = ((max(h[jb:j]) - lv) if up else (lv - min(l[jb:j]))) / ab   # как далеко уходила цена от уровня после пробоя (с самой свечой пробоя)
            if j - jb >= MIN_GAP and dep >= DEP_ATR and ((up and l[j] <= lv + TOUCH_ATR * ab) or ((not up) and h[j] >= lv - TOUCH_ATR * ab)): jt = j; break
        if dead: continue
        if jt is None:
            if i - jb >= VALID_B: e.update(status="expired", reason="возврат к уровню не случился за %d свечей" % VALID_B, t_end=tend)
            continue
        bad = [k for k in range(jt, i + 1) if (up and c[k] < lv - TOL_ATR * ab) or ((not up) and c[k] > lv + TOL_ATR * ab)]
        if bad:
            e.update(status="false", reason="ложный пробой: свеча %s закрылась за уровнем" % pos.tstr(t[bad[0]]), t_end=tend, t_touch=int(t[jt])); continue
        pierce = ((lv - float(l[jt:i + 1].min())) if up else (float(h[jt:i + 1].max()) - lv)) / ab
        if pierce > WICK_ATR:
            e.update(status="false", reason="ложный пробой: тень ушла за уровень на %.1f ATR (предел %.1f)" % (pierce, WICK_ATR), t_end=tend, t_touch=int(t[jt])); continue
        jc = jt + CONFIRM_N - 1
        if jc > i: e["t_touch"] = int(t[jt]); continue   # окно подтверждения ещё не закрыто
        ext = float(l[jt:jc + 1].min()) if up else float(h[jt:jc + 1].max())
        entry = lv + ENTRY_OFF * ab if up else lv - ENTRY_OFF * ab
        away = (float(c[i]) - entry) / a if up else (entry - float(c[i])) / a
        if away > AWAY_ATR:
            e.update(status="skipped", reason="после подтверждения цена ушла от уровня на %.1f ATR (не гонимся)" % away, t_end=tend, t_touch=int(t[jt]), t_conf=int(t[jc])); continue
        stop = ext - STOP_PAD * ab if up else ext + STOP_PAD * ab; risk = abs(entry - stop); floor = MIN_RISK / 100 * entry
        if risk < floor: stop = entry - floor if up else entry + floor; risk = floor
        tp = entry + max(e["width"], 2 * risk) if up else entry - max(e["width"], 2 * risk)
        side = "long" if up else "short"; rule = "retest_up" if up else "retest_down"; b = e["basis"]; tp_ = int(t[i]) + TFM
        why = [chan_text(b),
               "Пробой: свеча %s закрылась на %s %s границы канала (%s) больше чем на 0.2 ATR." % (tok(e["bo"]["t"]), P(e["bo"]["close"]), "выше верхней" if up else "ниже нижней", P(e["line"])),
               "Уровень: %s (окно 24 свечи до пробоя) = %s. %s." % (e["src"], P(lv), "Бывшее сопротивление становится поддержкой" if up else "Бывшая поддержка становится сопротивлением"),
               "Подтверждение (путь Б, v3): после пробоя цена отошла от уровня на %.1f ATR (не меньше %.1f), вернулась к нему (свеча %s, через %d св. после пробоя, %s %s, тень за уровнем %.1f ATR, предел %.1f), затем %d свечи подряд ни одного закрытия %s уровня на 0.2 ATR (допуск по ATR на момент пробоя %s). Пробой удержался." % (
                   ((max(h[jb:jt]) - lv) if up else (lv - min(l[jb:jt]))) / ab, DEP_ATR, tok(int(t[jt])), jt - jb, "минимум" if up else "максимум", P(ext), pierce, WICK_ATR, CONFIRM_N, "ниже" if up else "выше", P(ab)),
               "Вход лимитом %s: уровень %s 0.1 ATR = %s; цена сейчас %s (%.1f ATR от входа, предел %.1f)." % ("покупки" if up else "продажи", "плюс" if up else "минус", P(entry), P(float(c[i])), away, AWAY_ATR),
               "Стоп %s ретеста (%s) на 0.5 ATR = %s (риск %.2f%%, не меньше 0.5%% цены)." % ("ниже минимума" if up else "выше максимума", P(ext), P(stop), risk / entry * 100),
               "Цель = вход %s max(высота канала %s, 2 риска %s) = %s." % ("плюс" if up else "минус", P(e["width"]), P(2 * risk), P(tp)),
               "Заявка живёт %d свечей (до %s). Отмена: закрытие за уровнем на 0.7 ATR, либо цена ушла от входа больше чем на %.1f ATR." % (VALID_C, tok(tp_ + (VALID_C - 1) * TFM), AWAY_ATR)]
        o = mk(sym, rule, side, entry, stop, tp, a, tp_, VALID_C, e["chan"], e["lv"], key=e["key"], ctype=e["ctype"], basis=b, why=why, breakout=e["bo"], rv=RV,
               confirm={"t_touch": int(t[jt]), "t_conf": int(t[jc]), "ext": ext, "n": CONFIRM_N})
        out.append(o); e.update(status="confirmed", reason="подтверждено, заявка выставлена", t_end=tend, t_touch=int(t[jt]), t_conf=int(t[jc]))
        log("CONFIRM %s %s уровень %.6g вход %.6g стоп %.6g" % (sym, rule, lv, entry, stop))
    return out

def shadow_text(sh):
    ru = {"yes": "по направлению", "no": "ПРОТИВ", "neutral": "нейтрально", None: "нет данных"}; parts = []
    for nm, lab in (("btc", "BTC"), ("eth", "ETH"), ("own", "сама пара")):
        for tf, r in (sh.get(nm) or {}).items():
            ag = (sh.get("agree") or {}).get("%s_%s" % (nm, tf)); parts.append("%s %s: счёт %s, %s" % (lab, tf, ("%+d" % r["s"]) if r else "?", ru.get(ag, "нет данных")))
    return "Тренд (тень, на решение НЕ влияет; счёт -4..+4 по EMA; BTC/ETH и другой таймфрейм): " + "; ".join(parts) + "."

def cycle(dry=False):
    now = int(time.time() * 1000); stt = load_state(); props = {}; closes = {}; evs = load_events()
    for sym in PAIRS:
        try:
            A = analyze(sym, now)
            if not A: continue
            ti = A["t"][A["M"] - 1]; closes[sym] = (float(A["c"][A["M"] - 1]), float(A["atr"][A["M"] - 1]), ti)
            if stt["last"].get(sym) == ti: continue
            ps = propose(sym, A, evs) + eval_events(sym, A, evs)
            for p in ps:
                try: p["shadow"] = trend_shadow.shadow(sym, p["side"]); p["why"].append(shadow_text(p["shadow"]))
                except Exception as e: log("shadow %s error: %s" % (sym, e))
            props[sym] = (ti, ps)
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
        print("events watching %d: %s" % (sum(1 for e in evs if e["status"] == "watch"), [(e["sym"], e["dir"], e["status"], e.get("reason", "")) for e in evs[-8:]]))
        print("pairs scanned %d, with proposals %d, pending %d" % (len(closes), sum(1 for v in props.values() if v[1]), len(pend))); return
    with pos.lock():
        orders = load_orders(); ps_ = pos.load(); by_id = {o["id"]: o for o in orders}
        def n_open(): return sum(1 for p in ps_ if p["status"] == "open")
        def cancel(o, why, t=None): o.update(status="cancelled", reason=why, t_end=t or now)
        for x in orders:  # заменённые правила: заблаговременные у границы (флаг) и ретест без подтверждения
            if x["status"] == "pending" and ((x["rule"] in ("chan_top", "chan_bottom") and not CHAN_EDGE) or (x["rule"] in ("retest_up", "retest_down") and not x.get("rv"))):
                cancel(x, "правило заменено: ретест с подтверждением удержания")
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
                    elif x.get("rv") in (2, 3) and ((x["side"] == "long" and (c0 - x["price"]) / a0 > AWAY_ATR) or (x["side"] == "short" and (x["price"] - c0) / a0 > AWAY_ATR)): cancel(x, "цена ушла от входа больше чем на %.1f ATR (в погоне не входим)" % AWAY_ATR, ti + TFM)
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
                log("SHADOW order %d agree=%s" % (p["id"], json.dumps((p.get("shadow") or {}).get("agree", {}))))
            for x in [x for x in pend_sym if x["status"] == "pending" and x["rule"] in ("chan_top", "chan_bottom") and not any(pp["rule"] == x["rule"] and pp["side"] == x["side"] for pp in props_)]:
                cancel(x, "условия исчезли (канал, расстояние или цель)", ti + TFM)
        # слоты заполнены: лишние заявки не держим
        if n_open() >= SLOTS:
            for x in orders:
                if x["status"] == "pending": cancel(x, "слоты заняты")
        save_orders(orders); save_state(stt); save_events(evs)

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

def shadow_report():
    """Результаты ЗАКРЫТЫХ позиций заявок по группам согласия с трендом (тень). Правила не меняются; решение о фильтре: >=30 заявок в группе, разница >=0.3R."""
    orders = {o["id"]: o for o in load_orders()}; rows = []
    for p in pos.load():
        o = orders.get(p.get("order_id"))
        if p.get("src") == "chan" and p["status"] == "closed" and o and o.get("shadow"): rows.append((o, p["r_mult"]))
    print("закрытых позиций заявок с тенью: %d" % len(rows))
    for ver in ("v3", "v2", "все"):
        sel = [(o, r) for o, r in rows if ver == "все" or o.get("rv") == (3 if ver == "v3" else 2)]
        print("== %s: %d сделок, сумма R %.2f" % ({"v3": "ретест v3 (возврат, структура, тень)", "v2": "ретест с подтверждением v2"}.get(ver, "все правила"), len(sel), sum(r for _, r in sel)))
        keys = sorted({k for o, _ in sel for k in o["shadow"]["agree"]})
        for k in keys:
            for g in ("yes", "neutral", "no"):
                rs = [r for o, r in sel if o["shadow"]["agree"].get(k) == g]
                if rs: print("  %-10s %-8s n=%-3d win=%3.0f%% avgR=%+.2f sumR=%+.2f" % (k, g, len(rs), 100.0 * sum(1 for r in rs if r > 0) / len(rs), sum(rs) / len(rs), sum(rs)))

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


SH_LAB = {"btc_5m": "BTC 5m", "btc_15m": "BTC 15m", "eth_5m": "ETH 5m", "eth_15m": "ETH 15m", "own_15m": "сама пара 15m", "own_1h": "сама пара 1h"}
def shadow_summary():
    """Сводка тени тренда по закрытым позициям заявок (для панели): группы v3 и все; в ячейке n, доля прибыльных, средний R, сумма R."""
    orders = {o["id"]: o for o in load_orders()}; rows = []
    for p in pos.load():
        o = orders.get(p.get("order_id"))
        if p.get("src") == "chan" and p["status"] == "closed" and o and o.get("shadow"): rows.append((o, p["r_mult"]))
    def grp(sel):
        out = []
        for k, lab in SH_LAB.items():
            r = {"k": k, "label": lab}
            for g in ("yes", "neutral", "no"):
                rs = [x for o, x in sel if (o["shadow"].get("agree") or {}).get(k) == g]
                r[g] = {"n": len(rs), "win": round(100.0 * sum(1 for x in rs if x > 0) / len(rs)) if rs else None, "avg": round(sum(rs) / len(rs), 2) if rs else None, "sum": round(sum(rs), 2)}
            out.append(r)
        return {"n": len(sel), "sumR": round(sum(x for _, x in sel), 2), "rows": out}
    return {"v3": grp([(o, r) for o, r in rows if o.get("rv") == 3]), "all": grp(rows)}

def closed_view(pid):
    """Закрытая позиция для графика на панели: свечи вокруг сделки (5m у заявок, 15m у позиций ожидателя), канал/уровень/пробой из заявки."""
    p = next((x for x in pos.load() if x["id"] == pid and x["status"] != "open"), None)
    if not p: return {"error": "закрытая позиция не найдена"}
    q = dict(p); o = None
    if p.get("src") == "chan": o = next((x for x in load_orders() if x["id"] == p.get("order_id")), None)
    dt = TFM if o else 900000; tf = "5m" if o else "15m"
    if o:
        for k in ("chan", "basis", "level", "breakout", "placed_t", "expire_t", "ctype", "rule", "atr", "why", "confirm", "shadow"):
            if o.get(k) is not None: q["o_" + k] = o[k]
        ts = [ln["t1"] for ln in ((o.get("chan") or {}).get("upper"), (o.get("chan") or {}).get("lower")) if ln] + [p["t_in"]]
        start = max(min(ts) - 12 * dt, p["t_in"] - 700 * dt)
    else: start = p["t_in"] - 120 * dt
    end = p["t_out"] + 30 * dt
    d = pos.kl(p["sym"], tf, 1000, int(start))
    q["cand"] = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in d if int(k[0]) <= end]
    q["o_dt"] = dt; q["tf"] = tf
    return q

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "scan": cycle(dry="--dry" in sys.argv)
    elif cmd == "report": shadow_report()
    elif cmd == "cfg":
        c = {}
        try: c = json.load(open(CFGF))
        except Exception: pass
        if len(sys.argv) >= 4: c[sys.argv[2]] = int(sys.argv[3]); json.dump(c, open(CFGF, "w"), ensure_ascii=False)
        print(c)
    elif cmd == "loop":
        while True:
            try: cycle()
            except Exception as e: log("cycle error: %s" % e)
            time.sleep(20)
    else:
        for o in load_orders(): print(o["id"], o["sym"], o["rule"], o["side"], "%.6g" % o["price"], o["status"], pos.tstr(o["placed_t"]), o.get("reason", ""))
