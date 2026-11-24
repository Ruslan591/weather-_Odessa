import re
for path,pat in (("/opt/trading-bot/live/live_web.py",r"ST\[.sh.\]|ST\.get\(.sh.\)|ST = |ST=|def ws_handler|t.: .sh.|\"sh\""),("/opt/trading-bot/live/index.html",r"==='sh'|S\.sh\b|S\.arch=|t==='arch'|id=.ssum|ssum")):
    print("=====",path)
    for i,l in enumerate(open(path,encoding="utf-8")):
        if re.search(pat,l): print("%d:%s"%(i+1,ascii(l.rstrip()[:330])))
