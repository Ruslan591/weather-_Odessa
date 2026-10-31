
import json,urllib.request
d=json.load(urllib.request.urlopen("http://localhost:8091/api/runs",timeout=120))
a=d["accounts"]["vp"]
print("acct keys", list(a.keys())[:25])
for k in ("balance","equity","n","taken","closed","start"):
    if k in a: print(k, a[k])
vp=[r for r in d["runs"] if r.get("track")=="vp" and r.get("stop_ms") is None]
print("vp runs", len(vp))
for r in vp:
    tr=r.get("trades") or []
    if tr: print(r["sym"], r["cfg"]["tf"], [(t["side"], t.get("tag"), round(t["net"],2), t["open"]) for t in tr])
