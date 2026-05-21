#!/usr/bin/env python3
"""
update_local.py — локальная версия update.py для запуска в Termux.

Читает/пишет файлы напрямую с диска вместо GitHub API.
После обновления делает git commit + git push.

Запуск:
    cd /storage/emulated/0/Documents/weather
    python3 scripts/update_local.py

Аргументы:
    --no-push     обновить локальные файлы без git push
    --no-synop    пропустить шаг 1 (SYNOP с ogimet)
    --no-model    пропустить шаг 2 (исторические данные моделей)
    --snap-only   только шаг 3: снять снимок ансамбля (быстро, ~1 мин)
"""

import os, sys, subprocess, argparse

# ── Путь к проекту (скрипт лежит рядом с update.py в scripts/) ───────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Заглушка токена (GitHub API не используется для чтения/записи) ────────────
os.environ.setdefault("GITHUB_TOKEN", "_local_")

# ── Импортируем оригинальный update.py ────────────────────────────────────────
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
import update as _upd

# ── Локальный I/O: замена GitHub API на файловую систему ─────────────────────

_GIT_CHANGED = []   # файлы, которые нужно закоммитить

def _local_gh_get(path):
    """Читает файл из BASE_DIR/path. Возвращает (text, 'local') или (None, None)."""
    full = os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        return None, None
    with open(full, "r", encoding="utf-8") as f:
        return f.read(), "local"

def _local_gh_put(path, content, sha, message):
    """Пишет файл в BASE_DIR/path, запоминает для git."""
    full = os.path.join(BASE_DIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    if path not in _GIT_CHANGED:
        _GIT_CHANGED.append(path)
    _upd.log.info("  💾 %s", path)
    return "local"

# Monkey-patch — gh_load_json/gh_save_json автоматически используют патч
_upd.gh_get = _local_gh_get
_upd.gh_put = _local_gh_put

# ── Git-операции ──────────────────────────────────────────────────────────────

def git_commit_push(no_push=False):
    if not _GIT_CHANGED:
        print("\n  git: нечего коммитить")
        return

    files_str = ", ".join(os.path.basename(p) for p in _GIT_CHANGED)
    msg = f"update_local: {files_str}"

    try:
        subprocess.run(
            ["git", "-C", BASE_DIR, "add"] + _GIT_CHANGED,
            check=True, capture_output=True
        )
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", msg],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"\n  git commit: {result.stdout.strip() or result.stderr.strip()}")
            return

        print(f"\n  git commit ✓  ({files_str})")

        if not no_push:
            push = subprocess.run(
                ["git", "-C", BASE_DIR, "push"],
                capture_output=True, text=True
            )
            if push.returncode == 0:
                print("  git push ✓")
            else:
                print(f"  git push ✗: {push.stderr.strip()}")
        else:
            print("  git push пропущен (--no-push)")

    except subprocess.CalledProcessError as e:
        print(f"\n  git: ошибка — {e}")

# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="update_local.py — локальный апдейтер")
    parser.add_argument("--no-push",   action="store_true", help="Не делать git push")
    parser.add_argument("--no-synop",  action="store_true", help="Пропустить шаг 1 (SYNOP)")
    parser.add_argument("--no-model",  action="store_true", help="Пропустить шаг 2 (modelData)")
    parser.add_argument("--snap-only", action="store_true", help="Только снять снимок (шаг 3+4)")
    args = parser.parse_args()

    # --snap-only / --no-synop: fetch_synop_ogimet возвращает None → шаг 1 пустой
    if args.snap_only or args.no_synop:
        _upd.fetch_synop_ogimet = lambda d: None
        _upd.time.sleep = lambda s: None   # убираем паузы между датами
        _upd.log.info("  [local] Шаг 1 (SYNOP) пропущен")

    # --snap-only / --no-model: fetch_historical_model возвращает None → шаг 2 пустой
    if args.snap_only or args.no_model:
        _upd.fetch_historical_model = lambda m, d: None
        _upd.log.info("  [local] Шаг 2 (modelData) пропущен")

    _upd.main()
    git_commit_push(no_push=args.no_push)

if __name__ == "__main__":
    main()
