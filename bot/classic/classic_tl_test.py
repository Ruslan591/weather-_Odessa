"""classic_tl_test.py — проверка триггеров по линиям тренда (tl_bounce — отбой в канале/флэте, tl_breakout — пробой треугольника) на 4h, 6 пар, вся история.
Два набора выходов: ПОЛЬЗОВАТЕЛЬСКИЙ (стоп за предыдущей свечой ≥3%/3 ATR, БУ 1.8/1.1, паттерн-трейлинг 2.0, разворот) и НЕЙТРАЛЬНЫЙ (стоп sig3: за 3 свечами −0.2 ATR,
цель 2R, выход по времени через 48 свечей, без БУ). Комиссия 0.05% за сторону. Сегменты по дате входа: A до 2023-07, B 2023-07…2025-09, LAST с 2025-10.
Сравнение с базой «паттерн разворота». Запуск: python classic_tl_test.py [tf]"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
TF = sys.argv[1] if len(sys.argv) > 1 else "4h"; STEP = {"1h": 3600000, "4h": 14400000}[TF]
now = int(time.time() * 1000)
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
T_A, T_L = ms("2023-07-01"), ms("2025-10-01")
SYMS = ["ZECUSDT", "NEARUSDT", "SOLUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"]
DATA = {}
for s in SYMS:
    df = load(s); DATA[s] = (df, int(df.t.iloc[0]) + 450 * STEP); print(s, len(df), flush=True)
USER = dict(tf=TF, entry_mode="stages", entry_trigger="open", tp_r=0.0, max_bars=0, rev_exit=True, stop_mode="prev", min_stop_pct=3.0, min_stop_atr=3.0, be_trigger=1.8, be_lock=1.1,
            trail_mode="none", trail_dist=0.7, pat_mode="trail", pat_min=2.0, fee=0.05)
NEUT = dict(tf=TF, entry_mode="stages", entry_trigger="open", tp_r=2.0, max_bars=48, rev_exit=False, stop_mode="sig3", be_trigger=30.0, be_lock=0.0, trail_mode="none",
            pat_mode="off", fee=0.05)
def st(*ts): return [{"t": t, "p": 0, "w": 2 if i else 12, "f": "none"} for i, t in enumerate(ts)]
SETS = [("база: паттерн разворота", st("pattern")), ("tl_bounce (отбой в канале/флэте)", st("tl_bounce")), ("tl_breakout (пробой треугольника)", st("tl_breakout")),
        ("tl_bounce + macd_sign + stoch_dir", st("tl_bounce", "macd_sign", "stoch_dir")), ("tl_breakout + macd_sign + stoch_dir", st("tl_breakout", "macd_sign", "stoch_dir"))]
def fm(x): return "%4d / %+8.1f / %+5.2f" % (len(x), x.sum(), x.mean() if len(x) else 0.0)
for en, ex in (("ВЫХОДЫ ПОЛЬЗОВАТЕЛЯ", USER), ("НЕЙТРАЛЬНЫЕ ВЫХОДЫ (sig3, цель 2R, 48 св.)", NEUT)):
    print("\n==== %s (%s) ====\nформат: сделок / сумма net %% / средний net %% за сделку" % (en, TF))
    print("%-38s | %-24s | %-24s | %-24s | %s" % ("триггер (пул 6 пар)", "A (до 2023-07)", "B (до 2025-10)", "LAST", "пар с плюсом в A / B / LAST"))
    for name, stg in SETS:
        segs = {s: [None, None, None] for s in SYMS}
        pool = [[], [], []]
        for s in SYMS:
            df, t0 = DATA[s]
            P = dict(cs.PARAMS, **ex, pat_filter="none", stages=stg, sim_from_ms=t0)
            tr = [(x["t_in"], x["net"]) for x in cs.simulate(df, now, P)]
            for k, sel in enumerate((lambda t: t < T_A, lambda t: T_A <= t < T_L, lambda t: t >= T_L)):
                arr = np.array([n for t, n in tr if sel(t)]); segs[s][k] = arr; pool[k].append(arr)
        pc = [np.concatenate(p) if p else np.array([]) for p in pool]
        plus = [sum(1 for s in SYMS if len(segs[s][k]) and segs[s][k].sum() > 0) for k in range(3)]
        have = [sum(1 for s in SYMS if len(segs[s][k])) for k in range(3)]
        print("%-38s | %s | %s | %s | %d/%d  %d/%d  %d/%d" % (name, fm(pc[0]), fm(pc[1]), fm(pc[2]), plus[0], have[0], plus[1], have[1], plus[2], have[2]), flush=True)
print("\nГОТОВО", flush=True)
