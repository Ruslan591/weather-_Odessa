#!/bin/bash
# Deploy patch 7: manual stop by PRICE per position, protected from auto changes. ASCII only.
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; C=/opt/trading-bot/classic
PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
cd $R || exit 1
git fetch -q origin main || { echo FETCH_FAILED; exit 1; }
B=/opt/trading-bot/backup_stop_ui_$(date +%s); mkdir -p $B
cp $P/pos.py $P/sr_stop.py $P/positions.json $B/ || exit 1
cp $C/classic_pos_html.py $B/ || exit 1
echo PANEL_MD5_BEFORE $(md5sum $C/classic_pos_html.py | cut -c1-32)
git show origin/main:bot/positions/sr_stop.py > /tmp/sr_stop.new || exit 1
git show origin/main:bot/positions/patch_stop_ui.py > /tmp/patch_stop_ui.py || exit 1
rollback() { echo ROLLBACK; cp $B/pos.py $B/sr_stop.py $P/; cp $B/classic_pos_html.py $C/; systemctl restart classicbot pos-tracker chan-orders; exit 1; }
cp /tmp/sr_stop.new $P/sr_stop.py
$PY /tmp/patch_stop_ui.py $C $P || rollback
$PY -m py_compile $P/pos.py $P/sr_stop.py $C/classic_pos_html.py || rollback
systemctl restart classicbot pos-tracker chan-orders
sleep 50
systemctl is-active classicbot pos-tracker chan-orders || rollback
for PORT in 18091 8091; do N=$(curl -s -m 20 localhost:$PORT/ | grep -c clStopBox); echo PORT $PORT clStopBox_lines=$N; done
curl -s -m 30 localhost:18091/api/claude | python3 -c "import sys,json;d=json.load(sys.stdin);print([(p['id'],p['sym'],p['side'],round(p['stop'],6),p.get('stop_manual'),(p.get('sr_level') or {}).get('p')) for p in d['open']])" 2>&1 | head -3
journalctl -u pos-tracker --since '-2min' --no-pager | tail -4
echo BACKUP=$B
