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


def check_eumetsat_point():
    # Значения EUMETSAT (облачность/высота/молнии) в точке Одессы, для
    # сравнения с RainViewer-прокси. Гейт 12 мин (реальные данные — 5-15 мин).
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
    # Мини-прогноз движения облачности (EUMETSAT Cloud Mask + CTH,
    # персистентный буфер до 9 кадров = 2ч, шаг 15 мин, докачка 1 кадра/прогон).
    # Гейт 15 мин — реальные данные обновляются с той же частотой.
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
    # Пилотный западный тайл (2026-08-16, план "мозаика тайлов") — детект
    # ТОЛЬКО frontlike-систем (см. докстринг eumetsat_west_watch.py), без
    # multi-frame буфера. Собственный гейт ВНУТРИ скрипта — по времени
    # кадра CLM, объявленному сервером (не искусственный wall-clock
    # интервал, тот же принцип, что у *_motion.py/cloud_forecast.py), тут
    # только подстраховка по subprocess-таймауту. До 3 WMS-запросов на
    # непустой цикл (CLM+IR+GC), 0 — на холостой. Вызывается ДО
    # check_eumetsat_frontal_track(), чтобы трекер видел свежий
    # eumetsat_west_watch.json в том же цикле (тот же порядок, что near-tier
    # cloud_forecast -> frontal_track).
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_west_watch.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_west_watch.py: {e}")


def check_eumetsat_frontal_track():
    # Трекинг фронтоподобных систем во времени (шаг 3 плана "Отслеживание
    # фронтов", см. docs/topics/eumetsat.md, 2026-08-14) — читает уже
    # готовый eumetsat_cloud_forecast.json (никаких WMS-запросов, чистая
    # локальная обработка), поэтому отдельный гейт по времени не нужен —
    # скрипт сам идемпотентен: если cloud_forecast.py не обновлялся с
    # прошлого запуска, тихо ничего не делает (см. докстринг скрипта).
    # Вызывается СРАЗУ после check_eumetsat_cloud_forecast(), чтобы всегда
    # видеть самые свежие candidates этого же цикла.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_frontal_track.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_frontal_track.py: {e}")


def check_eumetsat_render_track_overlay():
    # [ДОБАВЛЕНО 2026-08-19] Финальная покраска РЕАЛЬНОЙ формы фронта на
    # CLM-снимках (near+west) вместо PCA-эллипса — см. докстринг самого
    # скрипта и docs/topics/eumetsat.md, обсуждение 2026-08-19. Вызывается
    # СРАЗУ после check_eumetsat_frontal_track() — на этот момент
    # data/eumetsat_frontal_track.json уже содержит current_target_id для
    # треков этого кадра (без него красить нечего). Как и frontal_track.py,
    # чистая локальная обработка (без сети) — читает scratch-файлы,
    # написанные cloud_forecast.py/eumetsat_west_watch.py В ЭТОМ ЖЕ
    # прогоне, идемпотентен (если scratch-файлов нет — тихо пропускает
    # тайл, см. докстринг скрипта), отдельный гейт по времени не нужен.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_render_track_overlay.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_render_track_overlay.py: {e}")


def check_eumetsat_ground_station_verify():
    # Реальные наблюдения (SYNOP) по станциям "впереди"/"позади" активных
    # треков — план шага 5, пункт 4 (2026-08-15). Единственный шаг во всей
    # цепочке шага 5, который трогает сеть (ogimet + proxy-fallback), см.
    # докстринг eumetsat_ground_station_verify.py. Вызывается СРАЗУ после
    # check_eumetsat_frontal_track(), чтобы читать ahead_station/
    # behind_station из самого свежего кадра этого же цикла — результат
    # (ahead_obs/behind_obs) сам eumetsat_frontal_track.py подмешает в свой
    # вывод уже на СЛЕДУЮЩЕМ цикле (тот же принцип лага в один цикл, что у
    # has_precip/has_lightning). Таймаут 90с — как у остальных сетевых
    # шагов в этом файле; скрипт сам гейтит повторные запросы кешем
    # (STALE_MINUTES=45), так что за 90с почти всегда укладывается (fetch
    # нужен редко, чаще срабатывает кеш).
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_ground_station_verify.py")],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_ground_station_verify.py: {e}")


def check_eumetsat_precip_forecast():
    # Мини-прогноз движения осадков (msg_fes:h60b, 4 кадра). Гейт 15 мин.
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
    # Мини-прогноз движения грозовой активности (mtg_fd:li_afa, 4 кадра,
    # шаг 5 мин — обновляется чаще осадков/облаков). Гейт 5 мин.
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
    # Независимая оценка движения облачности по текстуре ИК-канала 10.5мкм
    # (mtg_fd:ir105_hrfi, персистентный буфер 6 кадров, шаг 10 мин) —
    # работает днём и ночью. Гейт 10 мин.
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
    # Тренд фазы облаков (mtg_fd:rgb_cloudphase) и грубой группы облачности
    # (mtg_fd:rgb_cloudtype) по HSV-анкерам — персистентный буфер до 13
    # кадров (2ч, шаг 10 мин, докачка 1 кадра/прогон). Не трекинг движения
    # (это делает Cloud Mask/IR), только качественный тренд фазы/группы.
    # Гейт 10 мин.
    #
    # НОЧЬЮ ПРОПУСКАЕМ ЦЕЛИКОМ (экономия времени пайплайна, запрос
    # 2026-08-14 "убрать лишнее"): ночная пара слоёв (Fog/Dust RGB) даёт
    # confirmed=None ВСЕГДА (не участвует в trio-голосовании существования
    # цели — см. eumetsat_cloud_phase_type.py, ветка is_day), и по решению
    # от 2026-08-13 Fog/Dust явно выведены из активного состава каналов
    # ("вне активного состава", докстринг docs/topics/eumetsat.md) — не
    # относятся к цели проекта (форма/движение фронтов). Функциональных
    # потерь нет: два WMS-запроса + классификация + запись буфера/файла
    # просто не тратятся зря всю ночь (~12ч из суток).
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
    # Motion + area-fraction по GeoColour RGB (mtg_fd:rgb_geocolour),
    # круглосуточно (день/ночь-гейт в самом скрипте). Персистентный буфер
    # 6 кадров (60 мин, шаг 10 мин). Гейт 10 мин.
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
    # MP4-петли (2ч) на каждый слой просмотрщика eumetsat.html — вместо
    # живой покадровой WMS-анимации в браузере (см. eumetsat_anim_render.py
    # docstring). Тяжелее остальных проверок (до ~9*13 GetMap-запросов на
    # широкий обзорный кадр), поэтому гейт реже — 20 мин, не 10-15.
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
    # Дальний контроль (~1000км, Балканы/Турция/Кавказ/Центр.Европа), см.
    # docstring eumetsat_far_watch.py — секторная сводка облачности, БЕЗ
    # векторного трекинга (на такой дистанции он даёт шум). Раньше был
    # отдельный workflow far_watch.yml со своим cron — отказались (лишняя
    # независимая цепочка триггеров вместо переиспользования этой).
    #
    # БАГ (2026-08-04, найден по скрину Руслана — данные зависли на 15+
    # часов): гейт раньше сравнивал os.path.getmtime(out_file) — а после
    # actions/checkout@v4 mtime ВСЕГДА "только что" (git checkout не
    # сохраняет исходное время коммита, выставляет текущее при клонировании
    # в свежем контейнере). Гейт "< 30 мин с момента mtime" был математически
    # ВСЕГДА true → скрипт никогда не перезапускался после самого первого
    # раза. Исправлено по образцу check_eumetsat_anim_render() — сравниваем
    # с временем ВНУТРИ самого JSON (payload["timestamp"]), не с файловой
    # системой.
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
    # Очень дальний контроль (~2500км, Испания/Италия/Британия) — раз в 3ч,
    # тот же гейт по содержимому JSON, что и check_eumetsat_far_watch()
    # (см. комментарий там про баг с mtime после checkout).
    out_file = os.path.join(BASE_DIR, "data", "eumetsat_very_far_watch.json")
    now_utc = datetime.now(timezone.utc)
    try:
        if os.path.exists(out_file):
            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("timestamp")
            if ts:
                last_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                if (now_utc - last_time).total_seconds() < 180 * 60:
                    return
    except Exception:
        pass
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_far_watch.py"), "very_far"],
            cwd=BASE_DIR, capture_output=False, timeout=90
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_far_watch.py very_far: {e}")


def git_push_satellite():
    """Коммитит и пушит только файлы спутникового модуля."""
    try:
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
            "data/eumetsat_frontal_track_state.json",
            "data/eumetsat_ground_station_verify.json",
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
            "data/anim/debug.json",
            "data/fog_calibration_log.jsonl",
            "data/eumetsat_target_summary.json",
            "data/eumetsat_target_false_positive_log.json",
            "data/eumetsat_skip_log.jsonl",
            "data/eumetsat_pipeline_health.json",
            "data/eumetsat_pipeline_alert_state.json",
        ]
        _to_add = [p for p in _candidates if os.path.exists(os.path.join(BASE_DIR, p))]
        if not _to_add:
            print("  Нет файлов для коммита.")
            return
        subprocess.run(["git", "-C", BASE_DIR, "add"] + _to_add,
                        check=True, capture_output=True)
        # data/anim/* — ОТДЕЛЬНО, директорией целиком, не поштучным списком
        # файлов (баг 2026-08-03): внутри вперемешку .mp4 (animated=True) и
        # .png (animated=False, см. eumetsat_anim_render.py), и когда слой
        # переключается video->image, старый файл УДАЛЯЕТСЯ с диска —
        # поштучный список "добавь X.mp4, если он существует" никогда не
        # видел эту ситуацию (сам путь X.mp4 просто исчезал из проверки
        # exists() ДО git add, а новый X.png в списке вообще не было
        # перечислено) — из-за этого fog.png молча терялся, а протухший
        # fog.mp4 навсегда оставался закоммиченным. Заодно всплыл более
        # старый баг: vis06.mp4 не был в поштучном списке вообще и никогда
        # не коммитился, даже до сегодняшних правок. "git add <директория>"
        # (без -A) в современном git сам покрывает добавления, изменения И
        # удаления путей внутри неё — за это отвечает git, а не наш список.
        subprocess.run(["git", "-C", BASE_DIR, "add", "data/anim"], capture_output=True)
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


def check_eumetsat_target_summary():
    # Слой конфликтов (см. docs/topics/eumetsat.md, план от 2026-08-04) —
    # только читает уже готовые JSON остальных 6 модулей и агрегирует,
    # никакого WMS-фетча, дёшево — гейта по времени не нужно, гоняем
    # каждый цикл, чтобы summary всегда отражал самое свежее состояние.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_target_summary.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_target_summary.py: {e}")


def check_eumetsat_render_systems_overlay():
    # [ДОБАВЛЕНО 2026-09-02] Покраска РЕАЛЬНЫХ пикселей ВСЕХ систем
    # синоптического масштаба (снапшот текущего цикла, не персистентные
    # frontlike-треки) — см. докстринг eumetsat_render_systems_overlay.py.
    # ВАЖНО: вызывается ПОСЛЕ check_eumetsat_target_summary() (не сразу
    # после check_eumetsat_render_track_overlay(), как для треков) —
    # system_candidates нужны уже ПРОФИЛЬТРОВАННЫМИ по видимости ИК/
    # GeoColour (это делает eumetsat_target_summary.py), иначе красили бы
    # неподтверждённый шум, который таблица на фронтенде и так не
    # показывает. Near-tier scratch-файлы (_scratch_clm_base.png/
    # _scratch_clm_pixelmap.npy), записанные check_eumetsat_cloud_forecast()
    # в начале ЭТОГО ЖЕ прогона, к этому моменту ещё не тронуты — ни один
    # промежуточный шаг их не удаляет и не перезаписывает.
    try:
        subprocess.run(
            [PYTHON, os.path.join(SCRIPTS_DIR, "eumetsat_render_systems_overlay.py")],
            cwd=BASE_DIR, capture_output=False, timeout=30
        )
    except Exception as e:
        print(f"  [WARN] eumetsat_render_systems_overlay.py: {e}")


def check_pipeline_health_alert():
    # Алерт "источник (EUMETSAT) застрял" — реакция на инцидент 2026-08-18
    # (см. docs/topics/eumetsat.md): ~75 мин без новых кадров msg_fes:clm
    # совпали с проходом реального фронта, пайплайн ничего не написал и
    # никто об этом не узнал до разбора постфактум. Порог — обсуждён и
    # согласован явно: 3 подряд "источник не дал данных" (source_stale/
    # duplicate_frame, см. field_motion_common.record_pipeline_health) на
    # ЛЮБОМ из 6 скриптов с инкрементальным буфером = ~45 мин простоя.
    # next_frame_not_ready/capabilities_unavailable в счётчик НЕ входят —
    # это единичные сетевые сбои запроса, сами разрешаются на следующем
    # прогоне, включать их сделало бы алерт слишком шумным.
    N_CONSECUTIVE_STALE_FOR_ALERT = 3
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


def main():
    print(f"\n{'─'*52}")
    print(f"  [SATELLITE] Цикл спутникового модуля  {datetime.now(timezone.utc).strftime('%d.%m %H:%M UTC')}")
    print(f"{'─'*52}\n")

    # check_eumetsat_point() убран из цикла 2026-08-14 ("убрать всё лишнее,
    # сократить время"): eumetsat_point.json писался, но НИ ОДИН html/js
    # файл его не читает (проверено code search по репозиторию) — мёртвый
    # шаг с эпохи RainViewer-сравнения (RainViewer давно удалён из
    # nearby.html, см. память проекта). Функция check_eumetsat_point()
    # оставлена в файле неиспользуемой — если понадобится, легко вернуть
    # вызов обратно.
    check_eumetsat_cloud_forecast()
    check_eumetsat_west_watch()
    check_eumetsat_frontal_track()
    check_eumetsat_render_track_overlay()
    check_eumetsat_ground_station_verify()
    check_eumetsat_cloud_phase_type()
    check_eumetsat_precip_forecast()
    check_eumetsat_lightning_forecast()
    check_eumetsat_ir_motion()
    check_eumetsat_precip_motion()
    check_eumetsat_geocolour_motion()
    check_eumetsat_target_summary()
    check_eumetsat_render_systems_overlay()
    # check_eumetsat_anim_render() убран из цикла 2026-08-16 (решение: закрыть
    # eumetsat.html/визуальный браузер снимков, сосредоточиться на nearby.html
    # и детекте фронтов — самый тяжёлый шаг пайплайна, до 600с, 12 слоёв x
    # до 13 GetMap-запросов). Функция и её выход (data/anim/*) НЕ удалены —
    # оставлена возможность вернуть вызов обратно одной строкой, если
    # понадобится визуальный браузер снова.
    check_eumetsat_far_watch()
    check_eumetsat_very_far_watch()

    check_pipeline_health_alert()
    git_push_satellite()


if __name__ == "__main__":
    main()


