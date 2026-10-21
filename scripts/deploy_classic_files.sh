#!/bin/bash
# usage: deploy_classic_files.sh file:commit ...
# Файлы берутся прямо из объектов git (git show commit:path), рабочая папка клона не используется — клон на VPS делит ссылки с мостом и pull бывает не завершён.
# Проверка расхождений: файл на VPS должен совпадать с версией в родительском коммите (то есть с тем, что выкладывали раньше).
REPO=/opt/weather-pipeline/repo; DST=/opt/trading-bot/classic; cd $REPO
B=$DST/backup_$(date +%Y%m%d_%H%M%S); mkdir -p $B; OK=1; FILES=""
for a in "$@"; do f=${a%%:*}; c=${a##*:}
  git cat-file -e $c 2>/dev/null || { echo "MISSING commit $c (git fetch не дотянул)"; OK=0; continue; }
  if [ -f $DST/$f ] && ! git show $c^:bot/classic/$f 2>/dev/null | cmp -s - $DST/$f; then echo "DIVERGED on VPS: $f (not touched)"; OK=0; fi
  FILES="$FILES $f"
done
if [ $OK = 1 ]; then
  for a in "$@"; do f=${a%%:*}; c=${a##*:}
    git show $c:bot/classic/$f > $B/$f.new 2>/dev/null; [ -s $B/$f.new ] || { echo "empty $f"; OK=0; }
  done
fi
if [ $OK = 1 ]; then
  for f in $FILES; do cp -a $DST/$f $B/; cp $B/$f.new $DST/$f; done
  PY=/opt/trading-bot/venv/bin/python; [ -x $PY ] || PY=python3
  (cd $DST && $PY -m py_compile $FILES) && echo compiled_ok
  systemctl restart classicbot; sleep 6
  echo "service: $(systemctl is-active classicbot)"; echo "http: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:18093/)"
  if [ "$(systemctl is-active classicbot)" != active ]; then echo ROLLBACK; for f in $FILES; do cp -a $B/$f $DST/$f; done; systemctl restart classicbot; sleep 4; echo "service after rollback: $(systemctl is-active classicbot)"; fi
else echo "deploy skipped"; fi
echo backup: $B
