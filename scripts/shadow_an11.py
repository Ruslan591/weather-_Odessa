import json,collections
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
C=[x for x in d if x.get("status") in("closed","filtered") and x.get("var") in("A",None) and not (x.get("p") or {}).get("legacy") and x.get("sn",0)>=13]
print(len(C))
ks=collections.Counter(k for x in C for k in x)
print(dict(ks))
x=[y for y in C if y["tf"]=="5m" and y.get("status")=="closed"][-1]
def sh(o,dep=0):
    if isinstance(o,dict): return {k:sh(v,dep+1) for k,v in o.items() if k not in("p","pb","cf","plan","o","o0","path","rows")}
    if isinstance(o,list): return [sh(v,dep+1) for v in o[:8]]
    return o
print(json.dumps(sh(x),ensure_ascii=True)[:3500])
for k in ("feat","b1","v","verdict","conds","htf","gate","gt"):
    if k in x: print("KEY",k,json.dumps(x[k],ensure_ascii=True)[:900])
