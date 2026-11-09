#!/bin/bash
# deploy_tg_selflearn.sh <parent_commit>: самообучение (разбор закрытых сделок, коррекции порогов), база по пробоям, лимиты слежения в экспрессе.
# tg_gate.py -> positions (chan-orders-regr); tg_bot/tg_express/tg_learn/tg_review -> /opt/tg-notify (tg-bot-regr). Бэкап, DIVERGED, компиляция, импорт, автооткат.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in tg_gate.py tg_bot.py tg_express.py tg_learn.py tg_review.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
if [ -n "$PAR" ]; then
  for pair in tg_gate.py:$P tg_bot.py:$N tg_express.py:$N tg_learn.py:$N; do f=${pair%%:*}; d=${pair##*:}
    git show $PAR:bot/positions/$f > /tmp/$f.par && cmp -s /tmp/$f.par $d/$f || { echo "DIVERGED $f"; diff /tmp/$f.par $d/$f | head -10; exit 1; }
  done
fi
$VPY -m py_compile /tmp/tg_gate.py.new /tmp/tg_bot.py.new /tmp/tg_express.py.new /tmp/tg_learn.py.new /tmp/tg_review.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $P/tg_gate.py $N/bak/tg_gate.py.$TS; for f in tg_bot.py tg_express.py tg_learn.py; do cp $N/$f $N/bak/$f.$TS; done
rollback() { echo ROLLBACK; cp $N/bak/tg_gate.py.$TS $P/tg_gate.py; for f in tg_bot.py tg_express.py tg_learn.py; do cp $N/bak/$f.$TS $N/$f; done; rm -f $N/tg_review.py; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
install -o tbot -g tbot -m 644 /tmp/tg_gate.py.new $P/tg_gate.py
for f in tg_bot.py tg_express.py tg_learn.py tg_review.py; do install -m 644 /tmp/$f.new $N/$f; done
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders; print('gate ok')") || { echo IMPORT_FAIL_GATE; rollback; }
(cd $N && POS_DIR=$PR $VPY -c "import tg_review as RV, tg_express as X, tg_learn as L; print('modules ok', RV.corr()['wick_min'], hasattr(L, 'record_brk')); print(RV.summary(L)[:200].encode('ascii','replace').decode())") || { echo IMPORT_FAIL_MODULES; rollback; }
systemctl restart tg-bot-regr chan-orders-regr
sleep 45
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-160
journalctl -u tg-bot-regr -n 4 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
ls -la $PR/tg_reviewed.json 2>&1 | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
