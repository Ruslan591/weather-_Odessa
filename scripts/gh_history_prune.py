#!/usr/bin/env python3
"""
Прунинг git-истории для 'мультимедиа'-путей (mp4/mp3/png/jpg/jpeg/gif/webp).

Логика: для каждого такого пути в истории удаляются ВСЕ версии старше
--hours часов, КРОМЕ:
  (a) самой последней версии пути в истории (чтобы файл не исчез из HEAD),
  (b) любых версий моложе --hours часов.
Всё остальное (JSON, .npz, код, docs, html) НЕ трогается вообще.

Режимы:
  --mode analyze  — только отчёт (сколько commit-touches будет вырезано), ничего не меняет
  --mode execute  — реально переписывает ЛОКАЛЬНУЮ историю через git-filter-repo
                    (push делает отдельный шаг workflow, этот скрипт не пушит)

Запускать ВНУТРИ директории git-репозитория (mirror-клон).
"""
import subprocess
import sys
import time
import argparse
from pathlib import Path

MEDIA_EXTS = {".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def sh(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if r.returncode != 0:
        print(f"КОМАНДА УПАЛА: {cmd}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
    return r.stdout


def is_media(path: str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTS


def build_maps(cutoff_ts: int):
    """
    Один проход по всей истории (oldest -> newest).
    Возвращает:
      latest_commit_for_path: {путь: sha последнего коммита, тронувшего путь}
      recent_shas: множество sha коммитов моложе cutoff_ts
    """
    out = sh("git log --reverse --name-only --no-renames --pretty=format:'@@%H|%ct'")
    latest_commit_for_path = {}
    recent_shas = set()
    cur_sha = None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur_sha, ts = line[2:].split("|")
            if int(ts) >= cutoff_ts:
                recent_shas.add(cur_sha)
        else:
            path = line.strip()
            if path and is_media(path):
                latest_commit_for_path[path] = cur_sha
    return latest_commit_for_path, recent_shas


def analyze(latest_commit_for_path, recent_shas, hours: int):
    out = sh("git log --name-only --no-renames --pretty=format:'@@%H'")
    cur_sha = None
    affected = 0
    touched_paths = set()
    for line in out.splitlines():
        if line.startswith("@@"):
            cur_sha = line[2:]
        else:
            path = line.strip()
            if not path or not is_media(path):
                continue
            if cur_sha in recent_shas:
                continue
            if latest_commit_for_path.get(path) == cur_sha:
                continue
            affected += 1
            touched_paths.add(path)

    print(f"Медиа-путей всего в истории: {len(latest_commit_for_path)}")
    print(f"Коммитов моложе {hours}ч (не трогаются вообще): {len(recent_shas)}")
    print(f"Commit-touches к удалению: {affected} (по {len(touched_paths)} путям)")
    print("\nПути, которые будут прорежены:")
    for p in sorted(touched_paths):
        print(" -", p)
    print("\nЭто ТОЛЬКО отчёт. История не изменена. Для реального прогона: mode=execute")


def execute(latest_commit_for_path, recent_shas):
    import os
    import git_filter_repo as fr  # type: ignore

    old_main = sh("git rev-parse main").strip()
    print(f"main до прунинга: {old_main}")

    def commit_cb(commit, _metadata):
        sha = commit.original_id.decode("ascii")
        kept = []
        for change in commit.file_changes:
            path = change.filename.decode("utf-8", "replace")
            if not is_media(path) or sha in recent_shas or latest_commit_for_path.get(path) == sha:
                kept.append(change)
        commit.file_changes = kept

    args = fr.FilteringOptions.parse_args(["--force"])
    filt = fr.RepoFilter(args, commit_callback=commit_cb)
    filt.run()
    print("История переписана ЛОКАЛЬНО. filter-repo удаляет remote 'origin' — добавляю заново.")

    push_url = os.environ.get("REPO_PUSH_URL")
    if not push_url:
        raise SystemExit("REPO_PUSH_URL не задан — не могу запушить результат.")

    sh(f"git remote add origin {push_url!r}")

    # Пока клонировались/прунились ~20 ГБ (много минут), основной пайплайн
    # (коммиты каждые ~15 мин) почти наверняка успел уйти вперёд на реальном
    # main. Нужно перенести эти новые коммиты поверх прореженной истории,
    # иначе force-push их сотрёт.
    sh("git fetch origin '+refs/heads/main:refs/heads/__live_check__'")
    new_main = sh("git rev-parse refs/heads/__live_check__").strip()

    if new_main == old_main:
        print("Новых коммитов на main за время прогона не появилось.")
    else:
        ahead = sh(f"git rev-list --count {old_main}..{new_main}").strip()
        print(f"На main появилось {ahead} новых коммитов за время прогона — переношу поверх прореженной истории.")
        try:
            sh(f"git rebase --onto main {old_main} refs/heads/__live_check__")
        except subprocess.CalledProcessError as e:
            sh("git rebase --abort")
            print("STDOUT:", e.stdout)
            print("STDERR:", e.stderr)
            raise SystemExit(
                "Не удалось перенести новые коммиты поверх прореженной истории "
                "(конфликт при rebase). Push отменён, ничего не сломано на "
                "удалённом репозитории — нужно разобраться руками."
            )
        sh("git branch -f main __live_check__")
        sh("git checkout main")
        sh("git branch -D __live_check__")

    sh("git push --force origin main")
    print("Готово: прореженная история (с учётом свежих коммитов) запушена в main.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["analyze", "execute"], default="analyze")
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    cutoff_ts = int(time.time()) - args.hours * 3600
    latest_commit_for_path, recent_shas = build_maps(cutoff_ts)

    if args.mode == "analyze":
        analyze(latest_commit_for_path, recent_shas, args.hours)
    else:
        execute(latest_commit_for_path, recent_shas)


if __name__ == "__main__":
    sys.exit(main())
