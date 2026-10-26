# -*- coding: utf-8 -*-
"""Исследование: (A) правила робота (tl_*) на длинной истории 1h/4h; (B) другие правила входа против случайных входов.
Запуск: cd /opt/trading-bot/classic && venv/bin/python /tmp/robot_research.py [A|B|AB]
Выход: /tmp/research_A.json, /tmp/research_B.json, сводки в stdout. gross = результат до комиссий (в %)."""
import sys, json, time, os, pickle, urllib.request, collections, statistics as st
import numpy as np
import pandas as pd
import classic_strategy as cs

MODE = sys.argv[1] if len(sys.argv) > 1 else "AB"
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
TFMS = {"5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}
PAIRS = ["BTCUSDT", "BNBUSDT", "SOLUSDT", "NEARUSDT", "ZECUSDT", "IOSTUSDT", "NILUSDT", "PHAUSDT", "CHIPUSDT", "TREEUSDT"]
NOW = int(time.time() * 1000)


def fetch(sym, tf, days):
    fn = "/tmp/kl_%s_%s_%d.pkl" % (sym, tf, days)
    if os.path.exists(fn):
        return pickle.load(open(fn, "rb"))
    need = NOW - days * 86400000 - 300 * TFMS[tf]
    parts, end = [], None
    for _ in range(400):
        data = None
        for b in BASES:
            try:
                url = "%s/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (b, sym, tf) + ("&endTime=%d" % end if end else "")
                data = json.load(urllib.request.urlopen(url, timeout=25))
                break
            except Exception:
                time.sleep(1.5)
        if not data:
            break
        parts.insert(0, data)
        end = int(data[0][0]) - 1
        if len(data) < 1000 or int(data[0][0]) <= need:
            break
        time.sleep(0.12)
    if not parts:
        raise RuntimeError("нет данных " + sym + " " + tf)
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for col in "ohlcv":
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["ct"] = df["ct"].astype("int64")
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    pickle.dump(df, open(fn, "wb"))
    return df


def month_t(T):
    """Консервативная оценка: t по помесячным средним gross (сделки одного месяца по всем монетам — один кластер)."""
    g = collections.defaultdict(list)
    for t in T:
        g[t["t_in"] // (30 * 86400000)].append(t["gross"])
    ms = [sum(v) / len(v) for v in g.values() if len(v) >= 5]
    if len(ms) < 3:
        return 0.0, len(ms)
    sd = st.stdev(ms)
    return (sum(ms) / len(ms)) / (sd / len(ms) ** 0.5) if sd else 0.0, len(ms)


def stats(T):
    n = len(T)
    if n < 30:
        return None
    g = [t["gross"] for t in T]
    mg = sum(g) / n
    se = st.pstdev(g) / n ** 0.5
    tm, nm = month_t(T)
    tmid = sorted(t["t_in"] for t in T)[n // 2]
    h1 = [t["gross"] for t in T if t["t_in"] < tmid]
    h2 = [t["gross"] for t in T if t["t_in"] >= tmid]
    bysym = collections.defaultdict(list)
    for t in T:
        bysym[t["sym"]].append(t["gross"])
    pos = sum(1 for v in bysym.values() if sum(v) / len(v) > 0)
    return dict(n=n, win=round(100 * sum(1 for t in T if t["net"] > 0) / n), gross=mg, t=mg / se if se else 0, tm=tm, nm=nm,
                h1=sum(h1) / len(h1) if h1 else 0, h2=sum(h2) / len(h2) if h2 else 0, pos=pos, nsym=len(bysym), net=mg - 0.10)


def fmt(k, s):
    return "%-34s n %5d win%% %2d gross %+.3f t %+.1f t_мес %+.1f (мес %d) | пол1 %+.3f пол2 %+.3f | монет+ %d/%d | net %+.3f" % (
        k, s["n"], s["win"], s["gross"], s["t"], s["tm"], s["nm"], s["h1"], s["h2"], s["pos"], s["nsym"], s["net"])


def pack(res, sym, tf, frm, extra):
    out = []
    for x in res:
        if x["open"] or x["t_in"] < frm:
            continue
        y = dict(sym=sym, tf=tf, t_in=int(x["t_in"]), gross=float(x["gross"]), net=float(x["net"]), side=x["side"])
        y.update(extra)
        out.append(y)
    return out


def is_bot(cfg):
    stg = [x for x in (cfg.get("stages") or []) if x and x.get("t")]
    return bool(stg) and stg[0]["t"].startswith("tl_")


def mode_a():
    runs = json.load(open("runs.json", encoding="utf-8"))
    items = collections.OrderedDict()
    for r in runs:
        if is_bot(r["cfg"]) and r["cfg"]["tf"] in ("1h", "4h"):
            items.setdefault((r["sym"], r["cfg"]["tf"]), r["cfg"])
    allt = []
    for (sym, tf), cfg in sorted(items.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        t0 = time.time()
        try:
            df = fetch(sym, tf, 365)
            P = dict(cs.PARAMS, **dict(cfg, sym=sym))
            frm = NOW - 365 * 86400000
            P["sim_from_ms"] = frm
            res = cs.simulate(df, NOW, P)
        except Exception as e:
            print("A ОШИБКА", sym, tf, str(e)[:160], flush=True)
            continue
        tr = pack(res, sym, tf, frm, {"sig": None})
        for y, x in zip(tr, [z for z in res if not z["open"] and z["t_in"] >= frm]):
            y["sig"] = x.get("sig")
        allt += tr
        print("A %s %s: свечей %d (c %s), сделок %d, %.0f с" % (sym, tf, len(df), time.strftime("%Y-%m-%d", time.gmtime(df.t.iloc[0] / 1000)), len(tr), time.time() - t0), flush=True)
    json.dump(allt, open("/tmp/research_A.json", "w"))
    print("\n==== A: ПРАВИЛА РОБОТА НА ДЛИННОЙ ИСТОРИИ (до 365 дней)", flush=True)
    for tf in ("1h", "4h"):
        T = [t for t in allt if t["tf"] == tf]
        s = stats(T)
        if s:
            print(fmt(tf + " все", s))
        for sg, nm in (("k", "пробой"), ("b", "отбой")):
            s = stats([t for t in T if t["sig"] == sg])
            if s:
                print(fmt(tf + " " + nm, s))
        for sd in ("L", "S"):
            s = stats([t for t in T if t["side"] == sd])
            if s:
                print(fmt(tf + " сторона " + sd, s))
    print(flush=True)


def sigs_all(pre):
    c, h, l, o, v = (np.asarray(pre[k], float) for k in ("c", "h", "l", "o", "v"))
    n = len(c)
    S = pd.Series
    out = {}

    def ev(cond):
        a = np.asarray(cond, bool)
        b = np.zeros(n, bool)
        b[1:] = a[1:] & ~a[:-1]
        return b
    hh20, ll20 = S(h).rolling(20).max().shift(1).values, S(l).rolling(20).min().shift(1).values
    hh55, ll55 = S(h).rolling(55).max().shift(1).values, S(l).rolling(55).min().shift(1).values
    up20, dn20 = ev(c > hh20), ev(c < ll20)
    up55, dn55 = ev(c > hh55), ev(c < ll55)
    ma, sd = S(c).rolling(20).mean().values, S(c).rolling(20).std().values
    bup, bdn = ev(c > ma + 2 * sd), ev(c < ma - 2 * sd)
    rsi = np.asarray(pre["rsi"], float)
    rlo, rhi = ev(rsi < 25), ev(rsi > 75)
    e20, e50 = np.asarray(pre["e20"], float), np.asarray(pre["e50"], float)
    cu, cd = ev(e20 > e50), ev(e20 < e50)
    vavg = np.asarray(pre["vavg"], float)
    spk = (v > 3 * vavg) & (vavg > 0)
    vup, vdn = ev(spk & (c > o)), ev(spk & (c < o))

    def mk(longs, shorts):
        d = {}
        for i in np.where(longs)[0]:
            d[int(i)] = "L"
        for i in np.where(shorts)[0]:
            d[int(i)] = "S"
        return d
    out["donch20_trend"] = mk(up20, dn20)
    out["donch20_fade"] = mk(dn20, up20)
    out["donch55_trend"] = mk(up55, dn55)
    out["bb_break"] = mk(bup, bdn)
    out["bb_rev"] = mk(bdn, bup)
    out["rsi_rev"] = mk(rlo, rhi)
    out["rsi_trend"] = mk(rhi, rlo)
    out["ema20_50_cross"] = mk(cu, cd)
    out["volspike_follow"] = mk(vup, vdn)
    out["volspike_fade"] = mk(vdn, vup)
    for seed in (1, 2, 3):
        rng = np.random.default_rng(seed)
        r1, r2 = rng.random(n), rng.random(n)
        pick = r1 < 0.02
        out["random%d" % seed] = mk(pick & (r2 < 0.5), pick & (r2 >= 0.5))
    out["builtin_cross200"] = None
    return out


EXITS = [(0.8, 1.0), (0.8, 2.0), (2.0, 1.0), (2.0, 2.0)]


def mode_b():
    cfgs = [("15m", 120), ("1h", 365), ("4h", 365)]
    allt = []
    for tf, days in cfgs:
        frm = NOW - days * 86400000
        for sym in PAIRS:
            t0 = time.time()
            try:
                df = fetch(sym, tf, days)
                base = dict(cs.PARAMS, tf=tf, sym=sym, entry_mode="cross200", rev_exit=False, pat_mode="off", be_trigger=999.0,
                            be_intrabar=False, trail_mode="none", max_bars=0, tp_mode="r", sim_from_ms=frm, fee=0.05)
                pre = cs.prepare(df, NOW)
                if not pre.get("ok"):
                    continue
                S = sigs_all(pre)
            except Exception as e:
                print("B ОШИБКА", sym, tf, str(e)[:160], flush=True)
                continue
            n0 = len(allt)
            for rule, sg in S.items():
                for stp, rr in EXITS:
                    P = dict(base, stop_mode="pct", min_stop_pct=stp, tp_r=rr)
                    try:
                        res = cs.simulate(df, NOW, P, pre=pre, sigs=sg)
                    except Exception as e:
                        print("B ОШИБКА sim", rule, str(e)[:120], flush=True)
                        break
                    allt += pack(res, sym, tf, frm, {"rule": rule, "ex": "стоп%.1f_цель%gR" % (stp, rr)})
            print("B %s %s: свечей %d, сделок всего +%d, %.0f с" % (sym, tf, len(df), len(allt) - n0, time.time() - t0), flush=True)
        json.dump(allt, open("/tmp/research_B.json", "w"))
    print("\n==== B: ДРУГИЕ ПРАВИЛА ВХОДА (gross до комиссий; t_мес — консервативный t по месяцам)", flush=True)
    for tf, days in cfgs:
        T = [t for t in allt if t["tf"] == tf]
        g = collections.defaultdict(list)
        for t in T:
            g[(t["rule"], t["ex"])].append(t)
        rows = []
        for k, v in g.items():
            s = stats(v)
            if s:
                rows.append((k, s))
        print("---- ТФ %s (%d дней), комбинаций %d" % (tf, days, len(rows)), flush=True)
        mk_ = [s["gross"] for k, s in rows if k[0].startswith("random")]
        if mk_:
            print("случайные входы: gross от %+.3f до %+.3f (среднее %+.3f), макс t_мес %+.1f" % (min(mk_), max(mk_), sum(mk_) / len(mk_), max(s["tm"] for k, s in rows if k[0].startswith("random"))), flush=True)
        rows.sort(key=lambda r: -r[1]["tm"])
        for k, s in rows[:8]:
            print(fmt(k[0] + " " + k[1], s), flush=True)
        print("  ...худшие:", flush=True)
        for k, s in rows[-3:]:
            print(fmt(k[0] + " " + k[1], s), flush=True)
        # по правилам: средний gross по 4 выходам
        agg = collections.defaultdict(list)
        for k, s in rows:
            agg[k[0]].append(s["gross"])
        print("  по правилам (средний gross по 4 вариантам выхода): " + "; ".join("%s %+.3f" % (r, sum(v) / len(v)) for r, v in sorted(agg.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))), flush=True)


if __name__ == "__main__":
    if "A" in MODE:
        mode_a()
    if "B" in MODE:
        mode_b()
    print("ГОТОВО", flush=True)
