#!/bin/bash
# deploy_tg_rsi5.sh name=md5 ...: фильтр RSI(14) 5m для отбоя (tg_express.py) и строка RSI 5m в постах не-экспресс (tg_bot.py) -> /opt/tg-notify, перезапуск tg-bot-regr. md5 на VPS должен совпасть с переданным (DIVERGED), бэкап, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
for f in tg_express tg_bot; do git show origin/main:bot/positions/$f.py > /tmp/$f.py.new || { echo "SHOW_FAIL $f"; exit 1; }; done
for a in "$@"; do f=${a%%=*}; m=${a##*=}; [ "$(md5sum < $N/$f.py | cut -d' ' -f1)" = "$m" ] || { echo "DIVERGED $f"; exit 1; }; done
$VPY -m py_compile /tmp/tg_express.py.new /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; for f in tg_express tg_bot; do cp $N/$f.py $N/bak/$f.py.$TS; done
rollback() { echo ROLLBACK; for f in tg_express tg_bot; do cp $N/bak/$f.py.$TS $N/$f.py; done; systemctl restart tg-bot-regr; exit 1; }
for f in tg_express tg_bot; do install -m 644 /tmp/$f.py.new $N/$f.py; done
(cd $N && POS_DIR=$PR $VPY -c "import tg_bot, tg_express as X; print('rsi cfg', X._rcfg())") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr; sleep 30
A1=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A1"
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
[ "$A1" = active ] || rollback
echo DEPLOY_OK $TS
