"""classic_rules.py — проверка правил пользователя (EMA50 + Stoch RSI 3/3/14/14 + паттерн + объём) на 15m, ZEC (412 суток) + SOL/ETH/XRP/BTC (208 суток).
Сигнальная свеча = свеча свечного паттерна разворота (любой бычий/медвежий из detect_patterns).
ЛОНГ: цена > EMA50 и EMA50 не снижается (5 св.); откат: за последние 6 св. low подходил к EMA50 ближе 0.8 ATR; Stoch RSI: K пересекла D снизу вверх
в зоне <20 (K/D предыдущей свечи <20) за последние 3 св. (до сигнальной включительно); объём сигнальной свечи > среднего 20 (вариант); шорт зеркально (>80).
Общие фильтры (G): EMA50 не плоская (|Δ за 10 св.| ≥ 0.3 ATR), ≤3 пересечений ценой EMA50 за 20 св., сигнальная свеча не импульсная (диапазон < 2.5 ATR).
Вход E1: по открытию следующей свечи; E2: по пробою максимума (мин. для шорта) сигнальной свечи в течение 3 свечей; отмена: закрытие за EMA50 или пробит локальный
минимум/максимум до входа. Стоп: за минимумом 3 свечей (до сигнальной включительно) −0.2 ATR, не ближе 0.5 ATR (=1R). Горизонт 96 св. Консервативно: стоп раньше цели.
Издержки: комиссия 0.10% за круг; вторая колонка — плюс проскальзывание 0.04% на сторону (всего 0.18%). Запуск: python classic_rules.py"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
TF = "15m"; STEP = 900000; HMAX = 96; now = int(time.time() * 1000)


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


def stochrsi(c, rl=14, sl=14, sk=3, sd=3):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / rl, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / rl, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / (dn + 1e-12))
    st = 100 * (rsi - rsi.rolling(sl).min()) / (rsi.rolling(sl).max() - rsi.rolling(sl).min() + 1e-9)
    K = st.rolling(sk).mean(); D = K.rolling(sd).mean()
    return K.values, D.values


DATA = {}
for sym, pg in (("ZECUSDT", 40), ("SOLUSDT", 20), ("ETHUSDT", 20), ("XRPUSDT", 20), ("BTCUSDT", 20)):
    df = load(sym, pg); pre = cs.prepare(df, now); M = pre["M"]
    t0 = int(df.t.iloc[0]) + 450 * STEP
    g0 = cs.stage_signals(pre, dict(cs.PARAMS, tf=TF, stages=[{"t": "pattern", "p": 0, "w": 0, "f": "none"}]))
    K, Dd = stochrsi(df.c); e50 = df.c.ewm(span=50, adjust=False).mean().values
    h, l = pre["h"], pre["l"]; n = len(df); sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for k in range(5, n - 5):
        if h[k] >= h[k - 5:k + 6].max(): sh[k] = True
        if l[k] <= l[k - 5:k + 6].min(): sl[k] = True
    anyL = np.zeros(n, bool); anyS = np.zeros(n, bool)
    for i, (sd_, tr) in g0.items(): (anyL if sd_ == "L" else anyS)[i] = True
    DATA[sym] = dict(df=df, pre=pre, M=M, t0=t0, split=t0 + int((now - t0) * 0.6), g0=g0, K=K, D=Dd, e50=e50, sh=sh, sl=sl, anyL=anyL, anyS=anyS)
    print(sym, n, "свечей", flush=True)


def conds(D, i, L, zone=20):
    """Возвращает словарь выполненных условий на сигнальной свече i."""
    pre = D["pre"]; o, h, l, c, atr, e50, K, Dd = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], D["e50"], D["K"], D["D"]
    sd = 1 if L else -1; a = atr[i]; r = {}
    r["trend"] = (c[i] > e50[i] and e50[i] >= e50[i - 5]) if L else (c[i] < e50[i] and e50[i] <= e50[i - 5])
    near = (l[i - 5:i + 1] - e50[i - 5:i + 1]).min() <= 0.8 * a if L else (e50[i - 5:i + 1] - h[i - 5:i + 1]).min() <= 0.8 * a
    r["pull"] = bool(near)
    st = False
    for j in range(i - 3, i + 1):
        if L and K[j - 1] <= Dd[j - 1] and K[j] > Dd[j] and min(K[j - 1], Dd[j - 1]) < zone: st = True
        if (not L) and K[j - 1] >= Dd[j - 1] and K[j] < Dd[j] and max(K[j - 1], Dd[j - 1]) > 100 - zone: st = True
    r["stoch"] = st
    vavg = pre["vavg"][i]; r["vol"] = bool(vavg == vavg and pre["v"][i] > vavg)
    flat = abs(e50[i] - e50[i - 10]) < 0.3 * a
    sgn = np.sign(c[i - 20:i + 1] - e50[i - 20:i + 1]); cross = int((sgn[1:] != sgn[:-1]).sum())
    r["gen"] = (not flat) and cross <= 3 and (h[i] - l[i]) < 2.5 * a
    return r


def swing_ok(D, i, e, L, R, minrr=1.5):
    pre = D["pre"]; lo = max(0, i - 192)
    if L:
        ks = [k for k in range(lo, i - 4) if D["sh"][k] and pre["h"][k] > e]
        tg = min(pre["h"][k] for k in ks) if ks else None
        return tg is not None and (tg - e) >= minrr * R
    ks = [k for k in range(lo, i - 4) if D["sl"][k] and pre["l"][k] < e]
    tg = max(pre["l"][k] for k in ks) if ks else None
    return tg is not None and (e - tg) >= minrr * R


def sim(D, i, L, entry, ex, rr=False):
    pre = D["pre"]; o, h, l, c, atr, e50, K, Dd = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], D["e50"], D["K"], D["D"]; T = D["M"]
    sg = 1 if L else -1; a = atr[i]
    loc = l[i - 2:i + 1].min() if L else h[i - 2:i + 1].max()
    stop0 = loc - 0.2 * a if L else loc + 0.2 * a
    # вход
    if entry == "E1":
        s = i + 1; e = o[s]
    else:
        s = None; e = None
        for j in range(i + 1, min(i + 4, T - 1)):
            if (L and c[j] < e50[j]) or ((not L) and c[j] > e50[j]): return None  # закрепление за EMA50
            if (L and l[j] < loc) or ((not L) and h[j] > loc): return None  # локальный экстремум пробит до входа
            trig = h[i] if L else l[i]
            if (L and h[j] >= trig) or ((not L) and l[j] <= trig):
                s = j; e = max(o[j], trig) if L else min(o[j], trig); break
        if s is None: return None
    R = max(e - stop0, 0.5 * a) if L else max(stop0 - e, 0.5 * a)
    if R <= 0: return None
    if rr and not swing_ok(D, i, e, L, R): return None
    stop = e - sg * R; kind = ex[0]; target = e + sg * ex[1] * R if kind == "tp" else None
    be = False; best = e; res = None
    opp = D["anyS"] if L else D["anyL"]
    for j in range(s, min(s + HMAX, T - 1)):
        first = (j == s and entry == "E2")
        if not first:
            if (L and o[j] <= stop) or ((not L) and o[j] >= stop): res = sg * (o[j] - e) / R; break
        if (L and l[j] <= stop) or ((not L) and h[j] >= stop): res = sg * (stop - e) / R; break
        if first: continue  # после входа внутри свечи цели/трейл не засчитываем (консервативно)
        if target is not None and ((L and h[j] >= target) or ((not L) and l[j] <= target)): res = sg * (target - e) / R; break
        mv = (h[j] - e) / R if L else (e - l[j]) / R
        if kind == "trail":
            if not be and mv >= 1.0: be = True; stop = e
            if be:
                best = max(best, h[j]) if L else min(best, l[j]); ns = best - sg * 3 * atr[j]; stop = max(stop, ns) if L else min(stop, ns)
        if kind == "counter" and opp[j] and sg * (c[j] - e) / R >= 1.0: res = sg * (o[j + 1] - e) / R; break
        if kind == "stochx":
            if L and K[j - 1] >= Dd[j - 1] and K[j] < Dd[j] and K[j - 1] > 80: res = sg * (o[j + 1] - e) / R; break
            if (not L) and K[j - 1] <= Dd[j - 1] and K[j] > Dd[j] and K[j - 1] < 20: res = sg * (o[j + 1] - e) / R; break
    if res is None:
        jj = min(s + HMAX, T - 1); res = sg * (c[jj] - e) / R
    return res - 0.001 * e / R, res - 0.0018 * e / R, R / e * 100


def build(D, need, zone=20):
    out = {}
    for i, (sd_, tr) in sorted(D["g0"].items()):
        if i < 60 or i + 5 >= D["M"] or D["pre"]["t"][i] < D["t0"]: continue
        L = sd_ == "L"; r = conds(D, i, L, zone)
        if all(r[k] for k in need): out[i] = L
    return out


def run(D, sigs, entry, ex, rr=False, acc=None):
    rows = []
    for i, L in sigs.items():
        x = sim(D, i, L, entry, ex, rr)
        if x is None: continue
        rows.append((int(D["pre"]["t"][i]), x[0], x[1]))
        if acc is not None: acc.append(x[2])
    return rows


def summ(rows, split):
    if len(rows) < 3: return None
    a = np.array([x[1] for x in rows]); b = np.array([x[2] for x in rows]); ts = np.array([x[0] for x in rows])
    return dict(n=len(a), win=(a > 0).mean() * 100, avg=a.mean(), avg2=b.mean(), t=a.mean() / (a.std() / np.sqrt(len(a)) + 1e-9),
                ins=a[ts < split].mean() if (ts < split).any() else float("nan"), nins=int((ts < split).sum()),
                oos=a[ts >= split].mean() if (ts >= split).any() else float("nan"), noos=int((ts >= split).sum()))


# воронка условий
D = DATA["ZECUSDT"]; f = {k: 0 for k in ("pattern", "trend", "+pull", "+stoch", "+vol", "+gen")}; fl = dict(f)
for i, (sd_, tr) in D["g0"].items():
    if i < 60 or i + 5 >= D["M"] or D["pre"]["t"][i] < D["t0"]: continue
    r = conds(D, i, sd_ == "L"); f["pattern"] += 1
    ok = True
    for nm, k in (("trend", "trend"), ("+pull", "pull"), ("+stoch", "stoch"), ("+vol", "vol"), ("+gen", "gen")):
        ok = ok and r[k]
        if ok: f[nm] += 1
print("\nВОРОНКА (ZEC, паттерн-сигналов → после каждого условия по очереди):", f)
HDR = "%-30s %5s %5s %7s %7s %5s %14s %14s | %s" % ("набор / вход / выход", "n", "win%", "avgR", "avgR*", "t", "подбор(n)", "проверка(n)", "SOL ETH XRP BTC avgR(n)")
print("* avgR* — с проскальзыванием (всего издержек 0.18% за круг), остальное — комиссия 0.10%")
SETS = [("R0 тренд+откат+паттерн", ["trend", "pull"], 20), ("R1 +StochRSI зона 20/80", ["trend", "pull", "stoch"], 20), ("R1b +StochRSI зона 30/70", ["trend", "pull", "stoch"], 30),
        ("R2 +объём>ср.20", ["trend", "pull", "stoch", "vol"], 20), ("R3 +общие фильтры", ["trend", "pull", "stoch", "gen"], 20), ("R4 всё вместе", ["trend", "pull", "stoch", "vol", "gen"], 20)]
EXITS = [("цель 2R", ("tp", 2.0)), ("цель 3R", ("tp", 3.0)), ("трейлинг 3ATR после +1R", ("trail",)), ("выход по Stoch RSI", ("stochx",))]
for sname, need, zone in SETS:
    sigs = {s: build(DATA[s], need, zone) for s in DATA}
    for entry in ("E1", "E2"):
        acc = []; run(DATA["ZECUSDT"], sigs["ZECUSDT"], entry, ("tp", 3.0), False, acc)
        nl = sum(1 for v in sigs["ZECUSDT"].values() if v)
        print("\n== %s | вход %s | сигналов ZEC %d (лонг %d / шорт %d), средний стоп %.2f%%" % (sname, "по открытию" if entry == "E1" else "по пробою", len(sigs["ZECUSDT"]), nl, len(sigs["ZECUSDT"]) - nl, np.mean(acc) if acc else float("nan"))); print(HDR, flush=True)
        for xn, ex in EXITS + ([("цель 3R + фильтр R:R≥1.5 по свингу", ("tp", 3.0))] if entry == "E1" else []):
            rr = xn.startswith("цель 3R + фильтр")
            s = summ(run(DATA["ZECUSDT"], sigs["ZECUSDT"], entry, ex, rr), DATA["ZECUSDT"]["split"])
            oth = []
            for sym in ("SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
                so = summ(run(DATA[sym], sigs[sym], entry, ex, rr), DATA[sym]["split"]); oth.append((so["avg"], so["n"]) if so else (float("nan"), 0))
            if not s: print("%-30s n<3" % xn); continue
            print("%-30s %5d %4.0f%% %+7.3f %+7.3f %5.1f %+7.3f(%4d) %+7.3f(%4d) | %+6.3f(%d) %+6.3f(%d) %+6.3f(%d) %+6.3f(%d)" % (
                xn, s["n"], s["win"], s["avg"], s["avg2"], s["t"], s["ins"], s["nins"], s["oos"], s["noos"], *[x for p in oth for x in p]), flush=True)
print("\nГОТОВО", flush=True)
