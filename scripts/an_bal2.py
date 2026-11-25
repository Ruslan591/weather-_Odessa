import json, time, datetime, collections
P = "/opt/trading-bot/positions_regr/"
sh = json.load(open(P + "shadow.json")); items = sh["items"]
cfg = json.load(open(P + "shadow_bal.json")); t0 = cfg["t0"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M") if ms else "-"
print("items", len(items), "seq", sh.get("seq"))
c = collections.Counter(); rows = []
for x in items:
    p = x.get("p") or {}; cf = x.get("cf") or {}
    tsig = x.get("t_sig") or x.get("t0") or 0
    if tsig < t0 and (p.get("t_in") or 0) < t0: continue
    rg = x.get("rg") or {}
    c[(x.get("status"), x.get("var"))] += 1
    rows.append((tsig, x, p, cf, rg))
print(dict(c))
rows.sort(key=lambda r: r[0])
for tsig, x, p, cf, rg in rows:
    st = x.get("status")
    s = p if st in ("closed", "open") else cf
    why = ""
    if st == "filtered":
        why = str(x.get("chk") or x.get("g") or "")[:40].encode("ascii", "ignore").decode()
    print(x.get("sn"), x.get("var"), x.get("sym"), x.get("side"), x.get("tf"), (x.get("kind") or "")[:6], st, "sig", ts(tsig), "in", ts(s.get("t_in")), "out", ts(s.get("t_out")),
          "net", s.get("net_pct") if s.get("net_pct") is None else round(s["net_pct"], 2), "R", s.get("r_mult") if s.get("r_mult") is None else round(s["r_mult"], 2),
          "why", s.get("reason"), "rg", rg.get("regime"), rg.get("strength"), why)
