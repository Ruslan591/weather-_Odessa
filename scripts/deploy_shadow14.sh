#!/bin/bash
# deploy_shadow14: фильтр стороны по режиму рынка в тенях (идемпотентно, с откатом)
TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow14_$TS; N=/tmp/shadownew14
mkdir -p $B $N
cp $TN/tg_shadow.py $B/; cp $PR/shadow_cfg.json $B/
cp $TN/tg_shadow.py $N/tg_shadow.py
curl -s https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/patch_side_filter.py -o $N/patch_side_filter.py
OUT=$($VPY $N/patch_side_filter.py $N/tg_shadow.py 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) echo ALREADY_DONE; exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
$VPY -m py_compile $N/tg_shadow.py || { echo COMPILE_FAIL; exit 1; }
cp $N/tg_shadow.py $TN/tg_shadow.py; chown tbot:tbot $TN/tg_shadow.py
rollback() { echo ROLLBACK; cp $B/tg_shadow.py $TN/; cp $B/shadow_cfg.json $PR/; chown tbot:tbot $TN/tg_shadow.py; systemctl restart tg-bot-regr; sleep 15; echo ROLLED tg=$(systemctl is-active tg-bot-regr); exit 1; }
systemctl restart tg-bot-regr; sleep 25
[ "$(systemctl is-active tg-bot-regr)" = "active" ] || rollback
$VPY -c 'import json; f="/opt/trading-bot/positions_regr/shadow_cfg.json"; c=json.load(open(f)); c["side_filter"]=True; json.dump(c,open(f,"w")); print("cfg",c)'
chown tbot:tbot $PR/shadow_cfg.json
sleep 5
echo tg=$(systemctl is-active tg-bot-regr)
journalctl -u tg-bot-regr -n 12 --no-pager | tail -12
echo DEPLOYED $TS
