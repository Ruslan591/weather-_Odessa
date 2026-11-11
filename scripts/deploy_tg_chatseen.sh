#!/bin/bash
# deploy_tg_chatseen.sh <md5_old>: deploy tg_bot.py (channel_post/my_chat_member -> tg_chats_seen.json) to /opt/tg-notify, restart tg-bot-regr, auto rollback.
set -u
OLD=${1:-}; R=/opt/weather-pipeline/repo; N=/opt/tg-notify; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
ok=0; for i in 1 2 3 4 5; do git fetch -q origin && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
git show origin/main:bot/positions/tg_bot.py > /tmp/tg_bot.py.new || { echo SHOW_FAIL; exit 1; }
if [ -n "$OLD" ]; then CUR=$(md5sum $N/tg_bot.py | cut -d' ' -f1); [ "$CUR" = "$OLD" ] || { echo DIVERGED $CUR; exit 1; }; fi
$VPY -m py_compile /tmp/tg_bot.py.new || { echo COMPILE_FAIL; exit 1; }
mkdir -p $N/bak; cp $N/tg_bot.py $N/bak/tg_bot.py.$TS
install -m 644 /tmp/tg_bot.py.new $N/tg_bot.py
systemctl restart tg-bot-regr; sleep 15
A=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A"
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
if [ "$A" != active ]; then echo ROLLBACK; cp $N/bak/tg_bot.py.$TS $N/tg_bot.py; systemctl restart tg-bot-regr; exit 1; fi
echo DEPLOY_OK $TS
