#!/bin/bash
# deploy_tg_files.sh name=md5 ... (name: tg_express | tg_bot | tg_regime): файлы бота -> /opt/tg-notify, перезапуск tg-bot-regr. md5 на VPS должен совпасть (DIVERGED), бэкап, компиляция, импорт, автооткат.
set -u
R=/opt/weather-pipeline/repo; N=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; TS=$(date +%Y%m%d_%H%M%S); VPY=/opt/trading-bot/venv/bin/python
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done; [ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
mkdir -p /tmp/tgf $N/bak
for a in "$@"; do f=${a%%=*}; m=${a##*=}
  git show origin/main:bot/positions/$f.py > /tmp/tgf/$f.py || { echo SHOW_FAIL $f; exit 1; }
  [ "$(md5sum < $N/$f.py | cut -d' ' -f1)" = "$m" ] || { echo "DIVERGED $f"; exit 1; }
  $VPY -m py_compile /tmp/tgf/$f.py || { echo COMPILE_FAIL $f; exit 1; }
done
for a in "$@"; do f=${a%%=*}; cp $N/$f.py $N/bak/$f.py.$TS; done
rollback() { echo ROLLBACK; for a in "$@"; do f=${a%%=*}; cp $N/bak/$f.py.$TS $N/$f.py; done; systemctl restart tg-bot-regr; exit 1; }
for a in "$@"; do f=${a%%=*}; install -m 644 /tmp/tgf/$f.py $N/$f.py; done
(cd $N && POS_DIR=$PR $VPY -c "import tg_bot, tg_express as X, tg_regime as G; print('import ok', X._bcc_cfg()['mode'], G.get() is not None)") || { echo IMPORT_FAIL; rollback "$@"; }
systemctl restart tg-bot-regr; sleep 30
A1=$(systemctl is-active tg-bot-regr); echo "tg-bot-regr=$A1"
journalctl -u tg-bot-regr -n 3 --no-pager | LC_ALL=C tr -cd '\11\12\40-\176' | cut -c1-200
[ "$A1" = active ] || rollback "$@"
echo DEPLOY_OK $TS
