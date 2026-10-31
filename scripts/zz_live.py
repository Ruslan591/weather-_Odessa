import sys, os, time, asyncio, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
import classic_panel as cp, classic_vp as vpm
now = int(time.time()*1000)
def ts(ms): return dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%d.%m %H:%M")
async def go(sym):
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try: return await cp.fetch_back(sym, "5m", 1793318400000 - 1300*300000 - 300*300000)
    finally: await cp.SES.close()
for sym in ("PHAUSDT","REZUSDT","CHIPUSDT"):
    df,_ = asyncio.run(go(sym)); anc = 1793318400000 - 1300*300000
    df = df[df["t"]>=anc].reset_index(drop=True)
    h,l,t = df["h"].values, df["l"].values, df["t"].values
    piv = vpm.zigzag(h,l,12,0.2,3)
    print(sym, "window", ts(int(t[0])), "->", ts(int(t[-1])), "pivots", len(piv))
    byday = {}
    for p in piv: byday[ts(int(t[p["conf"]]))[:5]] = byday.get(ts(int(t[p["conf"]]))[:5],0)+1
    print("  pivots by day (confirm):", byday, "last conf", ts(int(t[piv[-1]["conf"]])) if piv else None)
