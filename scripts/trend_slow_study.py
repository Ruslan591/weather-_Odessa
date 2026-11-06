# -*- coding: utf-8 -*-
"""trend_slow_study.py [TF 4h|1d] -- портфельный бэктест медленных трендовых систем на ~20 парах Binance (spot-котировки USDT), лонг и шорт, равные доли капитала на пару.
Стратегии: Donchian (пробой N свечей, выход по противоположному каналу N/2), EMA-кроссовер, направление авто-регрессии ADXAE (chan_src.regression_at).
Исполнение по закрытию сигнальной свечи, издержки 0.05% комиссия + 0.03% проскальзывание на каждое изменение позиции (в одну сторону), финансирование и маржа не учтены.
Показывает: годовую доходность, Sharpe, макс. просадку, число сделок в год, среднюю сделку после издержек, по половинам периода, и равновесную покупку-удержание для сравнения.
Предупреждение: пары выбраны из крупных ныне живых монет (выживший отбор), поэтому результат оптимистичен."""
import sys, json, time, urllib.request
import numpy as np
sys.path.insert(0, "/opt/trading-bot/positions")
TF = sys.argv[1] if len(sys.argv) > 1 else "4h"
NB = 9000 if TF == "4h" else 2000; PPY = 2190.0 if TF == "4h" else 365.0; STEP = 14400000 if TF == "4h" else 86400000
SYMS = "BTC ETH BNB XRP ADA DOGE LTC TRX LINK DOT ATOM ETC BCH SOL AVAX NEAR UNI FIL XLM AAVE".split()
COST = 0.0008

def klines(sym, n):
    out = []; end = None
    while len(out) < n:
        u = "https://api.binance.com/api/v3/klines?symbol=%sUSDT&interval=%s&limit=1000" % (sym, TF) + ("&endTime=%d" % end if end else "")
        k = json.load(urllib.request.urlopen(u, timeout=30))
        if not k: break
        out = k + out; end = int(k[0][0]) - 1
        if len(k) < 1000: break
    return out[-n:]

data = {}
for s in SYMS:
    try:
        k = klines(s, NB); data[s] = np.array([[float(x[0]), float(x[2]), float(x[3]), float(x[4])] for x in k][:-1])
    except Exception as e:
        print("skip", s, e)
t0 = min(a[0, 0] for a in data.values()); T = int(max(a[-1, 0] for a in data.values()) - t0) // STEP + 1
syms = list(data); N = len(syms)
H = np.full((N, T), np.nan); L = H.copy(); C = H.copy()
for i, s in enumerate(syms):
    a = data[s]; idx = ((a[:, 0] - t0) // STEP).astype(int); H[i, idx] = a[:, 1]; L[i, idx] = a[:, 2]; C[i, idx] = a[:, 3]
print("TF", TF, "pairs", N, "bars", T, "years %.2f" % (T / PPY), flush=True)
R = np.zeros((N, T)); R[:, 1:] = C[:, 1:] / C[:, :-1] - 1; R[np.isnan(R)] = 0.0
avail = ~np.isnan(C)

def ema(y, n):
    k = 2.0 / (n + 1); o = np.copy(y)
    for t in range(1, len(y)):
        o[t] = y[t] * k + o[t - 1] * (1 - k) if not np.isnan(y[t]) and not np.isnan(o[t - 1]) else y[t]
    return o

def sig_donchian(i, n, longonly):
    h, l, c = H[i], L[i], C[i]; pos = np.zeros(T); p = 0; m = max(n // 2, 5)
    for t in range(n + 1, T):
        if np.isnan(c[t]): pos[t] = p; continue
        hh = np.nanmax(h[t - n:t]); ll = np.nanmin(l[t - n:t]); hm = np.nanmax(h[t - m:t]); lm = np.nanmin(l[t - m:t])
        if p >= 0 and c[t] > hh: p = 1
        elif p <= 0 and c[t] < ll: p = 0 if longonly else -1
        elif p == 1 and c[t] < lm: p = 0
        elif p == -1 and c[t] > hm: p = 0
        pos[t] = p
    return pos

def sig_ema(i, f, s, longonly):
    c = C[i]; e1 = ema(c, f); e2 = ema(c, s); p = np.sign(e1 - e2); p[np.isnan(p)] = 0
    if longonly: p = np.maximum(p, 0)
    p[:s] = 0; return p

_regcache = {}
def sig_reg(i, longonly):
    import chan_src
    key = i
    if key not in _regcache:
        c = np.nan_to_num(C[i], nan=0.0); h = np.nan_to_num(H[i]); l = np.nan_to_num(L[i]); atr = chan_src._avg_tr(h, l, c, 14); d = np.zeros(T)
        first = int(np.argmax(avail[i])) + 360
        for t in range(first, T):
            if not avail[i, t]: d[t] = d[t - 1]; continue
            g = chan_src.regression_at(c, atr, t); d[t] = g["dir"] if g else 0
        _regcache[key] = d
    p = _regcache[key].copy()
    if longonly: p = np.maximum(p, 0)
    return p

def evaluate(posm, label, extra=""):
    P = np.zeros((N, T)); P[:] = posm; P[~avail] = 0
    dP = np.zeros((N, T)); dP[:, 1:] = np.abs(P[:, 1:] - P[:, :-1])
    shift = np.zeros((N, T)); shift[:, 1:] = P[:, :-1]
    gross = shift * R; cost = dP * COST; n_t = np.maximum(avail.sum(0), 1)
    ret = ((gross - cost).sum(0)) / n_t
    eq = np.cumprod(1 + ret); yrs = T / PPY; cagr = eq[-1] ** (1 / yrs) - 1; sh = ret.mean() / (ret.std() + 1e-12) * np.sqrt(PPY)
    dd = (eq / np.maximum.accumulate(eq) - 1).min(); half = T // 2
    sh1 = ret[:half].mean() / (ret[:half].std() + 1e-12) * np.sqrt(PPY); sh2 = ret[half:].mean() / (ret[half:].std() + 1e-12) * np.sqrt(PPY)
    nets = []
    for i in range(N):
        t = 1
        while t < T:
            if P[i, t - 1] != 0 and (t == 1 or P[i, t - 2] != P[i, t - 1]):
                j = t
                while j < T and P[i, j - 1] == P[i, t - 1]: j += 1
                seg = (P[i, t - 1] * R[i, t:j]).sum() - 2 * COST; nets.append(seg * 100); t = j
            else: t += 1
    nets = np.array(nets) if nets else np.array([0.0])
    print("%-30s CAGR %+6.1f%% Sharpe %+5.2f (%+5.2f / %+5.2f) maxDD %6.1f%% trades/yr %5.0f avg %+6.2f%% win %2.0f%% %s" % (label, cagr * 100, sh, sh1, sh2, dd * 100, len(nets) / yrs, nets.mean(), (nets > 0).mean() * 100, extra), flush=True)

bh = np.ones((N, T)); evaluate(bh, "buy&hold equal weight")
for lo in (False, True):
    tag = "long-only" if lo else "long/short"
    print("== Donchian", tag)
    ns = (20, 55, 100) if TF == "4h" else (10, 20, 55)
    if TF == "4h": ns = (60, 120, 240, 480)
    for n in ns: evaluate(np.array([sig_donchian(i, n, lo) for i in range(N)]), "donchian N=%d" % n)
    print("== EMA", tag)
    for f, s in ((10, 30), (20, 60), (50, 150)) if TF == "1d" else ((20, 60), (50, 150), (100, 300)): evaluate(np.array([sig_ema(i, f, s, lo) for i in range(N)]), "ema %d/%d" % (f, s))
    print("== regression auto (ADXAE) direction", tag)
    evaluate(np.array([sig_reg(i, lo) for i in range(N)]), "reg-auto dir")
print("DONE", flush=True)
