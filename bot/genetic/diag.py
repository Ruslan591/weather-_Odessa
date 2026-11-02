# -*- coding: utf-8 -*-
"""Диагностика: проблема во входе или в выходе? Для лучших геномов (feat, feat_short): валовая доходность (до издержек) на всех парах и всём времени.
A вход генома + выход генома; B вход генома + просто держать H свечей; C случайные входы (те же числа сигналов) + выход генома; D случайные + держать H.
Вход (при фикс. выходе) = B-D; эффект выхода на тех же входах = A-B. Результат: diag.json."""
import os, sys, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genetic as G
OUT = os.environ.get("GEN_OUT", "/opt/trading-bot/genetic"); NR = 10
G.DATA, _ = G.build_data(); G.ZONE = G.zone(G.DATA)
orig = G.signals; RNG = [None]
def rsig(s, g):
    L, S = orig(s, g); r = RNG[0]
    if r is None: return L, S
    n = s.n; pool = np.arange(G.WARM, n - 2)
    L2 = np.zeros(n, bool); S2 = np.zeros(n, bool)
    kl, ks = int(L.sum()), int(S.sum())
    if kl: L2[r.choice(pool, min(kl, len(pool)), replace=False)] = True
    if ks: S2[r.choice(pool, min(ks, len(pool)), replace=False)] = True
    return L2, S2
G.signals = rsig
def gross(g, rnd=None):
    RNG[0] = rnd; xs = []
    for grp in ("search", "unseen"):
        for s in G.DATA[g["tf"]][grp]:
            x, t = G.run(s, g)
            if len(x): xs.append(x + G.FEE)
    RNG[0] = None
    x = np.concatenate(xs) if xs else np.empty(0)
    return (float(x.mean()) if len(x) else float("nan")), len(x)
def full(a):
    g = {k: G.GRID[k][0] for k in G.KEYS}; g.update({k: (list(v) if isinstance(v, tuple) else v) for k, v in a.items()}); return G.fix(g)
rows = []
for d in ("feat", "feat_short"):
    r = json.load(open(os.path.join(OUT, d, "results.json")))
    for t in r["runs"]["real"]["top"][:10]:
        g = full(t["genome"]); g2 = dict(g, sl=0, tp=0, tr=0)
        A, n = gross(g); B, _ = gross(g2)
        C = float(np.nanmean([gross(g, np.random.default_rng(i))[0] for i in range(NR)]))
        D = float(np.nanmean([gross(g2, np.random.default_rng(100 + i))[0] for i in range(NR)]))
        rows.append({"text": t["text"], "tf": g["tf"], "n": n, "A": A, "B": B, "C": C, "D": D, "entry_fixed": B - D, "entry_with_exit": A - C, "exit_on_entries": A - B})
        print(round(A, 3), round(B, 3), round(C, 3), round(D, 3), n, t["text"][:90], flush=True)
def m(k): return float(np.nanmean([r[k] for r in rows]))
summ = {k: round(m(k), 4) for k in ("A", "B", "C", "D", "entry_fixed", "entry_with_exit", "exit_on_entries")}
summ["fee_doubled"] = G.FEE; summ["fee_real"] = G.FEE_RT; summ["genomes"] = len(rows)
json.dump({"summary": summ, "rows": rows}, open(os.path.join(OUT, "diag.json"), "w"), ensure_ascii=False)
print("SUMMARY", json.dumps(summ))
