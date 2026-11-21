#!/bin/bash
# Тени v7 (21.11): (а) фильтр входа: все младшие таймфреймы параллельно (1h -> 15m, 5m, 1m) и доля 1/6 как ВРЕМЯ по ходу сделки (patch_gate_multi.py, chan_orders; действует и на реальные ордера из слежения), (б) B делит номер с A (#42 и #42B) (tg_shadow.py). Требует патчи gate_age и gate_tf. Перезапускаются chan-orders-regr и tg-bot-regr. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow7.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; VPY2=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow7_$TS; N=/tmp/shadownew7
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
grep -q "_pair_live_candle_tf" $PC/chan_orders.py || { echo NO_GATE_TF_PATCH; exit 1; }
rm -rf $N; mkdir -p $N/pos $B
for f in patch_gate_multi.py test_gate_multi.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
cp $PC/chan_orders.py $B/; cp $TN/tg_shadow.py $B/; cp $PR/shadow.json $B/shadow.json
cp $PC/*.py $N/pos/
$VPY2 $N/patch_gate_multi.py $N/pos/chan_orders.py || { echo PATCH_FAIL; exit 1; }
$VPY2 -m py_compile $N/pos/chan_orders.py || { echo COMPILE_FAIL_CO; exit 1; }
$VPY -m py_compile $N/tg_shadow.py || { echo COMPILE_FAIL_SH; exit 1; }
T=$(cd $N/pos && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY2 $N/test_gate_multi.py 2>&1 | tail -4)
echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "^gate wait go wait go wait go wait go" || { echo GATE_TEST_FAIL; exit 1; }
echo "$T" | grep -q "^run wait go wait wait wait wait go" || { echo RUN_TEST_FAIL; exit 1; }
EN=$(cd $N && POS_DIR=$PR SHADOW_CODE_DIR=$N/pos $VPY -c "import tg_shadow as s; e = s.eng(); print('engine', bool(e), hasattr(e['CO'], '_dir_run_s') if e else None, s.tag({'id': 5, 'n': 3, 'var': 'B'}), s.tag({'id': 5}), s.chain_txt({'chain': [{'tf': '15m', 'run': 200, 'need': 150, 'ok': 1}, {'tf': '5m', 'run': 20, 'need': 50, 'ok': 0, 'side': 1}]}))" 2>&1 | tail -2)
echo "$EN" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$EN" | grep -q "engine True True 3B 5" || { echo ENGINE_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/pos/chan_orders.py $PC/chan_orders.py
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
rollback() { echo ROLLBACK; cp $B/chan_orders.py $PC/; cp $B/tg_shadow.py $TN/; systemctl restart chan-orders-regr tg-bot-regr; sleep 10; echo ROLLED chan=$(systemctl is-active chan-orders-regr) tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import tg_bot; print('bot import ok', tg_bot.SH is not None)") || { echo IMPORT_FAIL_BOT; rollback; }
systemctl restart chan-orders-regr tg-bot-regr; sleep 30
C1=$(systemctl is-active chan-orders-regr); G=$(systemctl is-active tg-bot-regr)
E=$(journalctl -u tg-bot-regr -u chan-orders-regr --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "chan=$C1 tg=$G errors=$E"
if [ "$C1" != active ] || [ "$G" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW7_DONE $TS backup=$B
