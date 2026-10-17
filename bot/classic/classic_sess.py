"""classic_sess.py — проверка идей из статьи: (1) паттерн со съёмом ликвидности (ложный пробой экстремума N свечей и возврат),
(2) время сессии (UTC). Схема исхода та же, что в classic_trend_start.py: вход по открытию следующей свечи, стоп за экстремумом
с момента паттерна (−0.1 ATR), не ближе 0.5 ATR (1R), цель +3R, лимит 96 свечей, комиссия 0.10% за круг. Метрика — avgR после комиссий.
ZEC 15m основная (подбор 60% / проверка 40%); SOL/ETH/XRP — только знак эффекта.
Запуск: python classic_sess.py"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
now = int(time.time() * 1000); STEP = 900 * 1000; H = 96


def load(sym, pages):
    parts, end = [], None
    for _ in range(pages):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=15m&limit=1000" % sym + ("&endTime=%d" % end if end else "")
        d = json.load(urllib.request.urlopen(u, timeout=20))
        if not d: break
        parts.insert(0, d); end = int(d[0][0]) - 1
        if len(d) < 1000: break
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for k in "ohlcv": df[k] = df[k].astype(float)
    df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True)


DATA = {}
for sym, pg in (("ZECUSDT", 40), ("SOLUSDT", 20), ("ETHUSDT", 20), ("XRPUSDT", 20)):
    df = load(sym, pg); pre = cs.prepare(df, now)
    t0 = int(df.t.iloc[0]) + 450 * STEP
    DATA[sym] = (df, pre, t0, t0 + int((now - t0) * 0.6))
    print(sym, len(df), "свечей; оценка с", datetime.datetime.fromtimestamp(t0 / 1000, datetime.UTC).date(), flush=True)

TR = {"t": "pattern", "f": "none"}
C20 = {"t": "close_ema20", "w": 12}


def hour(pre, i): return int(pre["t"][i] // 3600000) % 24


def sweep(N):
    def p(i, tr, side, pre):
        if tr < N + 3: return False
        l, h, c = pre["l"], pre["h"], pre["c"]
        if side == "L":
            prev = l[tr - 3 - N:tr - 2].min()
            return l[tr - 2:tr + 1].min() < prev and c[tr] > prev
        prev = h[tr - 3 - N:tr - 2].max()
        return h[tr - 2:tr + 1].max() > prev and c[tr] < prev
    return p


def nosweep(N):
    s = sweep(N)
    return lambda i, tr, side, pre: not s(i, tr, side, pre)


def hrs(a, b): return lambda i, tr, side, pre: a <= hour(pre, i) < b
def not_hrs(a, b): return lambda i, tr, side, pre: not (a <= hour(pre, i) < b)
def AND(*ps): return lambda i, tr, side, pre: all(p(i, tr, side, pre) for p in ps)
def first3(i, tr, side, pre): h = hour(pre, i); return 7 <= h < 10 or 13 <= h < 16


def evaluate(sym, stages, pred=None):
    df, pre, t0, split = DATA[sym]
    g = cs.stage_signals(pre, dict(cs.PARAMS, stages=stages))
    T = len(df); o, h, l, c, atr, t = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], pre["t"]
    rows = []
    for i, (side, tr) in sorted(g.items()):
        if t[i] < t0 or i + 1 >= T: continue
        if pred and not pred(i, tr, side, pre): continue
        L = side == "L"
        e = o[i + 1]; a = atr[i]
        ext = l[tr:i + 1].min() if L else h[tr:i + 1].max()
        stop = ext - 0.1 * a if L else ext + 0.1 * a
        R = max(e - stop, 0.5 * a) if L else max(stop - e, 0.5 * a)
        stop = e - R if L else e + R
        res = None
        for j in range(i + 1, min(i + 1 + H, T)):
            if L:
                if o[j] <= stop: res = (o[j] - e) / R; break
                if l[j] <= stop: res = -1.0; break
                if h[j] >= e + 3 * R: res = 3.0; break
            else:
                if o[j] >= stop: res = (e - o[j]) / R; break
                if h[j] >= stop: res = -1.0; break
                if l[j] <= e - 3 * R: res = 3.0; break
        if res is None:
            jj = min(i + H, T - 1); res = ((c[jj] - e) if L else (e - c[jj])) / R
        rows.append((int(t[i]), res - 0.001 * e / R))
    return rows


def summ(rows, split):
    if len(rows) < 3: return None
    r = np.array([x[1] for x in rows]); ts = np.array([x[0] for x in rows])
    ins, oos = r[ts < split], r[ts >= split]
    return dict(n=len(r), win=(r > 0).mean() * 100, avg=r.mean(), t=r.mean() / (r.std() / np.sqrt(len(r)) + 1e-9),
                ins=ins.mean() if len(ins) else float("nan"), nins=len(ins), oos=oos.mean() if len(oos) else float("nan"), noos=len(oos))


def show(name, st, pred):
    s = summ(evaluate("ZECUSDT", st, pred), DATA["ZECUSDT"][3])
    oth = []
    for sym in ("SOLUSDT", "ETHUSDT", "XRPUSDT"):
        so = summ(evaluate(sym, st, pred), DATA[sym][3]); oth.append((so["avg"], so["n"]) if so else (float("nan"), 0))
    if not s: print("%-44s n<3" % name); return
    print("%-44s %5d %4.0f%% %+7.3f %5.1f %+8.3f(%4d) %+8.3f(%4d) | %+6.3f(%d) %+6.3f(%d) %+6.3f(%d)" % (
        name, s["n"], s["win"], s["avg"], s["t"], s["ins"], s["nins"], s["oos"], s["noos"], *[x for p in oth for x in p]), flush=True)


HDR = "%-44s %5s %5s %7s %5s %15s %15s | %s" % ("набор", "n", "win%", "avgR", "t", "подбор avgR(n)", "проверка avgR(n)", "SOL ETH XRP avgR(n)")
print("\n== 1. ЛОВУШКА ЛИКВИДНОСТИ: паттерн снял экстремум N свечей и закрылся обратно (UTC)"); print(HDR)
show("паттерн (база)", [TR], None)
for N in (16, 48, 96):
    show("паттерн + съём экстремума %d св. (%d ч)" % (N, N // 4), [TR], sweep(N))
    show("паттерн БЕЗ съёма %d св." % N, [TR], nosweep(N))
print("-- с подтверждением закрытия за EMA20")
show("паттерн → закр. за EMA20 (база)", [TR, C20], None)
for N in (16, 48, 96):
    show("паттерн+съём %d св. → закр. за EMA20" % N, [TR, C20], sweep(N))

print("\n== 2. ВРЕМЯ СЕССИИ (UTC; время сигнала = закрытие свечи подтверждения). Лондон 07-13, Нью-Йорк 13-21, Азия 00-07"); print(HDR)
for a in range(0, 24, 3):
    show("база: час UTC %02d-%02d" % (a, a + 3), [TR], hrs(a, a + 3))
show("база: Азия 00-07", [TR], hrs(0, 7)); show("база: Лондон 07-13", [TR], hrs(7, 13))
show("база: Нью-Йорк 13-21", [TR], hrs(13, 21)); show("база: поздно 21-24", [TR], hrs(21, 24))
show("база: первые 3 ч Лондона/НЙ", [TR], first3); show("база: без Азии", [TR], not_hrs(0, 7))
print("-- цепочка паттерн → закрытие за EMA20")
show("цепочка: Азия 00-07", [TR, C20], hrs(0, 7)); show("цепочка: Лондон 07-13", [TR, C20], hrs(7, 13))
show("цепочка: Нью-Йорк 13-21", [TR, C20], hrs(13, 21)); show("цепочка: поздно 21-24", [TR, C20], hrs(21, 24))
show("цепочка: первые 3 ч Лондона/НЙ", [TR, C20], first3); show("цепочка: без Азии", [TR, C20], not_hrs(0, 7))
print("\n== 3. СОЧЕТАНИЕ: съём экстремума + сессия")
for N in (16, 48):
    show("съём %d + без Азии" % N, [TR], AND(sweep(N), not_hrs(0, 7)))
    show("съём %d + первые 3 ч Лондона/НЙ" % N, [TR], AND(sweep(N), first3))
    show("съём %d → закр. EMA20 + без Азии" % N, [TR, C20], AND(sweep(N), not_hrs(0, 7)))
print("\nГОТОВО", flush=True)
