#!/bin/bash
# Тени v5: сканер сигналов для таймфреймов, на которых бот не следит (tg_shadow_scan.py, сервис tg-shadow-scan). Тени по 5m, 15m, 1h, 4h, 1d одновременно. Бот и торговые сервисы не перезапускаются.
# Сначала пробный проход без записи сигналов (--once --dry), сервис включается, только если проход чистый. Откат: systemctl disable --now tg-shadow-scan.
# Запуск (через мост): cd /opt/weather-pipeline/repo && git update-ref -d refs/remotes/origin/main; git fetch -q origin main:refs/remotes/origin/main && git show origin/main:scripts/deploy_shadow5.sh | bash -s
set -u
R=/opt/weather-pipeline/repo; TN=/opt/tg-notify; PR=/opt/trading-bot/positions_regr; VPY2=/opt/trading-bot/venv/bin/python; N=/tmp/shadownew5
cd $R || exit 1
git update-ref -d refs/remotes/origin/main 2>/dev/null
ok=0; for i in 1 2 3 4 5; do git fetch -q origin main:refs/remotes/origin/main && ok=1 && break; sleep 6; done
[ $ok = 1 ] || { echo FETCH_FAIL; exit 1; }
grep -q "def consume_queue" $TN/tg_shadow.py || { echo NO_V4_MODULE; exit 1; }
rm -rf $N; mkdir -p $N
git show origin/main:bot/positions/tg_shadow_scan.py > $N/tg_shadow_scan.py || { echo SHOW_FAIL; exit 1; }
$VPY2 -m py_compile $N/tg_shadow_scan.py || { echo COMPILE_FAIL; exit 1; }
install -o tbot -g tbot -m 644 $N/tg_shadow_scan.py $TN/tg_shadow_scan.py
echo "--- dry run 15m"
cd $TN && timeout 280 sudo -u tbot env POS_DIR=$PR PYTHONUNBUFFERED=1 $VPY2 $TN/tg_shadow_scan.py --once --dry --tf 15m > $N/dry.log 2>&1; RC=$?
grep -c Traceback $N/dry.log | sed 's/^/tracebacks: /'; grep "RESULT\|error\|Error" $N/dry.log | head -8 | LC_ALL=C tr -cd '\11\12\40-\176'
echo "rc=$RC"
[ $RC = 0 ] && grep -q "^RESULT" $N/dry.log && ! grep -q Traceback $N/dry.log || { echo DRY_FAIL; tail -n 8 $N/dry.log | LC_ALL=C tr -cd '\11\12\40-\176'; exit 1; }
cat > /etc/systemd/system/tg-shadow-scan.service <<UNIT
[Unit]
Description=Shadow signals scanner for timeframes without live watching (Regression account)
After=network-online.target
[Service]
User=tbot
Environment=POS_DIR=$PR
Environment=CHAN_SRC=regr
Environment=CHAN_EDGE=1
Environment=TG_GATE=1
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$TN
ExecStart=$VPY2 $TN/tg_shadow_scan.py
Restart=always
RestartSec=20
Nice=15
CPUQuota=60%
MemoryMax=1200M
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload; systemctl enable --now tg-shadow-scan; sleep 45
A=$(systemctl is-active tg-shadow-scan); E=$(journalctl -u tg-shadow-scan --since "-50sec" --no-pager 2>/dev/null | grep -ci "Traceback")
echo "scan=$A errors=$E"
journalctl -u tg-shadow-scan --since "-50sec" --no-pager 2>/dev/null | tail -n 6 | LC_ALL=C tr -cd '\11\12\40-\176'
if [ "$A" != active ] || [ "$E" != 0 ]; then systemctl disable --now tg-shadow-scan; echo DISABLED; exit 1; fi
echo SHADOW5_DONE
