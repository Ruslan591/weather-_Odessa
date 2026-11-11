#!/bin/bash
# deploy_tg_monitor.sh chan_orders.py:md5 tg_gate.py:md5 tg_bot.py:md5 tg_notify.py:md5 : канал «Монитор» (маршрутизация постов, Радар), список пар счёта из pairs.json, освобождение мест слежения.
# chan_orders.py, tg_gate.py -> /opt/trading-bot/positions (перезапуск только chan-orders-regr); tg_bot.py, tg_notify.py -> /opt/tg-notify (tg-bot-regr). Бэкап, DIVERGED, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak /tmp/tgmon
declare -A DST=( [chan_orders.py]=$P [tg_gate.py]=$P [tg_bot.py]=$N [tg_notify.py]=$N )
for a in "$@"; do
  f=${a%%:*}; old=${a#*:}; d=${DST[$f]}
  git show origin/main:bot/positions/$f > /tmp/tgmon/$f || { echo SHOW_FAIL $f; exit 1; }
  CUR=$(md5sum $d/$f | cut -d' ' -f1); [ "$CUR" = "$old" ] || { echo DIVERGED $f $CUR; exit 1; }
  $VPY -m py_compile /tmp/tgmon/$f || { echo COMPILE_FAIL $f; exit 1; }
done
for a in "$@"; do f=${a%%:*}; d=${DST[$f]}; cp $d/$f $N/bak/$f.$TS; done
rollback() { echo ROLLBACK; for a in "$@"; do f=${a%%:*}; d=${DST[$f]}; cp $N/bak/$f.$TS $d/$f; done; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
for a in "$@"; do f=${a%%:*}; d=${DST[$f]}; if [ "$d" = "$P" ]; then install -o tbot -g tbot -m 644 /tmp/tgmon/$f $d/$f; else install -m 644 /tmp/tgmon/$f $d/$f; fi; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders; print('gate ok', len(chan_orders.pairs_now()))") || { echo IMPORT_FAIL_GATE; rollback "$@"; }
(cd $N && POS_DIR=$PR $VPY -c "import tg_notify, tg_express, tg_btc1m; print('modules ok')") || { echo IMPORT_FAIL_MODULES; rollback "$@"; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 60
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -3 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 6 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
ls -la $PR/radar_state.json 2>&1 | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback "$@"; fi
echo DEPLOY_OK $TS
