#!/bin/bash
# deploy_ledger1: виртуальный баланс теней (две линии) в панели 18111. Идемпотентно, с откатом. Подсчёт теней не трогает.
LV=/opt/trading-bot/live; PS=/opt/trading-bot/positions; PR=/opt/trading-bot/positions_regr; VPY=/opt/trading-bot/venv/bin/python
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_ledger1_$TS; N=/tmp/ledgernew1; RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts
mkdir -p $B $N; cp $LV/live_web.py $LV/index.html $B/
curl -s $RAW/shadow_ledger.py -o $N/shadow_ledger.py
$VPY -m py_compile $N/shadow_ledger.py || { echo LEDGER_COMPILE_FAIL; exit 1; }
cp $N/shadow_ledger.py $PS/shadow_ledger.py; chown tbot:tbot $PS/shadow_ledger.py
if [ ! -f $PR/shadow_bal.json ]; then
$VPY - <<'PY'
import json,time,urllib.request
a=json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude"))["account"]
c={"on":True,"t0":int(time.time()*1000),"start":round(a["equity"],3),"stake":a["stake"],"lev":a["lev"],"slot_eq":2.0,"min_slots":3}
json.dump(c,open("/opt/trading-bot/positions_regr/shadow_bal.json","w")); print("bal cfg",c)
PY
chown tbot:tbot $PR/shadow_bal.json
fi
cp $LV/live_web.py $LV/index.html $N/
curl -s $RAW/patch_ledger_panel.py -o $N/patch_ledger_panel.py
OUT=$($VPY $N/patch_ledger_panel.py $N 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) echo ALREADY_DONE; exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
$VPY -m py_compile $N/live_web.py || { echo COMPILE_FAIL; exit 1; }
cp $N/live_web.py $LV/live_web.py; cp $N/index.html $LV/index.html; chown tbot:tbot $LV/live_web.py $LV/index.html
rollback() { echo ROLLBACK; cp $B/live_web.py $B/index.html $LV/; chown tbot:tbot $LV/live_web.py $LV/index.html; systemctl restart live-web; sleep 8; echo ROLLED live=$(systemctl is-active live-web); exit 1; }
systemctl restart live-web; sleep 10
[ "$(systemctl is-active live-web)" = "active" ] || rollback
H=$(curl -s -m 5 http://127.0.0.1:18110/live/health); echo health=$H
[ "$H" = "ok" ] || rollback
journalctl -u live-web --since "-1min" --no-pager | grep -i -E "bal:|error|traceback" | cut -c1-200 | tail -5
cat $PR/shadow_bal.json; echo
echo DEPLOYED $TS
