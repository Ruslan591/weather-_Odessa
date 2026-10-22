"""classic_fastchan.py — «быстрый канал» по правилу пользователя (2026-10-22).

Канал = три чередующихся экстремума (низ-верх-низ или верх-низ-верх): главная линия через 1-ю и 3-ю точки, параллельная — через 2-ю.
Пивот подтверждается быстро: L свечей слева ниже/выше, R свечей справа (по умолчанию L=2, R=1) — т.е. канал чертится уже на следующей свече после третьей точки.
Пробой — ТЕЛОМ: закрытие свечи за линией (с допуском tol*ATR); тень пробоем не считается. После пробоя канал снимается и строится заново
только по экстремумам, возникшим на/после свечи пробоя.
Опорная цена экстремума: хвост (high/low) или край тела. Правило хвост/тело: тень «аномальная», если она длиннее тела в k раз (и не меньше 0.3 ATR)
или длиннее m*ATR. Если аномальна тень у любой из трёх точек — ВСЕ три точки берутся по телам (хвост-с-хвостом или тело-с-телом, не вперемешку),
иначе по хвостам. Линии могут пробивать тени, но не должны резать тела (проверка по телам от 1-й точки до текущей свечи).
Всё считается только по закрытым свечам до i включительно (без заглядывания вперёд).
"""
import numpy as np

FC = {"L": 2, "R": 1, "k": 2.0, "m": 1.0, "minw": 0.8, "maxw": 8.0, "tol": 0.15, "anomaly": 1, "after": 1, "dev": 0.5, "redraw": 1, "btol": 0.0, "deep": 6}  # anomaly=0 — всегда хвосты, 2 — всегда тела


def at(line, j):
    return line[1] + line[4] * (j - line[0])


def _anom(o, h, l, c, atr, cfg):
    bh, bl = np.maximum(o, c), np.minimum(o, c)
    body = bh - bl

    def f(w):  # тень аномальна: длиннее m*ATR, либо длиннее k тел (только если тело заметное: >= 0.2 ATR — у дожи отношение к телу бессмысленно) и не короче 0.4 ATR
        return ((w > cfg["k"] * body) & (body >= 0.2 * atr) & (w >= 0.4 * atr)) | (w > cfg["m"] * atr)
    return f(h - bh), f(bl - l)


def find_pivots(o, h, l, c, cfg):
    """Все свинги: {i, k:'H'|'L', conf}. conf = i+R — свеча, на закрытии которой пивот уже известен."""
    L, R, n = int(cfg["L"]), int(cfg["R"]), len(h)
    out = []
    for i in range(L, n - R):
        isH = h[i] > h[i - L:i].max() and h[i] >= h[i + 1:i + R + 1].max()
        isL = l[i] < l[i - L:i].min() and l[i] <= l[i + 1:i + R + 1].min()
        pair = [("H", isH), ("L", isL)]
        if isH and isL and c[i] >= o[i]:  # внешняя свеча: бычья — сначала низ, потом верх
            pair = [("L", isL), ("H", isH)]
        for k, ok in pair:
            if ok:
                out.append({"i": i, "k": k, "conf": i + R})
    return out


def _add_zz(zz, p, h, l, atr, dev):
    """Зигзаг: пивот противоположного типа принимается, только если ход от предыдущего пивота >= dev*ATR (мелкие колебания игнорируются, одноимённые пивоты сливаются в более экстремальный)."""
    pr = lambda q: h[q["i"]] if q["k"] == "H" else l[q["i"]]
    if zz and zz[-1]["k"] == p["k"]:
        a = zz[-1]
        better = h[p["i"]] > h[a["i"]] if p["k"] == "H" else l[p["i"]] < l[a["i"]]
        if better:
            zz[-1] = p
        return
    if zz and abs(pr(p) - pr(zz[-1])) < dev * atr[p["i"]]:
        return
    zz.append(p)


def _bodymode(pa, pb, cfg, anH, anL):
    if cfg["anomaly"] == 2:
        return True
    if cfg["anomaly"] == 0:
        return False
    return any((anH if p["k"] == "H" else anL)[p["i"]] for p in (pa, pb))


def _price(o, h, l, c, p, body):
    j = p["i"]
    if p["k"] == "H":
        return float(max(o[j], c[j]) if body else h[j])
    return float(min(o[j], c[j]) if body else l[j])


def _own(o, h, l, c, p, cfg, anH, anL):
    """Опорная цена пивота по его собственной тени (хвост, а при аномальной тени — тело)."""
    return _price(o, h, l, c, p, _bodymode(p, p, cfg, anH, anL))


def _try(o, h, l, c, atr, i, p1, p2, p3, cfg, anH, anL):
    pts = (p1, p2, p3)
    body = _bodymode(p1, p3, cfg, anH, anL)  # главная линия: обе точки по хвостам или обе по телам
    a1, a2, a3 = _price(o, h, l, c, p1, body), _own(o, h, l, c, p2, cfg, anH, anL), _price(o, h, l, c, p3, body)
    if p3["i"] == p1["i"]:
        return None
    s = (a3 - a1) / (p3["i"] - p1["i"])
    off = a2 - (a1 + s * (p2["i"] - p1["i"]))
    side = p3["k"]  # L: главная линия — нижняя; H: главная — верхняя
    if (side == "L" and off <= 0) or (side == "H" and off >= 0):
        return None
    width = abs(off)
    if width < cfg["minw"] * atr[i] or width > cfg["maxw"] * atr[i]:
        return None
    main = (p1["i"], a1, p3["i"], a3, s)
    clone = (p1["i"], a1 + off, p3["i"], a3 + off, s)
    lower, upper = (main, clone) if side == "L" else (clone, main)
    # тела между 1-й точкой и текущей свечой не должны выходить за линии
    idx = np.arange(p1["i"], i + 1)
    tol = cfg["tol"] * atr[p1["i"]:i + 1]
    up = upper[1] + s * (idx - upper[0]); lo = lower[1] + s * (idx - lower[0])
    if (np.maximum(o, c)[p1["i"]:i + 1] > up + tol).any() or (np.minimum(o, c)[p1["i"]:i + 1] < lo - tol).any():
        return None
    mv = s * (i - p1["i"]) / atr[i]
    kind = "flat" if abs(mv) < 1.0 else ("up" if mv > 0 else "down")
    return {"upper": upper, "lower": lower, "kind": kind, "mode": "body" if body else "wick", "born": i, "pivots": [(p["i"], p["k"]) for p in pts], "width_atr": width / atr[i], "span": p3["i"] - p1["i"]}


def _build(o, h, l, c, atr, i, zz, floor, cfg, anH, anL):
    """Последний пивот P3 (подтверждён, не раньше свечи пробоя) + 1-я точка P1 того же типа из предыдущих deep пивотов + 2-я точка P2 = самый далёкий пивот
    противоположного типа между ними (так трейдер пропускает мелкие колебания). Из подходящих (линии не режут тела) берётся самый длинный канал."""
    if cfg["after"]:
        pool = zz
    else:
        pool = [p for p in zz if p["i"] >= floor]
    if len(pool) < 3:
        return None
    p3 = pool[-1]
    if p3["conf"] > i or p3["i"] < floor:
        return None
    best = None
    same = [q for q in pool[:-1] if q["k"] == p3["k"]][-int(cfg["deep"]):]
    for p1 in reversed(same):
        mid = [q for q in pool if p1["i"] < q["i"] < p3["i"] and q["k"] != p3["k"]]
        if not mid:
            continue
        ka = lambda q: _own(o, h, l, c, q, cfg, anH, anL)
        p2 = max(mid, key=ka) if p3["k"] == "L" else min(mid, key=ka)
        ch = _try(o, h, l, c, atr, i, p1, p2, p3, cfg, anH, anL)
        if ch and (best is None or ch["span"] > best["span"]):
            best = ch
    return best


def walk(o, h, l, c, atr, cfg=None, start=30):
    """Генератор (i, state, event). state — действующий канал на закрытии свечи i (или None), event — {'i','dir'} если свеча i пробила канал телом."""
    cfg = dict(FC, **(cfg or {}))
    anH, anL = _anom(o, h, l, c, atr, cfg)
    piv = find_pivots(o, h, l, c, cfg)
    ptr, zz, floor, st = 0, [], 0, None
    for i in range(start, len(c)):
        sig = (len(zz), zz[-1]["i"] if zz else -1, zz[-1]["k"] if zz else "")
        while ptr < len(piv) and piv[ptr]["conf"] <= i:
            _add_zz(zz, piv[ptr], h, l, atr, cfg["dev"])
            ptr += 1
        changed = sig != (len(zz), zz[-1]["i"] if zz else -1, zz[-1]["k"] if zz else "")  # появился новый пивот
        ev = None
        if st is not None:
            tol = cfg["btol"] * atr[i]  # пробой — закрытие за линией (по правилу пользователя без допуска)
            if c[i] > at(st["upper"], i) + tol:
                ev = {"i": i, "dir": "up"}
            elif c[i] < at(st["lower"], i) - tol:
                ev = {"i": i, "dir": "down"}
            if ev:
                floor, st = i, None
        if ev is None and (st is None or (changed and cfg["redraw"])):
            nw = _build(o, h, l, c, atr, i, zz, floor, cfg, anH, anL)  # новый пивот: если по трём последним строится канал — перерисовываем, иначе остаётся прежний
            if nw is not None:
                st = nw
        yield i, st, ev


def channel_now(o, h, l, c, atr, cfg=None, start=30):
    """Канал на последней закрытой свече: (state, события пробоев)."""
    st, evs = None, []
    for i, s, ev in walk(o, h, l, c, atr, cfg, start):
        st = s
        if ev:
            evs.append(ev)
    return st, evs
