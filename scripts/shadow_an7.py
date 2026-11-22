import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
def f(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%d %H:%M")
rows=[]
for x in d:
    if x.get("var") not in ("A",None): continue
    p=x.get("p")
    if p and p.get("legacy"): continue
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: r=p["r_mult"];src="in";t=p["t_in"]
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: r=x["cf"]["r_mult"];src="cf";t=x["cf"]["t_in"]
    else: continue
    if t<1795137600000-1000*0: pass
    rg=x.get("rg") or {}
    rows.append(dict(r=r,src=src,t=t,reg=rg.get("regime"),st=rg.get("strength") or 0,side=x["side"],tf=x["tf"],kind=x["kind"],sn=x.get("sn")))
rows=[q for q in rows if q["t"]>=1795137641000-1000*3600*0] if False else rows
# base start: #13 20.11 00:00:41 UTC
START=int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000)
rows=[q for q in rows if q["t"]>=START]
print("signals with result",len(rows),"in",sum(1 for q in rows if q["src"]=="in"),"cf",sum(1 for q in rows if q["src"]=="cf"))
def st(v):
    if not v: return "n=0"
    r=[q["r"] for q in v]; n=len(r)
    return "n=%d win=%d(%.0f%%) sumR=%.2f avg=%.2f"%(n,sum(1 for a in r if a>0),100*sum(1 for a in r if a>0)/n,sum(r),sum(r)/n)
def grp(name,key,sel=lambda q:True):
    o=collections.defaultdict(list)
    for q in rows:
        if sel(q): o[key(q)].append(q)
    print("--",name)
    for k,v in sorted(o.items(),key=lambda a:str(a[0])): print("  ",k,st(v))
grp("ALL regime x side",lambda q:(q["reg"],q["side"]))
grp("ENTERED only regime x side",lambda q:(q["reg"],q["side"]),lambda q:q["src"]=="in")
grp("CF only regime x side",lambda q:(q["reg"],q["side"]),lambda q:q["src"]=="cf")
grp("5m only regime x side",lambda q:(q["reg"],q["side"]),lambda q:q["tf"]=="5m")
grp("regime x side x strength>=0.7",lambda q:(q["reg"],q["side"]),lambda q:q["st"]>=0.7)
grp("regime x side x strength<0.7",lambda q:(q["reg"],q["side"]),lambda q:q["st"]<0.7)
grp("by kind x regime-agree",lambda q:(q["kind"], "agree" if (q["reg"]=="down" and q["side"]=="short") or (q["reg"]=="up" and q["side"]=="long") else ("flat" if q["reg"]=="flat" else "counter")))
def cls(q):
    if q["reg"]=="flat": return "flat"
    return "agree" if (q["reg"]=="down" and q["side"]=="short") or (q["reg"]=="up" and q["side"]=="long") else "counter"
grp("agree/flat/counter ALL",cls)
grp("agree/flat/counter ENTERED",cls,lambda q:q["src"]=="in")
grp("agree/flat/counter 5m ALL",cls,lambda q:q["tf"]=="5m")
# halves in time for stability
rows.sort(key=lambda q:q["t"]); h=len(rows)//2
for nm,part in (("first half",rows[:h]),("second half",rows[h:])):
    o=collections.defaultdict(list)
    for q in part: o[cls(q)].append(q)
    print("--",nm,f(part[0]["t"]),"..",f(part[-1]["t"]))
    for k,v in sorted(o.items()): print("  ",k,st(v))
# regime timeline: share of signals per regime per day
o=collections.Counter((D.datetime.fromtimestamp(q["t"]/1000,D.UTC).strftime("%d"),q["reg"]) for q in rows)
print("regime by day",sorted(o.items()))
# filter effect: drop counter
keep=[q for q in rows if cls(q)!="counter"]
print("FILTER no-counter: all %s | kept %s | dropped %s"%(st(rows),st(keep),st([q for q in rows if cls(q)=="counter"])))
keep2=[q for q in rows if cls(q)=="agree"]
print("FILTER agree-only: kept %s"%st(keep2))
