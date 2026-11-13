#!/bin/bash
# deploy_tg_brkcr.sh tg_express=md5 : фильтр «пробой против режима рынка» (тело >= 0.6, закрытий за линией <= 5) в tg_express.verdict_break -> /opt/tg-notify, перезапуск tg-bot-regr. md5 на VPS должен совпасть (DIVERGED), бэкап, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
git show origin/main:bot/positions/tg_express.py > /tmp/tg_express.py.new || { echo SHOW_FAIL; exit 1; }
for a in "$@"; do f=${a%%=*}; m=${a##*=}; [ "$(md5sum < $N/$f.py | cut -d' ' -f1)" = "$m" ] || { echo "DIVERGED $f"; exit 1; }; done
$VPY -m py_compile /tmp/tg_express.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $N/tg_express.py $N/bak/tg_express.py.$TS
rollback() { echo ROLLBACK; cp $N/bak/tg_express.py.$TS $N/tg_express.py; systemctl restart tg-bot-regr; exit 1; }
install -m 644 /tmp/tg_express.py.new $N/tg_express.py
(cd $N && POS_DIR=$PR $VPY -c "import tg_bot, tg_express as X; print('brkcr cfg', X._brk_cr_cfg())") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr; sleep 30
A1=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A1"
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
[ "$A1" = active ] || rollback
echo DEPLOY_OK $TS
