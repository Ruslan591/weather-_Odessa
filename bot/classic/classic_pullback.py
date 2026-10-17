"""classic_pullback.py — проверка гипотезы из разметки: вход = паттерн разворота на экстремуме 12 ч → затем возврат к EMA20 (±0.9 ATR),
RSI 40–58, расстояние 2.4–4.5 ATR от экстремума 12 ч; выход — встречное поглощение +2 св., растяжение от EMA20 + RSI, цели, трейлинг.
Плюс: какие доп. индикаторы (MACD, Stoch, ADX, наклон EMA50, объём) улучшают фильтр; и значения индикаторов на метках пользователя.
Схема исхода: вход по открытию следующей свечи, стоп за экстремумом с паттерна (−0.1 ATR) не ближе 0.5 ATR (=1R), комиссия 0.10%, горизонт 24 ч.
Запуск: python classic_pullback.py 15m|5m"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs, classic_analysis as an
TF = sys.argv[1]; MIN = {"5m": 5, "15m": 15}[TF]; STEP = MIN * 60000
N12 = 720 // MIN; HMAX = 1440 // MIN; W = 36; FEE = 0.001
PAGES = {"15m": (40, 20), "5m": (80, 30)}[TF]
now = int(time.time() * 1000)


def load(sym, pages):
    parts, end = [], None
    for _ in range(pages):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (sym, TF) + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
        if len(d) < 1000: break
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


def extras(df):
    h, l, c = df.h, df.l, df.c
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0); minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(plus).ewm(alpha=1 / 14, adjust=False).mean() / a; mdi = 100 * pd.Series(minus).ewm(alpha=1 / 14, adjust=False).mean() / a
    adx = (100 * (pdi - mdi).abs() / (pdi + mdi + 1e-9)).ewm(alpha=1 / 14, adjust=False).mean()
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    stoch = 100 * (c - ll) / (hh - ll + 1e-9)
    e50 = c.ewm(span=50, adjust=False).mean()
    return dict(adx=adx.values, stoch=stoch.values, e50=e50.values)


DATA = {}
syms = (("ZECUSDT", PAGES[0]), ("SOLUSDT", PAGES[1]), ("ETHUSDT", PAGES[1]), ("XRPUSDT", PAGES[1]), ("BTCUSDT", PAGES[1]))
for sym, pg in syms:
    df = load(sym, pg); pre = cs.prepare(df, now); M = pre["M"]
    t0 = int(df.t.iloc[0]) + 450 * STEP
    g0 = cs.stage_signals(pre, dict(cs.PARAMS, stages=[{"t": "pattern", "f": "none"}]))
    closed = df.iloc[:M].reset_index(drop=True); ind = an.indicators(closed); pats = an.detect_patterns(closed, ind)
    n = len(df); anyL = np.zeros(n, bool); anyS = np.zeros(n, bool); engB = np.zeros(n, bool); engS = np.zeros(n, bool)
    for i, (sd, tr) in g0.items(): (anyL if sd == "L" else anyS)[i] = True
    for p in pats:
        if p["k"] == "bull_eng": engB[p["i"]] = True
        if p["k"] == "bear_eng": engS[p["i"]] = True
    ex = extras(df)
    DATA[sym] = dict(df=df, pre=pre, M=M, t0=t0, split=t0 + int((now - t0) * 0.6), g0=g0, anyL=anyL, anyS=anyS, engB=engB, engS=engS, **ex)
    print(sym, n, "свечей", datetime.datetime.fromtimestamp(df.t.iloc[0] / 1000, datetime.UTC).date(), flush=True)


def pb_signals(D, zone=True, rsi=None, dist=None, extra=None):
    pre = D["pre"]; M = D["M"]; o, h, l, c, atr, e20, rs = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], pre["e20"], pre["rsi"]
    out = {}
    for tr, (sd, _) in sorted(D["g0"].items()):
        L = sd == "L"
        if tr < N12 + 5: continue
        for i in range(tr, min(tr + W, M - 2) + 1):
            if L and i > tr and c[i] < l[tr]: break
            if (not L) and i > tr and c[i] > h[tr]: break
            a = atr[i]
            ex_ = l[i - N12:i + 1].min() if L else h[i - N12:i + 1].max()
            if L and l[tr] > ex_ + 0.5 * a: break
            if (not L) and h[tr] < ex_ - 0.5 * a: break
            if zone and abs(c[i] - e20[i]) > 0.9 * a: continue
            if rsi and not (rsi[0] <= rs[i] <= rsi[1]): continue
            d = ((c[i] - ex_) if L else (ex_ - c[i])) / a
            if dist and not (dist[0] <= d <= dist[1]): continue
            if extra and not extra(D, i, L): continue
            out[i] = (sd, tr); break
    return out


def sim(D, i, tr, L, ex):
    pre = D["pre"]; o, h, l, c, atr, e20, rs = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], pre["e20"], pre["rsi"]; T = D["M"]
    e = o[i + 1]; a = atr[i]
    ext = l[tr:i + 1].min() if L else h[tr:i + 1].max()
    stop = ext - 0.1 * a if L else ext + 0.1 * a
    R = max(e - stop, 0.5 * a) if L else max(stop - e, 0.5 * a); sg = 1 if L else -1; stop = e - sg * R
    kind = ex[0]; target = e + sg * ex[1] * R if kind == "tp" else None
    opp = D["anyS"] if L else D["anyL"]; eng = D["engS"] if L else D["engB"]
    be = False; best = e; res = None
    for j in range(i + 1, min(i + 1 + HMAX, T - 1)):
        if (L and o[j] <= stop) or ((not L) and o[j] >= stop): res = sg * (o[j] - e) / R; break
        if (L and l[j] <= stop) or ((not L) and h[j] >= stop): res = sg * (stop - e) / R; break
        if target is not None and ((L and h[j] >= target) or ((not L) and l[j] <= target)): res = sg * (target - e) / R; break
        mv = (h[j] - e) / R if L else (e - l[j]) / R
        if kind == "trail":
            if not be and mv >= 1.0: be = True; stop = e
            if be:
                best = max(best, h[j]) if L else min(best, l[j]); ns = best - sg * 3 * atr[j]; stop = max(stop, ns) if L else min(stop, ns)
        if kind == "counter" and opp[j] and sg * (c[j] - e) / R >= 1.0: res = sg * (o[j + 1] - e) / R; break
        if kind == "engulf2" and j - 2 > i and eng[j - 2]: res = sg * (o[j + 1] - e) / R; break
        if kind == "stretch" and sg * (c[j] - e20[j]) >= 1.2 * atr[j] and ((rs[j] >= 65) if L else (rs[j] <= 35)): res = sg * (o[j + 1] - e) / R; break
    if res is None:
        jj = min(i + HMAX, T - 1); res = sg * (c[jj] - e) / R
    return res - FEE * e / R, R / e * 100


def run(sym, sigs, ex, accum=None):
    D = DATA[sym]; pre = D["pre"]; rows = []
    for i, (sd, tr) in sorted(sigs.items()):
        if pre["t"][i] < D["t0"] or i + 2 >= D["M"]: continue
        r, rp = sim(D, i, tr, sd == "L", ex); rows.append((int(pre["t"][i]), r))
        if accum is not None: accum.append(rp)
    return rows


def summ(rows, split):
    if len(rows) < 3: return None
    r = np.array([x[1] for x in rows]); ts = np.array([x[0] for x in rows]); a, b = r[ts < split], r[ts >= split]
    return dict(n=len(r), win=(r > 0).mean() * 100, avg=r.mean(), t=r.mean() / (r.std() / np.sqrt(len(r)) + 1e-9),
                ins=a.mean() if len(a) else float("nan"), nins=len(a), oos=b.mean() if len(b) else float("nan"), noos=len(b))


EXITS = [("цель 2R", ("tp", 2.0)), ("цель 3R", ("tp", 3.0)), ("цель 5R", ("tp", 5.0)), ("трейлинг 3 ATR после +1R", ("trail",)),
         ("встречный паттерн при плюсе ≥1R", ("counter",)), ("встречное поглощение +2 св.", ("engulf2",)), ("растяжение 1.2 ATR + RSI 65/35", ("stretch",))]
HDR = "%-34s %5s %5s %7s %5s %15s %15s | %s" % ("выход", "n", "win%", "avgR", "t", "подбор avgR(n)", "проверка avgR(n)", "SOL ETH XRP BTC avgR(n)")


def table(name, builder, exits):
    sigs = {s: builder(DATA[s]) for s in DATA}
    acc = []; run("ZECUSDT", sigs["ZECUSDT"], ("tp", 3.0), acc)
    print("\n== [%s] %s: сигналов ZEC %d, средний стоп %.2f%% цены" % (TF, name, len(sigs["ZECUSDT"]), np.mean(acc) if acc else float("nan"))); print(HDR, flush=True)
    for xn, ex in exits:
        s = summ(run("ZECUSDT", sigs["ZECUSDT"], ex), DATA["ZECUSDT"]["split"])
        oth = []
        for sym in ("SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
            so = summ(run(sym, sigs[sym], ex), DATA[sym]["split"]); oth.append((so["avg"], so["n"]) if so else (float("nan"), 0))
        if not s: print("%-34s n<3" % xn); continue
        print("%-34s %5d %4.0f%% %+7.3f %5.1f %+8.3f(%4d) %+8.3f(%4d) | %+6.3f(%d) %+6.3f(%d) %+6.3f(%d) %+6.3f(%d)" % (
            xn, s["n"], s["win"], s["avg"], s["t"], s["ins"], s["nins"], s["oos"], s["noos"], *[x for p in oth for x in p]), flush=True)


def chainA(D):
    return cs.stage_signals(D["pre"], dict(cs.PARAMS, stages=[{"t": "pattern", "f": "none"}, {"t": "close_ema20", "w": 12}]))


RSI = (40, 58); DIST = (2.4, 4.5)
table("0. база: паттерн → закрытие за EMA20", chainA, EXITS)
table("1. паттерн на экстремуме 12 ч → возврат к EMA20 ±0.9 ATR", lambda D: pb_signals(D), EXITS)
table("2. то же + RSI 40–58", lambda D: pb_signals(D, rsi=RSI), EXITS)
table("3. то же + расстояние 2.4–4.5 ATR от экстремума (полная гипотеза)", lambda D: pb_signals(D, rsi=RSI, dist=DIST), EXITS)
print("\n######## ДОП. ИНДИКАТОРЫ поверх фильтра 2 (паттерн + возврат к EMA20 + RSI 40–58)")
EXX = [("цель 3R", ("tp", 3.0)), ("встречное поглощение +2 св.", ("engulf2",))]
def macd_turn(D, i, L): hh = D["pre"]["hist"]; return hh[i] > hh[i - 1] if L else hh[i] < hh[i - 1]
def stoch_turn(D, i, L): k = D["stoch"]; return (k[i] > k[i - 1] and k[i - 1] < 50) if L else (k[i] < k[i - 1] and k[i - 1] > 50)
def adx_ge(x): return lambda D, i, L: D["adx"][i] >= x
def adx_lt(x): return lambda D, i, L: D["adx"][i] < x
def e50_slope(D, i, L): e = D["e50"]; return e[i] > e[i - 5] if L else e[i] < e[i - 5]
def vol12(D, i, L): return D["df"].v.values[i] >= 1.2 * D["pre"]["vavg"][i]
def vol_lt(D, i, L): return D["df"].v.values[i] < D["pre"]["vavg"][i]
for nm, fn in (("MACD-гистограмма развернулась в сторону", macd_turn), ("StochK(14) развернулся из <50 / >50", stoch_turn), ("ADX ≥ 20", adx_ge(20)), ("ADX < 20", adx_lt(20)),
               ("наклон EMA50 в сторону (5 св.)", e50_slope), ("объём ≥1.2× среднего", vol12), ("объём ниже среднего", vol_lt)):
    table("2 + " + nm, lambda D, fn=fn: pb_signals(D, rsi=RSI, extra=fn), EXX)
print("\n######## ИНДИКАТОРЫ НА МЕТКАХ ПОЛЬЗОВАТЕЛЯ (ZEC %s)" % TF)
D = DATA["ZECUSDT"]; pre = D["pre"]; idx = {int(x): k for k, x in enumerate(pre["t"])}
labs = sorted([x for x in json.load(open("/opt/trading-bot/classic/labels.json")) if x["sym"] == "ZECUSDT" and x["tf"] == TF], key=lambda x: x["t"])
for x in labs:
    i = idx.get(x["t"]); 
    if i is None or i >= D["M"]: continue
    print("%s %s: ADX %.0f | StochK %.0f (пред. %.0f) | MACD-гист %+.3f (пред. %+.3f) | EMA50 наклон 5 св. %+.2f ATR | объём %.2f×" % (
        {"L": "вход ЛОНГ", "S": "вход ШОРТ", "X": "выход"}[x["kind"]], datetime.datetime.fromtimestamp(x["t"] / 1000 + 10800, datetime.UTC).strftime("%d.%m %H:%M"),
        D["adx"][i], D["stoch"][i], D["stoch"][i - 1], pre["hist"][i], pre["hist"][i - 1], (D["e50"][i] - D["e50"][i - 5]) / pre["atr"][i], D["df"].v.values[i] / pre["vavg"][i]))
print("\nГОТОВО", flush=True)
