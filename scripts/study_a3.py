import json,time
tr=json.load(open("/opt/trading-bot/live/data/shadow_bal_trades.json"))
rs=sorted(tr.values(),key=lambda r:r["t_in"])
def f(ms): return time.strftime("%d %H:%M",time.gmtime(ms/1000)) if ms else "-"
print(len(rs), "k:", {k:sum(1 for r in rs if r["k"]==k) for k in("in","cf")})
cum=0
for r in rs:
    if r["k"]=="in": pass
    print(f(r["t_in"]),f(r["t_out"]),r["sn"],r["sym"],r["side"][0],r["tf"],r["k"],r.get("rg"),r["r"],round(r["net_pct"],2) if r["net_pct"] is not None else None)
