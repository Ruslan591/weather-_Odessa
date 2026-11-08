#!/bin/bash
# deploy_tg_update4.sh: original channel overlay in watch charts, alerts on both lines, bounce/breakout x market/limit/stop orders. Files: chan_orders.py tg_gate.py (positions), tg_bot.py tg_notify.py (/opt/tg-notify).
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak
for f in chan_orders.py tg_gate.py; do cp $P/$f $N/bak/$f.$TS; done; for f in tg_bot.py tg_notify.py; do cp $N/$f $N/bak/$f.$TS; done
for f in chan_orders.py tg_gate.py tg_bot.py tg_notify.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/tg_gate.py.new /tmp/tg_bot.py.new /tmp/tg_notify.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; for f in chan_orders.py tg_gate.py; do cp $N/bak/$f.$TS $P/$f; done; for f in tg_bot.py tg_notify.py; do cp $N/bak/$f.$TS $N/$f; done; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
for f in chan_orders.py tg_gate.py; do install -o tbot -g tbot -m 644 /tmp/$f.new $P/$f; done
install -m 644 /tmp/tg_notify.py.new $N/tg_notify.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders") || { echo IMPORT_FAIL; rollback; }
echo "--- real-data check: orders for every setup/entry/target on live channels"
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=0 timeout 150 $VPY -c "
import time, chan_orders as c, tg_gate
n = 0
for sym in ('SOL','ETH','XRP','LINK','DOGE','ADA'):
    A = c.analyze(sym, int(time.time()*1000))
    if not A: print(sym, 'no data'); continue
    i = c._tg_info(sym, A)
    if not i['ctype']: print(sym, 'no channel'); continue
    for line in ('upper', 'lower'):
        ep = tg_gate._episode(i, line)
        w = {'sym': sym, 'side': 'short' if line == 'upper' else 'long', 'line': line, 'ctype': i['ctype'], 'chan': i['chan'], 't_alert': i['t'], 'updates': 2, 'last': {k: i[k] for k in ('t','o','h','l','c','atr','R','S','Rn','Sn')}}
        for setup, tgs in (('bounce', ('opp','mid')), ('breakout', ('h05','h1'))):
            for entry in ('market','limit','stop'):
                o, why = c._tg_mkorder(w, entry, tgs[0], i['c'], setup)
                n += 1; print(sym, line, setup, entry, ('%s %s price %.6g stop %.6g tp %.6g' % (o['rule'], o['side'], o['price'], o['stop'], o['tp'])) if o else why)
    break
print('episodes: upper', tg_gate._episode(i, 'upper'), 'lower', tg_gate._episode(i, 'lower'))
" 2>&1 | tail -22 | LC_ALL=C tr -cd '\11\12\40-\176')
echo "--- render check (watch chart with chan0)"
(cd $N && POS_DIR=$PR $N/venv/bin/python -c "
import json, tg_notify as T
W = json.load(open('$PR/tg_watch.json'))['items']; w = dict(W[-1])
kl = json.load(open('/tmp/klcache/%s_5m_1000.json' % w['sym']))
import copy; c0 = copy.deepcopy(w['chan']); c0['upper']['p1'] += 0.0002 * c0['upper']['p1']; c0['lower']['p1'] += 0.0002 * c0['lower']['p1']; w['chan0'] = c0
png = T.render_watch(w, kl); print('render ok bytes', len(png), w['sym'])
" 2>&1 | tail -3 | LC_ALL=C tr -cd '\11\12\40-\176')
systemctl restart tg-bot-regr chan-orders-regr
sleep 50
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -3 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176'
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
