#!/usr/bin/env bash
# Установка HTTP-агента weather-odessa-vps на Ubuntu 24.04 (Oracle A1.Flex, ARM).
# Запускать ОДИН РАЗ на самом сервере (через Oracle Cloud Shell → SSH к инстансу,
# или через веб-консоль VM → Instance Console Connection).
#
# После выполнения скрипт выведет:
#   - публичный домен агента (nip.io, автоматически резолвится в текущий IP сервера)
#   - токен авторизации (VPS_AGENT_TOKEN)
# Эти два значения нужно передать Claude в чате — это всё, что требуется для доступа.
#
# Что делает скрипт:
#   1. Ставит Python3/pip/venv, FastAPI, uvicorn
#   2. Ставит Caddy (авто-TLS через Let's Encrypt, без ручной настройки certbot)
#   3. Генерирует случайный токен, кладёт в /etc/vps-agent/token
#   4. Создаёт systemd unit vps-agent.service (слушает 127.0.0.1:8080)
#   5. Настраивает Caddyfile: https://<IP>.nip.io -> reverse_proxy 127.0.0.1:8080

set -euo pipefail

PUBLIC_IP="$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com)"
if [ -z "$PUBLIC_IP" ]; then
  echo "Не удалось определить публичный IP автоматически. Укажи вручную:"
  read -r PUBLIC_IP
fi
NIP_DOMAIN="$(echo "$PUBLIC_IP" | tr '.' '-').nip.io"

echo "== Публичный IP: $PUBLIC_IP =="
echo "== Домен агента: $NIP_DOMAIN =="

echo "== Обновление пакетов и установка зависимостей =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https gnupg

echo "== Установка Caddy (официальный репозиторий) =="
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y
  sudo apt-get install -y caddy
fi

echo "== Настройка агента =="
sudo mkdir -p /opt/vps-agent
sudo mkdir -p /etc/vps-agent

if [ ! -f /etc/vps-agent/token ]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "VPS_AGENT_TOKEN=$TOKEN" | sudo tee /etc/vps-agent/token >/dev/null
  sudo chmod 600 /etc/vps-agent/token
else
  TOKEN="$(sudo grep VPS_AGENT_TOKEN /etc/vps-agent/token | cut -d= -f2-)"
  echo "Токен уже существовал, использую сохранённый."
fi

# vps_agent.py должен лежать рядом с этим скриптом (скачивается отдельно с raw.githubusercontent.com)
sudo cp ./vps_agent.py /opt/vps-agent/vps_agent.py

sudo python3 -m venv /opt/vps-agent/venv
sudo /opt/vps-agent/venv/bin/pip install --upgrade pip
sudo /opt/vps-agent/venv/bin/pip install fastapi "uvicorn[standard]"

echo "== systemd unit =="
sudo tee /etc/systemd/system/vps-agent.service >/dev/null <<'EOF'
[Unit]
Description=weather-odessa-vps HTTP agent
After=network.target

[Service]
Type=simple
EnvironmentFile=/etc/vps-agent/token
WorkingDirectory=/opt/vps-agent
ExecStart=/opt/vps-agent/venv/bin/uvicorn vps_agent:app --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable vps-agent
sudo systemctl restart vps-agent

echo "== Caddyfile =="
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$NIP_DOMAIN {
    reverse_proxy 127.0.0.1:8080
}
EOF

sudo systemctl restart caddy

echo "== Открытие портов 80/443 в ufw (если активен) =="
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
fi

echo ""
echo "======================================================"
echo "ГОТОВО. Передай Claude в чате следующие два значения:"
echo ""
echo "  Домен агента: https://$NIP_DOMAIN"
echo "  Токен:        $TOKEN"
echo ""
echo "Проверка (можно выполнить прямо сейчас):"
echo "  curl https://$NIP_DOMAIN/health"
echo "======================================================"
