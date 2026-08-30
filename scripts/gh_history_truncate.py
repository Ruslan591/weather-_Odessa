#!/usr/bin/env python3
"""
gh_history_truncate.py — полное усечение git-истории до последних --days дней.

Решено 30.08.2026 (см. docs/topics/hosting_migration.md, обсуждение по
раздуванию репозитория ensemble_snapshots_*.json). Заменяет избирательную
чистку (scripts/gh_history_prune.py, только media-файлы) на полное усечение
ВСЕЙ истории разом: всё старше --days дней сжимается в один базовый коммит
(git commit-tree на дереве пограничного коммита), настоящие коммиты внутри
окна переносятся как есть (git rebase --onto). Технически даже проще
прежнего подхода (filter-repo с колбэком по путям и merge-map) — просто один
срез по времени, без разбора путей и специальных случаев "последняя версия
файла".

Причины оставить именно 30 дней, а не 1-2 суток — см. docs/topics/
hosting_migration.md: минимум 3-4 цикла самой чистки про запас (откатиться,
если баг в самом механизме), плюс запас на "не заходил на сайт пару недель".

Режимы:
  --mode analyze  — только отчёт, ничего не меняет
  --mode execute  — реально переписывает историю и пушит

chunked_push()/handle_live_drift() — СКОПИРОВАНЫ дословно из
gh_history_prune.py (тот же самый, уже обкатанный паттерн):
  - GitHub рвёт соединение (HTTP 500) на одном гигантском force-push
    переписанной истории → продвигаем служебную ветку чекпоинтами.
  - Пока клонировались/переписывали историю (много минут), VPS (коммитит
    каждые 5 мин) почти наверняка успел уйти вперёд на реальном main →
    переносим эти новые коммиты поверх усечённой истории перед пушем,
    иначе force-push их сотрёт. Это заменяет собой ручную паузу cron на
    время прогона — приостанавливать VPS не обязательно.

Запускать ВНУТРИ директории git-репозитория (полный клон, не mirror и не
shallow — нужен обычный checkout main для rebase).
"""
import subprocess
import sys
import argparse
from datetime import datetime, timezone, timedelta


def sh(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if r.returncode != 0:
        print(f"КОМАНДА УПАЛА: {cmd}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
    return r.stdout


def chunked_push(batch_size: int = 1500) -> None:
    sh("git config http.postBuffer 524288000")
    sh("git config http.version HTTP/1.1")

    commits = sh("git rev-list --reverse main").strip().splitlines()
    total = len(commits)
    scratch = "__truncate_progress__"
    checkpoints = list(range(batch_size - 1, total, batch_size))
    if not checkpoints or checkpoints[-1] != total - 1:
        checkpoints.append(total - 1)

    print(f"Пушу {total} коммитов чанками по {batch_size}, чекпоинтов: {len(checkpoints)}")
    for n, idx in enumerate(checkpoints, 1):
        csha = commits[idx]
        print(f"  чекпоинт {n}/{len(checkpoints)} ({idx + 1}/{total} коммитов): {csha[:10]}")
        sh(f"git push origin +{csha}:refs/heads/{scratch}")

    print("Все объекты уже на сервере — финальный (дешёвый) апдейт main.")
    sh("git push --force origin main")
    sh(f"git push origin --delete {scratch}")


def handle_live_drift(old_main: str) -> None:
    sh("git fetch origin '+refs/heads/main:refs/heads/__live_check__'")
    new_main = sh("git rev-parse refs/heads/__live_check__").strip()

    if new_main == old_main:
        print("Новых коммитов на main за время прогона не появилось.")
        return

    ahead = sh(f"git rev-list --count {old_main}..{new_main}").strip()
    print(f"На main появилось {ahead} новых коммитов за время прогона — переношу поверх усечённой истории.")
    try:
        sh(f"git rebase --onto main {old_main} refs/heads/__live_check__")
    except subprocess.CalledProcessError as e:
        sh("git rebase --abort")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        raise SystemExit(
            "Не удалось перенести новые коммиты поверх усечённой истории "
            "(конфликт при rebase). Push отменён, ничего не сломано на "
            "удалённом репозитории — нужно разобраться руками."
        )
    sh("git branch -f main __live_check__")
    sh("git checkout main")
    sh("git branch -D __live_check__")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["analyze", "execute"], default="analyze")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    size_before = sh("du -sh .git").strip()
    total_commits = sh("git rev-list --count main").strip()

    keep_from_lines = sh(
        f"git log --since {cutoff_str!r} --format=%H --reverse main"
    ).strip().splitlines()
    if not keep_from_lines:
        print(f"Нет коммитов за последние {args.days} дней — отменяю, "
              f"что-то не так (проверить вручную).")
        sys.exit(1)
    keep_from = keep_from_lines[0]

    parent_check = subprocess.run(
        f"git rev-parse {keep_from}^", shell=True, text=True, capture_output=True)
    if parent_check.returncode != 0:
        print(f"У самого старого коммита в окне ({keep_from[:8]}) нет родителя — "
              f"история и так короче {args.days} дней, усекать нечего.")
        sys.exit(0)
    parent_of_keep = parent_check.stdout.strip()

    commits_to_drop = sh(f"git rev-list --count {parent_of_keep}").strip()
    commits_to_keep = int(total_commits) - int(commits_to_drop)

    print(f"Всего коммитов сейчас: {total_commits}")
    print(f"Размер .git сейчас: {size_before}")
    print(f"Граница окна ({args.days} дн.): {cutoff_str}")
    print(f"Будет сохранено (начиная с {keep_from[:8]}): {commits_to_keep} коммитов")
    print(f"Будет сжато в 1 базовый коммит: {commits_to_drop} коммитов "
          f"(всё до и включая {parent_of_keep[:8]})")

    if args.mode == "analyze":
        print("\nРежим analyze — изменений не внесено.")
        return

    old_main = sh("git rev-parse main").strip()

    tree = sh(f"git rev-parse {parent_of_keep}^{{tree}}").strip()
    msg = (f"История усечена ({datetime.now(timezone.utc).strftime('%Y-%m-%d')}): "
           f"базовый снимок, сжато {commits_to_drop} коммитов старше {args.days} дней")
    new_base = sh(f"git commit-tree {tree} -m {msg!r}").strip()
    if not new_base:
        raise SystemExit("commit-tree не создал новый корень — прерываю.")
    print(f"Новый базовый коммит: {new_base}")

    try:
        sh(f"git rebase --onto {new_base} {parent_of_keep} main")
    except subprocess.CalledProcessError as e:
        sh("git rebase --abort")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        raise SystemExit("rebase --onto не прошёл — история НЕ изменена на удалённом репозитории.")

    handle_live_drift(old_main)
    chunked_push()

    sh("git reflog expire --expire=now --all")
    sh("git gc --prune=now --aggressive")
    size_after = sh("du -sh .git").strip()

    print(f"\n✓ Готово. Размер .git локально после gc: {size_after} (было {size_before})")
    print("Не забыть: пересоздать клон на VPS (git clone --depth 1, ~6с — уже проверено эмпирически 30.08.2026).")


if __name__ == "__main__":
    sys.exit(main())
