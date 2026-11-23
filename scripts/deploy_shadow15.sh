#!/bin/bash
# deploy_shadow15: расширенные предфильтры теней (идемпотентно, с откатом)
TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow15_$TS; N=/tmp/shadownew15
mkdir -p $B $N
cp $TN/tg_shadow.py $B/; cp $PR/shadow_cfg.json $B/
cp $TN/tg_shadow.py $N/tg_shadow.py
curl -s https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/patch_filters2.py -o $N/patch_filters2.py
OUT=$($VPY $N/patch_filters2.py $N/tg_shadow.py 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) echo ALREADY_DONE; exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
$VPY -m py_compile $N/tg_shadow.py || { echo COMPILE_FAIL; exit 1; }
cp $N/tg_shadow.py $TN/tg_shadow.py; chown tbot:tbot $TN/tg_shadow.py
rollback() { echo ROLLBACK; cp $B/tg_shadow.py $TN/; cp $B/shadow_cfg.json $PR/; chown tbot:tbot $TN/tg_shadow.py $PR/shadow_cfg.json; systemctl restart tg-bot-regr; sleep 15; echo ROLLED tg=$(systemctl is-active tg-bot-regr); exit 1; }
systemctl restart tg-bot-regr; sleep 25
[ "$(systemctl is-active tg-bot-regr)" = "active" ] || rollback
$VPY -c 'import json; f="/opt/trading-bot/positions_regr/shadow_cfg.json"; c=json.load(open(f)); c.update({"score_filter":True,"btc_rsi_filter":True,"counter_filter":True,"rsi5_filter":True,"width_filter":False,"width_max":8}); json.dump(c,open(f,"w")); print("cfg",c)'
chown tbot:tbot $PR/shadow_cfg.json
sleep 20
echo tg=$(systemctl is-active tg-bot-regr)
journalctl -u tg-bot-regr -n 15 --no-pager | grep -i -E 'error|traceback|shadow' | tail -8
$VPY -c '
import sys; sys.path.insert(0,"/opt/tg-notify")
import tg_shadow as T
print("side_block present", hasattr(T,"_side_block"))
it={"side":"long","rg":{"regime":"flat"},"feat":{"counter":1,"rsi5":50,"width":9},"b1":{"rsi_ok":0}}
print("test1", T._side_block(it))
it["b1"]["rsi_ok"]=1; print("test2", T._side_block(it))
it["feat"]["counter"]=0; it["feat"]["rsi5"]=25; print("test3", T._side_block(it))
it["feat"]["rsi5"]=50; print("test4", T._side_block(it))
' 2>&1 | LC_ALL=C tr -cd '\11\12\40-\176'
echo DEPLOYED $TS
