import json, collections
D='/opt/trading-bot/positions_regr/'
pos=json.load(open(D+'positions.json')); orders={o['id']:o for o in json.load(open(D+'orders.json'))}
rows=[]
for p in pos:
    if p.get('status') not in ('closed','done','exited') and p.get('t_out') is None: continue
    o=orders.get(p.get('order_id'))
    if not o or not o.get('chan'): continue
    ch=o['chan']; 
    try:
        t=p['t_in']; R=ch['upper']['p1']+ch['upper']['s']*(t-ch['upper']['t1']); S=ch['lower']['p1']+ch['lower']['s']*(t-ch['lower']['t1'])
    except Exception: continue
    H=R-S
    if H<=0: continue
    e=p['entry']; mfe=p['mfe_pct']/100*e; mae=p['mae_pct']/100*e
    long=p['side']=='long'
    pos_in=(e-S)/H if long else (R-e)/H     # 0 = at own line
    rows.append(dict(rule=p['rule'],side=p['side'],ct=o.get('ctype'),fr=mfe/H,mae=abs(mae)/H,start=pos_in,H_atr=H/o['atr'] if o.get('atr') else None,src=p.get('src'),reason=p.get('reason')))
print('rows',len(rows)); print(collections.Counter((r['rule'],r['src']) for r in rows).most_common(12))
import statistics as st
def rep(name,rs):
    if len(rs)<5: print(name,len(rs)); return
    fr=[max(0,r['fr']) for r in rs]
    print(name,'n=%d'%len(rs),'median %.2f'%st.median(fr),' '.join('P>=%.2f:%.0f%%'%(f,100*sum(x>=f for x in fr)/len(fr)) for f in (0.1,0.25,0.5,0.75,1.0)),'| start med %.2f'%st.median([r['start'] for r in rs]),'| mae med %.2f'%st.median([r['mae'] for r in rs]))
rep('all',rows)
for rule in set(r['rule'] for r in rows): rep('rule '+str(rule),[r for r in rows if r['rule']==rule])
bo=[r for r in rows if r['start']<0.25]; rep('start<0.25',bo)
for ct in ('with','counter'):
    rs=[r for r in bo if (('up' in str(r['ct']))==(r['side']=='long'))==(ct=='with')]; rep('bounce '+ct,rs)
