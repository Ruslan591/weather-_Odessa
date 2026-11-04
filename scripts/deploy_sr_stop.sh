#!/bin/bash
# Deploy patch 6 (auto stop to support/resistance after breakeven). ASCII only.
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions
PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
cd $R || exit 1
git fetch -q origin main || { echo FETCH_FAILED; exit 1; }
B=/opt/trading-bot/backup_sr_stop_$(date +%s); mkdir -p $B
cp $P/pos.py $P/positions.json $B/ || exit 1
git show origin/main:bot/positions/sr_stop.py > /tmp/sr_stop.new || exit 1
git show origin/main:bot/positions/patch_sr_stop.py > /tmp/patch_sr_stop.py || exit 1
rollback() { echo ROLLBACK; cp $B/pos.py $P/; rm -f $P/sr_stop.py; systemctl restart classicbot pos-tracker chan-orders; exit 1; }
cp /tmp/sr_stop.new $P/sr_stop.py; chown --reference=$B/pos.py $P/sr_stop.py
$PY /tmp/patch_sr_stop.py $P || rollback
$PY -m py_compile $P/pos.py $P/sr_stop.py || rollback
systemctl restart classicbot pos-tracker chan-orders
sleep 50
systemctl is-active classicbot pos-tracker chan-orders || rollback
journalctl -u pos-tracker --since '-2min' --no-pager | tail -8
echo SR_LOG; tail -8 $P/sr.log 2>/dev/null
curl -s -m 20 localhost:8091/api/claude | python3 -c "import sys,json;d=json.load(sys.stdin);print([(p['id'],p['sym'],p['side'],p.get('armed'),round(p['stop'],6),(p.get('sr_level') or {}).get('p')) for p in d['open']])"
echo BACKUP=$B
