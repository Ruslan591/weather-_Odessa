#!/usr/bin/env python3
"""
vps_satellite_pipeline.py — версия спутникового модуля (EUMETSAT) для
постоянного VPS (не GitHub Actions).

Основано на scripts/gh_satellite_pipeline.py — логика самих check_eumetsat_*
функций и их гейтов НЕ менялась, перенесена как есть (см. докстринг там).
Отличия VPS-версии, по аналогии с vps_pipeline.py (см. его докстринг и
docs/topics/hosting_migration.md):

  1. BASE_DIR — постоянный shallow-клон на диске VPS, тот же самый, что
     использует vps_pipeline.py (/opt/weather-pipeline/repo).
  2. sync_repo()/ensure_repo_healthy() — скопированы БУКВАЛЬНО из
     vps_pipeline.py (тот же самый хардненинг detached-HEAD/unmerged-index/
     зависших .git/*.lock, найденный и обкатанный 27-28.08.2026). Не
     импортируются оттуда намеренно — этот файл самодостаточен и не зависит
     от vps_pipeline.py по коду, только по общему BASE_DIR на диске (тот же
     принцип независимости, что был у отдельного workflow до переезда).
  3. ОБЩИЙ git-lock (/tmp/vps_git.lock, см. acquire_git_lock() ниже) —
     ЭТОТ файл и vps_pipeline.py запускаются как ДВА НЕЗАВИСИМЫХ cron-
     процесса на разных тактах (сдвиг по фазе, не совпадающие минуты), но
     оба пишут в один и тот же .git. Без общего лока это ровно тот же класс
     гонки (detached HEAD, потерянный push), что чинили весь день 28.08.2026
     для одного писателя — теперь их два, поэтому лок обязателен именно на
     секции git add/commit/push (короткая, секунды), а не на весь цикл:
     это не мешает независимости кадансов, только не даёт двум git-процессам
     тронуть репозиторий одновременно.
  4. Убран весь механизм chain_depth/eumetsat_alert_redispatch.yml
     (самоповтор через workflow_dispatch каждые 5 мин во время тревоги) —
     существовал только потому, что Termux не мог триггерить чаще 15 мин.
     На VPS cron сам тикает с нужным тактом, самоповтор не нужен.
  5. ffmpeg НЕ устанавливается и не требуется — check_eumetsat_anim_render()
     не входит в main() с 2026-08-16 (решение "закрыть визуальный браузер",
     см. docs/topics/eumetsat.md), функция оставлена неиспользуемой в файле
     ровно как в оригинале.
  6. Push-уведомления (ntfy) — раньше жили в шагах satellite_pipeline.yml
     (bash+curl+jq), перенесены сюда на Python (urllib.request), т.к. в
     VPS-модели нет YAML-шагов вообще — вся логика должна быть в самом
     скрипте.
  7. Запускается через cron на VPS (не workflow_dispatch), на отдельном
     такте со сдвигом по фазе от vps_pipeline.py — см. docs/topics/
     hosting_migration.md.
"""

import json
import os
import re
import subprocess
import sys
import time as _time
from datetime import datetime, timezone

BASE_DIR    = "/opt/weather-pipeline/repo"
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
PYTHON      = sys.executable

# ntfy-топики — те же самые, что были в satellite_pipeline.yml (см. докстринг
# там про "случайная нечитаемая строка вместо auth" — приемлемо для личных
# алертов, не для критичных данных).
NTFY_STORM_TOPIC   = "https://ntfy.sh/odessa-storm-x7k2m9qp4h"
NTFY_HEALTH_TOPIC  = "https://ntfy.sh/odessa-pipeline-health-k7m2q9wx4h"
NEARBY_URL         = "https://ruslan591.github.io/weather-_Odessa/nearby.html"


def _is_daytime_utc(now_utc):
    """Та же грубая формула, что fc.is_daytime() в field_motion_common.py
    (локальный час Одессы UTC+3, без сезонной точности) — продублирована
    здесь напрямую (не импортом fc), чтобы не тащить scipy-зависимость
    field_motion_common.py в лёгкий процесс-оркестратор ради одной проверки.
    Используется только для гейта check_eumetsat_cloud_phase_type() —
    см. комментарий там."""
    local_hour = (now_utc.hour + 3) % 24
    return 5 <= local_hour < 20


def _parse_ts_flexible(ts):
    """Парсит "timestamp" из data/eumetsat_{cloud_forecast,geocolour_motion,
    ir_motion}.json — с 2026-08-19 это время КАДРА (формат
    "...T%H:%M:00.000Z", как в остальном пайплайне), раньше было время
    генерации ("...T%H:%M:%SZ", без миллисекунд). Пробуем оба формата —
    нужно для первого прогона после деплоя, пока в закоммиченном файле ещё
    старый формат от предыдущего запуска. См. docs/topics/eumetsat.md."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"не удалось распарсить timestamp: {ts!r}")


# ── синхронизация репозитория (копия из vps_pipeline.py, см. его докстринг
#    sync_repo()/ensure_repo_healthy() за полной историей находок 27-28.08) ──

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
            subprocess.run(
                ["git", "-C", BASE_DIR, "stash", "clear"],
                capture_output=True, text=True, timeout=10)
            print(f"  [WARN] очищено {n} осиротевших stash-записей")

        print("  ✓ repo synced with origin/main")
        return True
    except Exception as e:
        print(f"  [WARN] sync_repo error: {e}")
        return False


def ensure_repo_healthy():
    try:
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
            return False
        return True
    except Exception as e:
        print(f"  [WARN] ensure_repo_healthy error: {e}")
        return False


# ── общий git-lock между vps_pipeline.py и этим скриптом (см. докстринг) ──

GIT_LOCK_FILE = "/tmp/vps_git.lock"
GIT_LOCK_TIMEOUT_SEC = 60


def acquire_git_lock():
    """Блокирующий (с таймаутом) лок на КОРОТКУЮ секцию git add/commit/push —
    общий между vps_pipeline.py и vps_satellite_pipeline.py (два независимых
    процесса, один .git). Не путать с LOCK_FILE ниже (self-collision одного
    и того же скрипта) — это разные локи с разными именами файлов.
    Ждём до GIT_LOCK_TIMEOUT_SEC, опрашивая раз в секунду; если так и не
    получили — не блокируем цикл навсегда, идём на push без лока (в худшем
    случае сработает retry с rebase -X theirs, как и раньше)."""
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


# ── check_eumetsat_* (перенесены как есть из gh_satellite_pipeline.py) ────

def check_eumetsat_point():
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_point.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
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
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_cloud_forecast.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
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


def check_eumetsat_west_watch():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_west_watch.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch.py: {e}")


def check_eumetsat_frontal_track():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_frontal_track.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_frontal_track.py: {e}")


def check_open_meteo_frontal_confirm():
    # Согласовано с пользователем 2026-09-06 (docs/topics/frontal_line_
    # stations.md). Событийный гейт ВНУТРИ скрипта (новый прогон модели +
    # наличие кандидата) — можно звать каждый цикл, лишней сети не будет.
    # timeout щедрый: 5 моделей x REQUEST_INTERVAL=30с пауз + сами запросы.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "open_meteo_frontal_confirm.py")],
            cwd=BASE_DIR, capture_output=False, timeout=210
        )
    except Exception as e:
        print(f"  [WARN] open_meteo_frontal_confirm.py: {e}")


def check_eumetsat_render_track_overlay():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_render_track_overlay.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_render_track_overlay.py: {e}")


def check_eumetsat_ground_station_verify():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_ground_station_verify.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_ground_station_verify.py: {e}")


def check_ground_station_field_fetch():
    # [ДОБАВЛЕНО 2026-09-03] Исследование найденного фронта через сеть
    # наземных станций вдоль оси трека (BUFR-first) — см. докстринг
    # ground_station_field_fetch.py и docs/topics/frontal_line_stations.md.
    # timeout щедрый (240с): на "холодном" кэше несколько треков × до
    # ~11 сэмплов каждый могут дать десятки УНИКАЛЬНЫХ станций (кэш
    # дедуплицирует повторы В ПРЕДЕЛАХ одного прогона, но не между
    # прогонами при истёкшем TTL), каждая — до ~20с на BUFR-запрос в
    # худшем случае (timeout внутри fetch_bufr_obs.py). После прогрева
    # кэша (TTL=45мин) большинство станций будут отдаваться мгновенно.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "ground_station_field_fetch.py")],
            cwd=BASE_DIR, capture_output=False, timeout=240
        )
    except Exception as e:
        print(f"  [WARN] ground_station_field_fetch.py: {e}")


def _throttle_ok(key, interval_minutes):
    # [ДОБАВЛЕНО 2026-09-05] Общий гейт для Open-Meteo шагов — найдено
    # вживую: open_meteo_field_fetch.py (до 8 моделей × N треков) +
    # open_meteo_very_far_line.py КАЖДЫЙ 5-минутный цикл VPS всё вместе
    # словили HTTP 429 (Too Many Requests) от Open-Meteo. Локальный
    # файл-метка (НЕ коммитится — VPS-диск персистентный между cron-
    # запусками, в отличие от GH Actions с чистым чекаутом каждый раз,
    # см. docs/topics/hosting_migration.md), просто пейсинг на месте.
    path = os.path.join(BASE_DIR, "data", f"_throttle_{key}.json")
    now = datetime.now(timezone.utc)
    try:
        with open(path, "r", encoding="utf-8") as f:
            last = datetime.strptime(json.load(f)["last_run"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < interval_minutes * 60:
            return False
    except Exception:
        pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_run": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, f)
    return True


def check_open_meteo_field_fetch():
    # Шаг 3 плана (docs/topics/frontal_line_stations.md) — плотное поле
    # 8 моделей вокруг найденного трека. Throttle 15мин — см. _throttle_ok.
    if not _throttle_ok("open_meteo_field", 15):
        return
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "open_meteo_field_fetch.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] open_meteo_field_fetch.py: {e}")


def check_frontal_line_score():
    # Шаг 4 плана — сверка Open-Meteo с реальными станциями, лёгкий (без
    # сети), короткий timeout.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "frontal_line_score.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] frontal_line_score.py: {e}")


def check_eumetsat_precip_forecast():
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_precip_forecast.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
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
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_lightning_forecast.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
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
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_ir_motion.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
            if (now_utc - last_time).total_seconds() < 10 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_ir_motion.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_ir_motion.py: {e}")


def check_eumetsat_precip_motion():
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_precip_motion.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
            if (now_utc - last_time).total_seconds() < 10 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_precip_motion.py")],
            cwd=BASE_DIR, capture_output=False, timeout=180
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_precip_motion.py: {e}")


def check_eumetsat_cloud_phase_type():
    if not _is_daytime_utc(datetime.now(timezone.utc)):
        return
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_cloud_phase_type.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
            if (now_utc - last_time).total_seconds() < 10 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_cloud_phase_type.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_cloud_phase_type.py: {e}")


def check_eumetsat_geocolour_motion():
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_geocolour_motion.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            last_time = _parse_ts_flexible(prev["timestamp"])
            if (now_utc - last_time).total_seconds() < 10 * 60:
                return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_geocolour_motion.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_geocolour_motion.py: {e}")


def check_eumetsat_anim_render():
    # НЕ вызывается из main() с 2026-08-16 — см. докстринг файла, п.5.
    # Оставлено неиспользуемым, как в оригинале, на случай возврата.
    manifest_file = os.path.join(BASE_DIR, "data", "anim", "manifest.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(manifest_file):
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            times = [v for v in manifest.values() if v]
            if times:
                last_time = max(
                    datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    for t in times
                )
                if (now_utc - last_time).total_seconds() < 20 * 60:
                    return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_anim_render.py")],
            cwd=BASE_DIR, capture_output=False, timeout=600
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_anim_render.py: {e}")


def check_eumetsat_far_watch():
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_far_watch.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("timestamp")
            if ts:
                last_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                if (now_utc - last_time).total_seconds() < 30 * 60:
                    return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_far_watch.py"), "far"],
            cwd=BASE_DIR, capture_output=False, timeout=60
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_far_watch.py far: {e}")


def check_eumetsat_very_far_watch():
    # [ИЗМЕНЕНО 2026-09-03] Гейт 180мин убран — по запросу пользователя
    # для эксперимента с open_meteo_very_far_line.py нужно обновление
    # снимка каждый прогон, а не раз в 3ч.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_far_watch.py"), "very_far"],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_far_watch.py very_far: {e}")


def check_open_meteo_very_far_line():
    # Эксперимент 2026-09-03 (см. docs/topics/frontal_line_stations.md) —
    # линия по Open-Meteo (1 модель, без подтверждения станциями) поверх
    # very_far_geocolour.png. Нужен ГОТОВЫЙ файл (пишется поверх), поэтому
    # строго после check_eumetsat_very_far_watch. Throttle 15мин — см.
    # _throttle_ok (изначально "каждый цикл" по запросу пользователя для
    # отладки, но вместе с open_meteo_field_fetch поймали HTTP 429).
    if not _throttle_ok("open_meteo_very_far_line", 15):
        return
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "open_meteo_very_far_line.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] open_meteo_very_far_line.py: {e}")


def check_eumetsat_target_summary():
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_target_summary.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_target_summary.py: {e}")


def check_eumetsat_render_systems_overlay():
    # [ДОБАВЛЕНО 2026-09-02] Перенесено вслед за gh_satellite_pipeline.py —
    # покраска РЕАЛЬНЫХ пикселей ВСЕХ систем синоптического масштаба
    # (снапшот текущего цикла, не персистентные frontlike-треки), см.
    # докстринг eumetsat_render_systems_overlay.py. Вызывается ПОСЛЕ
    # check_eumetsat_target_summary() — system_candidates нужны уже
    # профильтрованными по видимости ИК/GeoColour.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_render_systems_overlay.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_render_systems_overlay.py: {e}")


def check_pipeline_health_alert():
    # Порог поднят с 3 до 4 (2026-09-02, по запросу пользователя — пуши
    # "пайплайн застрял" приходили слишком часто при цикле VPS ~5 мин:
    # 3 подряд = ~15 мин простоя, легко ловилось на обычных паузах публикации
    # кадра). Теперь 4 подряд = ~20 мин.
    N_CONSECUTIVE_STALE_FOR_ALERT = 4
    health_file = os.path.join(BASE_DIR, "data", "eumetsat_pipeline_health.json")
    alert_file = os.path.join(BASE_DIR, "data", "eumetsat_pipeline_alert_state.json")

    health = {}
    try:
        if os.path.exists(health_file):
            with open(health_file, "r", encoding="utf-8") as f:
                health = json.load(f)
    except Exception:
        health = {}

    stuck = [
        {"script": script, **entry}
        for script, entry in health.items()
        if entry.get("consecutive_skips", 0) >= N_CONSECUTIVE_STALE_FOR_ALERT
    ]
    is_alert = len(stuck) > 0

    prev_alert = False
    try:
        if os.path.exists(alert_file):
            with open(alert_file, "r", encoding="utf-8") as f:
                prev_alert = bool(json.load(f).get("alert"))
    except Exception:
        prev_alert = False

    alert_state = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert": is_alert,
        "just_triggered": bool(is_alert and not prev_alert),
        "just_recovered": bool(prev_alert and not is_alert),
        "stuck_scripts": stuck,
    }
    try:
        with open(alert_file, "w", encoding="utf-8") as f:
            json.dump(alert_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [WARN] check_pipeline_health_alert: alert state write failed: {e}")


# ── ntfy push-уведомления (перенос из шагов satellite_pipeline.yml на Python) ──

def _ntfy_post(topic_url, title, priority, tags, body, click=None):
    """POST в ntfy.sh с retry (аналог `curl --retry 3 --retry-delay 2` в
    старых YAML-шагах). Ошибки не фатальны для цикла — push-уведомление не
    должно ронять весь пайплайн (та же логика, что была у continue-on-error:
    true в workflow).

    НАХОДКА (29.08.2026, первый прогон на VPS): заголовок Title содержит
    эмодзи (🌧️/⛈️/⚠️/✅) — `http.client.putheader()` пытается закодировать
    строковые значения заголовков в latin-1 и падает с UnicodeEncodeError
    ДО того, как что-либо уходит на сервер (curl в старом YAML этой
    проблемы не имел — просто шлёт сырые UTF-8 байты без такой проверки).
    Фикс: передаём значения заголовков как bytes (уже закодированные в
    UTF-8) — `http.client` пропускает свой latin-1-энкодинг для значений,
    у которых нет метода .encode (bytes его не имеет, есть только .decode),
    и отправляет байты как есть — то же самое, что делал curl."""
    import urllib.request
    import urllib.error
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority.encode("utf-8"),
        "Tags": tags.encode("utf-8"),
    }
    if click:
        headers["Click"] = click.encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                topic_url, data=body.encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            print(f"  [WARN] ntfy push попытка {attempt+1}: {e}")
        if attempt < 2:
            _time.sleep(2)
    print("  [WARN] ntfy push не прошёл после 3 попыток")
    return False


def notify_precip_alert():
    # Push ТОЛЬКО на переход false→true (just_triggered), не на каждый цикл.
    state_file = os.path.join(BASE_DIR, "data", "eumetsat_alert_state.json")
    if not os.path.exists(state_file):
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return
    if not state.get("just_triggered"):
        return
    eta = state.get("eta_min", "?")
    dist = state.get("distance_km_now", "?")
    verdict = state.get("verdict", "?")
    prob = state.get("probability_percent", "?")
    ok = _ntfy_post(
        NTFY_STORM_TOPIC, "🌧️ Осадки приближаются", "high", "cloud_with_rain",
        f"{verdict} / ETA ~{eta} мин / {dist} км / вероятность {prob}%",
        click=NEARBY_URL)
    if ok:
        print("  push (осадки) отправлен")


def notify_lightning_alert():
    state_file = os.path.join(BASE_DIR, "data", "eumetsat_lightning_alert_state.json")
    if not os.path.exists(state_file):
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return
    if not state.get("just_triggered"):
        return
    eta = state.get("eta_min", "?")
    dist = state.get("distance_km_now", "?")
    verdict = state.get("verdict", "?")
    prob = state.get("probability_percent", "?")
    ok = _ntfy_post(
        NTFY_STORM_TOPIC, "⛈️ Гроза приближается", "urgent", "zap",
        f"{verdict} / ETA ~{eta} мин / {dist} км / вероятность {prob}%",
        click=NEARBY_URL)
    if ok:
        print("  push (гроза) отправлен")


def notify_pipeline_health():
    state_file = os.path.join(BASE_DIR, "data", "eumetsat_pipeline_alert_state.json")
    if not os.path.exists(state_file):
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return
    if state.get("just_triggered"):
        scripts = ", ".join(s.get("script", "") for s in state.get("stuck_scripts", []))
        since = (state.get("stuck_scripts") or [{}])[0].get("stuck_since", "?")
        ok = _ntfy_post(
            NTFY_HEALTH_TOPIC, "⚠️ Спутниковый пайплайн застрял", "default", "warning",
            f"Источник не даёт новых кадров (3+ прогона подряд): {scripts}. "
            f"Застряло с {since} UTC.")
        if ok:
            print("  push (пайплайн застрял) отправлен")
    elif state.get("just_recovered"):
        ok = _ntfy_post(
            NTFY_HEALTH_TOPIC, "✅ Спутниковый пайплайн отпустило", "low", "white_check_mark",
            "Источник снова даёт новые кадры, данные обновляются.")
        if ok:
            print("  push (пайплайн отпустило) отправлен")


# ── коммит и push (общий git-lock + hardened retry, как в vps_pipeline.py) ──

def git_push_satellite():
    lock_fd = acquire_git_lock()
    try:
        ensure_repo_healthy()
        _candidates = [
            "data/eumetsat_point.json",
            "data/eumetsat_point_debug.json",
            "data/eumetsat_cloud_forecast.json",
            "data/eumetsat_cloud_forecast_debug.json",
            "data/eumetsat_cloud_buffer.npz",
            "data/eumetsat_west_watch.json",
            "data/eumetsat_west_snapshot_clm.png",
            "data/eumetsat_west_snapshot_geocolour.png",
            "data/eumetsat_west_snapshot_ir.png",
            "data/eumetsat_frontal_track.json",
            "data/open_meteo_frontal_confirm.json",
            "data/eumetsat_frontal_track_state.json",
            "data/eumetsat_ground_station_verify.json",
            "data/ground_station_field.json",
            "data/open_meteo_field.json",
            "data/frontal_line_score.json",
            "data/eumetsat_cloud_phase_type.json",
            "data/eumetsat_cloud_phase_type_debug.json",
            "data/eumetsat_cloud_phase_type_buffer.npz",
            "data/eumetsat_precip_forecast.json",
            "data/eumetsat_precip_forecast_debug.json",
            "data/eumetsat_precip_history.jsonl",
            "data/eumetsat_alert_state.json",
            "data/eumetsat_lightning_forecast.json",
            "data/eumetsat_lightning_forecast_debug.json",
            "data/eumetsat_lightning_history.jsonl",
            "data/eumetsat_lightning_alert_state.json",
            "data/eumetsat_ir_motion.json",
            "data/eumetsat_ir_motion_debug.json",
            "data/eumetsat_ir_buffer.npz",
            "data/eumetsat_precip_motion.json",
            "data/eumetsat_precip_motion_debug.json",
            "data/eumetsat_precip_buffer.npz",
            "data/eumetsat_geocolour_motion.json",
            "data/eumetsat_geocolour_motion_debug.json",
            "data/eumetsat_geocolour_buffer.npz",
            "data/eumetsat_geocolour_debug_preview.png",
            "data/eumetsat_geocolour_snapshot.png",
            "data/eumetsat_ir_snapshot.png",
            "data/eumetsat_clm_snapshot.png",
            "data/eumetsat_systems_snapshot.png",
            "data/eumetsat_local_channel_suppression_log.json",
            "data/eumetsat_system_channel_suppression_log.json",
            "data/eumetsat_far_watch.json",
            "data/eumetsat_far_watch_state.json",
            "data/eumetsat_far_watch_debug.json",
            "data/eumetsat_very_far_watch.json",
            "data/eumetsat_very_far_watch_state.json",
            "data/eumetsat_very_far_watch_debug.json",
            "data/anim/manifest.json",
            "data/eumetsat_very_far_line_debug.json",
            "data/anim/debug.json",
            "data/fog_calibration_log.jsonl",
            "data/eumetsat_target_summary.json",
            "data/eumetsat_target_false_positive_log.json",
            "data/eumetsat_skip_log.jsonl",
            "data/eumetsat_pipeline_health.json",
            "data/eumetsat_pipeline_alert_state.json",
        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        if _to_add:
            subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                            check=True, capture_output=True, timeout=30)
        # data/anim/* — ОТДЕЛЬНО, директорией целиком (см. докстринг в
        # оригинале gh_satellite_pipeline.py про баг video->image 2026-08-03).
        subprocess.run(["git", "-C", BASE_DIR, "add", "data/anim"],
                        capture_output=True, timeout=30)

        status = subprocess.run(
            ["git", "-C", BASE_DIR, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=15)
        _changed = [
            os.path.splitext(os.path.basename(p))[0]
            for p in status.stdout.strip().splitlines() if p.strip()
        ]
        if not _changed:
            print("  Нет изменений для коммита.")
            return
        commit_msg = "satellite: " + ", ".join(_changed)
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
            push = subprocess.run(
                ["git", "-C", BASE_DIR, "push"],
                capture_output=True, text=True, timeout=60)
            if push.returncode == 0:
                suffix = f" (attempt {_attempt+1})" if _attempt > 0 else ""
                print(f"  satellite push ✓{suffix}")
                return
            err = push.stderr.strip()
            print(f"  satellite push ✗ attempt {_attempt+1}: {err}")
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
        print("  satellite push failed after 3 attempts")
    except subprocess.TimeoutExpired as e:
        print(f"  satellite git timeout: {e}")
    except Exception as e:
        print(f"  satellite git error: {e}")
    finally:
        release_git_lock(lock_fd)


# ── собственный process-lock (self-collision, отдельный от git-lock) ──────

LOCK_FILE = "/tmp/vps_satellite_pipeline.lock"


def acquire_lock():
    import fcntl
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except OSError:
        return None


def main():
    lock_fd = acquire_lock()
    if lock_fd is None:
        print("  ⏭ предыдущий цикл спутника ещё выполняется — пропускаю (lock занят)")
        return

    _t0 = _time.time()
    try:
        _main_body()
    finally:
        _dt = _time.time() - _t0
        print(f"\n  ⏱ [satellite] цикл занял {_dt:.1f}с")
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _main_body():
    print(f"\n{'─'*52}")
    print(f"  [SATELLITE-VPS] Цикл спутникового модуля  {datetime.now(timezone.utc).strftime('%d.%m %H:%M UTC')}")
    print(f"{'─'*52}\n")

    if not sync_repo():
        print("  ✗ sync_repo failed — цикл пропущен, попробуем в следующий раз.")
        return

    # [ДОБАВЛЕНО 30.08.2026] Замер времени каждого check_eumetsat_* — найдены
    # циклы 100-132с при том, что "полные" циклы (10-14 шагов) укладываются
    # в 19-25с; без потайминга по шагам непонятно, кто именно тормозит
    # (подозрение — retry на флакающем EUMETSAT WMS, но это гадание без
    # цифр). Печатает только шаги дольше STEP_WARN_SEC, чтобы не засорять
    # лог на каждом быстром шаге.
    STEP_WARN_SEC = 5

    def _timed(fn):
        _t0 = _time.monotonic()
        fn()
        _dt = _time.monotonic() - _t0
        if _dt >= STEP_WARN_SEC:
            print(f"  ⏱ {fn.__name__}: {_dt:.1f}с")

    # check_eumetsat_point() не вызывается — см. комментарий в оригинале
    # gh_satellite_pipeline.py (мёртвый шаг с эпохи RainViewer-сравнения).
    _timed(check_eumetsat_cloud_forecast)
    _timed(check_eumetsat_west_watch)
    _timed(check_eumetsat_frontal_track)
    _timed(check_open_meteo_frontal_confirm)
    _timed(check_eumetsat_render_track_overlay)
    _timed(check_eumetsat_ground_station_verify)
    _timed(check_ground_station_field_fetch)
    # [ОТКЛЮЧЕНО 2026-09-05, ЭКСТРЕННО] check_open_meteo_field_fetch() —
    # эксперимент бьёт по общему рейт-лимиту Open-Meteo на IP VPS и
    # блокирует БОЕВОЕ обновление 8 моделей в update.py (пользователь
    # сообщил: "5 часов не может обновиться ни одна модель"). НЕ включать
    # обратно без пересмотра частоты/объёма запросов — см.
    # docs/topics/frontal_line_stations.md.
    # _timed(check_open_meteo_field_fetch)
    _timed(check_frontal_line_score)
    _timed(check_eumetsat_cloud_phase_type)
    _timed(check_eumetsat_precip_forecast)
    _timed(check_eumetsat_lightning_forecast)
    _timed(check_eumetsat_ir_motion)
    _timed(check_eumetsat_precip_motion)
    _timed(check_eumetsat_geocolour_motion)
    _timed(check_eumetsat_target_summary)
    _timed(check_eumetsat_render_systems_overlay)
    # check_eumetsat_anim_render() не вызывается — см. докстринг файла, п.5.
    _timed(check_eumetsat_far_watch)
    _timed(check_eumetsat_very_far_watch)
    # [ОТКЛЮЧЕНО 2026-09-05, ЭКСТРЕННО] check_open_meteo_very_far_line() —
    # см. причину у check_open_meteo_field_fetch() выше, тот же общий
    # рейт-лимит на IP VPS.
    # _timed(check_open_meteo_very_far_line)

    check_pipeline_health_alert()
    git_push_satellite()

    notify_precip_alert()
    notify_lightning_alert()
    notify_pipeline_health()


if __name__ == "__main__":
    main()
