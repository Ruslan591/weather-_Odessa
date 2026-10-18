"""classic_tl_robust.py — устойчивость триггера tl_breakout (пробой треугольника) с выходами пользователя: вклад крупнейших сделок, медиана, издержки 0.09%/сторону,
разбивка по парам и сегментам, 1h и 4h. Запуск: python classic_tl_robust.py 4h|1h"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
TF = sys.argv[1]; STEP = {"1h": 3600000, "4h": 14400000}[TF]; now = int(time.time() * 1000)
_o = cs.prepare; _c = {}
def _p(df, n_):
    k = (len(df), int(df.t.iloc[0]), int(df.t.iloc[-1]))
    if k not in _c: _c[k] = _o(df, n_)
    return _c[k]
cs.prepare = _p
def load(sym):
    parts, end = [], None
    for _ in range(30):
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
def ms(s): return int(datetime.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
SYMS = ["ZECUSDT", "NEARUSDT", "SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"]
DATA = {s: load(s) for s in SYMS}
for s in SYMS: print(s, len(DATA[s]), datetime.datetime.fromtimestamp(DATA[s].t.iloc[0] / 1000, datetime.UTC).date(), flush=True)
USER = dict(tf=TF, entry_mode="stages", entry_trigger="open", tp_r=0.0, max_bars=0, rev_exit=True, stop_mode="prev", min_stop_pct=3.0, min_stop_atr=3.0, be_trigger=1.8, be_lock=1.1,
            trail_mode="none", trail_dist=0.7, pat_mode="trail", pat_min=2.0)
def stg(*ts): return [{"t": t, "p": 0, "w": 2 if i else 12, "f": "none"} for i, t in enumerate(ts)]
def run(fee, stages):
    out = {}
    for s in SYMS:
        df = DATA[s]; t0 = int(df.t.iloc[0]) + 450 * STEP
        P = dict(cs.PARAMS, **USER, fee=fee, pat_filter="none", stages=stages, sim_from_ms=t0)
        out[s] = [(x["t_in"], x["net"], x["risk"]) for x in cs.simulate(df, now, P) if True]
    return out
def stats(tr):
    n = np.array([x[1] for x in tr])
    if not len(n): return "нет сделок"
    top = np.sort(n)[::-1]; k = min(5, len(n)); pos = n[n > 0].sum()
    return "n %d | сумма %+.1f | средний %+.2f | медиана %+.2f | win %.0f%% | t %.1f | топ-%d сделок = %.0f%% суммы прибыльных; без них средний %+.2f" % (
        len(n), n.sum(), n.mean(), np.median(n), (n > 0).mean() * 100, n.mean() / (n.std() / np.sqrt(len(n)) + 1e-9), k, 100 * top[:k].sum() / pos if pos else 0, np.sort(n)[:-k].mean() if len(n) > k else 0)
T_A, T_L = ms("2023-07-01"), ms("2025-10-01")
for name, sg in (("tl_breakout", stg("tl_breakout")), ("tl_breakout + macd_sign + stoch_dir", stg("tl_breakout", "macd_sign", "stoch_dir"))):
    for fee in (0.05, 0.09):
        R = run(fee, sg); allv = [x for s in SYMS for x in R[s]]
        print("\n== [%s] %s | комиссия %.2f%%/сторону" % (TF, name, fee)); print("  ВСЁ:", stats(allv))
        for lab, sel in (("A до 2023-07", lambda t: t < T_A), ("B 2023-07…2025-09", lambda t: T_A <= t < T_L), ("LAST с 2025-10", lambda t: t >= T_L)):
            print("  %-18s" % lab, stats([x for x in allv if sel(x[0])]))
        if fee == 0.05:
            print("  по парам (сумма net %% / сделок): " + " | ".join("%s %+.0f/%d" % (s[:-4], sum(x[1] for x in R[s]), len(R[s])) for s in SYMS))
            print("  по годам (сумма net %): " + " ".join("%d: %+.0f" % (y, sum(x[1] for x in allv if datetime.datetime.fromtimestamp(x[0] / 1000, datetime.UTC).year == y)) for y in range(2018, 2027)))
            print("  средний размер стопа (риск): %.2f%%" % np.mean([x[2] for x in allv]))
print("\nГОТОВО", flush=True)
