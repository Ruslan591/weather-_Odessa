"""classic_botcheck.py — сверка реализации в боте (cs.simulate: одна позиция за раз) с исследованием classic_rules.py (R1, вход по пробою, цель 3R).
Конфиг: уровни фильтра = паттерн → [ema50_trend + ema50_pullback + stochrsi_cross] (окно 1 св.), entry_trigger=breakout, stop_mode=sig3, tp_r=3,
fee 0.09% за сторону (0.18% за круг, как avgR* в исследовании), без безубытка/трейлинга/разворота. avgR = net% / риск% по сделке. Запуск: python classic_botcheck.py"""
import json, os, sys, time, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
now = int(time.time() * 1000)
CFG = dict(tf="15m", entry_mode="stages", entry_trigger="breakout", stop_mode="sig3", tp_r=3.0, rev_exit=False, be_trigger=30.0, be_lock=0.0, trail_mode="none",
           pat_mode="off", fee=0.09, pat_filter="none",
           stages=[{"t": "pattern", "p": 0, "w": 0, "f": "none"}, {"t": "ema50_trend", "p": 0, "w": 1, "f": "none"},
                   {"t": "ema50_pullback", "p": 0, "w": 1, "f": "none"}, {"t": "stochrsi_cross", "p": 0, "w": 1, "f": "none"}])


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


for sym, pg in (("ZECUSDT", 40), ("SOLUSDT", 20), ("XRPUSDT", 20), ("ETHUSDT", 20), ("BTCUSDT", 20)):
    df = load(sym, pg); P = dict(cs.PARAMS, **CFG)
    tr = [x for x in cs.simulate(df, now, P) if not x["open"]]
    if not tr: print(sym, "сделок нет"); continue
    R = np.array([x["net"] / x["risk"] for x in tr]); G = np.array([x["gross"] / x["risk"] for x in tr])
    reasons = {}
    for x in tr: reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    split = int(len(tr) * 0.6)
    print("%s: сделок %d (лонг %d / шорт %d) | win %.0f%% | avgR net %+.3f (gross %+.3f), t %.1f | первые 60%% %+.3f / последние 40%% %+.3f | ср. риск %.2f%% | итого net %+.1f%% | причины %s" % (
        sym, len(tr), sum(1 for x in tr if x["side"] == "L"), sum(1 for x in tr if x["side"] == "S"), (R > 0).mean() * 100, R.mean(), G.mean(),
        R.mean() / (R.std() / np.sqrt(len(R)) + 1e-9), R[:split].mean(), R[split:].mean(), np.mean([x["risk"] for x in tr]), sum(x["net"] for x in tr), reasons), flush=True)
print("ГОТОВО", flush=True)
