"""classic_entry.py — разбор входов по признакам сигнала и проверка фильтров (1h, ~13 месяцев, выход: конфиг C).
Признаки на закрытой свече пересечения: наклон EMA200 (в ATR/свечу, по направлению сделки), ADX14, объём к среднему за 20,
ATR%, согласие с трендом 4h и 1d (счёт −2..+2: цена vs EMA200 и EMA50 vs EMA200, по направлению сделки)."""
import json, os, sys, time, pickle, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
import classic_analysis as an

pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "ZECUSDT"]
CACHE = "/tmp/cl_entry_cache.pkl"
now = int(time.time() * 1000)


def fetch(sym, tf, pages):
    parts, end = [], None
    for _ in range(pages):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (sym, tf) + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 3000:
    RAW = pickle.load(open(CACHE, "rb"))
else:
    RAW = {s: (fetch(s, "1h", 10), fetch(s, "4h", 4), fetch(s, "1d", 2)) for s in pairs}
    pickle.dump(RAW, open(CACHE, "wb"))


def closed_only(df):
    return df.iloc[:-1] if df.ct.iloc[-1] > now else df


def htf_score(dfh, ct1h):
    d = closed_only(dfh).reset_index(drop=True)
    e50, e200 = an.ema(d.c, 50).values, an.ema(d.c, 200).values
    sc = (np.where(d.c.values > e200, 1, -1) + np.where(e50 > e200, 1, -1)).astype(float)
    idx = np.searchsorted(d.ct.values, ct1h, side="right") - 1
    out = np.where(idx >= 0, sc[np.clip(idx, 0, None)], 0.0)
    return out


def adx_calc(df, n=14):
    h, l, c = df.h, df.l, df.c
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0); minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().fillna(0).values


D = {}
for s in pairs:
    d1, d4, dd = RAW[s]
    pre = cs.prepare(d1, now)
    M = pre["M"]
    cl = d1.iloc[:M].reset_index(drop=True)
    e200, atr = pre["e200"], pre["atr"]
    k = np.arange(M)
    km = np.clip(k - 20, 0, None)
    slope = (e200 - e200[km]) / (20 * atr)
    v = cl.v.values
    volr = np.array([v[i] / max(v[max(0, i - 20):i].mean(), 1e-12) if i > 0 else 1.0 for i in range(M)])
    D[s] = dict(df=d1, pre=pre, slope=slope, adx=adx_calc(cl), volr=volr, atrp=atr / cl.c.values * 100,
                sc4=htf_score(d4, cl.ct.values), sc1=htf_score(dd, cl.ct.values))

START = max(RAW[s][0].t.iloc[0] for s in pairs) + 450 * 3600 * 1000
MID = (START + now) // 2
print("1h с", datetime.datetime.fromtimestamp(START / 1000, datetime.UTC).date(), "по", datetime.datetime.fromtimestamp(now / 1000, datetime.UTC).date())
CFG = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, be_trigger=1.5, trail_mode="atr", trail_dist=4.0)
sg = lambda side: 1 if side == "L" else -1


def run(cond=None):
    T = []
    for s, d in D.items():
        filt = None
        if cond is not None:
            filt = (lambda side, i, d=d: cond(d, side, i))
        for x in cs.simulate(d["df"], now, CFG, d["pre"], filt):
            if x["t_in"] >= START:
                x["sym"] = s; x["s"] = x["i_in"] - 1; T.append(x)
    return T


def feat(T, name):
    out = []
    for x in T:
        d, i, sd = D[x["sym"]], x["s"], sg(x["side"])
        out.append({"slope": d["slope"][i] * sd, "adx": d["adx"][i], "volr": d["volr"][i], "atrp": d["atrp"][i],
                    "sc4": d["sc4"][i] * sd, "sc1": d["sc1"][i] * sd}[name])
    return np.array(out)


def line(lab, T):
    n = len(T)
    if not n: print("  %-34s n=0" % lab); return
    net = sum(x["net"] for x in T); top5 = sum(sorted((x["net"] for x in T), reverse=True)[:5])
    mm = {}
    for x in T:
        m = datetime.datetime.fromtimestamp(x["t_in"] / 1000, datetime.UTC).strftime("%Y-%m"); mm[m] = mm.get(m, 0) + x["net"]
    h1 = sum(x["net"] for x in T if x["t_in"] < MID); h2 = net - h1
    print("  %-34s n=%4d net=%+7.1f avg=%+.2f win=%2.0f%% без5лучших=%+7.1f мес+=%2d/%-2d  1пол=%+6.1f 2пол=%+6.1f" % (
        lab, n, net, net / n, sum(x["net"] > 0 for x in T) / n * 100, net - top5, sum(v > 0 for v in mm.values()), len(mm), h1, h2))


def main():
    base = run()
    print("\n=== БАЗА (конфиг C без фильтра входа)")
    line("все сделки", base)
    nets = np.array([x["net"] for x in base])
    print("\n=== РАЗБОР ПО ПРИЗНАКАМ (по направлению сделки; каждая корзина — сделки базы)")
    for name, qs in [("slope", 4), ("adx", 4), ("volr", 4), ("atrp", 4)]:
        f = feat(base, name); edges = np.quantile(f, np.linspace(0, 1, qs + 1))
        print("-- %s (квартили: %s)" % (name, ", ".join("%.2f" % e for e in edges)))
        for q in range(qs):
            m = (f >= edges[q]) & ((f <= edges[q + 1]) if q == qs - 1 else (f < edges[q + 1]))
            sub = [x for x, ok in zip(base, m) if ok]; line("Q%d [%.2f..%.2f]" % (q + 1, edges[q], edges[q + 1]), sub)
    for name in ("sc4", "sc1"):
        f = feat(base, name); print("-- %s (согласие с трендом %s: +2 по тренду, −2 против)" % (name, "4h" if name == "sc4" else "1d"))
        for v in (-2, 0, 2):
            sub = [x for x, a in zip(base, f) if a == v]; line("%+d" % v, sub)

    F = {
        "4h по тренду (=+2)": lambda d, side, i: d["sc4"][i] * sg(side) == 2,
        "4h не против (>=0)": lambda d, side, i: d["sc4"][i] * sg(side) >= 0,
        "1d по тренду (=+2)": lambda d, side, i: d["sc1"][i] * sg(side) == 2,
        "1d не против (>=0)": lambda d, side, i: d["sc1"][i] * sg(side) >= 0,
        "4h=+2 и 1d>=0": lambda d, side, i: d["sc4"][i] * sg(side) == 2 and d["sc1"][i] * sg(side) >= 0,
        "slope>=0": lambda d, side, i: d["slope"][i] * sg(side) >= 0,
        "slope>=0.02": lambda d, side, i: d["slope"][i] * sg(side) >= 0.02,
        "slope>=0.05": lambda d, side, i: d["slope"][i] * sg(side) >= 0.05,
        "ADX>=15": lambda d, side, i: d["adx"][i] >= 15,
        "ADX>=20": lambda d, side, i: d["adx"][i] >= 20,
        "ADX>=25": lambda d, side, i: d["adx"][i] >= 25,
        "объём>=1.0": lambda d, side, i: d["volr"][i] >= 1.0,
        "объём>=1.5": lambda d, side, i: d["volr"][i] >= 1.5,
        "4h>=0 и ADX>=20": lambda d, side, i: d["sc4"][i] * sg(side) >= 0 and d["adx"][i] >= 20,
        "1d>=0 и ADX>=20": lambda d, side, i: d["sc1"][i] * sg(side) >= 0 and d["adx"][i] >= 20,
        "4h>=0, slope>=0.02": lambda d, side, i: d["sc4"][i] * sg(side) >= 0 and d["slope"][i] * sg(side) >= 0.02,
        "4h=+2, ADX>=20": lambda d, side, i: d["sc4"][i] * sg(side) == 2 and d["adx"][i] >= 20,
    }
    print("\n=== ФИЛЬТРЫ ВХОДА (полная симуляция с выходом C; сигнал против позиции по-прежнему закрывает её)")
    line("без фильтра", base)
    for lab, c in F.items():
        line(lab, run(c))


if __name__ == "__main__":
    main()
