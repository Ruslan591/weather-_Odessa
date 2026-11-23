import subprocess
def sh(c): return subprocess.run(c,shell=True,capture_output=True,text=True,errors="replace").stdout
print(sh("cat /opt/trading-bot/positions_regr/tg_slots.json | head -c 600"))
print(sh("cd /opt/weather-pipeline/repo/bot/positions && grep -n -E 'def slots|def free_slots|slots\\(|SLOT|n_slots|slot_n|max_slots|free_margin|free <|free >=|margin_ok' *.py | cut -c1-220 | head -25"))
