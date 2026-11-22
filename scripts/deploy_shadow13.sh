#!/bin/bash
# Тени v13 (22.11): (а) условие входа: свеча самого сигнального таймфрейма (15m, 1h, 4h, 1d; 5m не трогаем) тоже по ходу сделки, по правилу времени 1/6 (patch_gate_sig.py); (б) причина пропуска в журнале chan_missed.json (поля why, why_st, patch_miss_why.py); (в) включён сканер таймфреймов выше 5m (shadow_cfg.json scan true, tfs 5m,15m,1h,4h,1d; служба tg-shadow-scan). Затрагивает chan_orders.py (действует и на реальные ордера слежения 5m только через неизменённую ветку 5m). Перезапуск chan-orders-regr и tg-bot-regr. Откат при ошибке (в том числе выключение сканера).
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow13.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; PR=/opt/trading-bot/positions_regr; VPY2=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow13_$TS; N=/tmp/shadownew13
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
grep -q "def _gate_chain" $PC/chan_orders.py || { echo NO_MULTI_PATCH; exit 1; }
rm -rf $N; mkdir -p $N/pos $B
for f in patch_gate_sig.py patch_miss_why.py test_gate_multi.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
cp $PC/chan_orders.py $B/; cp $PR/shadow_cfg.json $B/shadow_cfg.json; cp $PR/chan_missed.json $B/chan_missed.json 2>/dev/null
cp $PC/*.py $N/pos/
$VPY2 $N/patch_gate_sig.py $N/pos/chan_orders.py || { echo PATCH_SIG_FAIL; exit 1; }
$VPY2 $N/patch_miss_why.py $N/pos/chan_orders.py || { echo PATCH_WHY_FAIL; exit 1; }
$VPY2 -m py_compile $N/pos/chan_orders.py || { echo COMPILE_FAIL; exit 1; }
T=$(cd $N/pos && POS_DIR=$PR CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY2 $N/test_gate_multi.py 2>&1 | tail -5)
echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "^gate wait go wait go wait go wait go" || { echo GATE_TEST_FAIL; exit 1; }
echo "$T" | grep -q "^run wait go wait wait wait wait wait go" || { echo RUN_TEST_FAIL; exit 1; }
echo "$T" | grep -q "^cap \[600000, 600000, 1500000, 5100000, 29100000\]" || { echo CAP_TEST_FAIL; exit 1; }
rm -rf /tmp/mw13; mkdir -p /tmp/mw13; cp $PR/chan_missed.json /tmp/mw13/ 2>/dev/null; cp $PR/chan_events.json /tmp/mw13/ 2>/dev/null
W=$(cd $N/pos && POS_DIR=/tmp/mw13 CHAN_SRC=regr CHAN_EDGE=1 TG_GATE=1 $VPY2 -c "
import chan_orders as C, json
C.miss_update(10**13, limit=0)
m = json.load(open('/tmp/mw13/chan_missed.json')); print('why_backfill', sum(1 for x in m if 'why' in x), 'of', len(m))" 2>&1 | tail -2)
echo "$W" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$W" | grep -q "^why_backfill" || { echo WHY_TEST_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/pos/chan_orders.py $PC/chan_orders.py
rollback() { echo ROLLBACK; cp $B/chan_orders.py $PC/; cp $B/shadow_cfg.json $PR/shadow_cfg.json; systemctl disable --now tg-shadow-scan >/dev/null 2>&1; systemctl restart chan-orders-regr tg-bot-regr; sleep 10; echo ROLLED chan=$(systemctl is-active chan-orders-regr) tg=$(systemctl is-active tg-bot-regr) scan=$(systemctl is-active tg-shadow-scan); exit 1; }
systemctl restart chan-orders-regr tg-bot-regr; sleep 25
C1=$(systemctl is-active chan-orders-regr); G=$(systemctl is-active tg-bot-regr)
[ "$C1" = active ] && [ "$G" = active ] || { echo "services chan=$C1 tg=$G"; rollback; }
$VPY2 - <<PY
import json
p = "$PR/shadow_cfg.json"; c = json.load(open(p)); c["scan"] = True; c["tfs"] = ["5m", "15m", "1h", "4h", "1d"]
json.dump(c, open(p, "w"), ensure_ascii=False); print("cfg", c)
PY
chown tbot:tbot $PR/shadow_cfg.json 2>/dev/null
systemctl enable --now tg-shadow-scan; sleep 60
S=$(systemctl is-active tg-shadow-scan); E=$(journalctl -u tg-bot-regr -u chan-orders-regr -u tg-shadow-scan --since "-85sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "chan=$C1 tg=$G scan=$S errors=$E"
if [ "$S" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW13_DONE $TS backup=$B
