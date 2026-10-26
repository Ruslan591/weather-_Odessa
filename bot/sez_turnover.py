# -*- coding: utf-8 -*-
"""Сезонник N1 L14 R7: сколько сделок (ордеров) в день/неделю/месяц. Запуск: cd /opt/trading-bot && EXTRA_DIR=data_ext venv/bin/python /tmp/sez_turnover.py"""
import glob, os
import numpy as np
import pandas as pd

TOPN, START, N, L, R = 15, 210, 1, 14, 7
O, CL, V = {}, {}, {}
EXTRA = os.environ.get("EXTRA_DIR")
FILES = sorted(glob.glob("data/*_USDT_1d.csv")) + (sorted(glob.glob(EXTRA + "/*_USDT_1d.csv")) if EXTRA else [])
for f in FILES:
    s = os.path.basename(f).split("_")[0]
    d = pd.read_csv(f, parse_dates=["time"]).set_index("time")
    d = d[~d.index.duplicated()].sort_index()
    O[s], CL[s], V[s] = d.open, d.close, d.volume
O, CL, V = pd.DataFrame(O), pd.DataFrame(CL), pd.DataFrame(V)
cols, dates = list(CL.columns), CL.index
dv = (CL * V).rolling(30).mean()
elig = (CL.notna() & (dv.rank(axis=1, ascending=False) <= TOPN)).to_numpy()
btc = CL["BTC"]
ok = (btc > btc.rolling(200).mean()).to_numpy()
mom = (CL / CL.shift(L) - 1).to_numpy()
CL_ = CL.to_numpy()
T, M = CL_.shape
held = -1
orders = []  # (дата, 'buy'/'sell', монета)
inmkt = []
for t in range(START, T - 2):
    new = -1
    if not ok[t]:
        new = -1
    elif (t - START) % R == 0:
        sc = np.where(elig[t] & (mom[t] > 0), mom[t], -np.inf)
        i = int(np.argmax(sc))
        new = i if np.isfinite(sc[i]) else -1
    else:
        new = held if (held >= 0 and not np.isnan(CL_[t][held])) else -1
    if new != held:
        if held >= 0:
            orders.append((dates[t], "sell", cols[held]))
        if new >= 0:
            orders.append((dates[t], "buy", cols[new]))
    held = new
    inmkt.append(held >= 0)
days = len(inmkt)
od = pd.DataFrame(orders, columns=["d", "side", "sym"])
print("Период %s .. %s: %d дней (%.1f лет)" % (dates[START].date(), dates[T - 3].date(), days, days / 365.25))
print("Всего ордеров: %d (покупок %d, продаж %d)" % (len(od), (od.side == "buy").sum(), (od.side == "sell").sum()))
print("В рынке %.0f%% дней" % (100 * np.mean(inmkt)))
yrs = days / 365.25
print("Ордеров в среднем: %.2f в день, %.1f в неделю, %.1f в месяц" % (len(od) / days, len(od) / days * 7, len(od) / days * 30.4))
buys = od[od.side == "buy"]
print("Входов (покупок): %.2f в неделю, %.1f в месяц, %.0f в год" % (len(buys) / days * 7, len(buys) / days * 30.4, len(buys) / yrs))
od["y"] = od.d.dt.year
od["m"] = od.d.dt.to_period("M")
print("По годам (ордеров):", dict(od.groupby("y").size()))
pm = od.groupby("m").size().reindex(pd.period_range(od.m.min(), od.m.max(), freq="M"), fill_value=0)
print("Ордеров в месяц: медиана %d, 90-й перцентиль %d, максимум %d, минимум %d" % (pm.median(), pm.quantile(0.9), pm.max(), pm.min()))
pw = od.groupby(od.d.dt.to_period("W")).size().reindex(pd.period_range(od.d.min(), od.d.max(), freq="W"), fill_value=0)
print("Ордеров в неделю: доля недель с 0: %.0f%%, с 1: %.0f%%, с 2: %.0f%%, больше: %.0f%%; максимум %d" % (100 * (pw == 0).mean(), 100 * (pw == 1).mean(), 100 * (pw == 2).mean(), 100 * (pw > 2).mean(), pw.max()))
print("Дней между сменами монеты (медиана): %.0f" % np.median(np.diff(buys.d.values).astype("timedelta64[D]").astype(int)))
print("Последние 8 ордеров:", [(str(a.date()), b, c) for a, b, c in orders[-8:]])
print("ГОТОВО")
