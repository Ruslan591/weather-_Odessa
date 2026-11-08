#!/bin/bash
# deploy_tg_update.sh: обновление tg_gate.py (в positions), tg_bot.py и tg_notify.py (в /opt/tg-notify) + перезапуск tg-bot-regr и chan-orders-regr. Бэкап и откат при ошибке.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak; cp $P/tg_gate.py $N/bak/tg_gate.py.$TS; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS; cp $N/tg_notify.py $N/bak/tg_notify.py.$TS
for f in tg_gate.py tg_notify.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/tg_gate.py.new /tmp/tg_notify.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; cp $N/bak/tg_gate.py.$TS $P/tg_gate.py; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; cp $N/bak/tg_notify.py.$TS $N/tg_notify.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
install -o tbot -g tbot -m 644 /tmp/tg_gate.py.new $P/tg_gate.py; install -m 644 /tmp/tg_notify.py.new $N/tg_notify.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
mkdir -p /etc/systemd/system/tg-bot-regr.service.d; printf '[Service]\nEnvironment=ACCT_PORT=18102\n' > /etc/systemd/system/tg-bot-regr.service.d/acct.conf
systemctl daemon-reload
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 40
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | cut -c1-160
journalctl -u tg-bot-regr -n 4 --no-pager | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo "--- status card (preview, not sent):"
(cd $N && POS_DIR=$PR ACCT_PORT=18102 MPLCONFIGDIR=/tmp/mpl-tg $N/venv/bin/python -c "import tg_bot; print(tg_bot.status_text())" 2>&1 | tail -16)
echo DEPLOY_OK $TS
