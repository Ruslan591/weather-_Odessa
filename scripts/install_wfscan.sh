#!/bin/bash
# Ustanovka WF-skanera na VPS (zapuskat ot root cherez most). Zhivye boty ne trogaet.
set -e
D=/opt/trading-bot/wfscan; R=/opt/weather-pipeline/repo
cd $R && git fetch -q origin
install -d -o tbot -g tbot $D
for f in wfscan.py wfscan_panel.py; do git show origin/main:bot/wfscan/$f > $D/$f; done
chown tbot:tbot $D/*.py
sudo -u tbot /opt/trading-bot/venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://localhost:8091/api/runs"))
r = [x for x in d["runs"] if x.get("track") == "vp" and x["cfg"].get("tf") == "5m" and x["sym"] == "PHAUSDT" and x.get("stop_ms") is None][0]
cfg = {k: v for k, v in r["cfg"].items() if k not in ("vp_start", "vp_starts", "vp_since", "sym")}
cfg["vp_start"] = "auto"; cfg["vp_starts"] = {}
json.dump(cfg, open("/opt/trading-bot/wfscan/base_cfg.json", "w"), ensure_ascii=False, indent=1)
print("base_cfg keys", len(cfg))
PY
cat > /etc/systemd/system/wfscan-panel.service <<'U1'
[Unit]
Description=WF scan results page (127.0.0.1:18094)
After=network-online.target

[Service]
User=tbot
WorkingDirectory=/opt/trading-bot/wfscan
ExecStart=/opt/trading-bot/venv/bin/python /opt/trading-bot/wfscan/wfscan_panel.py
Restart=always
RestartSec=5
Nice=10
MemoryMax=300M

[Install]
WantedBy=multi-user.target
U1
cat > /etc/systemd/system/wfscan.service <<'U2'
[Unit]
Description=WF scan: walk-forward podbor nastroek Profilya (nizkij prioritet)
After=network-online.target
StartLimitIntervalSec=900
StartLimitBurst=5

[Service]
User=tbot
WorkingDirectory=/opt/trading-bot/wfscan
ExecStart=/opt/trading-bot/venv/bin/python /opt/trading-bot/wfscan/wfscan.py
Restart=on-failure
RestartSec=60
Nice=19
CPUSchedulingPolicy=batch
IOSchedulingClass=idle
MemoryMax=3G

[Install]
WantedBy=multi-user.target
U2
systemctl daemon-reload
systemctl enable --now wfscan-panel.service
sleep 2
ss -ltn | grep 18094 || echo "panel not listening"
echo INSTALLED
