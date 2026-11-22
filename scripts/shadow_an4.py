import json,collections,statistics as S,datetime as D
P="/opt/trading-bot/positions_regr/"
def lst(d):
    if isinstance(d,list): return d
    for k in("orders","items","positions"):
        if k in d and isinstance(d[k],list): return d[k]
    for v in d.values():
        if isinstance(v,list): return v
    return list(d.values())
O=lst(json.load(open(P+"orders.json")))
print("orders",len(O),"keys sample",sorted(O[-1].keys())[:40])
om={}
for o in O:
    if isinstance(o,dict) and "id" in o: om[o["id"]]=o
POS=json.load(open(P+"positions.json"))
done=[x for x in POS if x.get("status")=="closed" and x.get("r_mult") is not None]
print("positions closed",len(done))
def stat(v):
    r=[x[0] for x in v]; n=len(r)
    if n==0: return "n=0"
    m=S.mean(r); se=(S.pstdev(r)/n**.5) if n>1 else 0
    return "n=%d win=%.0f%% sumR=%.2f avg=%.2f se=%.2f"%(n,100*sum(1 for q in r if q>0)/n,sum(r),m,se)
g=collections.defaultdict(list)
miss=0
for x in done:
    o=om.get(x.get("order_id"))
    if not o: miss+=1; continue
    g[(o.get("tf") or "?",o.get("setup") or "?",x["side"])].append((x["r_mult"],x["t_in"]))
print("no order match",miss)
tot=[]
for k,v in sorted(g.items(),key=lambda a:-len(a[1])):
    if len(v)>=8: print("REAL",k,stat(v))
v=g.get(("5m","bounce","short"),[])
v.sort(key=lambda a:a[1]); h=len(v)//2
print("REAL 5m bounce short halves:",stat(v[:h]),"|",stat(v[h:]))
# all real 5m by side/setup done above; also overall
allr=[(x["r_mult"],x["t_in"]) for x in done]; print("REAL all",stat(allr))
# shadow: all signals bounce short 5m incl cf
d=json.load(open(P+"shadow.json"))["items"]
def res(x):
    if x.get("status")=="closed" and x.get("p") and x["p"].get("r_mult") is not None: return x["p"]["r_mult"],"in"
    if x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: return x["cf"]["r_mult"],"cf"
    return None
G=collections.defaultdict(list)
for x in d:
    r=res(x)
    if r is None: continue
    G[(x.get("var"),x["tf"],x["kind"],x["side"],r[1])].append((r[0],0))
for k,v in sorted(G.items(),key=lambda a:str(a[0])):
    if len(v)>=4: print("SHADOW",k,stat(v))
# paths replay on entered shadows
Pl=[json.loads(l) for l in open(P+"shadow_paths.jsonl").read().splitlines() if l.strip()]
print("paths",len(Pl))
def replay(p,stop,tp,cost=0.05):
    for t,hi,lo,c in p["hlc"]:
        if lo<=-stop: return -stop-cost,1
        if hi>=tp: return tp-cost,1
    return p["r"],0
for stop,tp in ((1,1),(1,0.75),(1,1.5),(1,2),(0.75,0.75),(1.5,1.5)):
    for lab,sel in (("all",lambda p:True),("5m bounce short",lambda p:p["tf"]=="5m" and p["kind"]=="bounce" and p["side"]=="short")):
        rs=[replay(p,stop,tp) for p in Pl if sel(p)]
        if not rs: continue
        n=len(rs);u=sum(1 for a,b in rs if b==0)
        print("REPLAY stop %.2f tp %.2f %s n=%d unresolved(actual used)=%d sumR=%.2f avg=%.2f"%(stop,tp,lab,n,u,sum(a for a,b in rs),sum(a for a,b in rs)/n))
print("ACTUAL paths sumR %.2f"%sum(p["r"] for p in Pl))
