import json, urllib.request, math
import numpy as np, pandas as pd
d=json.load(open('/tmp/runs.json'))
log=d['accounts']['both']['account']['log']
TFMS={'5m':300000,'15m':900000,'1h':3600000,'4h':14400000,'1d':86400000}
def kl(sym,tf,end,limit=1000):
    u=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={tf}&endTime={int(end)}&limit={limit}"
    try: r=json.load(urllib.request.urlopen(u,timeout=20))
    except Exception:
        u=u.replace('api.binance.com','data-api.binance.vision'); r=json.load(urllib.request.urlopen(u,timeout=20))
    df=pd.DataFrame(r,columns='t o h l c v ct qv n tb tq i'.split())
    for c in 'ohlcv': df[c]=df[c].astype(float)
    return df
def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi(c,n=14):
    dl=c.diff(); up=dl.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-dl.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn)
def feats(df,tf,t_ref):
    df=df[df.t+TFMS[tf]<=t_ref].reset_index(drop=True)
    if len(df)<30: return None
    c,h,l,o,v=df.c,df.h,df.l,df.o,df.v
    e20,e50,e200=ema(c,20),ema(c,50),ema(c,200)
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); atr=tr.ewm(alpha=1/14,adjust=False).mean()
    r=rsi(c); rs=r; st=(rs-rs.rolling(14).min())/(rs.rolling(14).max()-rs.rolling(14).min()+1e-12)*100; k=st.rolling(3).mean(); dd=k.rolling(3).mean()
    m=ema(c,12)-ema(c,26); sg=ema(m,9); hist=m-sg
    ma=c.rolling(20).mean(); sd=c.rolling(20).std(); bb=(c-(ma-2*sd))/(4*sd+1e-12); bw=4*sd/ma*100
    i=len(df)-1; px=c[i]
    f=dict(tf=tf,n=len(df),close=px,
      d_e20=(px/e20[i]-1)*100,d_e50=(px/e50[i]-1)*100,d_e200=(px/e200[i]-1)*100 if len(df)>=200 else None,
      e20_gt_e50=bool(e20[i]>e50[i]),e50_slope=(e50[i]/e50[i-5]-1)*100,
      rsi=r[i],stoch_k=k[i],stoch_d=dd[i],macd_h=hist[i]/px*100,macd_h_up=bool(hist[i]>hist[i-1]),macd_gt0=bool(m[i]>0),
      bb_pct=bb[i],bb_w=bw[i],atr_pct=atr[i]/px*100,atr_rel=atr[i]/atr.rolling(50).mean()[i],
      vol_rel=v[i]/v.rolling(20).mean()[i],cndl_body=(c[i]-o[i])/max(h[i]-l[i],1e-12),cndl_green=bool(c[i]>o[i]),
      rng_atr=(h[i]-l[i])/atr[i],
      hh20=bool(c[i]>=h[-21:-1].max()) if False else bool(c[i]>h[i-20:i].max()), ll20=bool(c[i]<l[i-20:i].min()),
      pos20=(px-l[i-19:i+1].min())/(h[i-19:i+1].max()-l[i-19:i+1].min()+1e-12),
      ret6=(px/c[i-6]-1)*100, ret24=(px/c[i-24]-1)*100)
    return {a:(round(b,4) if isinstance(b,float) else b) for a,b in f.items()}
out=[]
for t in log:
    sym,tf=t['sym'],t['tf']; tin=t['t_in']
    row=dict(sym=sym,tf=tf,side=t['side'],sig=t['sig'],pnl=t['pnl'],net=t['net'],open=t['open'],be=t['be'],t_in=tin,
             hour_utc=int((tin//3600000)%24),dow=int((tin//86400000+3)%7))
    out_f={}
    for ftf in ['5m','15m','1h','4h','1d']:
        try:
            df=kl(sym,ftf,tin); out_f[ftf]=feats(df,ftf,tin)
        except Exception as e: out_f[ftf]=str(e)
    # BTC context
    try:
        b=kl('BTCUSDT','1h',tin); b=b[b.t+3600000<=tin].reset_index(drop=True); bc=b.c
        row['btc_1h_d_e50']=round((bc.iloc[-1]/ema(bc,50).iloc[-1]-1)*100,3); row['btc_ret24h']=round((bc.iloc[-1]/bc.iloc[-25]-1)*100,3)
    except Exception as e: row['btc_err']=str(e)
    # path after entry
    try:
        df=kl(sym,tf,tin+TFMS[tf]*60); end=t['t_out']
        p=df[(df.t>=tin-TFMS[tf])&(df.t<=end)]
        row['mfe']=round((p.h.max()/t['p_in']-1)*100*(1 if t['side']=='L' else 0)+( (1-p.l.min()/t['p_in'])*100 if t['side']=='S' else 0),3)
        row['mae']=round(((p.l.min()/t['p_in']-1)*100) if t['side']=='L' else -((p.h.max()/t['p_in']-1)*100),3)
    except Exception as e: row['path_err']=str(e)
    row['f']=out_f; out.append(row)
json.dump(out,open('/tmp/diag.json','w'))
print(len(out))
# trade details from run
for t in log:
    for r in d['runs']:
        if r.get('id')==t['run']:
            for tr in r.get('trades',[]):
                if abs(tr.get('t_in',0)-t['kt'])<TFMS[t['tf']]*2 or tr.get('kt')==t['kt']:
                    print(t['sym'],t['tf'],json.dumps({k:v for k,v in tr.items() if not isinstance(v,(list,dict))},ensure_ascii=False)[:700])
                    for k,v in tr.items():
                        if isinstance(v,(list,dict)) and k not in('candles',): print('  ',k,json.dumps(v,ensure_ascii=False)[:300])
