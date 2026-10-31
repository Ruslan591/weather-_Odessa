import sys, os, json, asyncio, time, urllib.request
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
import classic_panel as cp, classic_strategy as cs, classic_vp as vpm
now = int(time.time() * 1000); DAY = 86400000
d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
r = [x for x in d["runs"] if x.get("track") == "vp" and x["cfg"].get("tf") == "5m" and x["sym"] == "PHAUSDT" and x.get("stop_ms") is None][0]
print("cfg keys:", sorted(k for k in r["cfg"] if k.startswith(("vp_", "zz_"))))
print({k: v for k, v in r["cfg"].items() if k.startswith(("vp_", "zz_")) and k != "vp_starts"})
print("other cfg:", {k: v for k, v in r["cfg"].items() if not k.startswith(("vp_", "zz_"))})
async def ld(days):
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    try:
        t0 = time.time(); df, _ = await cp.fetch_back("PHAUSDT", "5m", now - days * DAY - 1500 * 300000)
        print("fetch %.1fs rows %d first %s" % (time.time() - t0, len(df), df["t"].iloc[0])); return df
    finally: await cp.SES.close()
for days in (60,):
    df = asyncio.run(ld(150))
    sub = df[df["t"] >= now - (days * DAY + 1500 * 300000)].reset_index(drop=True)
    P = dict(cs.PARAMS, **dict(r["cfg"], sym="PHAUSDT")); P["sim_from_ms"] = now - days * DAY
    t0 = time.time(); trs = cs.simulate(sub, now, P); print("days", days, "rows", len(sub), "trades", len(trs), "sec %.1f" % (time.time() - t0))
