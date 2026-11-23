import sys,json,collections,statistics as S,datetime as D,bisect,time
sys.path.insert(0,"/opt/tg-notify")
import tg_regime as R
HOUR=3600000
btc=R.klines("BTC","1h",500)
alts={s:{int(k[0]):float(k[4]) for k in R.klines(s,"1h",200)} for s in R.BASKET}
bt=[int(k[0]) for k in btc]; H=[float(k[2]) for k in btc]; Lo=[float(k[3]) for k in btc]; C=[float(k[4]) for k in btc]
now=int(time.time()*1000); n=len(bt)
if bt[-1]+HOUR>now: n-=1
tab={}
for i in range(220,n):
    t=bt[i]; chg=[]
    for s,m in alts.items():
        if t in m and (t-24*HOUR) in m: chg.append(m[t]/m[t-24*HOUR]-1)
    ds=(sum(1 for x in chg if x<0)/len(chg)) if len(chg)>=12 else None
    f=R.regime_at(H[:i+1],Lo[:i+1],C[:i+1],ds,None)
    if f: tab[t+HOUR]=f
ts=sorted(tab)
P="/opt/trading-bot/positions_regr/"
d=json.load(open(P+"shadow.json"))["items"]
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
    t0=x.get("t0") or pp["t_in"]; k=bisect.bisect_right(ts,t0-15*60000)-1
    if k<0: continue
    f=tab[ts[k]]; sg=1 if x["side"]=="long" else -1
    ft=x.get("feat") or {}; b1=x.get("b1") or {}
    rs=ft.get("rsi5"); ars=(rs if sg>0 else 100-rs) if rs is not None else None
    rows.append(dict(sn=x.get("sn"),tf=x["tf"],r=pp["r_mult"],t=pp["t_in"],raw=f["raw"],side=x["side"],al=(f["bull"]-f["bear"])*sg,
      rsi_ok=b1.get("rsi_ok"),strict=b1.get("strict"),counter=ft.get("counter"),ars=ars,width=ft.get("width"),rr=ft.get("rr")))
rows.sort(key=lambda q:q["t"])
print("rows",len(rows),"half split at",D.datetime.fromtimestamp(rows[len(rows)//2]["t"]/1000,D.UTC))
def st(v):
    if not v: return "n=  0"
    r=[q["r"] for q in v]
    return "n=%3d win=%2.0f%% sumR=%6.2f avg=%5.2f"%(len(r),100*sum(1 for a in r if a>0)/len(r),sum(r),sum(r)/len(r))
side_ok=lambda q:not((q["raw"]=="down" and q["side"]=="long") or (q["raw"]=="up" and q["side"]=="short"))
F={
 "side(binary)":side_ok,
 "score>=0":lambda q:q["al"]>=0,
 "btc rsi_ok":lambda q:q["rsi_ok"] in (1,True,None),
 "btc strict":lambda q:q["strict"] in (1,True,None),
 "not counter":lambda q:not q["counter"],
 "rsi5 aligned>=30":lambda q:q["ars"] is None or q["ars"]>=30,
 "width<8":lambda q:q["width"] is None or q["width"]<8,
 "rr<6":lambda q:q["rr"] is None or q["rr"]<6,
}
combos=[("none",[]),("side(binary)",["side(binary)"]),("score>=0",["score>=0"]),("old BTC rsi_ok",["btc rsi_ok"]),("old BTC strict",["btc strict"]),("old counter",["not counter"]),("old rsi5>=30",["rsi5 aligned>=30"]),
 ("side+rsi_ok+counter+rsi5",["side(binary)","btc rsi_ok","not counter","rsi5 aligned>=30"]),
 ("score+rsi_ok+counter+rsi5",["score>=0","btc rsi_ok","not counter","rsi5 aligned>=30"]),
 ("side+strict+counter+rsi5",["side(binary)","btc strict","not counter","rsi5 aligned>=30"]),
 ("score+strict+counter+rsi5",["score>=0","btc strict","not counter","rsi5 aligned>=30"]),
 ("score+rsi_ok+counter+rsi5+width<8",["score>=0","btc rsi_ok","not counter","rsi5 aligned>=30","width<8"]),
 ("side+rsi_ok+counter+rsi5+width<8",["side(binary)","btc rsi_ok","not counter","rsi5 aligned>=30","width<8"]),
 ("width<8 only",["width<8"])]
h=len(rows)//2
for sel_name,sel in (("ALL TF",lambda q:True),("5m only",lambda q:q["tf"]=="5m")):
    sub=[q for q in rows if sel(q)]; hh=len(sub)//2
    print("=====",sel_name,len(sub))
    for nm,fs in combos:
        keep=[q for q in sub if all(F[f](q) for f in fs)]
        drop=[q for q in sub if q not in keep]
        k1=[q for q in keep if q in sub[:hh]]; k2=[q for q in keep if q in sub[hh:]]
        d1=[q for q in drop if q in sub[:hh]]; d2=[q for q in drop if q in sub[hh:]]
        print("%-36s KEEP %s | DROP %s"%(nm,st(keep),st(drop)))
        print("%-36s   halves: keep 1st %s | 2nd %s ; drop 1st %s | 2nd %s"%("",st(k1)[5:],st(k2)[5:],st(d1)[5:],st(d2)[5:]))
