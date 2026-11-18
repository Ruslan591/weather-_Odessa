#!/bin/bash
# deploy_tg_tf.sh <parent_commit> (PAR2=<второй> в окружении): переключаемый таймфрейм сканера отбоя/пробоя (5m 15m 1h 4h 1d), кнопка и /tf в боте.
# positions (chan-orders-regr): chan_orders.py tg_gate.py; /opt/tg-notify (tg-bot-regr): tg_bot tg_express tg_post tg_notify tg_learn tg_review tg_target (tg_target и в positions).
# Бэкап, DIVERGED (сравнение с родительским коммитом), компиляция, импорт, проверка расчёта каналов по 15m/1h/4h/1d на живых свечах, автооткат. Переключение таймфрейма не делает: по умолчанию 5m.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
PAIRS="chan_orders.py:$P tg_gate.py:$P tg_target.py:$P tg_bot.py:$N tg_express.py:$N tg_post.py:$N tg_notify.py:$N tg_learn.py:$N tg_review.py:$N tg_target.py:$N"
mkdir -p /tmp/tft $N/bak
for pair in $PAIRS; do f=${pair%%:*}; d=${pair##*:}
  [ -f $d/$f ] || { echo "SKIP_NOFILE $d/$f"; continue; }
  git show origin/main:bot/positions/$f > /tmp/tft/$f || { echo SHOW_FAIL $f; exit 1; }
  if [ -n "$PAR" ]; then   # VPS должен совпасть с одним из родительских коммитов (PAR, PAR2)
    same=0; for pc in $PAR ${PAR2:-}; do git show $pc:bot/positions/$f > /tmp/tft/$f.par 2>/dev/null && cmp -s /tmp/tft/$f.par $d/$f && same=1 && break; done
    [ $same = 1 ] || { echo "DIVERGED $d/$f"; diff /tmp/tft/$f.par $d/$f | head -8; exit 1; }
  fi
  $VPY -m py_compile /tmp/tft/$f || { echo COMPILE_FAIL $f; exit 1; }
done
for pair in $PAIRS; do f=${pair%%:*}; d=${pair##*:}; [ -f $d/$f ] && cp $d/$f $N/bak/$f.$(basename $d).tf$TS; done
rollback() { echo ROLLBACK; for pair in $PAIRS; do f=${pair%%:*}; d=${pair##*:}; [ -f $N/bak/$f.$(basename $d).tf$TS ] && cp $N/bak/$f.$(basename $d).tf$TS $d/$f; done; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
for pair in $PAIRS; do f=${pair%%:*}; d=${pair##*:}; [ -f $d/$f ] || continue
  if [ $d = $P ]; then install -o tbot -g tbot -m 644 /tmp/tft/$f $d/$f; else install -m 644 /tmp/tft/$f $d/$f; fi
done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "
import time, chan_orders as c, tg_gate as g
print('gate tf', g.cur_tf(), sorted(g.TFS))
now = int(time.time() * 1000)
for tf in ('15m', '1h', '4h', '1d'):
    A = c.analyze('ETH', now, tf); i = c._tg_info('ETH', A) if A else None
    print(tf, 'M', A and A['M'], 'ctype', i and i['ctype'], 'R', i and i.get('R'))
") || { echo IMPORT_FAIL_POS; rollback; }
(cd $N && POS_DIR=$PR $VPY -c "
import tg_bot, tg_express as X, tg_post, tg_notify as T
print('import ok', X.btc_blocks('5m'), X.btc_blocks('15m'), X.btc_blocks('1h'), tg_bot.cur_tf())
") || { echo IMPORT_FAIL_BOT; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -3 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
