#!/bin/bash
# deploy_tg_express.sh <parent_commit>: express mode. tg_gate.py -> positions (chan-orders-regr); tg_bot.py, tg_express.py, tg_learn.py -> /opt/tg-notify (tg-bot-regr). Backup, DIVERGED check, compile, import check, auto rollback.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in tg_gate.py tg_bot.py tg_express.py tg_learn.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
if [ -n "$PAR" ]; then
  git show $PAR:bot/positions/tg_gate.py > /tmp/tg_gate.py.par && cmp -s /tmp/tg_gate.py.par $P/tg_gate.py || { echo DIVERGED tg_gate; diff /tmp/tg_gate.py.par $P/tg_gate.py | head -10; exit 1; }
  git show $PAR:bot/positions/tg_bot.py > /tmp/tg_bot.py.par && cmp -s /tmp/tg_bot.py.par $N/tg_bot.py || { echo DIVERGED tg_bot; diff /tmp/tg_bot.py.par $N/tg_bot.py | head -10; exit 1; }
fi
$VPY -m py_compile /tmp/tg_gate.py.new /tmp/tg_bot.py.new /tmp/tg_express.py.new /tmp/tg_learn.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $P/tg_gate.py $N/bak/tg_gate.py.$TS; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS
rollback() { echo ROLLBACK; cp $N/bak/tg_gate.py.$TS $P/tg_gate.py; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; rm -f $N/tg_express.py $N/tg_learn.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
install -o tbot -g tbot -m 644 /tmp/tg_gate.py.new $P/tg_gate.py
install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py; install -m 644 /tmp/tg_express.py.new $N/tg_express.py; install -m 644 /tmp/tg_learn.py.new $N/tg_learn.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders") || { echo IMPORT_FAIL_GATE; rollback; }
(cd $N && POS_DIR=$PR $VPY -c "import tg_express, tg_learn; print('modules ok')") || { echo IMPORT_FAIL_MODULES; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 40
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
