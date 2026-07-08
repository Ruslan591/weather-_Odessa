#!/usr/bin/env python3
"""
push_file_via_api.py — публикует ОДИН локальный файл на GitHub напрямую через
Contents API (без git add/commit/push).

Полезно для файлов, которые правит только человек и никогда не трогает
пайплайн (например data/ai_schedule.json) — конфликтов с облаком в принципе
быть не может, поэтому локальный git не нужен вообще.

Использование:
    python3 scripts/push_file_via_api.py data/ai_schedule.json "ai_schedule: update"

Требует GH_DISPATCH_TOKEN в .env (тот же токен, что для триггера workflow —
права repo достаточно).
"""

import sys
import os
import json
import base64
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")
REPO_OWNER = "Ruslan591"
REPO_NAME = "weather-_Odessa"


def load_token():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GH_DISPATCH_TOKEN="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("GH_DISPATCH_TOKEN")


def api_request(url, token, method="GET", body=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/push_file_via_api.py <путь_относительно_репо> [сообщение_коммита]")
        sys.exit(1)

    rel_path = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else f"update {rel_path} via API"

    token = load_token()
    if not token:
        print("Ошибка: GH_DISPATCH_TOKEN не найден в .env")
        sys.exit(1)

    local_path = os.path.join(BASE_DIR, rel_path)
    if not os.path.exists(local_path):
        print(f"Ошибка: файл не найден локально: {local_path}")
        sys.exit(1)

    with open(local_path, "rb") as f:
        content = f.read()
    encoded = base64.b64encode(content).decode("ascii")

    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{rel_path}"

    # получаем текущий sha (если файл уже существует на GitHub)
    sha = None
    try:
        info = api_request(f"{api_url}?ref=main", token)
        sha = info.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"Ошибка чтения текущего файла: {e.code} {e.read().decode()}")
            sys.exit(1)
        # 404 — файла ещё нет на GitHub, создаём новый

    body = {"message": message, "content": encoded}
    if sha:
        body["sha"] = sha

    try:
        resp = api_request(api_url, token, method="PUT", body=body)
        print(f"✓ Опубликовано: {rel_path} (sha: {resp['content']['sha'][:8]})")
    except urllib.error.HTTPError as e:
        print(f"✗ Ошибка публикации: {e.code} {e.read().decode()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
