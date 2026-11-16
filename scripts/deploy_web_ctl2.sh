#!/bin/bash
# Выкладка версии 6 страницы онлайн: H4/D1, галочка «Следить», сообщения в Telegram и журнал по действиям со страницы.
# Патч накладывается на файлы, которые РАБОТАЮТ на VPS (не на версию из git). Идемпотентно (повтор: ALREADY). Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git show origin/main:scripts/deploy_web_ctl2.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; L=/opt/trading-bot/live; TN=/opt/tg-notify; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_web2_$TS; N=/tmp/webnew2
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_web_ctl2.py > $N/patch_web_ctl2.py || { echo SHOW_FAIL; exit 1; }
cp $P/chan_orders.py $P/pos.py $P/tg_gate.py $P/decisions.py $B/; cp $TN/tg_bot.py $B/; cp $L/live_web.py $L/index.html $B/
cp $P/chan_orders.py $P/pos.py $P/tg_gate.py $P/decisions.py $TN/tg_bot.py $L/live_web.py $L/index.html $N/
$VPY $N/patch_web_ctl2.py $N/chan_orders.py $N/pos.py $N/tg_gate.py $N/decisions.py $N/tg_bot.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in chan_orders.py pos.py tg_gate.py decisions.py tg_bot.py live_web.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
install -o tbot -g tbot -m 644 $N/chan_orders.py $P/chan_orders.py; install -o tbot -g tbot -m 644 $N/pos.py $P/pos.py; install -o tbot -g tbot -m 644 $N/tg_gate.py $P/tg_gate.py; install -o tbot -g tbot -m 644 $N/decisions.py $P/decisions.py
install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
systemctl restart acct-api-regr chan-orders-regr live-web tg-bot-regr; sleep 8
A=$(systemctl is-active acct-api-regr); C=$(systemctl is-active chan-orders-regr); W=$(systemctl is-active live-web); G=$(systemctl is-active tg-bot-regr)
H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
T=$(curl -s -m 20 -X POST http://127.0.0.1:18102/api/claude -H 'Content-Type: application/json' -d '{"action":"watch_keep","id":0,"on":true}')
echo "acct=$A chan=$C live=$W tg=$G health=$H test=$T"
if [ "$A" != active ] || [ "$C" != active ] || [ "$W" != active ] || [ "$G" != active ] || [ "$H" != 200 ] || ! echo "$T" | grep -q '"error"'; then
  cp $B/chan_orders.py $B/pos.py $B/tg_gate.py $B/decisions.py $P/; cp $B/tg_bot.py $TN/; cp $B/live_web.py $B/index.html $L/
  systemctl restart acct-api-regr chan-orders-regr live-web tg-bot-regr; sleep 5; echo ROLLBACK acct=$(systemctl is-active acct-api-regr) chan=$(systemctl is-active chan-orders-regr) live=$(systemctl is-active live-web) tg=$(systemctl is-active tg-bot-regr); exit 1
fi
echo WEB_CTL2_DONE $TS backup=$B
