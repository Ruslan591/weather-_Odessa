import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))
L=d["items"]
def hm(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%d %H:%M")
C=[x for x in L if x.get("status")=="closed" and x.get("p") and x.get("pb") and x["pb"].get("r_mult") is not None and x["p"].get("r_mult") is not None]
print("n",len(C))
rows=[]
for x in sorted(C,key=lambda x:x["p"]["t_in"]):
    p=x["p"];b=x["pb"]
    rows.append(p["r_mult"]-b["r_mult"])
    print("#%s %s %s %s %s in %s | p %s %.2f out %s mfe %.2f | pb %s %.2f out %s | sw %d ext %s"%(x["sn"],x["sym"],x["tf"],x["kind"][:2],x["side"][0],hm(p["t_in"]),p["reason"],p["r_mult"],hm(p["t_out"]),p["mfe_pct"]/p["R_pct"],b["reason"],b["r_mult"],hm(b["t_out"]),len(p.get("sw_hist") or []),len(p.get("ext_hist") or [])))
better=[r for r in rows if r>0.05];worse=[r for r in rows if r<-0.05]
print("better",len(better),"%.2f"%sum(better),"worse",len(worse),"%.2f"%sum(worse),"equal",len(rows)-len(better)-len(worse))
ins=sorted((x["p"]["t_in"],x["sym"],x["side"],x["tf"],x.get("var"),x["p"]["r_mult"]) for x in L if x.get("status")=="closed" and x.get("p") and x["p"].get("r_mult") is not None and x.get("var")=="A")
cl=[];cur=[ins[0]]
for e in ins[1:]:
    if e[0]-cur[-1][0]<=3600000: cur.append(e)
    else: cl.append(cur);cur=[e]
cl.append(cur)
print("A clusters (<=1h gap):",len(cl),"for",len(ins),"trades")
for c in cl:
    if len(c)>=3: print("  ",hm(c[0][0]),"n=%d"%len(c),dict(collections.Counter(e[2] for e in c)),"sumR %.2f"%sum(e[5] for e in c),[e[1] for e in c])
