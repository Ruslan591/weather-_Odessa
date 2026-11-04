#!/bin/bash
# Deploy patch 4 (zoomable charts, Claude tab) + longer candle history. ASCII only.
R=/opt/weather-pipeline/repo; C=/opt/trading-bot/classic; P=/opt/trading-bot/positions
PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
cd $R || exit 1
git fetch -q origin main || { echo FETCH_FAILED; exit 1; }
B=/opt/trading-bot/backup_tab4_$(date +%s); mkdir -p $B
cp $C/classic_pos_html.py $P/pos.py $P/chan_orders.py $B/ || exit 1
git show origin/main:bot/positions/patch_claude_tab4.py > /tmp/patch_claude_tab4.py || exit 1
rollback() { echo ROLLBACK; cp $B/classic_pos_html.py $C/; cp $B/pos.py $B/chan_orders.py $P/; systemctl restart classicbot pos-tracker chan-orders; exit 1; }
$PY /tmp/patch_claude_tab4.py $C || rollback
grep -c '"15m", 120)' $P/pos.py; sed -i 's/"15m", 120)\]/"15m", 300)]/' $P/pos.py
grep -c '"5m", 150)' $P/chan_orders.py; sed -i 's/pos.kl(sym + "USDT", "5m", 150)/pos.kl(sym + "USDT", "5m", 300)/; s/lo = max(0, A\["M"\] - 150)/lo = max(0, A["M"] - 300)/' $P/chan_orders.py
$PY -m py_compile $C/classic_pos_html.py $P/pos.py $P/chan_orders.py || rollback
systemctl restart classicbot pos-tracker chan-orders
for i in 1 2 3 4 5 6 7 8; do sleep 10; if curl -s -m 20 localhost:8091/api/claude | head -c 60 | grep -q account; then echo PANEL_OK; curl -s localhost:8091/ | grep -c clZInit; systemctl is-active classicbot pos-tracker chan-orders; echo BACKUP=$B; exit 0; fi; done
echo PANEL_FAIL; rollback
