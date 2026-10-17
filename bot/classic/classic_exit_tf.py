"""classic_exit_tf.py — то же, что classic_exit.py, но для старших ТФ (1h/4h/1d) и полной доступной истории; добавлен BTC. Запуск: python classic_exit_tf.py 1h|4h|1d
(исходное описание:) classic_exit.py — варианты ВЫХОДА для входов «паттерн → закрытие за EMA20» (с фильтром съёма экстремума и без).
Вход по открытию следующей свечи после сигнала; стоп за экстремумом с момента паттерна (−0.1 ATR), не ближе 0.5 ATR (=1R);
комиссия 0.10% за круг (в R); внутри свечи консервативно: стоп раньше цели; перенос в безубыток действует со следующей свечи.
Выходы: фиксированная цель kR; цель + БУ при 1R; частичная фиксация 50% при 1R + остаток до цели; цель = ближайший свинг (фрактал 5/5)
с отсевом потенциала <1.5R; встречный паттерн (любой / только при плюсе ≥1R); трейлинг 3 ATR после +1R.
ZEC 15m основная (подбор 60% / проверка 40%), SOL/ETH/XRP — знак эффекта. Запуск: python classic_exit.py"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
TF = sys.argv[1]; SEC = {"1h": 3600, "4h": 14400, "1d": 86400}[TF]; PAGES = {"1h": 40, "4h": 25, "1d": 8}[TF]
now = int(time.time() * 1000); STEP = SEC * 1000; HMAX = 96; FEE = 0.001; ACC = None


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


TR = {"t": "pattern", "f": "none"}
C20 = {"t": "close_ema20", "w": 12}
DATA = {}
for sym in ("ZECUSDT", "SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
    df = load(sym, PAGES); pre = cs.prepare(df, now)
    t0 = int(df.t.iloc[0]) + 450 * STEP
    g0 = cs.stage_signals(pre, dict(cs.PARAMS, stages=[TR]))
    n = len(df); pL = np.zeros(n, bool); pS = np.zeros(n, bool)
    for i, (sd, tr) in g0.items():
        (pL if sd == "L" else pS)[i] = True
    h, l = pre["h"], pre["l"]
    sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for k in range(5, n - 5):
        if h[k] >= h[k - 5:k + 6].max(): sh[k] = True
        if l[k] <= l[k - 5:k + 6].min(): sl[k] = True
    DATA[sym] = dict(df=df, pre=pre, t0=t0, split=t0 + int((now - t0) * 0.6), pL=pL, pS=pS, sh=sh, sl=sl)
    print(sym, n, "свечей", datetime.datetime.fromtimestamp(df.t.iloc[0] / 1000, datetime.UTC).date(), "оценка с", datetime.datetime.fromtimestamp(t0 / 1000, datetime.UTC).date(), flush=True)


def sweep(N):
    def p(i, tr, side, pre):
        if tr < N + 3: return False
        l, h, c = pre["l"], pre["h"], pre["c"]
        if side == "L":
            prev = l[tr - 3 - N:tr - 2].min(); return l[tr - 2:tr + 1].min() < prev and c[tr] > prev
        prev = h[tr - 3 - N:tr - 2].max(); return h[tr - 2:tr + 1].max() > prev and c[tr] < prev
    return p


def swing_target(D, i, e, L, R):
    pre = D["pre"]; lo = max(0, i - 192)
    if L:
        ks = [k for k in range(lo, i - 4) if D["sh"][k] and pre["h"][k] > e]
        return min(pre["h"][k] for k in ks) if ks else None
    ks = [k for k in range(lo, i - 4) if D["sl"][k] and pre["l"][k] < e]
    return max(pre["l"][k] for k in ks) if ks else None


def sim(D, i, tr, L, ex):
    pre = D["pre"]; o, h, l, c, atr = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"]; T = len(atr)
    e = o[i + 1]; a = atr[i]
    ext = l[tr:i + 1].min() if L else h[tr:i + 1].max()
    stop = ext - 0.1 * a if L else ext + 0.1 * a
    R = max(e - stop, 0.5 * a) if L else max(stop - e, 0.5 * a)
    sg = 1 if L else -1
    stop = e - sg * R
    kind = ex[0]; tgt_r = ex[1] if len(ex) > 1 else None
    target = None
    if kind == "swing":
        st = swing_target(D, i, e, L, R)
        if st is None or abs(st - e) < ex[2] * R: return None
        target = st
    elif tgt_r: target = e + sg * tgt_r * R
    be = False; part = 0.0; rem = 1.0; best = e; res = None
    opp = D["pS"] if L else D["pL"]
    for j in range(i + 1, min(i + 1 + HMAX, T)):
        # стоп (консервативно первым)
        if (L and o[j] <= stop) or ((not L) and o[j] >= stop): res = part + rem * sg * (o[j] - e) / R; break
        if (L and l[j] <= stop) or ((not L) and h[j] >= stop): res = part + rem * sg * (stop - e) / R; break
        # частичная фиксация
        if kind == "partial" and not be:
            lvl = e + sg * R
            if (L and h[j] >= lvl) or ((not L) and l[j] <= lvl):
                part = 0.5 * 1.0; rem = 0.5; be = True; stop = e
        # цель
        if target is not None:
            if (L and h[j] >= target) or ((not L) and l[j] <= target):
                res = part + rem * sg * (target - e) / R; break
        # БУ / трейлинг со следующей свечи
        mv = (h[j] - e) / R if L else (e - l[j]) / R
        if kind in ("be", "trail") and not be and mv >= 1.0: be = True; stop = e
        if kind == "trail" and be:
            best = max(best, h[j]) if L else min(best, l[j])
            ns = best - sg * 3 * atr[j]
            stop = max(stop, ns) if L else min(stop, ns)
        # встречный паттерн
        if kind == "counter" and opp[j] and j + 1 < T:
            if ex[2] == 0 or sg * (c[j] - e) / R >= ex[2]:
                res = part + rem * sg * (o[j + 1] - e) / R; break
    if res is None:
        jj = min(i + HMAX, T - 1); res = part + rem * sg * (c[jj] - e) / R
    if ACC is not None: ACC.append(R / e * 100)
    return res - FEE * e / R


def run(sym, stages, pred, ex):
    D = DATA[sym]; pre = D["pre"]
    g = cs.stage_signals(pre, dict(cs.PARAMS, stages=stages)); T = len(pre["atr"]); rows = []
    for i, (sd, tr) in sorted(g.items()):
        if pre["t"][i] < D["t0"] or i + 1 >= T: continue
        if pred and not pred(i, tr, sd, pre): continue
        r = sim(D, i, tr, sd == "L", ex)
        if r is not None: rows.append((int(pre["t"][i]), r))
    return rows


def summ(rows, split):
    if len(rows) < 3: return None
    r = np.array([x[1] for x in rows]); ts = np.array([x[0] for x in rows]); a, b = r[ts < split], r[ts >= split]
    return dict(n=len(r), win=(r > 0).mean() * 100, avg=r.mean(), t=r.mean() / (r.std() / np.sqrt(len(r)) + 1e-9),
                ins=a.mean() if len(a) else float("nan"), nins=len(a), oos=b.mean() if len(b) else float("nan"), noos=len(b))


EXITS = [("цель 1R", ("tp", 1.0)), ("цель 1.5R", ("tp", 1.5)), ("цель 2R", ("tp", 2.0)), ("цель 3R", ("tp", 3.0)), ("цель 5R", ("tp", 5.0)),
         ("цель 2R + БУ при 1R", ("be", 2.0)), ("цель 3R + БУ при 1R", ("be", 3.0)),
         ("50% при 1R, остаток БУ → 3R", ("partial", 3.0)), ("50% при 1R, остаток БУ → 5R", ("partial", 5.0)),
         ("цель = свинг (любой потенциал)", ("swing", None, 0.0)), ("цель = свинг, отсев <1.5R", ("swing", None, 1.5)),
         ("встречный паттерн + стоп (без цели)", ("counter", None, 0.0)), ("встречный паттерн при плюсе ≥1R", ("counter", None, 1.0)),
         ("цель 3R + встречный при плюсе ≥1R", ("counter", 3.0, 1.0)),
         ("трейлинг 3 ATR после +1R (БУ)", ("trail", None))]
ENTRIES = [("A: паттерн → закр. за EMA20", [TR, C20], None), ("B: + съём 16 св.", [TR, C20], sweep(16)),
           ("C: + съём 48 св.", [TR, C20], sweep(48)), ("D: только паттерн + съём 48", [TR], sweep(48))]
HDR = "%-38s %5s %5s %7s %5s %15s %15s | %s" % ("выход", "n", "win%", "avgR", "t", "подбор avgR(n)", "проверка avgR(n)", "SOL ETH XRP BTC avgR(n)")
for ename, st, pred in ENTRIES:
    ACC = []; run("ZECUSDT", st, pred, ("tp", 3.0)); sa = ACC; ACC = None
    print("\n== [%s] ВХОД %s: средний стоп (1R) %.2f%% цены, комиссия круга = %.3f R" % (TF, ename, np.mean(sa), 0.10 / np.mean(sa))); print(HDR, flush=True)
    for xname, ex in EXITS:
        s = summ(run("ZECUSDT", st, pred, ex), DATA["ZECUSDT"]["split"])
        oth = []
        for sym in ("SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"):
            so = summ(run(sym, st, pred, ex), DATA[sym]["split"]); oth.append((so["avg"], so["n"]) if so else (float("nan"), 0))
        if not s: print("%-38s n<3" % xname); continue
        print("%-38s %5d %4.0f%% %+7.3f %5.1f %+8.3f(%4d) %+8.3f(%4d) | %+6.3f(%d) %+6.3f(%d) %+6.3f(%d) %+6.3f(%d)" % (
            xname, s["n"], s["win"], s["avg"], s["t"], s["ins"], s["nins"], s["oos"], s["noos"], *[x for p in oth for x in p]), flush=True)
print("\nГОТОВО", flush=True)
