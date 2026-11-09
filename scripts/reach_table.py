import os, sys, json
os.environ["POS_DIR"] = "/opt/trading-bot/positions_regr"; sys.path.insert(0, "/opt/tg-notify")
import tg_target as T
rows = T._rows(); hs = sorted(r["hatr"] for r in rows); thr = hs[len(hs)//2]
print("n", len(rows), "median width ATR", thr, "min", hs[0], "max", hs[-1])
for name, sel in (("narrow", lambda r: r["hatr"] < thr), ("wide", lambda r: r["hatr"] >= thr)):
    seg = [r for r in rows if sel(r)]
    out = []
    for f in T.GRID:
        xs = [r["res"]["%.2f" % f] for r in seg if r["res"].get("%.2f" % f) is not None]
        out.append("%.2f: %+.2fR win%d%% n%d" % (f, sum(xs)/len(xs), 100*sum(x > 0 for x in xs)/len(xs), len(xs)) if xs else "%.2f: -" % f)
    print(name, len(seg), " | ".join(out))
for w in (thr*0.6, thr*1.5): c = T.choose(w, False); print("choose width %.1f -> f=%s p=%s ev=%s n=%s" % (w, c["f"], c.get("p"), c.get("ev"), c["n"]))
