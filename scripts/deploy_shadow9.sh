#!/bin/bash
# Тени v9 (21.11): единая нумерация. Показываемый номер sn: A #65, B #65B (один сигнал, разные фильтры); канал, подтверждение заметки и панель «Онлайн» показывают одно и то же; старое поле n (номер сигнала источника, 769...) не используется. Затрагивает tg_shadow.py, tg_bot.py (подтверждение заметки), live_web.py и index.html (панель). Перезапуск tg-bot-regr и live-web. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow9.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; TN=/opt/tg-notify; L=/opt/trading-bot/live; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow9_$TS; N=/tmp/shadownew9
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
for f in patch_numbers.py test_numbers.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $TN/tg_bot.py $TN/tg_shadow.py $B/; cp $L/live_web.py $L/index.html $B/; cp $PR/shadow.json $B/shadow.json
cp $TN/tg_bot.py $N/tg_bot.py; cp $L/live_web.py $L/index.html $N/
$VPY $N/patch_numbers.py $N/tg_bot.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in tg_bot.py tg_shadow.py live_web.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
T=$(cd $N && $VPY $N/test_numbers.py $N $PR/shadow.json 2>&1 | tail -2)
echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "^nums 61 61B 65 65B 67 67B \['61B', '61'\] 67" || { echo NUMS_TEST_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py; install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
rollback() { echo ROLLBACK; cp $B/tg_bot.py $B/tg_shadow.py $TN/; cp $B/live_web.py $B/index.html $L/; systemctl restart tg-bot-regr live-web; sleep 10; echo ROLLED tg=$(systemctl is-active tg-bot-regr) live=$(systemctl is-active live-web); exit 1; }
systemctl restart tg-bot-regr live-web; sleep 30
G=$(systemctl is-active tg-bot-regr); W=$(systemctl is-active live-web); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
E=$(journalctl -u tg-bot-regr -u live-web --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "tg=$G live=$W health=$H errors=$E"
if [ "$G" != active ] || [ "$W" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW9_DONE $TS backup=$B
