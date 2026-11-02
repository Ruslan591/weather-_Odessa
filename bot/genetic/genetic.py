# -*- coding: utf-8 -*-
"""Генетический поиск стратегий (прототип, 1h/4h). Результаты -> results.json (страница: index.html, порт 18096).
Фитнес: только отрезки вперёд (K блоков по времени в зоне поиска), издержки x2, нижняя граница среднего по худшему блоку
(без верхних 5% сделок), штраф за сложность. Отложено: последние 30% времени и пары, которых поиск не видел.
Тест поисковика: тот же поиск на данных с перемешанными барами (случайное блуждание) - он не должен находить 'стратегии'.
Запуск: python genetic.py   (env: GEN_CACHE, GEN_OUT, GEN_POP, GEN_GENS, GEN_NOISE, GEN_WORKERS, GEN_UNSEEN)"""
import os, sys, re, json, time, glob, pickle, math, random
import numpy as np, pandas as pd

CACHE = os.environ.get("GEN_CACHE", "/opt/trading-bot/wfscan/cache")
OUT = os.environ.get("GEN_OUT", "/opt/trading-bot/genetic")
POP = int(os.environ.get("GEN_POP", "150")); GENS = int(os.environ.get("GEN_GENS", "30"))
NOISE_N = int(os.environ.get("GEN_NOISE", "3")); WORKERS = int(os.environ.get("GEN_WORKERS", "2"))
UNSEEN = os.environ.get("GEN_UNSEEN", "XRPUSDT,DOGEUSDT,ZECUSDT,TREEUSDT,KORUBUSDT,NILUSDT").split(",")
TFS = ["1h", "4h"]
FEE_RT = 0.10; FEE_MULT = 2.0; FEE = FEE_RT * FEE_MULT       # % за круг; в фитнесе издержки удвоены (комиссия + проскальзывание)
K_BLOCKS = 4; TRAIN_FRAC = 0.7; WARM = 300; TRIM_TOP = 0.05
MIN_BLOCK_N = 20; MIN_VALID_BLOCKS = 3; MIN_TOTAL = 80; PEN = 0.01
TOPN = 30; MIN_HO_N = 40; MIN_UN_N = 40

GRID = {
    "tf": TFS, "side": ["L", "S", "B"],
    "trig": ["ema", "macd", "rsi", "donch", "bb"], "tm": [0, 1],
    "ef": [5, 8, 10, 13, 20, 30], "es": [20, 30, 50, 80, 120, 200],
    "mf": [8, 12, 16], "ms": [21, 26, 35], "msg": [7, 9],
    "rn": [7, 14, 21], "rl": [20, 25, 30, 35],
    "dn": [10, 20, 40, 80, 120],
    "bn": [14, 20, 40], "bk": [1.5, 2.0, 2.5, 3.0],
    "reg": ["none", "sma", "atrp"], "rd": [0, 1], "rs": [50, 100, 200],
    "ra": [[0.0, 0.8], [0.5, 1.0], [0.8, 1.5], [1.0, 3.0]],
    "conf": ["none", "vol", "candle", "rsi50"], "cv": [1.0, 1.5, 2.0],
    "hold": [6, 12, 24, 48], "sl": [0, 1.0, 1.5, 2.0, 3.0], "tp": [0, 1.5, 2.0, 3.0, 5.0],
}
KEYS = list(GRID)

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

# ---------- данные ----------
class Ser:
    def __init__(self, sym, tf, d):
        self.sym, self.tf = sym, tf
        self.t = d.t.values.astype("int64"); self.o = d.o.values.astype(float); self.h = d.h.values.astype(float)
        self.l = d.l.values.astype(float); self.c = d.c.values.astype(float); self.v = d.v.values.astype(float)
        self.n = len(d); self.tfms = int(np.median(np.diff(self.t))); self.cache = {}
        pc = np.r_[self.c[0], self.c[:-1]]
        tr = np.maximum(self.h - self.l, np.maximum(abs(self.h - pc), abs(self.l - pc)))
        self.atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values

def load_df(sym, tf):
    fs = sorted(glob.glob(os.path.join(CACHE, "*_%s_%s.pkl" % (sym, tf))))
    if not fs: return None
    d = pickle.load(open(fs[-1], "rb")).sort_values("t").reset_index(drop=True)
    return d if len(d) > WARM + 200 else None

def shuffled(d, seed):
    """Случайное блуждание: перемешать бары (отношения o,h,l,c к прошлому закрытию и объём); время и длина те же."""
    rng = np.random.default_rng(seed)
    o, h, l, c, v = (d[k].values.astype(float) for k in "ohlcv")
    pc = np.r_[c[0], c[:-1]]
    idx = np.r_[0, rng.permutation(len(d) - 1) + 1]
    ro, rh, rl, rc = (x[idx] / pc[idx] for x in (o, h, l, c))
    ro[0] = rh[0] = rl[0] = rc[0] = 1.0
    c2 = c[0] * np.cumprod(rc); pc2 = np.r_[c2[0], c2[:-1]]
    e = d.copy(); e["o"] = pc2 * ro; e["h"] = pc2 * rh; e["l"] = pc2 * rl; e["c"] = c2; e["v"] = v[idx]
    e.loc[0, ["o", "h", "l"]] = [c[0], c[0], c[0]]
    return e

def build_data(noise_seed=None):
    syms = sorted(set(re.findall(r"_([A-Z0-9]+USDT)_", " ".join(os.listdir(CACHE)))))
    data = {tf: {"search": [], "unseen": []} for tf in TFS}
    for tf in TFS:
        for i, sym in enumerate(syms):
            d = load_df(sym, tf)
            if d is None: continue
            if noise_seed is not None: d = shuffled(d, noise_seed * 1000 + i)
            data[tf]["unseen" if sym in UNSEEN else "search"].append(Ser(sym, tf, d))
    return data, syms

def zone(data):
    """Границы: T0 - начало, CUT - начало отложенного отрезка (последние 30% времени), по каждому ТФ."""
    z = {}
    for tf in TFS:
        ss = data[tf]["search"]
        t0 = min(s.t[0] for s in ss); t1 = max(s.t[-1] for s in ss)
        z[tf] = (int(t0), int(t0 + TRAIN_FRAC * (t1 - t0)), int(t1))
    return z

# ---------- индикаторы и сигналы ----------
def ind(s, key, fn):
    r = s.cache.get(key)
    if r is None: r = s.cache[key] = fn()
    return r
def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values
def sma(x, n): return pd.Series(x).rolling(n).mean().values
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))
def cross_up(x, lvl):
    r = np.zeros(len(x), bool); r[1:] = (x[:-1] <= (lvl[:-1] if hasattr(lvl, "__len__") else lvl)) & (x[1:] > (lvl[1:] if hasattr(lvl, "__len__") else lvl)); return r
def cross_dn(x, lvl):
    r = np.zeros(len(x), bool); r[1:] = (x[:-1] >= (lvl[:-1] if hasattr(lvl, "__len__") else lvl)) & (x[1:] < (lvl[1:] if hasattr(lvl, "__len__") else lvl)); return r

def fix(g):
    if g["ef"] > g["es"]: g["ef"], g["es"] = g["es"], g["ef"]
    elif g["ef"] == g["es"]: g["es"] = g["ef"] * 2
    return g

def active(g):
    """Только действующие гены (для ключа кэша и счёта проверенных вариантов)."""
    a = {"tf": g["tf"], "side": g["side"], "trig": g["trig"], "tm": g["tm"], "hold": g["hold"], "sl": g["sl"], "tp": g["tp"], "reg": g["reg"], "conf": g["conf"]}
    t = g["trig"]
    if t == "ema": a.update(ef=g["ef"], es=g["es"])
    elif t == "macd": a.update(mf=g["mf"], ms=g["ms"], msg=g["msg"])
    elif t == "rsi": a.update(rn=g["rn"], rl=g["rl"])
    elif t == "donch": a.update(dn=g["dn"])
    elif t == "bb": a.update(bn=g["bn"], bk=g["bk"])
    if g["reg"] == "sma": a.update(rd=g["rd"], rs=g["rs"])
    elif g["reg"] == "atrp": a.update(ra=tuple(g["ra"]))
    if g["conf"] == "vol": a.update(cv=g["cv"])
    return a
def gkey(g): return json.dumps(active(g), sort_keys=True)
def ncomp(g): return (g["reg"] != "none") + (g["conf"] != "none") + (g["sl"] > 0) + (g["tp"] > 0)

def signals(s, g):
    c, n, t = s.c, s.n, g["trig"]
    if t == "ema":
        d = ind(s, ("ema", g["ef"]), lambda: ema(s.c, g["ef"])) - ind(s, ("ema", g["es"]), lambda: ema(s.c, g["es"]))
        L, S = cross_up(d, 0.0), cross_dn(d, 0.0)
        if g["tm"]: L, S = S, L
    elif t == "macd":
        k = ("macd", g["mf"], g["ms"], g["msg"])
        def mk():
            m = ema(s.c, g["mf"]) - ema(s.c, g["ms"]); return m - ema(m, g["msg"])
        d = ind(s, k, mk); L, S = cross_up(d, 0.0), cross_dn(d, 0.0)
        if g["tm"]: L, S = S, L
    elif t == "rsi":
        r = ind(s, ("rsi", g["rn"]), lambda: rsi(s.c, g["rn"])); lo, hi = g["rl"], 100 - g["rl"]
        if g["tm"] == 0: L, S = cross_up(r, lo), cross_dn(r, hi)      # возврат: из перепроданности вверх / из перекупленности вниз
        else: L, S = cross_up(r, hi), cross_dn(r, lo)                  # импульс
    elif t == "donch":
        hh = ind(s, ("hh", g["dn"]), lambda: pd.Series(s.h).rolling(g["dn"]).max().shift(1).values)
        ll = ind(s, ("ll", g["dn"]), lambda: pd.Series(s.l).rolling(g["dn"]).min().shift(1).values)
        L = np.zeros(n, bool); S = np.zeros(n, bool)
        up = c > hh; dn = c < ll
        L[1:] = up[1:] & ~up[:-1]; S[1:] = dn[1:] & ~dn[:-1]
        if g["tm"]: L, S = S, L
    else:  # bb
        mu = ind(s, ("bm", g["bn"]), lambda: sma(s.c, g["bn"])); sd = ind(s, ("bs", g["bn"]), lambda: pd.Series(s.c).rolling(g["bn"]).std().values)
        lw, up_ = mu - g["bk"] * sd, mu + g["bk"] * sd
        if g["tm"] == 0: L, S = cross_up(c, lw), cross_dn(c, up_)      # возврат внутрь полос
        else: L, S = cross_up(c, up_), cross_dn(c, lw)                  # пробой полос
    L = np.nan_to_num(L).astype(bool); S = np.nan_to_num(S).astype(bool)
    if g["side"] == "L": S = np.zeros(n, bool)
    elif g["side"] == "S": L = np.zeros(n, bool)
    if g["reg"] == "sma":
        m = ind(s, ("sma", g["rs"]), lambda: sma(s.c, g["rs"]))
        above = c > m; below = c < m
        if g["rd"]: L &= above; S &= below
        else: L &= below; S &= above
    elif g["reg"] == "atrp":
        ra = tuple(g["ra"]); rr = ind(s, ("atrr",), lambda: s.atr / np.maximum(sma(s.atr, 100), 1e-12))
        mk = (rr >= ra[0]) & (rr <= ra[1]); L &= mk; S &= mk
    if g["conf"] == "vol":
        vm = ind(s, ("vm",), lambda: sma(s.v, 20)); mk = s.v > g["cv"] * vm; L &= mk; S &= mk
    elif g["conf"] == "candle": L &= s.c > s.o; S &= s.c < s.o
    elif g["conf"] == "rsi50":
        r = ind(s, ("rsi", 14), lambda: rsi(s.c, 14)); L &= r > 50; S &= r < 50
    L[:WARM] = False; S[:WARM] = False; L[-2:] = False; S[-2:] = False
    return L, S

def run(s, g):
    """Сделки по геному на серии: (чистая доходность % после издержек, время входа мс). Вход по открытию следующей свечи."""
    L, S = signals(s, g)
    li = np.flatnonzero(L); si = np.flatnonzero(S)
    if len(li) + len(si) == 0: return np.empty(0), np.empty(0, "int64")
    idx = np.r_[li, si]; sg = np.r_[np.ones(len(li)), -np.ones(len(si))]
    od = np.argsort(idx, kind="stable"); idx, sg = idx[od], sg[od]
    H = g["hold"]; keep = []; last = -10 ** 9
    for k, i in enumerate(idx):
        if i - last >= H: keep.append(k); last = i
    idx, sg = idx[keep], sg[keep]
    e = idx + 1; ok = e + H - 1 <= s.n - 1
    idx, sg, e = idx[ok], sg[ok], e[ok]
    if len(e) == 0: return np.empty(0), np.empty(0, "int64")
    ep = s.o[e]; a = s.atr[idx]; act = np.ones(len(e), bool); xp = np.empty(len(e))
    slp = ep - sg * g["sl"] * a if g["sl"] > 0 else None
    tpp = ep + sg * g["tp"] * a if g["tp"] > 0 else None
    for k in range(H):
        b = e + k; hb = s.h[b]; lb = s.l[b]
        if slp is not None:
            hit = act & np.where(sg > 0, lb <= slp, hb >= slp)
            if hit.any():
                ob = s.o[b]; xp[hit] = np.where(sg > 0, np.minimum(slp, ob), np.maximum(slp, ob))[hit]; act &= ~hit
        if tpp is not None:
            hit = act & np.where(sg > 0, hb >= tpp, lb <= tpp)
            if hit.any(): xp[hit] = tpp[hit]; act &= ~hit
        if k == H - 1: xp[act] = s.c[b][act]
        elif not act.any(): break
    return sg * (xp / ep - 1) * 100 - FEE, s.t[e]

def tstats(x):
    n = len(x)
    if n == 0: return {"n": 0, "tm": 0.0, "lcb": -9.0, "mean": 0.0, "med": 0.0, "win": 0.0}
    xs = np.sort(x); k = int(n * TRIM_TOP); xt = xs[:n - k] if k > 0 else xs
    tm = float(xt.mean()); sd = float(xt.std(ddof=1)) if len(xt) > 1 else 1.0
    return {"n": int(n), "tm": tm, "lcb": tm - sd / math.sqrt(len(xt)), "mean": float(x.mean()), "med": float(np.median(x)), "win": float((x > 0).mean())}

# ---------- оценка ----------
DATA = None; ZONE = None
def eval_search(g):
    tf = g["tf"]; t0, cut, _ = ZONE[tf]; xs = []; ts = []
    for s in DATA[tf]["search"]:
        x, t = run(s, g)
        if len(x):
            m = t < cut - g["hold"] * s.tfms; xs.append(x[m]); ts.append(t[m])
    x = np.concatenate(xs) if xs else np.empty(0); t = np.concatenate(ts) if ts else np.empty(0, "int64")
    b = np.clip(((t - t0) / (cut - t0) * K_BLOCKS).astype(int), 0, K_BLOCKS - 1) if len(t) else np.empty(0, int)
    blocks = [tstats(x[b == k]) for k in range(K_BLOCKS)]
    valid = [q for q in blocks if q["n"] >= MIN_BLOCK_N]; tot = len(x)
    if len(valid) < MIN_VALID_BLOCKS or tot < MIN_TOTAL:
        return -5.0 + min(tot, MIN_TOTAL) / MIN_TOTAL, blocks
    med = float(np.median(x))
    return min(q["lcb"] for q in valid) - PEN * ncomp(g) - max(0.0, -med) * 0.5, blocks

def eval_fit(g): return eval_search(g)[0]

def pool_stats(g, group, mode):
    """mode 'ho': отложенное время на парах поиска; 'un': все данные на невиданных парах."""
    tf = g["tf"]; t0, cut, _ = ZONE[tf]; xs = []; per = []
    for s in DATA[tf][group]:
        x, t = run(s, g)
        if mode == "ho": x = x[t >= cut]
        if len(x): xs.append(x)
        if len(x) >= 5: per.append(float(tstats(x)["tm"] > 0))
    x = np.concatenate(xs) if xs else np.empty(0); st = tstats(x)
    st["pos"] = round(float(np.mean(per)), 2) if per else None; st["pairs"] = len(per)
    return st

def detail(g):
    fit, blocks = eval_search(g)
    ho = pool_stats(g, "search", "ho"); un = pool_stats(g, "unseen", "un")
    ok = bool(ho["n"] >= MIN_HO_N and ho["tm"] > 0 and un["n"] >= MIN_UN_N and un["tm"] > 0 and (un["pos"] or 0) >= 0.5)
    return {"fit": fit, "blocks": blocks, "ho": ho, "un": un, "pass": ok, "med_ok": bool(ok and ho["med"] > 0 and un["med"] > 0)}

def text(g):
    a = active(g); t = a["trig"]
    side = {"L": "лонг", "S": "шорт", "B": "лонг+шорт"}[a["side"]]
    tm = a["tm"]
    tr = {"ema": "EMA %s/%s%s" % (a.get("ef"), a.get("es"), " (против)" if tm else ""),
          "macd": "MACD %s/%s/%s%s" % (a.get("mf"), a.get("ms"), a.get("msg"), " (против)" if tm else ""),
          "rsi": "RSI%s %s, ур.%s" % (a.get("rn"), "импульс" if tm else "возврат", a.get("rl")),
          "donch": "Дончиан %s%s" % (a.get("dn"), " (против)" if tm else ""),
          "bb": "Боллинджер %s/%s %s" % (a.get("bn"), a.get("bk"), "пробой" if tm else "возврат")}[t]
    reg = {"none": "", "sma": "; режим: цена %s SMA%s" % ("по тренду от" if a.get("rd") else "против тренда от", a.get("rs")),
           "atrp": "; режим: ATR/SMA(ATR,100) в %s" % (a.get("ra"),)}[a["reg"]]
    cf = {"none": "", "vol": "; объём>%sx" % a.get("cv"), "candle": "; свеча по направлению", "rsi50": "; RSI14 по стороне 50"}[a["conf"]]
    ex = "; выход: %d св." % a["hold"] + (", SL %sATR" % a["sl"] if a["sl"] else "") + (", TP %sATR" % a["tp"] if a["tp"] else "")
    return "%s | %s | %s%s%s%s" % (a["tf"], side, tr, reg, cf, ex)

# ---------- генетика ----------
def rand_genome(rng):
    g = {k: rng.choice(GRID[k]) for k in KEYS}
    return fix(g)
def crossover(a, b, rng): return fix({k: (a if rng.random() < 0.5 else b)[k] for k in KEYS})
def mutate(g, rng, pm=0.15):
    g = dict(g)
    for k in KEYS:
        if rng.random() < pm: g[k] = rng.choice(GRID[k])
    return fix(g)
def tournament(pop, fit, rng, k=3):
    c = rng.sample(range(len(pop)), k); return pop[max(c, key=lambda i: fit[i])]

def _eval_task(g): return eval_fit(g)

def run_ga(name, seed, res, save):
    global DATA, ZONE
    rng = random.Random(seed); store = {}; hist = []
    pool = None
    if WORKERS > 1:
        import multiprocessing as mp
        pool = mp.get_context("fork").Pool(WORKERS)
    def evaluate(gs):
        new = {}
        for g in gs:
            k = gkey(g)
            if k not in store and k not in new: new[k] = g
        ks = list(new)
        out = pool.map(_eval_task, [new[k] for k in ks], chunksize=4) if pool else [eval_fit(new[k]) for k in ks]
        for k, f in zip(ks, out): store[k] = (f, new[k])
        return [store[gkey(g)][0] for g in gs]
    pop = [rand_genome(rng) for _ in range(POP)]; t0 = time.time()
    for gen in range(GENS):
        fit = evaluate(pop)
        order = sorted(range(len(pop)), key=lambda i: -fit[i])
        hist.append({"g": gen, "best": round(max(fit), 4), "mean": round(float(np.mean(fit)), 3), "evals": len(store), "sec": round(time.time() - t0)})
        res["runs"][name] = {"status": "search", "hist": hist, "evals": len(store), "seed": seed}
        save(); log(name, "gen", gen, "best", hist[-1]["best"], "evals", len(store))
        elite = [pop[i] for i in order[:6]]
        nxt = list(elite) + [rand_genome(rng) for _ in range(POP // 10)]
        while len(nxt) < POP:
            nxt.append(mutate(crossover(tournament(pop, fit, rng), tournament(pop, fit, rng), rng), rng))
        pop = nxt
    if pool: pool.close(); pool.join()
    ranked = []; seen = set()
    for f, g in sorted(store.values(), key=lambda fg: -fg[0]):
        a = active(g); sig = json.dumps({k: a[k] for k in a if k in ("tf", "side", "trig", "tm", "ef", "es", "mf", "ms", "msg", "rn", "rl", "dn", "bn", "bk")}, sort_keys=True)
        if sig in seen: continue
        seen.add(sig); ranked.append((f, g))
        if len(ranked) >= TOPN: break
    top = []
    for f, g in ranked:
        d = detail(g); d["genome"] = active(g); d["text"] = text(g); top.append(d)
    res["runs"][name] = {"status": "done", "hist": hist, "evals": len(store), "seed": seed, "top": top,
                         "npass": sum(t["pass"] for t in top), "npass_med": sum(t["med_ok"] for t in top),
                         "best_fit": max(t["fit"] for t in top) if top else None}
    save()

def main():
    os.makedirs(OUT, exist_ok=True)
    real, syms = build_data()
    z0 = zone(real)
    res = {"meta": {"started": int(time.time()), "status": "running", "pop": POP, "gens": GENS, "noise_runs": NOISE_N, "workers": WORKERS,
                    "tfs": TFS, "unseen_pairs": UNSEEN, "pairs": syms, "fee_round_pct_used": FEE, "k_blocks": K_BLOCKS, "train_frac": TRAIN_FRAC,
                    "series": {tf: {"search": len(real[tf]["search"]), "unseen": len(real[tf]["unseen"])} for tf in TFS},
                    "zone": {tf: {"t0": z0[tf][0], "cut": z0[tf][1], "t1": z0[tf][2]} for tf in TFS}},
           "runs": {}, "verdict": None}
    def save():
        tmp = os.path.join(OUT, "results.json.tmp")
        json.dump(res, open(tmp, "w"), ensure_ascii=False); os.replace(tmp, os.path.join(OUT, "results.json"))
    global DATA, ZONE
    DATA, ZONE = real, z0
    log("pairs", syms, "series", res["meta"]["series"])
    run_ga("real", 1, res, save)
    for i in range(1, NOISE_N + 1):
        DATA, _ = build_data(noise_seed=i); ZONE = zone(DATA)
        run_ga("noise%d" % i, 100 + i, res, save)
    r = res["runs"]["real"]; ns = [res["runs"]["noise%d" % i] for i in range(1, NOISE_N + 1)]
    nb = [n["best_fit"] for n in ns]; npass = [n["npass"] for n in ns]
    beats = bool(r["best_fit"] is not None and nb and r["best_fit"] > max(nb))
    res["verdict"] = {"real_best_fit": r["best_fit"], "noise_best_fit": nb, "real_npass": r["npass"], "noise_npass": npass,
                      "real_npass_med": r["npass_med"], "real_beats_noise": beats,
                      "signal": bool(beats and r["npass"] > max(npass or [0])),
                      "evals_real": r["evals"], "evals_noise": [n["evals"] for n in ns]}
    res["meta"]["status"] = "done"; res["meta"]["finished"] = int(time.time()); save()
    log("ALL DONE", json.dumps(res["verdict"], ensure_ascii=False))

if __name__ == "__main__":
    main()
