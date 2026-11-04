#!/bin/bash
# Deploy chan_orders: retest with confirmation (chan_top/chan_bottom off by flag) + trend shadow log. ASCII only.
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions
PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
cd $R || exit 1
git fetch -q origin main || { echo FETCH_FAILED; exit 1; }
B=/opt/trading-bot/backup_chan_retest_$(date +%s); mkdir -p $B
cp $P/chan_orders.py $B/ || exit 1
[ -f $P/trend_shadow.py ] && cp $P/trend_shadow.py $B/
cp $P/orders.json $B/ 2>/dev/null
git show origin/main:bot/positions/chan_orders.py > /tmp/chan_orders.new || exit 1
git show origin/main:bot/positions/trend_shadow.py > /tmp/trend_shadow.new || exit 1
rollback() { echo ROLLBACK; cp $B/chan_orders.py $P/; [ -f $B/trend_shadow.py ] || rm -f $P/trend_shadow.py; cp $B/orders.json $P/ 2>/dev/null; systemctl restart chan-orders; exit 1; }
cp /tmp/chan_orders.new $P/chan_orders.py; cp /tmp/trend_shadow.new $P/trend_shadow.py
chown --reference=$B/chan_orders.py $P/chan_orders.py $P/trend_shadow.py
$PY -m py_compile $P/chan_orders.py $P/trend_shadow.py || rollback
cd $P && sudo -u tbot env POS_DIR=$P $PY chan_orders.py scan --dry 2>&1 | tail -6
systemctl restart chan-orders
sleep 45
systemctl is-active chan-orders || rollback
tail -15 $P/chan.log
echo EVENTS; cat $P/chan_events.json 2>/dev/null | head -c 600
echo; echo BACKUP=$B
