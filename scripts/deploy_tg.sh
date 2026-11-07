#!/bin/bash
# deploy_tg.sh: режимы Сон/Монитор/Авто и Telegram-бот для счёта «Регрессия» (запускать от root). Бэкап и откат при ошибке.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in chan_orders.py decisions.py; do cp $P/$f $P/$f.bak_tg_$TS || exit 1; done
for f in chan_orders.py decisions.py tg_gate.py tg_notify.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/decisions.py.new /tmp/tg_gate.py.new /tmp/tg_notify.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; for f in chan_orders.py decisions.py; do cp $P/$f.bak_tg_$TS $P/$f; chown tbot:tbot $P/$f; done; rm -f $P/tg_gate.py /etc/systemd/system/chan-orders-regr.service.d/tg.conf; systemctl daemon-reload; systemctl stop tg-bot-regr; systemctl restart chan-orders-regr; exit 1; }
for f in chan_orders.py decisions.py tg_gate.py; do install -o tbot -g tbot -m 644 /tmp/$f.new $P/$f; done
install -m 644 /tmp/tg_notify.py.new $N/tg_notify.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
cat > /etc/systemd/system/tg-bot-regr.service <<UNIT
[Unit]
Description=Telegram bot for Regression account (modes sleep/monitor/auto)
After=network-online.target
[Service]
User=tbot
Environment=POS_DIR=$PR
Environment=MPLCONFIGDIR=/tmp/mpl-tg
Environment=TG_ACCT_NAME=Регрессия
WorkingDirectory=$N
ExecStart=$N/venv/bin/python $N/tg_bot.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p /etc/systemd/system/chan-orders-regr.service.d
printf '[Service]\nEnvironment=TG_GATE=1\n' > /etc/systemd/system/chan-orders-regr.service.d/tg.conf
systemctl daemon-reload
cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 $VPY -c "import chan_orders" || { echo IMPORT_FAIL; rollback; }
systemctl enable --now tg-bot-regr >/dev/null 2>&1
systemctl restart chan-orders-regr
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -4 $PR/chan.log | cut -c1-200
journalctl -u tg-bot-regr -n 6 --no-pager | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
