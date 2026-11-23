import subprocess,json
def sh(c): return subprocess.run(c,shell=True,capture_output=True,text=True,errors="replace").stdout
print(sh("ls -la /opt/trading-bot/live/; diff -q /opt/trading-bot/live/live_web.py /opt/weather-pipeline/repo/bot/live/live_web.py; diff -q /opt/trading-bot/live/index.html /opt/weather-pipeline/repo/bot/live/index.html"))
out=sh("grep -n -i 'shadow' /opt/trading-bot/live/live_web.py /opt/trading-bot/live/index.html | cut -c1-230 | head -40")
print(ascii(out) if False else out)
acc=json.loads(sh("curl -s http://127.0.0.1:18102/api/claude"))
a=acc.get("account")
print("ACCOUNT",a)
print("keys",list(acc.keys())[:12])
