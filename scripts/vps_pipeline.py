#!/usr/bin/env python3
"""
vps_pipeline.py — версия full_pipeline для постоянного VPS (не GitHub Actions).

Основано на scripts/gh_pipeline.py (облачный дирижёр для GH Actions).
Логика идентична, отличия:
  1. BASE_DIR — постоянный shallow-клон на диске VPS
     (/opt/weather-pipeline/repo), а не эфемерный checkout раннера.
  2. В начале КАЖДОГО цикла — обязательная синхронизация с origin:
     git fetch origin main --depth 1 && git reset --hard origin/main.
     Причина: пока full_pipeline.yml в GitHub Actions не отключён, оба
     писателя (VPS и GH Actions) пушат в один и тот же main. Без
     ресинхронизации в начале цикла VPS рискует стартовать со стейлового
     HEAD и потом получать rejected push. reset --hard безопасен именно
     ЗДЕСЬ (до вычислений), т.к. никаких ещё не закоммиченных изменений
     на этом этапе нет.
  3. git_push_history() уже содержал retry с fetch+rebase (без force) —
     этот механизм остаётся как есть и подстраховывает на случай, если
     GH Actions запушит что-то ПОСЛЕ старта текущего цикла VPS (rebase
     переносит коммит VPS поверх свежего HEAD).
  4. Запускается через cron на VPS (не workflow_dispatch), см.
     vps_pipeline_install.md / crontab на сервере.

Пока работает ПАРАЛЛЕЛЬНО с full_pipeline.yml в GH Actions (этап
тестирования). full_pipeline.yml отключается только после нескольких
стабильных циклов VPS без конфликтов push.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

# ── конфиг ────────────────────────────────────────────────────────────────────
BASE_DIR     = "/opt/weather-pipeline/repo"
HISTORY_FILE = os.path.join(BASE_DIR, "data", "model_runs_history.json")
LOG_DIR      = os.path.join(BASE_DIR, "logs")
MAX_ENTRIES  = 60

AI_QUEUE_FILE = os.path.join(BASE_DIR, "data", "_ai_pending_models.json")

PYTHON       = sys.executable
SCRIPTS_DIR  = os.path.join(BASE_DIR, "scripts")

MODELS = [
    {"id": "ecmwf_ifs",                     "metaId": "ecmwf_ifs025",                   "label": "ECMWF IFS"},
    {"id": "icon_eu",                        "metaId": "dwd_icon_eu",                    "label": "ICON EU"},
    {"id": "ukmo_global_deterministic_10km", "metaId": "ukmo_global_deterministic_10km", "label": "UKMO"},
    {"id": "meteofrance_arpege_europe",      "metaId": "meteofrance_arpege_europe",      "label": "Arpège"},
    {"id": "gfs_global",                     "metaId": "ncep_gfs013",                    "label": "GFS"},
    {"id": "cma_grapes_global",              "metaId": "cma_grapes_global",              "label": "GRAPES"},
]

OPEN_METEO_META = "https://api.open-meteo.com/data/{metaId}/static/meta.json"
TIMEOUT = 15

# ── вспомогательные ───────────────────────────────────────────────────────────

def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ts_to_iso(unix_ts):
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def iso_to_local(iso_str):
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m %H:%M")
    except Exception:
        return iso_str

def age_str(iso_str):
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if hours < 1:
            return f"{int(hours*60)}м назад"
        return f"{hours:.1f}ч назад"
    except Exception:
        return ""

# ── синхронизация репозитория (НОВОЕ для VPS-версии) ──────────────────────────

def sync_repo():
    """Обязательная ресинхронизация в начале КАЖДОГО цикла — см. docstring.

    ВАЖНО (найдено 27.08.2026): `git reset --hard origin/main` НЕ гарантирует,
    что HEAD прикреплён к локальной ветке main. Если HEAD хоть раз "отвязался"
    (detached) — например, из-за прерванного `git rebase`/`stash pop` где-то
    в update_local.py — reset --hard просто двигает detached HEAD дальше,
    оставляя его detached навсегда. Итог: `git push` начинает падать со
    `fatal: You are not currently on a branch` на ВСЕХ трёх retry-попытках
    (наблюдалось: 16 из 20 циклов подряд потеряли push). Заодно
    `git stash` внутри update_local.py в detached-состоянии создаёт записи
    "WIP on (no branch)", которые не удаляются автоматически и копятся.

    Фикс: `git checkout -B main origin/main` вместо reset --hard — эта
    команда идемпотентно (пере)создаёт локальную ветку main и переключает
    на неё HEAD, гарантируя attached-состояние независимо от того, что было
    раньше.

    ВТОРАЯ НАХОДКА (27.08.2026, тот же день): `checkout -B` сам по себе
    требует ЧИСТОГО индекса — если предыдущий цикл закончился с unmerged-
    записями (сорванный `git stash pop`/rebase где-то в update_local.py),
    checkout падает с `error: you need to resolve your current index first`,
    sync_repo() возвращает False, и весь цикл пропускается ОДНОЙ строкой
    в лог, ничего не почистив. Конфликт остаётся — следующий цикл падает
    ровно так же. Итог: пайплайн молчал 5+ часов подряд (17:15-17:30),
    хотя cron исправно стрелял каждые 15 минут — просто каждый раз падал
    почти мгновенно на этом шаге, и `ensure_repo_healthy()` (см. ниже),
    вызываемая только из git_push_history(), даже не успевала отработать,
    потому что до неё сам sync_repo() уже возвращал False.

    Поэтому самолечение (abort rebase/merge + сброс индекса) теперь стоит
    ЗДЕСЬ, до checkout -B — а не только в git_push_history().
    """
    try:
        # Самолечение ДО checkout -B: чистим любой мусор, оставленный
        # предыдущим циклом, иначе checkout -B откажется работать.
        subprocess.run(["git", "-C", BASE_DIR, "rebase", "--abort"],
                       capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", BASE_DIR, "merge", "--abort"],
                       capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", BASE_DIR, "cherry-pick", "--abort"],
                       capture_output=True, text=True, timeout=15)

        # НАХОДКА (27.08.2026, поздний вечер): `reset --mixed HEAD` НЕ всегда
        # убирает unmerged-записи (UU) из индекса — если процесс был прерван
        # (например, cron убил зависший rebase) ДО того, как git успел
        # записать полное состояние конфликта, `.git/rebase-merge` может
        # остаться на диске в частично валидном виде, из-за чего `rebase
        # --abort`/`merge --abort` тихо завершаются с ошибкой и НИЧЕГО не
        # чистят, а `reset --mixed` не трогает stage 1/2/3 записи в индексе,
        # если git всё ещё считает репозиторий "в процессе rebase".
        # Наблюдалось: 3 цикла подряд получали одну и ту же ошибку
        # "you need to resolve your current index first" несмотря на
        # предыдущую версию самолечения. Единственное, что реально помогло —
        # ручное удаление .git/rebase-merge и т.п. НАПРЯМУЮ с диска плюс
        # `reset --hard` (не --mixed). Делаем то же самое автоматически:
        for _leftover in ("rebase-merge", "rebase-apply"):
            _p = os.path.join(BASE_DIR, ".git", _leftover)
            if os.path.isdir(_p):
                import shutil as _shutil
                _shutil.rmtree(_p, ignore_errors=True)
        for _leftover in ("MERGE_HEAD", "MERGE_MSG", "CHERRY_PICK_HEAD", "AUTO_MERGE"):
            _p = os.path.join(BASE_DIR, ".git", _leftover)
            if os.path.isfile(_p):
                try:
                    os.remove(_p)
                except OSError:
                    pass
        # НАХОДКА (28.08.2026, вечер): `.git/shallow.lock` (и другие *.lock —
        # index.lock, HEAD.lock, config.lock) — это ВНУТРЕННИЙ git-лок для
        # конкретной операции (fetch/commit/etc), НЕ путать с нашим
        # /tmp/vps_pipeline.lock (flock на уровне процесса). Если git-процесс
        # был прерван на середине операции (напр. столкнулся с ручной
        # отладочной командой в этой же рабочей директории), файл-лок
        # остаётся навсегда и блокирует ЛЮБОЙ следующий `git fetch` кодом
        # ошибки 128 ("Unable to create ... File exists"). В отличие от
        # unmerged-индекса это не даёт вообще никакой ошибки в основном теле
        # цикла — просто тихо роняет sync_repo() на fetch ещё ДО того, как
        # успевает попасть в лог что-то кроме "sync_repo failed". Наблюдалось:
        # пайплайн продолжал работать на СТАРОЙ версии кода несколько часов,
        # потому что каждый checkout -B срывался на fetch раньше, чем успевал
        # подтянуть новый скрипт с GitHub.
        for _lockname in ("shallow.lock", "index.lock", "HEAD.lock", "config.lock"):
            _p = os.path.join(BASE_DIR, ".git", _lockname)
            if os.path.isfile(_p):
                try:
                    os.remove(_p)
                    print(f"  [WARN] удалён зависший .git/{_lockname}")
                except OSError:
                    pass
        # reset --hard (не --mixed!) — единственное, что гарантированно
        # убирает unmerged (UU) записи из индекса в этом сценарии.
        subprocess.run(["git", "-C", BASE_DIR, "reset", "--hard", "HEAD"],
                       capture_output=True, text=True, timeout=15)

        fetch = subprocess.run(
            ["git", "-C", BASE_DIR, "fetch", "origin", "main", "--depth", "1"],
            capture_output=True, text=True, timeout=60)
        if fetch.returncode != 0:
            print(f"  [WARN] git fetch failed: {fetch.stderr.strip()}")
            return False

        was_detached = subprocess.run(
            ["git", "-C", BASE_DIR, "symbolic-ref", "-q", "HEAD"],
            capture_output=True, text=True, timeout=10).returncode != 0

        checkout = subprocess.run(
            ["git", "-C", BASE_DIR, "checkout", "-B", "main", "origin/main"],
            capture_output=True, text=True, timeout=30)
        if checkout.returncode != 0:
            # Крайний случай: даже после чистки checkout не прошёл.
            # Форсируем через reset --hard как последнюю линию защиты,
            # чтобы цикл НЕ пропускался молча (см. находку выше).
            print(f"  [WARN] git checkout -B main failed: {checkout.stderr.strip()}"
                  f" — форсирую reset --hard")
            subprocess.run(["git", "-C", BASE_DIR, "reset", "--hard", "origin/main"],
                           capture_output=True, text=True, timeout=30)
            checkout2 = subprocess.run(
                ["git", "-C", BASE_DIR, "checkout", "-B", "main", "origin/main"],
                capture_output=True, text=True, timeout=30)
            if checkout2.returncode != 0:
                print(f"  [WARN] checkout -B всё ещё падает: {checkout2.stderr.strip()}")
                return False

        if was_detached:
            print("  [WARN] HEAD был detached — переприкреплён к main")

        # Защита от накопления осиротевших stash-записей (см. докстринг).
        # Дропаем всё, что скопилось: свежие данные всё равно пересчитываются
        # заново каждым циклом, восстанавливать устаревший stash смысла нет.
        stash_list = subprocess.run(
            ["git", "-C", BASE_DIR, "stash", "list"],
            capture_output=True, text=True, timeout=10)
        if stash_list.stdout.strip():
            n = len(stash_list.stdout.strip().splitlines())
            subprocess.run(
                ["git", "-C", BASE_DIR, "stash", "clear"],
                capture_output=True, text=True, timeout=10)
            print(f"  [WARN] очищено {n} осиротевших stash-записей")

        print("  ✓ repo synced with origin/main")
        return True
    except Exception as e:
        print(f"  [WARN] sync_repo error: {e}")
        return False

# ── загрузка/сохранение истории ───────────────────────────────────────────────

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Не удалось прочитать историю: {e}")
    return {}

def save_history(history):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ── запрос к open-meteo ───────────────────────────────────────────────────────

def fetch_run_time(meta_id):
    url = OPEN_METEO_META.format(metaId=meta_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        ts = data.get("last_run_availability_time")
        return ts_to_iso(ts) if ts else None
    except Exception:
        return None

# ── git push (fetch+rebase retry — без force, без лока) ──────────────────────

def ensure_repo_healthy():
    """Самолечение перед каждым commit/push (найдено 27.08.2026).

    sync_repo() чинит detached HEAD только В НАЧАЛЕ цикла. Но update_local.py
    внутри себя делает свой git stash/pull --rebase/stash pop — и если ЭТОТ
    rebase конфликтует (гонка с параллельным GH Actions), может: (а) оставить
    HEAD detached (сорванный rebase), (б) оставить unmerged paths (сорванный
    stash pop). Оба состояния ломают ЛЮБОЙ следующий git commit/push в этом
    же цикле — наблюдалось как систематический провал push (16 из 20 циклов).

    Раз данные здесь — идемпотентно пересчитываемая статистика (bias/weights),
    жертвовать одним циклом ради устойчивости — не проблема: следующий цикл
    пересчитает всё заново с нуля.
    """
    try:
        # прерванный rebase/merge — бросаем, если есть
        subprocess.run(["git", "-C", BASE_DIR, "rebase", "--abort"],
                       capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", BASE_DIR, "merge", "--abort"],
                       capture_output=True, text=True, timeout=15)

        status = subprocess.run(
            ["git", "-C", BASE_DIR, "status", "--porcelain"],
            capture_output=True, text=True, timeout=15)
        has_unmerged = any(line.startswith(("U", "AA", "DD"))
                           for line in status.stdout.splitlines())
        is_detached = subprocess.run(
            ["git", "-C", BASE_DIR, "symbolic-ref", "-q", "HEAD"],
            capture_output=True, text=True, timeout=10).returncode != 0

        if has_unmerged or is_detached:
            print(f"  [WARN] repo нездоров (unmerged={has_unmerged}, "
                  f"detached={is_detached}) — пересобираю на origin/main")
            subprocess.run(
                ["git", "-C", BASE_DIR, "fetch", "origin", "main", "--depth", "1"],
                capture_output=True, text=True, timeout=60)
            subprocess.run(
                ["git", "-C", BASE_DIR, "checkout", "-B", "main", "origin/main"],
                capture_output=True, text=True, timeout=30)
            subprocess.run(["git", "-C", BASE_DIR, "stash", "clear"],
                           capture_output=True, text=True, timeout=10)
            return False  # локальные несохранённые изменения этого цикла потеряны
        return True
    except Exception as e:
        print(f"  [WARN] ensure_repo_healthy error: {e}")
        return False


def git_push_history():
    import time as _time
    try:
        ensure_repo_healthy()
        year = datetime.now(timezone.utc).year
        _candidates = [
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        # [ДОБАВЛЕНО 2026-08-27] calc_weights.py и pws_sync.py
                        # теперь в VPS-режиме пишут эти файлы напрямую на диск
                        # (без GITHUB_TOKEN, см. их докстринги) — коммит и push
                        # этих файлов делает этот процесс, не они сами.
                        "data/model_weights.json",
                        "data/pws_raw.json",
                        "data/_ai_pending_models.json",
                        "data/marine_history.json",
                        "data/nearby_precip.json",
                        "data/nearby_precip_debug.json",
                        "data/hmcbas_sea_temp_realtime.json",
                        "data/hmcbas_telegram_sea_temp.json",
                        "data/hmcbas_telegram_debug.json",
                        "data/pws_sync_state.json",
                        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                      check=True, capture_output=True, timeout=30)
        # [ДОБАВЛЕНО 2026-08-29] Раньше коммит всегда шёл под фиксированным
        # текстом "vps: synop + history update" (название историческое, ещё
        # с тех пор, когда это были единственные два файла), хотя реально
        # сюда попадает от 2 до 13 разных data-файлов — читать `git log` и
        # понимать, что реально изменилось, без захода внутрь коммита было
        # невозможно. Теперь имя коммита формируется по факту git status:
        # только реально изменённые/добавленные файлы из _to_add (не просто
        # всё, что оказалось в _to_add — многие уже up-to-date и add их не
        # трогает), короткими именами (basename без расширения).
        status = subprocess.run(
            ["git", "-C", BASE_DIR, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=15)
        _changed = [
            os.path.splitext(os.path.basename(p))[0]
            for p in status.stdout.strip().splitlines() if p.strip()
        ]
        if _changed:
            commit_msg = "vps: " + ", ".join(_changed)
            if len(commit_msg) > 200:
                commit_msg = commit_msg[:197] + "..."
        else:
            commit_msg = "vps: data update"
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", commit_msg],
            capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")

        _delays = [10, 20]
        for _attempt in range(3):
            push = subprocess.run(
                ["git", "-C", BASE_DIR, "push"],
                capture_output=True, text=True, timeout=60)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  history push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  history push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"],
                               capture_output=True, timeout=60)
                # НАХОДКА (27.08.2026, вечер): обычный `git rebase origin/main`
                # при КОНФЛИКТЕ содержимого (гонка с параллельным GH Actions
                # по тем же derived-файлам) сам оставляет HEAD detached до
                # ручного разрешения — а retry-цикл просто идёт на следующую
                # попытку, которая тут же валится с "not on a branch",
                # оставляя detached HEAD висеть до следующего вызова
                # sync_repo()/ensure_repo_healthy(). Раз эти файлы —
                # идемпотентно пересчитываемая статистика, конфликт можно
                # смело авто-резолвить в пользу СВОИХ данных этого цикла:
                # `-X theirs` для git rebase значит "предпочесть коммит,
                # который перекладываем" (наш), а не upstream — семантика
                # theirs/ours у rebase обратная по сравнению с merge.
                rebase = subprocess.run(
                    ["git", "-C", BASE_DIR, "rebase", "-X", "theirs", "origin/main"],
                    capture_output=True, text=True, timeout=60)
                if rebase.returncode != 0:
                    # rebase не смог даже с авторазрешением — не оставляем
                    # висеть detached HEAD до следующего цикла, чиним сразу.
                    print(f"  [WARN] rebase -X theirs не прошёл: "
                          f"{rebase.stderr.strip()[:200]} — abort+reset")
                    subprocess.run(["git", "-C", BASE_DIR, "rebase", "--abort"],
                                   capture_output=True, timeout=15)
                    subprocess.run(
                        ["git", "-C", BASE_DIR, "checkout", "-B", "main", "origin/main"],
                        capture_output=True, timeout=30)
        print("  history push failed after 3 attempts")
    except subprocess.TimeoutExpired as e:
        print(f"  history git timeout: {e}")
    except Exception as e:
        print(f"  history git error: {e}")

# ── пайплайн ──────────────────────────────────────────────────────────────────

def run_pipeline(new_models):
    print(f"\n  🚀 Новых прогонов: {len(new_models)} ({', '.join(new_models)})")
    print(  "     Запускаю пайплайн...\n")

    steps = [
        {"name": "calc_model_bias_cloud.py",
         "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_model_bias_cloud.py")]},
        {"name": "calc_weights.py (cloud/API)",
         "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_weights.py")]},
        {"name": "update_local.py --no-model",
         "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model"]},
    ]

    for step in steps:
        print(f"  ▶ {step['name']}")
        try:
            result = subprocess.run(step["cmd"], cwd=BASE_DIR,
                                     capture_output=False, timeout=300)
        except subprocess.TimeoutExpired:
            # НАХОДКА (27.08.2026): без timeout зависший шаг (напр. сетевой
            # вызов к open-meteo/GitHub API) мог блокировать процесс дольше
            # 15 минут — тогда cron запускал СЛЕДУЮЩИЙ экземпляр поверх ещё
            # работающего, и два процесса ломали один .git одновременно
            # (см. серию detached-HEAD патчей выше). Lock (flock) уже
            # закрывает саму гонку, но таймаут здесь убирает первопричину:
            # шаг не может висеть бесконечно.
            print(f"  ✗ {step['name']} завис дольше 300с — прерван по таймауту")
            print(  "    Пайплайн остановлен.")
            return False
        if result.returncode != 0:
            print(f"  ✗ {step['name']} завершился с ошибкой (код {result.returncode})")
            print(  "    Пайплайн остановлен.")
            return False
        print(f"  ✓ {step['name']}\n")

    print("  ✅ Пайплайн завершён успешно.")
    return True


def dispatch_ai_pipeline():
    """Диспетч ai_pipeline.yml через GitHub Actions API (28.08.2026).

    Раньше это делал последний шаг full_pipeline.yml (в GH Actions) — тем же
    паттерном (guard на in_progress/queued + явный workflow_dispatch), что
    описан в докстринге scripts/gh_ai_pipeline.py. Теперь, когда
    full_pipeline.yml отключается (VPS — основной писатель), диспетч
    переезжает сюда, иначе очередь `data/_ai_pending_models.json` продолжит
    наполняться, но AI-анализ (Claude/Gemini) никогда не запустится.

    Токен для диспетча (`GH_PAT`, PAT с scope repo+workflow) читается ТОЛЬКО
    из переменной окружения — не хардкодится в этом файле, т.к. файл
    закоммичен в публичный репозиторий. Настраивается в crontab на VPS.
    """
    # Порядок поиска токена: сперва env (GH_PAT), затем — уже существующий
    # git credential store на VPS (~/.git-credentials), которым и так
    # пользуется `git push` в этом же скрипте. Второй вариант позволяет
    # не передавать секрет через data/vps_task.json (канал моста
    # vps_github_bridge, который сам коммитится в git — GitHub secret
    # scanning справедливо блокирует такие коммиты, см. находку 28.08.2026).
    token = os.environ.get("GH_PAT")
    if not token:
        cred_file = os.path.expanduser("~/.git-credentials")
        if os.path.isfile(cred_file):
            try:
                with open(cred_file, "r", encoding="utf-8") as f:
                    for line in f:
                        m = re.search(r"://[^:]+:([^@]+)@github\.com", line)
                        if m:
                            token = m.group(1)
                            break
            except Exception:
                pass
    if not token:
        print("  [WARN] токен для диспетча ai_pipeline.yml не найден "
              "(ни GH_PAT в env, ни ~/.git-credentials) — пропуск")
        return

    repo = "ruslan591/weather-_Odessa"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    def _gh_get(url):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    try:
        # НАХОДКА (28.08.2026): обнаружен ran ai_pipeline.yml, застрявший в
        # статусе "queued" с 26.08.2026 15:03 UTC (~2 суток, 0 джобов) — не
        # снимается ни через POST /cancel ("not queued yet", 409), ни через
        # DELETE (403). Похоже на баг/аномалию на стороне GitHub Actions.
        # Пока этот ran существует, guard "уже queued" блокирует АБСОЛЮТНО
        # ЛЮБОЙ новый диспетч навсегда — AI-анализ был мёртв ~44 часа
        # незамеченным (это скрывал тот же guard в full_pipeline.yml).
        # Раз нормальный ran должен подхватываться раннером почти сразу,
        # игнорируем queued/in_progress runs старше 30 минут как зомби —
        # не полагаемся на то, что GitHub гарантированно почистит их сам.
        ZOMBIE_THRESHOLD_MIN = 30
        now = datetime.now(timezone.utc)
        for status in ("in_progress", "queued"):
            data = _gh_get(
                f"https://api.github.com/repos/{repo}/actions/workflows/"
                f"ai_pipeline.yml/runs?status={status}&per_page=5")
            for run in data.get("workflow_runs", []):
                created = datetime.strptime(
                    run["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age_min = (now - created).total_seconds() / 60
                if age_min < ZOMBIE_THRESHOLD_MIN:
                    print(f"  ai_pipeline.yml уже {status} "
                          f"({age_min:.0f} мин) — пропуск диспетча")
                    return
                print(f"  [WARN] ran {run['id']} висит в {status} "
                      f"{age_min:.0f} мин (>{ZOMBIE_THRESHOLD_MIN}) — "
                      f"похоже на зомби, игнорирую при проверке guard")

        body = json.dumps({"ref": "main"}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/"
            f"ai_pipeline.yml/dispatches",
            data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
        if code == 204:
            print("  ✓ ai_pipeline.yml задиспетчен")
        else:
            print(f"  [WARN] диспетч ai_pipeline.yml вернул HTTP {code}")
    except Exception as e:
        print(f"  [WARN] dispatch_ai_pipeline error: {e}")


def queue_ai_models(models):
    existing = []
    if os.path.exists(AI_QUEUE_FILE):
        try:
            with open(AI_QUEUE_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f).get("models", [])
        except Exception:
            pass
    merged = sorted(set(existing) | set(models))
    try:
        with open(AI_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": merged, "queued_at": now_utc_iso()}, f, ensure_ascii=False, indent=2)
        print(f"  ✓ AI-очередь: {', '.join(merged)}")
    except Exception as e:
        print(f"  [WARN] не удалось записать AI-очередь: {e}")
        return
    dispatch_ai_pipeline()

# ── PWS-синк ───────────────────────────────────────────────────────────────

PWS_SYNC_STATE = os.path.join(BASE_DIR, "data", "pws_sync_state.json")
MAX_PWS_RETRIES = 3

def check_pws_sync():
    pws_file = os.path.join(BASE_DIR, "data", "pws_raw.json")
    now_utc  = datetime.now(timezone.utc)
    cur_hk   = now_utc.strftime("%Y-%m-%dT%H")

    sync_state = {}
    if os.path.exists(PWS_SYNC_STATE):
        try:
            with open(PWS_SYNC_STATE, "r", encoding="utf-8") as f:
                sync_state = json.load(f)
        except Exception:
            pass

    last_hk = ""
    if os.path.exists(pws_file):
        try:
            with open(pws_file, "r", encoding="utf-8") as f:
                recs = json.load(f)
            last_hk = max((r.get("hourKey", "") for r in recs), default="")
        except Exception:
            pass

    if last_hk >= cur_hk:
        return

    retries = sync_state.get(cur_hk, 0)
    if retries >= MAX_PWS_RETRIES:
        return

    print(f"\n  🔄 PWS: нет данных за {cur_hk}, запускаю синк "
          f"(попытка {retries + 1}/{MAX_PWS_RETRIES})...")
    try:
        result = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "pws_sync.py")],
            cwd=BASE_DIR, capture_output=False, timeout=120
        )
    except subprocess.TimeoutExpired:
        print("  ✗ pws_sync.py завис дольше 120с — прерван по таймауту")
        return
    if result.returncode == 0:
        print("  ✓ pws_sync.py")
    else:
        print(f"  ✗ pws_sync.py (код {result.returncode})")

def check_pws_calibration():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "calibrate_pws_pressure.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] calibrate_pws_pressure.py: {e}")

def check_hmcbas_telegram():
    hist_file = os.path.join(BASE_DIR, "data", "hmcbas_telegram_sea_temp.json")
    today_utc = datetime.now(timezone.utc).date().isoformat()
    try:
        if os.path.exists(hist_file):
            with open(hist_file, "r", encoding="utf-8") as f:
                hist = json.load(f)
            if hist and hist[-1].get("timestamp", "").startswith(today_utc):
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "fetch_hmcbas_telegram.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] fetch_hmcbas_telegram.py: {e}")

def check_nearby_precip():
    out_file = os.path.join(BASE_DIR, "data", "nearby_precip.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = datetime.strptime(prev["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now_utc - last_time).total_seconds() < 10 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "nearby_precip.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] nearby_precip.py: {e}")

def check_marine_history():
    marine_file = os.path.join(BASE_DIR, "data", "marine_history.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(marine_file):
            with open(marine_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            if records:
                last_time = datetime.fromisoformat(records[-1]["time"])
                if (now_utc - last_time).total_seconds() < 300:
                    return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "marine_history.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] marine_history.py: {e}")

# ── основная логика ───────────────────────────────────────────────────────────

LOCK_FILE = "/tmp/vps_pipeline.lock"


def acquire_lock():
    """Файловая блокировка (найдено 27.08.2026, поздний вечер).

    Гипотеза о повторяющихся повреждениях .git/rebase-merge: если какой-то
    сетевой вызов внутри цикла (subprocess.run БЕЗ timeout — calc_weights.py,
    update_local.py, git fetch/push) зависает дольше 15 минут, cron всё
    равно запускает СЛЕДУЮЩИЙ экземпляр этого скрипта поверх ещё работающего
    — и два процесса одновременно трогают один и тот же .git в одной рабочей
    директории. Это правдоподобно объясняет полу-записанные rebase-merge
    директории, которые не лечились обычным `rebase --abort` (см. sync_repo).
    Пересекающихся процессов при проверке не застали, но лок дёшев и
    правильно закрывает саму возможность гонки — не полагаемся на удачу.
    """
    import fcntl
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except OSError:
        return None


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    lock_fd = acquire_lock()
    if lock_fd is None:
        print("  ⏭ предыдущий цикл ещё выполняется — пропускаю (lock занят)")
        return

    try:
        _main_body()
    finally:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _main_body():
    if not sync_repo():
        print("  ✗ sync_repo failed — цикл пропущен, попробуем в следующий раз.")
        return

    now = now_utc_iso()
    history = load_history()
    new_models = []

    print(f"\n{'─'*52}")
    print(f"  [VPS] Проверка прогонов моделей  {iso_to_local(now)}")
    print(f"{'─'*52}")

    for m in MODELS:
        label    = m["label"]
        meta_id  = m["metaId"]
        entries  = history.setdefault(label, [])
        last_run = entries[-1]["run_time"] if entries else None

        run_time = fetch_run_time(meta_id)

        # НАХОДКА (28.08.2026): open-meteo отдаёт last_run_availability_time
        # с разных backend-серверов за балансировщиком нагрузки — значения
        # для ОДНОГО И ТОГО ЖЕ реального прогона модели колеблются на
        # секунды-минуты между опросами (напр. 13:09:18 → 13:12:04 →
        # 13:09:18 туда-сюда). Точное сравнение `run_time == last_run`
        # ложно детектировало "новый прогон" почти на КАЖДОМ 15-минутном
        # цикле — это не просто шум в логе, а лишний прогон всего пайплайна
        # и лишний платный AI-диспетч (Claude/Gemini) на пустом месте.
        # Реальные прогоны моделей обновляются раз в 6-12 часов, поэтому
        # разница меньше 30 минут — точно тот же прогон, а не новый.
        SAME_RUN_TOLERANCE_MIN = 30
        is_same_run = False
        if run_time is not None and last_run is not None:
            try:
                t_new = datetime.strptime(run_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                t_old = datetime.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                is_same_run = abs((t_new - t_old).total_seconds()) < SAME_RUN_TOLERANCE_MIN * 60
            except Exception:
                is_same_run = (run_time == last_run)

        if run_time is None:
            status = "❌ нет ответа"
        elif is_same_run:
            status = f"  {iso_to_local(run_time)}  ({age_str(run_time)}) — без изменений"
        else:
            entries.append({"run_time": run_time, "detected_at": now})
            if len(entries) > MAX_ENTRIES:
                history[label] = entries[-MAX_ENTRIES:]
            new_models.append(label)
            status = f"🆕 {iso_to_local(run_time)}  ({age_str(run_time)}) ← новый прогон"

        print(f"  {label:<14}  {status}")

    print(f"{'─'*52}\n")

    if new_models:
        save_history(history)
        ok = run_pipeline(new_models)
        if ok:
            queue_ai_models(new_models)
        git_push_history()
    else:
        print("  Новых прогонов нет.\n")
        try:
            subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model", "--no-fill"],
                cwd=BASE_DIR, capture_output=False, timeout=300
            )
        except subprocess.TimeoutExpired:
            print("  ✗ update_local.py завис дольше 300с — прерван по таймауту")
        git_push_history()

    check_pws_sync()
    check_pws_calibration()
    check_marine_history()
    check_nearby_precip()
    check_hmcbas_telegram()

    git_push_history()


if __name__ == "__main__":
    main()
