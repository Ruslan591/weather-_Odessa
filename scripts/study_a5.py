import json,base64,urllib.request
P="/opt/trading-bot/positions_regr/"
tr=json.load(open("/opt/trading-bot/live/data/shadow_bal_trades.json"))
its={str(i["id"]):i for i in json.load(open(P+"shadow.json"))["items"] if i.get("var") in ("A",None)}
out=[]
for k,r in tr.items():
    x=its.get(r["id"]); r=dict(r)
    if x:
        src=x.get("cf") if r["k"]=="cf" else x.get("p")
        src=src or {}; f=x.get("feat") or {}; rg=x.get("rg") or {}; b1=x.get("b1") or {}
        r.update(kind=x.get("kind"),setup=x.get("setup"),rsi5=f.get("rsi5"),beyond=f.get("beyond"),body=f.get("body"),width=f.get("width"),rr=f.get("rr"),counter=f.get("counter"),h=f.get("h"),rgs=rg.get("strength"),b1ok=b1.get("ok"),b1rsi=b1.get("rsi"),rpct=src.get("R_pct"),mfe=src.get("mfe_pct"),mae=src.get("mae_pct"),reason=src.get("reason"),st=x.get("status"),var="A",btc_rsd=b1.get("rsd"),cols=b1.get("cols"))
    out.append(r)
body=json.dumps(out)
tok=[l.split("=",1)[1].strip() for l in open("/etc/vps-github-bridge/token") if "=" in l][0]
H={"Authorization":"token "+tok,"Accept":"application/vnd.github+json","Content-Type":"application/json"}
u="https://api.github.com/repos/ruslan591/weather-_Odessa/contents/data/study_j.json"
try: sha=json.load(urllib.request.urlopen(urllib.request.Request(u,headers=H)))["sha"]
except Exception: sha=None
d={"message":"study journal","content":base64.b64encode(body.encode()).decode()}
if sha: d["sha"]=sha
urllib.request.urlopen(urllib.request.Request(u,method="PUT",data=json.dumps(d).encode(),headers=H))
print("ok",len(out),len(body),sum(1 for r in out if "kind" in r))
