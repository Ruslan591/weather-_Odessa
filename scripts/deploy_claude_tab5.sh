#!/bin/bash
# Deploy patch 5 (channel on open position chart, Claude tab). ASCII only.
R=/opt/weather-pipeline/repo; C=/opt/trading-bot/classic; P=/opt/trading-bot/positions
PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
cd $R || exit 1
git fetch -q origin main || { echo FETCH_FAILED; exit 1; }
B=/opt/trading-bot/backup_tab5_$(date +%s); mkdir -p $B
cp $C/classic_pos_html.py $P/pos.py $B/ || exit 1
git show origin/main:bot/positions/patch_claude_tab5.py > /tmp/patch_claude_tab5.py || exit 1
rollback() { echo ROLLBACK; cp $B/classic_pos_html.py $C/; cp $B/pos.py $P/; systemctl restart classicbot pos-tracker chan-orders; exit 1; }
$PY /tmp/patch_claude_tab5.py $C $P || rollback
$PY -m py_compile $C/classic_pos_html.py $P/pos.py || rollback
systemctl restart classicbot pos-tracker chan-orders
for i in 1 2 3 4 5 6 7 8; do sleep 10; if curl -s -m 20 localhost:8091/api/claude | head -c 60 | grep -q account; then echo PANEL_OK; curl -s localhost:8091/api/claude | python3 -c "import sys,json;d=json.load(sys.stdin);print([(p['id'],p['sym'],p.get('o_rule'),bool(p.get('o_chan')),p.get('o_err'),len(p.get('cand',[]))) for p in d['open']])"; systemctl is-active classicbot pos-tracker chan-orders; echo BACKUP=$B; exit 0; fi; done
echo PANEL_FAIL; rollback
