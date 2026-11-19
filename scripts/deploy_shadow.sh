#!/bin/bash
# Теневые позиции (пропущенные сигналы «ЗАХОДИТЬ» ведутся на бумаге, на счёт не влияют): tg_shadow.py (новый) + патч tg_bot.py, live_web.py, index.html.
# Патч накладывается на файлы, которые РАБОТАЮТ на VPS. Идемпотентно (повтор: ALREADY). Торговые сервисы (chan-orders, acct-api) НЕ перезапускаются. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; L=/opt/trading-bot/live; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow_$TS; N=/tmp/shadownew
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
[ -f $TN/tg_bot.py ] && [ -f $L/live_web.py ] && [ -f $L/index.html ] || { echo NO_FILES; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_shadow.py > $N/patch_shadow.py || { echo SHOW_FAIL_PATCH; exit 1; }
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $TN/tg_bot.py $L/live_web.py $L/index.html $B/; cp $TN/tg_bot.py $L/live_web.py $L/index.html $N/
[ -f $TN/tg_shadow.py ] && cp $TN/tg_shadow.py $B/
$VPY $N/patch_shadow.py $N/tg_bot.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in tg_bot.py live_web.py tg_shadow.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
(cd $N && POS_DIR=$PR $VPY -c "import tg_shadow as s; print('shadow import ok', s.enabled(), s.stats()['open'])") || { echo IMPORT_FAIL_MODULE; exit 1; }
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
rollback() { echo ROLLBACK; cp $B/tg_bot.py $TN/; cp $B/live_web.py $B/index.html $L/; if [ -f $B/tg_shadow.py ]; then cp $B/tg_shadow.py $TN/; else rm -f $TN/tg_shadow.py; fi; systemctl restart live-web tg-bot-regr; sleep 5; echo ROLLED live=$(systemctl is-active live-web) tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import tg_bot; print('bot import ok', tg_bot.SH is not None)") || { echo IMPORT_FAIL_BOT; rollback; }
systemctl restart live-web tg-bot-regr; sleep 12
W=$(systemctl is-active live-web); G=$(systemctl is-active tg-bot-regr); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
E=$(journalctl -u tg-bot-regr -u live-web --since "-20sec" --no-pager 2>/dev/null | grep -ci "Traceback\|shadow run\|shadow record")
echo "live=$W tg=$G health=$H errors=$E"
if [ "$W" != active ] || [ "$G" != active ] || [ "$H" != 200 ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW_DONE $TS backup=$B
