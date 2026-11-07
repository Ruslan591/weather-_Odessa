# -*- coding: utf-8 -*-
"""chan_life_diag.py: срок жизни замороженного канала Fixed N при разных правилах перестройки после выхода.
delay = сколько свечей ждать после выхода перед построением нового канала (0 = сразу, как в chan_fixed_study)."""
import sys, os
import numpy as np
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "chan_fixed_study.py"), encoding="utf-8").read().rstrip()
assert src.endswith("main()"); src = src[:-len("main()")]
sys.argv = ["chan_fixed_study.py", "5m", "60", "100"]
ns = {"__name__": "chan_fixed_study"}; exec(compile(src, "chan_fixed_study.py", "exec"), ns)
klines, atr14 = ns["klines"], ns["atr14"]; KS, FLAT, BO = 2.0, 0.03, 0.5

def lives(o, h, l, c, atr, N, delay, need_out):
    n = len(c); x = np.arange(N, dtype=float); xm = x.mean(); sxx = ((x - xm) ** 2).sum(); out = []; i = N - 1; act = None; born = None; first = True; firsts = []
    def make(i):
        y = c[i - N + 1:i + 1]; ym = y.mean(); s = ((x - xm) * (y - ym)).sum() / sxx; a0 = ym - s * xm
        return a0, s, i - N + 1, float(np.sqrt(((y - (a0 + s * x)) ** 2).sum() / (N - 2)))
    wait = 0
    for i in range(N - 1, n):
        if act is None:
            if wait > 0: wait -= 1; continue
            act = make(i); born = i; continue
        a0, s, st, sd = act; m = a0 + s * (i - st); U = m + KS * sd; L = m - KS * sd
        bl = min(o[i], c[i]); bh = max(o[i], c[i]); body = max(bh - bl, 1e-12); ex = 0
        if c[i] > U and (bh - max(bl, U)) / body >= BO: ex = 1
        elif c[i] < L and (min(bh, L) - bl) / body >= BO: ex = -1
        if need_out >= 2 and ex == 0 and False: pass
        if ex:
            out.append(i - born)
            if delay == 0: act = make(i); born = i
            else: act = None; wait = delay - 1
    return np.array(out)

for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    a = klines(sym, "5m", 60); o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]; atr = atr14(h, l, c)
    for N in (100,):
        for delay in (0, 12, 50, 100):
            L = lives(o, h, l, c, atr, N, delay, 1)
            print("%s N=%d delay=%3d channels %5d life bars: median %.0f p25 %.0f p75 %.0f p90 %.0f mean %.1f  share<=3: %.0f%%  share>=100: %.0f%%" % (sym, N, delay, len(L), np.median(L), np.percentile(L, 25), np.percentile(L, 75), np.percentile(L, 90), L.mean(), 100.0 * (L <= 3).mean(), 100.0 * (L >= 100).mean()), flush=True)
