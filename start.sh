#!/bin/bash
cd /storage/emulated/0/Documents/weather

echo "=== Weather monitor startup ==="

if [ -f $TMPDIR/check_runs.pid ]; then
  OLD_PID=$(cat $TMPDIR/check_runs.pid)
  kill "$OLD_PID" 2>/dev/null && echo "Killed old process $OLD_PID"
  rm $TMPDIR/check_runs.pid
fi

pkill -f "http.server 8080" 2>/dev/null
nohup python3 -m http.server 8080 > $TMPDIR/http.log 2>&1 &
echo "HTTP server started on :8080 (PID $!)"

mkdir -p logs
nohup bash -c '
  cd /storage/emulated/0/Documents/weather
  while true; do
    echo "[$(date +%H:%M:%S)] check_model_runs.py..."
    python3 scripts/check_model_runs.py
    sleep 900
  done
' >> logs/model_runs.log 2>&1 &

MONITOR_PID=$!
echo $MONITOR_PID > $TMPDIR/check_runs.pid
echo "Monitor started (PID $MONITOR_PID)"

echo ""
echo "=== Запущено ==="
echo "  HTTP:    http://localhost:8080"
echo "  Лог:     tail -f logs/model_runs.log"
echo "  PID:     $MONITOR_PID"
