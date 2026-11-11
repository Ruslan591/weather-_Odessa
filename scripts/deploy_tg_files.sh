#!/bin/bash
# deploy_tg_files.sh file:md5_old ...   (file: tg_bot.py | tg_notify.py ...) : deploy files from origin/main:bot/positions/ to /opt/tg-notify, restart tg-bot-regr, auto rollback.
set -u
R=/opt/weather-pipeline/repo; N=/opt/tg-notify; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p $N/bak /tmp/tgnew
for a in "$@"; do
  f=${a%%:*}; old=${a#*:}
  git show origin/main:bot/positions/$f > /tmp/tgnew/$f || { echo SHOW_FAIL $f; exit 1; }
  CUR=$(md5sum $N/$f | cut -d' ' -f1); [ "$CUR" = "$old" ] || { echo DIVERGED $f $CUR; exit 1; }
  $VPY -m py_compile /tmp/tgnew/$f || { echo COMPILE_FAIL $f; exit 1; }
done
for a in "$@"; do f=${a%%:*}; cp $N/$f $N/bak/$f.$TS; install -m 644 /tmp/tgnew/$f $N/$f; done
systemctl restart tg-bot-regr; sleep 15
A=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A"
journalctl -u tg-bot-regr -n 5 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A" != active ]; then echo ROLLBACK; for a in "$@"; do f=${a%%:*}; cp $N/bak/$f.$TS $N/$f; done; systemctl restart tg-bot-regr; exit 1; fi
echo DEPLOY_OK $TS
