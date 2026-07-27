#!/usr/bin/env python3
"""
gh_satellite_pipeline.py — независимый цикл спутникового модуля (EUMETSAT).

Вынесен из scripts/gh_pipeline.py 2026-07-26: пять EUMETSAT-скриптов
(cloud/precip/lightning motion-прогнозы + point-сравнение) стали настолько
частыми (гейты 5-15 мин почти совпадают с 15-минутным интервалом триггера
телефона), что регулярно раздували длительность основного пайплайна до
10-17 минут и из-за concurrency-группы full-pipeline заставляли следующие
триггеры вставать в очередь.

Теперь это отдельный workflow (satellite_pipeline.yml), запускается
автоматически сразу после завершения full_pipeline.yml (workflow_run),
но в своей collision-группе и с собственным таймаутом — медленный или
подвисший спутниковый цикл больше не блокирует verification+AI+PWS.

Логика самих функций и гейтов НЕ менялась — просто перенесена сюда как есть.
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


def check_eumetsat_precip_forecast():
    # Мини-прогноз движения осадков (msg_fes:h60b, 4 кадра). Гейт 15 мин.
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_precip_forecast.json")
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
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_precip_forecast.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_precip_forecast.py: {e}")


def check_eumetsat_lightning_forecast():
    # Мини-прогноз движения грозовой активности (mtg_fd:li_afa, 4 кадра,
    # шаг 5 мин — обновляется чаще осадков/облаков). Гейт 5 мин.
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_lightning_forecast.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = datetime.strptime(prev["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now_utc - last_time).total_seconds() < 5 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_lightning_forecast.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_lightning_forecast.py: {e}")


def check_eumetsat_ir_motion():
    # Независимая оценка движения облачности по текстуре ИК-канала 10.5мкм
    # (mtg_fd:ir105_hrfi, персистентный буфер 6 кадров, шаг 10 мин) —
    # работает днём и ночью. Гейт 10 мин.
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion.json")
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
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_ir_motion.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_ir_motion.py: {e}")


def check_eumetsat_precip_motion():
    # Анализ движения осадков (mtg_fd:h40b, персистентный буфер 6 кадров,
    # шаг 10 мин) — та же инфраструктура, что у eumetsat_ir_motion.py,
    # домен-логика (CPA/ETA/probability) как у старого precip_forecast.
    # Гейт 10 мин.
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_precip_motion.json")
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
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_precip_motion.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_precip_motion.py: {e}")


def git_push_satellite():
    """Коммитит и пушит только файлы спутникового модуля."""
    try:
        _candidates = [
            "data/eumetsat_point.json",
            "data/eumetsat_point_debug.json",
            "data/eumetsat_cloud_forecast.json",
            "data/eumetsat_cloud_forecast_debug.json",
            "data/eumetsat_precip_forecast.json",
            "data/eumetsat_precip_forecast_debug.json",
            "data/eumetsat_lightning_forecast.json",
            "data/eumetsat_lightning_forecast_debug.json",
            "data/eumetsat_ir_motion.json",
            "data/eumetsat_ir_motion_debug.json",
            "data/eumetsat_ir_buffer.npz",
            "data/eumetsat_precip_motion.json",
            "data/eumetsat_precip_motion_debug.json",
            "data/eumetsat_precip_buffer.npz",
        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        if not _to_add:
            print("  Нет файлов для коммита.")
            return
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                        check=True, capture_output=True)
        result = subprocess.run(
            ["git", "-C", BASE_DIR, "commit", "-m", "satellite: eumetsat cloud/precip/lightning/ir update"],
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
                print(f"  satellite push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  satellite push ✗ attempt {_attempt+1}: {err}")
            if _attempt < 2:
                _time.sleep(_delays[_attempt])
                subprocess.run(["git", "-C", BASE_DIR, "fetch", "origin", "main"], capture_output=True)
                subprocess.run(["git", "-C", BASE_DIR, "rebase", "origin/main"], capture_output=True)
        print("  satellite push failed after 3 attempts")
    except Exception as e:
        print(f"  satellite git error: {e}")


def main():
    print(f"\n{'─'*52}")
    print(f"  [SATELLITE] Цикл спутникового модуля  {datetime.now(timezone.utc).strftime('%d.%m %H:%M UTC')}")
    print(f"{'─'*52}\n")

    check_eumetsat_point()
    check_eumetsat_cloud_forecast()
    check_eumetsat_precip_forecast()
    check_eumetsat_lightning_forecast()
    check_eumetsat_ir_motion()
    check_eumetsat_precip_motion()

    git_push_satellite()


if __name__ == "__main__":
    main()

