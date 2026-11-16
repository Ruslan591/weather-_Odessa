#!/bin/bash
# Выкладка управления ждущим ордером со страницы онлайн: патч накладывается на файлы, которые РАБОТАЮТ на VPS (не на версию из git), чтобы не выкатить чужие невыложенные правки.
# Запуск: cd /opt/weather-pipeline/repo && git show origin/main:scripts/deploy_ord_manage.sh | bash -s   (через мост, вывод пропускать через ASCII-фильтр)
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; L=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_ord_$TS; N=/tmp/ordnew
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_ord_manage.py > $N/patch_ord_manage.py || { echo SHOW_FAIL; exit 1; }
cp $P/chan_orders.py $P/pos.py $B/; cp $L/live_web.py $L/index.html $B/
cp $P/chan_orders.py $P/pos.py $L/live_web.py $L/index.html $N/
$VPY $N/patch_ord_manage.py $N/chan_orders.py $N/pos.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in chan_orders.py pos.py live_web.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
install -o tbot -g tbot -m 644 $N/chan_orders.py $P/chan_orders.py; install -o tbot -g tbot -m 644 $N/pos.py $P/pos.py
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
systemctl restart acct-api-regr chan-orders-regr live-web; sleep 8
A=$(systemctl is-active acct-api-regr); C=$(systemctl is-active chan-orders-regr); W=$(systemctl is-active live-web)
H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
T=$(curl -s -m 20 -X POST http://127.0.0.1:18102/api/claude -H 'Content-Type: application/json' -d '{"action":"ord_cancel","id":0}')
echo "acct=$A chan=$C live=$W health=$H test=$T"
if [ "$A" != active ] || [ "$C" != active ] || [ "$W" != active ] || [ "$H" != 200 ] || ! echo "$T" | grep -q '"error"'; then
  cp $B/chan_orders.py $B/pos.py $P/; cp $B/live_web.py $B/index.html $L/
  systemctl restart acct-api-regr chan-orders-regr live-web; sleep 5; echo ROLLBACK acct=$(systemctl is-active acct-api-regr) chan=$(systemctl is-active chan-orders-regr) live=$(systemctl is-active live-web); exit 1
fi
echo ORD_MANAGE_DONE $TS backup=$B
