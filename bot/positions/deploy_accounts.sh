#!/bin/bash
# Выкладка параллельных счетов chan-orders (AFD / Регрессия / Комбо). Запуск от root на VPS: bash deploy_accounts.sh [rollback]
# Берёт файлы из репозитория (raw.githubusercontent.com), делает бэкап chan_orders.py, ставит chan_src.py, acct_api.py, создаёт каталоги счетов
# и systemd-сервисы (chan-orders-X, pos-tracker-X, acct-api-X), существующие сервисы chan-orders/pos-tracker перезапускает.
set -u
P=/opt/trading-bot/positions; RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/bot/positions
TK=$(grep GITHUB_TOKEN= /etc/vps-github-bridge/token 2>/dev/null | cut -d= -f2); [ -z "$TK" ] && TK=$(cat /etc/vps-github-bridge/token 2>/dev/null)
get() { curl -sf "$RAW/$1" -o "$2" || curl -sf -H "Authorization: token $TK" "$RAW/$1" -o "$2"; }
ACCTS="afd:afd:18101 regr:regr:18102 combo:combo:18103"
if [ "${1:-}" = "rollback" ]; then
  for a in $ACCTS; do n=${a%%:*}; for s in chan-orders-$n pos-tracker-$n acct-api-$n; do systemctl disable --now $s 2>/dev/null; rm -f /etc/systemd/system/$s.service; done; done
  B=$(ls -d $P/backup_acct_* 2>/dev/null | tail -1); [ -n "$B" ] && cp $B/chan_orders.py $P/chan_orders.py && echo "restored $B"
  systemctl daemon-reload; systemctl restart chan-orders pos-tracker; echo ROLLBACK_DONE; exit 0
fi
B=$P/backup_acct_$(date +%Y%m%d_%H%M%S); mkdir -p $B; cp $P/chan_orders.py $B/
mkdir -p /tmp/acc_new
for f in chan_orders.py chan_src.py acct_api.py; do get $f /tmp/acc_new/$f || { echo "FETCH_FAIL $f"; exit 1; }; done
for f in chan_orders.py chan_src.py acct_api.py; do /opt/trading-bot/venv/bin/python -m py_compile /tmp/acc_new/$f || { echo "COMPILE_FAIL $f"; exit 1; }; done
cp /tmp/acc_new/chan_orders.py /tmp/acc_new/chan_src.py /tmp/acc_new/acct_api.py $P/; chown tbot:tbot $P/chan_orders.py $P/chan_src.py $P/acct_api.py
for a in $ACCTS; do IFS=: read n src port <<< "$a"
  D=/opt/trading-bot/positions_$n; mkdir -p $D; cp -n $P/chan_cfg.json $D/chan_cfg.json; chown -R tbot:tbot $D
  cat > /etc/systemd/system/chan-orders-$n.service <<UNIT
[Unit]
Description=Claude paper limit orders, channels=$src
After=network.target
[Service]
User=tbot
ExecStart=/opt/trading-bot/venv/bin/python $P/chan_orders.py loop
Environment=POS_DIR=$D
Environment=CHAN_SRC=$src
Environment=CHAN_EDGE=1
Restart=always
Nice=10
[Install]
WantedBy=multi-user.target
UNIT
  cat > /etc/systemd/system/pos-tracker-$n.service <<UNIT
[Unit]
Description=Paper positions tracker ($n)
After=network.target
[Service]
User=tbot
ExecStart=/opt/trading-bot/venv/bin/python $P/pos.py loop
Environment=POS_DIR=$D
Restart=always
Nice=10
[Install]
WantedBy=multi-user.target
UNIT
  cat > /etc/systemd/system/acct-api-$n.service <<UNIT
[Unit]
Description=Account API ($n)
After=network.target
[Service]
User=tbot
ExecStart=/opt/trading-bot/venv/bin/python $P/acct_api.py
Environment=POS_DIR=$D
Environment=CHAN_SRC=$src
Environment=CHAN_EDGE=1
Environment=ACCT_PORT=$port
Restart=always
Nice=10
[Install]
WantedBy=multi-user.target
UNIT
done
systemctl daemon-reload
systemctl restart chan-orders pos-tracker
sleep 3
for a in $ACCTS; do n=${a%%:*}; systemctl enable --now chan-orders-$n pos-tracker-$n acct-api-$n; done
sleep 20
for s in chan-orders pos-tracker; do echo "$s: $(systemctl is-active $s)"; done
for a in $ACCTS; do n=${a%%:*}; port=${a##*:}; echo "$n: chan=$(systemctl is-active chan-orders-$n) trk=$(systemctl is-active pos-tracker-$n) api=$(systemctl is-active acct-api-$n) snap=$(curl -s localhost:$port/api/claude | head -c 120)"; done
tail -3 $P/chan.log 2>/dev/null | cut -c1-200
echo DEPLOY_DONE backup=$B
