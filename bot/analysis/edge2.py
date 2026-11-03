import json, time, random, urllib.request, statistics as S, bisect
BASE = "https://data-api.binance.vision/api/v3"
d = json.load(open('/tmp/runs.json'))['accounts']
tr = {}
for k in ['me', 'bot', 'vp', 'both', 'cand']:
    for x in d[k]['account']['log']:
        if x.get('open') or x['tf'] not in ('5m', '15m'): continue
        tr[(x['sym'], x['tf'], x['side'], x['t_in'])] = x
trades = sorted(tr.values(), key=lambda x: x['t_in'])
def get(u):
    for a in range(4):
        try: return json.load(urllib.request.urlopen(u, timeout=20))
        except Exception: time.sleep(1)
    return None
def klines(sym, tf, st, en):
    out = []
    while st < en:
        dd = get("%s/klines?symbol=%s&interval=%s&limit=1000&startTime=%d" % (BASE, sym, tf, st))
        if not dd: break
        out += dd; st = int(dd[-1][0]) + 1
        if len(dd) < 1000: break
    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in out]
def aggt(sym, st, en):
    out = []; cur = st
    while cur < en:
        dd = get("%s/aggTrades?symbol=%s&startTime=%d&endTime=%d&limit=1000" % (BASE, sym, cur, min(en, cur + 3600000)))
        if not dd: break
        out += [(int(t['T']), float(t['p']), bool(t['m'])) for t in dd]
        if len(dd) < 1000: break
        cur = int(dd[-1]['T']) + 1
    return out
tmin = trades[0]['t_in']; now = int(time.time() * 1000); syms = sorted(set(x['sym'] for x in trades))
C5 = {}; AT = {}; I5 = {}
def atr_arr(c):
    a = None; out = [None]
    for i in range(1, len(c)):
        t_ = max(c[i][2] - c[i][3], abs(c[i][2] - c[i - 1][4]), abs(c[i][3] - c[i - 1][4])); a = t_ if a is None else a + (t_ - a) / 14; out.append(a)
    return out
CT = {}
for s in syms:
    C5[s] = klines(s, '5m', tmin - 3 * 86400000, now); I5[s] = {c[0]: i for i, c in enumerate(C5[s])}
    CT[s] = {'5m': (C5[s], atr_arr(C5[s]), I5[s])}
    c15 = klines(s, '15m', tmin - 4 * 86400000, now); CT[s]['15m'] = (c15, atr_arr(c15), {c[0]: i for i, c in enumerate(c15)})
MS = {'5m': 300000, '15m': 900000}
def unit_at(s, tf, t):
    c, a, ix = CT[s][tf]; b = (t // MS[tf]) * MS[tf] - MS[tf]; i = ix.get(b)
    return a[i] if i is not None and i >= 30 else None
def bracket(s, t, side, px, unit, Sm, Tm):
    st = (t // 300000 + 1) * 300000; i = I5[s].get(st)
    if i is None: return None
    sg = 1 if side == 'L' else -1; stop = px - sg * Sm * unit; tp = px + sg * Tm * unit; c = C5[s]
    for q in range(i, min(i + 288, len(c))):
        _, o, h, l, cl = c[q]
        if (l <= stop) if sg > 0 else (h >= stop): return ('stop', sg * (stop / px - 1) * 100)
        if (h >= tp) if sg > 0 else (l <= tp): return ('tp', sg * (tp / px - 1) * 100)
    q = i + 288
    if q >= len(c): return None
    return ('time', sg * (c[q - 1][4] / px - 1) * 100)
W = 60000; DELAY = 500
def sim_fill(tt, side, t0, mode, R, through):
    # tt: list of (t,p,m) sorted, covering [t0-10s, t0+W+...]. returns (fill_t, fill_p) or None
    ts = [x[0] for x in tt]; buy = side == 'L'
    def proxy(at):
        i = bisect.bisect_right(ts, at) - 1
        while i >= 0:
            if tt[i][2] == buy: return tt[i][1]   # buy limit: bid proxy = last sell-aggressor print (m=True); sell: last buy-aggressor (m=False)
            i -= 1
        return None
    k = 0
    while True:
        r = t0 + k * R if mode != 'passive' else t0
        if r >= t0 + W: return None
        L = proxy(r)
        if L is None: return None
        act = r + DELAY; end = (t0 + W) if mode == 'passive' else min(t0 + W, t0 + (k + 1) * R + DELAY)
        i = bisect.bisect_left(ts, act)
        while i < len(tt) and tt[i][0] < end:
            t_, p_, m_ = tt[i]
            if buy and m_ and (p_ < L if through else p_ <= L): return (t_, L)
            if (not buy) and (not m_) and (p_ > L if through else p_ >= L): return (t_, L)
            i += 1
        if mode == 'passive': return None
        k += 1
VAR = [('passive', 0, True), ('passive', 0, False), ('chase5s', 5000, True), ('chase5s', 5000, False), ('chase1s', 1000, True), ('chase1s', 1000, False)]
res = {v: [] for v in VAR}; n_ok = 0
for x in trades:
    s = x['sym']; tf = x['tf']; t0 = x['t_in']; u = unit_at(s, tf, t0)
    if not u: continue
    tt = aggt(s, t0 - 10000, t0 + W + 2000)
    if len(tt) < 5: continue
    n_ok += 1
    g_mkt = {}
    for g in [(1, 1), (1, 2)]:
        b = bracket(s, t0, x['side'], x['p_in'], u, g[0], g[1]); g_mkt[g] = b
    for v in VAR:
        mode, R, th = v
        f = sim_fill(tt, x['side'], t0, 'passive' if mode == 'passive' else 'chase', R if R else 0, th)
        rec = dict(g_mkt=g_mkt, filled=f is not None)
        if f:
            ft, fp = f; sg = 1 if x['side'] == 'L' else -1
            rec['impr'] = sg * (x['p_in'] / fp - 1) * 100   # +: better than market-at-open price
            rec['wait'] = (ft - t0) / 1000.0
            rec['lim'] = {}
            for g in [(1, 1), (1, 2)]:
                b = bracket(s, ft, x['side'], fp, u, g[0], g[1])
                if b: rec['lim'][g] = b
        res[v].append(rec)
print("trades with tick data:", n_ok, "(entries at signal time t_in; wait<=60s; latency 0.5s; fills: through = strictly through limit, touch = at limit)")
for v in VAR:
    r = res[v]; f = [a for a in r if a['filled']]; u_ = [a for a in r if not a['filled']]
    if not r: continue
    print("== %s %s: fill %.0f%% (%d/%d) | entry vs open-price %+.3f%% (median wait %.1fs)" % (v[0], "through" if v[2] else "touch", 100 * len(f) / len(r), len(f), len(r), S.mean(a['impr'] for a in f) if f else 0, S.median(a['wait'] for a in f) if f else 0))
    for g in [(1, 1), (1, 2)]:
        gf = [a['g_mkt'][g][1] for a in f if a['g_mkt'][g]]; gu = [a['g_mkt'][g][1] for a in u_ if a['g_mkt'][g]]
        # limit model net: entry maker 0.02; exit tp maker 0.02, stop/time taker 0.05
        ln = []
        for a in f:
            b = a['lim'].get(g)
            if b: ln.append(b[1] - 0.02 - (0.02 if b[0] == 'tp' else 0.05))
        mk = [a['g_mkt'][g][1] - 0.10 for a in r if a['g_mkt'][g]]
        print("   bracket %s/%s ATR: market-all net %+.3f%% (n=%d) | filled: mkt-gross %+.3f%% vs UNFILLED mkt-gross %+.3f%% (n=%d) | limit-model net on filled %+.3f%% (n=%d)" % (g[0], g[1], S.mean(mk), len(mk), S.mean(gf) if gf else 0, S.mean(gu) if gu else 0, len(gu), S.mean(ln) if ln else 0, len(ln)))
