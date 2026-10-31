import sys, os, time, asyncio, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic"); os.chdir("/opt/trading-bot/classic")
import numpy as np, aiohttp
import classic_panel as cp
SYM = sys.argv[1]; now = int(time.time()*1000)
def ts(ms): return dt.datetime.fromtimestamp(ms/1000, dt.timezone.utc).strftime("%d.%m %H:%M")
async def go():
    cp.SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try: return await cp.fetch_back(SYM, "5m", now - 120*86400000)
    finally: await cp.SES.close()
df,_ = asyncio.run(go()); df = df[df["t"] >= now-120*86400000].reset_index(drop=True)
h,l,t = df["h"].values, df["l"].values, df["t"].values
print("nan", int(np.isnan(h).sum()), int(np.isnan(l).sum()), "min l", l.min(), ts(int(t[l.argmin()])), "max h", h.max(), ts(int(t[h.argmax()])))
r = h/np.maximum(l,1e-12); bad = np.nonzero(r>1.2)[0]; print("bars with h/l>1.2:", [(ts(int(t[i])), h[i], l[i]) for i in bad[:10]])
# gaps in time
dd = np.diff(t); gi = np.nonzero(dd != 300000)[0]; print("time gaps:", [(ts(int(t[i])), int(dd[i]/300000)) for i in gi[:10]])
# monthly median close
c = df["c"].values
for m in range(7,11):
    idx = [i for i in range(len(t)) if int(ts(int(t[i]))[3:5]) == m]
    if idx: print("month", m, "bars", len(idx), "med c", float(np.median(c[idx])), "range h/l", float(h[idx].max()/l[idx].min()))
# воспроизвести zigzag с отладкой после 17.09
n=len(h); dv=0.002; depth=12; back=3
d=0; ei=0; ep=0.0; last_i=-10**9; hi_i=lo_i=0; piv=[]
i0 = int(np.searchsorted(t, int(dt.datetime(2026,9,17,3,10,tzinfo=dt.timezone.utc).timestamp()*1000)))
for i in range(n):
    if d==0:
        if h[i]>h[hi_i]: hi_i=i
        if l[i]<l[lo_i]: lo_i=i
        if hi_i!=lo_i and h[hi_i]/l[lo_i]-1>=dv:
            if hi_i>lo_i: piv.append(("L",lo_i,i)); d,ei,ep=1,hi_i,h[hi_i]
            else: piv.append(("H",hi_i,i)); d,ei,ep=-1,lo_i,l[lo_i]
            last_i=piv[-1][1]
        continue
    if d==1:
        if h[i]>ep: ei,ep=i,h[i]
        elif ep-l[i]>=ep*dv and i-ei>=back and ei-last_i>=depth:
            piv.append(("H",ei,i)); last_i=ei; d=-1; j=ei+1+int(np.argmin(l[ei+1:i+1])); ei,ep=j,l[j]
    else:
        if l[i]<ep: ei,ep=i,l[i]
        elif h[i]-ep>=ep*dv and i-ei>=back and ei-last_i>=depth:
            piv.append(("L",ei,i)); last_i=ei; d=1; j=ei+1+int(np.argmax(h[ei+1:i+1])); ei,ep=j,h[j]
    if i in (i0+1, i0+50, i0+500, i0+3000, n-1): print("state at", ts(int(t[i])), "d",d,"ei",ts(int(t[ei])),"ep",ep,"last_i",ts(int(t[last_i])),"h",h[i],"l",l[i])
print("pivots", len(piv))
