import subprocess,os,re,json
def sh(c): return subprocess.run(c,shell=True,capture_output=True,text=True).stdout
print(sh("ps -o pid,args -p 80235 | cut -c1-200"))
print("cwd",sh("readlink /proc/80235/cwd"))
cwd=sh("readlink /proc/80235/cwd").strip()
print(sh("ls -la %s | head -40"%cwd))
for f in ("/opt/trading-bot/positions_regr/chan_cfg.json","/opt/trading-bot/positions_regr/exit_cfg.json"):
    try: print(f,open(f).read()[:1500])
    except Exception as e: print(f,e)
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
p=[x["p"] for x in d if x.get("p") and x["p"].get("r_mult") is not None][-1]
print("p keys",{k:(v if not isinstance(v,(list,dict)) else "..") for k,v in p.items()})
