#!/bin/bash
# deploy_tg_filters.sh name=md5 ...: фильтр по режиму BTC 1h + снимки BTC 1m/режима в журнал, ордера и разборы.
# /opt/tg-notify: tg_btc1m tg_regime tg_express tg_learn tg_bot tg_review; /opt/trading-bot/positions: tg_gate decisions.
# Проверка расхождения: md5 файла на VPS должен совпасть с переданным (версия предыдущего коммита из GitHub), иначе DIVERGED. Бэкап, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
NF="tg_btc1m tg_regime tg_express tg_learn tg_bot tg_review"; PF="tg_gate decisions"
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in $NF $PF; do git show origin/main:bot/positions/$f.py > /tmp/$f.py.new || { echo "SHOW_FAIL $f"; exit 1; }; done
for a in "$@"; do f=${a%%=*}; m=${a##*=}
  d=$N; case " $PF " in *" $f "*) d=$P;; esac
  [ -f $d/$f.py ] && [ "$(md5sum < $d/$f.py | cut -d' ' -f1)" = "$m" ] || { echo "DIVERGED $f"; exit 1; }
done
for f in $NF $PF; do $VPY -m py_compile /tmp/$f.py.new || { echo "COMPILE_FAIL $f"; exit 1; }; done
mkdir -p $N/bak
for f in $NF; do [ -f $N/$f.py ] && cp $N/$f.py $N/bak/$f.py.$TS; done
for f in $PF; do cp $P/$f.py $N/bak/$f.py.$TS; done
ACCT=""; systemctl is-active --quiet acct-api-regr && ACCT=acct-api-regr
rollback() { echo ROLLBACK; for f in $NF; do [ -f $N/bak/$f.py.$TS ] && cp $N/bak/$f.py.$TS $N/$f.py; done; for f in $PF; do cp $N/bak/$f.py.$TS $P/$f.py; done; systemctl restart tg-bot-regr chan-orders-regr $ACCT; exit 1; }
for f in $PF; do install -o tbot -g tbot -m 644 /tmp/$f.py.new $P/$f.py; done
for f in $NF; do install -m 644 /tmp/$f.py.new $N/$f.py; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders, decisions; print('gate ok', tg_gate.b1_snap('short')); print('mkt', sorted(decisions._mkt().keys()))") || { echo IMPORT_FAIL_GATE; rollback; }
(cd $N && POS_DIR=$PR $VPY -c "import tg_express as X, tg_regime as RG, tg_btc1m as B, tg_learn, tg_review; print('regime cond short', RG.cond('short')); print('regime cond long', RG.cond('long')); print('X', X.RG is not None, X.B1 is not None)" | LC_ALL=C tr -cd '\11\12\40-\176') || { echo IMPORT_FAIL_MODULES; rollback; }
systemctl restart tg-bot-regr chan-orders-regr $ACCT
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2 acct=$ACCT"
tail -2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
