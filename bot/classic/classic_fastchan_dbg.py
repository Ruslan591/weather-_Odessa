"""Отладка: зигзаг-пивоты и причины отказа кандидатов канала. python classic_fastchan_dbg.py SYM TF 'HH:MM' (локальное UTC+3, сегодня) """
import sys, json, urllib.request, datetime as dt
import numpy as np
import classic_fastchan as F
sym, tf = sys.argv[1], sys.argv[2]
k = json.load(urllib.request.urlopen("https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (sym, tf), timeout=20))
t = np.array([x[0] for x in k]) / 1000.0
o, h, l, c = (np.array([float(x[j]) for x in k]) for j in (1, 2, 3, 4))
tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
atr = np.zeros(len(c)); atr[13] = tr[:14].mean()
for i in range(14, len(c)):
    atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
atr[:13] = atr[13]
tm = lambda i: (dt.datetime.fromtimestamp(t[i], dt.timezone.utc) + dt.timedelta(hours=3)).strftime("%H:%M")
cfg = dict(F.FC)
piv = F.find_pivots(o, h, l, c, cfg)
zz = []
for p in piv:
    F._add_zz(zz, p, h, l, atr, cfg["dev"])
print("ATR last %.4f" % atr[-1])
print("zigzag since", sys.argv[3])
for p in zz:
    if tm(p["i"]) >= sys.argv[3] or True:
        if dt.datetime.fromtimestamp(t[p["i"]], dt.timezone.utc).date() == dt.datetime.now(dt.timezone.utc).date() and tm(p["i"]) >= sys.argv[3]:
            print(tm(p["i"]), p["k"], h[p["i"]] if p["k"] == "H" else l[p["i"]])
anH, anL = F._anom(o, h, l, c, atr, cfg)
i = len(c) - 2
l740 = [p for p in zz if p["k"] == "L" and tm(p["i"]) == "07:40"]
print("candles from 08:35 (open time): close / lowline(user #4)")
for j in range(len(c)):
    if tm(j) >= "08:30" and dt.datetime.fromtimestamp(t[j], dt.timezone.utc).date() == dt.datetime.now(dt.timezone.utc).date():
        print(tm(j), o[j], h[j], l[j], c[j])
