#!/bin/bash
# deploy_tg_update6.sh: account status card as image, watch-chart touch marker offset. Files: tg_bot.py tg_notify.py (/opt/tg-notify). Restarts only tg-bot-regr.
set -u
R=/opt/weather-pipeline/repo; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VP=$N/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak; for f in tg_bot.py tg_notify.py; do cp $N/$f $N/bak/$f.$TS; done
for f in tg_bot.py tg_notify.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VP -m py_compile /tmp/tg_bot.py.new /tmp/tg_notify.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; for f in tg_bot.py tg_notify.py; do cp $N/bak/$f.$TS $N/$f; done; systemctl restart tg-bot-regr; exit 1; }
for f in tg_bot.py tg_notify.py; do install -m 644 /tmp/$f.new $N/$f; done
out=$(cd $N && POS_DIR=$PR $VP -c "
import tg_bot as B, tg_notify as T
d = B.status_data(); png = T.render_status(d); open('/tmp/status_check.png', 'wb').write(png); print('status render ok bytes', len(png), '|', B.status_caption(d))
" 2>&1 | tail -4); rc=$?; echo "$out"; echo "$out" | grep -q "status render ok" || { echo STATUS_CHECK_FAIL; rollback; }
out=$(cd $N && POS_DIR=$PR $VP -c "
import json, tg_notify as T
W = json.load(open('$PR/tg_watch.json'))['items']; w = dict(W[-1]); kl = json.load(open('/tmp/klcache/%s_5m_1000.json' % w['sym'])); print('watch render ok', len(T.render_watch(w, kl)), w['sym'])
" 2>&1 | tail -3); echo "$out"
systemctl restart tg-bot-regr
sleep 12
A1=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A1"
journalctl -u tg-bot-regr -n 4 --no-pager | cut -c1-200
if [ "$A1" != active ] || journalctl -u tg-bot-regr -n 6 --no-pager | grep -q Traceback; then rollback; fi
echo DEPLOY_OK $TS
