"""classic_trend_start.py — исследование «симптомов начала нового тренда»: какие подтверждения паттерна разворота ловят начало тренда
раньше и точнее. Исход сигнала считается единой простой схемой, не зависящей от остальных правил бота:
вход по открытию следующей свечи; стоп за экстремумом с момента паттерна (−0.1 ATR), но не ближе 0.5 ATR (это 1R); цель +3R; лимит 96 свечей;
комиссия 0.10% за круг (в долях R). Метрики: avgR (после комиссий), win%, лаг подтверждения (свечей от паттерна), отдаление входа от экстремума (ATR).
Запуск: python classic_trend_start.py   (ZEC 15m — основная пара; SOL/ETH/XRP — только проверка, совпадает ли знак эффекта)"""
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
def T_(f): return {"t": "pattern", "f": f}
C20 = {"t": "close_ema20", "w": 12}
SETS = [
    ("паттерн (без подтверждения)", [TR]),
    ("+ закрытие за EMA20", [TR, C20]),
    ("+ закрытие за экстремумом свечи-паттерна", [TR, {"t": "break_trigger", "w": 6}]),
    ("+ разворот наклона EMA20 (3 св.)", [TR, {"t": "ema20_slope", "p": 3, "w": 12}]),
    ("+ RSI вернулся ≥45 (≤55 для шорта)", [TR, {"t": "rsi_level", "p": 45, "w": 12}]),
    ("+ RSI ≥50", [TR, {"t": "rsi_level", "p": 50, "w": 12}]),
    ("+ гистограмма MACD растёт 2 св.", [TR, {"t": "macd_turn", "w": 12}]),
    ("+ объём свечи ≥1.2× среднего", [TR, {"t": "volume", "p": 1.2, "w": 12}]),
    ("+ сильное тело ≥0.8 ATR", [TR, {"t": "strong_body", "p": 0.8, "w": 12}]),
    ("+ слом структуры (за pivot)", [TR, {"t": "break_swing", "w": 12}]),
    ("закр. за EMA20 → за экстремумом паттерна", [TR, C20, {"t": "break_trigger", "w": 6}]),
    ("закр. за EMA20 → наклон EMA20", [TR, C20, {"t": "ema20_slope", "p": 3, "w": 6}]),
    ("закр. за EMA20 → RSI ≥45", [TR, C20, {"t": "rsi_level", "p": 45, "w": 6}]),
    ("закр. за EMA20 → MACD растёт", [TR, C20, {"t": "macd_turn", "w": 6}]),
    ("закр. за EMA20 → объём ≥1.2×", [TR, C20, {"t": "volume", "p": 1.2, "w": 6}]),
    ("закр. за EMA20 → сильное тело", [TR, C20, {"t": "strong_body", "p": 0.8, "w": 6}]),
    ("закр. за EMA20 → слом структуры", [TR, C20, {"t": "break_swing", "w": 6}]),
    ("паттерн у уровня → закр. за EMA20", [T_("level"), C20]),
    ("паттерн с объёмом → закр. за EMA20", [T_("volume"), C20]),
    ("паттерн на экстремуме 12 ч → закр. за EMA20", [T_("extreme"), C20]),
    ("паттерн после растяжения от EMA20 → закр.", [T_("stretch"), C20]),
]


def evaluate(sym, stages):
    df, pre, t0, split = DATA[sym]
    g = cs.stage_signals(pre, dict(cs.PARAMS, stages=stages))
    T = len(df); o, h, l, c, atr, t = pre["o"], pre["h"], pre["l"], pre["c"], pre["atr"], pre["t"]
    rows = []
    for i, (side, tr) in sorted(g.items()):
        if t[i] < t0 or i + 1 >= T: continue
        L = side == "L"
        e = o[i + 1]; a = atr[i]
        ext = l[tr:i + 1].min() if L else h[tr:i + 1].max()
        stop = ext - 0.1 * a if L else ext + 0.1 * a
        R = max(e - stop, 0.5 * a) if L else max(stop - e, 0.5 * a)
        stop = e - R if L else e + R
        mfe, res = 0.0, None
        for j in range(i + 1, min(i + 1 + H, T)):
            if L:
                if o[j] <= stop: res = (o[j] - e) / R; break
                if l[j] <= stop: res = -1.0; break
                if h[j] >= e + 3 * R: res = 3.0; break
                mfe = max(mfe, (h[j] - e) / R)
            else:
                if o[j] >= stop: res = (e - o[j]) / R; break
                if h[j] >= stop: res = -1.0; break
                if l[j] <= e - 3 * R: res = 3.0; break
                mfe = max(mfe, (e - l[j]) / R)
        if res is None:
            jj = min(i + H, T - 1); res = ((c[jj] - e) if L else (e - c[jj])) / R
        net = res - 0.001 * e / R
        late = ((e - ext) if L else (ext - e)) / a
        rows.append((int(t[i]), net, res >= 3.0, i - tr, late, mfe))
    return rows


def summ(rows, split):
    if not rows: return None
    r = np.array([x[1] for x in rows]); ts = np.array([x[0] for x in rows])
    ins, oos = r[ts < split], r[ts >= split]
    return dict(n=len(r), win=(r > 0).mean() * 100, avg=r.mean(), t=r.mean() / (r.std() / np.sqrt(len(r)) + 1e-9), tp=np.mean([x[2] for x in rows]) * 100,
                lag=np.mean([x[3] for x in rows]), late=np.mean([x[4] for x in rows]), mfe=np.mean([x[5] for x in rows]),
                ins=ins.mean() if len(ins) else float("nan"), nins=len(ins), oos=oos.mean() if len(oos) else float("nan"), noos=len(oos))


print("\n== ZEC 15m: исход сигналов (стоп за экстремумом ≥0.5 ATR, цель +3R, 96 свечей, комиссия 0.10%)")
print("%-46s %5s %5s %7s %5s %5s %5s %6s %7s %15s %15s | %7s %7s %7s" % ("набор уровней фильтра", "n", "win%", "avgR", "t", "цель%", "лаг", "дальше", "MFE_R", "подбор avgR(n)", "проверка avgR(n)", "SOL", "ETH", "XRP"))
res = {}
for name, st in SETS:
    s = summ(evaluate("ZECUSDT", st), DATA["ZECUSDT"][3])
    oth = []
    for sym in ("SOLUSDT", "ETHUSDT", "XRPUSDT"):
        so = summ(evaluate(sym, st), DATA[sym][3]); oth.append(so["avg"] if so else float("nan"))
    res[name] = (s, oth)
    if not s: print("%-46s n=0" % name); continue
    print("%-46s %5d %4.0f%% %+7.3f %5.1f %4.0f%% %5.1f %6.2f %7.2f %+8.3f(%4d) %+8.3f(%4d) | %+7.3f %+7.3f %+7.3f" % (
        name, s["n"], s["win"], s["avg"], s["t"], s["tp"], s["lag"], s["late"], s["mfe"], s["ins"], s["nins"], s["oos"], s["noos"], *oth), flush=True)
df, pre, t0, split = DATA["ZECUSDT"]
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
lo, hi = int(pd.Timestamp("2026-10-14 12:00", tz="UTC").value // 10**6), int(pd.Timestamp("2026-10-16 06:00", tz="UTC").value // 10**6)
print("\nСигналы в окне 14–16.10 (UTC+3): время входа (открытие следующей свечи), сторона, цена, лаг от паттерна")
for name in ("паттерн (без подтверждения)", "+ закрытие за EMA20", "закр. за EMA20 → слом структуры", "закр. за EMA20 → за экстремумом паттерна" if False else "закр. за EMA20 → объём ≥1.2×"):
    st = dict(SETS)[name]
    g = cs.stage_signals(pre, dict(cs.PARAMS, stages=st))
    out = [(L3(pre["t"][i + 1]), side, round(pre["o"][i + 1], 1), i - tr) for i, (side, tr) in sorted(g.items()) if i + 1 < len(df) and lo <= pre["t"][i] <= hi]
    print(" ", name, "→", out[:14])
