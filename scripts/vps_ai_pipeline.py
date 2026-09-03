#!/usr/bin/env python3
"""
vps_ai_pipeline.py — VPS-версия независимого цикла AI-анализа прогноза
(Claude + Gemini). Портирован из scripts/gh_ai_pipeline.py (31.08.2026) по
той же схеме, что и scripts/vps_satellite_pipeline.py (29.08.2026): логика
шагов не меняется, но добавляются VPS-специфичные защиты от гонок git,
накопленные за 27-29.08.2026 (см. docs/topics/hosting_migration.md).

Почему отдельный файл и отдельный cron, а не слияние в vps_pipeline.py:
AI-блок может идти существенно дольше основного цикла (два LLM API,
edge-tts озвучка, ffmpeg рендер видео) — жёстко привязывать его к
5-минутному такту verification+PWS означало бы либо резать таймауты
слишком туго, либо периодически блокировать основной цикл. Тот же
аргумент уже применили к спутниковому модулю.

Источник очереди — data/_ai_pending_models.json, которую пишет
queue_ai_models() в vps_pipeline.py (после успешного run_pipeline()).
Этот скрипт очередь только читает и опустошает, сам не наполняет
(инвариант сохранён от оригинала).

Раньше диспетч шёл через GitHub Actions (dispatch_ai_pipeline() в
vps_pipeline.py, workflow_dispatch на ai_pipeline.yml). После того как
этот скрипт встал на собственный cron на VPS — диспетч больше не нужен,
очередь подхватывается напрямую в пределах нескольких минут.
"""

import json
import os
import subprocess
import sys
import time as _time
from datetime import datetime, timezone

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
PYTHON      = sys.executable

AI_QUEUE_FILE = os.path.join(BASE_DIR, "data", "_ai_pending_models.json")


# ── sync_repo() — идентичен vps_pipeline.py/vps_satellite_pipeline.py ───────
# (см. docs/topics/hosting_migration.md, серия detached-HEAD патчей
# 27-28.08.2026: checkout -B вместо reset --hard, чистка rebase-merge/
# *.lock мусора ДО checkout, dropped stash). Продублирован, а не
# импортирован — тот же паттерн, что уже выбран для спутникового модуля,
# чтобы каждый VPS-скрипт оставался независимым и самодостаточным.

def sync_repo():
    try:
        subprocess.run(["git", "-C", BASE_DIR, "rebase", "--abort"],
                        capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", BASE_DIR, "merge", "--abort"],
                        capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", BASE_DIR, "cherry-pick", "--abort"],
                        capture_output=True, text=True, timeout=15)

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
        for _lockname in ("shallow.lock", "index.lock", "HEAD.lock", "config.lock"):
            _p = os.path.join(BASE_DIR, ".git", _lockname)
            if os.path.isfile(_p):
                try:
                    os.remove(_p)
                    print(f"  [WARN] удалён зависший .git/{_lockname}")
                except OSError:
                    pass

        subprocess.run(["git", "-C", BASE_DIR, "reset", "--hard", "HEAD"],
                        capture_output=True, text=True, timeout=15)

        fetch = subprocess.run(
            ["git", "-C", BASE_DIR, "fetch", "origin", "main", "--depth", "1", "--update-shallow"],
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

        stash_list = subprocess.run(
            ["git", "-C", BASE_DIR, "stash", "list"],
            capture_output=True, text=True, timeout=10)
        if stash_list.stdout.strip():
            n = len(stash_list.stdout.strip().splitlines())
            subprocess.run(["git", "-C", BASE_DIR, "stash", "clear"],
                            capture_output=True, text=True, timeout=10)
            print(f"  [WARN] очищено {n} осиротевших stash-записей")

        print("  ✓ repo synced with origin/main")
        return True
    except Exception as e:
        print(f"  [WARN] sync_repo error: {e}")
        return False


# ── общий git-lock с vps_pipeline.py/vps_satellite_pipeline.py ─────────────
# Три независимых cron-процесса пишут в один .git — лок оборачивает ТОЛЬКО
# секцию add/commit/push (секунды), не весь цикл.

GIT_LOCK_FILE = "/tmp/vps_git.lock"
GIT_LOCK_TIMEOUT_SEC = 60


def acquire_git_lock():
    import fcntl
    lock_fd = open(GIT_LOCK_FILE, "w")
    waited = 0
    while waited < GIT_LOCK_TIMEOUT_SEC:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_fd
        except OSError:
            _time.sleep(1)
            waited += 1
    print(f"  [WARN] git-lock не получен за {GIT_LOCK_TIMEOUT_SEC}с — "
          f"продолжаю без него (второй писатель, возможна гонка)")
    lock_fd.close()
    return None


def release_git_lock(lock_fd):
    if lock_fd is None:
        return
    import fcntl
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        lock_fd.close()


# ── очередь новых моделей (пишет vps_pipeline.py, этот файл читает/опустошает) ──

def check_ai_new_models(force=False):
    if not os.path.exists(AI_QUEUE_FILE):
        return
    try:
        with open(AI_QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
    except Exception as e:
        print(f"  [WARN] не удалось прочитать очередь AI: {e}")
        return

    models = queue.get("models", [])
    if not models:
        return

    print(f"\n  🤖 AI: в очереди {len(models)} новых прогонов ({', '.join(models)})")
    print(  "     Запускаю generate_ai_analysis.py...\n")

    ai_cmd = [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py")]
    if force:
        ai_cmd.append("--force")
    ai_cmd += ["--models", ",".join(models)]
    try:
        ai_result = subprocess.run(ai_cmd, cwd=BASE_DIR, capture_output=False, timeout=280)
    except subprocess.TimeoutExpired:
        print("  ✗ generate_ai_analysis.py завис дольше 280с — прерван, очередь оставлена для повтора")
        return

    if ai_result.returncode != 0:
        print("  ✗ generate_ai_analysis.py завершился с ошибкой — очередь оставлена для повтора в следующем цикле")
        return

    claude_file = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
    claude_changed = False
    try:
        with open(claude_file, encoding="utf-8") as f:
            claude_changed = json.load(f).get("changed", False)
    except Exception:
        pass

    gemini_file = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
    gemini_changed = False
    try:
        with open(gemini_file, encoding="utf-8") as f:
            gemini_changed = json.load(f).get("changed", False)
    except Exception:
        pass

    # 01.09.2026: коммитим и пушим свежий текст СРАЗУ, до make_blocks/make_video
    # (которые вместе могут идти ~10+ минут — дольше 5-минутного такта соседних
    # cron-скриптов). Иначе их sync_repo() успевает откатить ещё не запушенный
    # forecast_analysis_*.json обратно к origin/main раньше, чем дойдёт очередь
    # до git_push_ai() в конце этой функции — см. ANALYSIS_PATHS/MEDIA_PATHS.
    if claude_changed or gemini_changed:
        git_push_ai(paths=ANALYSIS_PATHS)

    if claude_changed:
        try:
            blocks_result = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_cloud.py")],
                cwd=BASE_DIR, capture_output=False, timeout=180
            )
        except subprocess.TimeoutExpired:
            print("  [WARN] make_blocks_cloud.py завис дольше 180с — прерван")
            blocks_result = None
        if blocks_result is not None and blocks_result.returncode == 0:
            # 02.09.2026: пушим свежие блоки СРАЗУ, до make_video (который может
            # идти ~600-700с — дольше 5-минутного такта соседних cron-скриптов).
            # Иначе их sync_repo() (reset --hard HEAD БЕЗ git-лока — см.
            # GIT_LOCK_FILE) успевает откатить только что записанные, но ещё не
            # закоммиченные mp3 обратно к origin/main раньше, чем дойдёт очередь
            # до git_push_ai(MEDIA_PATHS) в конце этой функции. Видео при этом
            # выживало, т.к. дописывается на диск последним — отсюда баг
            # "текст и видео обновляются, озвучка блоков стоит на месте".
            git_push_ai(paths=BLOCKS_CLAUDE_PATHS)
            try:
                video_result = subprocess.run(
                    [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py")],
                    cwd=BASE_DIR, capture_output=False, timeout=700
                )
                if video_result.returncode != 0:
                    print("  [WARN] make_video.py (claude) упал")
            except subprocess.TimeoutExpired:
                print("  [WARN] make_video.py завис дольше 700с — прерван")

    if gemini_changed:
        try:
            blocks_result = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
                cwd=BASE_DIR, capture_output=False, timeout=180
            )
        except subprocess.TimeoutExpired:
            print("  [AI-Gemini] make_blocks_gemini_cloud.py завис дольше 180с — прерван")
            blocks_result = None
        if blocks_result is not None:
            if blocks_result.returncode != 0:
                print("  [AI-Gemini] make_blocks_gemini_cloud.py упал")
            else:
                # 02.09.2026: тот же ранний push, что и для claude-веток выше —
                # см. комментарий там же. Без этого data/blocks_gemini годами
                # стоял на дате последнего успешного окна без гонки (было
                # 29.08 при ежедневно обновляющемся forecast_video_gemini.mp4).
                git_push_ai(paths=BLOCKS_GEMINI_PATHS)
                try:
                    # 700с — с запасом от реально измеренных ~592с на этом ARM VPS
                    # (было 240с — гарантированно убивало рендер на середине).
                    video_result = subprocess.run(
                        [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                        cwd=BASE_DIR, capture_output=False, timeout=700
                    )
                    if video_result.returncode != 0:
                        print("  [AI-Gemini] make_video.py (gemini) упал")
                except subprocess.TimeoutExpired:
                    print("  [AI-Gemini] make_video.py завис дольше 700с — прерван")

    try:
        with open(AI_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": [], "queued_at": None}, f, ensure_ascii=False, indent=2)
        print("  ✓ очередь AI обработана и очищена")
    except Exception as e:
        print(f"  [WARN] не удалось очистить очередь AI: {e}")


# ── повтор Gemini при pending (rate-limit) ──────────────────────────────────

def check_ai_gemini_pending():
    gemini_file = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
    if not os.path.exists(gemini_file):
        return
    try:
        with open(gemini_file, encoding="utf-8") as f:
            gd = json.load(f)
    except Exception:
        return
    if not gd.get("pending", False):
        return

    print("\n  [AI-Gemini] Найден pending — повторная попытка Gemini...")
    try:
        gr = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py"), "--force-gemini"],
            cwd=BASE_DIR, capture_output=False, timeout=280
        )
    except subprocess.TimeoutExpired:
        print("  [AI-Gemini] retry завис дольше 280с — прерван")
        return
    if gr.returncode != 0:
        return
    try:
        with open(gemini_file, encoding="utf-8") as f:
            gd2 = json.load(f)
        if gd2.get("changed") and not gd2.get("pending"):
            # 01.09.2026: тот же ранний push текста, что и в check_ai_new_models()
            # — иначе следующий cron-тик (main/satellite) может откатить его
            # sync_repo()'ом раньше, чем дойдёт очередь до git_push_ai() в конце.
            git_push_ai(paths=ANALYSIS_PATHS)
            try:
                blocks_r = subprocess.run(
                    [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
                    cwd=BASE_DIR, capture_output=False, timeout=180
                )
            except subprocess.TimeoutExpired:
                print("  [AI-Gemini] retry: make_blocks_gemini_cloud.py завис дольше 180с — прерван")
                blocks_r = None
            if blocks_r is not None and blocks_r.returncode == 0:
                # 02.09.2026: тот же ранний push блоков, что и в check_ai_new_models().
                git_push_ai(paths=BLOCKS_GEMINI_PATHS)
                try:
                    subprocess.run(
                        [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                        cwd=BASE_DIR, capture_output=False, timeout=700
                    )
                except subprocess.TimeoutExpired:
                    print("  [AI-Gemini] retry: make_video.py завис дольше 700с — прерван")
    except Exception:
        pass


# ── git push (общий лок, самолечение, dynamic commit message) ──────────────

# Полный список кандидатов на коммит. 01.09.2026: разбит на два подмножества
# (см. ANALYSIS_PATHS/MEDIA_PATHS ниже) после обнаружения гонки: рендер
# видео идёт до ~600с (реально измерено), это дольше 5-минутного такта
# vps_pipeline.py/vps_satellite_pipeline.py — их sync_repo() успевает
# сделать git reset --hard HEAD + checkout -B ПОКА AI-цикл ещё не
# закоммитил свежий текстовый анализ, откатывая его обратно к состоянию
# origin/main. Блоки/видео при этом выживают (дописываются на диск уже
# ПОСЛЕ отката), а вот forecast_analysis_*.json — нет: он писался в
# начале цикла и был единственным, что успевало попасть под откат.
# Поэтому текст теперь коммитится и пушится СРАЗУ после генерации,
# отдельным вызовом, до старта make_blocks/make_video.
ANALYSIS_PATHS = [
    "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
    "data/forecast_analysis_gemini.json", "data/forecast_analysis_gemini.mp3",
    "data/ai_schedule.json", "data/ai_schedule_gemini.json",
]
MEDIA_PATHS = [
    "data/blocks",
    "data/blocks_gemini",
    "data/forecast_video.mp4",
    "data/forecast_video_gemini.mp4",
    "data/_ai_pending_models.json",
]
# 02.09.2026: подмножества MEDIA_PATHS для раннего push блоков сразу после
# генерации, до старта долгого make_video.py — см. комментарии в
# check_ai_new_models()/check_ai_gemini_pending().
BLOCKS_CLAUDE_PATHS = ["data/blocks"]
BLOCKS_GEMINI_PATHS = ["data/blocks_gemini"]


def git_push_ai(paths=None):
    lock_fd = acquire_git_lock()
    try:
        _candidates = paths if paths is not None else (ANALYSIS_PATHS + MEDIA_PATHS)
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        if not _to_add:
            print("  Нет файлов для коммита.")
            return
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                        check=True, capture_output=True, timeout=30)

        status = subprocess.run(
            ["git", "-C", BASE_DIR, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=15)
        _changed = [
            os.path.splitext(os.path.basename(p))[0]
            for p in status.stdout.strip().splitlines() if p.strip()
        ]
        commit_msg = "vps ai: " + ", ".join(_changed) if _changed else "vps ai: forecast analysis update"
        if len(commit_msg) > 200:
            commit_msg = commit_msg[:197] + "..."

        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", commit_msg],
            capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")
                return

        _delays = [10, 20]
        for _attempt in range(3):
            push = subprocess.run(["git", "-C", BASE_DIR, "push"],
                                   capture_output=True, text=True, timeout=60)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  ai push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  ai push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"],
                                capture_output=True, timeout=60)
                rebase = subprocess.run(
                    ["git", "-C", BASE_DIR, "rebase", "-X", "theirs", "origin/main"],
                    capture_output=True, text=True, timeout=60)
                if rebase.returncode != 0:
                    print(f"  [WARN] rebase -X theirs не прошёл: "
                          f"{rebase.stderr.strip()[:200]} — abort+reset")
                    subprocess.run(["git", "-C", BASE_DIR, "rebase", "--abort"],
                                    capture_output=True, timeout=15)
                    subprocess.run(
                        ["git", "-C", BASE_DIR, "checkout", "-B", "main", "origin/main"],
                        capture_output=True, timeout=30)
        print("  ai push failed after 3 attempts")
    except subprocess.TimeoutExpired as e:
        print(f"  ai git timeout: {e}")
    except Exception as e:
        print(f"  ai git error: {e}")
    finally:
        release_git_lock(lock_fd)


# ── процесс-лок (self-collision, отдельно от других VPS-скриптов) ──────────

LOCK_FILE = "/tmp/vps_ai_pipeline.lock"


def acquire_process_lock():
    import fcntl
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except OSError:
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                         help="передать --force в generate_ai_analysis.py (в обход расписания ai_schedule.json)")
    args, _ = parser.parse_known_args()

    lock_fd = acquire_process_lock()
    if lock_fd is None:
        print("  ⏭ предыдущий цикл AI ещё выполняется — пропуск")
        return

    _t0 = _time.time()
    try:
        print(f"\n{'─'*52}")
        print(f"  [AI-VPS] Цикл AI-анализа  {datetime.now(timezone.utc).strftime('%d.%m %H:%M UTC')}")
        print(f"{'─'*52}")

        if not sync_repo():
            print("  ⏭ sync_repo не удался — цикл пропущен")
            return

        check_ai_new_models(force=args.force)
        check_ai_gemini_pending()
        git_push_ai()
    finally:
        _dt = _time.time() - _t0
        print(f"\n  ⏱ [ai] цикл занял {_dt:.1f}с")
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
