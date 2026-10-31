import sys, os, json, asyncio, time, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
import classic_panel as cp, classic_vp as vpm
SYM = sys.argv[1]; now = int(time.time()*1000)
def ts(ms): return dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%d.%m %H:%M")
async def go():
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try: return await cp.fetch_back(SYM, "5m", now - 120*86400000)
    finally: await cp.SES.close()
df,_ = asyncio.run(go())
df = df[df["t"] >= now-120*86400000].reset_index(drop=True)
h,l,t = df["h"].values, df["l"].values, df["t"].values
for dev,dep,bk in ((0.2,12,3),(0.6,12,3),(1.0,12,3)):
    piv = vpm.zigzag(h,l,dep,dev,bk)
    print("dev",dev,"pivots",len(piv),"last 6:",[(p["k"],ts(int(t[p["i"]])),"conf",ts(int(t[p["conf"]]))) for p in piv[-6:]])
    # count by month
    from collections import Counter
    print(Counter(ts(int(t[p["i"]]))[3:5] for p in piv))
