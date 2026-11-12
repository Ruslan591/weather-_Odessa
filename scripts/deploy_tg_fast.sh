#!/bin/bash
# deploy_tg_fast.sh chan_orders.py:md5 trend_shadow.py:md5 : ускорение цикла chan-orders-regr (параллельная подкачка свечей, тень тренда одним заходом, пауза цикла 5 с, замер времени цикла в chan.log).
# Файлы -> /opt/trading-bot/positions; перезапуск chan-orders-regr и acct-api-regr. Бэкап, DIVERGED, компиляция, импорт, ожидание строки "cycle ...s" в chan.log, автооткат.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
SVC="chan-orders-regr acct-api-regr"
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak /tmp/tgfast
for a in "$@"; do
  f=${a%%:*}; old=${a#*:}
  git show origin/main:bot/positions/$f > /tmp/tgfast/$f || { echo SHOW_FAIL $f; exit 1; }
  CUR=$(md5sum $P/$f | cut -d' ' -f1); [ "$CUR" = "$old" ] || { echo DIVERGED $f $CUR; exit 1; }
  $VPY -m py_compile /tmp/tgfast/$f || { echo COMPILE_FAIL $f; exit 1; }
done
for a in "$@"; do f=${a%%:*}; cp $P/$f $N/bak/$f.tgfast_$TS; done
rollback() { echo ROLLBACK; for a in "$@"; do f=${a%%:*}; cp $N/bak/$f.tgfast_$TS $P/$f; done; systemctl restart $SVC; exit 1; }
for a in "$@"; do f=${a%%:*}; install -o tbot -g tbot -m 644 /tmp/tgfast/$f $P/$f; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import chan_orders, trend_shadow; print('import ok', hasattr(trend_shadow, 'prefetch'), hasattr(chan_orders, 'prefetch_5m'))") || { echo IMPORT_FAIL; rollback "$@"; }
L0=$(wc -l < $PR/chan.log)
systemctl restart $SVC
sleep 90
BAD=0; for s in $SVC; do A=$(systemctl is-active $s); echo "$s=$A"; [ "$A" = active ] || BAD=1; done
tail -n +$((L0+1)) $PR/chan.log | grep -E "cycle|error" | tail -6 | LC_ALL=C tr -cd '\11\12\40-\176'
if [ $BAD = 1 ] || tail -n +$((L0+1)) $PR/chan.log | grep -q "cycle error"; then rollback "$@"; fi
echo DEPLOY_OK $TS
