
import json,urllib.request
d=json.load(urllib.request.urlopen("http://localhost:8091/api/runs",timeout=120))
print("accounts keys", list(d["accounts"].keys()), "load", str(d.get("load"))[:200])
a=d["accounts"].get("vp") or {}
for k,v in a.items():
    if not isinstance(v,(list,dict)): print(k, v)
vp=[r for r in d["runs"] if r.get("track")=="vp" and r.get("stop_ms") is None]
print("vp runs", len(vp))
for r in vp:
    tr=r.get("trades") or []
    if tr: print(r["sym"], r["cfg"]["tf"], [(t["side"], t.get("tag"), round(t["net"],2), t["open"]) for t in tr])
