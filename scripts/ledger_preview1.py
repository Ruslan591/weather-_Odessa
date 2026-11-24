import sys,os,json,shutil,subprocess,datetime as D
os.makedirs("/tmp/prev",exist_ok=True)
shutil.copy("/opt/trading-bot/positions_regr/shadow.json","/tmp/prev/shadow.json")
for f in ("shadow_bal_trades.json",):
    if os.path.exists("/tmp/prev/"+f): os.remove("/tmp/prev/"+f)
subprocess.run("curl -s https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/shadow_ledger.py -o /tmp/prev/shadow_ledger.py",shell=True)
sys.path.insert(0,"/tmp/prev")
import importlib, shadow_ledger as SL
for lab,t0 in (("from 23.11 01:22 UTC (filters on)",int(D.datetime(2026,11,23,1,22,tzinfo=D.UTC).timestamp()*1000)),("from 20.11 00:00:41 (all new-rule shadows, filters not on)",int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000))):
    json.dump({"t0":t0,"start":4.807,"stake":6.0,"lev":5,"slot_eq":2.0,"min_slots":3},open("/tmp/prev/shadow_bal.json","w"))
    if os.path.exists("/tmp/prev/shadow_bal_trades.json"): os.remove("/tmp/prev/shadow_bal_trades.json")
    SL._CACHE["mt"]=None
    o=SL.compute("/tmp/prev")
    print("PREVIEW",lab)
    for l in o["lines"]: print("  ",l)
