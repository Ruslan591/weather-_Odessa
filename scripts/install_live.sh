#!/bin/bash
# Установка живой страницы бота (live-web). Запуск: cd /opt/weather-pipeline/repo && git show origin/main:scripts/install_live.sh | bash -s
# Секреты в вывод не печатаются (вывод уходит в репозиторий через мост): ссылка с токеном отправляется только в Telegram владельцу.
set -u
R=/opt/weather-pipeline/repo; L=/opt/trading-bot/live; VPY=/opt/trading-bot/venv/bin/python; HOST=130-61-25-212.nip.io; TS=$(date +%Y%m%d_%H%M%S); N=/tmp/livenew
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
rm -rf $N; mkdir -p $N $L
for f in live_web.py index.html; do git show origin/main:bot/live/$f > $N/$f || { echo SHOW_FAIL $f; exit 1; }; done
$VPY -m py_compile $N/live_web.py || { echo COMPILE_FAIL; exit 1; }
[ -s $L/token.txt ] || { $VPY -c "import secrets;print(secrets.token_urlsafe(24))" > $L/token.txt; }
chmod 600 $L/token.txt; chown tbot:tbot $L/token.txt
install -o tbot -g tbot -m 644 $N/live_web.py $L/live_web.py
install -o tbot -g tbot -m 644 $N/index.html $L/index.html
cat > /etc/systemd/system/live-web.service <<EOF
[Unit]
Description=Live page of the bot (read-only WebSocket)
After=network-online.target acct-api-regr.service

[Service]
User=tbot
Environment=POS_DIR=/opt/trading-bot/positions_regr
Environment=LIVE_PORT=18110
Environment=ACCT_PORT=18102
ExecStart=$VPY $L/live_web.py
Restart=always
RestartSec=3
Nice=10
CPUQuota=25%
MemoryMax=200M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl enable live-web >/dev/null 2>&1; systemctl restart live-web; sleep 4
echo "svc=$(systemctl is-active live-web) local=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18110/live/health)"
CF=/etc/caddy/Caddyfile
BEFORE=$(curl -sk -o /dev/null -w '%{http_code}' --resolve $HOST:443:127.0.0.1 https://$HOST/)
if ! grep -q 18110 $CF; then
  cp $CF $CF.bak_$TS
  cat > $CF <<EOF
$HOST {
    handle /live* {
        reverse_proxy 127.0.0.1:18110
    }
    handle {
        reverse_proxy 127.0.0.1:8080
    }
}
EOF
  if caddy validate --config $CF >/dev/null 2>&1 && systemctl reload caddy; then sleep 3; else cp $CF.bak_$TS $CF; systemctl reload caddy; echo CADDY_ROLLBACK_VALIDATE; fi
fi
AFTER=$(curl -sk -o /dev/null -w '%{http_code}' --resolve $HOST:443:127.0.0.1 https://$HOST/)
LIVE=$(curl -sk -o /dev/null -w '%{http_code}' --resolve $HOST:443:127.0.0.1 https://$HOST/live/)
echo "site_before=$BEFORE site_after=$AFTER live_via_caddy=$LIVE"
if [ "$AFTER" != "$BEFORE" ] && [ -f $CF.bak_$TS ]; then cp $CF.bak_$TS $CF; systemctl reload caddy; echo CADDY_ROLLBACK_SITE; fi
$VPY - <<'EOF'
import json, urllib.request
env = {}
for l in open("/opt/trading-bot/tg.env", encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
tok = open("/opt/trading-bot/live/token.txt").read().strip(); host = "130-61-25-212.nip.io"
def call(m, d):
    r = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (env["TG_TOKEN"], m), data=json.dumps(d).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=20)).get("ok")
try: print("MENU ok=%s" % call("setChatMenuButton", {"chat_id": int(env["TG_USER_ID"]), "menu_button": {"type": "web_app", "text": "Онлайн", "web_app": {"url": "https://%s/live/" % host}}}))
except Exception as e: print("MENU fail", type(e).__name__)
try: print("MSG ok=%s" % call("sendMessage", {"chat_id": int(env["TG_USER_ID"]), "text": "Живая страница бота установлена.\nВ Telegram: кнопка «Онлайн» слева от поля ввода.\nВ браузере (резервная ссылка, никому не показывай):\nhttps://%s/live/#t=%s" % (host, tok), "disable_web_page_preview": True}))
except Exception as e: print("MSG fail", type(e).__name__)
EOF
journalctl -u live-web -n 5 --no-pager 2>/dev/null | cut -c1-160
echo INSTALL_DONE $TS
