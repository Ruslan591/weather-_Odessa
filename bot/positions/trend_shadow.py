# -*- coding: utf-8 -*-
"""Режим «тень» (задача 1): сигнал тренда пишется в заявку, правила НЕ меняются.
Счёт тренда -4..+4 как в pos_watch (цена к EMA50, EMA20 к EMA50, наклон EMA50, EMA50 к EMA200) на закрытых свечах.
Для заявки пишем: BTC и ETH на 5m и 15m, сама пара на 15m и 1h, согласие с направлением заявки (yes/no/neutral, порог |счёт|>=2)
и время последней смены состояния счёта (flip_t) - по нему потом меряем, разворачиваются ли BTC/ETH раньше пары."""
import time
import pos
TFMS = {"5m": 300000, "15m": 900000, "1h": 3600000}
THR = 2; TTL = 60; _c = {}

def _ema(v, n):
    k = 2.0 / (n + 1); e = v[0]; o = []
    for x in v:
        e = x * k + e * (1 - k); o.append(e)
    return o

def score_series(c):
    """Счёт тренда по каждому индексу (None, пока нет 200 свечей)."""
    e20 = _ema(c, 20); e50 = _ema(c, 50); e200 = _ema(c, 200); out = [None] * len(c)
    for i in range(205, len(c)):
        out[i] = (1 if c[i] > e50[i] else -1) + (1 if e20[i] > e50[i] else -1) + (1 if e50[i] > e50[i - 5] else -1) + (1 if e50[i] > e200[i] else -1)
    return out

def _state(s): return 1 if s >= THR else (-1 if s <= -THR else 0)

def snap(sym, tf, now=None):
    now = now or int(time.time() * 1000); key = (sym, tf); h = _c.get(key)
    if h and time.time() - h[0] < TTL: return h[1]
    d = [k for k in pos.kl(sym + "USDT", tf, 400) if int(k[0]) + TFMS[tf] <= now]
    c = [float(k[4]) for k in d]; ss = score_series(c); i = len(c) - 1
    if i < 205 or ss[i] is None: r = None
    else:
        st = _state(ss[i]); j = i
        while j > 205 and _state(ss[j - 1]) == st: j -= 1
        r = {"s": int(ss[i]), "state": st, "flip_t": int(d[j][0]), "flip_to": st}
    _c[key] = (time.time(), r); return r

def agree(side, s):
    if s is None: return None
    want = 1 if side == "long" else -1; st = _state(s)
    return "yes" if st == want else ("no" if st == -want else "neutral")

def shadow(sym, side):
    """Снимок тренда на момент решения. Любая ошибка по одному ряду: поле None."""
    out = {"btc": {}, "eth": {}, "own": {}, "agree": {}, "ts": int(time.time() * 1000)}
    for name, s_, tfs in (("btc", "BTC", ("5m", "15m")), ("eth", "ETH", ("5m", "15m")), ("own", sym, ("15m", "1h"))):
        for tf in tfs:
            try: r = snap(s_, tf)
            except Exception: r = None
            out[name][tf] = r
            out["agree"]["%s_%s" % (name, tf)] = agree(side, r["s"]) if r else None
    return out
