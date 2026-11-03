import json, time, random, urllib.request, statistics as S
random.seed(11)
BASE = "https://data-api.binance.vision/api/v3/klines"; FEE = 0.10
d = json.load(open('/tmp/runs.json'))['accounts']
tr = {}
for k in ['me', 'bot', 'vp', 'both', 'cand']:
    for x in d[k]['account']['log']:
        if x.get('open') or x['tf'] not in ('5m', '15m'): continue
        tr[(x['sym'], x['tf'], x['side'], x['t_in'])] = x
trades = list(tr.values()); print("unique trades (5m/15m):", len(trades))
def fetch(sym, tf, st, en):
    out = []
    while st < en:
        u = "%s?symbol=%s&interval=%s&limit=1000&startTime=%d" % (BASE, sym, tf, st)
        for a in range(4):
            try: dd = json.load(urllib.request.urlopen(u, timeout=20)); break
            except Exception: time.sleep(1); dd = None
        if not dd: break
        out += dd; st = int(dd[-1][0]) + 1
        if len(dd) < 1000: break
    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in out]
tmin = min(x['t_in'] for x in trades); tmax = max(x['t_in'] for x in trades); now = int(time.time() * 1000)
syms = sorted(set(x['sym'] for x in trades)); D = {}
for s in syms:
    D[s] = {tf: fetch(s, tf, tmin - 4 * 86400000, now) for tf in ('5m', '15m')}
print("symbols", len(syms), flush=True)
MS = {'5m': 300000, '15m': 900000}
def atr_arr(c):
    a = None; out = [None]
    for i in range(1, len(c)):
        tr_ = max(c[i][2] - c[i][3], abs(c[i][2] - c[i - 1][4]), abs(c[i][3] - c[i - 1][4])); a = tr_ if a is None else a + (tr_ - a) / 14; out.append(a)
    return out
AT = {s: {tf: atr_arr(D[s][tf]) for tf in D[s]} for s in syms}
IDX = {s: {tf: {c[0]: i for i, c in enumerate(D[s][tf])} for tf in D[s]} for s in syms}
def unit_at(s, tf, t):
    b = (t // MS[tf]) * MS[tf] - MS[tf]   # last closed candle open
    i = IDX[s][tf].get(b)
    if i is None or i < 30: return None
    return AT[s][tf][i]
c5 = {s: D[s]['5m'] for s in syms}; i5 = {s: {c[0]: i for i, c in enumerate(c5[s])} for s in syms}
HMAX = 24 * 12
def bracket(s, t, side, px, unit, Sm, Tm):
    st = (t // 300000 + 1) * 300000; i = i5[s].get(st)
    if i is None: return None
    sg = 1 if side == 'L' else -1
    stop = px - sg * Sm * unit; tp = px + sg * Tm * unit; c = c5[s]
    for q in range(i, min(i + HMAX, len(c))):
        _, o, h, l, cl = c[q]
        if (l <= stop) if sg > 0 else (h >= stop):
            return (sg * (stop / px - 1)) * 100 - FEE
        if (h >= tp) if sg > 0 else (l <= tp):
            return (sg * (tp / px - 1)) * 100 - FEE
    q = i + HMAX
    if q >= len(c): return None
    return sg * (c[q - 1][4] / px - 1) * 100 - FEE
GRID = [(0.5, 0.5), (1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (1, 3), (3, 3), (0.5, 2), (2, 0.5)]
ent = {g: [] for g in GRID}; ctl = {g: [] for g in GRID}
for x in trades:
    s = x['sym']; tf = x['tf']; u = unit_at(s, tf, x['t_in'])
    if not u: continue
    px = x['p_in']
    for g in GRID:
        r = bracket(s, x['t_in'], x['side'], px, u, g[0], g[1])
        if r is not None: ent[g].append((r, x['t_in']))
    for _ in range(8):
        t = random.randint(tmin, tmax); t = (t // 300000) * 300000 + 1
        u2 = unit_at(s, tf, t); k = i5[s].get((t // 300000 + 1) * 300000)
        if not u2 or k is None: continue
        px2 = c5[s][i5[s].get((t // 300000) * 300000, k)][4]
        for g in GRID:
            r = bracket(s, t, x['side'], px2, u2, g[0], g[1])
            if r is not None: ctl[g].append((r, t))
print("grid stop/target in ATR units of the trade TF; mean net %% per trade after 0.10%% fee; horizon 24h, no BE/trail")
print("%-10s %6s %8s %7s | %6s %8s %7s | diff   z" % ("S/T", "n_ent", "meanEnt", "win%", "n_ctl", "meanCtl", "win%"))
for g in GRID:
    e = [r for r, _ in ent[g]]; c = [r for r, _ in ctl[g]]
    if len(e) < 20 or len(c) < 50: continue
    me, mc = S.mean(e), S.mean(c); se = (S.pvariance(e) / len(e) + S.pvariance(c) / len(c)) ** 0.5
    print("%-10s %6d %+8.3f %6.1f%% | %6d %+8.3f %6.1f%% | %+.3f %+.1f" % ("%.1f/%.1f" % g, len(e), me, 100 * sum(1 for r in e if r > 0) / len(e), len(c), mc, 100 * sum(1 for r in c if r > 0) / len(c), me - mc, (me - mc) / se))
# gross expectancy iso-line illustration: entries only
print("time split of entries (first half vs second half of trades), meanEnt for 1/1,2/1,1/2,2/2")
for g in [(1, 1), (2, 1), (1, 2), (2, 2)]:
    v = sorted(ent[g], key=lambda z: z[1]); h = len(v) // 2
    print("%.0f/%.0f" % g, "half1 %+.3f half2 %+.3f" % (S.mean([r for r, _ in v[:h]]), S.mean([r for r, _ in v[h:]])))
