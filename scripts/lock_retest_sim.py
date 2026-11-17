# -*- coding: utf-8 -*-
"""Lock-BE variants and breakout retest entry, replayed with the REAL pos.step engine on closed trades of the account regr (2026-11-18).
Output is ASCII only (the VPS bridge strips non-ASCII). Run on VPS: mkdir /tmp/lrs; copy pos.py exit_cfg.py decisions.py trade_mgr.py here; python3 lock_retest_sim.py
Part A: all closed trades, exit settings variants (lock in % vs R, BE trigger). Not modelled: S/R stop move (sr_stop), manual actions.
Part B: breakout trades (setup=breakout, has channel line): enter not at market but after a retest: within 6 closed 5m candles after the signal,
  first candle that touches the line (low <= line + 0.3 ATR for long) and closes beyond the line in trade direction (green for long) -> enter at its close,
  stop = extreme of retest candles - 0.25 ATR, target = order target (tp_manual), skip if R:R < 1.3; cancel if a candle closes back across the line first."""
import copy, json, os, sys, time, urllib.request, statistics as st
os.environ["POS_DIR"] = "/tmp/lrs_pos"; os.makedirs("/tmp/lrs_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg
REAL = "/opt/trading-bot/positions_regr"
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(REAL + "/orders.json", encoding="utf-8"))}
CFG0 = exit_cfg._merge(json.load(open(REAL + "/exit_cfg.json")))
_cc = {}


def candles(sym, start, end):
    key = (sym, start // 3600000, end // 3600000)
    if key in _cc: return _cc[key]
    out = []; t = start
    while t < end and len(out) < 3000:
        u = "%s?symbol=%s&interval=1m&limit=1000&startTime=%d" % (pos.BASE, sym, t)
        d = None
        for _try in range(3):
            try: d = json.load(urllib.request.urlopen(u, timeout=20)); break
            except Exception: time.sleep(1.5)
        if not d: break
        out += d; t = int(d[-1][0]) + 60000
        if len(d) < 1000: break
    time.sleep(0.1); r = [k for k in out if int(k[0]) <= end]; _cc[key] = r; return r


def mkbase(p, entry, stop, t_in, tp_manual=None):
    sd = 1 if p["side"] == "long" else -1
    b = {k: copy.deepcopy(p[k]) for k in ("id", "sym", "side", "max_h", "stake", "lev", "thesis", "rule", "fee_in", "fee_tp", "src", "order_id", "atr1h", "xr") if k in p}
    R = abs(entry - stop)
    b.update(t_in=t_in, entry=entry, stop0=stop, stop=stop, R=R, R_pct=R / entry * 100, tp=entry + sd * 2 * R, armed=False, hi=entry, lo=entry, status="open",
             last_t=(t_in // 60000) * 60000 - 60000, trail_dist=1.5 * (p.get("atr1h") or 0), be_px=entry + sd * R, lock_px=entry)
    if tp_manual: b["tp_manual"] = tp_manual
    return b


def play(base, ks, cfg):
    exit_cfg._cache[0] = None; exit_cfg._cache[1] = cfg
    p = copy.deepcopy(base)
    for k in ks:
        if int(k[0]) <= p["last_t"]: continue
        pos.step(p, k); p["last_t"] = int(k[0])
        if p["status"] != "open": break
    return p


def cfgv(be_val=None, lock_unit=None, lock_val=None, trail_val=None):
    c = copy.deepcopy(CFG0)
    if be_val is not None: c["be"]["val"] = be_val
    if lock_unit: c["be"]["lock_unit"] = lock_unit; c["be"]["lock_val"] = lock_val
    if trail_val is not None: c["trail"]["val"] = trail_val
    return c


trades = []
for p in snap["closed"]:
    if not p.get("t_in") or not p.get("t_out") or p.get("entry") is None: continue
    t_in = p["t_in"]
    ks = candles(p["sym"], (t_in // 60000) * 60000, min(p["t_out"] + 3600000 * 6, int(time.time() * 1000)))
    if ks: trades.append((p, orders.get(p.get("order_id")) or {}, ks))
    if len(trades) % 25 == 0: print("loaded", len(trades), flush=True)
print("closed trades with paths: %d of %d" % (len(trades), len(snap["closed"])), flush=True)
ids = sorted(p["id"] for p, _, _ in trades); half = ids[len(ids) // 2]

V = [("OLD  current cfg (BE 1R, lock %.2f%%)" % CFG0["be"]["lock_val"], cfgv()),
     ("A1   lock 0.2 pct", cfgv(lock_unit="pct", lock_val=0.2)),
     ("A2   lock 0.15 R", cfgv(lock_unit="r", lock_val=0.15)),
     ("A3   lock 0.2 R", cfgv(lock_unit="r", lock_val=0.2)),
     ("A4   lock 0.3 R", cfgv(lock_unit="r", lock_val=0.3)),
     ("A5   BE at 1.3R, lock 0.3 R", cfgv(be_val=1.3, lock_unit="r", lock_val=0.3)),
     ("A6   BE at 1.3R, lock 0.5 R", cfgv(be_val=1.3, lock_unit="r", lock_val=0.5)),
     ("A7   lock 0.2 R, trail 2.0 ATR", cfgv(lock_unit="r", lock_val=0.2, trail_val=2.0))]
print("\nPART A: exit variants, all closed trades (replayed from stop0 with real engine)")
act = {p["id"]: (p.get("r_mult") or 0) for p, _, _ in trades}
print("actual total %+.1f R" % sum(act.values()))
print("%-44s %8s %8s %8s %6s" % ("variant", "sumR", "half1", "half2", "stop%"))
for name, cfg in V:
    rs = []
    for p, o, ks in trades:
        b = mkbase(p, p["entry"], p["stop0"], p["t_in"]); b["tp"] = p.get("tp") or b["tp"]
        if p.get("xr"): b["xr"] = p["xr"]
        q = play(b, ks, cfg); rs.append((p["id"], q.get("r_mult") if q["status"] == "closed" else 0.0, q.get("reason")))
    a = sum(r for i, r, _ in rs if i < half); c = sum(r for i, r, _ in rs if i >= half)
    print("%-44s %+8.1f %+8.1f %+8.1f %5.0f%%" % (name, a + c, a, c, 100 * sum(1 for _, _, w in rs if w == "stop") / len(rs)), flush=True)


def line_at(o, t):
    ln = o["chan"]["upper" if o.get("line") == "upper" else "lower"]
    return ln["p1"] + ln["s"] * (t - ln["t1"])


def agg5(ks, t0, n):
    out = []
    for i in range(n):
        s = t0 + i * 300000; g = [k for k in ks if s <= int(k[0]) < s + 300000]
        if len(g) < 5: break
        out.append((s, float(g[0][1]), max(float(k[2]) for k in g), min(float(k[3]) for k in g), float(g[-1][4])))
    return out


print("\nPART B: breakout trades, retest entry vs actual (exit cfg = current, target = order target)")
rows = []
for p, o, ks in trades:
    if o.get("setup") != "breakout" or not o.get("chan") or o.get("line") not in ("upper", "lower") or not o.get("checked_t") or not o.get("tp"): continue
    sd = 1 if p["side"] == "long" else -1; atr = o.get("atr") or 0
    if not atr: continue
    t0 = int(o["checked_t"]); res = None; ext = None
    for (s, op, h, l, c) in agg5(ks, t0, 6):
        ln = line_at(o, s + 300000)
        ext = (l if ext is None else min(ext, l)) if sd > 0 else (h if ext is None else max(ext, h))
        beyond = (c > ln) if sd > 0 else (c < ln)
        touched = (l <= ln + 0.3 * atr) if sd > 0 else (h >= ln - 0.3 * atr)
        if not beyond: res = "cancel"; break
        if touched and ((c > op) if sd > 0 else (c < op)):
            ent = c; stp = ext - sd * 0.25 * atr; tp = o["tp"]
            if (tp - ent) * sd <= 0 or (stp - ent) * sd >= 0: res = "skip_geom"; break
            rr = abs(tp - ent) / abs(ent - stp)
            if rr < 1.3: res = "skip_rr"; break
            res = (ent, stp, s + 300000); break
    r_act = p.get("r_mult") or 0
    if isinstance(res, tuple):
        b = mkbase(p, res[0], res[1], res[2], tp_manual=o["tp"]); q = play(b, [k for k in ks if int(k[0]) >= res[2]], CFG0)
        r_new = q.get("r_mult") if q["status"] == "closed" else 0.0; rows.append((p["id"], r_act, r_new, "enter", q.get("reason")))
    else: rows.append((p["id"], r_act, 0.0, res or "no_retest", None))
n = len(rows); print("breakout trades: %d" % n)
for tag in ("enter", "no_retest", "cancel", "skip_rr", "skip_geom"):
    g = [r for r in rows if r[3] == tag]
    if g: print("%-10s n=%3d  actual sum %+6.1f R  variant sum %+6.1f R" % (tag, len(g), sum(r[1] for r in g), sum(r[2] for r in g)))
print("TOTAL actual %+.1f R  retest variant %+.1f R   (half1 %+.1f vs %+.1f, half2 %+.1f vs %+.1f)" % (
    sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[1] for r in rows if r[0] < half), sum(r[2] for r in rows if r[0] < half),
    sum(r[1] for r in rows if r[0] >= half), sum(r[2] for r in rows if r[0] >= half)))
en = [r for r in rows if r[3] == "enter"]
if en: print("entered: win rate actual %.0f%% variant %.0f%%" % (100 * sum(1 for r in en if r[1] > 0) / len(en), 100 * sum(1 for r in en if r[2] > 0) / len(en)))
for r in rows:
    if r[0] == 463: print("trade 463:", r)
print("DONE")
