#!/bin/bash
# Тени v8 (21.11): (а) swing_stop: перенос стопа за ближайший локальный экстремум после разворотной свечи 1m, только для теней (флаг sw), параллельно считается копия без правила (it.pb) для сравнения; (б) tg_live1m.json max_dist_atr 0.90 -> 0.95 (заметка №40). Перезапускается tg-bot-regr (chan-orders-regr и счета не трогаются). Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow8.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; VPY2=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow8_$TS; N=/tmp/shadownew8
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N/pos $B
for f in patch_swing.py test_swing.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
git show origin/main:bot/positions/swing_stop.py > $N/swing_stop.py || { echo SHOW_FAIL_SW; exit 1; }
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $PC/pos.py $B/; cp $TN/tg_shadow.py $B/; cp $PR/shadow.json $B/shadow.json; cp $PR/tg_live1m.json $B/ 2>/dev/null
cp $PC/*.py $N/pos/; cp $N/swing_stop.py $N/pos/
$VPY2 $N/patch_swing.py $N/pos/pos.py || { echo PATCH_FAIL; exit 1; }
$VPY2 -m py_compile $N/pos/pos.py $N/swing_stop.py || { echo COMPILE_FAIL_POS; exit 1; }
$VPY -m py_compile $N/tg_shadow.py || { echo COMPILE_FAIL_SH; exit 1; }
T=$($VPY2 $N/test_swing.py $N 2>&1 | tail -2); echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "^swing 99.82 100.18 100.07 None None" || { echo SWING_TEST_FAIL; exit 1; }
EN=$(cd $N && POS_DIR=$PR SHADOW_CODE_DIR=$N/pos $VPY -c "import tg_shadow as s; e = s.eng(); print('engine', bool(e), 'sw' in open('$N/pos/pos.py').read())" 2>&1 | tail -2)
echo "$EN" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$EN" | grep -q "engine True True" || { echo ENGINE_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/pos/pos.py $PC/pos.py; install -o tbot -g tbot -m 644 $N/swing_stop.py $PC/swing_stop.py
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
$VPY2 -c "
import json
f='$PR/tg_live1m.json'
try: c=json.load(open(f))
except Exception: c={}
c['max_dist_atr']=0.95
json.dump(c,open(f,'w'))
print('live1m', c)
"
chown tbot:tbot $PR/tg_live1m.json 2>/dev/null
rollback() { echo ROLLBACK; cp $B/pos.py $PC/; cp $B/tg_shadow.py $TN/; rm -f $PC/swing_stop.py; [ -f $B/tg_live1m.json ] && cp $B/tg_live1m.json $PR/; systemctl restart tg-bot-regr; sleep 10; echo ROLLED tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import tg_bot; print('bot import ok', tg_bot.SH is not None)") || { echo IMPORT_FAIL_BOT; rollback; }
systemctl restart tg-bot-regr; sleep 30
G=$(systemctl is-active tg-bot-regr); E=$(journalctl -u tg-bot-regr --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "tg=$G errors=$E"
if [ "$G" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW8_DONE $TS backup=$B
