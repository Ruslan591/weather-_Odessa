# -*- coding: utf-8 -*-
"""Сезонник: ротация по моментуму против случайного выбора монеты (те же недели, тот же фильтр BTC>SMA200, те же комиссии).
Запуск на VPS: cd /opt/trading-bot && venv/bin/python /tmp/sez_random.py   (данные data/*_USDT_1d.csv, логика из rotation.py)"""
import glob, os, sys
import numpy as np
import pandas as pd

C, START, TOPN = 0.0015, 210, 15
NSEED = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
O, CL, V = {}, {}, {}
EXTRA = os.environ.get("EXTRA_DIR")
FILES = sorted(glob.glob("data/*_USDT_1d.csv")) + (sorted(glob.glob(EXTRA + "/*_USDT_1d.csv")) if EXTRA else [])
for f in FILES:
    s = os.path.basename(f).split("_")[0]
    d = pd.read_csv(f, parse_dates=["time"]).set_index("time")
    d = d[~d.index.duplicated()].sort_index()
    O[s], CL[s], V[s] = d.open, d.close, d.volume
O, CL, V = pd.DataFrame(O), pd.DataFrame(CL), pd.DataFrame(V)
cols = list(CL.columns)
dates = CL.index
dv = (CL * V).rolling(30).mean()
elig = (CL.notna() & (dv.rank(axis=1, ascending=False) <= TOPN)).to_numpy()
btc = CL["BTC"]
ok = (btc > btc.rolling(200).mean()).to_numpy()
mom = {L: (CL / CL.shift(L) - 1).to_numpy() for L in (14, 30, 60)}
O_, CL_ = O.to_numpy(), CL.to_numpy()
T, M = O_.shape
asset_ret = np.nan_to_num(O_[2:] / O_[1:-1] - 1)
idx = dates[START:T - 2]
yrs = idx.year


def run(N, L, R, mode="mom", rng=None, need_pos=True):
    w = np.zeros(M)
    rets = np.zeros(T)
    for t in range(START, T - 2):
        if not ok[t]:
            nw = np.zeros(M)
        elif (t - START) % R == 0:
            if mode == "mom":
                sc = np.where(elig[t] & (mom[L][t] > 0), mom[L][t], -np.inf)
                sel = [i for i in np.argsort(-sc)[:N] if np.isfinite(sc[i])]
            else:
                pool = np.where(elig[t] & ((mom[L][t] > 0) if need_pos else True))[0]
                sel = list(rng.choice(pool, size=min(N, len(pool)), replace=False)) if len(pool) else []
            nw = np.zeros(M)
            if sel:
                nw[sel] = 1.0 / len(sel)
        else:
            nw = w * (~np.isnan(CL_[t]))
        rets[t] = (nw * asset_ret[t]).sum() - C * np.abs(nw - w).sum()
        w = nw
    return rets[START:T - 2]


def met(r):
    eq = np.cumprod(1 + r)
    pk = np.maximum.accumulate(eq)
    n = len(r)
    return dict(x=eq[-1], cagr=(eq[-1] ** (365 / n) - 1) * 100, dd=((pk - eq) / pk).max() * 100,
                is_x=np.prod(1 + r[yrs <= 2022]), oos_x=np.prod(1 + r[yrs >= 2023]))


print("Период %s .. %s, дней %d, монет %d, комиссия %.2f%% за сторону; случайных прогонов %d" % (idx[0].date(), idx[-1].date(), len(idx), len(cols), C * 100, NSEED))
btc_r = asset_ret[START:T - 2, cols.index("BTC")].copy()
h = btc_r.copy(); h[0] -= C
f = np.where(ok[START:T - 2], btc_r, 0.0) - C * np.abs(np.diff(ok[START:T - 2].astype(float), prepend=0))
for nm, r in (("hold BTC", h), ("BTC>SMA200", f)):
    m = met(r)
    print("%-26s x%.1f cagr %+.0f%% dd %.0f%% IS x%.2f OOS(2023+) x%.2f" % (nm, m["x"], m["cagr"], m["dd"], m["is_x"], m["oos_x"]))
rng = np.random.default_rng(12345)
for (N, L, R) in ((1, 14, 7), (1, 30, 7), (2, 30, 7), (3, 30, 7)):
    ms = met(run(N, L, R, "mom"))
    for need_pos in (True, False):
        xs, os_, cg, dd = [], [], [], []
        for _ in range(NSEED):
            m = met(run(N, L, R, "rand", rng, need_pos))
            xs.append(m["x"]); os_.append(m["oos_x"]); cg.append(m["cagr"]); dd.append(m["dd"])
        xs, os_, cg = np.array(xs), np.array(os_), np.array(cg)
        print("N%d L%d R%d моментум: x%.1f cagr %+.0f%% dd %.0f%% OOS x%.2f | случайный выбор%s: x медиана %.1f (5%%..95%%: %.1f..%.1f), cagr мед %+.0f%%, OOS x мед %.2f | доля случайных не хуже моментума: по итогу %.0f%%, по OOS %.0f%%" % (
            N, L, R, ms["x"], ms["cagr"], ms["dd"], ms["oos_x"], " (только mom>0)" if need_pos else " (любая из топ-15)",
            np.median(xs), np.percentile(xs, 5), np.percentile(xs, 95), np.median(cg), np.median(os_),
            100 * (xs >= ms["x"]).mean(), 100 * (os_ >= ms["oos_x"]).mean()))
print("ГОТОВО")
