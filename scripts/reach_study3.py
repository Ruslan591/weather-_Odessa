import json, sys, time, urllib.request, statistics as st, collections
D='/opt/trading-bot/positions_regr/'
BASE="https://data-api.binance.vision/api/v3/klines"
pos=json.load(open(D+'positions.json')); orders={o['id']:o for o in json.load(open(D+'orders.json'))}
def kl(sym,start,limit):
    sy=sym if sym.endswith("USDT") else sym+"USDT"; u="%s?symbol=%s&interval=5m&limit=%d&startTime=%d"%(BASE,sy,limit,start)
    for i in range(3):
        try: return json.load(urllib.request.urlopen(u,timeout=20))
        except Exception: time.sleep(1)
    return []
import sys
sys.stdout.reconfigure(line_buffering=True)
FR=[round(0.1+0.05*i,2) for i in range(19)]    # 0.10 .. 1.00
rows=[]
for p in pos:
    o=orders.get(p.get('order_id'))
    if not o or not o.get('chan') or p.get('t_out') is None: continue
    ch=o['chan']; t=p['t_in']
    try:
        R=ch['upper']['p1']+ch['upper']['s']*(t-ch['upper']['t1']); S=ch['lower']['p1']+ch['lower']['s']*(t-ch['lower']['t1'])
    except Exception: continue
    H=R-S
    if H<=0: continue
    long=p['side']=='long'; s=1 if long else -1; e=p['entry']; stop=p['stop0']; risk=abs(e-stop)
    if risk<=0 or (e-stop)*s<=0: continue
    ks=[k for k in kl(p['sym'],t,60) if k[0]>t]
    if len(ks)<30: continue
    line=S if long else R
    res={}
    for f in FR:
        tp=line+s*f*H; gain=(tp-e)*s
        if gain<=0.05*risk: res[f]=None; continue
        out=None
        for n,k in enumerate(ks[:48],1):
            hi,lo,cl=float(k[2]),float(k[3]),float(k[4])
            hs=(lo<=stop) if long else (hi>=stop); ht=(hi>=tp) if long else (lo<=tp)
            if hs: out=-1.0; break
            if ht: out=gain/risk; break
        if out is None: out=(float(ks[:48][-1][4])-e)*s/risk
        res[f]=out
    # unmanaged MFE until stop (fraction of H from entry)
    mfe=0.0
    for k in ks[:48]:
        hi,lo=float(k[2]),float(k[3])
        if (lo<=stop) if long else (hi>=stop): break
        mfe=max(mfe,((hi-e) if long else (e-lo))/H)
    rows.append(dict(sym=p['sym'],side=p['side'],res=res,mfe=mfe,risk_h=risk/H,Hatr=H/o['atr'] if o.get('atr') else 0,start=((e-S)/H if long else (R-e)/H),mgd=p.get('r_mult')))
print('trades',len(rows),'median risk/H %.2f'%st.median([r['risk_h'] for r in rows]))
print('unmanaged MFE before stop (fraction of channel): '+' '.join('P>=%.2f:%.0f%%'%(f,100*sum(r['mfe']>=f for r in rows)/len(rows)) for f in (0.1,0.25,0.5,0.75,1.0)))
print('target | n | avg R | win%% | (R per trade, 48 bars, initial stop, no fees)')
best=None
for f in FR:
    xs=[r['res'][f] for r in rows if r['res'].get(f) is not None]
    if len(xs)<20: continue
    w=100*sum(x>0 for x in xs)/len(xs); a=sum(xs)/len(xs)
    print('f=%.2f n=%d avgR=%+.3f win=%.0f%%'%(f,len(xs),a,w))
    if best is None or a>best[1]: best=(f,a)
print('best',best)
print('with managed r_mult avg:',round(sum((r['mgd'] or 0) for r in rows)/len(rows),3))
for name,sel in (('narrow Hatr<median',lambda r:r['Hatr']<st.median([x['Hatr'] for x in rows])),('wide',lambda r:r['Hatr']>=st.median([x['Hatr'] for x in rows])),('long',lambda r:r['side']=='long'),('short',lambda r:r['side']=='short')):
    rs=[r for r in rows if sel(r)]; out=[]
    for f in (0.25,0.5,0.75,1.0):
        xs=[r['res'][f] for r in rs if r['res'].get(f) is not None]
        out.append('f%.2f:%+.2f(n%d)'%(f,sum(xs)/len(xs),len(xs)) if xs else 'f%.2f:-'%f)
    print(name,len(rs),' '.join(out))
