#!/usr/bin/env python3
"""
gh_pipeline.py — облачный дирижёр пайплайна для GitHub Actions.

Аналог scripts/check_model_runs.py (телефон/Termux), адаптированный для
запуска в GitHub Actions на checkout-е репозитория. Логика идентична,
но зовёт cloud-варианты скриптов там, где у телефонных есть
Termux-специфичные хардкоды (пути), и пушит без форса/лока — в облаке
пишет только один процесс за раз (телефон в этот период остановлен).

check_model_runs.py на телефоне НЕ используется и не изменяется — это
отдельный файл специально под workflow, согласно решению не трогать
телефонную версию.

Пайплайн при обнаружении нового прогона:
  1. calc_model_bias_cloud.py
  2. calc_weights.py (без LOCAL=1 — пишет через GitHub API сам)
  3. update_local.py --no-model
  4. generate_ai_analysis.py
  5. make_blocks_cloud.py / make_blocks_gemini_cloud.py (если изменилось)
  6. git commit + push (без force, без лока — единственный писатель)

Плюс каждый цикл: PWS-синк (pws_sync.py), калибровка давления PWS,
полная морская история — SST/волны/ветер/давление/течение (marine_history.py).

Расписание: .github/workflows/full_pipeline.yml, schedule */15 * * * *
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

# ── git (без форса и без лока — единственный писатель в облаке) ──────────────

def git_push_history():
    import time as _time
    try:
        year = datetime.now(timezone.utc).year
        _candidates = [
                        "data/model_runs_history.json",
                        f"data/synop_{year}.txt",
                        "data/model_bias.json",
                        "data/forecast_analysis_claude.json", "data/forecast_analysis_claude.mp3",
                        "data/blocks",
                        "data/forecast_analysis_gemini.json", "data/forecast_analysis_gemini.mp3",
                        "data/blocks_gemini",
                        "data/ai_schedule.json",
                        "data/ai_schedule_gemini.json",
                        "data/marine_history.json",
                        "data/nearby_precip.json",
                        "data/nearby_precip_debug.json",
                        "data/eumetsat_point.json",
                        "data/eumetsat_point_debug.json",
                        "data/eumetsat_cloud_forecast.json",
                        "data/eumetsat_cloud_forecast_debug.json",
                        "data/hmcbas_sea_temp_realtime.json",
                        "data/hmcbas_telegram_sea_temp.json",
                        "data/hmcbas_telegram_debug.json",
                        "data/pws_sync_state.json",
                        "data/forecast_video.mp4",
                        "data/forecast_video_gemini.mp4",
                        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                      check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", "cloud: synop + history update"],
            capture_output=True, text=True)
        if result.returncode != 0:
            msg = result.stdout.strip() or result.stderr.strip()
            if "nothing to commit" not in msg and "nothing added" not in msg:
                print(f"  commit warn: {msg}")

        # push с retry: fetch + rebase перед повтором (никакого force)
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
    """Запускает calc_model_bias_cloud → calc_weights → update_local --no-model."""
    print(f"\n  🚀 Новых прогонов: {len(new_models)} ({', '.join(new_models)})")
    print(  "     Запускаю пайплайн...\n")

    steps = [
        {
            "name": "calc_model_bias_cloud.py",
            "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_model_bias_cloud.py")],
            "env":  None,
        },
        {
            "name": "calc_weights.py (cloud/API)",
            "cmd":  [PYTHON, os.path.join(SCRIPTS_DIR, "calc_weights.py")],
            "env":  None,
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
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"  ✗ {step['name']} завершился с ошибкой (код {result.returncode})")
            print(  "    Пайплайн остановлен.")
            return False

        print(f"  ✓ {step['name']}\n")

    print("  ✅ Пайплайн завершён успешно.")
    return True

# ── PWS-синк (cloud: пишет через API pws_sync.py напрямую) ───────────────────

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
        return  # данные актуальны

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

    # pws_sync.py пишет через API — локальный pws_file не обновится в этом
    # процессе, поэтому счётчик попыток не увеличиваем здесь: следующий
    # запуск получит свежий checkout и увидит актуальное состояние сам.

# ── калибровка и SST (уже переносимы, используем как есть) ───────────────────

def check_pws_calibration():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "calibrate_pws_pressure.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] calibrate_pws_pressure.py: {e}")

def check_hmcbas_sea_temp():
    # Раз в ~20 мин: реальная (не прогнозная) температура воды с виджета
    # ГМЦ ЧАМ (hmcbas.od.ua), с фоллбэком через r.jina.ai при 421.
    out_file = os.path.join(BASE_DIR, "data", "hmcbas_sea_temp_realtime.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = datetime.strptime(prev["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now_utc - last_time).total_seconds() < 20 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "fetch_hmcbas_sea_temp.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] fetch_hmcbas_sea_temp.py: {e}")

def check_hmcbas_telegram():
    # Раз в сутки: реальный замер температуры воды из утреннего поста
    # t.me/HMC_Odesa. Гейт — если в истории уже есть запись за сегодня
    # (UTC), не дёргаем канал зря; иначе пробуем каждый цикл, пока пост
    # не появится (дешёвый фетч одной страницы).
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
    # Расстояние до ближайших осадков/грозы (open-meteo сетка вокруг Одессы).
    # Гейт 10 мин — защита от дублирующего запуска в рамках одного цикла.
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

def check_eumetsat_cloud_forecast():
    # Мини-прогноз движения облачности (EUMETSAT Cloud Mask, 2 кадра).
    # Гейт 15 мин — реальные данные обновляются с той же частотой.
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = datetime.strptime(prev["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now_utc - last_time).total_seconds() < 15 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_cloud_forecast.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_cloud_forecast.py: {e}")

def check_eumetsat_point():
    # Значения EUMETSAT (облачность/высота/молнии) в точке Одессы, для
    # сравнения с RainViewer-прокси. Гейт 12 мин (реальные данные — 5-15 мин).
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_point.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = datetime.strptime(prev["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now_utc - last_time).total_seconds() < 12 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_point.py")],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_point.py: {e}")

def check_marine_history():
    # marine_history.py пишет каждый прогон пайплайна (~15 мин) — все параметры моря,
    # а не только SST раз в час, как было раньше в sst_compare.py.
    # Небольшой гейт (5 мин) — только защита от случайного дублирующего запуска,
    # а не намеренное прореживание.
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-ai", action="store_true")
    args, _ = parser.parse_known_args()
    os.makedirs(LOG_DIR, exist_ok=True)
    now = now_utc_iso()
    history = load_history()
    new_models = []

    print(f"\n{'─'*52}")
    print(f"  [CLOUD] Проверка прогонов моделей  {iso_to_local(now)}")
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
                _ai_file = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
                _ai_changed = False
                try:
                    with open(_ai_file, encoding="utf-8") as _f:
                        _ai_changed = json.load(_f).get("changed", False)
                except Exception:
                    pass
                if _ai_changed:
                    subprocess.run(
                        [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_cloud.py")],
                        cwd=BASE_DIR, capture_output=False
                    )

                _ai_file_g = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
                _ai_changed_g = False
                try:
                    with open(_ai_file_g, encoding="utf-8") as _fg:
                        _ai_changed_g = json.load(_fg).get("changed", False)
                except Exception:
                    pass
                if _ai_changed_g:
                    _blocks_result_g = subprocess.run(
                        [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
                        cwd=BASE_DIR, capture_output=False
                    )
                    if _blocks_result_g.returncode != 0:
                        print("  [AI-Gemini] make_blocks_gemini_cloud упал")
                    else:
                        _video_result_g = subprocess.run(
                            [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                            cwd=BASE_DIR, capture_output=False
                        )
                        if _video_result_g.returncode != 0:
                            print("  [AI-Gemini] make_video.py (gemini) упал")

        git_push_history()
    else:
        print("  Новых прогонов нет.\n")

        _gemini_file = os.path.join(BASE_DIR, "data", "forecast_analysis_gemini.json")
        _gemini_pending = False
        if os.path.exists(_gemini_file):
            try:
                with open(_gemini_file, encoding="utf-8") as _fg:
                    _gd = json.load(_fg)
                _gemini_pending = _gd.get("pending", False)
            except Exception:
                pass
        if _gemini_pending:
            print("  [AI-Gemini] Найден pending — повторная попытка Gemini...")
            _gr = subprocess.run(
                [PYTHON, os.path.join(SCRIPTS_DIR, "generate_ai_analysis.py"), "--force-gemini"],
                cwd=BASE_DIR, capture_output=False
            )
            if _gr.returncode == 0:
                try:
                    with open(_gemini_file, encoding="utf-8") as _fg2:
                        _gd2 = json.load(_fg2)
                    if _gd2.get("changed") and not _gd2.get("pending"):
                        _blocks_r = subprocess.run(
                            [PYTHON, os.path.join(SCRIPTS_DIR, "make_blocks_gemini_cloud.py")],
                            cwd=BASE_DIR, capture_output=False
                        )
                        if _blocks_r.returncode == 0:
                            subprocess.run(
                                [PYTHON, os.path.join(SCRIPTS_DIR, "make_video.py"), "gemini"],
                                cwd=BASE_DIR, capture_output=False
                            )
                except Exception:
                    pass

        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "update_local.py"), "--no-model", "--no-fill"],
            cwd=BASE_DIR, capture_output=False
        )
        git_push_history()

    check_pws_sync()
    check_pws_calibration()
    check_marine_history()
    check_nearby_precip()
    check_eumetsat_point()
    check_eumetsat_cloud_forecast()
    # check_hmcbas_sea_temp()  # отключено: виджет сайта стабильно отдаёт 0°C (брак), Telegram надёжнее
    check_hmcbas_telegram()

    # calibrate_pws_pressure.py и marine_history.py пишут только в локальный
    # checkout раннера — без этого push их изменения терялись при завершении job'а.
    git_push_history()


if __name__ == "__main__":
    main()
