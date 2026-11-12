#!/bin/bash
# deploy_flat_brk.sh pos.py:md5 exit_cfg.py:md5 chan_orders.py:md5 : правило выхода «флэт + пробой» (50% на +0.4R, остаток в БУ с комиссиями).
# Файлы -> /opt/trading-bot/positions. Перезапуск: pos-tracker-regr, chan-orders-regr, acct-api-regr (другие счета правило не получают: у их ордеров нет regime/setup). Бэкап, DIVERGED, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
SVC="pos-tracker-regr chan-orders-regr acct-api-regr"
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak /tmp/fbrk
for a in "$@"; do
  f=${a%%:*}; old=${a#*:}
  git show origin/main:bot/positions/$f > /tmp/fbrk/$f || { echo SHOW_FAIL $f; exit 1; }
  CUR=$(md5sum $P/$f | cut -d' ' -f1); [ "$CUR" = "$old" ] || { echo DIVERGED $f $CUR; exit 1; }
  $VPY -m py_compile /tmp/fbrk/$f || { echo COMPILE_FAIL $f; exit 1; }
done
for a in "$@"; do f=${a%%:*}; cp $P/$f $N/bak/$f.flatbrk_$TS; done
rollback() { echo ROLLBACK; for a in "$@"; do f=${a%%:*}; cp $N/bak/$f.flatbrk_$TS $P/$f; done; systemctl restart $SVC; exit 1; }
for a in "$@"; do f=${a%%:*}; install -o tbot -g tbot -m 644 /tmp/fbrk/$f $P/$f; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import pos, exit_cfg, chan_orders; e=exit_cfg.eff({'xr':'flat_brk','fee_in':0.02}); print('import ok', e['tp1'], e['be']['trig'], e['be']['lock_val'])") || { echo IMPORT_FAIL; rollback "$@"; }
systemctl restart $SVC
sleep 45
BAD=0; for s in $SVC; do A=$(systemctl is-active $s); echo "$s=$A"; [ "$A" = active ] || BAD=1; done
tail -3 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176'
if [ $BAD = 1 ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback "$@"; fi
echo DEPLOY_OK $TS
