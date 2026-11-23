import subprocess
def sh(c): return subprocess.run(c,shell=True,capture_output=True,text=True,errors="replace").stdout
print(sh("cd /opt/weather-pipeline/repo/bot && grep -n -E \"free|slots|'start'|\\\"start\\\"|stake|margin|MAX_USE|max_open|n_slots\" positions/pos.py | cut -c1-210 | head -60"))
print("=====live_web routes")
print(sh("cd /opt/weather-pipeline/repo/bot/live && grep -n -E \"add_get|add_post|route|/api|acct\" live_web.py | cut -c1-200 | head -30"))
print("=====panel process")
print(sh("ps aux | grep -E 'live_web|acct' | grep -v grep | cut -c1-250"))
