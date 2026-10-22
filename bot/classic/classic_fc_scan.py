"""classic_fc_scan.py [КОНФИГ ...] — пробой быстрого канала на 1h по тренду 1d на выборке research/ (сотня пар) + помесячная/поквартальная устойчивость.
Сделка: tl_breakout (tl_src=fast), тренд старшего ТФ по последней закрытой дневной свече, стоп sig3, без фикс. цели (tp_r=0, выход по стопу/обратному сигналу).
Конфиги: slope (EMA50 1d растёт/падает за 5 дн.), e200 (закрытие 1d выше/ниже EMA200), none (без тренда)."""
import sys, os, json
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L, classic_fastchan as fchan
R = "/opt/trading-bot/classic/research"
cfgs = sys.argv[1:] or ["slope", "e200", "none"]
SKIP = {"RLUSDUSDT", "XAUTUSDT", "USDCUSDT", "PAXGUSDT"}
syms = [s for s in json.load(open(R + "_universe.json")) if s not in SKIP]
ema = lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean().values
orig = fchan.fc_signals
res = {c: {} for c in cfgs}   # cfg -> sym -> dict(n, a, b, q[list])
for k, sym in enumerate(syms):
    f1, f2 = "%s/%s/klines_1h.csv" % (R, sym), "%s/%s/klines_1d.csv" % (R, sym)
    if not (os.path.exists(f1) and os.path.exists(f2)):
        continue
    df = pd.read_csv(f1); hd = pd.read_csv(f2)
    if len(df) < 5000 or len(hd) < 450 or float(df.c.pct_change().abs().mean()) < 0.0008:
        continue
    now = int(df.ct.iloc[-1]) + 10 ** 6
    hc = hd.c.values.astype(float); e200, e50 = ema(hc, 200), ema(hc, 50)
    tr = {"e200": np.sign(hc - e200), "slope": np.sign(e50 - np.r_[np.full(5, e50[0]), e50[:-5]])}
    j = np.searchsorted(hd.ct.values, df.t.values, side="right") - 1
    j[j < 200] = 200
    P0 = L.base_params(sym, "1h")
    warm = int(P0.get("warmup", 200)); t0, t1 = int(df.t.iloc[warm]), int(df.t.iloc[-1]); cut = int(t0 + 0.7 * (t1 - t0))
    nq = max(1, int((t1 - t0) / (91 * 86400000))); edges = np.linspace(t0, t1 + 1, nq + 1).astype(np.int64)
    for name in cfgs:
        def patched(o, h, l, c, atr, M, kind, p=0.0, minw=1.5, maxw=8.0, info=None, cfg=None, start=60, _n=name):
            inf = {} if info is not None else None
            out = orig(o, h, l, c, atr, M, kind, p, minw, maxw, info=inf, cfg=cfg, start=start)
            res_ = {}
            for i, s in out.items():
                if _n == "none" or (tr[_n][j[i]] > 0 and s == "L") or (tr[_n][j[i]] < 0 and s == "S"):
                    res_[i] = s
                    if info is not None: info[i] = inf[i]
            return res_
        fchan.fc_signals = patched
        P = dict(P0, tl_src="fast", stages=[{"t": "tl_breakout", "p": 0, "w": 0, "f": "none"}], entry_mode="stages", stop_mode="sig3", tp_mode="r", tp_r=0.0, sym=sym)
        try:
            T = cs.simulate(df, now, P, pre=cs.prepare(df, now))
        except Exception as e:
            print(sym, name, "err", repr(e)[:100], flush=True); continue
        a, b = L.metrics(T, None, cut), L.metrics(T, cut, None)
        q = [L.metrics(T, int(edges[i]), int(edges[i + 1]))["net"] for i in range(nq)]
        res[name][sym] = dict(n=len(T), a=a["net"], b=b["net"], ddb=b["dd"], q=q, nq=nq)
    fchan.fc_signals = orig
    if (k + 1) % 10 == 0:
        print(k + 1, "пар обработано", flush=True)
json.dump(res, open("/opt/trading-bot/classic/fc_scan_result.json", "w"))
for name in cfgs:
    r = res[name]
    if not r:
        continue
    syms_ = list(r)
    A = np.array([r[s]["a"] for s in syms_]); Bv = np.array([r[s]["b"] for s in syms_]); N = sum(r[s]["n"] for s in syms_)
    top = sorted(syms_, key=lambda s: -r[s]["b"])
    print("\n== %s: пар %d, сделок %d" % (name, len(syms_), N))
    print("подбор: сумма %+.0f, в среднем на пару %+.1f, в плюсе %d%%, медиана %+.1f" % (A.sum(), A.mean(), 100 * (A > 0).mean(), np.median(A)))
    print("проверка: сумма %+.0f, в среднем на пару %+.1f, в плюсе %d%%, медиана %+.1f; без 5 лучших пар сумма %+.0f" % (Bv.sum(), Bv.mean(), 100 * (Bv > 0).mean(), np.median(Bv), Bv.sum() - sum(r[s]["b"] for s in top[:5])))
    print("лучшие:", " ".join("%s%+.0f" % (s[:-4], r[s]["b"]) for s in top[:6]), "| худшие:", " ".join("%s%+.0f" % (s[:-4], r[s]["b"]) for s in top[-4:]))
    nq = min(r[s]["nq"] for s in syms_)
    print("по кварталам (в среднем на пару, % пар в плюсе):", " ".join("Q%d %+.1f/%d%%" % (i + 1, np.mean([r[s]["q"][i] for s in syms_]), 100 * np.mean([r[s]["q"][i] > 0 for s in syms_])) for i in range(nq)))
