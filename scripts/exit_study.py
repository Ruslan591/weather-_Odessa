# exit_study.py - broad test of exit rules (long only) on 5m data, many pairs. Run on VPS: /opt/trading-bot/venv/bin/python exit_study.py
import json,urllib.request,time,os,sys,random
import numpy as np,pandas as pd
DAYS=int(os.environ.get('DAYS','30'));NP=int(os.environ.get('NP','50'));FEE=0.10;CACHE='/tmp/estudy';os.makedirs(CACHE,exist_ok=True)
def get(u):
    for host in ('api.binance.com','data-api.binance.vision'):
        try: return json.load(urllib.request.urlopen(u.replace('api.binance.com',host),timeout=25))
        except Exception as e: err=e
    raise err
def klines(sym,t0,t1):
    fn=f'{CACHE}/{sym}.csv'
    if os.path.exists(fn): return pd.read_csv(fn)
    out=[];s=t0
    while s<t1:
        r=get(f'https://api.binance.com/api/v3/klines?symbol={sym}&interval=5m&startTime={s}&limit=1000')
        if not r: break
        out+=r;s=r[-1][0]+1;time.sleep(0.05)
        if len(r)<1000: break
    d=pd.DataFrame([[x[0],float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5]),float(x[9])] for x in out],columns=['t','o','h','l','c','v','tb'])
    d.to_csv(fn,index=False);return d
def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def add(d):
    c=d.c;tr=pd.concat([d.h-d.l,(d.h-c.shift()).abs(),(d.l-c.shift()).abs()],axis=1).max(axis=1)
    d['atr']=tr.ewm(alpha=1/14,adjust=False).mean()
    dl=c.diff();up=dl.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();dn=(-dl.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d['rsi']=100-100/(1+up/dn.replace(0,np.nan))
    rmin=d.rsi.rolling(14).min();rmax=d.rsi.rolling(14).max();d['k']=((d.rsi-rmin)/(rmax-rmin).replace(0,np.nan)*100).rolling(3).mean()
    d['ema20']=ema(c,20);d['ema50']=ema(c,50)
    m=c.rolling(20).mean();s=c.rolling(20).std(ddof=0);d['pb']=(c-(m-2*s))/(4*s).replace(0,np.nan)
    macd=ema(c,12)-ema(c,26);d['mh']=macd-ema(macd,9)
    tp=(d.h+d.l+d.c)/3;ma=tp.rolling(20).mean();md=(tp-ma).abs().rolling(20).mean();d['cci']=(tp-ma)/(0.015*md)
    d['vr']=d.v/d.v.rolling(20).mean();rng=(d.h-d.l).replace(0,np.nan);d['uw']=(d.h-d[['o','c']].max(axis=1))/rng
    d['dist']=(c-d.ema20)/d.atr
    d['hi48']=d.h.rolling(48).max().shift(1)
    d['score']=(d.rsi>75).astype(int)+(d.pb>1.0).astype(int)+((d.vr>=2.5)&(d.uw>=0.35)).astype(int)+(d.k>90).astype(int)+(d.cci>200).astype(int)+(d.dist>4).astype(int)
    return d
def signals(d,kind):
    idx=[];last=-99
    A=d.to_dict('list')
    for i in range(60,len(d)-2):
        if i-last<24: continue
        if kind=='brk':
            ok=A['c'][i]>A['hi48'][i] and A['vr'][i]>=2 and A['c'][i]>A['ema20'][i]
        else:  # pullback to ema20 in uptrend
            ok=A['ema20'][i]>A['ema50'][i] and A['l'][i]<=A['ema20'][i]*1.001 and A['c'][i]>A['ema20'][i] and A['c'][i]>A['o'][i] and A['rsi'][i]<55
        if ok and not np.isnan(A['atr'][i]): idx.append(i);last=i
    return idx
def run(d,i0,rule,A):
    ei=i0+1;entry=A['o'][ei];risk=max(1.5*A['atr'][i0],0.006*entry);stop=entry-risk;hh=entry;be=False;N=len(A['c'])
    for i in range(ei,min(N-1,ei+288)):
        if A['l'][i]<=stop: px=stop;break
        hh=max(hh,A['h'][i])
        if not be and hh>=entry+1.5*risk: be=True;stop=max(stop,entry*1.002)
        if rule=='tp2R' and hh>=entry+2*risk: px=entry+2*risk;break
        if rule!='tp2R' and rule!='stop_be' and i>ei:
            if sig(rule,A,i,hh,entry,risk): px=A['o'][i+1];break
    else: px=A['c'][min(N-1,ei+288)-1] if True else None
    net=(px/entry-1)*100-FEE;mfe=(hh/entry-1)*100-FEE
    return net,mfe,risk/entry*100
def sig(rule,A,i,hh,entry,risk):
    c=A['c'][i];prof=(hh-entry)/risk
    if rule.startswith('chand'):
        k=float(rule[5:]);return prof>=0.5 and c<hh-k*A['atr'][i]
    if rule.startswith('tpct'):
        k=float(rule[4:]);return prof>=0.5 and c<hh*(1-k/100)
    if rule=='ema20': return prof>=1.0 and c<A['ema20'][i] and A['c'][i-1]<A['ema20'][i-1]
    if rule=='rsi_roll': 
        w=A['rsi'][max(0,i-12):i+1];return max(w)>75 and A['rsi'][i]<65
    if rule=='climax': return A['vr'][i]>=2.5 and A['uw'][i]>=0.4 and A['h'][i]>=hh*0.995 and prof>=1.0
    if rule=='adapt':
        sc=max(A['score'][max(0,i-3):i+1]);k=4.0 if sc<=1 else (2.0 if sc==2 else 1.0)
        return prof>=0.5 and c<hh-k*A['atr'][i]
    if rule=='adapt2':
        sc=max(A['score'][max(0,i-3):i+1]);k=3.0 if sc<=1 else (1.5 if sc==2 else 0.75)
        return prof>=0.5 and c<hh-k*A['atr'][i]
    if rule=='adapt_ema':  # tighten to EMA20 exit when overbought
        sc=max(A['score'][max(0,i-6):i+1])
        if sc>=3: return c<A['c'][i-1] and c<A['o'][i]
        return prof>=0.5 and c<hh-4*A['atr'][i]
    return False
RULES=['stop_be','tp2R','chand2','chand3','chand4','chand6','tpct1.5','tpct3','ema20','rsi_roll','climax','adapt','adapt2','adapt_ema']
def main():
    tk=get('https://api.binance.com/api/v3/ticker/24hr')
    u=[x for x in tk if x['symbol'].endswith('USDT') and not any(s in x['symbol'] for s in ('UPUSDT','DOWNUSDT','USDCUSDT','FDUSD','TUSD','EURUSDT','USDPUSDT')) and 3e6<float(x['quoteVolume'])<2e8]
    u=sorted(u,key=lambda x:-abs(float(x['priceChangePercent'])))
    random.seed(1);pool=[x['symbol'] for x in u[:150]];random.shuffle(pool);syms=pool[:NP]
    t1=int(time.time()*1000);t0=t1-DAYS*86400*1000
    res={k:{r:[] for r in RULES} for k in ('brk','pb')}
    for n,sy in enumerate(syms):
        try: d=add(klines(sy,t0,t1))
        except Exception as e: print('skip',sy,e);continue
        if len(d)<1000: continue
        A=d.to_dict('list')
        for kind in ('brk','pb'):
            for i0 in signals(d,kind):
                for r in RULES:
                    net,mfe,rk=run(d,i0,r,A);res[kind][r].append((A['t'][i0],net,mfe,rk))
        print(n,sy,flush=True)
    for kind in res:
        base=res[kind]['stop_be'];print(f'\n##### entry={kind} trades={len(base)} avg risk {np.mean([x[3] for x in base]):.2f}% avg MFE(net) {np.mean([x[2] for x in base]):.2f}%')
        ts=sorted(x[0] for x in base);mid=ts[len(ts)//2] if ts else 0
        print(f'{"rule":10s} {"n":>4s} {"mean%":>7s} {"med%":>7s} {"win%":>5s} {"PF":>5s} {"half1":>7s} {"half2":>7s} {"capt%":>6s}')
        for r in RULES:
            a=res[kind][r]
            if not a: continue
            v=np.array([x[1] for x in a]);m=np.array([x[2] for x in a]);t=np.array([x[0] for x in a])
            gp=v[v>0].sum();gl=-v[v<0].sum()
            cap=np.nanmean(np.where(m>1.0,v/m,np.nan)) if (m>1.0).any() else float('nan')
            print(f'{r:10s} {len(v):4d} {v.mean():7.3f} {np.median(v):7.3f} {100*(v>0).mean():5.1f} {gp/gl if gl>0 else 9:5.2f} {v[t<mid].mean():7.3f} {v[t>=mid].mean():7.3f} {100*cap:6.1f}')
if __name__=="__main__": main()
