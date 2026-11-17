#!/bin/bash
# deploy_live_rg.sh: страница онлайн с каналами регрессии 1м/1ч/4ч (live_web.py + index.html). Сверка md5 файлов на VPS с версией до правки (DIVERGED), бэкап, компиляция, перезапуск live-web, проверка health, автооткат.
# Запуск через мост: cd /opt/weather-pipeline/repo && git show origin/main:scripts/deploy_live_rg.sh | bash -s <md5 live_web.py> <md5 index.html>
set -u
R=/opt/weather-pipeline/repo; L=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_live_rg_$TS; N=/tmp/livergnew
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
[ "$(md5sum < $L/live_web.py | cut -d' ' -f1)" = "$1" ] || { echo DIVERGED live_web.py; exit 1; }
[ "$(md5sum < $L/index.html | cut -d' ' -f1)" = "$2" ] || { echo DIVERGED index.html; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:bot/live/live_web.py > $N/live_web.py || { echo SHOW_FAIL; exit 1; }
git show origin/main:bot/live/index.html > $N/index.html || { echo SHOW_FAIL; exit 1; }
$VPY -m py_compile $N/live_web.py || { echo COMPILE_FAIL; exit 1; }
cp $L/live_web.py $L/index.html $B/
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py; install -o tbot -g tbot -m 644 $N/index.html $L/index.html
systemctl restart live-web; sleep 6
W=$(systemctl is-active live-web); H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)
T=$(cd $L && $VPY -c "
import asyncio, time, aiohttp, live_web as W
async def m():
    async with aiohttp.ClientSession() as s:
        r = await W.reg_all(s, 'ETHUSDT'); print({k: [v['win'], v['r'], v['dir']] for k, v in r.items()})
asyncio.run(m())" 2>&1 | tail -1)
echo "live=$W health=$H reg=$T"
if [ "$W" != active ] || [ "$H" != 200 ] || ! echo "$T" | grep -q "1m"; then
  cp $B/live_web.py $B/index.html $L/; systemctl restart live-web; sleep 4; echo ROLLBACK live=$(systemctl is-active live-web); exit 1
fi
echo LIVE_RG_DONE $TS backup=$B
