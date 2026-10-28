"""classic_trendline.py — авто-линии тренда «как рисует трейдер»: канал = главная линия по двум экстремумам + её параллельный клон (как «параллельный канал» в TradingView).

Канал (auto_channel), на закрытой свече i, без заглядывания вперёд:
  • главная линия идёт по двум подтверждённым pivot-экстремумам с той стороны, куда направлен тренд: нисходящий канал — по двум максимумам (линия падает),
    восходящий — по двум минимумам (линия растёт); плоский (флэт) — по двум максимумам или двум минимумам почти горизонтально;
  • условие: закрытия между первой точкой и свечой i не пробивают линию дальше TOL×ATR;
  • вторая линия — параллельный клон главной, проведённый через самую далёкую от неё противоположную точку между первой опорной и свечой i
    (для нисходящего — через самый глубокий минимум, для восходящего — через самый высокий максимум);
  • ширина канала от 1.5 до 14 ATR, у клона не меньше двух касаний (в пределах 0.35 ATR);
  • из нескольких кандидатов выбирается лучший по числу касаний и длине.
Опорные точки: anchor = 'wick' (хвосты high/low) или 'body' (тела open/close) — параметр, который «обучается» по тому, как рисует пользователь.
Треугольник — две независимые линии (по двум максимумам и по двум минимумам), если они сходятся (build_lines + classify).
Сигналы (по состоянию на предыдущей свече; свеча i в построении не участвует):
  tl_bounce  — канал/флэт: свеча коснулась нижней (лонг) или верхней (шорт) границы в пределах P×ATR (0.3), закрылась по эту сторону и в сторону отбоя.
  tl_breakout — треугольник, клин, канал или флэт: первое закрытие за границей с запасом P×ATR (0.2).
Повтор сигнала той же стороны чаще чем раз в 6 свечей подавляется."""
import json, os
import numpy as np

CFG = {"piv_n": 5, "look": 150, "sep": 5, "tol": 0.15, "nback": 5, "flat": 1.0, "anchor": "wick"}
LEARNED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trendline_learned.json")
RU = {"range": "флэт (параллельный канал)", "channel_up": "восходящий канал", "channel_down": "нисходящий канал", "sym_tri": "симметричный треугольник",
      "asc_tri": "восходящий треугольник", "desc_tri": "нисходящий треугольник", "wedge": "клин", "other": "линии не образуют формацию"}


def set_cfg(d):
    for k in CFG:
        if k in d:
            CFG[k] = type(CFG[k])(d[k])


def load_learned():
    try:
        with open(LEARNED_FILE, encoding="utf-8") as f:
            j = json.load(f)
        set_cfg(j.get("cfg", {}))
        return j
    except Exception:
        return None


def cfg_key():
    return tuple(CFG[k] for k in sorted(CFG))


def anchor_series(o, h, l, c, anchor=None):
    """Ряды максимумов/минимумов для опорных точек: хвосты (wick) или тела свечей (body)."""
    if (anchor or CFG["anchor"]) == "body":
        return np.maximum(o, c), np.minimum(o, c)
    return h, l


def pivots(hh, ll, n=None):
    n = int(n or CFG["piv_n"])
    out = []
    for i in range(n, len(hh) - n):
        if hh[i] >= hh[i - n:i + n + 1].max() and (hh[i - n:i] < hh[i]).all():
            out.append({"i": i, "p": float(hh[i]), "k": "H", "conf": i + n})
        if ll[i] <= ll[i - n:i + n + 1].min() and (ll[i - n:i] > ll[i]).all():
            out.append({"i": i, "p": float(ll[i]), "k": "L", "conf": i + n})
    return out


def _valid(c, atr, i1, p1, i2, p2, upto, side, cfg):
    s = (p2 - p1) / (i2 - i1)
    ln = p1 + s * (np.arange(i1, upto + 1) - i1)
    tol = cfg["tol"] * atr[i1:upto + 1]
    seg = c[i1:upto + 1]
    ok = bool((seg >= ln - tol).all()) if side == "S" else bool((seg <= ln + tol).all())
    return ok, s


def at(line, j):
    return line[1] + line[4] * (j - line[0])


def build_lines(c, atr, i, lows, highs, cfg=None):
    """Независимые линии поддержки (S) и сопротивления (R) — нужны для треугольников. {"S": (i1,p1,i2,p2,slope)|None, "R": ...}."""
    cfg = cfg or CFG
    res = {}
    for key, pivs in (("S", lows), ("R", highs)):
        cand = [q for q in pivs if i - q["i"] <= cfg["look"]]
        found = None
        for a2 in reversed(cand[-2:]):
            for a1 in reversed([q for q in cand if q["i"] <= a2["i"] - cfg["sep"]][-cfg["nback"]:]):
                ok, s = _valid(c, atr, a1["i"], a1["p"], a2["i"], a2["p"], i, key, cfg)
                if ok:
                    found = (a1["i"], a1["p"], a2["i"], a2["p"], s)
                    break
            if found:
                break
        res[key] = found
    return res


def classify(ln, i, atr, cfg=None):
    """Формация по двум независимым линиям (для треугольников/клиньев) или None."""
    cfg = cfg or CFG
    FLAT = cfg["flat"]
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
    mS, mR = S[4] * span / a, R[4] * span / a
    conv = w_0 > 0 and w_i < 0.75 * w_0
    half = 0.5 * FLAT
    if conv:
        if abs(mR) < half and mS >= half:
            return "asc_tri"
        if abs(mS) < half and mR <= -half:
            return "desc_tri"
        if mS > 0 and mR < 0:
            return "sym_tri"
        return "wedge"
    return None


def auto_channel(hh, ll, c, atr, i, lows, highs, cfg=None):
    """Канал «главная линия + параллельный клон» на закрытой свече i. None, если подходящего канала нет.
    Возвращает {"kind": "up"|"down"|"flat", "upper": (i1,p1,i2,p2,slope), "lower": (...), "score", "t_main", "t_clone", "width"}."""
    cfg = cfg or CFG
    best = None
    for mode, pivs, side in (("down", highs, "R"), ("up", lows, "S"), ("flat", highs, "R"), ("flat", lows, "S")):
        cand = [q for q in pivs if i - q["i"] <= cfg["look"]]
        for a2 in reversed(cand[-2:]):
            for a1 in reversed([q for q in cand if q["i"] <= a2["i"] - cfg["sep"]][-cfg["nback"]:]):
                ok, s = _valid(c, atr, a1["i"], a1["p"], a2["i"], a2["p"], i, side, cfg)
                if not ok:
                    continue
                i1 = a1["i"]
                span = i - i1
                mv = s * span / atr[i]
                if (mode == "down" and not mv < -0.5 * cfg["flat"]) or (mode == "up" and not mv > 0.5 * cfg["flat"]) or (mode == "flat" and abs(mv) >= cfg["flat"]):
                    continue
                idx = np.arange(i1, i + 1)
                main = a1["p"] + s * (idx - i1)
                # третья точка — строго МЕЖДУ двумя опорными (волна завершилась — канал определён); раньше искалась до текущей свечи
                i2c = a2["i"] if cfg.get("clone_between", True) else i
                if side == "R":
                    dist = main[:i2c - i1 + 1] - ll[i1:i2c + 1]
                    k = int(np.argmax(dist)); off = -float(dist[k])
                else:
                    dist = hh[i1:i2c + 1] - main[:i2c - i1 + 1]
                    k = int(np.argmax(dist)); off = float(dist[k])
                width = abs(off)
                a_i = atr[i]
                if width < cfg.get("minw", 1.5) * a_i or width > cfg.get("maxw", 14) * a_i:
                    continue
                clone = main + off
                tol = 0.35 * atr[i1:i + 1]
                if side == "R":
                    t_main = int((np.abs(hh[i1:i + 1] - main) <= tol).sum()); t_cl = int((np.abs(ll[i1:i + 1] - clone) <= tol).sum())
                else:
                    t_main = int((np.abs(ll[i1:i + 1] - main) <= tol).sum()); t_cl = int((np.abs(hh[i1:i + 1] - clone) <= tol).sum())
                if t_cl < 2:
                    continue
                score = t_main + t_cl + span / 25.0
                ln_main = (i1, float(a1["p"]), a2["i"], float(a2["p"]), float(s))
                ln_cl = (i1, float(a1["p"] + off), a2["i"], float(a2["p"] + off), float(s))
                upper, lower = (ln_main, ln_cl) if side == "R" else (ln_cl, ln_main)
                if best is None or score > best["score"]:
                    best = {"kind": mode, "upper": upper, "lower": lower, "score": score, "t_main": t_main, "t_clone": t_cl, "width": width / a_i}
                break
    return best


def structure_at(hh, ll, c, atr, i, lows, highs, cfg=None):
    """Лучшая формация на свече i: треугольник (две сходящиеся линии), иначе канал-клон, иначе независимые линии.
    Возвращает {"type", "lower", "upper", "lines": {"S": .., "R": ..}} или None."""
    cfg = cfg or CFG
    ln = build_lines(c, atr, i, lows, highs, cfg)
    tri = classify(ln, i, atr, cfg)
    if tri:
        return {"type": tri, "lower": ln["S"], "upper": ln["R"], "lines": ln}
    ch = auto_channel(hh, ll, c, atr, i, lows, highs, cfg)
    if ch:
        t = {"up": "channel_up", "down": "channel_down", "flat": "range"}[ch["kind"]]
        return {"type": t, "lower": ch["lower"], "upper": ch["upper"], "lines": {"S": ch["lower"], "R": ch["upper"]}, "channel": ch}
    if ln["S"] or ln["R"]:
        return {"type": "other", "lower": ln["S"], "upper": ln["R"], "lines": ln}
    return None


def _walk(hh, ll, c, atr, piv, M, warm=60, cfg=None):
    """По свечам: (i, state) — формация, построенная на данных до свечи i-1 включительно."""
    cfg = cfg or CFG
    lows, highs, ptr = [], [], 0
    for i in range(warm, M):
        while ptr < len(piv) and piv[ptr]["conf"] <= i - 1:
            (lows if piv[ptr]["k"] == "L" else highs).append(piv[ptr])
            ptr += 1
        if len(lows) < 2 or len(highs) < 2:
            yield i, None
            continue
        yield i, structure_at(hh, ll, c, atr, i - 1, lows[-8:], highs[-8:], cfg)


def tl_signals(o, h, l, c, atr, piv, M, kind, p=0.0, warm=60, info=None, wlim=None):
    """{индекс закрытой свечи: сторона} для kind = 'tl_bounce' | 'tl_breakout'. Опорные точки и pivot считаются по текущим параметрам CFG (в том числе обученным)."""
    hh, ll = anchor_series(o, h, l, c)
    piv = pivots(hh[:M], ll[:M])
    out, last = {}, {"L": -99, "S": -99}
    cfgx = dict(CFG, minw=float(wlim[0]), maxw=float(wlim[1])) if wlim else None  # пределы ширины канала (в ATR) из конструктора
    minw = cfgx["minw"] if cfgx else 1.5
    for i, st in _walk(hh, ll, c, atr, piv, M, warm, cfg=cfgx):
        if not st or not st.get("lower") or not st.get("upper"):
            continue
        S, R, typ = st["lower"], st["upper"], st["type"]
        a = atr[i]
        Si, Ri = at(S, i), at(R, i)
        side = None
        if kind == "tl_bounce" and typ in ("range", "channel_up", "channel_down") and (Ri - Si) >= minw * a:
            tol = (p if p > 0 else 0.3) * a
            if l[i] <= Si + tol and l[i] >= Si - a and c[i] > Si and c[i] > o[i]:
                side = "L"
            elif h[i] >= Ri - tol and h[i] <= Ri + a and c[i] < Ri and c[i] < o[i]:
                side = "S"
        elif kind == "tl_breakout" and typ != "other":  # треугольник, клин, канал или флэт: первое закрытие за границей
            buf = (p if p > 0 else 0.2) * a
            if c[i] > Ri + buf and c[i - 1] <= at(R, i - 1) + buf:
                side = "L"
            elif c[i] < Si - buf and c[i - 1] >= at(S, i - 1) - buf:
                side = "S"
        if side and i - last[side] >= 6:
            out[i] = side
            last[side] = i
            if info is not None:  # линии канала на момент сигнала: функции номер свечи -> цена (для стопа/цели по каналу)
                fS_, fR_ = (lambda j, L=S: at(L, j)), (lambda j, L=R: at(L, j))
                fS_.typ = fR_.typ = typ  # тип формации и индекс самой ранней опорной точки — для цели по высоте основания треугольника
                fS_.i0 = fR_.i0 = min(int(S[0]), int(R[0]))
                info[i] = (fS_, fR_)
    return out


def chart_info(o, h, l, c, atr, piv, M, shift=0, back=12):
    """Для графика: актуальная формация на последней закрытой свече (если линия пробита — последняя действующая, пунктиром), подпись, сигналы."""
    hh, ll = anchor_series(o, h, l, c)
    pv = pivots(hh[:M], ll[:M])
    lows = [q for q in pv if q["k"] == "L"]
    highs = [q for q in pv if q["k"] == "H"]
    lines, struct = {}, None
    for b in range(0, back):
        i = M - 1 - b
        st = structure_at(hh, ll, c, atr, i, [q for q in lows if q["conf"] <= i][-8:], [q for q in highs if q["conf"] <= i][-8:])
        if not st:
            continue
        if b == 0:
            struct = st["type"]
        for key, ln in (("S", st["lower"]), ("R", st["upper"])):
            if ln and key not in lines:
                lines[key] = {"i1": ln[0] - shift, "p1": float(ln[1]), "i2": ln[2] - shift, "p2": float(ln[3]), "s": float(ln[4]), "broken": b > 0}
        if len(lines) == 2:
            break
    sigs = []
    for kd, tag in (("tl_bounce", "b"), ("tl_breakout", "k")):
        for i, side in tl_signals(o, h, l, c, atr, None, M, kd).items():
            if i - shift >= 0:
                sigs.append({"i": i - shift, "side": side, "kind": tag})
    if struct:
        label = RU[struct] + (" (опорные: тела свечей)" if CFG["anchor"] == "body" else "")
    elif lines:
        label = "есть линии: " + ", ".join({"S": "нижняя", "R": "верхняя"}[k] + (" (пробита)" if v["broken"] else "") for k, v in lines.items())
    else:
        label = "линий нет"
    return {"lines": lines, "struct": struct, "label": label, "sigs": sigs}


load_learned()
