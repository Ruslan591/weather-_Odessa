# -*- coding: utf-8 -*-
"""regime_study.py -- проверка классификатора режима рынка (tg_regime) на истории Binance.
Фаза 1: классификатор на ~150 суток 1h (BTC + корзина 20 пар): доли режимов, смены, предсказание движения корзины вперёд (4/12/24 ч, непересекающиеся окна), стабильность по 30-суточным блокам.
Фаза 2: прокси отбоя от линии на 5m (60 суток, 12 пар): регрессионный канал 96 свечей +-2 sigma, лимит на полосе, стоп 1.2 ATR, цель 1/3 высоты канала, 48 свечей; результат по режиму и стороне.
Меры: dATR (ход в ATR; позиция фиксированная), win%, R (результат / риск). Комиссии не учтены. Режим на момент входа = по последней закрытой 1h свече (без заглядывания вперёд).
Запуск: cd /opt/tg-notify && python3 regime_study.py"""
import math, os, sys, time
import numpy as np
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_regime as RG

HOUR = 3600000; BAR = 300000
DAYS_H = 150; DAYS_5 = 60
PAIRS5 = ["ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "NEAR", "UNI", "ATOM"]


def fetch_all(sym, interval, t0, t1, step_ms):
    out = []; t = t0
    while t < t1:
        ch = RG.klines(sym, interval, 1000, start=t)
        if not ch: break
        out += [k for k in ch if not out or k[0] > out[-1][0]]; t = ch[-1][0] + step_ms
        if len(ch) < 1000: break
    return out


def se_mean(xs):
    n = len(xs)
    if n < 2: return 0.0
    mu = sum(xs) / n; return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) / math.sqrt(n)


def phase1():
    now = int(time.time() * 1000); t1 = (now // HOUR) * HOUR; t0 = t1 - DAYS_H * 24 * HOUR
    syms = ["BTC"] + RG.BASKET
    with ThreadPoolExecutor(max_workers=5) as ex: data = list(ex.map(lambda s: fetch_all(s, "1h", t0, t1, HOUR), syms))
    btc = data[0]; print("BTC 1h свечей: %d (%.0f суток)" % (len(btc), len(btc) / 24), flush=True)
    tm = [int(k[0]) for k in btc]; H = np.array([float(k[2]) for k in btc]); L = np.array([float(k[3]) for k in btc]); C = np.array([float(k[4]) for k in btc])
    alt = []
    for ks in data[1:]:
        d = {int(k[0]): float(k[4]) for k in ks}; alt.append(d)
    reg = {}; rows = []
    for i in range(300, len(btc)):
        ch = []
        for d in alt:
            a = d.get(tm[i]); b = d.get(tm[i] - 24 * HOUR)
            if a and b: ch.append(a / b - 1)
        ds = (sum(1 for x in ch if x < 0) / len(ch)) if len(ch) >= 12 else None
        f = RG.regime_at(list(H[max(0, i - 499):i + 1]), list(L[max(0, i - 499):i + 1]), list(C[max(0, i - 499):i + 1]), ds, None)
        if f: reg[tm[i]] = f["raw"]; rows.append((i, f["raw"]))
    print("режим посчитан для %d часов\n" % len(rows), flush=True)
    names = {"down": "падающий", "up": "растущий", "flat": "флэт"}
    n = len(rows); cnt = {k: sum(1 for _, r in rows if r == k) for k in names}
    runs = []; cur = None; ln = 0
    for _, r in rows:
        if r == cur: ln += 1
        else:
            if cur is not None: runs.append((cur, ln))
            cur = r; ln = 1
    runs.append((cur, ln)); short = sum(1 for _, l_ in runs if l_ < 3)
    print("1. Доли режимов за %d суток: " % (n // 24) + ", ".join("%s %d%%" % (names[k], round(100 * cnt[k] / n)) for k in names))
    print("   смен режима: %d (в среднем раз в %.1f суток), из них серий короче 3 ч: %d; медиана серии %d ч" % (len(runs) - 1, n / 24 / max(1, len(runs) - 1), short, sorted(l_ for _, l_ in runs)[len(runs) // 2]))
    # равновзвешенная корзина вперёд
    def fwd_basket(i, hh):
        xs = []
        for d in alt:
            a = d.get(tm[i]); b = d.get(tm[i] + hh * HOUR) if i + hh < len(tm) else None
            if a and b: xs.append(b / a - 1)
        return sum(xs) / len(xs) if len(xs) >= 12 else None
    print("\n2. Предсказание: доход корзины из 20 альтов вперёд после метки режима (окна не пересекаются). «По режиму» = знак: в падающем -1, в растущем +1, во флэте не торгуем")
    for hh in (4, 12, 24):
        sel = [(i, r) for k_, (i, r) in enumerate(rows) if k_ % hh == 0]; byr = {"down": [], "up": [], "flat": []}; follow = []
        for i, r in sel:
            f = fwd_basket(i, hh)
            if f is None: continue
            byr[r].append(f)
            if r != "flat": follow.append(f * (-1 if r == "down" else 1))
        allx = [x for v in byr.values() for x in v]
        print("   горизонт %2d ч (всего %d окон, средний за период %+.2f%%):" % (hh, len(allx), 100 * sum(allx) / max(1, len(allx))))
        for r in ("down", "up", "flat"):
            v = byr[r]
            if v: print("      %-9s n=%3d  средний %+.2f%% ±%.2f%%  доля роста %2d%%" % (names[r], len(v), 100 * sum(v) / len(v), 100 * se_mean(v), round(100 * sum(1 for x in v if x > 0) / len(v))))
        if follow: print("      по режиму (down:-, up:+): n=%d  средний %+.2f%% ±%.2f%% за окно, доля плюсовых %d%%" % (len(follow), 100 * sum(follow) / len(follow), 100 * se_mean(follow), round(100 * sum(1 for x in follow if x > 0) / len(follow))))
    print("\n3. Стабильность по 30-суточным блокам (горизонт 12 ч, торговля по режиму): средний доход за окно, n")
    hh = 12; blk = 30 * 24
    for b0 in range(0, n, blk):
        seg = [(i, r) for k_, (i, r) in enumerate(rows) if b0 <= k_ < b0 + blk and k_ % hh == 0 and r != "flat"]; vals = []
        for i, r in seg:
            f = fwd_basket(i, hh)
            if f is not None: vals.append(f * (-1 if r == "down" else 1))
        share = {k: round(100 * sum(1 for k_, (i, r) in enumerate(rows) if b0 <= k_ < b0 + blk and r == k) / max(1, min(blk, n - b0))) for k in names}
        if vals: print("   блок с %s: n=%3d  %+.2f%% ±%.2f%%  (падающий %d%%, растущий %d%%, флэт %d%%)" % (time.strftime("%m-%d", time.gmtime(tm[rows[b0][0]] / 1000)), len(vals), 100 * sum(vals) / len(vals), 100 * se_mean(vals), share["down"], share["up"], share["flat"]))
    print("\n4. Метки режима за последние 12 суток (раз в сутки, 12:00 UTC): " + " ".join("%s:%s" % (time.strftime("%d", time.gmtime(tm[i] / 1000)), names[r][0]) for i, r in rows[-12 * 24::24]))
    return reg


def phase2(reg):
    now = int(time.time() * 1000); t1 = (now // BAR) * BAR; t0 = t1 - DAYS_5 * 24 * 12 * BAR
    with ThreadPoolExecutor(max_workers=4) as ex: data = list(ex.map(lambda s: fetch_all(s, "5m", t0, t1, BAR), PAIRS5))
    W = 96; res = []
    for sym, ks in zip(PAIRS5, data):
        if len(ks) < 2000: print("  мало данных 5m по %s: %d" % (sym, len(ks))); continue
        t = np.array([int(k[0]) for k in ks]); o = np.array([float(k[1]) for k in ks]); h = np.array([float(k[2]) for k in ks]); l = np.array([float(k[3]) for k in ks]); c = np.array([float(k[4]) for k in ks])
        n = len(c); pc = np.concatenate([[c[0]], c[:-1]]); tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))); cs = np.cumsum(tr); atr = np.full(n, np.nan); atr[14:] = (cs[14:] - cs[:-14]) / 14
        win = np.lib.stride_tricks.sliding_window_view(c, W); x = np.arange(W); xm = x.mean(); den = ((x - xm) ** 2).sum(); ym = win.mean(axis=1)
        b = ((win - ym[:, None]) * (x - xm)).sum(axis=1) / den; a = ym - b * xm; fit = a[:, None] + b[:, None] * x; sig = np.sqrt(((win - fit) ** 2).mean(axis=1)); mid_next = a + b * W
        busy = {1: -1, -1: -1}
        for j in range(len(win) - 60):
            i = j + W - 1; at = atr[i]
            if np.isnan(at) or at <= 0: continue
            up = mid_next[j] + 2 * sig[j]; lo = mid_next[j] - 2 * sig[j]; Hh = 4 * sig[j]
            if Hh < 1.5 * at: continue
            nxt = i + 1; long_t = l[nxt] <= lo; short_t = h[nxt] >= up
            if long_t == short_t: continue
            s = 1 if long_t else -1
            if busy[s] >= i: continue
            entry = lo if s > 0 else up; stop = entry - s * 1.2 * at; tp = entry + s * 0.33 * Hh
            if (tp - entry) * s < max(0.0015 * entry, 0.5 * at): continue
            out = None; end = min(n, nxt + 1 + 48); k_end = nxt + 1
            for k in range(nxt + 1, end):
                hs = (l[k] <= stop) if s > 0 else (h[k] >= stop); ht = (h[k] >= tp) if s > 0 else (l[k] <= tp); k_end = k
                if hs: out = (stop - entry) * s; wn = 0; break
                if ht: out = (tp - entry) * s; wn = 1; break
            if out is None: out = (c[end - 1] - entry) * s; wn = 0; k_end = end - 1
            busy[s] = k_end
            r_ = reg.get(int(t[i] // HOUR * HOUR - HOUR))
            if r_ is None: continue
            risk = 1.2 * at; res.append({"t": int(t[i]), "side": s, "reg": r_, "d": out / at, "R": out / risk, "w": wn, "sym": sym})
    print("\nПрокси отбоя: сигналов %d на %d парах за %d суток\n" % (len(res), len(PAIRS5), DAYS_5), flush=True)
    def st(xs):
        if not xs: return "n=0"
        d = [x["d"] for x in xs]; return "n=%4d win %2d%% dATR %+.2f ±%.2f  R %+.2f" % (len(xs), round(100 * sum(x["w"] for x in xs) / len(xs)), sum(d) / len(d), se_mean(d), sum(x["R"] for x in xs) / len(xs))
    print("5. Отбой от линии (регрессионный канал, лимит на полосе, стоп 1.2 ATR, цель 1/3 высоты): по режиму и стороне")
    names = {"down": "падающий", "up": "растущий", "flat": "флэт"}
    for r in ("down", "up", "flat"):
        for s, sn in ((1, "LONG "), (-1, "SHORT")): print("   %-9s %s %s" % (names[r], sn, st([x for x in res if x["reg"] == r and x["side"] == s])))
    al = [x for x in res if (x["reg"] == "down" and x["side"] == -1) or (x["reg"] == "up" and x["side"] == 1)]; ag = [x for x in res if (x["reg"] == "down" and x["side"] == 1) or (x["reg"] == "up" and x["side"] == -1)]; fl = [x for x in res if x["reg"] == "flat"]
    print("\n   ПО режиму   (шорт в падающем, лонг в растущем): %s" % st(al)); print("   ПРОТИВ режима (лонг в падающем, шорт в растущем):  %s" % st(ag)); print("   флэт (обе стороны):                                %s" % st(fl)); print("   все сигналы:                                       %s" % st(res))
    print("\n6. Стабильность по блокам по 15 суток: по режиму / против режима (dATR)")
    tmin = min(x["t"] for x in res); blk = 15 * 24 * HOUR
    for bi in range(0, DAYS_5 // 15 + 1):
        a0 = tmin + bi * blk; a1 = a0 + blk; sa = [x for x in al if a0 <= x["t"] < a1]; sg = [x for x in ag if a0 <= x["t"] < a1]
        if sa or sg: print("   с %s: по режиму %s | против %s" % (time.strftime("%m-%d", time.gmtime(a0 / 1000)), st(sa), st(sg)))


if __name__ == "__main__":
    reg = phase1(); phase2(reg)
