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
    return subprocess.run(
        cmd, shell=True, check=True, text=True, capture_output=True
    ).stdout


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
    import git_filter_repo as fr  # type: ignore

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
    print("История переписана ЛОКАЛЬНО (в этом клоне). Push делает следующий шаг workflow.")


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
