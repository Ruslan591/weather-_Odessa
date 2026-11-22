import json
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))
L=d["items"]
C=[x for x in L if x.get("status")=="closed" and "p" in x]
print(len(C))
x=C[-1]
def sh(o,dep=0):
    if isinstance(o,dict): return {k:sh(v,dep+1) for k,v in o.items() if k not in("rows","feat","ch")}
    if isinstance(o,list): return [sh(v,dep+1) for v in o[:6]]+(["..%d"%len(o)] if len(o)>6 else [])
    return o
print(json.dumps(sh({k:v for k,v in x.items() if k in("id","sn","sym","tf","kind","side","var","status","p","pb","gt","ref","reg","plan","target","setup","w","o","o0","g","t_sig","t_fill","mfe_r","mae_r","why")}),ensure_ascii=True)[:6000])
F=[y for y in L if y.get("status")=="filtered"]
print(json.dumps(sh({k:v for k,v in F[-1].items() if k in("id","sn","var","why","cf","t_end","gt")}),ensure_ascii=True)[:2500])
