import sys,json,collections,statistics as S,datetime as D,bisect
sys.path.insert(0,"/opt/tg-notify")
import tg_regime as R
P="/opt/trading-bot/positions_regr/"
HOUR=3600000
btc=R.klines("BTC","1h",500)
alts={s:{int(k[0]):float(k[4]) for k in R.klines(s,"1h",200)} for s in R.BASKET}
bt=[int(k[0]) for k in btc]; H=[float(k[2]) for k in btc]; Lo=[float(k[3]) for k in btc]; C=[float(k[4]) for k in btc]
# drop the unclosed last candle
import time
now=int(time.time()*1000)
n=len(bt)
if bt[-1]+HOUR>now: n-=1
tab={}
for i in range(220,n):
    t=bt[i]
    chg=[]
    for s,m in alts.items():
        if t in m and (t-24*HOUR) in m: chg.append(m[t]/m[t-24*HOUR]-1)
    ds=(sum(1 for x in chg if x<0)/len(chg)) if len(chg)>=12 else None
    med=sorted(chg)[len(chg)//2] if len(chg)>=12 else None
    f=R.regime_at(H[:i+1],Lo[:i+1],C[:i+1],ds,med)
    if f: tab[t+HOUR]=f   # evaluation available from candle close
ts=sorted(tab)
def fm(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%d %H:%M")
START=int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000)
print("hours computed",len(ts),fm(ts[0]),"..",fm(ts[-1]))
print("-- timeline from 19.11 18:00 (raw bear bull net adx ret24 slope ds)")
for t in ts:
    if t>=START-6*HOUR:
        f=tab[t]; print(fm(t),f["raw"],f["bear"],f["bull"],f["bull"]-f["bear"],f["adx"],f["ret24"],f["slope24_atr"],f["down_share"])
json.dump({str(t):tab[t] for t in ts},open("/tmp/regime_hist.json","w"))
d=json.load(open(P+"shadow.json"))["items"]
rows=[]
for x in d:
    if x.get("var") not in ("A",None): continue
    p=x.get("p")
    if p and p.get("legacy"): continue
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: pp=p;src="in"
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: pp=x["cf"];src="cf"
    else: continue
    if pp["t_in"]<START: continue
    t0=x.get("t0") or pp["t_in"]
    k=bisect.bisect_right(ts,t0-15*60000)-1
    if k<3: continue
    f=tab[ts[k]]; f3=tab[ts[k-3]]; f6=tab[ts[k-6]]
    sg=1 if x["side"]=="long" else -1
    net=f["bull"]-f["bear"]; net3=f3["bull"]-f3["bear"]; net6=f6["bull"]-f6["bear"]
    # hours since raw changed
    j=k
    while j>0 and tab[ts[j-1]]["raw"]==f["raw"]: j-=1
    rows.append(dict(tf=x["tf"],side=x["side"],kind=x["kind"],src=src,r=pp["r_mult"],mfe=pp["mfe_pct"]/pp["R_pct"],mae=pp["mae_pct"]/pp["R_pct"],raw=f["raw"],net=net,al=net*sg,d3=(net-net3)*sg,d6=(net-net6)*sg,adx=f["adx"],age=(t0-ts[j])/HOUR,rawsh=(f["raw"]!=f6["raw"]),sl=f["slope24_atr"]*sg,ret=f["ret24"]*sg,st_old=(x.get("rg") or {}).get("regime"),t=t0))
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
b=lambda a:"a<=-3" if a<=-3 else ("a-2..-1" if a<0 else ("a0" if a==0 else ("a1..2" if a<=2 else "a>=3")))
grp("raw regime at signal x side",lambda q:(q["raw"],q["side"]))
grp("ALL: aligned net score (bull-bear, sign by side)",lambda q:b(q["al"]))
grp("5m only: aligned net score",lambda q:b(q["al"]),lambda q:q["tf"]=="5m")
grp("flat only: aligned net score",lambda q:b(q["al"]),lambda q:q["raw"]=="flat")
grp("flat only, 5m: aligned",lambda q:b(q["al"]),lambda q:q["raw"]=="flat" and q["tf"]=="5m")
grp("momentum of bias over 3h (d3, + = bias moving toward the trade side)",lambda q:"d3>0" if q["d3"]>0 else ("d3=0" if q["d3"]==0 else "d3<0"))
grp("momentum over 6h",lambda q:"d6>0" if q["d6"]>0 else ("d6=0" if q["d6"]==0 else "d6<0"))
grp("raw regime changed within last 6h",lambda q:"changed6h" if q["rawsh"] else "stable6h")
grp("raw regime age buckets",lambda q:"<3h" if q["age"]<3 else ("3-12h" if q["age"]<12 else ">=12h"))
grp("slope24 aligned (ATR) buckets",lambda q:"sl<-1" if q["sl"]<-1 else ("sl-1..1" if q["sl"]<1 else "sl>=1"))
grp("ret24 aligned buckets",lambda q:"ret<-1%" if q["ret"]<-1 else ("ret-1..1%" if q["ret"]<1 else "ret>=1%"))
grp("old regime label (as stored) x side",lambda q:(q["st_old"],q["side"]))
