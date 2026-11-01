# MACD(12,26,9): bull/bear cross as entry; outcome split by cross depth. Results -> results.json (live page on :18095)
import glob, json, os, re, sys, time, pickle
import numpy as np, pandas as pd
CACHE = os.environ.get("MACD_CACHE", "/opt/trading-bot/wfscan/cache")
OUT = os.environ.get("MACD_OUT", "/opt/trading-bot/macdtest")
os.makedirs(OUT, exist_ok=True)
TFS = ["15m", "5m", "1h", "30m", "4h", "2h", "6h", "8h", "12h", "1d", "3m", "1m"]
HS = (12, 48); FEE = 0.10; WARM = 300; NPERM = int(os.environ.get("MACD_NPERM", "200"))
ATR_EDGES = [0.5, 1, 2, 4]
ATR_LAB = ["над нулём", "0-0.5", "0.5-1", "1-2", "2-4", ">4"]       # глубина в ATR
REL_EDGES = [0.25, 0.5, 0.75]
REL_LAB = ["над нулём", "<25%", "25-50%", "50-75%", ">=75%"]          # |MACD| / максимум |MACD| за 200 свечей
rng = np.random.default_rng(12345)

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

def load(sym, tf):
    fs = sorted(glob.glob(os.path.join(CACHE, "*_%s_%s.pkl" % (sym, tf))))
    if not fs: return None
    d = pickle.load(open(fs[-1], "rb")).sort_values("t").reset_index(drop=True)
    return d if len(d) > WARM + 100 else None

def prep(d):
    o = d.o.values; h = d.h.values; l = d.l.values; c = d.c.values; n = len(d)
    cs = pd.Series(c)
    macd = (cs.ewm(span=12, adjust=False).mean() - cs.ewm(span=26, adjust=False).mean())
    sig = macd.ewm(span=9, adjust=False).mean()
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values
    m = macd.values; s = sig.values
    rmax = pd.Series(np.abs(m)).rolling(200, min_periods=50).max().values
    up = np.zeros(n, bool); dn = np.zeros(n, bool)
    up[1:] = (m[:-1] <= s[:-1]) & (m[1:] > s[1:])
    dn[1:] = (m[:-1] >= s[:-1]) & (m[1:] < s[1:])
    up[:WARM] = False; dn[:WARM] = False
    return o, c, m, atr, rmax, up, dn, n

def fwd(o, c, n, H):  # long return % from open[j+1] to close[j+H]; nan where invalid
    r = np.full(n, np.nan)
    j = np.arange(WARM, n - 1 - H)
    r[j] = (c[j + H] / o[j + 1] - 1) * 100
    return r

def binidx(d, rel):
    if d < 0: return 0
    return 1 + int(np.searchsorted(ATR_EDGES, d, "right")), 1 + int(np.searchsorted(REL_EDGES, rel, "right"))

def main():
    syms = sorted(set(re.findall(r"_([A-Z0-9]+USDT)_", " ".join(os.listdir(CACHE)))))
    log("pairs", len(syms))
    res = {"meta": {"started": int(time.time()), "pairs": syms, "tfs_done": [], "status": "running", "nperm": NPERM,
                    "fee_round_pct": FEE, "horizons_bars": list(HS),
                    "rules": "MACD(12,26,9): пересечение MACD и сигнальной на закрытой свече, вход по открытию следующей; лонг - вверх, шорт - вниз. Глубина = расстояние MACD от нуля в ATR(14) на свече пересечения (над нулём = пересечение на 'неправильной' стороне)."},
           "cells": []}
    for tf in TFS:
        t0 = time.time()
        recs = []   # per signal
        base = {}   # (sym,side,H) -> array of all-bar returns (signed)
        spans = []
        for sym in syms:
            d = load(sym, tf)
            if d is None: continue
            o, c, m, atr, rmax, up, dn, n = prep(d)
            spans.append((n * (d.t.iloc[1] - d.t.iloc[0]) / 86400000))
            r = {H: fwd(o, c, n, H) for H in HS}
            for H in HS:
                v = r[H][~np.isnan(r[H])]
                base[(sym, "L", H)] = v; base[(sym, "S", H)] = -v
            dn_idx = np.where(dn)[0]; up_idx = np.where(up)[0]
            mid = n // 2
            for side, idx, opp in (("L", up_idx, dn_idx), ("S", dn_idx, up_idx)):
                for i in idx:
                    if i >= n - 2 or atr[i] <= 0: continue
                    dpt = (-m[i] if side == "L" else m[i]) / atr[i]
                    if dpt < 0: b1 = b2 = 0
                    else:
                        rel = abs(m[i]) / rmax[i] if rmax[i] > 0 else 0
                        b1, b2 = binidx(dpt, rel)
                    sg = 1 if side == "L" else -1
                    x = [sg * r[H][i] for H in HS]
                    k = np.searchsorted(opp, i, "right")
                    hold = np.nan
                    if k < len(opp) and opp[k] + 1 < n:
                        hold = sg * (o[opp[k] + 1] / o[i + 1] - 1) * 100 - FEE
                    recs.append((sym, side, b1, b2, x[0], x[1], hold, 0 if i < mid else 1))
        if not recs: continue
        df = pd.DataFrame(recs, columns=["sym", "side", "b1", "b2", "r12", "r48", "hold", "half"])
        cells = []
        for side in ("L", "S", "LS"):
            sd = df if side == "LS" else df[df.side == side]
            for kind, col, labs in (("atr", "b1", ATR_LAB), ("rel", "b2", REL_LAB)):
                for bi in [-1] + list(range(len(labs))):
                    cs_ = sd if bi < 0 else sd[sd[col] == bi]
                    cs48 = cs_.dropna(subset=["r48"])
                    if len(cs48) < 20: continue
                    cell = {"tf": tf, "side": side, "kind": kind, "bin": "все" if bi < 0 else labs[bi], "bi": bi,
                            "n": int(len(cs48)), "pairs": int(cs48.sym.nunique())}
                    for H, col2 in ((12, "r12"), (48, "r48")):
                        cc = cs_.dropna(subset=[col2])
                        mean = cc[col2].mean()
                        groups = []
                        for sy, g in cc.groupby("sym"):
                            sides = ["L", "S"] if side == "LS" else [side]
                            arrs = []
                            for sdn in sides:
                                k = int((g.side == sdn).sum())
                                if k: arrs.append((k, base[(sy, sdn, H)]))
                            groups.extend(arrs)
                        tot = sum(k for k, _ in groups)
                        bmean = sum(k * a.mean() for k, a in groups) / tot
                        sums = np.zeros(NPERM)
                        for k, a in groups:
                            sums += a[rng.integers(0, len(a), (NPERM, k))].sum(1)
                        pm = sums / tot
                        cell["m%d" % H] = round(float(mean), 3)
                        cell["x%d" % H] = round(float(mean - bmean), 3)
                        cell["p%d" % H] = round(float((1 + (pm >= mean).sum()) / (1 + NPERM)), 3)
                        if H == 48:
                            for hf in (0, 1):
                                ch = cc[cc.half == hf]
                                if len(ch) >= 5:
                                    gb = sum(int(((ch.sym == sy) & (ch.side == sd2)).sum()) * base[(sy, sd2, H)].mean()
                                             for sy in ch.sym.unique() for sd2 in (["L", "S"] if side == "LS" else [side])) / len(ch)
                                    cell["h%d" % (hf + 1)] = round(float(ch[col2].mean() - gb), 3)
                            pp = []
                            for sy, g in cc.groupby("sym"):
                                if len(g) >= 5:
                                    gb = np.mean([base[(sy, s2, H)].mean() for s2 in (["L", "S"] if side == "LS" else [side])])
                                    pp.append(g[col2].mean() - gb > 0)
                            cell["pp"] = round(float(np.mean(pp)), 2) if pp else None
                    hh = cs_["hold"].dropna()
                    cell["hold_n"] = int(len(hh))
                    if len(hh):
                        cell["hold_net"] = round(float(hh.mean()), 3); cell["hold_win"] = round(float((hh > 0).mean()), 2)
                    cell["cand"] = bool(cell["bi"] >= 0 and side != "LS" and cell["n"] >= 150 and cell["p48"] < 0.01 and cell["x48"] > 0
                                        and cell.get("h1", -1) > 0 and cell.get("h2", -1) > 0 and (cell.get("pp") or 0) >= 0.6)
                    cells.append(cell)
        res["cells"] = [c for c in res["cells"] if c["tf"] != tf] + cells
        res["meta"]["tfs_done"].append({"tf": tf, "signals": int(len(df)), "pairs": len(spans), "days_median": round(float(np.median(spans)), 1),
                                        "sec": round(time.time() - t0, 1)})
        tmp = os.path.join(OUT, "results.json.tmp")
        json.dump(res, open(tmp, "w"), ensure_ascii=False); os.replace(tmp, os.path.join(OUT, "results.json"))
        log(tf, "done", len(df), "signals", round(time.time() - t0, 1), "s")
    res["meta"]["status"] = "done"; res["meta"]["finished"] = int(time.time())
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), ensure_ascii=False)
    log("ALL DONE")

if __name__ == "__main__":
    main()
