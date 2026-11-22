import json,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
def f(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%m-%d %H:%M:%S")
rows=[]
for x in d:
    p=x.get("p")
    if x.get("status")=="closed":
        t=(p or x).get("t_in")
        rows.append((t,x.get("sn"),x.get("id"),x.get("var"),x.get("legacy") or (p or {}).get("legacy"),x["sym"],x["tf"],x["kind"],x["side"]))
rows.sort(key=lambda r:r[0])
for r in rows[:14]: print(f(r[0]),r[1:])
print("closed total",len(rows))
