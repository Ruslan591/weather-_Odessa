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
    раньше. Дополнительно чистим осиротевшие stash-записи на старте цикла —
    they can't collide with anything since reset выполняется до самого
    начала работы скрипта.
    """
    try:
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
            print(f"  [WARN] git checkout -B main failed: {checkout.stderr.strip()}")
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

def git_push_history():
    import time as _time
    try:
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
                      check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", "vps: synop + history update"],
            capture_output=True, text=True)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")

        _delays = [10, 20]
        for _attempt in range(3):
            push = subprocess.run(
                ["git", "-C", BASE_DIR, "push"],
                capture_output=True, text=True)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  history push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  history push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"],
                               capture_output=True)
                subprocess.run(["git", "-C", BASE_DIR, "rebase", "origin/main"],
                               capture_output=True)
        print("  history push failed after 3 attempts")
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
        result = subprocess.run(step["cmd"], cwd=BASE_DIR, capture_output=False)
        if result.returncode != 0:
            print(f"  ✗ {step['name']} завершился с ошибкой (код {result.returncode})")
            print(  "    Пайплайн остановлен.")
            return False
        print(f"  ✓ {step['name']}\n")

    print("  ✅ Пайплайн завершён успешно.")
    return True


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
    result = subprocess.run(
        [PYTHON, os.path.join(SCRIPTS_DIR, "pws_sync.py")],
        cwd=BASE_DIR, capture_output=False
    )
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

def main():
    os.makedirs(LOG_DIR, exist_ok=True)

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

        if run_time is None:
            status = "❌ нет ответа"
        elif run_time == last_run:
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
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model", "--no-fill"],
            cwd=BASE_DIR, capture_output=False
        )
        git_push_history()

    check_pws_sync()
    check_pws_calibration()
    check_marine_history()
    check_nearby_precip()
    check_hmcbas_telegram()

    git_push_history()


if __name__ == "__main__":
    main()
