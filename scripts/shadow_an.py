import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))
L=d["items"]
keys=collections.Counter(k for x in L for k in x)
print("KEYS",dict(keys))
C=[x for x in L if x.get("status")=="closed"]
print("closed",len(C))
def fmt(t): return D.datetime.utcfromtimestamp(t/1000).strftime("%m-%d %H:%M")
def agg(name,grp):
    print("--",name)
    for k,v in sorted(grp.items(),key=lambda a:str(a[0])):
        r=[x.get("r_mult",0) for x in v]
        w=sum(1 for q in r if q>0)
        print("  %s n=%d win=%d sumR=%.2f avg=%.2f"%(k,len(v),w,sum(r),sum(r)/len(r)))
def g(f):
    o=collections.defaultdict(list)
    for x in C: o[f(x)].append(x)
    return o
agg("reason",g(lambda x:x.get("reason")))
agg("variant",g(lambda x:x.get("var") or x.get("v") or x.get("variant")))
agg("tf",g(lambda x:x["tf"]))
agg("kind_side",g(lambda x:x["kind"]+" "+x["side"]))
agg("legacy",g(lambda x:x.get("legacy")))
agg("regime",g(lambda x:(x.get("rg") or {}).get("regime")))
agg("regime_vs_side",g(lambda x:((x.get("rg") or {}).get("regime"),x["side"])))
agg("hour_utc",g(lambda x:D.datetime.utcfromtimestamp(x["t_in"]/1000).hour//4*4))
agg("day",g(lambda x:D.datetime.utcfromtimestamp(x["t_in"]/1000).strftime("%m-%d")))
agg("sym",g(lambda x:x["sym"]))
rk=[x["risk"]/x["entry"]*100 for x in C if x.get("entry")]
print("risk% med %.2f mean %.2f min %.2f max %.2f"%(S.median(rk),S.mean(rk),min(rk),max(rk)))
rr=[x["rr"] for x in C if x.get("rr")]
print("planned rr med %.2f mean %.2f"%(S.median(rr),S.mean(rr)))
print("net_pct sum %.2f avg %.3f ; sumR %.2f"%(sum(x.get("net_pct",0) for x in C),S.mean([x.get("net_pct",0) for x in C]),sum(x.get("r_mult",0) for x in C)))
# commission estimate in R
cm=[0.10/(x["risk"]/x["entry"]*100) for x in C if x.get("entry")]
print("commission 0.10%% in R: mean %.3f sum %.2f"%(S.mean(cm),sum(cm)))
# hold time
h=[(x["t_out"]-x["t_in"])/60000 for x in C if x.get("t_out")]
print("hold min med %.0f mean %.0f"%(S.median(h),S.mean(h)))
# mfe/mae
print("mfe med %.2f mean %.2f ; mae med %.2f mean %.2f"%(S.median([x["mfe"] for x in C]),S.mean([x["mfe"] for x in C]),S.median([x["mae"] for x in C]),S.mean([x["mae"] for x in C])))
for th in (0.3,0.5,0.75,1.0,1.5,2.0):
    print(" mfe>=%.2f: %d/%d"%(th,sum(1 for x in C if x["mfe"]>=th),len(C)))
# stops with mfe
st=[x for x in C if x.get("reason")=="stop"]
print("stop n",len(st)," of them mfe>=0.5:",sum(1 for x in st if x["mfe"]>=0.5)," mfe>=0.8:",sum(1 for x in st if x["mfe"]>=0.8))
print("stop r_mult dist",sorted(round(x["r_mult"],2) for x in st))
# immediate losers: mfe<0.2
print("stop mfe<0.2:",sum(1 for x in st if x["mfe"]<0.2))
# time to stop for stops
hs=[(x["t_out"]-x["t_in"])/60000 for x in st if x.get("t_out")]
print("stop hold min med %.0f"%S.median(hs))
# filtered
F=[x for x in L if x.get("status")=="filtered"]
print("filtered",len(F)); fk=collections.Counter(k for x in F for k in x if k in("cf","why","fr","fstat","filt"))
print(fk)
x=F[-1]; print({k:(v if not isinstance(v,(list,dict)) else "..") for k,v in x.items()})
print("LASTCLOSED",[(x["sn"] if "sn" in x else x["id"],x["sym"],x["tf"],x["kind"],x["side"],fmt(x["t_in"]),x["reason"],x["r_mult"],x["mfe"],x["mae"]) for x in C[-20:]])
