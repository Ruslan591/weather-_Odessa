import json,urllib.request,time
D='/opt/trading-bot/positions_regr/'
pos=json.load(open(D+'positions.json')); orders={o['id']:o for o in json.load(open(D+'orders.json'))}
for p in pos[-3:]:
    o=orders.get(p.get('order_id')); t=p['t_in']
    print(p['sym'],p['side'],t,p.get('t_out'),p.get('stop0'),p['entry'],bool(o and o.get('chan')))
    u="https://data-api.binance.vision/api/v3/klines?symbol=%sUSDT&interval=5m&limit=60&startTime=%d"%(p['sym'],t)
    t0=time.time()
    try:
        d=json.load(urllib.request.urlopen(u,timeout=20)); print(' got',len(d),'in %.1fs'%(time.time()-t0), d[0][0] if d else None)
    except Exception as e: print(' ERR',repr(e)[:150],'%.1fs'%(time.time()-t0))
