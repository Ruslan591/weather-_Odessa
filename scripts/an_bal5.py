import json, datetime
P = "/opt/trading-bot/positions_regr/"
items = json.load(open(P + "shadow.json"))["items"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M:%S") if ms else "-"
def cut(o, n=1500): return json.dumps(o, ensure_ascii=True, default=str)[:n]
for x in items:
    if x.get("sn") != 198: continue
    print("=== ITEM", x.get("var"), "id", x.get("id"), "status", x.get("status"), "sig", ts(x.get("t_sig")), "fill", ts(x.get("t_fill")), "out", ts(x.get("t_out")))
    p = x.get("p") or {}
    print("P", cut({k: v for k, v in p.items() if k not in ("ext_hist", "sw_hist", "thesis")}, 1600))
    print("P.ext_hist", cut(p.get("ext_hist"), 600), "sw_hist", cut(p.get("sw_hist"), 600))
    print("PB", cut({k: v for k, v in (x.get("pb") or {}).items() if k not in ("thesis",)}, 900))
    print("CF", cut({k: v for k, v in (x.get("cf") or {}).items() if k not in ("thesis",)}, 900))
    print("EV")
    for e in (x.get("ev") or [])[:30]: print("  ", cut(e, 200))
    print("plan", cut(x.get("plan")), "target", cut(x.get("target")), "mfe_r", x.get("mfe_r"), "mae_r", x.get("mae_r"))
