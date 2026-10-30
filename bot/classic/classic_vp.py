# -*- coding: utf-8 -*-
"""classic_vp.py — стратегия «Пробой/Отбой канала с фильтром по профилю объёма» (Volume Profile) по ТЗ пользователя.

Состав: ZigZag по подтверждённым вершинам/впадинам; режим Флэт/Тренд; горизонтальный профиль объёма (как VPVR в TradingView) с POC, VAH/VAL (зона стоимости, по умолчанию 70%),
узлы HVN/LVN, POC вчерашней сессии (сутки UTC); сигналы отбоя, пробоя (с проверкой «пустоты» за границей) и возврата после ложного пробоя.
Вход всегда на открытии свечи, следующей за сигнальной (как у остальных прогонов); стоп, цель и безубыток для каждой сделки считает этот модуль и передаёт в classic_strategy.simulate (pre['_vp']).
ZigZag здесь — по порогу отклонения в % (не пиксель-в-пиксель порт индикатора MT4): depth — минимум свечей между соседними пивотами, deviation — минимальный откат в %, backstep — сколько свечей экстремум должен «отстояться»."""
import numpy as np
import os, json, time, sqlite3, bisect

ZZ_DEF = {"5m": (12, 0.6, 3), "15m": (12, 1.0, 3), "30m": (10, 1.2, 3), "1h": (8, 1.5, 2)}  # depth, deviation %, backstep по таймфреймам (если в настройках 0)
VPD = dict(vp_mode="auto", vp_rows=48, vp_va=70.0, zz_depth=0, zz_dev=0.0, zz_back=0, vp_flat_delta=0.1, vp_par=0.6, vp_hvn=1.5, vp_lvn=0.5,
           vp_tol_atr=0.3, vp_buf_atr=0.1, vp_hist_bars=1000, vp_ahead_atr=1.5, vp_imp_atr=1.0, vp_bo_entry="close", vp_retest_bars=10, vp_ret_bars=5,
           vp_sl_atr=0.5, vp_rr=2.0, vp_min_rr=1.0, vp_be_poc=True, vp_be_frac=0.65, vp_start="auto", vp_starts={}, vp_neutral="skip",
           vp_bounce=True, vp_breakout=True, vp_return=True,
           vp_wick_void=True, vp_room_r=1.5, vp_wall_stop=True, vp_ws_buf_atr=0.15, vp_ws_min_atr=0.5)


# ---- стакан (book.db, пишет classic_book.py): стенки на момент свечи ----
BOOK_DB = os.path.join(os.environ.get("CLASSIC_DIR", "/opt/trading-bot/classic"), "book.db")
_BOOK = {}


def book_series(sym, ms_from):
    """-> (ts[], walls[]) снимки стакана пары начиная с ms_from (кэш 60 с); пусто, если записи нет."""
    if not sym: return [], []
    now = time.time(); k = _BOOK.get(sym)
    if k and now - k[0] < 60 and k[1] <= ms_from: return k[2], k[3]
    ts, ws = [], []
    try:
        c = sqlite3.connect("file:%s?mode=ro" % BOOK_DB, uri=True, timeout=10)
        for a, b in c.execute("SELECT ts, walls FROM snap WHERE sym=? AND ts>=? ORDER BY ts", (sym, int(ms_from) - 600000)):
            ts.append(a); ws.append(json.loads(b) if b else [])
        c.close()
    except Exception:
        ts, ws = [], []
    _BOOK[sym] = (now, int(ms_from), ts, ws)
    return ts, ws


def walls_at(ser, ms, persist=True):
    """Стенки в снимке не позже ms (не старше 3 мин). persist: стенка должна быть и в снимке ~2.5 мин раньше (на той же цене +-0.15%), иначе это мелькание. -> список {s,p,v,m} или None, если снимка нет."""
    ts, ws = ser
    if not ts: return None
    j = bisect.bisect_right(ts, ms) - 1
    if j < 0 or ms - ts[j] > 180000: return None
    cur = ws[j]
    if not persist: return cur
    j2 = bisect.bisect_right(ts, ms - 150000) - 1
    if j2 < 0 or (ms - 150000) - ts[j2] > 180000: return cur
    old = ws[j2]
    return [w for w in cur if any(o_["s"] == w["s"] and abs(o_["p"] - w["p"]) / w["p"] <= 0.0015 for o_ in old)]


def wall_stop_level(sym, side, close_ms, price, entry, cur_stop, atr_i, P, ser=None):
    """Стоп под стенкой поддержки (лонг) / над стенкой сопротивления (шорт): среди стенок между входом и ценой (не ближе vp_ws_min_atr ATR к цене)
    берётся самая дальняя от цены, т.е. нижняя у лонга; стоп = цена стенки -/+ vp_ws_buf_atr ATR. Только подтягивание, и стоп должен быть в плюсе (за входом). -> цена или None."""
    ser = ser if ser is not None else book_series(sym, close_ms - 3 * 3600000)
    W = walls_at(ser, close_ms)
    if not W: return None
    buf = float(P.get("vp_ws_buf_atr", 0.15)) * atr_i; mn = float(P.get("vp_ws_min_atr", 0.5)) * atr_i
    if side == "L":
        cand = [w["p"] for w in W if w["s"] == "b" and entry < w["p"] <= price - mn]
        if not cand: return None
        q = min(cand) - buf
        return q if (q > cur_stop and q > entry and q < price) else None
    cand = [w["p"] for w in W if w["s"] == "a" and price + mn <= w["p"] < entry]
    if not cand: return None
    q = max(cand) + buf
    return q if (q < cur_stop and q < entry and q > price) else None


def zigzag(h, l, depth, dev, back):
    """Подтверждённые пивоты: [{i, p, k:'H'|'L', conf}] — conf = свеча, на которой пивот подтверждён (раньше неё о нём знать нельзя)."""
    n, dv = len(h), dev / 100.0
    piv, d, ei, ep, last_i = [], 0, 0, 0.0, -10 ** 9
    hi_i = lo_i = 0
    for i in range(n):
        if d == 0:
            if h[i] > h[hi_i]: hi_i = i
            if l[i] < l[lo_i]: lo_i = i
            if hi_i != lo_i and h[hi_i] / l[lo_i] - 1 >= dv:
                if hi_i > lo_i:
                    piv.append(dict(i=lo_i, p=float(l[lo_i]), k="L", conf=i)); d, ei, ep = 1, hi_i, h[hi_i]
                else:
                    piv.append(dict(i=hi_i, p=float(h[hi_i]), k="H", conf=i)); d, ei, ep = -1, lo_i, l[lo_i]
                last_i = piv[-1]["i"]
            continue
        if d == 1:
            if h[i] > ep:
                ei, ep = i, h[i]
            elif ep - l[i] >= ep * dv and i - ei >= back and ei - last_i >= depth:
                piv.append(dict(i=ei, p=float(ep), k="H", conf=i)); last_i = ei; d = -1
                j = ei + 1 + int(np.argmin(l[ei + 1:i + 1])); ei, ep = j, l[j]
        else:
            if l[i] < ep:
                ei, ep = i, l[i]
            elif h[i] - ep >= ep * dv and i - ei >= back and ei - last_i >= depth:
                piv.append(dict(i=ei, p=float(ep), k="L", conf=i)); last_i = ei; d = 1
                j = ei + 1 + int(np.argmax(h[ei + 1:i + 1])); ei, ep = j, h[j]
    return piv


def profile(h, l, v, a, b, rows, va_pct=70.0, hvn=1.5, lvn=0.5, lo=None, hi=None):
    """Горизонтальный профиль объёма по свечам [a..b]: объём свечи делится по строкам пропорционально пересечению её диапазона (как VPVR).
    -> dict(lo, step, vol[], poc, vah, val, hvn[(цена_низ, цена_верх, объём)], lvn[...]) или None."""
    hh, ll, vv = h[a:b + 1], l[a:b + 1], v[a:b + 1]
    if len(hh) < 3: return None
    lo = float(ll.min()) if lo is None else lo
    hi = float(hh.max()) if hi is None else hi
    if not hi > lo: return None
    step = (hi - lo) / rows
    vol = np.zeros(rows)
    for k in range(len(hh)):
        r0 = min(rows - 1, max(0, int((ll[k] - lo) / step))); r1 = min(rows - 1, max(0, int((hh[k] - lo) / step)))
        if r1 == r0 or hh[k] <= ll[k]:
            vol[r0] += vv[k]; continue
        rng = hh[k] - ll[k]
        for r in range(r0, r1 + 1):
            ov = min(hh[k], lo + (r + 1) * step) - max(ll[k], lo + r * step)
            if ov > 0: vol[r] += vv[k] * ov / rng
    tot = vol.sum()
    if tot <= 0: return None
    poc = int(np.argmax(vol)); acc, up, dn = vol[poc], poc, poc
    while acc < tot * va_pct / 100.0:
        u2 = vol[up + 1:up + 3].sum() if up + 1 < rows else 0.0
        d2 = vol[max(dn - 2, 0):dn].sum() if dn > 0 else 0.0
        if u2 <= 0 and d2 <= 0: break
        if u2 >= d2: acc += u2; up = min(rows - 1, up + 2)
        else: acc += d2; dn = max(0, dn - 2)
    mean = tot / rows
    H, Lv = [], []
    for r in range(rows):
        nb = max(vol[max(0, r - 1):min(rows, r + 2)])
        if vol[r] >= hvn * mean and vol[r] >= nb: H.append((lo + r * step, lo + (r + 1) * step, float(vol[r])))
        if vol[r] <= lvn * mean: Lv.append((lo + r * step, lo + (r + 1) * step, float(vol[r])))
    return dict(lo=lo, step=step, vol=vol, mean=mean, poc=lo + (poc + 0.5) * step, vah=lo + (up + 1) * step, val=lo + dn * step, hvn=H, lvn=Lv, a=a, b=b)


def node_near(nodes, lvl, tol):
    """Самый крупный HVN, пересекающий [lvl-tol, lvl+tol]."""
    best = None
    for n in nodes:
        if n[1] >= lvl - tol and n[0] <= lvl + tol and (best is None or n[2] > best[2]): best = n
    return best


def density_ahead(pf, z0, z1):
    """Отношение максимального объёма строк в зоне [z0, z1] к среднему объёму строки (0 — зона пуста, т.е. цена там не торговалась)."""
    if pf is None or pf["mean"] <= 0: return None
    r0 = int(np.floor((z0 - pf["lo"]) / pf["step"])); r1 = int(np.floor((z1 - pf["lo"]) / pf["step"]))
    n = len(pf["vol"])
    if r1 < 0 or r0 > n - 1: return 0.0
    return float(pf["vol"][max(0, r0):min(n - 1, r1) + 1].max() / pf["mean"])


def _pack_vpx(pf, mode, kind, lvl, ypoc, extra=None):
    """Компактный слепок профиля для графика сделки: строки 0..1000 от максимума, цены уровней."""
    mx = float(pf["vol"].max()) or 1.0
    d = dict(mode=mode, kind=kind, lo=float("%.8g" % pf["lo"]), st=float("%.8g" % pf["step"]), v=[int(round(x / mx * 1000)) for x in pf["vol"]],
             poc=float("%.8g" % pf["poc"]), vah=float("%.8g" % pf["vah"]), val=float("%.8g" % pf["val"]), a=int(pf["a"]), lvl=float("%.8g" % lvl) if lvl else None,
             hvn=[float("%.8g" % ((x[0] + x[1]) / 2)) for x in pf["hvn"]][:12])
    if ypoc: d["ypoc"] = float("%.8g" % ypoc)
    if extra: d.update(extra)
    return d


def vp_signals(pre, P):
    """-> (sig {свеча: 'L'|'S'}, chan {свеча: (нижняя(j), верхняя(j))}, tags {свеча: 'b'|'k'|'f'}, over {свеча: dict(stop, tp, be_thr, vpx)}).
    b — отбой от границы/VAL/VAH на HVN; k — истинный пробой (за границей пустота); f — возврат внутрь канала после ложного пробоя (за границей плотный объём или вчерашний POC)."""
    pr = {k: P.get(k, d) for k, d in VPD.items()}
    o, h, l, c, v, t, atr = pre["o"], pre["h"], pre["l"], pre["c"], pre["v"], pre["t"], pre["atr"]
    M = pre["M"]
    tf = P.get("tf", "15m")
    zd, zv, zb = ZZ_DEF.get(tf, (12, 1.0, 3))
    depth = int(pr["zz_depth"] or zd); dev = float(pr["zz_dev"] or zv); back = int(pr["zz_back"] or zb)
    piv = zigzag(h[:M], l[:M], depth, dev, back)
    sig, chan, tags, over = {}, {}, {}, {}
    if len(piv) < 4: return sig, chan, tags, over
    rows = int(pr["vp_rows"]); vaP = float(pr["vp_va"]); hv, lv = float(pr["vp_hvn"]), float(pr["vp_lvn"])
    start_ov = None
    sym = P.get("sym")
    s_ = (pr["vp_starts"] or {}).get(sym) or (pr["vp_start"] if pr["vp_start"] not in (None, "", "auto") else None)
    if s_:
        try:
            import datetime as _dt
            ms = int(_dt.datetime.strptime(str(s_)[:16].replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=_dt.timezone.utc).timestamp() * 1000) if not str(s_).isdigit() else int(s_)
            start_ov = int(np.searchsorted(t, ms))
        except Exception:
            start_ov = None
    day_cache = {}
    tfms = (float(t[1]) - float(t[0])) if len(t) > 1 else 300000.0

    def ypoc_at(i):
        d = int(t[i] // 86400000) - 1
        if d not in day_cache:
            idx = np.nonzero((t // 86400000) == d)[0]
            pf_ = profile(h, l, v, int(idx[0]), int(idx[-1]), rows, vaP, hv, lv) if len(idx) >= 20 else None
            day_cache[d] = pf_["poc"] if pf_ else None
        return day_cache[d]

    pcache = {}

    def prof_at(a, i):
        k = pcache.get(a)
        if k is None or i - k[0] >= 6:
            k = (i, profile(h, l, v, a, i, rows, vaP, hv, lv)); pcache[a] = k
        return k[1]

    pk = 0
    HP, LP = [], []  # подтверждённые вершины и впадины к текущей свече
    pend_rt, pend_ret = None, None
    W = max(60, depth * 4)
    for i in range(W, M):
        while pk < len(piv) and piv[pk]["conf"] <= i:
            (HP if piv[pk]["k"] == "H" else LP).append(piv[pk]); pk += 1
        if len(HP) < 2 or len(LP) < 2: continue
        H1, H2, L1, L2 = HP[-2], HP[-1], LP[-2], LP[-1]
        flat = abs(H1["p"] - H2["p"]) / H2["p"] * 100 <= float(pr["vp_flat_delta"]) and abs(L1["p"] - L2["p"]) / L2["p"] * 100 <= float(pr["vp_flat_delta"])
        mode = None
        if pr["vp_mode"] in ("auto", "flat") and flat:
            mode = "flat"; ub, lb = max(H1["p"], H2["p"]), min(L1["p"], L2["p"])
            a0 = min(H1["i"], H2["i"], L1["i"], L2["i"])
            up = (lambda j, u=ub: u); lo = (lambda j, u=lb: u)
        elif pr["vp_mode"] in ("auto", "trend") and not flat:
            sH = (H2["p"] - H1["p"]) / max(1, H2["i"] - H1["i"]); sL = (L2["p"] - L1["p"]) / max(1, L2["i"] - L1["i"])
            if sH * sL > 0 and abs(sH - sL) <= float(pr["vp_par"]) * max(abs(sH), abs(sL)):
                up = (lambda j, p=H2["p"], q=H2["i"], s=sH: p + s * (j - q)); lo = (lambda j, p=L2["p"], q=L2["i"], s=sL: p + s * (j - q))
                if up(i) > lo(i) and up(H1["i"]) > lo(H1["i"]):
                    mode = "trend"; a0 = piv[pk - 2]["i"] if pk >= 2 else min(H1["i"], L1["i"])  # начало последнего завершённого луча ZigZag
        if mode is None: continue
        if start_ov is not None and start_ov < i - 10: a0 = start_ov
        if i - a0 < 12: continue
        u_i, l_i = up(i), lo(i)
        if not u_i > l_i: continue
        a_ = atr[i]
        if not a_ > 0: continue
        pf = prof_at(a0, i)
        if pf is None: continue
        tol = float(pr["vp_tol_atr"]) * a_; buf = float(pr["vp_buf_atr"]) * a_
        cur = (lo, up)
        ent = c[i]  # оценка цены входа (открытие следующей свечи ≈ закрытие этой)

        def mk(side, stop, tp, kind, tag, lvl=None, poc_be=None):
            risk = (ent - stop) if side == "L" else (stop - ent)
            if risk <= 0 or tp is None: return False
            rew = (tp - ent) if side == "L" else (ent - tp)
            if rew <= 0 or rew / risk < float(pr["vp_min_rr"]): return False
            if kind in ("break", "retest") and float(pr["vp_room_r"]) > 0:  # запас хода: до ближайшего подтверждённого лоя (шорт) / хая (лонг) и до стенки стакана не меньше vp_room_r x риск
                rm = []
                if side == "S": rm += [ent - q["p"] for q in LP[-30:] if q["p"] < ent]
                else: rm += [q["p"] - ent for q in HP[-30:] if q["p"] > ent]
                bw = walls_at(book_series(sym, t[W] if len(t) > W else t[0]), int(t[i]) + tfms) if sym else None
                if bw:
                    rm += [ent - w_["p"] for w_ in bw if w_["s"] == "b" and w_["p"] < ent] if side == "S" else [w_["p"] - ent for w_ in bw if w_["s"] == "a" and w_["p"] > ent]
                if rm and min(rm) < float(pr["vp_room_r"]) * risk: return False
            thr = float(pr["vp_be_frac"]) * rew / ent * 100
            if pr["vp_be_poc"] and poc_be is not None:
                dpoc = (poc_be - ent) if side == "L" else (ent - poc_be)
                if 0 < dpoc < rew: thr = dpoc / ent * 100  # безубыток при достижении линии POC (если POC лежит между входом и целью)
            sig[i], chan[i], tags[i] = side, cur, tag
            thr = max(0.1, float(thr))
            over[i] = dict(stop=float(stop), tp=float(tp), be_thr=thr, be_lock=round(min(0.3, 0.5 * thr), 3), vpx=_pack_vpx(pf, mode, kind, lvl, ypoc_at(i)))
            return True

        # --- отбой: граница канала или VAL/VAH совпадает с HVN; стоп сразу за узлом, цель POC
        if pr["vp_bounce"] and i not in sig:
            for lvl in sorted((l_i, pf["val"]), key=lambda x: abs(l[i] - x)):
                nd = node_near(pf["hvn"], lvl, tol)
                if nd and l[i] <= lvl + tol and c[i] > lvl and c[i] < u_i and pf["poc"] > ent:
                    if mk("L", min(nd[0], l[i]) - buf, pf["poc"], "bounce", "b", lvl, None): break
            if i not in sig:
                for lvl in sorted((u_i, pf["vah"]), key=lambda x: abs(h[i] - x)):
                    nd = node_near(pf["hvn"], lvl, tol)
                    if nd and h[i] >= lvl - tol and c[i] < lvl and c[i] > l_i and pf["poc"] < ent:
                        if mk("S", max(nd[1], h[i]) + buf, pf["poc"], "bounce", "b", lvl, None): break
        # --- пробой границы канала импульсной свечой
        if i > 0 and (h[i] - l[i]) >= float(pr["vp_imp_atr"]) * a_:
            for side in ("L", "S"):
                brd, prev_brd = (u_i, up(i - 1)) if side == "L" else (l_i, lo(i - 1))
                beyond = (c[i] - brd) if side == "L" else (brd - c[i])
                was_in = (c[i - 1] <= prev_brd) if side == "L" else (c[i - 1] >= prev_brd)
                if beyond < 0.2 * a_ or not was_in: continue
                hb = max(0, i - int(pr["vp_hist_bars"]))
                hpf = profile(h, l, v, hb, i - 1, rows, vaP, hv, lv, lo=min(float(l[hb:i].min()), brd - 3 * a_), hi=max(float(h[hb:i].max()), brd + 3 * a_))
                z0, z1 = (brd, brd + float(pr["vp_ahead_atr"]) * a_) if side == "L" else (brd - float(pr["vp_ahead_atr"]) * a_, brd)
                dens = density_ahead(hpf, z0, z1)
                yp = ypoc_at(i)
                yin = yp is not None and z0 - 0.2 * a_ <= yp <= z1 + 0.2 * a_
                if dens is None: continue
                if dens >= hv or yin:  # ложный пробой: за границей плотный исторический объём или вчерашний POC → ищем возврат внутрь
                    if pr["vp_return"]: pend_ret = dict(side=("S" if side == "L" else "L"), bi=i, exp=i + int(pr["vp_ret_bars"]), ext=(h[i] if side == "L" else l[i]), br=side)
                elif dens <= lv or str(pr["vp_neutral"]) == "true":  # истинный пробой: за границей зона пустоты (LVN)
                    if not pr["vp_breakout"]: continue
                    if pr["vp_wick_void"] and bool(((l[hb:i] <= z1) & (h[hb:i] >= z0)).any()): continue  # цена в этой зоне уже бывала (прокол тенью) - это не пустота, пробой пропускаем
                    if str(pr["vp_bo_entry"]) == "retest":
                        pend_rt = dict(side=side, bi=i, exp=i + int(pr["vp_retest_bars"]))
                    else:
                        stop = brd - float(pr["vp_sl_atr"]) * a_ if side == "L" else brd + float(pr["vp_sl_atr"]) * a_
                        risk = abs(ent - stop)
                        tp = ent + float(pr["vp_rr"]) * risk if side == "L" else ent - float(pr["vp_rr"]) * risk
                        nx = [(n[0] + n[1]) / 2 for n in (hpf["hvn"] if hpf else []) if ((n[0] + n[1]) / 2 > ent) == (side == "L") and abs((n[0] + n[1]) / 2 - ent) >= 0.5 * risk]
                        if nx: tp = min(tp, min(nx)) if side == "L" else max(tp, max(nx))  # цель не дальше ближайшего HVN по ходу
                        mk(side, stop, tp, "break", "k", brd, pf["poc"])
        # --- ретест пробитой границы после истинного пробоя
        if pend_rt and i > pend_rt["bi"] and i not in sig:
            s_ = pend_rt["side"]
            if i > pend_rt["exp"] or (s_ == "L" and c[i] < u_i) or (s_ == "S" and c[i] > l_i): pend_rt = None
            else:
                brd = u_i if s_ == "L" else l_i
                if (s_ == "L" and l[i] <= brd + tol and c[i] > brd) or (s_ == "S" and h[i] >= brd - tol and c[i] < brd):
                    stop = brd - float(pr["vp_sl_atr"]) * a_ if s_ == "L" else brd + float(pr["vp_sl_atr"]) * a_
                    risk = abs(ent - stop)
                    tp = ent + float(pr["vp_rr"]) * risk if s_ == "L" else ent - float(pr["vp_rr"]) * risk
                    if mk(s_, stop, tp, "retest", "k", brd, pf["poc"]): pend_rt = None
        # --- возврат внутрь канала после ложного пробоя
        if pend_ret and i > pend_ret["bi"]:
            r_ = pend_ret
            r_["ext"] = max(r_["ext"], h[i]) if r_["br"] == "L" else min(r_["ext"], l[i])
            if i > r_["exp"]: pend_ret = None
            elif i not in sig and ((r_["br"] == "L" and c[i] < u_i) or (r_["br"] == "S" and c[i] > l_i)):
                stop = r_["ext"] + buf if r_["side"] == "S" else r_["ext"] - buf
                if mk(r_["side"], stop, pf["poc"], "return", "f", u_i if r_["side"] == "S" else l_i, None): pend_ret = None
    return sig, chan, tags, over
