import json, collections
D='/opt/trading-bot/positions_regr/'
m=json.load(open(D+'chan_missed.json'))
print(collections.Counter((x.get('kind'),x.get('bo'),x.get('res'),x.get('done')) for x in m).most_common(12))
x=[y for y in m if y.get('done')][-1]; y=dict(x); y['chan']='..'; print(json.dumps(y)[:900])
pos=json.load(open(D+'positions.json'))
print(collections.Counter(p.get('reason') for p in pos).most_common(8)); print(collections.Counter((p.get('armed'),p.get('trail_act')) for p in pos).most_common(6))
p=pos[-1]; print({k:p.get(k) for k in ('entry','tp','stop0','mfe_pct','mae_pct','max_h','t_in','t_out','reason','exit','R_pct','be_r')})
print(sum(1 for p in pos if p.get('tp')), 'with tp'); 
import statistics as st
print('tp dist pct med', st.median([abs(p['tp']-p['entry'])/p['entry']*100 for p in pos if p.get('tp')]))
print('max_h distinct', collections.Counter(p.get('max_h') for p in pos).most_common(4))
