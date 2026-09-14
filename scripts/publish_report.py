#!/usr/bin/env python3
"""Публикует .github/history_prune_last_report.txt через Contents API.

Не использует git push вообще — обходит все тонкости с правами на
переписанную историю и гонки с чекаутом. Требует переменные окружения:
  GH_PAT       — токен с правом contents:write
  GH_REPO      — "owner/repo"
  RUN_ID       — github.run_id
  EVENT_NAME   — github.event_name
  MODE         — analyze|execute
  REPORT_FILE  — путь к локальному файлу с выводом gh_history_prune.py
"""
import base64
import json
import os
import subprocess
import sys

TOKEN = os.environ["GH_PAT"]
REPO = os.environ["GH_REPO"]
PATH_ = ".github/history_prune_last_report.txt"


def api(method: str, url: str, data=None) -> dict:
    cmd = ["curl", "-s", "-X", method,
           "-H", f"Authorization: token {TOKEN}",
           "-H", "Accept: application/vnd.github+json", url]
    if data is not None:
        cmd += ["-d", json.dumps(data)]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return json.loads(out)


def main() -> int:
    when = subprocess.run(["date", "-u", "+%FT%TZ"], capture_output=True, text=True).stdout.strip()
    with open(os.environ["REPORT_FILE"]) as f:
        body = f.read()

    report = (
        "# History prune report\n"
        f"run: {os.environ['RUN_ID']} | trigger: {os.environ['EVENT_NAME']} | "
        f"mode: {os.environ['MODE']} | when: {when}\n\n"
        f"{body}"
    )

    base = f"https://api.github.com/repos/{REPO}/contents/{PATH_}"
    cur = api("GET", base + "?ref=main")
    sha = cur.get("sha")

    payload = {
        "message": f"History prune report (mode={os.environ['MODE']})",
        "content": base64.b64encode(report.encode()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    res = api("PUT", base, payload)
    if "content" not in res:
        print("ОШИБКА публикации отчёта:", res.get("message"), res)
        return 1

    print("Отчёт опубликован, sha:", res["content"]["sha"][:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
