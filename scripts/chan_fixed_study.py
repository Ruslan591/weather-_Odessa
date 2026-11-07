# -*- coding: utf-8 -*-
"""chan_fixed_study.py [TF] [DAYS] [N1,N2,..]  -- бэктест канала регрессии Fixed N с заморозкой (ТЗ пользователя 2026-11-07).

Канал: окно N свечей (включая свечу построения), регрессия по close, +-2 sigma остатков (n-2), тип up/down/flat по порогу 0.03 ATR/бар.
Канал строится на закрытой свече i и работает со свечи i+1. Заморожен: окно, наклон, sigma не меняются, линии продлеваются вправо.
Перестройка ТОЛЬКО после подтверждённого выхода: свеча закрылась за внешней границей и не менее 50% тела за линией; новый канал строится сразу по N свечам, включая свечу выхода.

Входы (одна позиция на пару, как в боте):
  lim   - базовый вариант текущего бота: лимит на границе (спроецирован на следующую свечу), 0..3 ATR от закрытия, живёт 1 свечу, вход мейкер.
  c1c/c1h - сигнальная свеча коснулась границы тенью и закрылась внутри; следующая свеча открылась И закрылась выше (ниже для short) сигнальной: c1c = выше close сигнальной, c1h = выше high (ниже low). Вход по рынку на открытии свечи после подтверждающей.
  pin   - пин-бар: тень наружу >= 50% размаха и >= 2 тел, закрытие внутри. Вход по рынку на следующей открытии.
  eng   - поглощение: предыдущая свеча коснулась границы, текущая бычья/медвежья перекрывает телом тело предыдущей и закрылась внутри.
  dbl   - двойной тест: два касания (интервал 2..15 свечей, второе не обновило экстремум более чем на 0.1 ATR), затем свеча к центру с телом >= 0.5 ATR, закрытие внутри.
  vol=1 - объём на разворотной/подтверждающей свече >= 1.5 x средний объём 3 предыдущих.
Режимы канала: with (по направлению), flat (оба направления в flat), counter (против, диагностика), user = with + flat.
Цели отбоя: q1 (1/4: линия -1 sigma от границы), mid (середина), q3 (3/4: +1 sigma), opp (противоположная граница -0.1 ATR). Стопы: bot = max(1.2 ATR, 0.5%), edge = 0.5 sigma за внешней границей (не меньше max(1 ATR, 0.3%)).
Пробой (b1 = свеча выхода с короткой тенью (тень <= тела), вход по рынку на следующей открытии; b2 = пробой + ретест за 1..3 свечи: касание тенью старой линии и закрытие по ту же сторону, что пробой, вход на следующей открытии).
  sel: all / cont (по направлению старого канала) / rev (против). Цели: ht = max(высота канала, 2R), r2 = 2R, r3 = 3R; стоп bot.
Контроль: те же расстояния стопа и цели в ATR, случайные свечи, вход по рынку (для lim - контроль из chan_tv_study).
Минимальная дистанция до цели 0.15% цены. maxb = 48 свечей. Комиссии: мейкер 0.02, тейкер 0.05 (вход по рынку: +0.03 к круговой).
Запуск: python chan_fixed_study.py 5m 60 100   (рядом chan_tv_study.py). Переменная FSYNTH=1 - синтетика, 2 пары.
"""
import sys, os, time
import numpy as np
TF = sys.argv[1] if len(sys.argv) > 1 else "5m"
DAYS = sys.argv[2] if len(sys.argv) > 2 else "60"
NLIST = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "100").split(",")]
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "chan_tv_study.py"), encoding="utf-8").read().rstrip()
assert src.endswith("main()"); src = src[:-len("main()")]
sys.argv = ["chan_tv_study.py", TF, DAYS]
ns = {"__name__": "chan_tv_study"}; exec(compile(src, "chan_tv_study.py", "exec"), ns)
klines, atr14, run_order, control_trades = (ns[k] for k in ("klines", "atr14", "run_order", "control_trades"))
SYMS = ns["SYMS"]
if os.environ.get("FSYNTH"): SYMS = SYMS[:2]
DRAWS = 3; ns["DRAWS"] = DRAWS
EXTRA = 0.03; MINTP = 0.0015; MAXB = 48; KS = 2.0; FLAT = 0.03; BODY_OUT = 0.5
MODES = ("with", "flat", "counter", "user"); CONFS = ("c1c", "c1h", "pin", "eng", "dbl"); TG = ("q1", "mid", "q3", "opp"); STOPS = ("bot", "edge")
BTG = ("ht", "r2", "r3"); SELS = ("all", "cont", "rev")


def build(o, h, l, c, atr, N):
    """Замороженные каналы. Возвращает mid, sd, dr, cid по свечам (значения линий на свече i, построены по данным <= i-1) и список выходов."""
    n = len(c); mid = np.full(n, np.nan); sd = np.full(n, np.nan); dr = np.zeros(n, int); cid = np.full(n, -1, int); exits = []
    x = np.arange(N, dtype=float); xm = x.mean(); sxx = ((x - xm) ** 2).sum()

    def make(i):
        y = c[i - N + 1:i + 1]; ym = y.mean(); s = ((x - xm) * (y - ym)).sum() / sxx; a0 = ym - s * xm
        res = y - (a0 + s * x); sdv = float(np.sqrt((res ** 2).sum() / (N - 2)))
        th = FLAT * atr[i]; d = 1 if s > th else (-1 if s < -th else 0)
        return a0, s, i - N + 1, sdv, d
    act = None; nid = 0; chans = 0
    for i in range(N - 1, n):
        if act is None:
            act = make(i); nid += 1; chans += 1; continue
        a0, s, st, sdv, d = act; m = a0 + s * (i - st); mid[i] = m; sd[i] = sdv; dr[i] = d; cid[i] = nid
        U = m + KS * sdv; Lw = m - KS * sdv; bl = min(o[i], c[i]); bh = max(o[i], c[i]); body = max(bh - bl, 1e-12); ex = 0
        if c[i] > U and (bh - max(bl, U)) / body >= BODY_OUT: ex = 1
        elif c[i] < Lw and (min(bh, Lw) - bl) / body >= BODY_OUT: ex = -1
        if ex:
            exits.append((i, ex, a0, s, st, sdv, d)); act = make(i); nid += 1; chans += 1
    return mid, sd, dr, cid, exits, chans


def modeok_of(dr, s, mode):
    if mode == "with": return dr == s
    if mode == "counter": return dr == -s
    if mode == "flat": return dr == 0
    return (dr == s) | (dr == 0)


def signals(kind, s, ctx, vol):
    """Список (i0 = свеча входа по рынку, j = сигнальная свеча)."""
    o, h, l, c, v, atrp, edge, valid = (ctx[k] for k in ("o", "h", "l", "c", "v", "atrp", "edge", "valid"))
    n = len(c); out = []
    with np.errstate(invalid="ignore"):
        touch = (l <= edge) if s > 0 else (h >= edge); inside = (c > edge) if s > 0 else (c < edge)
    base = valid & touch & inside

    def volok(j): return (not vol) or (j >= 3 and v[j] >= 1.5 * v[j - 3:j].mean())
    if kind in ("c1c", "c1h"):
        for j in np.nonzero(base)[0]:
            if j + 2 >= n: continue
            ref = c[j] if kind == "c1c" else (h[j] if s > 0 else l[j])
            ok = (o[j + 1] > ref and c[j + 1] > ref) if s > 0 else (o[j + 1] < ref and c[j + 1] < ref)
            if ok and volok(j + 1): out.append((j + 2, j))
    elif kind == "pin":
        for j in np.nonzero(base)[0]:
            if j + 1 >= n: continue
            rng = h[j] - l[j]
            if rng <= 0: continue
            body = abs(c[j] - o[j]); wick = (min(o[j], c[j]) - l[j]) if s > 0 else (h[j] - max(o[j], c[j]))
            if wick >= 0.5 * rng and wick >= 2 * body and volok(j): out.append((j + 1, j))
    elif kind == "eng":
        for j in np.nonzero(valid & inside & np.r_[False, touch[:-1]])[0]:
            if j + 1 >= n or j < 1: continue
            lo = min(o[j - 1], c[j - 1]); hi = max(o[j - 1], c[j - 1])
            ok = (c[j] > o[j] and o[j] <= lo and c[j] >= hi) if s > 0 else (c[j] < o[j] and o[j] >= hi and c[j] <= lo)
            if ok and volok(j): out.append((j + 1, j))
    elif kind == "dbl":
        with np.errstate(invalid="ignore"):
            t2 = valid & ((l <= edge + 0.1 * atrp) if s > 0 else (h >= edge - 0.1 * atrp))
            dirc = (c > o) if s > 0 else (c < o)
            cand = np.nonzero(valid & inside & dirc & (np.abs(c - o) >= 0.5 * atrp))[0]
        tidx = np.nonzero(t2)[0]
        for r in cand:
            if r + 1 >= n: continue
            w = tidx[(tidx >= r - 15) & (tidx <= r - 1)]; found = False
            for ai in range(len(w) - 1):
                for bi in range(ai + 1, len(w)):
                    p, q = w[ai], w[bi]
                    if q - p >= 2 and ((l[q] >= l[p] - 0.1 * atrp[q]) if s > 0 else (h[q] <= h[p] + 0.1 * atrp[q])):
                        found = True; break
                if found: break
            if found and volok(r): out.append((r + 1, r))
    return out


def mk_market(o, atr, mid, sd, cid, s, i0, j, tg, stp, n):
    if i0 >= n - MAXB - 2 or cid[i0] < 0 or cid[i0] != cid[j]: return None
    e = float(o[i0]); a = float(atr[i0 - 1]); m = mid[i0]; sg = sd[i0]
    if a <= 0 or np.isnan(m): return None
    if tg == "q1": t = m - s * sg
    elif tg == "q3": t = m + s * sg
    elif tg == "mid": t = m
    else: t = (m + s * KS * sg) - s * 0.1 * a
    if (t - e) * s < MINTP * e: return None
    if stp == "bot": risk = max(1.2 * a, 0.005 * e)
    else:
        st0 = m - s * 2.5 * sg; risk = (e - st0) * s
        if risk <= 0: return None
        risk = max(risk, a, 0.003 * e)
    return dict(side=s, i0=i0, life=1, level=e * (1 + s * 1e-7), stop=e - s * risk, tgt=t, cancel=None, maxb=MAXB, rk=risk / a, tgd=abs(t - e) / a, mk=1)


def run_set(o, h, l, c, orders):
    res = []; busy = -1
    for od in sorted(orders, key=lambda x: x["i0"]):
        if od["i0"] <= busy: continue
        r = run_order(o, h, l, c, od)
        if r:
            busy = r["exit"]; r["i0"] = od["i0"]
            if od.get("mk"): r["fee"] += EXTRA
            res.append(r)
    return res


def ctl_market(o, h, l, c, atr, orders, rng):
    res = []; n = len(c)
    for od in orders:
        for _ in range(DRAWS):
            j = int(rng.integers(ns["WARM"], n - MAXB - 3)); a = atr[j - 1]; s = od["side"]; e = o[j]
            cd = dict(side=s, i0=j, life=1, level=e * (1 + s * 1e-7), stop=e - s * od["rk"] * a, tgt=e + s * od["tgd"] * a, cancel=None, maxb=MAXB)
            r = run_order(o, h, l, c, cd)
            if r: r["fee"] += EXTRA; res.append(r)
    return res


def gen_lim(c, atr, mid, sd, dr, cid, mode, tg, stp):
    out = []; n = len(c)
    for j in range(ns["WARM"], n):
        if cid[j] < 0 or np.isnan(mid[j]): continue
        a = float(atr[j - 1])
        if 4 * KS / 2 * sd[j] < 1.5 * a: continue
        for s in (1, -1):
            if not modeok_of(np.array([dr[j]]), s, mode)[0]: continue
            lv = mid[j] - s * KS * sd[j]; dist = (c[j - 1] - lv) * s / a
            if not 0 <= dist <= 3: continue
            m = mid[j]; sg = sd[j]
            t = m - s * sg if tg == "q1" else (m + s * sg if tg == "q3" else (m if tg == "mid" else (m + s * KS * sg) - s * 0.1 * a))
            if (t - lv) * s < MINTP * lv: continue
            if stp == "bot": risk = max(1.2 * a, 0.005 * lv)
            else:
                st0 = m - s * 2.5 * sg; risk = (lv - st0) * s
                if risk <= 0: continue
                risk = max(risk, a, 0.003 * lv)
            out.append(dict(side=s, i0=j, life=1, level=lv, stop=lv - s * risk, tgt=t, cancel=None, maxb=MAXB, dist=dist, rk=risk / a, tgd=abs(t - lv) / a, cd=0.0))
    return out


def break_orders(o, h, l, c, v, atr, exits, kind, sel, vol, tg):
    out = []; n = len(c)
    for (b, d, a0, s_, st, sdv, dold) in exits:
        if sel == "cont" and d != dold: continue
        if sel == "rev" and d != -dold: continue
        if b + 6 >= n or b < 4: continue
        if vol and not (v[b] >= 1.5 * v[b - 3:b].mean()): continue
        body = abs(c[b] - o[b])
        if kind == "b1":
            wick = (h[b] - max(o[b], c[b])) if d > 0 else (min(o[b], c[b]) - l[b])
            if wick > body: continue
            i0 = b + 1
        else:
            i0 = None
            for r in range(b + 1, b + 4):
                lr = a0 + s_ * (r - st) + d * KS * sdv
                if (d > 0 and l[r] <= lr and c[r] >= lr) or (d < 0 and h[r] >= lr and c[r] <= lr):
                    i0 = r + 1; break
            if i0 is None: continue
        if i0 >= n - MAXB - 2: continue
        e = float(o[i0]); a = float(atr[i0 - 1])
        if a <= 0: continue
        risk = max(1.2 * a, 0.005 * e); H = 2 * KS * sdv
        dist = max(H, 2 * risk) if tg == "ht" else (2 * risk if tg == "r2" else 3 * risk)
        if dist < MINTP * e: continue
        out.append(dict(side=d, i0=i0, life=1, level=e * (1 + d * 1e-7), stop=e - d * risk, tgt=e + d * dist, cancel=None, maxb=MAXB, rk=risk / a, tgd=dist / a, mk=1))
    return out


def main():
    t0 = time.time(); acc = {}; rng = np.random.default_rng(7); stats = {}
    for si, sym in enumerate(SYMS):
        a = ns["synth"](si) if os.environ.get("FSYNTH") else klines(sym, TF, int(DAYS))
        if len(a) < ns["WARM"] + 600:
            print(sym, "short data", len(a), flush=True); continue
        o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]; v = a[:, 5] if a.shape[1] > 5 else np.ones(len(c)); atr = atr14(h, l, c); n = len(c)
        atrp = np.r_[atr[0], atr[:-1]]
        for N in NLIST:
            mid, sd, dr, cid, exits, chans = build(o, h, l, c, atr, N)
            S = stats.setdefault(N, dict(bars=0, chans=0, up=0, dn=0, fl=0, exits=0)); S["bars"] += n; S["chans"] += chans; S["exits"] += len(exits)
            S["up"] += int((dr == 1).sum()); S["dn"] += int((dr == -1).sum()); S["fl"] += int(((dr == 0) & (cid >= 0)).sum())
            print("%s N=%d bars %d channels %d exits %d  %.0fs" % (sym, N, n, chans, len(exits), time.time() - t0), flush=True)
            U = mid + KS * sd; Lw = mid - KS * sd; wide = (U - Lw) >= 1.5 * atrp
            # базовые лимиты
            for mode in MODES:
                for tg in TG:
                    for stp in STOPS:
                        ords = gen_lim(c, atr, mid, sd, dr, cid, mode, tg, stp)
                        A = acc.setdefault((N, "lim", mode, "-", 0, tg, stp), dict(real=[], ctl=[], n=n))
                        rt = []; busy = -1
                        for od in sorted(ords, key=lambda x: x["i0"]):
                            if od["i0"] <= busy: continue
                            r = run_order(o, h, l, c, od)
                            if r: busy = r["exit"]; r["i0"] = od["i0"]; rt.append(r)
                        A["real"] += rt; A["ctl"] += control_trades(o, h, l, c, atr, ords, rng)
            # подтверждённые отбои
            for mode in MODES:
                for kind in CONFS:
                    for vol in (0, 1):
                        sigs = []
                        for s in (1, -1):
                            edge = Lw if s > 0 else U
                            valid = (cid >= 0) & wide & modeok_of(dr, s, mode) & ~np.isnan(edge)
                            ctx = dict(o=o, h=h, l=l, c=c, v=v, atrp=atrp, edge=edge, valid=valid)
                            sigs += [(s, i0, j) for (i0, j) in signals(kind, s, ctx, vol)]
                        for tg in TG:
                            for stp in STOPS:
                                ords = [x for x in (mk_market(o, atr, mid, sd, cid, s, i0, j, tg, stp, n) for (s, i0, j) in sigs) if x]
                                A = acc.setdefault((N, kind, mode, "-", vol, tg, stp), dict(real=[], ctl=[], n=n))
                                A["real"] += run_set(o, h, l, c, ords); A["ctl"] += ctl_market(o, h, l, c, atr, ords, rng)
            # пробои
            for sel in SELS:
                for kind in ("b1", "b2"):
                    for vol in (0, 1):
                        for tg in BTG:
                            ords = break_orders(o, h, l, c, v, atr, exits, kind, sel, vol, tg)
                            A = acc.setdefault((N, kind, "break", sel, vol, tg, "bot"), dict(real=[], ctl=[], n=n))
                            A["real"] += run_set(o, h, l, c, ords); A["ctl"] += ctl_market(o, h, l, c, atr, ords, rng)
    print("\n==== Fixed N regression channel frozen; TF %s, %s days, pairs %d; net after fees; control = same ATR geometry at random bars x%d ====" % (TF, DAYS, len(SYMS), DRAWS))
    for N, S in stats.items():
        print("N=%d: channels %d, avg life %.0f bars, exits %d, bars up/down/flat %.0f%%/%.0f%%/%.0f%%" % (N, S["chans"], S["bars"] / max(S["chans"], 1), S["exits"], 100.0 * S["up"] / (S["up"] + S["dn"] + S["fl"]), 100.0 * S["dn"] / (S["up"] + S["dn"] + S["fl"]), 100.0 * S["fl"] / (S["up"] + S["dn"] + S["fl"])))
    rows = []; K = len(acc)
    for k, A in acc.items():
        if len(A["real"]) < 30: continue
        net = np.array([x["gross"] - x["fee"] for x in A["real"]]); cn = np.array([x["gross"] - x["fee"] for x in A["ctl"]]) if A["ctl"] else np.array([0.0])
        se = np.sqrt(net.var() / len(net) + cn.var() / max(len(cn), 1)); nn = A["n"]
        hn = lambda r: np.mean([x["gross"] - x["fee"] for x in r]) if r else float("nan")
        h1 = [x for x in A["real"] if x["i0"] < nn // 2]; h2 = [x for x in A["real"] if x["i0"] >= nn // 2]
        rows.append((net.mean() - cn.mean(), k, len(net), 100 * (net > 0).mean(), net.mean(), cn.mean(), se, hn(h1), hn(h2)))
    rows.sort(key=lambda r: -r[0] / r[6] if r[6] else 0)
    print("variants total %d, with >=30 fills %d. With K this large the best |diff/se| of pure noise is about 3; look for consistent half1/half2 and many neighbours.\n" % (K, len(rows)))
    hdr = "%-3s %-5s %-8s %-5s v | %-4s %-4s | %5s %5s %8s %8s %7s | %7s %7s"
    print(hdr % ("N", "entry", "mode", "sel", "tgt", "stop", "fills", "win%", "net", "control", "diff/se", "half1", "half2"))
    fm = lambda r: "%-3d %-5s %-8s %-5s %d | %-4s %-4s | %5d %5.1f %+8.3f %+8.3f %+7.2f | %+7.3f %+7.3f" % (r[1][0], r[1][1], r[1][2], r[1][3], r[1][4], r[1][5], r[1][6], r[2], r[3], r[4], r[5], r[0] / r[6] if r[6] else 0, r[7], r[8])
    for r in rows[:30]: print(fm(r))
    print("... worst 5 ...")
    for r in rows[-5:]: print(fm(r))
    print("\n== mean net and mean diff vs control per entry/mode (all variants with >=30 fills, unweighted) ==")
    grp = {}
    for r in rows: grp.setdefault((r[1][0], r[1][1], r[1][2], r[1][3]), []).append(r)
    for k, g in sorted(grp.items(), key=lambda kv: -np.mean([x[0] for x in kv[1]])):
        print("N=%d %-5s %-8s %-5s variants %3d  mean net %+7.3f  mean diff %+7.3f  mean fills %5.0f" % (k[0], k[1], k[2], k[3], len(g), np.mean([x[4] for x in g]), np.mean([x[0] for x in g]), np.mean([x[2] for x in g])))
    print("\nDONE %.0fs" % (time.time() - t0), flush=True)


main()
