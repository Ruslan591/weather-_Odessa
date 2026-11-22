import json,collections,statistics as S,datetime as D,bisect
P="/opt/trading-bot/positions_regr/"
d=json.load(open(P+"shadow.json"))["items"]
log=[json.loads(l) for l in open(P+"tg_regime_log.jsonl").read().splitlines() if l.strip()]
log.sort(key=lambda r:r["t"]); T=[r["t"] for r in log]
print("regime log",len(log),D.datetime.fromtimestamp(T[0]/1000,D.UTC),"..",D.datetime.fromtimestamp(T[-1]/1000,D.UTC))
START=int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000)
def at(t):
    i=bisect.bisect_right(T,t)-1
    return log[i] if i>=0 else None
rows=[]
for x in d:
    if x.get("var") not in ("A",None): continue
    p=x.get("p")
    if p and p.get("legacy"): continue
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: pp=p;src="in"
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: pp=x["cf"];src="cf"
    else: continue
    if pp["t_in"]<START: continue
    ts=x.get("t0") or pp["t_in"]
    L0=at(ts); L3=at(ts-3*3600000); L6=at(ts-6*3600000)
    if not L0: continue
    sg=1 if x["side"]=="long" else -1
    net=L0["bull"]-L0["bear"]
    net3=(L3["bull"]-L3["bear"]) if L3 else None
    # regime age
    k=bisect.bisect_right(T,ts)-1; reg=log[k]["regime"]; j=k
    while j>0 and log[j-1]["regime"]==reg: j-=1
    age=(ts-log[j]["t"])/3600000 if j>0 else None
    rows.append(dict(tf=x["tf"],side=x["side"],kind=x["kind"],src=src,r=pp["r_mult"],mfe=pp["mfe_pct"]/pp["R_pct"],mae=pp["mae_pct"]/pp["R_pct"],reg=L0["regime"],raw=L0["raw"],bear=L0["bear"],bull=L0["bull"],net=net,al=net*sg,d3=(net-net3)*sg if net3 is not None else None,adx=L0["adx"],age=age,t=ts))
print("rows",len(rows))
def st(v):
    if not v: return "n=0"
    r=[q["r"] for q in v];n=len(r)
    return "n=%d win=%.0f%% sumR=%.2f avg=%.2f medMFE=%.2f medMAE=%.2f"%(n,100*sum(1 for a in r if a>0)/n,sum(r),sum(r)/n,S.median([q["mfe"] for q in v]),S.median([q["mae"] for q in v]))
def grp(name,key,sel=lambda q:True):
    o=collections.defaultdict(list)
    for q in rows:
        if sel(q): o[key(q)].append(q)
    print("--",name)
    for k,v in sorted(o.items(),key=lambda a:str(a[0])): print("  ",k,st(v))
b=lambda a:"<=-3" if a<=-3 else ("-2..-1" if a<0 else ("0" if a==0 else ("1..2" if a<=2 else ">=3")))
grp("ALL aligned score (bull-bear, + for long, - for short) buckets",lambda q:b(q["al"]))
grp("5m only aligned",lambda q:b(q["al"]),lambda q:q["tf"]=="5m")
grp("flat regime only: aligned",lambda q:b(q["al"]),lambda q:q["reg"]=="flat")
grp("flat regime only: aligned, 5m",lambda q:b(q["al"]),lambda q:q["reg"]=="flat" and q["tf"]=="5m")
grp("regime/raw states",lambda q:(q["reg"],q["raw"]))
grp("raw!=regime (transition) vs steady",lambda q:"transition" if q["raw"]!=q["reg"] else "steady")
grp("net-change over 3h aligned (d3>0 = bias moving toward the trade side)",lambda q:("d3>0" if q["d3"]>0 else ("d3=0" if q["d3"]==0 else "d3<0")) if q["d3"] is not None else "na")
grp("regime age (h) buckets",lambda q:"na" if q["age"] is None else ("<3h" if q["age"]<3 else ("3-12h" if q["age"]<12 else ">=12h")))
grp("raw-only aligned (down/up/flat)x side",lambda q:(q["raw"],q["side"]))
print("-- regime log last 14 entries")
for r in log[-14:]: print(D.datetime.fromtimestamp(r["t"]/1000,D.UTC).strftime("%d %H:%M"),r["regime"],r["raw"],"bear",r["bear"],"bull",r["bull"],"adx",r["adx"],"ret24",r["ret24"],"ds",r["ds"])
# timeline compact: per 3 hours since 20.11
print("-- timeline every 3h")
for r in log:
    if r["t"]>=START and (D.datetime.fromtimestamp(r["t"]/1000,D.UTC).minute<30) and D.datetime.fromtimestamp(r["t"]/1000,D.UTC).hour%3==0: print(D.datetime.fromtimestamp(r["t"]/1000,D.UTC).strftime("%d %H:%M"),r["regime"],r["raw"],r["bear"],r["bull"],r["adx"],r["ret24"])
