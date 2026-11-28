import hashlib,subprocess
for p in ("/opt/trading-bot/live/index.html","/opt/trading-bot/live/live_web.py"):
    print(p,hashlib.md5(open(p,"rb").read()).hexdigest())
print(subprocess.run("find /opt -name shadow_ledger.py -not -path '*/bak*' 2>/dev/null | head; systemctl is-active live-web; grep -n 'shadow_ledger\\|import SL\\|SL =' /opt/trading-bot/live/live_web.py | head -5",shell=True,capture_output=True,text=True).stdout)
for p in subprocess.run("find /opt -name shadow_ledger.py -not -path '*/bak*' 2>/dev/null",shell=True,capture_output=True,text=True).stdout.split():
    print(p,hashlib.md5(open(p,"rb").read()).hexdigest())
