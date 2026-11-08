#!/bin/bash
# deploy_tg_update5.sh: alerts pause/resume (button + /alerts). Files: tg_gate.py (positions), tg_bot.py (/opt/tg-notify).
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak
cp $P/tg_gate.py $N/bak/tg_gate.py.$TS; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS
for f in tg_gate.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/tg_gate.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; cp $N/bak/tg_gate.py.$TS $P/tg_gate.py; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
install -o tbot -g tbot -m 644 /tmp/tg_gate.py.new $P/tg_gate.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders; print('gate import ok', tg_gate.DEFAULT['alerts_off'])") || { echo IMPORT_FAIL; rollback; }
(cd $N && POS_DIR=$PR $N/venv/bin/python -c "import tg_bot; print('menu rows', len(tg_bot.menu()), 'watch rows', len(tg_bot.watch_buttons(1,'alert')))") 2>&1 | tail -2
systemctl restart tg-bot-regr chan-orders-regr
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -3 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176'
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
