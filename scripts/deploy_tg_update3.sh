#!/bin/bash
# deploy_tg_update3.sh: hotfix tg_market/tg_limit (KeyError in cycle), immediate market fills, /orders list with cancel. Files: chan_orders.py (positions), tg_bot.py (/opt/tg-notify).
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak
cp $P/chan_orders.py $N/bak/chan_orders.py.$TS; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS
for f in chan_orders.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; cp $N/bak/chan_orders.py.$TS $P/chan_orders.py; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
systemctl stop chan-orders-regr
# stale orders stuck since the KeyError (they would be back-filled with 4h old prices): cancel
$VPY - <<'PY'
import json, time
f = "/opt/trading-bot/positions_regr/orders.json"; o = json.load(open(f)); now = int(time.time() * 1000); n = 0
for x in o:
    if x.get("status") == "pending" and x.get("rule") in ("tg_market", "tg_limit") and now - int(x.get("approved_t") or now) > 600000:
        x.update(status="cancelled", reason="stale: stuck by cycle error before fix", t_end=now); n += 1
json.dump(o, open(f + ".tmp", "w"), ensure_ascii=False); import os; os.replace(f + ".tmp", f); print("cancelled stale:", n)
PY
chown tbot:tbot $PR/orders.json 2>/dev/null
install -o tbot -g tbot -m 644 /tmp/chan_orders.py.new $P/chan_orders.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders; print('RULE_RU tg:', 'tg_market' in chan_orders.RULE_RU)") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 50
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -4 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176'
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A1" != active ] || [ "$A2" != active ] || tail -3 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
