#!/bin/bash
LV=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shnb_$TS; N=/tmp/shnb; rm -rf $N; mkdir -p $B $N; cp $LV/live_web.py $LV/index.html $B/; cp $LV/live_web.py $LV/index.html $N/
curl -s $RAW/patch_shadow_nb.py -o $N/patch.py
OUT=$($VPY $N/patch.py $N/live_web.py $N/index.html 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
cp $N/live_web.py $LV/live_web.py; cp $N/index.html $LV/index.html; chown tbot:tbot $LV/live_web.py $LV/index.html
systemctl restart live-web; sleep 10
H=$(curl -s -m 5 http://127.0.0.1:18110/live/health); echo active=$(systemctl is-active live-web) health=$H
if [ "$(systemctl is-active live-web)" != "active" ] || [ "$H" != "ok" ]; then echo ROLLBACK; cp $B/live_web.py $B/index.html $LV/; chown tbot:tbot $LV/live_web.py $LV/index.html; systemctl restart live-web; sleep 8; echo rolled=$(systemctl is-active live-web); exit 1; fi
journalctl -u live-web --since "-1min" --no-pager | grep -i -E "shadow:|error|traceback" | tail -3
which node >/dev/null 2>&1 && echo node_present
$VPY - <<'PY'
import os
os.environ["POS_DIR"] = "/opt/trading-bot/positions_regr"
import sys; sys.path.insert(0, "/opt/trading-bot/positions")
src = open("/opt/trading-bot/live/live_web.py").read().split("def derive(snap)")[0]
ns = {"__name__": "t", "__file__": "/opt/trading-bot/live/live_web.py"}; exec(compile(src, "lw", "exec"), ns)
sh = ns["build_shadow"](); import collections
c = collections.Counter((r.get("tf"), bool(r.get("nb"))) for r in sh); print("tf/nb", dict(c))
PY
echo DEPLOYED $TS
