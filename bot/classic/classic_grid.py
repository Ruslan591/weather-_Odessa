"""classic_grid.py — перебор комбинаций ФИЛЬТРОВ входа на ZEC и NEAR (4h, вся история), выходы и ставка как в текущих правилах пользователя.
Перебор: фильтр значимости паттерна (10 вариантов) × набор подтверждений после триггера-паттерна (0, 1 или 2 из 17 типов; окно каждого 2 св.) = 1540 конфигураций.
Выходы фиксированы: вход по открытию, стоп за предыдущей свечой (не ближе 3% и 3 ATR), БУ 1.8%/1.1%, паттерн-трейлинг 2.0, разворот, комиссия 0.05% за сторону.
Сегменты по дате входа: A — до 2023-07-01; B — 2023-07-01…2025-09-30 (вместе A+B = подбор); LAST — с 2025-10-01 (год настройки пользователя, в подборе НЕ участвует).
Отбор: средний net > 0 в A и в B на пуле ZEC+NEAR и на каждой паре в отдельности; ранжирование по t-статистике пула A+B. Запуск: python classic_grid.py"""
import itertools, json, multiprocessing as mp, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
now = int(time.time() * 1000); STEP = 14400000
_orig = cs.prepare; _cache = {}
def _prep(df, n_):
    k = (len(df), int(df.t.iloc[0]), int(df.t.iloc[-1]))
    if k not in _cache: _cache[k] = _orig(df, n_)
    return _cache[k]
cs.prepare = _prep


def load(sym):
    parts, end = [], None
    for _ in range(30):
        u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=4h&limit=1000" % sym + ("&endTime=%d" % end if end else "")
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
T_A, T_LAST = ms("2023-07-01"), ms("2025-10-01")
BASE = dict(tf="4h", entry_mode="stages", entry_trigger="open", tp_r=0.0, max_bars=0, rev_exit=True, stop_mode="prev", min_stop_pct=3.0, min_stop_atr=3.0,
            be_trigger=1.8, be_lock=1.1, trail_mode="none", trail_dist=0.7, pat_mode="trail", pat_min=2.0, fee=0.05, pat_filter="none")
DATA = {}
for sym in ("ZECUSDT", "NEARUSDT"):
    df = load(sym); DATA[sym] = (df, int(df.t.iloc[0]) + 450 * STEP)
    print(sym, len(df), "свечей с", datetime.datetime.fromtimestamp(df.t.iloc[0] / 1000, datetime.UTC).date(), flush=True)
CONF = ["close_ema20", "break_trigger", "ema20_slope", "rsi_level", "macd_turn", "volume", "strong_body", "break_swing", "pullback_ema20", "rsi_band", "ext_dist",
        "stoch_dir", "macd_sign", "ema50_slope", "ema50_trend", "ema50_pullback", "stochrsi_cross"]
PATF = ["none", "level", "volume", "extreme", "stretch", "level+volume", "extreme+volume", "sweep", "sweep16", "sweep+volume"]
SETS = [()] + [(a,) for a in CONF] + list(itertools.combinations(CONF, 2))
CONFIGS = [(pf, cs_) for pf in PATF for cs_ in SETS]


def stages_of(cset, w=2):
    return [{"t": "pattern", "p": 0, "w": 12, "f": "none"}] + [{"t": t, "p": 0, "w": w, "f": "none"} for t in cset]


def run_cfg(pf, cset, stages=None):
    out = {}
    for sym, (df, t0) in DATA.items():
        P = dict(cs.PARAMS, **BASE, pat_filter=pf, stages=stages or stages_of(cset), sim_from_ms=t0)
        try: tr = cs.simulate(df, now, P)
        except Exception: tr = []
        out[sym] = [(x["t_in"], x["net"]) for x in tr]
    return out


def seg(tr):
    a = np.array([n for t, n in tr if t < T_A]); b = np.array([n for t, n in tr if T_A <= t < T_LAST]); c = np.array([n for t, n in tr if t >= T_LAST])
    return a, b, c


def work(i):
    pf, cset = CONFIGS[i]
    return i, run_cfg(pf, cset)


def st(x): return (x.mean() / (x.std() / np.sqrt(len(x)) + 1e-9)) if len(x) > 2 else 0.0
def fmt(x): return "%3d / %+7.1f / %+5.2f" % (len(x), x.sum(), x.mean() if len(x) else 0.0)
def desc(pf, cset): return "паттерн[%s] → %s" % (pf, " + ".join(cset) if cset else "без подтверждений")

if __name__ == "__main__":
    t0 = time.time()
    # базовые линии
    HIS = run_cfg("none", None, [{"t": "pattern", "p": 0, "w": 12, "f": "none"}, {"t": "macd_sign", "p": 0, "w": 2, "f": "none"}, {"t": "stoch_dir", "p": 0, "w": 2, "f": "none"}])
    NOF = run_cfg("none", ())
    print("\nВремя одной конфигурации ~%.1f с; всего конфигураций %d" % ((time.time() - t0) / 2, len(CONFIGS)), flush=True)
    print("\nФормат ячейки: сделок / сумма net % / средний net % за сделку")
    hdr = "%-52s | %-22s | %-22s | %-22s" % ("конфигурация (пул ZEC+NEAR)", "A (до 2023-07)", "B (2023-07…2025-09)", "LAST (с 2025-10)")
    for nm, R in (("БАЗА: только паттерн, без подтверждений", NOF), ("ТЕКУЩИЕ ПРАВИЛА пользователя (macd_sign + stoch_dir)", HIS)):
        pool = [seg(R[s]) for s in R]
        print("\n" + nm); print(hdr)
        print("%-52s | %s | %s | %s" % ("  пул", *[fmt(np.concatenate([p[k] for p in pool])) for k in range(3)]))
        for s, p in zip(R, pool): print("%-52s | %s | %s | %s" % ("  " + s, fmt(p[0]), fmt(p[1]), fmt(p[2])))
    ncpu = max(1, min(os.cpu_count() or 1, 4)); print("\nпроцессов:", ncpu, flush=True)
    res = {}
    with mp.Pool(ncpu) as pool_:
        for k, (i, r) in enumerate(pool_.imap_unordered(work, range(len(CONFIGS)), chunksize=8)):
            res[i] = r
            if (k + 1) % 200 == 0: print("  посчитано %d / %d (%.0f с)" % (k + 1, len(CONFIGS), time.time() - t0), flush=True)
    rows = []
    for i, r in res.items():
        pf, cset = CONFIGS[i]
        segs = {s: seg(r[s]) for s in r}
        A = np.concatenate([segs[s][0] for s in segs]); B = np.concatenate([segs[s][1] for s in segs]); Lt = np.concatenate([segs[s][2] for s in segs])
        pre = np.concatenate([A, B])
        rows.append(dict(i=i, pf=pf, cset=cset, A=A, B=B, L=Lt, pre=pre, segs=segs))
    ok = [r for r in rows if len(r["A"]) >= 10 and len(r["B"]) >= 10]
    print("\nКонфигураций с ≥10 сделок в A и в B: %d из %d" % (len(ok), len(rows)))
    pos_pre = [r for r in ok if r["pre"].mean() > 0]
    print("со средним net>0 на подборе (A+B): %d (%.0f%%)" % (len(pos_pre), 100 * len(pos_pre) / len(ok)))
    pos_last = [r for r in pos_pre if len(r["L"]) >= 3 and r["L"].mean() > 0]
    print("из них среднее net>0 и на LAST: %d (%.0f%%); всего таких в LAST среди всех: %.0f%%" % (len(pos_last), 100 * len(pos_last) / max(1, len(pos_pre)),
          100 * np.mean([r["L"].mean() > 0 for r in ok if len(r["L"]) >= 3])))
    xs = np.array([r["pre"].mean() for r in ok if len(r["L"]) >= 5]); ys = np.array([r["L"].mean() for r in ok if len(r["L"]) >= 5])
    from math import isnan
    rx = pd.Series(xs).rank().values; ry = pd.Series(ys).rank().values
    print("Корреляция рангов (средний net на подборе ↔ средний net на LAST) по %d конфигурациям: %.2f" % (len(xs), np.corrcoef(rx, ry)[0, 1]))
    sel = [r for r in ok if r["A"].mean() > 0 and r["B"].mean() > 0 and all(len(r["segs"][s][0]) >= 3 and len(r["segs"][s][1]) >= 3 and (np.concatenate([r["segs"][s][0], r["segs"][s][1]]).mean() > 0) for s in r["segs"])]
    sel.sort(key=lambda r: -st(r["pre"]))
    print("\nОтобраны (A>0 и B>0 на пуле, обе пары на подборе >0): %d конфигураций. ТОП-20 по t-статистике подбора:" % len(sel))
    print("%-4s %-62s | %-22s | %-22s | %-22s | %s" % ("t", "конфигурация", "A", "B", "LAST (чистая проверка)", "LAST по парам: сумма net"))
    for r in sel[:20]:
        print("%-4.1f %-62s | %s | %s | %s | ZEC %+.1f NEAR %+.1f" % (st(r["pre"]), desc(r["pf"], r["cset"])[:62], fmt(r["A"]), fmt(r["B"]), fmt(r["L"]),
              r["segs"]["ZECUSDT"][2].sum(), r["segs"]["NEARUSDT"][2].sum()))
    if sel:
        top = sel[:20]
        print("\nТОП-20: среднее LAST на сделку %+.2f%% (все отобранные: %+.2f%%); доля с LAST>0: %.0f%%" % (np.mean([r["L"].mean() for r in top if len(r["L"])]),
              np.mean([r["L"].mean() for r in sel if len(r["L"])]), 100 * np.mean([r["L"].sum() > 0 for r in top])))
    print("\nВремя расчёта: %.0f с" % (time.time() - t0))
    print("ГОТОВО", flush=True)
