#!/bin/bash
# Панель v12 (21.11): график тени показывает все события сопровождения (БУ, БУ2, частичная цель, трейлинг, S/R, swing, лесенка, цель дальше) и ступенчатые линии стопа/цели; таймфрейм 1с на всех графиках; в разборе сделки строка про tp_ext. Затрагивает live_web.py, index.html (панель), tg_shadow.py. Перезапуск live-web и tg-bot-regr. Откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow12.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; TN=/opt/tg-notify; L=/opt/trading-bot/live; VPY=/opt/tg-notify/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shadow12_$TS; N=/tmp/shadownew12
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_chart.py > $N/patch_chart.py || { echo SHOW_FAIL; exit 1; }
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_SH; exit 1; }
cp $L/live_web.py $L/index.html $B/; cp $TN/tg_shadow.py $B/
cp $L/live_web.py $L/index.html $N/
$VPY $N/patch_chart.py $N/live_web.py $N/index.html || { echo PATCH_FAIL; exit 1; }
for f in live_web.py tg_shadow.py; do $VPY -m py_compile $N/$f || { echo COMPILE_FAIL $f; exit 1; }; done
if command -v node >/dev/null 2>&1; then $VPY - <<PY || { echo JS_FAIL; exit 1; }
import re, subprocess
h = open("$N/index.html", encoding="utf-8").read(); js = "\n;\n".join(re.findall(r"<script[^>]*>(.*?)</script>", h, re.S)); open("$N/ci.js", "w", encoding="utf-8").write(js)
r = subprocess.run(["node", "--check", "$N/ci.js"], capture_output=True, text=True); print("node check", r.returncode, r.stderr[:300]); raise SystemExit(r.returncode)
PY
else echo "node not on VPS, JS check skipped (done before push)"; fi
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html; install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
rollback() { echo ROLLBACK; cp $B/live_web.py $B/index.html $L/; cp $B/tg_shadow.py $TN/; systemctl restart live-web tg-bot-regr; sleep 10; echo ROLLED live=$(systemctl is-active live-web) tg=$(systemctl is-active tg-bot-regr); exit 1; }
systemctl restart live-web tg-bot-regr; sleep 30
G=$(systemctl is-active tg-bot-regr); W=$(systemctl is-active live-web); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
S=$(curl -s http://127.0.0.1:18110/ | grep -c "'1s':1000")
E=$(journalctl -u tg-bot-regr -u live-web --since "-35sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "tg=$G live=$W health=$H page_has_1s=$S errors=$E"
if [ "$G" != active ] || [ "$W" != active ] || [ "$E" != 0 ]; then rollback; fi
echo SHADOW12_DONE $TS backup=$B
