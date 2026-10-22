"""classic_fastchan_diag.py SYMBOL TF [UTC_END 'YYYY-MM-DD HH:MM'] [HOURS] — какие каналы строит быстрый канал на свежих свечах Binance (время вывода UTC+3)."""
import sys, json, urllib.request, datetime as dt
import numpy as np
import classic_fastchan as F

sym, tf = sys.argv[1], sys.argv[2]
end = sys.argv[3] if len(sys.argv) > 3 else None
hours = float(sys.argv[4]) if len(sys.argv) > 4 else 6
url = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (sym, tf)
if end:
    ms = int(dt.datetime.strptime(end, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    url += "&endTime=%d" % ms
k = json.load(urllib.request.urlopen(url, timeout=20))
t = np.array([x[0] for x in k]) / 1000.0
o, h, l, c = (np.array([float(x[j]) for x in k]) for j in (1, 2, 3, 4))
tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
atr = np.zeros(len(c)); atr[13] = tr[:14].mean()
for i in range(14, len(c)):
    atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
atr[:13] = atr[13]
tm = lambda i: (dt.datetime.utcfromtimestamp(t[i]) + dt.timedelta(hours=3)).strftime("%d.%m %H:%M")
n = len(c)
print("candles", n, "last", tm(n - 1), "close", c[-1])
t0 = t[-1] - hours * 3600
prev = None
for i, st, ev in F.walk(o, h, l, c, atr):
    if t[i] < t0:
        continue
    if ev:
        print("%s  BREAK %s by close %.5f" % (tm(i), ev["dir"], c[i]))
    if st and (prev is None or st["born"] != prev):
        prev = st["born"]
        pv = " ".join("%s@%s" % (kk, tm(ii)) for ii, kk in st["pivots"])
        print("%s  NEW %s %s width %.1f ATR  low[%.5f->%.5f] up[%.5f->%.5f]  pivots %s" % (tm(i), st["kind"], st["mode"], st["width_atr"],
              F.at(st["lower"], st["lower"][0]), F.at(st["lower"], i), F.at(st["upper"], st["upper"][0]), F.at(st["upper"], i), pv))
