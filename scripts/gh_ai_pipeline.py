#!/usr/bin/env python3
"""
gh_ai_pipeline.py — независимый цикл AI-анализа прогноза (Claude + Gemini).

Вынесен из scripts/gh_pipeline.py 2026-08-20: AI-блок (обращения к Claude/
Gemini API, TTS-озвучка, сборка видео) утяжелял и удлинял основной пайплайн
verification+PWS — по прямой аналогии с выносом спутникового модуля
2026-07-26 (см. scripts/gh_satellite_pipeline.py, тот же паттерн).

Теперь это отдельный workflow (ai_pipeline.yml), запускается явным
workflow_dispatch-диспетчем из последнего шага full_pipeline.yml — тем же
паттерном (guard на in_progress/queued, debug-коммит ответа), каким
full_pipeline.yml раньше (до 2026-08-20) диспетчил satellite_pipeline.yml.

Ключевое отличие от спутникового модуля: check_eumetsat_*() там полностью
самодостаточны (сами решают по времени, нужна ли работа). AI-блок же
управлялся переменной new_models, вычисленной ВЫШЕ по main() в
gh_pipeline.py, и запускался ТОЛЬКО если run_pipeline(new_models)
(calc_model_bias_cloud/calc_weights/update_local) отработал успешно —
реальная зависимость по данным, не по времени (generate_ai_analysis.py
читает то, что эти три скрипта посчитали).

Чтобы не терять эту зависимость при развязке на два независимых workflow,
gh_pipeline.py сам пишет очередь data/_ai_pending_models.json — и ТОЛЬКО
когда run_pipeline() вернул ok=True. Этот скрипт очередь только читает и
опустошает; сам её не наполняет и НЕ смотрит в data/model_runs_history.json
напрямую (это был первоначальный план — сравнивать историю моделей с
отдельным маркером "что уже проанализировано", см. план в
docs/topics/main_pipeline.md от 2026-08-18) — вариант с готовой очередью от
gh_pipeline.py проще (один маленький файл вместо пересчёта диффа истории
на каждый цикл) и гарантированно сохраняет исходную зависимость от успеха
run_pipeline(), а не только от факта нового прогона модели.

Отдельно, независимо от очереди — если предыдущий вызов Gemini упёрся в
rate-limit (data/forecast_analysis_gemini.json.pending == true), этот
скрипт сам обнаруживает и повторяет попытку каждый цикл — та же логика,
что раньше жила в ветке "новых прогонов нет" в gh_pipeline.py.
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


# ── очередь новых моделей (пишет gh_pipeline.py, этот файл — читает/опустошает) ──

def check_ai_new_models(force=False):
    """Обрабатывает очередь новых прогонов, ожидающих AI-анализа.
    Очередь наполняет ТОЛЬКО gh_pipeline.py, и только после успешного
    run_pipeline() — см. докстринг файла. Этот скрипт её не наполняет,
    только читает и опустошает после успешной обработки."""
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
    ai_result = subprocess.run(ai_cmd, cwd=BASE_DIR, capture_output=False)

    if ai_result.returncode != 0:
        print("  ✗ generate_ai_analysis.py завершился с ошибкой — очередь оставлена для повтора в следующем цикле")
        return

    # Claude: если анализ изменился — собираем аудио-блоки. Видео для Claude
    # НЕ вызываем здесь: make_video.yml триггерится push'ом по пути
    # data/blocks/blocks_meta.json и data/blocks/*.mp3 (см. этот workflow) —
    # git_push_ai() ниже сделает этот push сам, как раньше делал
    # git_push_history() из gh_pipeline.py. Поведение не меняется, просто
    # push теперь идёт из этого job'а.
    claude_file = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
    claude_changed = False
    try:
        with open(claude_file, encoding="utf-8") as f:
            claude_changed = json.load(f).get("changed", False)
    except Exception:
        pass
    if claude_changed:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_cloud.py")],
            cwd=BASE_DIR, capture_output=False
        )

    # Gemini: если анализ изменился — блоки И видео (для Gemini отдельного
    # push-триггерного workflow нет, вызываем прямо здесь — как и раньше
    # в gh_pipeline.py, без изменений в этой части).
    gemini_file = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
    gemini_changed = False
    try:
        with open(gemini_file, encoding="utf-8") as f:
            gemini_changed = json.load(f).get("changed", False)
    except Exception:
        pass
    if gemini_changed:
        blocks_result = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
            cwd=BASE_DIR, capture_output=False
        )
        if blocks_result.returncode != 0:
            print("  [AI-Gemini] make_blocks_gemini_cloud.py упал")
        else:
            video_result = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                cwd=BASE_DIR, capture_output=False
            )
            if video_result.returncode != 0:
                print("  [AI-Gemini] make_video.py (gemini) упал")

    # успех — очередь опустошаем (та же state-машина через файл, что
    # just_triggered у eumetsat_alert_state.json в спутниковом пайплайне)
    try:
        with open(AI_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": [], "queued_at": None}, f, ensure_ascii=False, indent=2)
        print("  ✓ очередь AI обработана и очищена")
    except Exception as e:
        print(f"  [WARN] не удалось очистить очередь AI: {e}")


# ── повтор Gemini при pending (rate-limit) — самодостаточная проверка ────────

def check_ai_gemini_pending():
    """Если предыдущий вызов Gemini упёрся в rate-limit — повторяем,
    независимо от очереди новых моделей выше. Та же логика, что раньше
    жила в ветке "новых прогонов нет" в gh_pipeline.py."""
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
    gr = subprocess.run(
        [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py"), "--force-gemini"],
        cwd=BASE_DIR, capture_output=False
    )
    if gr.returncode != 0:
        return
    try:
        with open(gemini_file, encoding="utf-8") as f:
            gd2 = json.load(f)
        if gd2.get("changed") and not gd2.get("pending"):
            blocks_r = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
                cwd=BASE_DIR, capture_output=False
            )
            if blocks_r.returncode == 0:
                subprocess.run(
                    [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                    cwd=BASE_DIR, capture_output=False
                )
    except Exception:
        pass


# ── git (без форса и без лока — единственный писатель в облаке) ──────────────

def git_push_ai():
    """Коммитит и пушит только файлы AI-модуля."""
    try:
        _candidates = [
            "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
            "data/blocks",
            "data/forecast_analysis_gemini.json", "data/forecast_analysis_gemini.mp3",
            "data/blocks_gemini",
            "data/ai_schedule.json",
            "data/ai_schedule_gemini.json",
            "data/forecast_video.mp4",
            "data/forecast_video_gemini.mp4",
            "data/_ai_pending_models.json",
        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        if not _to_add:
            print("  Нет файлов для коммита.")
            return
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                        check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", "ai: forecast analysis + blocks + video update"],
            capture_output=True, text=True)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")
                return

        _delays = [10, 20]
        for _attempt in range(3):
            push = subprocess.run(["git", "-C", BASE_DIR, "push"], capture_output=True, text=True)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  ai push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  ai push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"], capture_output=True)
                subprocess.run(["git", "-C", BASE_DIR, "rebase", "origin/main"], capture_output=True)
        print("  ai push failed after 3 attempts")
    except Exception as e:
        print(f"  ai git error: {e}")


# ── основная логика ───────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                         help="передать --force в generate_ai_analysis.py (в обход расписания ai_schedule.json)")
    args, _ = parser.parse_known_args()

    print(f"\n{'─'*52}")
    print(f"  [AI] Цикл AI-анализа  {datetime.now(timezone.utc).strftime('%d.%m %H:%M UTC')}")
    print(f"{'─'*52}")

    check_ai_new_models(force=args.force)
    check_ai_gemini_pending()

    git_push_ai()


if __name__ == "__main__":
    main()
