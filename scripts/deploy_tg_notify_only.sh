#!/bin/bash
# deploy_tg_notify_only.sh <parent_commit>: deploy only tg_notify.py to /opt/tg-notify, restart tg-bot-regr, auto rollback.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; N=/opt/tg-notify; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
git show origin/main:bot/positions/tg_notify.py > /tmp/tg_notify.py.new || { echo SHOW_FAIL; exit 1; }
if [ -n "$PAR" ]; then git show $PAR:bot/positions/tg_notify.py > /tmp/tg_notify.py.par || { echo PARENT_FAIL; exit 1; }; cmp -s /tmp/tg_notify.py.par $N/tg_notify.py || { echo DIVERGED; diff /tmp/tg_notify.py.par $N/tg_notify.py | head -20; exit 1; }; fi
$VPY -m py_compile /tmp/tg_notify.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $N/tg_notify.py $N/bak/tg_notify.py.$TS
install -m 644 /tmp/tg_notify.py.new $N/tg_notify.py
grep -n "^DPI_OUT" $N/tg_notify.py
systemctl restart tg-bot-regr; sleep 15
A=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A"
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A" != active ]; then echo ROLLBACK; cp $N/bak/tg_notify.py.$TS $N/tg_notify.py; systemctl restart tg-bot-regr; exit 1; fi
echo DEPLOY_OK $TS
