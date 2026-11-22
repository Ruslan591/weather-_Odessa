import json
P="/opt/trading-bot/positions_regr/"
l=open(P+"shadow_paths.jsonl").read().splitlines()
print("paths lines",len(l)); print(l[0][:600]); print(l[-1][:600])
d=json.load(open(P+"positions.json"))
print(type(d).__name__, (list(d.keys())[:10] if isinstance(d,dict) else len(d)))
L=d if isinstance(d,list) else d.get("positions") or d.get("items") or list(d.values())[0]
print(len(L))
x=L[-1]
def sh(o):
    if isinstance(o,dict): return {k:sh(v) for k,v in o.items() if k not in("thesis","sw_c")}
    if isinstance(o,list): return [sh(v) for v in o[:3]]
    return o
print(json.dumps(sh(x),ensure_ascii=True)[:2500])
