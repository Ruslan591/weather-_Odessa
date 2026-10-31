
import json,urllib.request
d=json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
for r in d["runs"]:
    if r.get("sym")=="PHAUSDT" and r.get("track")=="vp":
        print(r["id"], r.get("name"), r["cfg"].get("tf"), "start", r.get("start_ms"), "stop", r.get("stop_ms"))
        print({k:v for k,v in r["cfg"].items() if k.startswith(("vp_","zz_"))})
        st=r.get("stats") or {}
        print("stats", json.dumps(st)[:300])
        for t in (r.get("trades") or [])[:20]:
            print("  trade", t.get("t_in"), t.get("side"), t.get("tag"), round(t.get("net",0),2), t.get("open"))
print("vp runs total", sum(1 for r in d["runs"] if r.get("track")=="vp"))
print("accounts keys", list(d["accounts"].keys()) if isinstance(d["accounts"],dict) else type(d["accounts"]))
