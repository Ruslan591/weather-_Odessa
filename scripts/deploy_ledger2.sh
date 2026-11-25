#!/bin/bash
# deploy_ledger2: фильтр «не flat и не 5m» для обеих линий баланса (shadow_ledger.py). С откатом.
LV=/opt/trading-bot/live; PS=/opt/trading-bot/positions; VPY=/opt/trading-bot/venv/bin/python
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_ledger2_$TS; mkdir -p $B; cp $PS/shadow_ledger.py $B/
curl -s https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/shadow_ledger.py -o /tmp/sl2.py
$VPY -m py_compile /tmp/sl2.py || { echo COMPILE_FAIL; exit 1; }
grep -c skip_tf /tmp/sl2.py
cp /tmp/sl2.py $PS/shadow_ledger.py; chown tbot:tbot $PS/shadow_ledger.py
systemctl restart live-web; sleep 10
H=$(curl -s -m 5 http://127.0.0.1:18110/live/health); echo active=$(systemctl is-active live-web) health=$H
if [ "$(systemctl is-active live-web)" != "active" ] || [ "$H" != "ok" ]; then echo ROLLBACK; cp $B/shadow_ledger.py $PS/shadow_ledger.py; chown tbot:tbot $PS/shadow_ledger.py; systemctl restart live-web; sleep 8; echo rolled=$(systemctl is-active live-web); exit 1; fi
journalctl -u live-web --since "-1min" --no-pager | grep -i -E "bal:|error|traceback" | tail -5
echo "--- how live_web calls ledger"; grep -n "ledger" $LV/live_web.py | head -8
echo "--- trades file"; ls -la --time-style=long-iso /opt/trading-bot/positions_regr/ | grep -i "shadow_bal"; ps -o user,cmd -C python3 | grep -i live_web | head -3; systemctl show live-web -p User -p WorkingDirectory -p ExecStart | head -5
echo DEPLOYED $TS
