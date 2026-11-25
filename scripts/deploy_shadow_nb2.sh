#!/bin/bash
LV=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/${1:-main}/scripts
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shnb2_$TS; N=/tmp/shnb2; rm -rf $N; mkdir -p $B $N; cp $LV/index.html $B/; cp $LV/index.html $N/
curl -s "$RAW/patch_shadow_nb2.py" -o $N/patch.py
OUT=$($VPY $N/patch.py $N/index.html 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
$VPY - <<'PY'
import re,subprocess
h=open('/tmp/shnb2/index.html',encoding='utf-8').read()
for i,x in enumerate(re.findall(r'<script[^>]*>(.*?)</script>',h,re.S)):
    open('/tmp/shnb2/s%d.js'%i,'w',encoding='utf-8').write(x); print('js',i,subprocess.run(['node','--check','/tmp/shnb2/s%d.js'%i],capture_output=True,text=True).returncode)
PY
cp $N/index.html $LV/index.html; chown tbot:tbot $LV/index.html
systemctl restart live-web; sleep 8
H=$(curl -s -m 5 http://127.0.0.1:18110/live/health); echo active=$(systemctl is-active live-web) health=$H
if [ "$(systemctl is-active live-web)" != "active" ] || [ "$H" != "ok" ]; then echo ROLLBACK; cp $B/index.html $LV/index.html; chown tbot:tbot $LV/index.html; systemctl restart live-web; exit 1; fi
echo DEPLOYED $TS
