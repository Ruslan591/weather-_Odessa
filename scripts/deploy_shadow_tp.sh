#!/bin/bash
LV=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/bak_shtp_$TS; N=/tmp/shtp; mkdir -p $B $N; cp $LV/live_web.py $B/; cp $LV/live_web.py $N/live_web.py
curl -s $RAW/patch_shadow_tp.py -o $N/patch.py
OUT=$($VPY $N/patch.py $N/live_web.py 2>&1); echo "patch: $OUT"
case "$OUT" in ALREADY*) exit 0;; PATCHED*) ;; *) echo PATCH_FAIL; exit 1;; esac
cp $N/live_web.py $LV/live_web.py; chown tbot:tbot $LV/live_web.py
systemctl restart live-web; sleep 10
H=$(curl -s -m 5 http://127.0.0.1:18110/live/health); echo active=$(systemctl is-active live-web) health=$H
if [ "$(systemctl is-active live-web)" != "active" ] || [ "$H" != "ok" ]; then echo ROLLBACK; cp $B/live_web.py $LV/live_web.py; chown tbot:tbot $LV/live_web.py; systemctl restart live-web; sleep 8; echo rolled=$(systemctl is-active live-web); exit 1; fi
journalctl -u live-web --since "-1min" --no-pager | grep -i -E "shadow:|error|traceback" | tail -3
$VPY - <<'PY'
import sys, json
sys.path.insert(0, "/opt/trading-bot/positions"); sys.path.insert(0, "/opt/trading-bot/live")
import importlib.util, os
os.environ["POS_DIR"] = "/opt/trading-bot/positions_regr"
src = open("/opt/trading-bot/live/live_web.py").read()
ns = {"__name__": "lw_test"}
import re
exec(compile(src.split("def derive(snap)")[0], "lw", "exec"), ns)
sh = ns["build_shadow"]()
for r in sh:
    if r.get("sn") == 198 or r.get("sym") == "ACE":
        print("ACE", r.get("var"), r.get("status"), "entry", r.get("entry"), "stop", r.get("stop"), "tp", r.get("tp"), "tp_plan", r.get("tp_plan")); break
print("with tp_plan", sum(1 for r in sh if r.get("tp_plan")), "of", len(sh))
PY
echo DEPLOYED $TS
