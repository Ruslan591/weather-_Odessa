"""classic_atr.py — стоп/безубыток/трейлинг в единицах ATR (масштаб по волатильности пары), 1h, 13 месяцев."""
import itertools, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_entry as ce
import classic_strategy as cs

def run(P, cond=None):
    T = []
    for s, d in ce.D.items():
        filt = (lambda side, i, d=d: cond(d, side, i)) if cond else None
        for x in cs.simulate(d["df"], ce.now, P, d["pre"], filt):
            if x["t_in"] >= ce.START:
                x["sym"] = s; T.append(x)
    return T

rows = []
for ms, be, tr in itertools.product((1.5, 2.0, 3.0, 4.0), (1.0, 1.5, 2.0, 3.0), (3.0, 4.0, 5.0)):
    P = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=0.3, min_stop_atr=ms, be_trigger=1.0, be_atr=be, trail_mode="atr", trail_dist=tr)
    T = run(P); n = len(T); net = sum(x["net"] for x in T)
    top5 = sum(sorted((x["net"] for x in T), reverse=True)[:5])
    h1 = sum(x["net"] for x in T if x["t_in"] < ce.MID)
    import datetime
    mm = {}
    for x in T:
        m = datetime.datetime.fromtimestamp(x["t_in"] / 1000, datetime.UTC).strftime("%Y-%m"); mm[m] = mm.get(m, 0) + x["net"]
    rows.append((net, ms, be, tr, n, net / n, net - top5, sum(v > 0 for v in mm.values()), len(mm), h1, net - h1, sum(x["risk"] for x in T) / n))
rows.sort(reverse=True)
print("стоп=min k·ATR, БУ=k·ATR, трейл=k·ATR (ATR на сигнале)  — топ-12 и худшие 3")
print("%6s %5s %5s %5s %4s %6s %8s %6s %7s %7s %5s" % ("net", "стоп", "БУ", "трейл", "n", "avg", "без5луч", "мес+", "1пол", "2пол", "риск%"))
for r in rows[:12] + rows[-3:]:
    print("%+6.1f %5.1f %5.1f %5.1f %4d %+6.2f %+8.1f %3d/%-2d %+7.1f %+7.1f %5.2f" % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]))
best = rows[0]
Pb = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=0.3, min_stop_atr=best[1], be_trigger=1.0, be_atr=best[2], trail_mode="atr", trail_dist=best[3])
print("\nлучший + фильтры 4h:")
for lab, c in [("без фильтра", None), ("4h не против (>=0)", lambda d, side, i: d["sc4"][i] * ce.sg(side) >= 0), ("4h по тренду (=+2)", lambda d, side, i: d["sc4"][i] * ce.sg(side) == 2)]:
    ce.line(lab, [dict(x, s=x["i_in"] - 1) for x in run(Pb, c)])
# по парам для лучшего
T = run(Pb); byp = {}
for x in T: byp[x["sym"][:-4]] = byp.get(x["sym"][:-4], 0) + x["net"]
print("по парам:", {k: round(v, 1) for k, v in sorted(byp.items(), key=lambda kv: -kv[1])})
