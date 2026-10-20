#!/bin/bash
set -u
REPO=/opt/weather-pipeline/repo; DST=/opt/trading-bot/classic
cd $REPO
git log -1 --format='repo head: %h %s' | cut -c1-90
B=$DST/backup_ch_$(date +%Y%m%d_%H%M%S); mkdir -p $B
declare -A C=( [classic_strategy.py]=aa24f213 [classic_hand.py]=f968f70f [classic_trendline.py]=259ad79a [classic_panel.py]=d88c4b9b [classic_pos_html.py]=aeaab422 )
OK=1
for f in "${!C[@]}"; do
  P=$(git rev-parse ${C[$f]}^ 2>/dev/null)
  if [ -f $DST/$f ] && [ -n "$P" ] && ! git show $P:bot/classic/$f 2>/dev/null | cmp -s - $DST/$f; then echo "DIVERGED on VPS: $f (not touched)"; OK=0; fi
done
if [ $OK = 1 ]; then
  for f in "${!C[@]}"; do cp -a $DST/$f $B/ ; cp $REPO/bot/classic/$f $DST/$f; done
  /opt/trading-bot/venv/bin/python -m py_compile $DST/classic_strategy.py $DST/classic_panel.py $DST/classic_hand.py $DST/classic_trendline.py $DST/classic_pos_html.py && echo compiled_ok
  systemctl restart classicbot; sleep 6
  echo "service: $(systemctl is-active classicbot)"
  echo "http: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:18093/)"
  if [ "$(systemctl is-active classicbot)" != active ]; then echo ROLLBACK; cp -a $B/*.py $DST/; systemctl restart classicbot; sleep 4; echo "service after rollback: $(systemctl is-active classicbot)"; fi
else echo "deploy skipped"; fi
echo backup: $B
