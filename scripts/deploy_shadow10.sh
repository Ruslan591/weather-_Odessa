#!/bin/bash
# Тени v10 (21.11): swing_stop берёт ближайший экстремум (near=1: Hi/Lo самой свечи пика) вместо окна из 3 свечей перед пиком (разбор #67, заметка №8). На истории 499 сделок: +8.7 R вместо -13 R относительно варианта без правила. Зазор 0.2 R и ход к пику 0.3 R прежние. Перезапуск tg-bot-regr. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow10.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; PC=/opt/trading-bot/positions; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow10_$TS; N=/tmp/shadownew10
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:bot/positions/swing_stop.py > $N/swing_stop.py || { echo SHOW_FAIL; exit 1; }
cp $PC/swing_stop.py $B/
$VPY -m py_compile $N/swing_stop.py || { echo COMPILE_FAIL; exit 1; }
T=$(cd $N && POS_DIR=/tmp/none $VPY -c "import swing_stop as w; c = w.load(); print('cfg', c['near'], c['min_gap_r'], c['min_mfe'])" 2>&1 | tail -1)
echo "$T"; echo "$T" | grep -q "^cfg 1 0.2 0.3" || { echo CFG_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/swing_stop.py $PC/swing_stop.py
rollback() { echo ROLLBACK; cp $B/swing_stop.py $PC/; systemctl restart tg-bot-regr; sleep 10; echo ROLLED tg=$(systemctl is-active tg-bot-regr); exit 1; }
systemctl restart tg-bot-regr; sleep 30
G=$(systemctl is-active tg-bot-regr); E=$(journalctl -u tg-bot-regr --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "tg=$G errors=$E"
if [ "$G" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW10_DONE $TS backup=$B
