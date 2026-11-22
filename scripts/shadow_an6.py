import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
C=[x for x in d if x.get("status")=="closed" and x.get("p") and x["p"].get("r_mult") is not None and not x["p"].get("legacy") and x.get("var") in ("A",None)]
print("base n",len(C),"sumR %.2f avg %.3f"%(sum(x["p"]["r_mult"] for x in C),S.mean([x["p"]["r_mult"] for x in C])))
def agg(name,f):
    o=collections.defaultdict(list)
    for x in C: o[f(x)].append(x["p"]["r_mult"])
    print("--",name)
    for k,v in sorted(o.items(),key=lambda a:str(a[0])): print("  %s n=%d win=%d sumR=%.2f avg=%.2f"%(k,len(v),sum(1 for q in v if q>0),sum(v),S.mean(v)))
agg("reason",lambda x:x["p"]["reason"]); agg("tf",lambda x:x["tf"]); agg("kind_side",lambda x:x["kind"]+" "+x["side"])
agg("tf5 kind_side",lambda x:(x["kind"]+" "+x["side"]) if x["tf"]=="5m" else "skip")
agg("regime_side",lambda x:((x.get("rg") or {}).get("regime"),x["side"]))
g=[];fe=[]
for x in C:
    p=x["p"];e=p["entry"];ex=p["exit"];gr=((ex-e)/e*100)*(1 if p["side"]=="long" else -1);g.append(gr/p["R_pct"]);fe.append((gr-p["net_pct"])/p["R_pct"])
print("gross R sum %.2f ; cost R sum %.2f ; net %.2f"%(sum(g),sum(fe),sum(x["p"]["r_mult"] for x in C)))
mf=[x["p"]["mfe_pct"]/x["p"]["R_pct"] for x in C]
print("MFE>=1R %d/%d ; stops %d ; target %d"%(sum(1 for v in mf if v>=1),len(C),sum(1 for x in C if x["p"]["reason"]=="stop"),sum(1 for x in C if x["p"]["reason"]=="target")))
ins=sorted((x["p"]["t_in"],x["sym"],x["side"],x["tf"],x["p"]["r_mult"]) for x in C)
cl=[];cur=[ins[0]]
for e in ins[1:]:
    if e[0]-cur[-1][0]<=3600000: cur.append(e)
    else: cl.append(cur);cur=[e]
cl.append(cur)
print("clusters",len(cl))
for c in cl:
    if len(c)>=3: print("  ",D.datetime.fromtimestamp(c[0][0]/1000,D.UTC).strftime("%d %H:%M"),"n=%d"%len(c),"sumR %.2f"%sum(e[4] for e in c),[e[1] for e in c])
