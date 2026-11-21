#!/bin/bash
# Тени v11 (21.11): цель дальше при запасе хода (tp_ext.py, заметки #38 и №9). Включается для новых теней (флаг ext), копия без правил (pb) его не получает. Параметры tp_ext_cfg.json. Затрагивает pos.py (хук), tp_ext.py (новый), tg_shadow.py. Перезапуск tg-bot-regr. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow11.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; VPY2=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow11_$TS; N=/tmp/shadownew11
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N/pos $B
for f in patch_ext.py test_ext.py; do git show origin/main:scripts/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
git show origin/main:bot/positions/tp_ext.py > $N/pos/tp_ext.py || { echo SHOW_FAIL_EXT; exit 1; }
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_SH; exit 1; }
cp $PC/pos.py $B/; cp $TN/tg_shadow.py $B/; cp $PC/pos.py $N/pos/pos.py
$VPY2 $N/patch_ext.py $N/pos/pos.py || { echo PATCH_FAIL; exit 1; }
for f in $N/pos/pos.py $N/pos/tp_ext.py $N/tg_shadow.py; do $VPY2 -m py_compile $f || { echo COMPILE_FAIL $f; exit 1; }; done
T=$(cd $N/pos && $VPY2 $N/test_ext.py $N/pos 2>&1 | tail -2)
echo "$T" | LC_ALL=C tr -cd '\11\12\40-\176'
echo "$T" | grep -q "^ext (102.5, 100.8, 1) None (102.5, 100.8, 1) (97.5, 99.2, 1) None None" || { echo EXT_TEST_FAIL; exit 1; }
grep -n 'swing_stop.apply' $N/pos/pos.py | head -2; grep -n 'import tp_ext; _x' $N/pos/pos.py | head -2
install -o tbot -g tbot -m 644 $N/pos/tp_ext.py $PC/tp_ext.py; install -o tbot -g tbot -m 644 $N/pos/pos.py $PC/pos.py; install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
rollback() { echo ROLLBACK; cp $B/pos.py $PC/; rm -f $PC/tp_ext.py; cp $B/tg_shadow.py $TN/; systemctl restart tg-bot-regr; sleep 10; echo ROLLED tg=$(systemctl is-active tg-bot-regr); exit 1; }
(cd $TN && POS_DIR=$PR $VPY -c "import sys; sys.path.insert(0, '$PC'); import tg_bot; import tp_ext; print('import ok', tp_ext.load()['trig'])") || { echo IMPORT_FAIL; rollback; }
systemctl restart tg-bot-regr; sleep 30
G=$(systemctl is-active tg-bot-regr); E=$(journalctl -u tg-bot-regr --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback\|tp_ext err")
echo "tg=$G errors=$E"
if [ "$G" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW11_DONE $TS backup=$B
