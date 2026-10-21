#!/bin/bash
# usage: deploy_classic_files.sh file:deployed_sha ...  (deployed_sha — коммит, версию которого выкладывали раньше; для проверки расхождений на VPS)
REPO=/opt/weather-pipeline/repo; DST=/opt/trading-bot/classic; cd $REPO
B=$DST/backup_$(date +%Y%m%d_%H%M%S); mkdir -p $B; OK=1; FILES=""
for a in "$@"; do f=${a%%:*}; s=${a##*:}
  if [ -f $DST/$f ] && ! git show $s:bot/classic/$f 2>/dev/null | cmp -s - $DST/$f; then echo "DIVERGED on VPS: $f (not touched)"; OK=0; fi
  FILES="$FILES $f"
done
if [ $OK = 1 ]; then
  for f in $FILES; do cp -a $DST/$f $B/; cp $REPO/bot/classic/$f $DST/$f; done
  PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
  (cd $DST && $PY -m py_compile $FILES) && echo compiled_ok
  systemctl restart classicbot; sleep 6
  echo "service: $(systemctl is-active classicbot)"; echo "http: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:18093/)"
  if [ "$(systemctl is-active classicbot)" != active ]; then echo ROLLBACK; for f in $FILES; do cp -a $B/$f $DST/$f; done; systemctl restart classicbot; sleep 4; echo "service after rollback: $(systemctl is-active classicbot)"; fi
else echo "deploy skipped"; fi
echo backup: $B
