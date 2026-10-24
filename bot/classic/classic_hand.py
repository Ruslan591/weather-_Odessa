"""classic_hand.py — линии, нарисованные пользователем на графике (каналы, флэты, треугольники), торговля по ним и «обучение» авто-детектора на этих рисунках.

Хранение (hand.json рядом с модулем): список структур
  {"id", "sym", "tf" (на каком ТФ нарисовано), "kind": "channel" | "range" | "triangle",
   "A": [t1, p1, t2, p2], "B": [t1, p1, t2, p2]  — две линии, каждая по двум точкам (время мс, цена),
   "created": мс, "deleted": мс | None  (мягкое удаление: прогон не теряет историю)}.
Линия продолжается вправо в будущее (экстраполяция по двум точкам). Верхняя/нижняя граница определяются в каждый момент времени.

Сигналы (по закрытым свечам; геометрия линий задана заранее, ожидание будущего не используется):
  hand_bounce   — канал/флэт: свеча коснулась нижней границы (лонг) или верхней (шорт) в пределах P×ATR (умолч. 0.3), закрылась по эту сторону и в сторону отбоя;
                  ширина не меньше 1.5 ATR.
  hand_both     — оба сигнала сразу (отбой и пробой по одним и тем же рисункам; в сделке видно, какой был сигнал).
  hand_breakout — любая структура: первое закрытие за верхней границей (лонг) или нижней (шорт) с запасом P×ATR (умолч. 0.2).
Структура «закрывается» после первого пробоя границы закрытием (или когда линии пересеклись): дальше сигналов по ней нет.
forward=True — сигналы только с момента создания структуры (честный режим); False — по всей истории после последней опорной точки (с подглядыванием).
Повтор сигнала той же стороны по одной структуре чаще чем раз в 6 свечей подавляется."""
import json, os, time
import numpy as np
import classic_trendline as tl

HAND_FILE = os.environ.get("CLASSIC_HAND_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand.json")  # CLASSIC_HAND_FILE — для тестов на отдельном файле
_cache = {"mtime": None, "data": []}


def load():
    try:
        m = os.path.getmtime(HAND_FILE)
    except OSError:
        return []
    if _cache["mtime"] != m:
        try:
            with open(HAND_FILE, encoding="utf-8") as f:
                _cache["data"] = json.load(f)
        except Exception:
            _cache["data"] = []
        _cache["mtime"] = m
    return _cache["data"]


def save(items):
    """Запись с защитой: перед перезаписью предыдущая версия сохраняется (hand.json.bak — последняя, hand_backups/ — не чаще раза в 10 минут, последние 200)."""
    import shutil
    if os.path.exists(HAND_FILE):
        try:
            shutil.copy2(HAND_FILE, HAND_FILE + ".bak")
            bd = os.path.join(os.path.dirname(HAND_FILE), "hand_backups")
            os.makedirs(bd, exist_ok=True)
            snaps = sorted(os.listdir(bd))
            if not snaps or time.time() - os.path.getmtime(os.path.join(bd, snaps[-1])) > 600:
                shutil.copy2(HAND_FILE, os.path.join(bd, "hand_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
                for old in sorted(os.listdir(bd))[:-200]:
                    os.remove(os.path.join(bd, old))
        except OSError:
            pass
    tmp = HAND_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, HAND_FILE)
    _cache["mtime"] = None


_TFM = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080}


def for_sym(sym, tf=None, mode="any"):
    """Структуры пары. mode: any — все; junior — только нарисованные на этом ТФ или на более старшем (рисунок торгуется на своём ТФ и на младших); own — только на этом ТФ."""
    L = [x for x in load() if x.get("sym") == sym]
    if tf in _TFM and mode in ("junior", "own"):
        def ok(x):
            s = x.get("tf")
            if s not in _TFM:
                return True
            return _TFM[tf] <= _TFM[s] if mode == "junior" else tf == s
        L = [x for x in L if ok(x)]
    return L


def line_at(L, t):
    t1, p1, t2, p2 = L
    return p1 + (p2 - p1) / (t2 - t1) * (t - t1) if t2 != t1 else p1


def struct_signals(st, o, h, l, c, atr, t, M, forward=True, warm=60, p_b=0.0, p_k=0.0, info=None):
    """[(i, side, tag, id)] по одной структуре, tag: 'b' — отбой, 'k' — пробой."""
    A, B = st["A"], st["B"]
    t_start = max(A[0], A[2], B[0], B[2])
    created, deleted = st.get("created") or 0, st.get("deleted") or 1e18
    out, last = [], {"L": -99, "S": -99}
    tol_k = p_b if p_b > 0 else 0.3
    buf_k = p_k if p_k > 0 else 0.2
    for i in range(max(warm, 1), M):
        ti = t[i]
        if ti < t_start or (forward and ti < created):
            continue
        if ti >= deleted:
            break
        a_i, b_i = line_at(A, ti), line_at(B, ti)
        up, lo = max(a_i, b_i), min(a_i, b_i)
        if up - lo <= 0:
            break  # линии пересеклись (вершина треугольника)
        a_p, b_p = line_at(A, t[i - 1]), line_at(B, t[i - 1])
        up_p, lo_p = max(a_p, b_p), min(a_p, b_p)
        at = atr[i]
        side, tag = None, None
        if c[i] > up + buf_k * at and c[i - 1] <= up_p + buf_k * atr[i - 1]:
            side, tag = "L", "k"
        elif c[i] < lo - buf_k * at and c[i - 1] >= lo_p - buf_k * atr[i - 1]:
            side, tag = "S", "k"
        elif st.get("kind") in ("channel", "range") and (up - lo) >= 1.5 * at:
            tol = tol_k * at
            if l[i] <= lo + tol and l[i] >= lo - at and c[i] > lo and c[i] > o[i]:
                side, tag = "L", "b"
            elif h[i] >= up - tol and h[i] <= up + at and c[i] < up and c[i] < o[i]:
                side, tag = "S", "b"
        if side and i - last[side] >= 6:
            out.append((i, side, tag, st["id"]))
            last[side] = i
            if info is not None:  # линии структуры: функции номер свечи -> цена
                lo_l, up_l = (A, B) if a_i <= b_i else (B, A)
                info[i] = ((lambda j, L=lo_l: line_at(L, t[j])), (lambda j, L=up_l: line_at(L, t[j])))
        if tag == "k" or c[i] > up + at or c[i] < lo - at:
            break  # структура закончилась: пробой или уход цены за границу больше чем на ATR
    return out


def hand_signals(o, h, l, c, atr, t, M, structs, kind, p=0.0, forward=True, info=None, tags=None):
    """{индекс свечи: сторона} для kind 'hand_bounce' | 'hand_breakout' | 'hand_both' (отбой И пробой) по всем структурам пары (при совпадении побеждает более ранняя структура).
    tags (dict, необязательно) заполняется {индекс свечи: 'b' | 'k'} — какой это сигнал (нужно для hand_both: у отбоя и пробоя разные цели)."""
    both = kind == "hand_both"
    want = "b" if kind == "hand_bounce" else "k"
    out = {}
    for st in structs:
        inf = {} if info is not None else None
        pb = p if (both or want == "b") else 0.0
        pk = 0.0 if both else (p if want == "k" else 0.0)
        for i, side, tag, sid in struct_signals(st, o, h, l, c, atr, t, M, forward, p_b=pb, p_k=pk, info=inf):
            if (both or tag == want) and i not in out:
                out[i] = side
                if tags is not None:
                    tags[i] = tag
                if info is not None and i in inf:
                    info[i] = inf[i]
    return out


def markers(o, h, l, c, atr, t, M, structs, forward=False):
    """Для графика: [{t, side, kind, sid}] — все сигналы по структурам пары."""
    res = []
    for st in structs:
        if st.get("deleted") and False:
            continue
        for i, side, tag, sid in struct_signals(st, o, h, l, c, atr, t, M, forward):
            res.append({"t": int(t[i]), "side": side, "kind": tag, "sid": sid})
    return res


# ---------------- обучение авто-детектора на рисунках пользователя ----------------
GRID = {"piv_n": (3, 4, 5, 6, 8, 10), "tol": (0.1, 0.15, 0.25, 0.4), "sep": (3, 5, 8), "look": (80, 150, 250), "nback": (3, 5, 8), "anchor": ("wick", "body")}


def anchor_stats(structs):
    """Куда пользователь ставит опорные точки главной линии: хвосты (h/l) или тела (o/c). Данные берутся из поля anc (тип привязки каждого тапа)."""
    body = wick = 0
    for st in structs:
        anc = st.get("anc") or []
        main = anc[:2] if st.get("kind") == "channel" else anc[:4] if st.get("kind") == "triangle" else []
        for k in main:
            if k in ("o", "c"):
                body += 1
            elif k in ("h", "l"):
                wick += 1
    return {"body": body, "wick": wick}


def _lo_up(st):
    A, B = st["A"], st["B"]
    tt = max(A[0], A[2], B[0], B[2])
    return (A, B) if line_at(A, tt) <= line_at(B, tt) else (B, A)


def _piv(d, anchor, n):
    key = (anchor, n)
    if key not in d["piv"]:
        hh, ll = tl.anchor_series(d["o"], d["h"], d["l"], d["c"], anchor)
        d["piv"][key] = tl.pivots(hh, ll, n)
    return d["piv"][key]


def fit_cost(data, structs, cfg, miss=3.0):
    """Средняя ошибка (в ATR) авто-формации относительно нарисованных линий на окне из 9 свечей, заканчивающемся на последней опорной точке структуры.
    Возвращает (ошибка, сколько структур совпало (<0.75 ATR), сколько структур учтено)."""
    tot, cnt, hit = 0.0, 0, 0
    for st in structs:
        d = data.get((st["sym"], st["tf"]))
        if d is None:
            continue
        t, c, atr = d["t"], d["c"], d["atr"]
        t_end = max(st["A"][0], st["A"][2], st["B"][0], st["B"][2])
        i = int(np.searchsorted(t, t_end))
        if i < 40 or i >= len(t):
            continue
        piv = _piv(d, cfg["anchor"], cfg["piv_n"])
        lows = [q for q in piv if q["k"] == "L" and q["conf"] <= i][-8:]
        highs = [q for q in piv if q["k"] == "H" and q["conf"] <= i][-8:]
        hh, ll = tl.anchor_series(d["o"], d["h"], d["l"], c, cfg["anchor"])
        auto = tl.structure_at(hh, ll, c, atr, i, lows, highs, cfg)
        lo_l, up_l = _lo_up(st)
        cost = 0.0
        for key, drawn in (("lower", lo_l), ("upper", up_l)):
            ln = auto.get(key) if auto else None
            if not ln:
                cost += miss
                continue
            err = np.mean([abs(tl.at(ln, j) - line_at(drawn, t[j])) / atr[j] for j in range(i - 8, i + 1)])
            cost += min(err, miss)
        cost /= 2.0
        tot += cost
        cnt += 1
        hit += 1 if cost < 0.75 else 0
    return (tot / cnt if cnt else None), hit, cnt


def calibrate(data, structs):
    """Подбирает параметры авто-детектора (pivot, допуск, расстояние между опорами, окно, число перебираемых опор, хвосты/тела), при которых авто-формация
    лучше всего повторяет нарисованные пользователем линии. data: {(sym, tf): {t, o, h, l, c, atr}}. Возвращает (лучшие cfg, отчёт)."""
    import itertools
    for d in data.values():
        d["piv"] = {}
    stats = anchor_stats(structs)
    grid = dict(GRID)
    tot = stats["body"] + stats["wick"]
    if tot >= 4 and max(stats.values()) >= 0.7 * tot:  # явное предпочтение опорных точек — сужаем перебор
        grid["anchor"] = ("body",) if stats["body"] > stats["wick"] else ("wick",)
    base = dict(tl.CFG)
    base_cost, base_hit, n = fit_cost(data, structs, base)
    if not n:
        return None, {"n": 0, "msg": "нет структур с достаточной историей на графике"}
    best, best_cost, best_hit = dict(base), base_cost, base_hit
    keys = list(grid)
    for combo in itertools.product(*[grid[k] for k in keys]):
        cfg = dict(base)
        cfg.update(dict(zip(keys, combo)))
        cost, hit, _ = fit_cost(data, structs, cfg)
        pen = 0.003 * sum(1 for k in keys if cfg[k] != base[k])
        if cost is not None and cost + pen < best_cost - 1e-9:
            best, best_cost, best_hit = cfg, cost + pen, hit
    return best, {"n": n, "base_cost": round(float(base_cost), 3), "best_cost": round(float(best_cost), 3), "base_hit": int(base_hit), "best_hit": int(best_hit),
                  "anchors": stats, "cfg": {k: best[k] for k in tl.CFG}}
