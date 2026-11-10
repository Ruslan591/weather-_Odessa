#!/bin/bash
# deploy_tg_slots.sh <parent_commit>: слоты растут с балансом (баланс/2.0 $, не меньше 3), слежений в Автоордере не больше свободных слотов; фикс строки «Графиков в работе».
# chan_orders.py + tg_gate.py -> positions (chan-orders-regr; тот же код у afd/combo), tg_bot.py -> /opt/tg-notify. Бэкап, DIVERGED, компиляция, импорт, автооткат.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in chan_orders.py tg_gate.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
if [ -n "$PAR" ]; then
  for pair in chan_orders.py:$P tg_gate.py:$P tg_bot.py:$N; do f=${pair%%:*}; d=${pair##*:}
    git show $PAR:bot/positions/$f > /tmp/$f.par && cmp -s /tmp/$f.par $d/$f || { echo "DIVERGED $f"; diff /tmp/$f.par $d/$f | head -10; exit 1; }
  done
fi
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/tg_gate.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; for f in chan_orders.py tg_gate.py; do cp $P/$f $N/bak/$f.$TS; done; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS
rollback() { echo ROLLBACK; for f in chan_orders.py tg_gate.py; do cp $N/bak/$f.$TS $P/$f; done; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
for f in chan_orders.py tg_gate.py; do install -o tbot -g tbot -m 644 /tmp/$f.new $P/$f; done; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import chan_orders as c; print('slots', c.slots_state())") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
