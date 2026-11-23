import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
T0=int(D.datetime(2026,11,23,1,22,0,tzinfo=D.UTC).timestamp()*1000)
def lab(w):
    w=w or ""
    for k,v in (("\u0444\u0438\u043b\u044c\u0442\u0440 \u0441\u0442\u043e\u0440\u043e\u043d\u044b","side"),("\u0444\u0438\u043b\u044c\u0442\u0440 \u0440\u0435\u0436\u0438\u043c\u0430","score"),("\u0444\u0438\u043b\u044c\u0442\u0440 BTC 1m","btcrsi"),("\u0444\u0438\u043b\u044c\u0442\u0440: \u0441\u0438\u0433\u043d\u0430\u043b \u043f\u0440\u043e\u0442\u0438\u0432","counter"),("\u0444\u0438\u043b\u044c\u0442\u0440 RSI5","rsi5"),("\u0444\u0438\u043b\u044c\u0442\u0440 \u0448\u0438\u0440\u0438\u043d\u044b","width")):
        if w.startswith(k): return v
    return "gate/other"
def st(v):
    if not v: return "n=0"
    r=[q["r"] for q in v];n=len(r)
    return "n=%3d win=%2.0f%% sumR=%7.2f avg=%5.2f"%(n,100*sum(1 for a in r if a>0)/n,sum(r),sum(r)/n)
rows=[]
for x in d:
    t0=x.get("t0") or (x.get("p") or {}).get("t_in") or 0
    if t0<T0: continue
    p=x.get("p"); 
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: r=p["r_mult"];src="in"
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: r=x["cf"]["r_mult"];src="cf"
    elif x.get("status")=="filtered": r=None;src="cf_open"
    else: r=None;src=x.get("status")
    ft=x.get("feat") or {}; b1=x.get("b1") or {}
    rs=ft.get("rsi5"); sg=1 if x["side"]=="long" else -1
    rows.append(dict(sn=x.get("sn"),var=x.get("var"),tf=x["tf"],kind=x["kind"],side=x["side"],sym=x["sym"],src=src,r=r,why=lab(x.get("why")) if x.get("status")=="filtered" else "-",rsi_ok=b1.get("rsi_ok"),counter=ft.get("counter"),ars=((rs if sg>0 else 100-rs) if rs is not None else None),width=ft.get("width"),reg=(x.get("rg") or {}).get("regime"),t0=t0,rsn=(p or {}).get("reason")))
print("since 23.11 01:22 UTC: items",len(rows),collections.Counter((q["var"],q["src"]) for q in rows))
for var in ("A","B"):
    V=[q for q in rows if (q["var"] in ("A",None) if var=="A" else q["var"]=="B")]
    ins=[q for q in V if q["src"]=="in"]; cf=[q for q in V if q["src"]=="cf"]
    print("=== var",var,"entered",st(ins),"| filtered(cf) ",st(cf),"| not-finished",sum(1 for q in V if q["src"] not in("in","cf")))
    o=collections.defaultdict(list)
    for q in cf: o[q["why"]].append(q)
    for k,v in sorted(o.items()): print("   cf by first reason",k,st(v))
    o=collections.defaultdict(list)
    for q in cf: o[(q["tf"])].append(q)
    for k,v in sorted(o.items()): print("   cf by tf",k,st(v))
    o=collections.defaultdict(list)
    for q in ins: o[(q["tf"])].append(q)
    for k,v in sorted(o.items()): print("   entered by tf",k,st(v))
A=[q for q in rows if q["var"] in ("A",None) and q["r"] is not None]
print("--- A entered list")
for q in A:
    if q["src"]=="in": print("  #%s %s %s %s %s %s -> %s %.2f"%(q["sn"],q["sym"],q["tf"],q["kind"][:2],q["side"][0],q["reg"],q["rsn"],q["r"]))
print("--- standalone flag effect among A (all finished, in+cf)")
def flag(name,f):
    b=[q for q in A if f(q)]; k=[q for q in A if not f(q)]
    print("  %-10s blocked %s | passed %s"%(name,st(b),st(k)))
flag("rsi_ok=0",lambda q:q["rsi_ok"] in (0,False))
flag("counter",lambda q:bool(q["counter"]))
flag("rsi5<30",lambda q:q["ars"] is not None and q["ars"]<30)
flag("width>=8",lambda q:q["width"] is not None and q["width"]>=8)
flag("regime counter",lambda q:(q["reg"]=="down" and q["side"]=="long") or (q["reg"]=="up" and q["side"]=="short"))
allp=[q for q in A if not((q["rsi_ok"] in (0,False)) or q["counter"] or (q["ars"] is not None and q["ars"]<30) or (q["width"] is not None and q["width"]>=8))]
print("  pass all 4 old+width:",st(allp))
print("--- cf rows detail (A) sorted by R desc top 14")
for q in sorted([q for q in A if q["src"]=="cf"],key=lambda q:-q["r"])[:14]: print("  #%s %s %s %s %s why=%s reg=%s w=%s R=%.2f"%(q["sn"],q["sym"],q["tf"],q["kind"][:2],q["side"][0],q["why"],q["reg"],q["width"],q["r"]))
