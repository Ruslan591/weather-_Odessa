import json, os, time, datetime, collections
P = "/opt/trading-bot/positions_regr"
def L(n, d=None):
    for base in (P, "/opt/trading-bot/positions", "/opt/tg-notify"):
        p = os.path.join(base, n)
        if os.path.exists(p):
            try: return json.load(open(p))
            except Exception as e: print("ERR", p, e)
    return d
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M")
cfg = L("shadow_bal.json"); print("cfg", cfg)
tr = L("shadow_bal_trades.json", {}) or {}
sh = L("shadow.json", {}) or {}
items = sh.get("items") or []
print("trades saved", len(tr), "items", len(items))
t0 = int(cfg["t0"]); start = float(cfg["start"]); stake = float(cfg.get("stake", 6))
rows = []
for k, r in tr.items():
    rows.append(r)
rows.sort(key=lambda r: r["t_out"] or 0)
byid = {str(x.get("id")): x for x in items}
def feat(r):
    x = byid.get(r["id"]) or {}
    p = x.get("p") or {}; cf = x.get("cf") or {}
    src = p if r["k"] == "in" else cf
    return x, src
for line, sel in (("F with filters", lambda r: r["k"] == "in"), ("N no filter", lambda r: True)):
    print("=====", line)
    cum = 0; peak = 0
    for r in sorted([r for r in rows if sel(r)], key=lambda r: r["t_out"]):
        x, src = feat(r)
        pnl = stake * r["net_pct"] / 100
        cum += pnl; peak = max(peak, cum)
        rg = x.get("rg") or {}
        rgs = rg.get("regime") if isinstance(rg, dict) else rg
        print(r["id"], r["sn"], r["sym"], r["side"], r["tf"], r["k"], "in", ts(r["t_in"]), "out", ts(r["t_out"]),
              "dur_m", round((r["t_out"] - r["t_in"]) / 60000), "net", round(r["net_pct"], 2), "R", r["r"],
              "reason", src.get("reason"), "cum", round(cum, 3), "dd", round(cum - peak, 3), "rg", rgs, "kind", x.get("kind"))
print("===== open now")
for x in items:
    p = x.get("p") or {}
    if x.get("status") == "open" and p.get("t_in") and p["t_in"] >= t0:
        print(x.get("id"), x.get("sn"), x.get("sym"), x.get("side"), x.get("tf"), "in", ts(p["t_in"]), "age_h", round((time.time()*1000 - p["t_in"]) / 3600000, 1), "r", p.get("r_mult"), "netpct", p.get("net_pct"))
print("===== all keys of one closed item")
for x in items:
    if x.get("status") == "closed" and (x.get("p") or {}).get("t_in", 0) >= t0:
        print(sorted(x.keys())); print(sorted((x.get("p") or {}).keys())); print(json.dumps(x.get("rg"))[:300]); break
print("===== cfg shadow_cfg"); print(json.dumps(L("shadow_cfg.json")))
print("===== exit cfg"); print(json.dumps(L("exit_cfg.json"))[:800])
