#!/bin/bash
# Тени v3 часть 1: (а) правило «не подтверждать вход в первые секунды свечи 1m пары» в chan_orders._live1m_gate (patch_gate_age.py), (б) меню статистики в канале «Фон» (patch_shadow3.py + tg_shadow.py).
# Перезапускаются chan-orders-regr (код входа) и tg-bot-regr (тени используют тот же код). acct-api и live-web не трогаются. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow3.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; VPY2=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow3_$TS; N=/tmp/shadownew3
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
grep -q "def shadow_tg_loop" $TN/tg_bot.py || { echo NO_V2_PATCH; exit 1; }
rm -rf $N; mkdir -p $N/pos $B
for f in patch_gate_age.py patch_shadow3.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $PC/chan_orders.py $B/; cp $TN/tg_bot.py $TN/tg_shadow.py $B/
cp $PC/*.py $N/pos/; cp $TN/tg_bot.py $N/tg_bot.py
$VPY2 $N/patch_gate_age.py $N/pos/chan_orders.py || { echo PATCH_FAIL_GATE; exit 1; }
$VPY $N/patch_shadow3.py $N/tg_bot.py || { echo PATCH_FAIL_MENU; exit 1; }
$VPY2 -m py_compile $N/pos/chan_orders.py || { echo COMPILE_FAIL_CO; exit 1; }
for f in tg_bot.py tg_shadow.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
T=$(cd $N/pos && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY2 -c "
import time, chan_orders as C
C._l1m_emit = lambda *a, **k: None; C.log = lambda m: None
far = int(time.time() * 1000) - 3 * 3600000; far -= far % 60000
def g(sec):
    o = {'sym': 'X', 'side': 'short', 'atr': 0.05, 'line_px': 7.30, 'price': 7.29, 'stop': 7.35, 'tp': 7.10}
    return C._live1m_gate(o, far + int(sec * 1000), cfg={'enabled': True, 'max_dist_atr': 0.9}, price_fn=lambda s: 7.28, candle_fn=lambda: (7.29, 7.28))[0]
print('gate', g(3), g(9.5), g(30))
" 2>&1 | tail -2)
echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "gate wait wait go" || { echo GATE_TEST_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/pos/chan_orders.py $PC/chan_orders.py
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py; install -o tbot -g tbot -m 644 $N/tg_bot.py $TN/tg_bot.py
rollback() { echo ROLLBACK; cp $B/chan_orders.py $PC/; cp $B/tg_bot.py $B/tg_shadow.py $TN/; systemctl restart chan-orders-regr tg-bot-regr; sleep 8; echo ROLLED chan=$(systemctl is-active chan-orders-regr) tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import tg_bot; print('bot import ok', tg_bot.SH is not None)") || { echo IMPORT_FAIL_BOT; rollback; }
PEND=$($VPY2 -c "import json; print(sum(1 for o in json.load(open('$PR/orders.json')) if o.get('status')=='pending' and o.get('rule')=='tg_market'))" 2>/dev/null)
echo "pending tg_market orders: $PEND"
systemctl restart chan-orders-regr tg-bot-regr; sleep 30
C1=$(systemctl is-active chan-orders-regr); G=$(systemctl is-active tg-bot-regr)
E=$(journalctl -u tg-bot-regr -u chan-orders-regr --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "chan=$C1 tg=$G errors=$E"
journalctl -u tg-bot-regr --since "-35sec" --no-pager 2>/dev/null | grep -i "shadow" | tail -3 | LC_ALL=C tr -cd '\11\12\40-\176'
tail -n 2 $PR/chan.log | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$C1" != active ] || [ "$G" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW3_DONE $TS backup=$B
