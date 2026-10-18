"""classic_trendline.py — линии тренда по подтверждённым pivot-экстремумам, определение формации и сигналы.

Как строится линия (на закрытой свече i, без заглядывания вперёд): берутся pivot-экстремумы, подтверждённые к свече i (задержка PIV_N=5 свечей).
Поддержка — линия через два pivot-минимума (вторая точка — один из двух последних минимумов, первая — ближайший более ранний, не ближе SEP свечей),
сопротивление — через два pivot-максимума. Линия принимается, только если ни одно закрытие между первой точкой и свечой i не пробило её дальше
TOL×ATR (классическое правило: линию тренда не должно пересекать тело цены). Если подходящих линий нет — линия не рисуется.
Формация по двум линиям: range (флэт: обе линии почти горизонтальны), channel_up / channel_down (параллельный канал: наклоны одного знака,
ширина не сужается), sym_tri / asc_tri / desc_tri (треугольник: линии сходятся — симметричный, восходящий с плоским сопротивлением, нисходящий с плоской поддержкой),
wedge (сходятся в одну сторону), other.
Сигналы (только по состоянию линий на предыдущей свече — свеча i в построении не участвует):
  tl_bounce  — в канале/флэте: свеча коснулась поддержки (лонг) или сопротивления (шорт) в пределах P×ATR (умолч. 0.3), закрылась по эту сторону линии и
               в сторону отбоя (бычья/медвежья); ширина канала не меньше 1.5 ATR.
  tl_breakout — в треугольнике: первое закрытие за линией сопротивления (лонг) или поддержки (шорт) с запасом P×ATR (умолч. 0.2).
Повтор сигнала той же стороны чаще чем раз в 6 свечей подавляется."""
import numpy as np

LOOK, SEP, TOL, NBACK, FLAT = 150, 5, 0.15, 5, 1.0

RU = {"range": "флэт (боковик)", "channel_up": "восходящий канал", "channel_down": "нисходящий канал", "sym_tri": "симметричный треугольник",
      "asc_tri": "восходящий треугольник", "desc_tri": "нисходящий треугольник", "wedge": "клин", "other": "линии не образуют формацию"}


def _valid(c, atr, i1, p1, i2, p2, upto, side):
    s = (p2 - p1) / (i2 - i1)
    ln = p1 + s * (np.arange(i1, upto + 1) - i1)
    tol = TOL * atr[i1:upto + 1]
    seg = c[i1:upto + 1]
    ok = bool((seg >= ln - tol).all()) if side == "S" else bool((seg <= ln + tol).all())
    return ok, s


def build_lines(c, atr, i, lows, highs):
    """Линии поддержки (S) и сопротивления (R) на закрытой свече i. lows/highs — подтверждённые к i pivot-точки по возрастанию индекса.
    Возвращает {"S": (i1, p1, i2, p2, slope) | None, "R": ...}."""
    res = {}
    for key, pivs in (("S", lows), ("R", highs)):
        cand = [q for q in pivs if i - q["i"] <= LOOK]
        found = None
        for a2 in reversed(cand[-2:]):
            for a1 in reversed([q for q in cand if q["i"] <= a2["i"] - SEP][-NBACK:]):
                ok, s = _valid(c, atr, a1["i"], a1["p"], a2["i"], a2["p"], i, key)
                if ok:
                    found = (a1["i"], a1["p"], a2["i"], a2["p"], s)
                    break
            if found:
                break
        res[key] = found
    return res


def at(line, j):
    return line[1] + line[4] * (j - line[0])


def classify(ln, i, atr):
    """Формация по двум линиям на свече i или None, если линии пересеклись/слишком близко."""
    S, R = ln["S"], ln["R"]
    if not S or not R:
        return None
    a = atr[i]
    w_i = at(R, i) - at(S, i)
    if w_i < 0.5 * a:
        return None
    i0 = min(S[0], R[0])
    w_0 = at(R, i0) - at(S, i0)
    span = max(1, i - i0)
    mS, mR = S[4] * span / a, R[4] * span / a  # смещение линии за всю длину формации в ATR
    conv = w_0 > 0 and w_i < 0.75 * w_0
    half = 0.5 * FLAT
    if conv:  # линии сходятся — треугольник или клин (проверяется раньше флэта)
        if abs(mR) < half and mS >= half:
            return "asc_tri"
        if abs(mS) < half and mR <= -half:
            return "desc_tri"
        if mS > 0 and mR < 0:
            return "sym_tri"
        return "wedge"
    if abs(mS) < FLAT and abs(mR) < FLAT:
        return "range"
    if mS > half and mR > half:
        return "channel_up"
    if mS < -half and mR < -half:
        return "channel_down"
    return "other"


def _walk(o, h, l, c, atr, piv, M, warm=60):
    """Итератор по свечам: (i, lines_prev, struct_prev) — состояние линий на свече i-1."""
    lows, highs, ptr = [], [], 0
    for i in range(warm, M):
        while ptr < len(piv) and piv[ptr]["conf"] <= i - 1:
            (lows if piv[ptr]["k"] == "L" else highs).append(piv[ptr])
            ptr += 1
        if len(lows) < 2 or len(highs) < 2:
            yield i, None, None
            continue
        ln = build_lines(c, atr, i - 1, lows[-8:], highs[-8:])
        yield i, ln, classify(ln, i - 1, atr)


def tl_signals(o, h, l, c, atr, piv, M, kind, p=0.0, warm=60):
    """{индекс закрытой свечи: сторона 'L'/'S'} для kind = 'tl_bounce' | 'tl_breakout'."""
    out, last = {}, {"L": -99, "S": -99}
    for i, ln, st in _walk(o, h, l, c, atr, piv, M, warm):
        if not ln or not st:
            continue
        S, R = ln["S"], ln["R"]
        a = atr[i]
        Si, Ri = at(S, i), at(R, i)
        side = None
        if kind == "tl_bounce" and st in ("range", "channel_up", "channel_down") and (Ri - Si) >= 1.5 * a:
            tol = (p if p > 0 else 0.3) * a
            if l[i] <= Si + tol and l[i] >= Si - a and c[i] > Si and c[i] > o[i]:
                side = "L"
            elif h[i] >= Ri - tol and h[i] <= Ri + a and c[i] < Ri and c[i] < o[i]:
                side = "S"
        elif kind == "tl_breakout" and st in ("sym_tri", "asc_tri", "desc_tri"):
            buf = (p if p > 0 else 0.2) * a
            if c[i] > Ri + buf and c[i - 1] <= at(R, i - 1) + buf:
                side = "L"
            elif c[i] < Si - buf and c[i - 1] >= at(S, i - 1) - buf:
                side = "S"
        if side and i - last[side] >= 6:
            out[i] = side
            last[side] = i
    return out


def chart_info(o, h, l, c, atr, piv, M, shift=0, back=12):
    """Данные для графика: актуальные линии на последней закрытой свече (если линия пробита — последняя действующая, пунктиром),
    формация, сигналы отбоя/пробоя. Индексы сдвигаются на shift (окно графика)."""
    lows = [q for q in piv if q["k"] == "L"]
    highs = [q for q in piv if q["k"] == "H"]
    lines, st_now = {}, None
    for key, lst in (("S", lows), ("R", highs)):
        for b in range(0, back):
            i = M - 1 - b
            conf_l = [q for q in lows if q["conf"] <= i][-8:]
            conf_h = [q for q in highs if q["conf"] <= i][-8:]
            ln = build_lines(c, atr, i, conf_l, conf_h)
            if ln[key]:
                L = ln[key]
                lines[key] = {"i1": L[0] - shift, "p1": float(L[1]), "i2": L[2] - shift, "p2": float(L[3]), "s": float(L[4]), "broken": b > 0}
                if b == 0 and key == "S":
                    st_now = ln
                break
    conf_l = [q for q in lows if q["conf"] <= M - 1][-8:]
    conf_h = [q for q in highs if q["conf"] <= M - 1][-8:]
    cur = build_lines(c, atr, M - 1, conf_l, conf_h)
    struct = classify(cur, M - 1, atr) if cur["S"] and cur["R"] else None
    sigs = []
    for kind, tag in (("tl_bounce", "b"), ("tl_breakout", "k")):
        for i, side in tl_signals(o, h, l, c, atr, piv, M, kind).items():
            if i - shift >= 0:
                sigs.append({"i": i - shift, "side": side, "kind": tag})
    label = RU[struct] if struct else ("есть линии: " + ", ".join({"S": "поддержка", "R": "сопротивление"}[k] + (" (пробита)" if v["broken"] else "") for k, v in lines.items())) if lines else "линий нет"
    return {"lines": lines, "struct": struct, "label": label, "sigs": sigs}
