"""classic_analysis.py — «классический» анализ свечей: индикаторы, pivot, уровни, тренд, свечные паттерны.
Все расчёты — только по ЗАКРЫТЫМ свечам (формирующаяся свеча в анализе не участвует).
Pivot подтверждается через PIV_N свечей после экстремума (т.е. бот видит его с задержкой — это честно)."""
import numpy as np
import pandas as pd

PIV_N = 5

PAT_INFO = {
    "hammer":     ("Молот", "Мол", 1),
    "shooting":   ("Падающая звезда", "ПЗ", -1),
    "bull_eng":   ("Бычье поглощение", "П↑", 1),
    "bear_eng":   ("Медвежье поглощение", "П↓", -1),
    "morning":    ("Утренняя звезда", "УЗ", 1),
    "evening":    ("Вечерняя звезда", "ВЗ", -1),
    "doji":       ("Доджи", "Д", 0),
}


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi_calc(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr_calc(df, n=14):
    pc = df.c.shift(1)
    tr = pd.concat([df.h - df.l, (df.h - pc).abs(), (df.l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def indicators(df):
    c = df.c
    ind = {
        "ema20": ema(c, 20), "ema50": ema(c, 50), "ema200": ema(c, 200),
        "rsi": rsi_calc(c), "atr": atr_calc(df),
    }
    ma = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    ind["bbm"], ind["bbu"], ind["bbl"] = ma, ma + 2 * sd, ma - 2 * sd
    m = ema(c, 12) - ema(c, 26)
    sg = ema(m, 9)
    ind["macd"], ind["sig"], ind["hist"] = m, sg, m - sg
    return ind


def find_pivots(df, n=PIV_N):
    h, l = df.h.values, df.l.values
    out = []
    for i in range(n, len(df) - n):
        if h[i] >= h[i - n:i + n + 1].max() and (h[i - n:i] < h[i]).all():
            out.append({"i": i, "p": float(h[i]), "k": "H", "conf": i + n})
        if l[i] <= l[i - n:i + n + 1].min() and (l[i - n:i] > l[i]).all():
            out.append({"i": i, "p": float(l[i]), "k": "L", "conf": i + n})
    return out


def calc_trend(df, ind, piv):
    c = float(df.c.iloc[-1])
    atr = float(ind["atr"].iloc[-1])
    e20, e50, e200 = (float(ind[k].iloc[-1]) for k in ("ema20", "ema50", "ema200"))
    score, maxs, why = 0, 0, []

    maxs += 1
    if c > e50: score += 1; why.append("+ цена выше EMA50")
    else: score -= 1; why.append("− цена ниже EMA50")
    maxs += 1
    if e20 > e50: score += 1; why.append("+ EMA20 выше EMA50")
    else: score -= 1; why.append("− EMA20 ниже EMA50")
    if len(df) > 12 and atr > 0:
        maxs += 1
        sl = (float(ind["ema50"].iloc[-1]) - float(ind["ema50"].iloc[-11])) / (10 * atr)
        if sl > 0.03: score += 1; why.append("+ EMA50 растёт")
        elif sl < -0.03: score -= 1; why.append("− EMA50 падает")
        else: why.append("0 EMA50 плоская")
    if len(df) >= 200:
        maxs += 1
        if e50 > e200: score += 1; why.append("+ EMA50 выше EMA200")
        else: score -= 1; why.append("− EMA50 ниже EMA200")
    H = [p for p in piv if p["k"] == "H"][-2:]
    Lw = [p for p in piv if p["k"] == "L"][-2:]
    struct = "н/д"
    if len(H) == 2 and len(Lw) == 2:
        maxs += 2
        hh, hl = H[1]["p"] > H[0]["p"], Lw[1]["p"] > Lw[0]["p"]
        if hh and hl: score += 2; struct = "HH+HL"; why.append("+ структура: HH+HL (рост)")
        elif (not hh) and (not hl): score -= 2; struct = "LH+LL"; why.append("− структура: LH+LL (падение)")
        else: struct = "HH+LL" if hh else "LH+HL"; why.append("0 структура смешанная (%s)" % struct)
    thr = max(2, round(maxs * 0.5))
    d = "up" if score >= thr else "down" if score <= -thr else "flat"
    return {"dir": d, "score": score, "max": maxs, "why": why, "struct": struct}


def calc_levels(df, piv, atr, price, lookback=400):
    last_i = len(df) - 1
    pts = [p for p in piv if p["i"] >= last_i - lookback]
    if not pts:
        return []
    tol = max(0.6 * atr, price * 0.0015)
    pts.sort(key=lambda p: p["p"])
    groups, cur = [], [pts[0]]
    for p in pts[1:]:
        if p["p"] - np.mean([q["p"] for q in cur]) <= tol:
            cur.append(p)
        else:
            groups.append(cur); cur = [p]
    groups.append(cur)
    lv = []
    for g in groups:
        ps = [q["p"] for q in g]
        age = last_i - max(q["i"] for q in g)
        score = len(g) + (1.0 if age < 50 else 0.5 if age < 150 else 0.0)
        lv.append({"p": float(np.mean(ps)), "lo": min(ps) - 0.1 * atr, "hi": max(ps) + 0.1 * atr,
                   "n": len(g), "age": int(age), "score": score,
                   "k": "R" if np.mean(ps) > price else "S"})
    keep = [x for x in lv if x["n"] >= 2]
    below = sorted([x for x in lv if x["p"] <= price], key=lambda x: -x["p"])[:1]
    above = sorted([x for x in lv if x["p"] > price], key=lambda x: x["p"])[:1]
    for x in below + above:
        if x not in keep: keep.append(x)
    keep = sorted(keep, key=lambda x: -x["score"])[:12]
    keep.sort(key=lambda x: x["p"])
    for x in keep:
        x["dist"] = (x["p"] - price) / price * 100
    return keep


def detect_patterns(df, ind):
    o, h, l, c = df.o.values, df.h.values, df.l.values, df.c.values
    e20, atr = ind["ema20"].values, ind["atr"].values
    out = []
    for i in range(2, len(df)):
        a = atr[i]
        rng = h[i] - l[i]
        if not (a > 0) or rng <= 0:
            continue
        body = abs(c[i] - o[i])
        upw = h[i] - max(o[i], c[i])
        low = min(o[i], c[i]) - l[i]
        dctx = c[i - 1] < e20[i - 1]
        uctx = c[i - 1] > e20[i - 1]
        found = []
        if rng >= 0.6 * a and body <= 0.1 * rng:
            found.append("doji")
        elif rng >= 0.7 * a and body <= 0.35 * rng:
            if low >= 0.6 * rng and upw <= 0.2 * rng and dctx: found.append("hammer")
            elif upw >= 0.6 * rng and low <= 0.2 * rng and uctx: found.append("shooting")
        pb = abs(c[i - 1] - o[i - 1])
        if c[i - 1] < o[i - 1] and c[i] > o[i] and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body > pb and body >= 0.6 * a and dctx:
            found.append("bull_eng")
        if c[i - 1] > o[i - 1] and c[i] < o[i] and c[i] <= o[i - 1] and o[i] >= c[i - 1] and body > pb and body >= 0.6 * a and uctx:
            found.append("bear_eng")
        b2 = abs(c[i - 2] - o[i - 2])
        if b2 >= 0.7 * a and pb <= 0.35 * b2:
            mid = (o[i - 2] + c[i - 2]) / 2
            if c[i - 2] < o[i - 2] and c[i] > o[i] and c[i] > mid and c[i - 2] < e20[i - 2]: found.append("morning")
            if c[i - 2] > o[i - 2] and c[i] < o[i] and c[i] < mid and c[i - 2] > e20[i - 2]: found.append("evening")
        for k in found:
            nm, code, d = PAT_INFO[k]
            out.append({"i": i, "k": k, "n": nm, "c": code, "d": d})
    return out


def _r(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float("%.8g" % x)


def _lst(s, start):
    return [_r(float(x)) if not pd.isna(x) else None for x in s.values[start:]]


def analyze(df, keep=500):
    """df — только закрытые свечи (колонки t,o,h,l,c,v)."""
    if len(df) < 60:
        raise ValueError("мало свечей (%d), нужно минимум 60" % len(df))
    ind = indicators(df)
    piv = find_pivots(df)
    price = float(df.c.iloc[-1])
    atr = float(ind["atr"].iloc[-1])
    tr = calc_trend(df, ind, piv)
    lv = calc_levels(df, piv, atr, price)
    pats = detect_patterns(df, ind)
    st = max(0, len(df) - keep)
    res = {"t": [int(x) for x in df.t.values[st:]]}
    for k in "ohlcv":
        res[k] = _lst(df[k], st)
    for k in ("ema20", "ema50", "ema200", "bbu", "bbm", "bbl", "rsi", "macd", "sig", "hist"):
        res[k] = _lst(ind[k], st)
    res["pivots"] = [{"i": p["i"] - st, "p": _r(p["p"]), "k": p["k"], "conf": p["conf"] - st} for p in piv if p["i"] >= st]
    res["patterns"] = [dict(p, i=p["i"] - st) for p in pats if p["i"] >= st]
    res["levels"] = [{k: (_r(v) if isinstance(v, float) else v) for k, v in x.items()} for x in lv]
    res["trend"] = tr
    res["atr"] = _r(atr)
    res["last"] = _r(price)
    return res


def summary(df):
    ind = indicators(df)
    piv = find_pivots(df)
    tr = calc_trend(df, ind, piv)
    c = float(df.c.iloc[-1])
    return {"dir": tr["dir"], "score": tr["score"], "max": tr["max"], "struct": tr["struct"],
            "rsi": _r(float(ind["rsi"].iloc[-1])), "atrp": _r(float(ind["atr"].iloc[-1]) / c * 100),
            "vs50": _r((c / float(ind["ema50"].iloc[-1]) - 1) * 100), "close": _r(c)}
