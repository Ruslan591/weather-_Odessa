import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
START=int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000)
rows=[]
for x in d:
    if x.get("var") not in ("A",None): continue
    p=x.get("p")
    if p and p.get("legacy"): continue
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: pp=p;src="in"
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: pp=x["cf"];src="cf"
    else: continue
    if pp["t_in"]<START: continue
    ft=x.get("feat") or {}; b1=x.get("b1") or {}; rg=x.get("rg") or {}
    sg=1 if x["side"]=="long" else -1
    rsi5=ft.get("rsi5"); 
    rows.append(dict(sn=x.get("sn"),tf=x["tf"],side=x["side"],kind=x["kind"],src=src,r=pp["r_mult"],mfe=pp["mfe_pct"]/pp["R_pct"],t=pp["t_in"],ft=ft,b1=b1,reg=rg.get("regime"),ars=(rsi5 if sg>0 else 100-rsi5) if rsi5 is not None else None))
rows.sort(key=lambda q:q["t"])
print("rows",len(rows),"last",D.datetime.fromtimestamp(rows[-1]["t"]/1000,D.UTC),"max sn",max(q["sn"] or 0 for q in rows))
print("b1 present",sum(1 for q in rows if q["b1"]),"; feat keys sample",list(rows[-1]["ft"].keys()))
def st(v):
    if not v: return "n=0"
    r=[q["r"] for q in v];n=len(r)
    return "n=%3d win=%2.0f%% sumR=%6.2f avg=%5.2f"%(n,100*sum(1 for a in r if a>0)/n,sum(r),sum(r)/n)
def test(name,key,sel=lambda q:True):
    sub=[q for q in rows if sel(q)]
    o=collections.defaultdict(list)
    for q in sub:
        k=key(q)
        if k is not None: o[k].append(q)
    h=len(sub)//2
    print("--",name,"(n=%d)"%len(sub))
    for k,v in sorted(o.items(),key=lambda a:str(a[0])):
        v1=[q for q in v if q in sub[:h]]; v2=[q for q in v if q in sub[h:]]
        print("   %-10s %s | 1st half avg %s (n=%d) | 2nd half avg %s (n=%d)"%(k,st(v),("%.2f"%(sum(q["r"] for q in v1)/len(v1)) if v1 else "-"),len(v1),("%.2f"%(sum(q["r"] for q in v2)/len(v2)) if v2 else "-"),len(v2)))
for nm,sel in (("ALL",lambda q:True),("5m",lambda q:q["tf"]=="5m")):
    print("=======",nm)
    test("b1.strict",lambda q:q["b1"].get("strict"),sel)
    test("b1.ok",lambda q:q["b1"].get("ok"),sel)
    test("b1.pos",lambda q:q["b1"].get("pos"),sel)
    test("b1.rsi_ok",lambda q:q["b1"].get("rsi_ok"),sel)
    test("b1.imp",lambda q:q["b1"].get("imp"),sel)
    test("b1.big",lambda q:q["b1"].get("big"),sel)
    test("b1.run3",lambda q:q["b1"].get("run3"),sel)
    test("b1.exh",lambda q:q["b1"].get("exh"),sel)
    test("b1.rsi (BTC 1m RSI) bucket",lambda q:None if q["b1"].get("rsi") is None else ("<40" if q["b1"]["rsi"]<40 else ("40-60" if q["b1"]["rsi"]<=60 else ">60")),sel)
    test("feat.rsi5 aligned (long=rsi, short=100-rsi)",lambda q:None if q["ars"] is None else ("<30" if q["ars"]<30 else ("30-45" if q["ars"]<45 else ("45-60" if q["ars"]<60 else ">=60"))),sel)
    test("feat.favor",lambda q:q["ft"].get("favor"),sel)
    test("feat.counter",lambda q:q["ft"].get("counter"),sel)
    test("feat.st",lambda q:q["ft"].get("st"),sel)
    test("feat.wick>=0.4",lambda q:None if q["ft"].get("wick") is None else q["ft"]["wick"]>=0.4,sel)
    test("feat.cpos>=0.5",lambda q:None if q["ft"].get("cpos") is None else q["ft"]["cpos"]>=0.5,sel)
    test("feat.rr bucket",lambda q:None if q["ft"].get("rr") is None else ("<3" if q["ft"]["rr"]<3 else ("3-6" if q["ft"]["rr"]<6 else ">=6")),sel)
    test("feat.dist bucket (ATR from line)",lambda q:None if q["ft"].get("dist") is None else ("<0" if q["ft"]["dist"]<0 else ("0-0.3" if q["ft"]["dist"]<0.3 else ">=0.3")),sel)
    test("feat.bc[0] bucket",lambda q:None if not q["ft"].get("bc") else ("bc0<0.2" if q["ft"]["bc"][0]<0.2 else ("bc0 0.2-0.5" if q["ft"]["bc"][0]<0.5 else "bc0>=0.5")),sel)
    test("feat.h[0] (htf)",lambda q:None if not q["ft"].get("h") else q["ft"]["h"][0],sel)
    test("feat.width bucket",lambda q:None if q["ft"].get("width") is None else ("w<4" if q["ft"]["width"]<4 else ("w4-8" if q["ft"]["width"]<8 else "w>=8")),sel)
