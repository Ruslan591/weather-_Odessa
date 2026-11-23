import os,re
pat=re.compile("\u0431\u0435\u0437 \u0444\u0438\u043b\u044c\u0442\u0440\u0430|\u0431\u0430\u043b\u0430\u043d\u0441",re.I)
for root in ("/opt/weather-pipeline/repo/bot/classic",):
    for f in sorted(os.listdir(root)):
        if not f.endswith((".py",".html",".js")): continue
        for i,l in enumerate(open(os.path.join(root,f),encoding="utf-8",errors="replace")):
            if pat.search(l): print("%s:%d:%s"%(f,i+1,ascii(l.strip()[:200])))
