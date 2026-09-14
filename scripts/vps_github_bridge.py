#!/usr/bin/env python3
"""
vps_github_bridge.py — обходной канал управления VPS без прямого HTTP-доступа Claude к серверу.

Причина существования: на индивидуальных тарифах Claude (Free/Pro/Max) нет возможности
добавить кастомный домен в network egress allowlist (это функция только Team/Enterprise) —
см. docs/topics/hosting_migration.md. Поэтому Claude не может напрямую обратиться к
HTTPS-агенту (scripts/vps_agent.py) на сервере, даже если тот развёрнут и работает.

Схема:
  Claude пишет задачу  -> data/vps_task.json      (через GitHub Contents API, уже работает)
  Этот скрипт на VPS    -> читает vps_task.json каждую минуту (cron)
                         -> если task_id новый — выполняет команду локально
                         -> пишет результат в data/vps_result.json
  Claude читает результат -> data/vps_result.json (через GitHub Contents API)

Формат data/vps_task.json:
{
  "task_id": "уникальная строка, обычно timestamp или счётчик",
  "cmd": "shell-команда для выполнения на сервере",
  "timeout": 60
}

Формат data/vps_result.json (перезаписывается после каждой обработанной задачи):
{
  "task_id": "тот же task_id, что был в задаче",
  "returncode": 0,
  "stdout": "...",
  "stderr": "...",
  "completed_at_utc": "2026-08-26T20:00:00Z"
}

Обработанный task_id запоминается в state-файле локально на сервере
(/opt/vps-github-bridge/last_task_id.txt), чтобы не выполнять одну и ту же команду повторно
при каждом запуске cron.

Настройка (один раз, через install-скрипт или вручную):
  - GITHUB_TOKEN в /etc/vps-github-bridge/token (аналогично vps-agent)
  - cron: * * * * * /opt/vps-github-bridge/venv/bin/python3 /opt/vps-github-bridge/vps_github_bridge.py
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import base64
from datetime import datetime, timezone

REPO = "ruslan591/weather-_Odessa"
BRANCH = "main"
TASK_PATH = "data/vps_task.json"
RESULT_PATH = "data/vps_result.json"
STATE_FILE = "/opt/vps-github-bridge/last_task_id.txt"
TOKEN_FILE = "/etc/vps-github-bridge/token"

API_BASE = "https://api.github.com"


def load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GITHUB_TOKEN="):
                    return line.strip().split("=", 1)[1]
    raise RuntimeError("GITHUB_TOKEN не найден ни в окружении, ни в " + TOKEN_FILE)


def gh_request(method: str, path: str, token: str, body: dict | None = None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        return e.code, json.loads(body_text) if body_text else {}


def get_file(path: str, token: str):
    status, resp = gh_request(
        "GET", f"/repos/{REPO}/contents/{path}?ref={BRANCH}", token
    )
    if status == 404:
        return None, None
    if status != 200:
        raise RuntimeError(f"GET {path} failed: {status} {resp}")
    content = base64.b64decode(resp["content"]).decode("utf-8")
    return json.loads(content), resp["sha"]


def put_file(path: str, token: str, obj: dict, sha: str | None, message: str):
    content_b64 = base64.b64encode(
        json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    body = {"message": message, "content": content_b64, "branch": BRANCH}
    if sha:
        body["sha"] = sha
    status, resp = gh_request("PUT", f"/repos/{REPO}/contents/{path}", token, body)
    if status not in (200, 201):
        raise RuntimeError(f"PUT {path} failed: {status} {resp}")


def load_last_task_id() -> str | None:
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def save_last_task_id(task_id: str) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(task_id)


def main() -> int:
    token = load_token()

    task, _task_sha = get_file(TASK_PATH, token)
    if not task:
        return 0  # нет файла задачи — нечего делать

    task_id = str(task.get("task_id", ""))
    if not task_id:
        return 0

    last_id = load_last_task_id()
    if task_id == last_id:
        return 0  # уже обработано

    cmd = task.get("cmd", "")
    timeout = int(task.get("timeout", 60))

    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        result = {
            "task_id": task_id,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-50_000:],
            "stderr": proc.stderr[-50_000:],
            "completed_at_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
    except subprocess.TimeoutExpired:
        result = {
            "task_id": task_id,
            "returncode": -1,
            "stdout": "",
            "stderr": f"command timed out after {timeout}s",
            "completed_at_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }

    _existing_result, result_sha = get_file(RESULT_PATH, token)
    put_file(
        RESULT_PATH,
        token,
        result,
        result_sha,
        f"vps-bridge: результат задачи {task_id}",
    )
    save_last_task_id(task_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
