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
  entry_mode: stages (уровни фильтра входа: триггер → подтверждения по очереди, пустой уровень пропускается; см. stage_signals) | pattern20 (паттерн разворота «взводит» вход, вход по первому закрытию за EMA20 в пределах arm_k свечей) | cross200 (пересечение EMA20 и EMA200) | close20 (первое закрытие свечи за EMA20 после пересечения) | state20 (любое закрытие за EMA20, когда позиции нет)
  Триггеры по линиям тренда: tl_bounce (отбой от границы канала/флэта, P — допуск касания в ATR, 0.3) | tl_breakout (пробой треугольника, P — запас за линией в ATR, 0.2); линии строятся по подтверждённым pivot (см. classic_trendline.py)
  Триггеры по линиям, нарисованным пользователем: hand_bounce (отбой от границы канала/флэта) | hand_breakout (пробой границы); hand_forward — торговать только после момента рисования (иначе по всей истории — с подглядыванием). P: допуск касания/запас пробоя в ATR
  entry_trigger: open (по открытию следующей свечи) | breakout (по пробою экстремума сигнальной свечи, до bo_wait свечей; отмена: закрытие за EMA50 / пробит локальный экстремум); stop_mode sig3: за экстремумом 3 свечей сигнала −0.2 ATR, не ближе 0.5 ATR; tp_r: цель в R (0 — нет); max_bars: выход по времени через столько свечей (0 — нет)
  Подтверждения правил EMA50+StochRSI: ema50_trend | ema50_pullback (P ATR) | stochrsi_cross (зона P, умолч. 20) — считаются на одной свече, в т.ч. на сигнальной
  rev_exit: обратный сигнал входа закрывает позицию (разворот)
  stop_mode: prev (за экстремумом предыдущей свечи, не ближе min_stop_pct/min_stop_atr) | pct (фиксированный min_stop_pct) | pivot
  be_trigger (точка перехода в безубыток, %), be_lock (размер безубытка: стоп на вход ± be_lock%)
  trail_mode: none | pct | atr | pivot (после безубытка), trail_dist
  pat_mode: off | exit (паттерн закрывает позицию при плюсе >= pat_min%) | trail (паттерн включает трейлинг под минимумом/максимумом предыдущей свечи, не хуже безубытка)
  Подтверждения «возврата» (из разметки; подряд идущие такие уровни считаются на одной свече, а ext_dist ещё требует паттерн у экстремума 12 ч): pullback_ema20 (P ATR от EMA20) | rsi_band (RSI 49±P) | ext_dist (P…P+2.1 ATR от экстремума 12 ч) | stoch_dir (StochK14 в сторону, порог P) | macd_sign (гист. MACD по знаку и растёт) | ema50_slope (наклон EMA50 за P св.)
  pat_filter: значимость паттерна — none | level (у pivot-уровня) | volume (объём ≥1.5× среднего) | extreme (новый экстремум 12 ч для 15m) | stretch (растяжение ≥1.5 ATR от EMA20) | level+volume | extreme+volume | sweep (паттерн снял экстремум 48 свечей=12 ч и закрылся обратно) | sweep16 (то же за 16 свечей=4 ч) | sweep+volume
  sim_from_ms: начать симуляцию «с нуля» с этого момента (для живой бумажной торговли)"""
import numpy as np
import pandas as pd
import classic_analysis as an
import classic_trendline as tl
import classic_fastchan as fchan
import classic_hand as hand

PARAMS = dict(tf="15m", be_trigger=1.5, fee=0.05, window_h=240, notional=100.0, warmup=200,
              stop_mode="prev", min_stop_pct=1.5, min_stop_atr=0.0, trail_mode="none", trail_dist=0.0, be_atr=0.0, be_lock=0.3, be_tp_frac=0.0,
              entry_mode="cross200", rev_exit=True, pat_mode="off", arm_k=12, pat_filter="none", entry_trigger="open", bo_wait=3, tp_r=0.0, max_bars=0, tp_mode="r", be_intrabar=False, tl_min_w=1.5, tl_max_w=14.0, tl_src="old", fc_minw=1.5, fc_maxw=8.0, ch_stop_pct=0.3, ch_stop_atr=0.0, ch_min_stop_pct=0.0, ch_tp_gap_pct=0.2, ch_tp_gap_atr=0.0, ch_min_rr=0.0, ch_follow=False, period_from="", period_to="", sym="", hand_forward=True, hand_tf_mode="junior",
              stake_mode="fixed", stake_base=100.0, stake_min=6.0, martingale="off", mart_pct=50.0, mart_max=0,
              stages=[{"t": "pattern", "p": 0, "w": 0, "f": "none"}, {"t": "close_ema20", "p": 0, "w": 12, "f": "none"}])

PANEL = dict(PARAMS, be_trigger=1.5, be_lock=0.4, entry_mode="cross200", rev_exit=True, pat_mode="off", pat_min=0.0, be_intrabar=True)  # «рекомендованные» правила конструктора (лучшие по проверке на ZEC 15m; пользователь может менять)


TRIGGERS = ("pattern", "cross200", "cross20", "cross50", "tl_bounce", "tl_breakout", "tl_both", "hand_bounce", "hand_breakout", "hand_both")
CONFIRMS = ("close_ema20", "break_trigger", "ema20_slope", "rsi_level", "macd_turn", "volume", "strong_body", "break_swing",
            "pullback_ema20", "rsi_band", "ext_dist", "stoch_dir", "macd_sign", "ema50_slope", "ema50_trend", "ema50_pullback", "stochrsi_cross", "ema200_side")
STATE_STAGES = ("pullback_ema20", "rsi_band", "ext_dist", "stoch_dir", "macd_sign", "ema50_slope", "ema50_trend", "ema50_pullback", "stochrsi_cross", "ema200_side")
TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720, "1d": 1440}


def chan_dir(ch, i, k=20, thr=0.15):
    """Направление канала на сигнальной свече i по линиям ch=(нижняя(j), верхняя(j)): +1 восходящий, -1 нисходящий, 0 боковик/неясно.
    Наклон средней линии за k свечей в долях ширины канала; меньше thr — боковик (ограничений нет)."""
    try:
        lo_f, up_f = ch
        w = up_f(i) - lo_f(i)
        if w <= 0 or i < k:
            return 0
        sl = ((lo_f(i) + up_f(i)) - (lo_f(i - k) + up_f(i - k))) / 2.0 / w
        return 1 if sl > thr else -1 if sl < -thr else 0
    except Exception:
        return 0


def chan_rule_ok(d, tag, side):
    """Правило канала: восходящий (d=+1): отбой — только лонг, пробой — только шорт; нисходящий (d=-1): отбой — только шорт, пробой — только лонг."""
    if d == 0 or tag not in ("b", "k"):
        return True
    return side == ("L" if (d > 0) == (tag == "b") else "S")


def stage_signals(pre, P, warmup=None):
    """Уровни фильтра входа. Возвращает {индекс закрытой свечи: (сторона, индекс свечи-триггера)}: на этой свече выполнены все уровни.
    Уровни идут по очереди: триггер (первый непустой уровень), затем подтверждения; каждое подтверждение должно выполниться
    не позже чем через w свечей после предыдущего уровня, при этом на свече-триггере подтверждения не проверяются.
    Паттерн-триггер отменяется, если цена закрылась за экстремумом свечи-паттерна против направления."""
    stages = [x for x in (P.get("stages") or []) if x and x.get("t")]
    out = {}
    pre["_chan"] = {}  # линии канала на момент сигнала триггера: {свеча: (нижняя(j), верхняя(j))} — для стопа/цели по каналу
    if not stages or not pre.get("ok"):
        return out
    M = pre["M"]
    W = P["warmup"] if warmup is None else warmup
    o, h, l, c, e20, e200, atr = pre["o"], pre["h"], pre["l"], pre["c"], pre["e20"], pre["e200"], pre["atr"]
    rsi, hist, v, vavg, piv = pre["rsi"], pre["hist"], pre["v"], pre["vavg"], pre["piv"]
    st14, e50, srk, srd = pre["stoch"], pre["e50"], pre["srk"], pre["srd"]
    N12 = max(4, 720 // TF_MIN.get(P.get("tf", "15m"), 15))  # окно «экстремум 12 ч» в свечах
    trig = stages[0]
    if trig["t"] not in TRIGGERS:
        return out
    bull = bear = set()
    tlsig = {}
    chan = {}
    tags = {}  # {свеча: 'b' | 'k'} — отбой или пробой (только hand_both)
    pre["_tag"] = tags
    sids = {}  # {свеча: id нарисованной структуры, давшей сигнал}
    pre["_sid"] = sids
    if trig["t"] == "pattern":
        bull, bear = pat_sets(pre, trig.get("f", "none"))
    elif trig["t"] in ("tl_bounce", "tl_breakout", "tl_both"):  # линии тренда: отбой в канале/флэте и/или пробой канала/треугольника (tl_both — оба сразу)
        kinds_ = ("tl_bounce", "tl_breakout") if trig["t"] == "tl_both" else (trig["t"],)
        cache = pre.setdefault("_tl", {})
        wl_ = (float(P.get("tl_min_w", 1.5)), float(P.get("tl_max_w", 14.0)))
        src_ = str(P.get("tl_src", "old"))
        fw_ = (float(P.get("fc_minw", 1.5)), float(P.get("fc_maxw", 8.0)))
        tlsig, chan = {}, {}
        for kd_ in kinds_:
            tlp = (0.2 if kd_ == "tl_breakout" else float(trig.get("p") or 0)) if trig["t"] == "tl_both" else float(trig.get("p") or 0)
            key_ = (kd_, tlp, tl.cfg_key(), wl_) if src_ != "fast" else (kd_, tlp, "fast", fw_, tuple(sorted(fchan.FC.items())))
            if key_ not in cache:
                pv_ = None  # опорные точки и pivot модуль считает сам по текущим (в т.ч. обученным по рисункам пользователя) параметрам
                inf_ = {}
                if src_ == "fast":  # быстрый канал по правилу пользователя (classic_fastchan): 3 точки, пробой по закрытию
                    cache[key_] = (fchan.fc_signals(o, h, l, c, atr, M, kd_, tlp, fw_[0], fw_[1], info=inf_), inf_)
                else:
                    cache[key_] = (tl.tl_signals(o, h, l, c, atr, pv_, M, kd_, tlp, info=inf_, wlim=None if wl_ == (1.5, 14.0) else wl_), inf_)
            sg_, inf2_ = cache[key_]
            for i_, sd2_ in sg_.items():
                if i_ in tlsig:
                    continue
                tlsig[i_] = sd2_
                if i_ in inf2_:
                    chan[i_] = inf2_[i_]
                if trig["t"] == "tl_both":
                    tags[i_] = "b" if kd_ == "tl_bounce" else "k"
    elif trig["t"] in ("hand_bounce", "hand_breakout", "hand_both"):  # линии, нарисованные пользователем (hand.json)
        hp = float(trig.get("p") or 0)
        structs_ = hand.for_sym(P.get("sym"), P.get("tf"), P.get("hand_tf_mode", "junior")) if P.get("sym") else []
        tlsig = hand.hand_signals(o, h, l, c, atr, pre["t"], M, structs_, trig["t"], hp, bool(P.get("hand_forward", True)), info=chan, tags=tags, sids=sids)
    if trig["t"] in ("hand_bounce", "hand_both"):
        # треугольник торгуется только на пробой (в любую сторону); отбой от его линий не берём
        tri0_ = {x.get("id") for x in structs_ if x.get("kind") == "triangle"}
        for i_ in list(tlsig):
            if sids.get(i_) in tri0_ and (tags.get(i_) or ("b" if trig["t"] == "hand_bounce" else None)) != "k":
                del tlsig[i_]
    if trig["t"] in ("tl_bounce", "tl_breakout", "tl_both", "hand_bounce", "hand_breakout", "hand_both") and P.get("chan_dir", True):
        # правило канала: направление канала задаёт, какая сторона разрешена на отбой и на пробой (треугольники и боковики не фильтруются)
        tri_ = {x.get("id") for x in structs_ if x.get("kind") == "triangle"} if trig["t"].startswith("hand_") else set()
        dflt_ = {"tl_bounce": "b", "tl_breakout": "k", "hand_bounce": "b", "hand_breakout": "k"}.get(trig["t"])
        for i_ in list(tlsig):
            if sids.get(i_) in tri_:
                continue
            tg_ = tags.get(i_) or dflt_
            if i_ in chan and not chan_rule_ok(chan_dir(chan[i_], i_), tg_, tlsig[i_]):
                del tlsig[i_]
    conf = []
    for st_ in stages[1:]:  # подряд идущие «состояния» объединяются в одно подтверждение: все условия на одной свече
        if st_["t"] in STATE_STAGES:
            if conf and conf[-1]["t"] == "group": conf[-1]["items"].append(st_)
            else: conf.append({"t": "group", "items": [st_], "w": st_.get("w"), "p": 0})
        else:
            conf.append(st_)

    def swing(i, side):
        for q in reversed(piv):
            if q["conf"] > i: continue
            if i - q["i"] > 150: break
            if q["k"] == ("H" if side == "L" else "L"):
                return q["p"]
        return None

    def ok(st, side, i, tr):
        t, p = st["t"], float(st.get("p") or 0)
        sd = 1 if side == "L" else -1
        if t == "group": return all(ok(it, side, i, tr) for it in st["items"])
        if t == "close_ema20": return sd * (c[i] - e20[i]) > 0
        if t == "break_trigger": return c[i] > h[tr] if side == "L" else c[i] < l[tr]
        if t == "ema20_slope":
            k = int(p) if p >= 1 else 3
            return sd * (e20[i] - e20[i - k]) > 0
        if t == "rsi_level":
            lv = p if p > 0 else 45.0
            return rsi[i] >= lv if side == "L" else rsi[i] <= 100 - lv
        if t == "macd_turn": return sd * (hist[i] - hist[i - 1]) > 0 and sd * (hist[i - 1] - hist[i - 2]) > 0
        if t == "volume":
            return (v[i] >= (p if p > 0 else 1.2) * vavg[i]) if vavg[i] == vavg[i] else False
        if t == "strong_body": return sd * (c[i] - o[i]) >= (p if p > 0 else 0.8) * atr[i]
        if t == "break_swing":
            sw = swing(i, side)
            return sw is not None and ((c[i] > sw) if side == "L" else (c[i] < sw))
        if t == "pullback_ema20": return abs(c[i] - e20[i]) <= (p if p > 0 else 0.9) * atr[i]  # возврат к EMA20: цена в пределах P ATR от неё
        if t == "rsi_band": return abs(rsi[i] - 49.0) <= (p if p > 0 else 9.0)  # RSI в нейтральной зоне 49±P (по умолч. 40–58)
        if t == "ext_dist":  # расстояние от экстремума 12 ч в сторону сделки: от P до P+2.1 ATR (по умолч. 2.4–4.5)
            if i < N12: return False
            ex = l[i - N12:i + 1].min() if side == "L" else h[i - N12:i + 1].max()
            d = sd * (c[i] - ex) / atr[i]
            lo = p if p > 0 else 2.4
            if side == "L" and l[tr] > ex + 0.5 * atr[i]: return False  # паттерн должен быть у экстремума 12 ч
            if side == "S" and h[tr] < ex - 0.5 * atr[i]: return False
            return lo <= d <= lo + 2.1
        if t == "stoch_dir":  # StochK(14) в сторону сделки: лонг выше P, шорт ниже 100−P (по умолч. 50)
            thr = p if p > 0 else 50.0
            return (st14[i] > thr) if side == "L" else (st14[i] < 100.0 - thr)
        if t == "macd_sign": return sd * hist[i] > 0 and sd * (hist[i] - hist[i - 1]) > 0  # гистограмма MACD по знаку сделки и растёт
        if t == "ema200_side":  # цена по сторону EMA200 (тренд старшего уровня): лонг — выше, шорт — ниже
            return c[i] > e200[i] if side == "L" else c[i] < e200[i]
        if t == "ema50_trend":  # цена по сторону EMA50 и EMA50 не направлена против сделки (5 св.)
            return (c[i] > e50[i] and e50[i] >= e50[i - 5]) if side == "L" else (c[i] < e50[i] and e50[i] <= e50[i - 5])
        if t == "ema50_pullback":  # откат: за 6 св. экстремум подходил к EMA50 ближе P ATR (по умолч. 0.8)
            lim = (p if p > 0 else 0.8) * atr[i]
            return bool((l[i - 5:i + 1] - e50[i - 5:i + 1]).min() <= lim) if side == "L" else bool((e50[i - 5:i + 1] - h[i - 5:i + 1]).min() <= lim)
        if t == "stochrsi_cross":  # Stoch RSI (3,3,14,14): K пересекла D в зоне <P (лонг) / >100−P (шорт) за последние 3 св.
            zone = p if p > 0 else 20.0
            for j in range(i - 3, i + 1):
                if side == "L" and srk[j - 1] <= srd[j - 1] and srk[j] > srd[j] and min(srk[j - 1], srd[j - 1]) < zone: return True
                if side == "S" and srk[j - 1] >= srd[j - 1] and srk[j] < srd[j] and max(srk[j - 1], srd[j - 1]) > 100.0 - zone: return True
            return False
        if t == "ema50_slope":
            k = int(p) if p >= 1 else 5
            return sd * (e50[i] - e50[i - k]) > 0  # EMA50 наклонена в сторону сделки
        return False
    pend = None
    for i in range(max(W, 3), M):
        if pend is not None:
            side, tr, idx, dead = pend
            if trig["t"] == "pattern" and ((side == "L" and c[i] < l[tr]) or (side == "S" and c[i] > h[tr])):
                pend = None
            elif i > dead:
                pend = None
            else:
                while idx < len(conf) and ok(conf[idx], side, i, tr):
                    idx += 1
                    if idx < len(conf):
                        dead = i + int(conf[idx].get("w") or 12)
                if idx >= len(conf):
                    out[i] = (side, tr)
                    pend = None
                else:
                    pend = (side, tr, idx, dead)
        ns = None
        if trig["t"] == "pattern":
            ns = "L" if (i in bull and i not in bear) else "S" if (i in bear and i not in bull) else None
        elif trig["t"] == "cross200":
            pr, cu = e20[i - 1] - e200[i - 1], e20[i] - e200[i]
            ns = "L" if pr <= 0 < cu else "S" if pr >= 0 > cu else None
        elif trig["t"] == "cross50":
            pr, cu = c[i - 1] - e50[i - 1], c[i] - e50[i]
            ns = "L" if pr <= 0 < cu else "S" if pr >= 0 > cu else None
        elif trig["t"] in ("tl_bounce", "tl_breakout", "tl_both", "hand_bounce", "hand_breakout", "hand_both"):
            ns = tlsig.get(i)
        else:
            pr, cu = c[i - 1] - e20[i - 1], c[i] - e20[i]
            ns = "L" if pr <= 0 < cu else "S" if pr >= 0 > cu else None
        if ns:
            if not conf:
                out[i] = (ns, i)
            else:
                gw = lambda st_: int(st_.get("w") or 12) - (1 if st_["t"] == "group" else 0)  # окно группы: w=1 — только сигнальная свеча
                k0, dead0 = 0, i + gw(conf[0])
                while k0 < len(conf) and conf[k0]["t"] == "group" and ok(conf[k0], ns, i, i):  # «состояния» проверяются и на сигнальной свече
                    k0 += 1
                    if k0 < len(conf): dead0 = i + gw(conf[k0])
                if k0 >= len(conf): out[i] = (ns, i)
                else: pend = (ns, i, k0, dead0)
    pre["_chan"] = chan
    return out


def _last_piv(piv, kind, maxconf, ok):
    for q in reversed(piv):
        if q["k"] == kind and q["conf"] <= maxconf and ok(q["p"]):
            return q["p"]
    return None


PAT_FILTERS = {
    "none": lambda f: True, "level": lambda f: f[0], "volume": lambda f: f[1], "extreme": lambda f: f[2], "stretch": lambda f: f[3],
    "level+volume": lambda f: f[0] and f[1], "extreme+volume": lambda f: f[2] and f[1],
    "sweep": lambda f: f[5], "sweep16": lambda f: f[4], "sweep+volume": lambda f: f[5] and f[1],
}


def pat_sets(pre, name):
    ff = PAT_FILTERS.get(name or "none", PAT_FILTERS["none"])
    bull, bear = set(), set()
    for (i, up, a, b, c, d, e, g) in pre["pfeat"]:
        if ff((a, b, c, d, e, g)):
            (bull if up else bear).add(i)
    return bull, bear


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
    h_, l_, c_, v_ = df.h.values, df.l.values, df.c.values, df.v.values
    a_, e20_ = ind["atr"].values, ind["ema20"].values
    pv = an.find_pivots(closed)
    PL = [(q["i"], q["p"], q["conf"]) for q in pv if q["k"] == "L"]
    PH = [(q["i"], q["p"], q["conf"]) for q in pv if q["k"] == "H"]

    def near_level(i, low, price, tol):
        for pi, pp, pc in reversed(PL if low else PH):
            if pc > i: continue
            if i - pi > 300: break
            if abs(price - pp) <= tol: return True
        return False
    def sweep(i, up, N):
        # съём ликвидности: паттерн (3 свечи) вышел за экстремум предыдущих N свечей и закрылся обратно в диапазон
        if i < N + 3: return False
        if up:
            prev = l_[i - 3 - N:i - 2].min()
            return bool(l_[i - 2:i + 1].min() < prev and c_[i] > prev)
        prev = h_[i - 3 - N:i - 2].max()
        return bool(h_[i - 2:i + 1].max() > prev and c_[i] < prev)
    pfeat = []
    for p in pats:
        i = p["i"]
        if p["d"] == 0: continue
        up = p["d"] > 0
        if i < 48:
            pfeat.append((i, up, False, False, False, False, False, False)); continue
        pfeat.append((i, up,
                      near_level(i, up, l_[i] if up else h_[i], 0.5 * a_[i]),
                      bool(v_[i] >= 1.5 * v_[i - 20:i].mean()),
                      bool(l_[i - 47:i + 1].min() == l_[i]) if up else bool(h_[i - 47:i + 1].max() == h_[i]),
                      bool((e20_[i] - c_[i]) >= 1.5 * a_[i]) if up else bool((c_[i] - e20_[i]) >= 1.5 * a_[i]),
                      sweep(i, up, 16), sweep(i, up, 48)))
    bu = {p["i"] for p in pats if p["d"] > 0}
    be_ = {p["i"] for p in pats if p["d"] < 0}
    exs = {i: "L" for i in bu - be_}
    exs.update({i: "S" for i in be_ - bu})
    vv = pd.Series(df.v.values)
    hh14, ll14 = pd.Series(df.h.values).rolling(14).max(), pd.Series(df.l.values).rolling(14).min()
    stoch = (100.0 * (pd.Series(df.c.values) - ll14) / (hh14 - ll14 + 1e-9)).values
    e50 = pd.Series(df.c.values).ewm(span=50, adjust=False).mean().values
    cc = pd.Series(df.c.values); dd = cc.diff()
    upm = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dnm = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi14 = 100 - 100 / (1 + upm / (dnm + 1e-12))
    srs = 100 * (rsi14 - rsi14.rolling(14).min()) / (rsi14.rolling(14).max() - rsi14.rolling(14).min() + 1e-9)
    srk = srs.rolling(3).mean(); srd = srk.rolling(3).mean()  # Stoch RSI (3, 3, 14, 14)
    pre.update(ok=True, stoch=stoch, e50=e50, srk=srk.values, srd=srd.values, exits=exs, pfeat=pfeat, piv=pv, rsi=ind["rsi"].values, hist=ind["hist"].values,
               v=df.v.values, vavg=vv.rolling(20).mean().shift(1).values, e20=ind["ema20"].values, e200=ind["ema200"].values,
               atr=ind["atr"].values, o=df.o.values, h=df.h.values, l=df.l.values, c=df.c.values, t=df.t.values)
    return pre


def simulate(df, now_ms, P=PARAMS, pre=None, filt=None, sigs=None, exits=None):
    pre = pre or prepare(df, now_ms)
    pm = P.get("pat_mode")
    if pm in (None, "", "off"):
        pm = "exit" if (P.get("pat_exit") or exits is not None) else "off"
    bull = bear = set()
    if pre.get("ok") and (pm in ("exit", "trail") or P.get("entry_mode") == "pattern20"):
        bull, bear = pat_sets(pre, P.get("pat_filter", "none"))
    if exits is None and pm in ("exit", "trail") and pre.get("ok"):
        if P.get("pat_filter", "none") == "none":
            exits = pre["exits"]
        else:
            exits = {i: "L" for i in bull - bear}
            exits.update({i: "S" for i in bear - bull})
    if not pre["ok"] or pre["M"] < P["warmup"] + 30:
        return []
    T, M, piv = pre["T"], pre["M"], pre["piv"]
    e20, e200, atr, e50 = pre["e20"], pre["e200"], pre["atr"], pre["e50"]
    o, h, l, c, t = pre["o"], pre["h"], pre["l"], pre["c"], pre["t"]
    fee2 = 2 * P["fee"]
    mcl = P.get("manual_close") or {}  # ручное закрытие позиций: {"t_in|сторона": (время_мс, цена, причина)} — кнопки «Закрыть» и срабатывание ручного стопа/трейлинга
    tfms_ = TF_MIN.get(P.get("tf"), 15) * 60000
    tm, td = P["trail_mode"], P["trail_dist"]
    trades, pos, pend, pexit, arm, parm, bo = [], None, None, False, None, None, None
    chan = pre.get("_chan") or {}  # линии канала на сигнале (для stop_mode=channel / tp_mode=channel)
    pend_ch = bo_ch = pos_ch = pos_vis = None
    tg_ = sd_ = None
    pend_sid = None
    pend_tag = None  # 'b' | 'k' сигнала, ожидающего входа (hand_both)
    ch_stop_on = P.get("stop_mode") == "channel"
    ch_tp_on = P.get("tp_mode", "r") == "channel"

    def ch_levels(side, ch, j, entry, a):
        """Стоп за линией канала (+запас в % и ATR, не ближе ch_min_stop_pct) и цель на противоположной линии (с отступом внутрь). (стоп, цель, запас стопа, отступ цели) или None, если уровни неверны."""
        lo, up = ch
        gs = entry * P.get("ch_stop_pct", 0.0) / 100 + P.get("ch_stop_atr", 0.0) * a
        fl = entry * P.get("ch_min_stop_pct", 0.0) / 100
        gt = entry * P.get("ch_tp_gap_pct", 0.0) / 100 + P.get("ch_tp_gap_atr", 0.0) * a
        if side == "L":
            st, tp = min(lo(j) - gs, entry - fl), up(j) - gt
            if not st < entry or (ch_tp_on and not tp > entry): return None
        else:
            st, tp = max(up(j) + gs, entry + fl), lo(j) + gt
            if not st > entry or (ch_tp_on and not tp < entry): return None
        if ch_tp_on and P.get("ch_min_rr", 0.0) and abs(tp - entry) < P["ch_min_rr"] * abs(entry - st): return None
        return float(st), float(tp), float(gs), float(gt)

    def chan_tp(side, ch, j, entry, tag):
        """Цель по рисунку, когда стоп не по каналу. Отбой ('b'/нет метки): противоположная граница. Пробой ('k'): граница + k_tp_mult x ширина канала (замер движения; 0 = без цели, ведёт трейлинг). None, если цель позади цены."""
        lo, up = ch
        if tag == "k":
            m = float(P.get("k_tp_mult", 1.0))
            if m <= 0: return None
            w = up(j) - lo(j)
            tp = up(j) + m * w if side == "L" else lo(j) - m * w
        else:
            tp = up(j) if side == "L" else lo(j)
        if (side == "L" and not tp > entry) or (side == "S" and not tp < entry): return None
        return float(tp)

    def sig3(side, si, entry):  # стоп за экстремумом 3 свечей до сигнальной включительно −0.2 ATR, не ближе 0.5 ATR
        a = atr[si]
        if side == "L":
            return min(l[si - 2:si + 1].min() - 0.2 * a, entry - 0.5 * a)
        return max(h[si - 2:si + 1].max() + 0.2 * a, entry + 0.5 * a)

    def mkpos(side, i, entry, st, clamped, ai):
        p_ = dict(side=side, i_in=i, t_in=int(t[i]), p_in=entry, stop0=float(st), stop=float(st), stage="init",
                  risk=abs(entry - st) / entry * 100, mfe=0.0, mae=0.0, be=False, clamped=clamped, ext=entry, ptrail=False,
                  be_thr=(P.get("be_atr", 0) * atr[ai] / entry * 100) if P.get("be_atr", 0) else P["be_trigger"],
                  atr=float(atr[ai]))  # ATR входного ТФ на сигнальной свече — для расстояний стоп/цель в ATR
        if P.get("tp_r") and not ch_tp_on:
            p_["tp"] = entry + (1 if side == "L" else -1) * P["tp_r"] * abs(entry - st)
        return p_
    st_sigs = stage_signals(pre, P) if P.get("entry_mode") == "stages" else None
    chan = pre.get("_chan") or {}  # линии считаются в stage_signals — читаем после него
    sids_ = pre.get("_sid") or {}
    tags_ = pre.get("_tag") or {}  # {свеча: 'b'|'k'} для hand_both

    def finish(i, price, reason):
        nonlocal pos, pos_ch, pos_vis
        pos_ch = None
        if pos_vis is not None:
            pos["chl"] = _chl(pos_vis, pos["i_in"], min(i, T - 1))
            pos["chlw"] = _chlw(pos_vis, pos["i_in"])
            pos_vis = None
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
            ch_ = pend_ch; pend_ch = None
            tg_ = pend_tag; pend_tag = None
            sd_ = pend_sid; pend_sid = None
            if xc and pos and pos["side"] != xc:
                finish(i, o[i], "разворот")
            if pos is None and side and allow:
                entry = float(o[i])
                clamped = False
                lv = None
                use_ch = ch_stop_on and ch_ is not None and tg_ != "k"  # у пробоя стоп по линии канала не годится (линия позади цены) — берём обычный стоп
                if use_ch:
                    lv = ch_levels(side, ch_, i, entry, atr[i - 1])
                if use_ch:
                    st = lv[0] if lv else None
                elif P["stop_mode"] == "pivot":
                    st = _last_piv(piv, "L", i - 1, lambda p: p < entry) if side == "L" else _last_piv(piv, "H", i - 1, lambda p: p > entry)
                elif P["stop_mode"] == "pct":
                    st = entry * (1 - P["min_stop_pct"] / 100) if side == "L" else entry * (1 + P["min_stop_pct"] / 100)
                elif P["stop_mode"] == "sig3":
                    st = sig3(side, i - 1, entry)
                else:
                    mind = max(entry * P["min_stop_pct"] / 100, P["min_stop_atr"] * atr[i - 1])
                    if side == "L":
                        st = min(l[i - 1], entry - mind); clamped = bool(st != l[i - 1])
                    else:
                        st = max(h[i - 1], entry + mind); clamped = bool(st != h[i - 1])
                if st is not None:
                    pos = mkpos(side, i, entry, st, clamped, i - 1)
                    pos_vis = ch_
                    if tg_: pos["sig"] = tg_
                    if sd_: pos["sid"] = sd_
                    if not lv and ch_tp_on and ch_ is not None:  # стоп не по каналу (prev/sig3/...), а цель по каналу — раньше цель в этом случае не ставилась вообще
                        tpx_ = chan_tp(side, ch_, i, entry, tg_)
                        if tpx_ is not None: pos["tp"] = tpx_
                    if lv:
                        pos_ch = ch_; pos["ch_gap_s"], pos["ch_gap_t"] = lv[2], lv[3]
                        if ch_tp_on: pos["tp"] = lv[1]
        if bo is not None and pos is None:  # вход по пробою экстремума сигнальной свечи
            bside, si, bloc = bo
            if i > si:
                if i > si + 1:  # отмена только по уже закрытым свечам: закрытие за EMA50 или пробит локальный экстремум
                    pc = i - 1
                    if (bside == "L" and (c[pc] < e50[pc] or l[pc] < bloc)) or (bside == "S" and (c[pc] > e50[pc] or h[pc] > bloc)):
                        bo = None
                if bo is not None and i > si + int(P.get("bo_wait", 3)):
                    bo = None
                if bo is not None:
                    trig = h[si] if bside == "L" else l[si]
                    if (bside == "L" and h[i] >= trig) or (bside == "S" and l[i] <= trig):
                        entry = float(max(o[i], trig) if bside == "L" else min(o[i], trig))
                        lv = ch_levels(bside, bo_ch, i, entry, atr[si]) if (ch_stop_on and bo_ch is not None) else None
                        if ch_stop_on and bo_ch is not None and not lv:
                            bo = None
                        else:
                            pos = mkpos(bside, i, entry, lv[0] if lv else sig3(bside, si, entry), False, si)
                            pos["bo"] = True
                            pos_vis = bo_ch
                            if lv:
                                pos_ch = bo_ch; pos["ch_gap_s"], pos["ch_gap_t"] = lv[2], lv[3]
                                if ch_tp_on: pos["tp"] = lv[1]
                            bo = None
        elif bo is not None:
            bo = None
        if pos is not None and "tp0" not in pos:
            pos["tp0"] = pos.get("tp")  # цель в момент входа (дальше она может ползти за каналом) — для честного анализа расстояния до цели
            if pos.get("tp0") and P.get("be_tp_frac"):  # точка БУ не дальше be_tp_frac от пути до цели (иначе при цели ближе be_trigger БУ не взводится никогда)
                d_ = abs(pos["tp0"] - pos["p_in"]) / pos["p_in"] * 100
                pos["be_thr"] = min(pos["be_thr"], float(P["be_tp_frac"]) * d_)
            if pos_vis is not None:  # только для журнала (на сделки не влияет): удаление входа от линии, ширина канала в ATR, ближайший пивот по ходу сделки
                try:
                    lo_x, up_x = pos_vis
                    wx = float(up_x(i) - lo_x(i)); e_ = pos["p_in"]; S_ = pos["side"] == "S"
                    bx = float(up_x(i) if (S_ == (pos.get("sig") == "b")) else lo_x(i))  # пробой шорта — нижняя линия, отбой шорта — верхняя (лонг наоборот)
                    if wx > 0:
                        pos["x_ext"] = abs(e_ - bx) / wx
                        if pos.get("atr"): pos["x_wat"] = wx / pos["atr"]
                    pv_ = _last_piv(piv, "L" if S_ else "H", i, lambda p: (p < e_) if S_ else (p > e_))
                    if pv_ is not None:
                        pos["x_pv"] = abs(e_ - pv_) / e_ * 100
                        if pos.get("atr"): pos["x_pvat"] = abs(e_ - pv_) / pos["atr"]
                except Exception:
                    pass
        if pos and mcl:
            mc_ = mcl.get("%d|%s" % (pos["t_in"], pos["side"]))
            if mc_ and (i == T - 1 or int(t[i]) + tfms_ > mc_[0]):  # свеча, в которой нажали «Закрыть» (или позже): выход по цене момента нажатия
                finish(i, mc_[1], mc_[2])
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
            elif pos.get("tp") and not (pos.get("bo") and pos["i_in"] == i) and ((L_ and h[i] >= pos["tp"]) or ((not L_) and l[i] <= pos["tp"])):
                finish(i, pos["tp"], "цель")
            else:
                pos["mfe"] = max(pos["mfe"], fav)
                pos["ext"] = max(pos["ext"], h[i]) if L_ else min(pos["ext"], l[i])
                if (not pos["be"]) and fav >= pos["be_thr"]:
                    pos["be"], pos["stop"], pos["stage"] = True, e * (1 + (1 if L_ else -1) * P.get("be_lock", 0) / 100), "be"
                    if P.get("be_intrabar") and ((L_ and c[i] <= pos["stop"]) or ((not L_) and c[i] >= pos["stop"])):
                        # свеча взвела БУ и закрылась по ту сторону БУ-стопа: цена пересекла стоп уже после экстремума, значит выход по цене стопа в этой же свече
                        finish(i, pos["stop"], "безубыток")
                if pos is not None:
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
                    if pos_ch is not None and P.get("ch_follow") and i + 1 < T:  # стоп/цель следуют за наклонными линиями канала (стоп только подтягивается)
                        j_ = i + 1
                        lo_, up_ = pos_ch
                        if pos["stage"] == "init":
                            q_ = (lo_(j_) - pos["ch_gap_s"]) if L_ else (up_(j_) + pos["ch_gap_s"])
                            if (L_ and q_ > pos["stop"] and q_ < c[i]) or ((not L_) and q_ < pos["stop"] and q_ > c[i]):
                                pos["stop"] = float(q_)
                        if ch_tp_on:
                            tq_ = (up_(j_) - pos["ch_gap_t"]) if L_ else (lo_(j_) + pos["ch_gap_t"])
                            if (L_ and tq_ > c[i]) or ((not L_) and tq_ < c[i]):
                                pos["tp"] = float(tq_)
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
        if pos and P.get("max_bars") and i - pos["i_in"] >= P["max_bars"]:
            finish(i, c[i], "время")  # выход по времени: закрытие свечи через max_bars свечей после входа
        if P["warmup"] <= i < M:
            em = P.get("entry_mode", "cross200")
            if em == "stages":
                g = st_sigs.get(i)
                if g:
                    xc = en = None
                    if pos is None:
                        en = g[0]
                    elif pos["side"] != g[0] and P.get("rev_exit", True):
                        xc = en = g[0]
                    if xc or en:
                        allow_ = (filt is None) or (en is None) or bool(filt(en, i))
                        if P.get("entry_trigger") == "breakout":
                            if xc: pend = (xc, None, False)  # закрыть противоположную позицию по открытию
                            if en and allow_:
                                bo = (en, i, float(l[i - 2:i + 1].min()) if en == "L" else float(h[i - 2:i + 1].max()))
                                bo_ch = chan.get(g[1])
                        else:
                            pend = (xc, en, allow_)
                            pend_ch = chan.get(g[1])
                            pend_tag = tags_.get(g[1])
                            pend_sid = sids_.get(g[1])
            elif em == "pattern20":
                xc = en = None
                na = "L" if (i in bull and i not in bear) else "S" if (i in bear and i not in bull) else None
                if na:
                    parm = (na, i + int(P.get("arm_k", 12)))
                elif parm is not None:
                    if i > parm[1]:
                        parm = None
                    elif (parm[0] == "L" and c[i] > e20[i]) or (parm[0] == "S" and c[i] < e20[i]):
                        if pos is None:
                            en = parm[0]
                        elif pos["side"] != parm[0] and P.get("rev_exit", True):
                            xc = en = parm[0]
                        parm = None
                if xc or en:
                    pend = (xc, en, (filt is None) or (en is None) or bool(filt(en, i)))
            else:
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
        if pos_vis is not None:
            pos["chl"] = _chl(pos_vis, pos["i_in"], T - 1)
            pos["chlw"] = _chlw(pos_vis, pos["i_in"])
        s = 1 if pos["side"] == "L" else -1
        gross = s * (c[T - 1] / pos["p_in"] - 1) * 100
        pos.update(i_out=T - 1, t_out=int(t[T - 1]), p_out=float(c[T - 1]), reason="открыта", gross=gross, net=gross - fee2, open=True)
        trades.append(pos)
    return trades


def _chlw(ch, a):
    """Канал на 80 свечей назад от входа: [нижняя, верхняя в начале, нижняя, верхняя при входе, индекс начала] — для рисунка предложения."""
    a0 = max(0, a - 80)
    w = _chl(ch, a0, a)
    return (w + [a0]) if w else None


def _chl(ch, a, b):
    """Линии канала сделки: [нижняя при входе, верхняя при входе, нижняя при выходе, верхняя при выходе] — для короткого фрагмента на графике."""
    try:
        lo, up = ch
        return [float(lo(a)), float(up(a)), float(lo(b)), float(up(b))]
    except Exception:
        return None


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
        if x.get("chl"):
            d["chl"] = [an._r(v) for v in x["chl"]]
        if x.get("sig"):
            d["sig"] = x["sig"]  # 'b' — отбой, 'k' — пробой (hand_both)
        if x.get("sid"):
            d["sid"] = x["sid"]  # id нарисованной пользователем структуры (hand.json)
        if x.get("tp"):
            d["tp"] = an._r(float(x["tp"]))
        if x.get("tp0"):
            d["tp0"] = an._r(float(x["tp0"]))
        xx = {k: round(float(x[k]), 3) for k in ("x_ext", "x_wat", "x_pv", "x_pvat") if x.get(k) is not None and x[k] == x[k]}
        if xx:
            d["x"] = xx  # журнал для анализа: x_ext (вход от линии, в ширинах канала), x_wat (ширина канала, ATR), x_pv (до ближайшего пивота, %), x_pvat (то же в ATR)
        if x.get("atr") and x["atr"] == x["atr"] and x["atr"] > 0:
            d["atr"] = round(float(x["atr"]) / float(x["p_in"]) * 100, 4)  # ATR в % от цены входа
        out.append(d)
    return out
