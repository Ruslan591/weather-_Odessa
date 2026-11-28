import json
P="/opt/trading-bot/positions_regr/"
for f in ("shadow_in.jsonl","shadow_paths.jsonl","shadow_cfg.json"):
    L=open(P+f).read().splitlines(); print("==",f,len(L)); print(L[0][:700]); print(L[-1][:700])
tr=json.load(open("/opt/trading-bot/live/data/shadow_bal_trades.json"))
print(list(tr.items())[0])
d=json.load(open(P+"shadow.json")); its=d["items"]
ids=sorted(int(i["id"]) for i in its); print("ids",ids[0],ids[-1],len(ids))
x=[i for i in its if i["status"]=="filtered"][-1]; print(json.dumps({k:v for k,v in x.items() if k not in("rows","w","o")})[:1800])
print(json.dumps(x.get("cf"))[:800])
