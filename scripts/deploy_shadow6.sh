#!/bin/bash
# Тени v6 (20.11): входы выше 5m остановлены. Модуль допускает тени только на таймфреймах из shadow_cfg.json "tfs" (по умолчанию 5m), открытые и ждущие входа тени выше 5m удалены вместе с двойниками B и сообщениями в канале, закрытые оставлены. Сканер tg-shadow-scan выключен.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow6.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY=/opt/tg-notify/venv/bin/python; N=/tmp/shadownew6; B=/opt/trading-bot/bak_shadow6_$(date +%Y%m%d_%H%M%S)
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $B
git show origin/main:bot/positions/tg_shadow.py > $N/tg_shadow.py || { echo SHOW_FAIL_MODULE; exit 1; }
git show origin/main:scripts/shadow_drop_tf.py > $N/shadow_drop_tf.py || { echo SHOW_FAIL_DROP; exit 1; }
$VPY -m py_compile $N/tg_shadow.py $N/shadow_drop_tf.py || { echo COMPILE_FAIL; exit 1; }
systemctl disable --now tg-shadow-scan 2>/dev/null; echo "scan=$(systemctl is-active tg-shadow-scan)"
cp $TN/tg_shadow.py $B/; cp $PR/shadow.json $B/shadow.json
echo '{"scan": false, "tfs": ["5m"]}' > $PR/shadow_cfg.json; : > $PR/shadow_in.jsonl; echo 0 > $PR/shadow_in.off
systemctl stop tg-bot-regr
set -a; . /opt/trading-bot/tg.env; set +a
POS_DIR=$PR $VPY $N/shadow_drop_tf.py 5m 2>&1 | LC_ALL=C tr -cd '\11\12\40-\176'
install -o tbot -g tbot -m 644 $N/tg_shadow.py $TN/tg_shadow.py
chown tbot:tbot $PR/shadow.json $PR/shadow_cfg.json 2>/dev/null
systemctl start tg-bot-regr; sleep 25
G=$(systemctl is-active tg-bot-regr); E=$(journalctl -u tg-bot-regr --since "-30sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "tg=$G errors=$E"
$VPY -c "
import json
d=json.load(open('$PR/shadow.json'))
from collections import Counter
c=Counter((i.get('tf'),i.get('status')) for i in d['items'] if not i.get('legacy'))
print(sorted(c.items()))
"
if [ "$G" != active ] || [ "$E" != 0 ]; then echo BAD; cp $B/tg_shadow.py $TN/; systemctl restart tg-bot-regr; exit 1; fi
echo SHADOW6_DONE backup=$B
