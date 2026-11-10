#!/bin/bash
# deploy_tg_btc1m.sh <parent_commit_tg_express>: фильтр входа по BTC 1m (tg_btc1m.py новый, tg_express.py с 6-м условием) -> /opt/tg-notify, перезапуск tg-bot-regr.
# Бэкап, DIVERGED (tg_express.py сверяется с родительским коммитом), компиляция, проверка импорта, автооткат.
set -u
PAR=${1:-}; R=/opt/weather-pipeline/repo; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in tg_express.py tg_btc1m.py; do git show origin/main:bot/positions/$f > /tmp/$f.new || { echo "SHOW_FAIL $f"; exit 1; }; done
if [ -n "$PAR" ]; then
  git show $PAR:bot/positions/tg_express.py > /tmp/tg_express.py.par && cmp -s /tmp/tg_express.py.par $N/tg_express.py || { echo "DIVERGED tg_express.py"; diff /tmp/tg_express.py.par $N/tg_express.py | head -10; exit 1; }
fi
$VPY -m py_compile /tmp/tg_express.py.new /tmp/tg_btc1m.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $N/tg_express.py $N/bak/tg_express.py.$TS
rollback() { echo ROLLBACK; cp $N/bak/tg_express.py.$TS $N/tg_express.py; rm -f $N/tg_btc1m.py; systemctl restart tg-bot-regr; exit 1; }
for f in tg_express.py tg_btc1m.py; do install -m 644 /tmp/$f.new $N/$f; done
(cd $N && POS_DIR=$PR $VPY -c "import tg_express as X, tg_btc1m as B; g = B.gate('short'); print('btc1m short', None if not g else (g['ok'], g['snap']['rsi'])); g = B.gate('long'); print('btc1m long', None if not g else (g['ok'], g['snap']['rsi'])); print('X.B1', X.B1 is not None)") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr
sleep 30
A1=$(systemctl is-active tg-bot-regr)
echo "tg-bot-regr=$A1"
journalctl -u tg-bot-regr -n 4 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A1" != active ]; then rollback; fi
echo DEPLOY_OK $TS
