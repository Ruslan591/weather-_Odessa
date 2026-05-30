#!/bin/bash
cd /storage/emulated/0/Documents/weather

echo "=== Weather monitor startup ==="

if [ -f /tmp/check_runs.pid ]; then
  OLD_PID=$(cat /tmp/check_runs.pid)
  kill "$OLD_PID" 2>/dev/null && echo "Killed old process $OLD_PID"
  rm /tmp/check_runs.pid
fi

pkill -f "http.server 8080" 2>/dev/null
nohup python3 -m http.server 8080 > /tmp/http.log 2>&1 &
echo "HTTP server started on :8080 (PID $!)"

nohup bash -c '
  cd /storage/emulated/0/Documents/weather
  while true; do
    echo "[$(date +%H:%M:%S)] check_model_runs.py..."
    python3 scripts/check_model_runs.py
    sleep 900
  done
' > /tmp/check_runs.log 2>&1 &

MONITOR_PID=$!
echo $MONITOR_PID > /tmp/check_runs.pid
echo "Monitor started (PID $MONITOR_PID)"

echo ""
echo "=== Запущено ==="
echo "  HTTP:    http://localhost:8080"
echo "  Лог:     tail -f /tmp/check_runs.log"
echo "  PID:     $MONITOR_PID"
