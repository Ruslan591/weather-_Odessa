#!/bin/bash
# Версия 10: подтверждение отмены слежения своим окном страницы вместо системного confirm. Только index.html. Идемпотентно, откат при ошибке.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_web_ctl6.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; L=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_web6_$TS; N=/tmp/webnew6
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:scripts/patch_web_ctl6.py > $N/patch_web_ctl6.py || { echo SHOW_FAIL; exit 1; }
cp $L/index.html $B/; cp $L/index.html $N/
$VPY $N/patch_web_ctl6.py $N/index.html || { echo PATCH_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/index.html $L/index.html
systemctl restart live-web; sleep 5
W=$(systemctl is-active live-web); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
echo "live=$W health=$H"
if [ "$W" != active ] || [ "$H" != 200 ]; then cp $B/index.html $L/; systemctl restart live-web; echo ROLLBACK; exit 1; fi
echo WEB_CTL6_DONE $TS backup=$B
