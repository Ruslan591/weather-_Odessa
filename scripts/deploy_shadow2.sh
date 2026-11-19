#!/bin/bash
# Тени v2 (docs/topics/shadow_positions.md): вход через боевой _tg_mkorder и _live1m_gate (свеча 1m пары), сопровождение боевым pos.step, события в канал TG_CHAT_SHADOW.
# Требует установленный патч v1 (deploy_shadow.sh, SHADOW_DONE 20261119_053802). Патч накладывается на рабочие файлы VPS, идемпотентно. Торговые сервисы (chan-orders, acct-api) НЕ перезапускаются. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow2.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; L=/opt/trading-bot/live; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow2_$TS; N=/tmp/shadownew2
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
[ -f $TN/tg_bot.py ] && [ -f $L/live_web.py ] && [ -f $L/index.html ] && [ -f $TN/tg_shadow.py ] || { echo NO_FILES_OR_NO_V1; exit 1; }
grep -q "import tg_shadow as SH" $TN/tg_bot.py || { echo NO_V1_PATCH; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_shadow2.py > $N/patch_shadow2.py || { echo SHOW_FAIL_PATCH; exit 1; }
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $TN/tg_bot.py $TN/tg_shadow.py $L/live_web.py $L/index.html $B/; cp $TN/tg_bot.py $L/live_web.py $L/index.html $N/
cp $PR/shadow.json $B/shadow.json 2>/dev/null
$VPY $N/patch_shadow2.py $N/tg_bot.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in tg_bot.py live_web.py tg_shadow.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
EN=$(cd $N && POS_DIR=$PR $VPY -c "import tg_shadow as s; e = s.eng(); print('engine', bool(e), s.enabled())" 2>&1 | tail -3)
echo "$EN" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$EN" | grep -q "engine True" || { echo ENGINE_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
rollback() { echo ROLLBACK; cp $B/tg_bot.py $B/tg_shadow.py $TN/; cp $B/live_web.py $B/index.html $L/; [ -f $B/shadow.json ] && cp $B/shadow.json $PR/shadow.json; systemctl restart live-web tg-bot-regr; sleep 5; echo ROLLED live=$(systemctl is-active live-web) tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import tg_bot; print('bot import ok', tg_bot.SH is not None)") || { echo IMPORT_FAIL_BOT; rollback; }
systemctl restart live-web tg-bot-regr; sleep 25
W=$(systemctl is-active live-web); G=$(systemctl is-active tg-bot-regr); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
E=$(journalctl -u tg-bot-regr -u live-web --since "-30sec" --no-pager 2>/dev/null | grep -ci "Traceback\|shadow tg:\|боевой код недоступен")
echo "live=$W tg=$G health=$H errors=$E"
journalctl -u tg-bot-regr --since "-30sec" --no-pager 2>/dev/null | grep -i "shadow" | tail -4 | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$W" != active ] || [ "$G" != active ] || [ "$H" != 200 ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW2_DONE $TS backup=$B
