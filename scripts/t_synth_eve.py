import math, random
from datetime import datetime, timedelta, timezone
import weather_tg_issue as I, weather_tg_channel as ch
K=ch.KYIV
now=datetime(2026,11,24,4,0,tzinfo=timezone.utc)  # 06:00 local; adjust
def mk(now, front=True, rain=True):
    base=datetime(2026,11,24,0,0,tzinfo=K); H=[]
    for i in range(72):
        dt=base+timedelta(hours=i)
        x=i
        P=1008-0.35*min(x,16)+ (0.9*(x-16) if x>16 else 0) if front else 1012
        T=2+4*math.sin((x-9)/24*2*math.pi)-(4 if (front and 17<=x<=30) else 0)
        R=0.8 if (rain and 15<=x<=18) else 0.0
        H.append({"dt":dt,"T":T,"P":P,"W":4+(5 if 15<=x<=20 else 0),"G":7+(6 if 15<=x<=20 else 0),"D":200 if x<16 else 300,"R":R,"C":3 if x<15 else 61 if R else 2})
    return H
def mkst(now):
    st={}
    rnd=random.Random(1)
    for k,(sid,name) in enumerate(ch.STATIONS):
        obs=[]
        for j in range(24*6):
            ts=now-timedelta(minutes=10*j)
            loc=ts.astimezone(K)
            obs.append({"ts":ts,"temp":3+3*math.sin((loc.hour-9)/24*2*math.pi)-k*0.3,"hum":80,"wind":3,"gust":5+(8 if k==2 and loc.hour==15 else 0),"dir":200,"p":1005,"rate":0,"ptot":0.4*k/8 if loc.hour>=15 else 0})
        obs.sort(key=lambda o:o["ts"]); st[sid]={"name":name,"obs":obs}
    return st

import re
import weather_tg_ai as ai
H=mk(now)
now2=datetime(2026,11,25,19,0,tzinfo=timezone.utc)
ist={"today":{"date":"2026-11-25","pred_tmax":4.9},"days":[{"date":"2026-11-24","pred_tmax":4.0,"obs_tmax":5.4}],"headlines":[]}
st=mkst(now2)
# одинокий датчик дождя в Чудо Городе: 1,8 мм, у остальных нули
for o in st["IODESA139"]["obs"]:
    o["ptot"]=1.8 if o["ts"].astimezone(K).hour>=15 else 0.0
for sid in st:
    if sid!="IODESA139":
        for o in st[sid]["obs"]: o["ptot"]=0.0
text,rec,parts=I.build_evening(st,H,now2,ist)
print("FACTS:\n"+re.sub(r"<[^>]+>","",parts["facts"]))
ai.budget(250)
a=I.ai_text("evening",parts,ist)
print("\nAI:\n"+(I.assemble("evening",a,parts).split("<blockquote")[0] if a else "(не прошёл проверку)"))
