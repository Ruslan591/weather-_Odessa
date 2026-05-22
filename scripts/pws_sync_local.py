#!/usr/bin/env python3
"""
pws_sync_local.py — локальная версия pws_sync.py для запуска в Termux.

Читает/пишет data/pws_raw.json напрямую с диска вместо GitHub API.
После обновления делает git commit + git push.

Запуск:
    cd /storage/emulated/0/Documents/weather
    python3 scripts/pws_sync_local.py

Аргументы:
    --no-push   записать файл без git push
"""

import os, sys, json, subprocess, argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("GITHUB_TOKEN", "_local_")

sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
import pws_sync as _pws

# ── Локальный I/O ─────────────────────────────────────────────────────────────

_GIT_CHANGED = []
FILE_FULL = os.path.join(BASE_DIR, _pws.FILE_PATH)

def _local_gh_get():
    if not os.path.exists(FILE_FULL):
        return [], None
    with open(FILE_FULL, "r", encoding="utf-8") as f:
        return json.load(f), "local"

def _local_gh_put(data, sha):
    content = "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n]"
    os.makedirs(os.path.dirname(FILE_FULL), exist_ok=True)
    with open(FILE_FULL, "w", encoding="utf-8") as f:
        f.write(content)
    if _pws.FILE_PATH not in _GIT_CHANGED:
        _GIT_CHANGED.append(_pws.FILE_PATH)
    _pws.log.info("  💾 %s", _pws.FILE_PATH)
    return "local"

_pws.gh_get = _local_gh_get
_pws.gh_put = _local_gh_put

# ── Git ───────────────────────────────────────────────────────────────────────

def git_commit_push(no_push=False):
    try:
        if _GIT_CHANGED:
            subprocess.run(
                ["git", "-C", BASE_DIR, "add"] + _GIT_CHANGED,
                check=True, capture_output=True
            )
            result = subprocess.run(
                ["git", "-C", BASE_DIR, "commit", "-m", "pws_sync_local: pws_raw.json"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"\n  git commit: {result.stdout.strip() or result.stderr.strip()}")
            else:
                print("\n  git commit ✓  (pws_raw.json)")
        else:
            print("\n  git: новых данных нет")

        if no_push:
            print("  git push пропущен (--no-push)")
            return

        push = subprocess.run(
            ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
            capture_output=True, text=True
        )
        if push.returncode == 0:
            print("  git push ✓")
        else:
            print(f"  git push ✗: {push.stderr.strip()}")

    except subprocess.CalledProcessError as e:
        print(f"\n  git: ошибка — {e}")

# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="pws_sync_local.py — локальный синк PWS")
    parser.add_argument("--no-push", action="store_true", help="Не делать git push")
    args = parser.parse_args()

    _pws.main()
    git_commit_push(no_push=args.no_push)

if __name__ == "__main__":
    main()