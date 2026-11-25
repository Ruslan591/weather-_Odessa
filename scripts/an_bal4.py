import json, datetime
P = "/opt/trading-bot/positions_regr/"
items = json.load(open(P + "shadow.json"))["items"]
t0 = json.load(open(P + "shadow_bal.json"))["t0"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d%H:%M") if ms else "-"
def g(d, k, r=2):
    v = (d or {}).get(k)
    return round(v, r) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
rows = []
for x in items:
    if x.get("var") != "A" or (x.get("t_sig") or 0) < t0: continue
    st = x.get("status"); s = x.get("p") if st in ("closed", "open") else x.get("cf")
    s = s or {}
    rows.append((s.get("t_in") or 0, x, s))
rows.sort(key=lambda r: r[0])
print("sn sym side tf kind st tin | net R mfe mae stop% dur | rgS | width rr cnt rsi5 wick dist | b1: rsi rsd emad strict imp exh run3 pos | o o0")
for tin, x, s in rows:
    f = x.get("feat") or {}; b = x.get("b1") or {}; rg = x.get("rg") or {}
    dur = round(((s.get("t_out") or 0) - tin) / 60000) if s.get("t_out") else None
    print(x.get("sn"), x.get("sym"), x.get("side"), x.get("tf"), (x.get("kind") or "")[:3], (x.get("status") or "")[:3], ts(tin), "|",
          g(s, "net_pct"), g(s, "r_mult"), g(s, "mfe_pct"), g(s, "mae_pct"), g(s, "R_pct"), dur, "|", rg.get("strength"), "|",
          g(f, "width", 1), g(f, "rr", 1), f.get("counter"), g(f, "rsi5", 0), g(f, "wick"), g(f, "dist"), "|",
          g(b, "rsi", 0), g(b, "rsd"), g(b, "emad", 4), b.get("strict"), b.get("imp"), b.get("exh"), b.get("run3"), b.get("pos"), "|",
          str(x.get("o"))[:60], str(x.get("o0"))[:40])
