import json,datetime
P="/opt/trading-bot/positions_regr/"
print(open(P+"shadow_bal.json").read()[:600])
tr=json.load(open("/opt/trading-bot/live/data/shadow_bal_trades.json"))
print("journal",len(tr))
d=json.load(open(P+"shadow.json")); its=d["items"]; print("items",len(its))
import collections
c=collections.Counter((x.get("status"),x.get("var")) for x in its); print(dict(c))
x=[i for i in its if i.get("status")=="closed" and i.get("p")][-1]
print(json.dumps(x,ensure_ascii=True)[:3000])
ts=[ (i.get("p") or {}).get("t_in") for i in its if (i.get("p") or {}).get("t_in")]
print("min t_in",datetime.datetime.utcfromtimestamp(min(ts)/1000),"max",datetime.datetime.utcfromtimestamp(max(ts)/1000))
