#!/bin/bash
# deploy_tg_target.sh <parent_commit>: цель по статистике (tg_target) в Авто и экспрессе, ссылка на предыдущий пост, отметка «здесь надо было заходить».
# chan_orders.py + tg_target.py -> positions (chan-orders-regr); tg_bot/tg_express/tg_learn/tg_notify/tg_target -> /opt/tg-notify (tg-bot-regr). Бэкап, DIVERGED, компиляция, импорт, автооткат.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in chan_orders.py tg_notify.py tg_bot.py tg_express.py tg_learn.py tg_target.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
if [ -n "$PAR" ]; then
  for pair in chan_orders.py:$P tg_notify.py:$N tg_bot.py:$N tg_express.py:$N tg_learn.py:$N; do f=${pair%%:*}; d=${pair##*:}
    git show $PAR:bot/positions/$f > /tmp/$f.par && cmp -s /tmp/$f.par $d/$f || { echo "DIVERGED $f"; diff /tmp/$f.par $d/$f | head -10; exit 1; }
  done
fi
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/tg_notify.py.new /tmp/tg_bot.py.new /tmp/tg_express.py.new /tmp/tg_learn.py.new /tmp/tg_target.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $P/chan_orders.py $N/bak/chan_orders.py.$TS
for f in tg_notify.py tg_bot.py tg_express.py tg_learn.py; do cp $N/$f $N/bak/$f.$TS; done
rollback() { echo ROLLBACK; cp $N/bak/chan_orders.py.$TS $P/chan_orders.py; for f in tg_notify.py tg_bot.py tg_express.py tg_learn.py; do cp $N/bak/$f.$TS $N/$f; done; rm -f $P/tg_target.py $N/tg_target.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
install -o tbot -g tbot -m 644 /tmp/chan_orders.py.new $P/chan_orders.py; install -o tbot -g tbot -m 644 /tmp/tg_target.py.new $P/tg_target.py
for f in tg_notify.py tg_bot.py tg_express.py tg_learn.py tg_target.py; do install -m 644 /tmp/$f.new $N/$f; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders, tg_target") || { echo IMPORT_FAIL_GATE; rollback; }
(cd $N && POS_DIR=$PR $VPY -c "import tg_express, tg_learn, tg_target as T; print('modules ok'); [print(w, T.choose(w, False)['text']) for w in (6, 14)]; print('counter', T.choose(10, True)['text'])") || { echo IMPORT_FAIL_MODULES; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 40
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
