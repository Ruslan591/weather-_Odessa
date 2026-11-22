import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))
L=d["items"]
def hr(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%m-%d %H")
C=[x for x in L if x.get("status")=="closed" and x.get("p") and x["p"].get("r_mult") is not None]
A=[x for x in C if x.get("var")=="A"]
print("closed with p",len(C),"A",len(A),"B",len([x for x in C if x.get("var")=="B"]),"other",len([x for x in C if x.get("var") not in("A","B")]))
def R(x,k="p"): return x[k]["r_mult"]
def agg(name,grp,k="p"):
    print("--",name)
    for key,v in sorted(grp.items(),key=lambda a:str(a[0])):
        r=[R(x,k) for x in v]
        print("  %s n=%d win=%d(%.0f%%) sumR=%.2f avg=%.2f"%(key,len(v),sum(1 for q in r if q>0),100*sum(1 for q in r if q>0)/len(r),sum(r),sum(r)/len(r)))
def g(S_,f):
    o=collections.defaultdict(list)
    for x in S_: o[f(x)].append(x)
    return o
print("ALL closed sumR %.2f avg %.3f"%(sum(R(x) for x in C),S.mean([R(x) for x in C])))
for nm,S_ in (("A",A),("ALL",C)):
    print("=====",nm,len(S_))
    agg("reason",g(S_,lambda x:x["p"].get("reason")))
    agg("tf",g(S_,lambda x:x["tf"]))
    agg("kind_side",g(S_,lambda x:x["kind"]+" "+x["side"]))
    agg("regime_vs_side",g(S_,lambda x:((x["rg"] or {}).get("regime"),x["side"])))
    agg("hour4",g(S_,lambda x:D.datetime.fromtimestamp(x["p"]["t_in"]/1000,D.UTC).hour//4*4))
    agg("day",g(S_,lambda x:D.datetime.fromtimestamp(x["p"]["t_in"]/1000,D.UTC).strftime("%m-%d")))
    agg("sym",g(S_,lambda x:x["sym"]))
S_=A
Rp=[x["p"]["R_pct"] for x in S_]
print("R_pct med %.2f mean %.2f min %.2f max %.2f ; R_pct<=0.55: %d/%d"%(S.median(Rp),S.mean(Rp),min(Rp),max(Rp),sum(1 for v in Rp if v<=0.55),len(Rp)))
# costs: gross vs net
gs=[];fees=[]
for x in S_:
    p=x["p"]; e=p["entry"]; ex=p.get("exit")
    if ex is None: continue
    gr=((ex-e)/e*100)*(1 if p["side"]=="long" else -1)
    gs.append(gr); fees.append(gr-p["net_pct"])
print("avg gross pct %.3f avg net pct %.3f avg cost pct %.3f -> cost in R %.3f"%(S.mean(gs),S.mean([x["p"]["net_pct"] for x in S_ if x["p"].get("exit")]),S.mean(fees),S.mean(fees)/S.mean(Rp)))
print("gross R sum (gross/R_pct): %.2f ; net R sum %.2f"%(sum(gr/x["p"]["R_pct"] for gr,x in zip(gs,[y for y in S_ if y["p"].get("exit")])),sum(R(x) for x in S_)))
# mfe mae in R
mf=[x["p"]["mfe_pct"]/x["p"]["R_pct"] for x in S_ if x["p"].get("mfe_pct") is not None]
ma=[x["p"]["mae_pct"]/x["p"]["R_pct"] for x in S_ if x["p"].get("mae_pct") is not None]
print("MFE_R med %.2f mean %.2f ; MAE_R med %.2f mean %.2f"%(S.median(mf),S.mean(mf),S.median(ma),S.mean(ma)))
for th in (0.3,0.5,0.75,1.0,1.5,2.0): print(" mfe>=%.2fR: %d/%d"%(th,sum(1 for v in mf if v>=th),len(mf)))
st=[x for x in S_ if x["p"].get("reason")=="stop"]
print("stops",len(st),"mfe>=0.5R among stops:",sum(1 for x in st if x["p"]["mfe_pct"]/x["p"]["R_pct"]>=0.5),">=0.8R:",sum(1 for x in st if x["p"]["mfe_pct"]/x["p"]["R_pct"]>=0.8),"mfe<0.2R:",sum(1 for x in st if x["p"]["mfe_pct"]/x["p"]["R_pct"]<0.2))
h=[(x["p"]["t_out"]-x["p"]["t_in"])/60000 for x in S_]
print("hold min med %.0f mean %.0f ; stops med %.0f"%(S.median(h),S.mean(h),S.median([(x["p"]["t_out"]-x["p"]["t_in"])/60000 for x in st]) if st else 0))
# entry delay and slippage vs plan
dl=[(x["p"]["t_in"]-x["t_sig"])/1000 for x in S_]
print("delay sig->entry sec med %.0f mean %.0f max %.0f"%(S.median(dl),S.mean(dl),max(dl)))
sl=[]
for x in S_:
    pl=x["plan"]; e=x["p"]["entry"]; R0=x["p"]["R"]
    s=(e-pl["entry"])/R0*(1 if x["side"]=="long" else -1)  # + means entered worse? for long higher entry is worse
    sl.append(s)
print("entry vs plan entry in R (+ = worse): med %.2f mean %.2f"%(S.median(sl),S.mean(sl)))
# tp distance in R
tpR=[abs(x["p"]["tp"]-x["p"]["entry"])/x["p"]["R"] for x in S_]
print("target distance R med %.2f mean %.2f"%(S.median(tpR),S.mean(tpR)))
# rules value: p vs pb
PB=[x for x in S_ if x.get("pb") and x["pb"].get("r_mult") is not None]
print("pb compare n",len(PB),"p sum %.2f pb sum %.2f"%(sum(R(x) for x in PB),sum(R(x,"pb") for x in PB)))
# filtered cf
F=[x for x in L if x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None]
print("filtered with cf result",len(F),"sumR %.2f avg %.3f win %d"%(sum(x["cf"]["r_mult"] for x in F),S.mean([x["cf"]["r_mult"] for x in F]),sum(1 for x in F if x["cf"]["r_mult"]>0)))
Fa=[x for x in F if x.get("var")=="A"]
print("filtered A",len(Fa),"sumR %.2f avg %.3f win %d"%(sum(x["cf"]["r_mult"] for x in Fa),S.mean([x["cf"]["r_mult"] for x in Fa]),sum(1 for x in Fa if x["cf"]["r_mult"]>0)))
def why(x):
    w=(x.get("why") or "")
    return "".join(ch for ch in w if ord(ch)<128)[:40] or "nonascii"
o=g(F,lambda x:(x.get("var"),x["cf"].get("reason")))
for k,v in sorted(o.items(),key=lambda a:str(a[0])): print("  cf",k,len(v),"sumR %.2f"%sum(y["cf"]["r_mult"] for y in v))
# last 12 closed A timeline
print("LAST",[(x["sn"],x["sym"],x["tf"],x["kind"][:2],x["side"][0],hr(x["p"]["t_in"]),x["p"]["reason"],round(R(x),2)) for x in sorted(A,key=lambda x:x["p"]["t_in"])[-14:]])
