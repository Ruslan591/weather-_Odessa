import json
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))
print(type(d).__name__, list(d.keys())[:10])
it=d["items"]
print(type(it).__name__, len(it))
L=list(it.values()) if isinstance(it,dict) else it
import collections
print(collections.Counter(str(x.get("st") or x.get("status")) for x in L))
for x in L:
    if (x.get("st") or x.get("status"))=="closed" or x.get("closed"):
        s=json.dumps(x,ensure_ascii=True)
        print(s[:3500]); break
else:
    print(json.dumps(L[-1],ensure_ascii=True)[:3500])
