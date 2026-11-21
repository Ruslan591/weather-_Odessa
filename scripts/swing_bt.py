# -*- coding: utf-8 -*-
"""Бэктест правила swing_stop на закрытых позициях: тени (shadow.json) и позиции счёта regr (positions.json). Запуск на VPS: POS_DIR=/opt/trading-bot/positions_regr SHADOW_CODE_DIR=/opt/trading-bot/positions python swing_bt.py [grid|base]
Позиция собирается заново из записи (стоп = stop0, флаги сброшены), прогоняется боевым pos.step по 1m свечам без и с правилом. S/R-стоп (sr_stop) и ручные действия не воспроизводятся."""
import sys, os, json, copy, time, itertools
sys.path.insert(0, os.environ.get("SHADOW_CODE_DIR", "/opt/trading-bot/positions")); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PR = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
import pos, decisions, swing_stop
decisions.auto = lambda *a, **k: None
RESET = ("t_out", "exit", "reason", "net_pct", "r_mult", "pnl_usd", "mfe_pct", "mae_pct", "armed_t", "tp1_done", "tp1_t", "be2_done", "be2_t", "trail_act", "trail_t", "sr_hist", "mgr", "base", "mgr_hist", "mgr_off", "stop_manual", "sw_c", "sw_hist", "manual_trail", "parts")
KL = {}

def fresh(q):
    p = copy.deepcopy(q)
    for k in RESET: p.pop(k, None)
    p.update(status="open", stop=p["stop0"], armed=False, rem=1.0, hi=p["entry"], lo=p["entry"], last_t=(int(p["t_in"]) // 60000) * 60000)
    return p

def klines(q):
    key = (q["sym"], int(q["t_in"]), int(q.get("t_out") or 0))
    if key in KL: return KL[key]
    out = []; st = (int(q["t_in"]) // 60000) * 60000; end = int(q.get("t_out") or 0) + 3600000
    while st < end:
        try: d = pos.kl(q["sym"], "1m", 1000, st)
        except Exception as e: print("kl err", q["sym"], e); break
        if not d: break
        out += d; st = int(d[-1][0]) + 60000
        if len(d) < 1000: break
    KL[key] = out; return out

def run(q, sw, cfg=None):
    p = fresh(q); side = 1 if p["side"] == "long" else -1
    if sw: p["sw"] = 1
    swing_stop.OVERRIDE.clear(); swing_stop.OVERRIDE.update(cfg or {})
    for k in klines(q):
        if int(k[0]) < p["last_t"] + 60000 and int(k[0]) != p["last_t"]: pass
        if int(k[0]) <= p["last_t"] - 60000: continue
        pos.step(p, k); p["last_t"] = int(k[0])
        if p["status"] != "open": break
    return p

def load_items():
    out = []
    try:
        S = json.load(open(PR + "/shadow.json"))
        for it in S["items"]:
            p = it.get("p")
            if p and p.get("status") == "closed" and p.get("stop0"): q = dict(p); q["_src"] = "sh%s%s" % (it["id"], it.get("var") or ""); out.append(q)
    except Exception as e: print("shadow", e)
    try:
        P = json.load(open(PR + "/positions.json"))
        for p in P:
            if p.get("status") == "closed" and p.get("stop0") and p.get("R") and p.get("t_out") and p.get("t_in"): q = dict(p); q["_src"] = "re%s" % p.get("id"); out.append(q)
    except Exception as e: print("positions", e)
    return out

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "grid"
    items = load_items(); print("items", len(items), flush=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex: list(ex.map(lambda q: klines(q), items))      # свечи грузим параллельно (сеть медленная)
    print("klines loaded", len(KL), flush=True)
    base = {}; t0 = time.time()
    for q in items:
        try: r = run(q, False); base[q["_src"]] = r.get("r_mult") if r["status"] == "closed" else None
        except Exception as e: print("err", q["_src"], repr(e)[:80]); base[q["_src"]] = None
    ok = [q for q in items if base.get(q["_src"]) is not None]
    rec = sum(q.get("r_mult") or 0 for q in ok); rb = sum(base[q["_src"]] for q in ok)
    print("base replay n=%d sum_recorded=%.2f sum_replay=%.2f (%.0fs)" % (len(ok), rec, rb, time.time() - t0), flush=True)
    if mode == "base": sys.exit(0)
    grid = [dict(sw_k=k, m=m, min_mfe=mf, min_body=b, min_gap_r=g) for k in (1, 2, 3) for m in (1, 3) for mf in (0.0, 0.3, 0.6) for b in (0.0, 0.4) for g in (0.1, 0.25)]
    res = []
    for cfg in grid:
        tot = 0; better = worse = n_ch = 0
        for q in ok:
            r = run(q, True, cfg); x = r.get("r_mult") if r["status"] == "closed" else None
            if x is None: x = base[q["_src"]]
            d = x - base[q["_src"]]; tot += d
            if abs(d) > 0.01: n_ch += 1; better += d > 0; worse += d < 0
        res.append((tot, cfg, n_ch, better, worse))
        print("d=%+.2f changed=%d better=%d worse=%d %s" % (tot, n_ch, better, worse, json.dumps(cfg)), flush=True)
    res.sort(key=lambda x: -x[0]); print("TOP"); [print("d=%+.2f ch=%d b=%d w=%d %s" % (a, c, d, e, json.dumps(b))) for a, b, c, d, e in res[:8]]
