import re
L=open("/opt/weather-pipeline/repo/bot/live/index.html",encoding="utf-8").read().split("\n")
print("lines",len(L))
pat=re.compile(r"getElementById\('acc'\)|\bacc\b|equity|shadow|\u0442\u0435\u043d|\u0431\u0435\u0437 \u0444|nofilt|bal",re.I)
n=0
for i,l in enumerate(L):
    if pat.search(l):
        print("%d:%s"%(i+1,ascii(l.strip()[:260]))); n+=1
        if n>45: break
