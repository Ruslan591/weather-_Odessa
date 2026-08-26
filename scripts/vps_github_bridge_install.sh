#!/usr/bin/env bash
# Установка обходного канала управления VPS через GitHub (без прямого HTTP-доступа Claude).
# Запускать ОДИН РАЗ на сервере (Cloud Shell -> ssh -> этот скрипт).
#
# В отличие от vps_agent_install.sh, этот скрипт НЕ открывает никаких портов наружу —
# сервер сам, по расписанию cron, стучится на api.github.com (исходящий трафик, порт 443,
# который и так открыт по умолчанию для исходящих соединений).
#
# Нужен: GitHub PAT с правами repo (тот же, что уже используется Claude для правки репозитория).
# Скрипт запросит его интерактивно и один раз сохранит в /etc/vps-github-bridge/token.

set -euo pipefail

echo "== Установка зависимостей =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip curl

echo "== Директории =="
sudo mkdir -p /opt/vps-github-bridge
sudo mkdir -p /etc/vps-github-bridge

if [ ! -f /etc/vps-github-bridge/token ]; then
  echo "Вставь GitHub PAT (ввод будет скрыт):"
  read -r -s GH_TOKEN
  echo "GITHUB_TOKEN=$GH_TOKEN" | sudo tee /etc/vps-github-bridge/token >/dev/null
  sudo chmod 600 /etc/vps-github-bridge/token
  echo "Токен сохранён."
else
  echo "Токен уже существует, пропускаю."
fi

sudo cp ./vps_github_bridge.py /opt/vps-github-bridge/vps_github_bridge.py

echo "== Виртуальное окружение (скрипт использует только стандартную библиотеку, venv не обязателен, но для единообразия создаём) =="
sudo python3 -m venv /opt/vps-github-bridge/venv

echo "== Разовый тестовый запуск =="
sudo /opt/vps-github-bridge/venv/bin/python3 /opt/vps-github-bridge/vps_github_bridge.py && echo "Тестовый запуск прошёл без ошибок (или нет задачи — это нормально)."

echo "== Настройка cron (раз в минуту, от имени root) =="
CRON_LINE="* * * * * /opt/vps-github-bridge/venv/bin/python3 /opt/vps-github-bridge/vps_github_bridge.py >> /var/log/vps-github-bridge.log 2>&1"
( sudo crontab -l 2>/dev/null | grep -v "vps_github_bridge.py" ; echo "$CRON_LINE" ) | sudo crontab -

echo ""
echo "======================================================"
echo "ГОТОВО. Мост настроен и работает по cron (раз в минуту)."
echo "Логи: /var/log/vps-github-bridge.log"
echo "Порты наружу НЕ открывались — весь трафик исходящий на api.github.com."
echo "======================================================"
