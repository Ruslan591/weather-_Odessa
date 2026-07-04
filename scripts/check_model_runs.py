#!/usr/bin/env python3
"""
check_model_runs.py — опрос open-meteo на наличие новых прогонов моделей.
При обнаружении нового прогона запускает пайплайн:
  1. calc_model_bias.py
  2. LOCAL=1 calc_weights.py
  3. update_local.py --snap-only  (снимок + git push)

История сохраняется в data/model_runs_history.json.

Расписание через termux-job-scheduler (~/run_check.sh):
    termux-job-scheduler --script ~/run_check.sh --period-ms 900000
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

# ── конфиг ────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "model_runs_history.json")
LOG_DIR      = os.path.join(BASE_DIR, "logs")
MAX_ENTRIES  = 60

PYTHON       = sys.executable   # тот же python3 что запустил этот скрипт
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

# ── пайплайн ──────────────────────────────────────────────────────────────────

def git_push_history():
    import time as _time
    try:
        year = datetime.now(timezone.utc).year
        _candidates = [
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/model_weights.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/forecast_video.mp4", "data/forecast_voice.mp3",
                        "data/blocks",
                        "data/forecast_analysis_gemini.json", "data/forecast_analysis_gemini.mp3",
                        "data/blocks_gemini",
                        "data/ai_schedule.json",
                        "data/sst_compare.json",
                        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                      check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", "data: synop + history update"],
            capture_output=True, text=True)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")
        # push with retry (3 attempts, delays 15s/30s)
        _delays = [15, 30]
        for _attempt in range(3):
            push = subprocess.run(
                ["bash", os.path.join(BASE_DIR, "scripts", "git_push_locked.sh"), BASE_DIR],
                capture_output=True, text=True)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  history push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  history push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                # resync ref before retry
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"],
                               capture_output=True)
        print("  history push failed after 3 attempts")
    except Exception as e:
        print(f"  history git error: {e}")

def run_pipeline(new_models):
    """Запускает calc_model_bias → calc_weights → update_local --snap-only."""
    print(f"\n  🚀 Новых прогонов: {len(new_models)} ({', '.join(new_models)})")
    print(  "     Запускаю пайплайн...\n")

    steps = [
        {
            "name": "calc_model_bias.py",
            "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_model_bias.py")],
            "env":  None,
        },
        {
            "name": "calc_weights.py (LOCAL)",
            "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_weights.py")],
            "env":  {**os.environ, "LOCAL": "1"},
        },
        {
            "name": "update_local.py --no-model",
            "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model"],
            "env":  None,
        },
    ]

    for step in steps:
        print(f"  ▶ {step['name']}")
        result = subprocess.run(
            step["cmd"],
            cwd=BASE_DIR,
            env=step["env"],
            capture_output=False,   # вывод идёт прямо в лог
        )
        if result.returncode != 0:
            print(f"  ✗ {step['name']} завершился с ошибкой (код {result.returncode})")
            print(  "    Пайплайн остановлен.")
            return False

        print(f"  ✓ {step['name']}\n")

    print("  ✅ Пайплайн завершён успешно.")
    return True

# ── PWS-синк ─────────────────────────────────────────────────────────────────

PWS_SYNC_STATE = os.path.join(BASE_DIR, "data", "pws_sync_state.json")
MAX_PWS_RETRIES = 3   # после 3 неудачных попыток час считается пустым

def check_pws_sync():
    pws_file = os.path.join(BASE_DIR, "data", "pws_raw.json")
    now_utc  = datetime.now(timezone.utc)
    cur_hk   = now_utc.strftime("%Y-%m-%dT%H")

    # Читаем состояние (счётчики попыток)
    sync_state = {}
    if os.path.exists(PWS_SYNC_STATE):
        try:
            with open(PWS_SYNC_STATE, "r", encoding="utf-8") as f:
                sync_state = json.load(f)
        except Exception:
            pass

    # Проверяем актуальность данных
    last_hk = ""
    if os.path.exists(pws_file):
        try:
            with open(pws_file, "r", encoding="utf-8") as f:
                recs = json.load(f)
            last_hk = max((r.get("hourKey", "") for r in recs), default="")
        except Exception:
            pass

    if last_hk >= cur_hk:
        return  # данные актуальны

    # Проверяем лимит попыток для cur_hk (станция могла быть офлайн)
    retries = sync_state.get(cur_hk, 0)
    if retries >= MAX_PWS_RETRIES:
        return  # тихо пропускаем

    print(f"\n  🔄 PWS: нет данных за {cur_hk}, запускаю синк "
          f"(попытка {retries + 1}/{MAX_PWS_RETRIES})...")
    result = subprocess.run(
        [PYTHON, os.path.join(SCRIPTS_DIR, "pws_sync_local.py")],
        cwd=BASE_DIR, capture_output=False
    )
    if result.returncode == 0:
        print("  ✓ pws_sync_local.py")
    else:
        print(f"  ✗ pws_sync_local.py (код {result.returncode})")

    # Проверяем, появились ли данные после синка
    try:
        with open(pws_file, "r", encoding="utf-8") as f:
            recs = json.load(f)
        new_last_hk = max((r.get("hourKey", "") for r in recs), default="")
    except Exception:
        new_last_hk = last_hk

    if new_last_hk < cur_hk:
        # Данных нет — станция была офлайн, увеличиваем счётчик
        sync_state[cur_hk] = retries + 1
        cutoff = (now_utc - timedelta(hours=48)).strftime("%Y-%m-%dT%H")
        sync_state = {k: v for k, v in sync_state.items() if k >= cutoff}
        try:
            with open(PWS_SYNC_STATE, "w", encoding="utf-8") as f:
                json.dump(sync_state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [WARN] sync_state: {e}")

def check_pws_calibration():
    """Автокалибровка pressureOffset PWS-станций по SYNOP/BUFR (±30 мин)."""
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "calibrate_pws_pressure.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] calibrate_pws_pressure.py: {e}")

def check_sst_compare():
    """Раз в час обновляет сравнение источников температуры воды (data/sst_compare.json)."""
    sst_file = os.path.join(BASE_DIR, "data", "sst_compare.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(sst_file):
            with open(sst_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            if records:
                last_time = datetime.fromisoformat(records[-1]["time"])
                if (now_utc - last_time).total_seconds() < 3600:
                    return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "sst_compare.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] sst_compare.py: {e}")

# ── основная логика ───────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-ai", action="store_true")
    args, _ = parser.parse_known_args()
    os.makedirs(LOG_DIR, exist_ok=True)
    now = now_utc_iso()
    history = load_history()
    new_models = []   # модели с новым прогоном

    print(f"\n{'─'*52}")
    print(f"  Проверка прогонов моделей  {iso_to_local(now)}")
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
            ai_cmd = [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py")]
            if args.force_ai:
                ai_cmd.append("--force")
            ai_cmd += ["--models", ",".join(new_models)]
            ai_result = subprocess.run(ai_cmd, cwd=BASE_DIR, capture_output=False)
            if ai_result.returncode == 0:
                import json, os as _os
                _ai_file = _os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
                _ai_changed = False
                try:
                    with open(_ai_file, encoding="utf-8") as _f:
                        _ai_changed = json.load(_f).get("changed", False)
                except Exception:
                    pass
                if _ai_changed:
                    _pending_file = _os.path.join(BASE_DIR, "data", "blocks", "pending_video.json")
                    _blocks_result = subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_blocks.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    if _blocks_result.returncode == 0:
                        # make_video отключён
                        if _os.path.exists(_pending_file):
                            _os.remove(_pending_file)
                    else:
                        import json as _json2
                        with open(_pending_file, "w", encoding="utf-8") as _pf:
                            _json2.dump({"reason": "make_blocks failed"}, _pf)
                        print("  [AI] make_blocks упал — отложено, повтор при следующем запуске")

                # --- Gemini blocks ---
                _ai_file_g = _os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
                _ai_changed_g = False
                try:
                    with open(_ai_file_g, encoding="utf-8") as _fg:
                        _ai_changed_g = json.load(_fg).get("changed", False)
                except Exception:
                    pass
                if _ai_changed_g:
                    _blocks_result_g = subprocess.run(
                        [PYTHON, _os.path.join(SCRIPTS_DIR, "make_blocks_gemini.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    if _blocks_result_g.returncode != 0:
                        print("  [AI-Gemini] make_blocks_gemini упал")

        git_push_history()
    else:
        print("  Новых прогонов нет.\n")
        # Повтор отложенной генерации видео
        _pending_file = os.path.join(BASE_DIR, "data", "blocks", "pending_video.json")
        if os.path.exists(_pending_file):
            print("  [AI] Найден pending_video — повторяю make_blocks + make_video...")
            _b = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks.py"), "--force"],
                cwd=BASE_DIR, capture_output=False
            )
            if _b.returncode == 0:
                # make_video отключён
                os.remove(_pending_file)
                print("  [AI] Повтор успешен, pending снят")
            else:
                print("  [AI] Повтор снова упал — pending остаётся")
        # Повтор Gemini если pending
        _gemini_file = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
        _gemini_pending = False
        _gemini_run_key = None
        if os.path.exists(_gemini_file):
            try:
                import json as _jg
                with open(_gemini_file, encoding="utf-8") as _fg:
                    _gd = _jg.load(_fg)
                _gemini_pending = _gd.get("pending", False)
                _gemini_run_key = _gd.get("pending_run_key")
            except Exception:
                pass
        if _gemini_pending:
            print("  [AI-Gemini] Найден pending -- повторная попытка Gemini...")
            _gr = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py"), "--force-gemini"],
                cwd=BASE_DIR, capture_output=False
            )
            if _gr.returncode == 0:
                try:
                    with open(_gemini_file, encoding="utf-8") as _fg2:
                        _gd2 = _jg.load(_fg2)
                    if _gd2.get("changed") and not _gd2.get("pending"):
                        subprocess.run(
                            [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini.py")],
                            cwd=BASE_DIR, capture_output=False
                        )
                except Exception:
                    pass

        # Всё равно обновляем SYNOP (и снимок если готов новый ансамбль)
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model", "--no-fill"],
            cwd=BASE_DIR, capture_output=False
        )
        git_push_history()   # пушим synop даже без новых моделей

    check_pws_sync()
    check_pws_calibration()
    check_sst_compare()



if __name__ == "__main__":
    main()
