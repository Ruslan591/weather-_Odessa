import json,hashlib,shutil,subprocess,time,urllib.request,py_compile,os,sys
COM={'bot/live/index.html': '960a860cc7c29fcb885bb4013c4fa933732bb82f', 'scripts/shadow_ledger.py': '965fb9b2cd8ee559a604f363816a0ca3ff53daea'}
tok=[l.split("=",1)[1].strip() for l in open("/etc/vps-github-bridge/token") if "=" in l][0]
def get(path,ref):
    r=urllib.request.Request("https://api.github.com/repos/ruslan591/weather-_Odessa/contents/%s?ref=%s"%(path,ref),headers={"Authorization":"token "+tok,"Accept":"application/vnd.github.raw"})
    return urllib.request.urlopen(r,timeout=60).read()
ts=time.strftime("%Y%m%d_%H%M%S"); bak="/opt/trading-bot/bak_balui_"+ts; os.makedirs(bak)
T=[("bot/live/index.html","/opt/trading-bot/live/index.html","7c18b712eadca76c745ed1a81432a18b"),("scripts/shadow_ledger.py","/opt/trading-bot/positions/shadow_ledger.py","2b4d4b4391f801d5250f4d9e6a8aea8c")]
new={}
for g,dst,md in T:
    cur=hashlib.md5(open(dst,"rb").read()).hexdigest()
    if cur!=md: print("DIVERGED",dst,cur); sys.exit(1)
    new[dst]=get(g,COM[g]); shutil.copy2(dst,bak)
for g,dst,md in T:
    st=os.stat(dst); open(dst,"wb").write(new[dst]); os.chown(dst,st.st_uid,st.st_gid); os.chmod(dst,st.st_mode)
try: py_compile.compile("/opt/trading-bot/positions/shadow_ledger.py",doraise=True)
except Exception as e:
    print("COMPILE FAIL",e)
    for g,dst,md in T: shutil.copy2(os.path.join(bak,os.path.basename(dst)),dst)
    sys.exit(1)
subprocess.run("systemctl restart live-web",shell=True); time.sleep(6)
a=subprocess.run("systemctl is-active live-web",shell=True,capture_output=True,text=True).stdout.strip(); print("live-web",a)
if a!="active":
    for g,dst,md in T: shutil.copy2(os.path.join(bak,os.path.basename(dst)),dst)
    subprocess.run("systemctl restart live-web",shell=True); print("ROLLED BACK"); sys.exit(1)
sys.path.insert(0,"/opt/trading-bot/positions"); import importlib,shadow_ledger as SL
o=SL.compute("/opt/trading-bot/positions_regr")
for l in o["lines"]: print(l["k"],l["bal"],l.get("r"),l["closed"],l["open"],l.get("skip_rule"),(l.get("full") or {}).get("r"))
print("DEPLOY_OK",ts,bak)
