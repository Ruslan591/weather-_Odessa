#!/data/data/com.termux/files/usr/bin/bash
# trigger_gh_pipeline.sh — лёгкий триггер full_pipeline.yml через workflow_dispatch.
#
# Новый файл специально под замену расписания телефона. Не запускает пайплайн
# сам — только "нажимает кнопку" запуска в GitHub Actions (полный пайплайн
# теперь выполняется в облаке, см. scripts/gh_pipeline.py и
# .github/workflows/full_pipeline.yml).
#
# Регистрируется вместо check_model_runs.py в job 1001:
#   termux-job-scheduler --job-id 1001 --persisted --period-ms 900000 \
#       --script ~/bin/run_trigger_gh_pipeline.sh
#
# Требует переменную GH_DISPATCH_TOKEN в .env (токен с правами repo+workflow).

set -e
BASE_DIR="/storage/emulated/0/Documents/weather"
ENV_FILE="$BASE_DIR/.env"
LOG_FILE="$BASE_DIR/logs/trigger_gh_pipeline.log"

mkdir -p "$BASE_DIR/logs"

TOKEN=""
if [ -f "$ENV_FILE" ]; then
    TOKEN=$(grep "^GH_DISPATCH_TOKEN=" "$ENV_FILE" | cut -d '=' -f2-)
fi

if [ -z "$TOKEN" ]; then
    echo "$(date -u +'%Y-%m-%d %H:%M:%S') UTC: ОШИБКА — GH_DISPATCH_TOKEN не найден в .env" >> "$LOG_FILE"
    exit 1
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/Ruslan591/weather-_Odessa/actions/workflows/full_pipeline.yml/dispatches" \
    -d '{"ref":"main"}')

if [ "$HTTP_CODE" = "204" ]; then
    echo "$(date -u +'%Y-%m-%d %H:%M:%S') UTC: triggered OK (204)" >> "$LOG_FILE"
else
    echo "$(date -u +'%Y-%m-%d %H:%M:%S') UTC: ОШИБКА триггера, http_code=$HTTP_CODE" >> "$LOG_FILE"
fi

# держим лог компактным — последние 200 строк
tail -n 200 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
