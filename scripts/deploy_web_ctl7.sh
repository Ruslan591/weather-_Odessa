#!/bin/bash
# Версия 11: свободный слот слежения занимается новой парой сразу (цикл ~5 с), без ожидания закрытия следующей свечи 5m. Только chan_orders.py. Идемпотентно, откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_web_ctl7.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_web7_$TS; N=/tmp/webnew7
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_web_ctl7.py > $N/patch_web_ctl7.py || { echo SHOW_FAIL; exit 1; }
cp $P/chan_orders.py $B/; cp $P/chan_orders.py $N/
$VPY $N/patch_web_ctl7.py $N/chan_orders.py || { echo PATCH_FAIL; exit 1; }
$VPY -m py_compile $N/chan_orders.py || { echo COMPILE_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/chan_orders.py $P/chan_orders.py
systemctl restart chan-orders-regr; sleep 40
C=$(systemctl is-active chan-orders-regr)
E=$(journalctl -u chan-orders-regr --since "-45sec" --no-pager 2>/dev/null | grep -ci "refill.*error\|Traceback")
echo "chan=$C errors=$E"
if [ "$C" != active ] || [ "$E" != 0 ]; then cp $B/chan_orders.py $P/; systemctl restart chan-orders-regr; echo ROLLBACK; exit 1; fi
echo WEB_CTL7_DONE $TS backup=$B
