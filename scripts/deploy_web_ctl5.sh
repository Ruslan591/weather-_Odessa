#!/bin/bash
# Выкладка версии 9: «Следить» и «Отменить» в одной строке; первый график слежения сразу после нажатия «Следить».
# Патч накладывается на файлы, которые РАБОТАЮТ на VPS. Идемпотентно (повтор: ALREADY). Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_web_ctl5.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; P=/opt/trading-bot/positions; L=/opt/trading-bot/live; TN=/opt/tg-notify; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_web5_$TS; N=/tmp/webnew5
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
[ -f $TN/tg_notify.py ] || { echo NO_TG_NOTIFY; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_web_ctl5.py > $N/patch_web_ctl5.py || { echo SHOW_FAIL; exit 1; }
cp $P/tg_gate.py $L/index.html $TN/tg_bot.py $TN/tg_notify.py $B/
cp $P/tg_gate.py $L/index.html $TN/tg_bot.py $TN/tg_notify.py $N/
$VPY $N/patch_web_ctl5.py $N/tg_gate.py $N/tg_bot.py $N/tg_notify.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in tg_gate.py tg_bot.py tg_notify.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
install -o tbot -g tbot -m 644 $N/tg_gate.py $P/tg_gate.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py; install -o tbot -g tbot -m 644 $N/tg_notify.py $TN/tg_notify.py
systemctl restart acct-api-regr chan-orders-regr live-web tg-bot-regr; sleep 8
A=$(systemctl is-active acct-api-regr); C=$(systemctl is-active chan-orders-regr); W=$(systemctl is-active live-web); G=$(systemctl is-active tg-bot-regr)
H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
T=$(curl -s -m 20 -X POST http://127.0.0.1:18102/api/claude -H 'Content-Type: application/json' -d '{"action":"watch_cancel","id":0}')
echo "acct=$A chan=$C live=$W tg=$G health=$H test=$T"
if [ "$A" != active ] || [ "$C" != active ] || [ "$W" != active ] || [ "$G" != active ] || [ "$H" != 200 ] || ! echo "$T" | grep -q '"error"'; then
  cp $B/tg_gate.py $P/; cp $B/index.html $L/; cp $B/tg_bot.py $B/tg_notify.py $TN/
  systemctl restart acct-api-regr chan-orders-regr live-web tg-bot-regr; sleep 5; echo ROLLBACK acct=$(systemctl is-active acct-api-regr) chan=$(systemctl is-active chan-orders-regr) live=$(systemctl is-active live-web) tg=$(systemctl is-active tg-bot-regr); exit 1
fi
echo WEB_CTL5_DONE $TS backup=$B
