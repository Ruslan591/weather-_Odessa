# pair_study.py - per-coin study: exhaustion sign precision, entry frequency, exit-rule stability by halves. needs exit_study.py in same dir
import sys,os,time
import numpy as np,pandas as pd
import exit_study as E
sym=sys.argv[1];days=int(sys.argv[2]) if len(sys.argv)>2 else 180
E.CACHE='/tmp/pstudy';os.makedirs(E.CACHE,exist_ok=True)
t1=int(time.time()*1000);t0=t1-days*86400*1000
raw=E.klines(sym,t0,t1);d=E.add(raw.copy());d['tbr']=d.tb/d.v.replace(0,np.nan)
d['dt']=pd.to_datetime(d.t,unit='ms');N=len(d)
print(f'##### {sym}: {N} bars 5m, {d.dt.iloc[0]} .. {d.dt.iloc[-1]} ({N/288:.0f} days); price {d.c.iloc[0]:.5g} -> {d.c.iloc[-1]:.5g}')
# A) exhaustion sign precision
H=36
fwdmax=pd.Series([d.h.iloc[i+1:i+1+H].max() if i+H<N else np.nan for i in range(N)])
fwdmin=pd.Series([d.l.iloc[i+1:i+1+H].min() if i+H<N else np.nan for i in range(N)])
bk=pd.Series([d.h.iloc[max(0,i-H):i].max() for i in range(N)])
ru=(d.dist>2)&(d.c>d.ema50)   # run-up state
def stats(mask,name):
    m=mask&fwdmax.notna()
    n=int(m.sum())
    if n==0: print(f'  {name:34s} n=0');return
    up=(fwdmax[m]/d.c[m]-1)*100;dn=(fwdmin[m]/d.c[m]-1)*100
    top=((d.h[m]>=bk[m])&(d.h[m]>=fwdmax[m])).mean()*100   # signal bar high is highest of -36..+36
    print(f'  {name:34s} n={n:5d} ({n/(N/288):5.1f}/day) | next3h: further up {up.median():+.2f}% median, down {dn.median():+.2f}% median, P(new high>+1%)={100*(up>1).mean():.0f}% , is local top {top:.0f}%')
print('A) exhaustion sign: state after signal (next 36 bars = 3h)')
stats(pd.Series(True,index=d.index),'all bars (baseline)')
stats(ru,'run-up state (dist>2 ATR over EMA20)')
ex1=(d.vr>=2.5)&(d.uw>=0.4);stats(ex1,'blow-off: vol>=2.5x & upper wick>=40%')
stats(ex1&ru,'blow-off IN run-up')
stats(ex1&~ru,'blow-off NOT in run-up')
ex2=ex1&(d.tbr<0.35);stats(ex2,'blow-off + buy share<0.35')
stats(ex2&ru,'... IN run-up')
ex3=(d.vr>=2.5)&(d.uw>=0.4)&(d.h>=bk);stats(ex3,'blow-off AT 3h high')
stats(ex3&ru,'... AT 3h high & run-up')
stats((d.rsi>75),'RSI>75')
stats((d.score>=3),'peak score>=3')
stats((d.score>=3)&ru,'peak score>=3 in run-up')
# B) entry frequency + exit stability
RULES=['stop_be','tp2R','chand2','chand3','chand4','tpct1.5','tpct3','ema20','rsi_roll','climax','adapt','adapt2']
A=d.to_dict('list');half=N//2
print('\nB) entry frequency and exit rules, by halves (net% per trade, fee 0.10%)')
for kind in ('brk','pb'):
    ids=E.signals(d,kind)
    print(f' entry={kind}: {len(ids)} entries in {N/288:.0f} days = {len(ids)/(N/288)*30:.1f}/month')
    if len(ids)<8: continue
    rows={r:[(i,)+E.run(d,i,r,A)[:2] for i in ids] for r in RULES}
    print(f'   {"rule":9s} {"n":>4s} {"mean":>7s} {"med":>7s} {"win%":>5s} {"PF":>5s} | {"half1":>7s} {"half2":>7s}')
    for r in RULES:
        v=np.array([x[1] for x in rows[r]]);ix=np.array([x[0] for x in rows[r]])
        gp=v[v>0].sum();gl=-v[v<0].sum()
        h1=v[ix<half];h2=v[ix>=half]
        print(f'   {r:9s} {len(v):4d} {v.mean():7.3f} {np.median(v):7.3f} {100*(v>0).mean():5.1f} {gp/gl if gl>0 else 9:5.2f} | {h1.mean() if len(h1) else float("nan"):7.3f} {h2.mean() if len(h2) else float("nan"):7.3f}')
