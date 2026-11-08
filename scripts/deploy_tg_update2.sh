#!/bin/bash
# deploy_tg_update2.sh: слежение за касаниями (Монитор): chan_orders.py, decisions.py, tg_gate.py (в positions), tg_bot.py, tg_notify.py (в /opt/tg-notify). Бэкап, проверка на реальных данных, автооткат.
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak
for f in chan_orders.py decisions.py tg_gate.py; do cp $P/$f $N/bak/$f.$TS; done; for f in tg_bot.py tg_notify.py; do cp $N/$f $N/bak/$f.$TS; done
for f in chan_orders.py decisions.py tg_gate.py tg_notify.py tg_bot.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
$VPY -m py_compile /tmp/chan_orders.py.new /tmp/decisions.py.new /tmp/tg_gate.py.new /tmp/tg_notify.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
rollback() { echo ROLLBACK; for f in chan_orders.py decisions.py tg_gate.py; do cp $N/bak/$f.$TS $P/$f; done; for f in tg_bot.py tg_notify.py; do cp $N/bak/$f.$TS $N/$f; done; systemctl restart tg-bot-regr chan-orders-regr; exit 1; }
for f in chan_orders.py decisions.py tg_gate.py; do install -o tbot -g tbot -m 644 /tmp/$f.new $P/$f; done
install -m 644 /tmp/tg_notify.py.new $N/tg_notify.py; install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY -c "import tg_gate, chan_orders") || { echo IMPORT_FAIL; rollback; }
echo "--- real-data check (_tg_info, _tg_mkorder):"
(cd $P && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=0 timeout 120 $VPY -c "
import time, chan_orders as c
for sym in ('SOL','ETH','XRP','LINK','DOGE','ADA'):
    A = c.analyze(sym, int(time.time()*1000))
    if not A: print(sym, 'no data'); continue
    i = c._tg_info(sym, A)
    print(sym, i['ctype'], {k: round(v, 5) for k, v in i.items() if isinstance(v, float)})
    if i['ctype']:
        w = {'sym': sym, 'side': 'short' if i['ctype'] == 'channel_down' else 'long', 'ctype': i['ctype'], 'chan': i['chan'], 't_alert': i['t'], 'updates': 2, 'last': {k: i[k] for k in ('t','o','h','l','c','atr','R','S','Rn','Sn')}}
        for entry in ('market', 'limit'):
            for tg in ('opp', 'mid', 'q1', 'q3'):
                o, why = c._tg_mkorder(w, entry, tg, i['c'])
                print('   ', entry, tg, ('price %.6g stop %.6g tp %.6g' % (o['price'], o['stop'], o['tp'])) if o else why)
        break
" 2>&1 | tail -16)
systemctl restart tg-bot-regr chan-orders-regr
sleep 40
A1=$(systemctl is-active tg-bot-regr); A2=$(systemctl is-active chan-orders-regr)
echo "tg-bot-regr=$A1 chan-orders-regr=$A2"
tail -2 $PR/chan.log | cut -c1-160
journalctl -u tg-bot-regr -n 3 --no-pager | cut -c1-200
if [ "$A1" != active ] || [ "$A2" != active ] || tail -5 $PR/chan.log | grep -q "cycle error"; then rollback; fi
echo DEPLOY_OK $TS
