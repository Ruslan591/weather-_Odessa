import os,re,json
pat=re.compile("\u0431\u0435\u0437 \u0444\u0438\u043b\u044c\u0442\u0440\u0430|\u0431\u0430\u043b\u0430\u043d\u0441|balance|equity|\u0441\u0447\u0451\u0442",re.I)
out=[]
for root in ("/opt/weather-pipeline/repo/bot/live","/opt/weather-pipeline/repo/bot/positions/tg_shadow.py"):
    files=[]
    if os.path.isdir(root):
        files=[os.path.join(root,f) for f in os.listdir(root)]
    else: files=[root]
    for f in files:
        if not f.endswith((".py",".html",".js")): continue
        for i,l in enumerate(open(f,encoding="utf-8",errors="replace")):
            if pat.search(l): out.append("%s:%d:%s"%(os.path.basename(f),i+1,ascii(l.strip()[:230])))
print("\n".join(out[:70]))
