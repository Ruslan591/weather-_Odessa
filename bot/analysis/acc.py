import json, statistics as S, time
d = json.load(open('/tmp/runs.json'))['accounts']
for k in ['me', 'bot', 'vp', 'both', 'cand']:
    ac = d[k]['account']; lg = [x for x in ac['log'] if not x.get('open')]
    print("=== %s: closed(total)=%s wins=%s win%%=%s pnl$=%s | log n=%d, period %s .. %s" % (k, ac['closed'], ac['wins'], ac['win_pct'], ac['pnl'], len(lg),
        time.strftime("%m-%d %H:%M", time.gmtime(min(x['t_in'] for x in lg) / 1000)), time.strftime("%m-%d %H:%M", time.gmtime(max(x['t_out'] for x in lg) / 1000))))
    if not lg: continue
    nets = [x['net'] for x in lg]; w = [n for n in nets if n > 0]; l = [-n for n in nets if n <= 0]
    aw = S.mean(w) if w else 0; al = S.mean(l) if l else 0; p = len(w) / len(nets)
    pay = aw / al if al else 0; be = 1 / (1 + pay) if pay else 1
    print("  n=%d win=%.1f%% avgWin=%+.3f%% avgLoss=-%.3f%% payoff(W/L)=%.2f breakeven win%%=%.1f%% expectancy/trade=%+.3f%% (net%% = on position, after fee)" % (len(nets), p * 100, aw, al, pay, be * 100, p * aw - (1 - p) * al))
    print("  medWin=%+.3f medLoss=-%.3f  max win %+.2f max loss -%.2f" % (S.median(w) if w else 0, S.median(l) if l else 0, max(nets), -min(nets)))
    # BE-flag trades
    be_t = [x for x in lg if x.get('be')]; nb = [x for x in lg if not x.get('be')]
    if be_t: print("  BE-armed trades: %d, win%% %.0f, avg net %+.3f | no-BE: %d, win%% %.0f, avg net %+.3f" % (len(be_t), 100 * sum(1 for x in be_t if x['net'] > 0) / len(be_t), S.mean(x['net'] for x in be_t), len(nb), 100 * sum(1 for x in nb if x['net'] > 0) / max(1, len(nb)), S.mean(x['net'] for x in nb) if nb else 0))
    # distribution of wins/losses in buckets
    def hist(v, edges):
        c = [0] * (len(edges) + 1)
        for x in v:
            i = 0
            while i < len(edges) and x > edges[i]: i += 1
            c[i] += 1
        return c
    edges = [0.1, 0.25, 0.5, 1, 2, 4]
    print("  wins buckets (<=%s,>%s): %s" % (edges, edges[-1], hist(w, edges)))
    print("  loss buckets (<=%s,>%s): %s" % (edges, edges[-1], hist(l, edges)))
    # by tf, side
    for key in ['tf', 'side']:
        g = {}
        for x in lg: g.setdefault(x[key], []).append(x['net'])
        print("  by %s:" % key, {a: (len(b), round(100 * sum(1 for n in b if n > 0) / len(b)), round(sum(b) / len(b), 3)) for a, b in sorted(g.items())})
