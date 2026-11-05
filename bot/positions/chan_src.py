# -*- coding: utf-8 -*-
"""Источники каналов для chan_orders.py (CHAN_SRC = afd | regr | combo). Порт Pine-скриптов TradingView на Python:
  afd   - Auto Trend Channels [AFD] (слой Swing: строгие пивоты swing=8, линия по двум одноимённым пивотам + параллель через самый далёкий
          противоположный пивот между ними, ширина 0.5..8 среднего TR(14), все свечи между якорями внутри с допуском 0.1 TR,
          канал ACTIVE с первого закрытия внутри, конец - закрытие за границей, одновременно один канал);
  regr  - Regression Channel Auto (ADXAE): линейная регрессия по close, окно 40..350 с максимальным |Пирсона|, границы +-2 sigma остатков (n-2),
          плоский при |наклон| < 0.03 ATR/свеча;
  combo - каналы AFD, но только когда направление регрессии совпадает с направлением AFD.
Интерфейс как у classic_trendline.structure_at: st_at(i) -> {type, lower, upper, channel{kind,upper,lower,t_main,t_clone,width,score,src,...}} | None.
Линии - кортежи (i1, p1, i2, p2, slope), как в classic_trendline (tl.at(L, j) = p1 + slope*(j - i1)). Состояние на i строится по свечам <= i (без заглядывания)."""
import numpy as np

SWING, POOL, HORIZON, VOLW = 8, 10, 600, 14
CONT, MINW, MAXW, PEND_WAIT = 0.10, 0.5, 8.0, 20
REG_LO, REG_HI, REG_K, REG_FLAT = 40, 350, 2.0, 0.03
_cache = {}


def _avg_tr(h, l, c, n=VOLW):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); tr[0] = h[0] - l[0]
    cs = np.cumsum(tr); out = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        out[i] = (cs[i] - (cs[i - n] if i >= n else 0.0)) / n
    return out


def afd_states(h, l, c):
    """states[i] = активный канал AFD после обработки закрытой свечи i (или None)."""
    n = len(c); sma = _avg_tr(h, l, c)
    highs, lows, pending, used = [], [], [], {}
    active = None; states = [None] * n

    def lower_at(ch, x):
        b = ch["ap"] + ch["slope"] * (x - ch["ai"]); return b if ch["dir"] == 1 else b - ch["w"]

    def upper_at(ch, x):
        b = ch["ap"] + ch["slope"] * (x - ch["ai"]); return b + ch["w"] if ch["dir"] == 1 else b

    for i in range(n):
        vol = sma[i]
        for k in [k for k, v in used.items() if i - v > HORIZON]: del used[k]
        pending[:] = [p for p in pending if i - p["ai"] <= HORIZON and i - p["built"] <= PEND_WAIT]
        if active:
            if i - active["ai"] > HORIZON: active = None
            elif i > active["avail"] and (c[i] > upper_at(active, i) or c[i] < lower_at(active, i)): active = None
        ctr = i - SWING; newp = None
        if ctr - SWING >= 0:
            sh = h[ctr - SWING:i + 1]; sl = l[ctr - SWING:i + 1]
            hp = bool((sh < h[ctr]).sum() == len(sh) - 1); lp = bool((sl > l[ctr]).sum() == len(sl) - 1)
            if hp != lp:
                newp = (ctr, h[ctr] if hp else l[ctr], "H" if hp else "L"); (highs if hp else lows).append((ctr, newp[1]))
        for arr in (highs, lows):
            while arr and (i - arr[0][0] > HORIZON or len(arr) > POOL): arr.pop(0)
        if newp and not np.isnan(vol) and vol > 0:
            same, opp = (highs, lows) if newp[2] == "H" else (lows, highs); d = -1 if newp[2] == "H" else 1; ci, cp = newp[0], newp[1]
            for (ai, ap) in same[:-1]:
                if not (ci - ai >= 2 * SWING and i - ai <= HORIZON and d * (cp - ap) > 0): continue
                slope = (cp - ap) / (ci - ai); w, bi = 0.0, None
                for (pi_, pp) in opp:
                    if ai < pi_ < ci:
                        r = d * (pp - (ap + slope * (pi_ - ai)))
                        if r > w: w, bi = r, pi_
                if bi is None or w < MINW * vol or w > MAXW * vol: continue
                xs = np.arange(ai, ci + 1); base = ap + slope * (xs - ai)
                upp = base + w if d == 1 else base; low = base if d == 1 else base - w
                if (h[ai:ci + 1] > upp + CONT * vol).any() or (l[ai:ci + 1] < low - CONT * vol).any(): continue
                pending.append(dict(ai=ai, ap=ap, ci=ci, cp=cp, bi=bi, dir=d, slope=slope, w=w, vol=vol, built=i, key=(d, ai, bi, ci)))
            while len(pending) > 32: pending.pop(0)
        if active is None and not np.isnan(vol):
            best, bk = None, None
            for p in pending:
                if p["key"] in used: continue
                lo_, hi_ = lower_at(p, i), upper_at(p, i)
                if not (lo_ <= c[i] <= hi_): continue
                dist = abs(c[i] - (lo_ + p["w"] * 0.5)) / p["w"]
                k = (p["ci"], -dist, p["ci"] - p["ai"], -p["bi"], p["dir"])
                if bk is None or k > bk: best, bk = p, k
            if best is not None:
                pending.remove(best); best["avail"] = i; used[best["key"]] = best["ai"]; active = best
        states[i] = active
    return states


def regression_at(c, atr, k):
    """Регрессия по закрытиям до свечи k включительно: dict(win, r, slope, i1, v1, vk, sd, dir) или None."""
    if k + 1 < REG_LO + 2: return None
    hi_n = min(REG_HI, k + 1); y = c[k - hi_n + 1:k + 1][::-1]; xs = np.arange(hi_n, dtype=float)
    Sx = np.cumsum(xs); Sxx = np.cumsum(xs * xs); Sy = np.cumsum(y); Sxy = np.cumsum(xs * y); Syy = np.cumsum(y * y)
    Ls = np.arange(REG_LO, hi_n + 1); idx = Ls - 1
    vx = Sxx[idx] - Sx[idx] ** 2 / Ls; vy = Syy[idx] - Sy[idx] ** 2 / Ls; cv = Sxy[idx] - Sx[idx] * Sy[idx] / Ls
    ok = (vx > 0) & (vy > 0)
    if not ok.any(): return None
    r = np.where(ok, np.abs(cv) / np.sqrt(np.where(ok, vx * vy, 1.0)), -1.0); m = int(np.argmax(r)); Lb = int(Ls[m])
    rev = cv[m] / vx[m]; sse = max(vy[m] - rev * cv[m], 0.0); sd = float(np.sqrt(sse / max(Lb - 2, 1)))
    meanY = Sy[idx[m]] / Lb; meanX = (Lb - 1) / 2.0; slope = -rev
    vk = meanY - rev * meanX; i1 = k - Lb + 1; v1 = vk - slope * (Lb - 1)
    th = REG_FLAT * float(atr[k]); d = 1 if slope > th else (-1 if slope < -th else 0)
    return dict(win=Lb, r=float(r[m]), slope=float(slope), i1=i1, v1=float(v1), vk=float(vk), sd=sd, dir=d)


def _touches(h, l, atr, up, lo, a, b):
    tu = tl_ = 0
    for j in range(max(a, 0), b + 1):
        tol = 0.35 * float(atr[j])
        if abs(h[j] - (up[1] + up[4] * (j - up[0]))) <= tol: tu += 1
        if abs(l[j] - (lo[1] + lo[4] * (j - lo[0]))) <= tol: tl_ += 1
    return tu, tl_


def _afd_struct(ch, h, l, atr, k, src, reg=None):
    d, ai, ap, ci, cp, s, w = ch["dir"], ch["ai"], ch["ap"], ch["ci"], ch["cp"], ch["slope"], ch["w"]
    main = (ai, ap, ci, ap + s * (ci - ai), s)
    if d == -1: up_, lo_ = main, (ai, ap - w, ci, ap - w + s * (ci - ai), s); kind = "down"; tm, tc = _touches(h, l, atr, up_, lo_, ai, k)
    else: lo_, up_ = main, (ai, ap + w, ci, ap + w + s * (ci - ai), s); kind = "up"; tc, tm = _touches(h, l, atr, up_, lo_, ai, k)
    if d == -1: tmain, tclone = tm, tc
    else: tmain, tclone = tm, tc
    chd = dict(kind=kind, upper=up_, lower=lo_, t_main=tmain, t_clone=tclone, width=w / max(float(atr[k]), 1e-12), score=0.0, src=src)
    if reg: chd.update(reg_slope_atr=reg["slope"] / max(float(atr[k]), 1e-12), reg_win=reg["win"], reg_r=reg["r"])
    return {"type": "channel_down" if d == -1 else "channel_up", "lower": lo_, "upper": up_, "channel": chd}


def make_st_at(src, key, t, h, l, c, atr):
    """key - (символ) для кэша; пересчёт AFD один раз на последнюю закрытую свечу."""
    M = len(c)
    if src in ("afd", "combo"):
        ck = (src if src == "afd" else "afd", key, int(t[-1]))
        if ck not in _cache:
            for k in [k for k in _cache if k[1] == key]: del _cache[k]
            _cache[ck] = afd_states(h, l, c)
        states = _cache[ck]

        def st_at(i):
            ch = states[i] if 0 <= i < M else None
            if not ch: return None
            reg = None
            if src == "combo":
                reg = regression_at(c, atr, i)
                if not reg or reg["dir"] != ch["dir"]: return None
            return _afd_struct(ch, h, l, atr, i, src, reg)
        return st_at

    def st_reg(i):
        g = regression_at(c, atr, i)
        if not g or g["dir"] == 0: return {"type": "range", "lower": None, "upper": None, "channel": None} if g else None
        k2 = REG_K * g["sd"]; s = g["slope"]
        up_ = (g["i1"], g["v1"] + k2, i, g["vk"] + k2, s); lo_ = (g["i1"], g["v1"] - k2, i, g["vk"] - k2, s)
        tu, tlw = _touches(h, l, atr, up_, lo_, g["i1"], i); kind = "down" if g["dir"] < 0 else "up"
        chd = dict(kind=kind, upper=up_, lower=lo_, t_main=tu if kind == "down" else tlw, t_clone=tlw if kind == "down" else tu,
                   width=2 * k2 / max(float(atr[i]), 1e-12), score=100.0 * g["r"], src="regr", reg_win=g["win"], reg_r=g["r"], reg_slope_atr=s / max(float(atr[i]), 1e-12))
        return {"type": "channel_down" if kind == "down" else "channel_up", "lower": lo_, "upper": up_, "channel": chd}
    return st_reg
