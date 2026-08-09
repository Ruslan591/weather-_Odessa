"""
eumetsat_target_summary.py — слой конфликтов object-centric пайплайна
(см. docs/topics/eumetsat.md, план от 2026-08-04).

Читает primary target (candidates[0]) из data/eumetsat_cloud_forecast.json
и target_confirmation из пяти остальных модулей (ir_motion, geocolour_motion,
cloud_phase_type, precip_forecast, lightning_forecast), сводит в ОДНО место:
data/eumetsat_target_summary.json — вместо ручной сверки 5 файлов.

Два разных вопроса разведены явно, не смешиваются в одну цифру:
  1. "СУЩЕСТВУЕТ ЛИ вообще цель" — трио ir/geocolour/cloud_phase_type
     (порог confirmed у каждого — >=50% ROI). Если они расходятся (кто-то
     confirmed=true, кто-то false) — это КОНФЛИКТ, помечается явно
     ("disputed"), а не тихо усредняется.
  2. "Что происходит В этой (уже подтверждённой или нет) цели" — precip и
     lightning, у них принципиально другие (низкие) пороги — это не
     "согласие/несогласие с существованием", а отдельные да/нет-факты.

Ничего не пересчитывает заново — только читает готовые JSON остальных
модулей и агрегирует. Если primary target отсутствует (пустой candidates)
или какой-то модуль ещё не отработал/не успел — пишет частичный summary,
не падает.

Пишет data/eumetsat_target_summary.json.
"""

import json
import math
import os
from datetime import datetime, timezone

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_FILE = os.path.join(DATA_DIR, "eumetsat_target_summary.json")

# Трио, отвечающее на вопрос "существует ли цель" (порог 0.5 у каждого)
EXISTENCE_MODULES = {
    "ir_motion": "eumetsat_ir_motion.json",
    "geocolour_motion": "eumetsat_geocolour_motion.json",
    "cloud_phase_type": "eumetsat_cloud_phase_type.json",
}
# Отдельные да/нет-факты про уже найденную цель (разные низкие пороги)
PHENOMENON_MODULES = {
    "precip_forecast": "eumetsat_precip_forecast.json",
    "lightning_forecast": "eumetsat_lightning_forecast.json",
}


def _load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _load_system_enrichment(system_target_id):
    """Обогащающий (не voting) анализ системы синоптического масштаба —
    читает system_analysis из cloud_phase_type/precip_forecast/
    lightning_forecast.json (см. docs/topics/eumetsat.md, обсуждение
    2026-08-06: система не проходит через существование-конфирмейшн трио,
    но полезно знать, что внутри неё — фаза/тип, осадки, гроза).
    Сверяет target_id с тем, что в system_info, — если модуль отработал по
    другой ближайшей системе (например snapshot cloud_forecast обновился
    между прогонами разных скриптов), не приписываем чужие данные."""
    enrichment = {}
    phase_data = _load_json("eumetsat_cloud_phase_type.json")
    sa = (phase_data or {}).get("system_analysis") or {}
    if sa.get("available") and sa.get("target_id") == system_target_id:
        enrichment["phase_label"] = sa.get("roi_dominant_phase_label")
        enrichment["cloud_fraction"] = sa.get("roi_cloud_fraction")

    precip_data = _load_json("eumetsat_precip_forecast.json")
    sa = (precip_data or {}).get("system_analysis") or {}
    if sa.get("available") and sa.get("target_id") == system_target_id:
        enrichment["has_precip"] = sa.get("has_precip")

    lightning_data = _load_json("eumetsat_lightning_forecast.json")
    sa = (lightning_data or {}).get("system_analysis") or {}
    if sa.get("available") and sa.get("target_id") == system_target_id:
        enrichment["has_lightning"] = sa.get("has_lightning")

    return enrichment


def _is_night(t_iso_seconds_format):
    """Локальная проверка ночи под формат таймстемпов ЭТИХ JSON
    (%Y-%m-%dT%H:%M:%SZ — с секундами, без .000) — НЕ то же самое, что
    fc.is_daytime(), который завязан на другой формат (WMS-время слоя,
    всегда :00.000Z) и трогать его контракт ради одного вызова здесь не
    стоит. Та же грубая эвристика (UTC+3, без сезонной точности)."""
    try:
        dt = datetime.strptime(t_iso_seconds_format, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    local_hour = (dt.hour + 3) % 24
    return not (5 <= local_hour < 20)


def main():
    now = datetime.now(timezone.utc)
    cf = _load_json("eumetsat_cloud_forecast.json")

    if cf is None:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "no_data",
            "reason": "eumetsat_cloud_forecast.json недоступен",
        }
        _write(out)
        print("  [WARN] eumetsat_target_summary.py: cloud_forecast.json недоступен")
        return

    candidates = cf.get("candidates") or []
    if not candidates:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "no_target",
            "reason": "candidates пуст — значимых облачных масс в радиусе 192км сейчас нет",
        }
        _write(out)
        print("  [OK] eumetsat_target_summary.py: целей нет")
        return

    # class отсутствует у снапшотов ДО 2026-08-05 — трактуем как "local"
    # для обратной совместимости (тот же приём, что в fc.load_primary_target).
    local_candidates = [c for c in candidates if c.get("class", "local") == "local"]
    system_candidates = [c for c in candidates if c.get("class", "local") == "system"]

    system_info = None
    if system_candidates:
        sys_c = system_candidates[0]  # ближайшая система (список уже отсортирован по расстоянию)
        s_bearing, s_compass = fc.bearing_compass(sys_c["centroid_dx_km"], sys_c["centroid_dy_km"])
        s_distance = math.hypot(sys_c["centroid_dx_km"], sys_c["centroid_dy_km"])
        system_info = {
            "target_id": sys_c["target_id"],
            "area_km2": sys_c["area_km2"],
            "distance_km": round(s_distance, 1),
            "bearing_deg": round(s_bearing, 0),
            "compass": s_compass,
            # Черновая эвристика "похоже на фронт" (PCA aspect ratio формы
            # blob'а), см. eumetsat_cloud_forecast.py::_blob_elongation и
            # docs/topics/eumetsat.md, "Идея на будущее: отслеживание фронтов".
            # Поля отсутствуют у снапшотов до этой правки — .get() на чтении.
            # elongation_axis_deg — точный градус ОСИ (0..180) рядом с
            # компасной меткой (та округляется до одного из 8 направлений,
            # шаг 45° — метка одна может отличаться от реального угла до
            # ±22°, добавлено по запросу 2026-08-09 после разбора живого
            # кейса, где ось "не совсем СЗ, не совсем С-Ю").
            "elongation_aspect_ratio": sys_c.get("elongation_aspect_ratio"),
            "elongation_axis_deg": sys_c.get("elongation_axis_deg"),
            "elongation_axis_compass": sys_c.get("elongation_axis_compass"),
            "frontlike": sys_c.get("frontlike", False),
        }
        system_info.update(_load_system_enrichment(sys_c["target_id"]))

    # Список ВСЕХ систем (не только ближайшей) — по запросу 2026-08-09:
    # раньше дальние системы (target_id 5/9/10/12 и т.д. в реальном прогоне)
    # были посчитаны (candidates уже содержит elongation/frontlike у КАЖДОГО
    # кандидата), но нигде не показывались — verdict текст собирается только
    # для ближайшей system_info. Это отдельный, более лёгкий список —
    # обогащение (фаза/осадки/гроза) сюда НЕ подмешивается (то ROI-сверка,
    # которая делается только для ближайшей системы в _load_system_enrichment,
    # тащить её на каждую систему было бы дорого и не нужно для таблицы).
    # Обогащение (фаза/осадки/гроза) ПО КАЖДОЙ системе — по запросу
    # 2026-08-09 ("подтверждение от остальных каналов, как для локальных
    # очагов, для каждой системы"). Три источника пишут system_analysis_all
    # (список по всем target_id, см. eumetsat_cloud_phase_type.py/
    # eumetsat_precip_forecast.py/eumetsat_lightning_forecast.py) — тут
    # просто собираем по target_id в словари для быстрого lookup.
    def _by_target_id(data, key):
        rows = (data or {}).get("system_analysis_all") or []
        return {r["target_id"]: r for r in rows if key is None or key in r}

    phase_by_id = _by_target_id(_load_json("eumetsat_cloud_phase_type.json"), "roi_dominant_phase_label")
    # Type — ДРУГОЙ слой (Cloud Type RGB), отдельный от Phase (Cloud Phase
    # RGB), см. запрос 2026-08-09 "Фаза и тип вместе будут? Это разные
    # каналы". Тот же файл содержит оба поля в одном элементе
    # system_analysis_all, поэтому источник данных (data) один и тот же —
    # только ключ для непустого-проверки другой.
    type_by_id = _by_target_id(_load_json("eumetsat_cloud_phase_type.json"), "roi_dominant_type_label")
    precip_by_id = _by_target_id(_load_json("eumetsat_precip_forecast.json"), "has_precip")
    lightning_by_id = _by_target_id(_load_json("eumetsat_lightning_forecast.json"), "has_lightning")
    # ИК и естественный свет (GeoColour) — по запросу 2026-08-09, тот же
    # смысл, что у trio-подтверждения локальных целей, но тут не voting.
    ir_by_id = _by_target_id(_load_json("eumetsat_ir_motion.json"), "roi_contrast_sigma")
    geocolour_by_id = _by_target_id(_load_json("eumetsat_geocolour_motion.json"), "roi_cloud_fraction")

    system_candidates_list = []
    for c in system_candidates:
        tid = c["target_id"]
        entry = {
            "target_id": tid,
            "area_km2": c["area_km2"],
            "distance_km": round(math.hypot(c["centroid_dx_km"], c["centroid_dy_km"]), 1),
            "bearing_deg": round(fc.bearing_compass(c["centroid_dx_km"], c["centroid_dy_km"])[0], 0),
            "compass": fc.bearing_compass(c["centroid_dx_km"], c["centroid_dy_km"])[1],
            "elongation_aspect_ratio": c.get("elongation_aspect_ratio"),
            "elongation_axis_deg": c.get("elongation_axis_deg"),
            "elongation_axis_compass": c.get("elongation_axis_compass"),
            "frontlike": c.get("frontlike", False),
        }
        ph = phase_by_id.get(tid)
        entry["phase_label"] = ph.get("roi_dominant_phase_label") if ph else None
        pr = precip_by_id.get(tid)
        entry["has_precip"] = pr.get("has_precip") if pr else None
        lt = lightning_by_id.get(tid)
        entry["has_lightning"] = lt.get("has_lightning") if lt else None
        ir = ir_by_id.get(tid)
        entry["ir_confirmed"] = ir.get("confirmed") if ir else None
        gc = geocolour_by_id.get(tid)
        entry["geocolour_confirmed"] = gc.get("confirmed") if gc else None
        system_candidates_list.append(entry)

    if not local_candidates:
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "system_only",
            "reason": "локальных компактных масс нет, есть только система(ы) синоптического масштаба",
            "cloud_forecast_timestamp": cf.get("timestamp"),
            "system": system_info,
            "system_candidates": system_candidates_list,
        }
        out["verdict"] = _build_system_only_verdict(system_info)
        _write(out)
        print(f"  [OK] eumetsat_target_summary.py: только система, {out['verdict']}")
        return

    # Выбор локальной цели с учётом реестра повторяющихся ложных срабатываний
    # CLM (см. docs/topics/eumetsat.md, запись от 2026-08-07) — вместо
    # local_candidates[0] напрямую пропускаем известные шумовые сигнатуры.
    fp_log = fc.load_false_positive_log()
    target, suppressed = fc.pick_local_target(local_candidates, fp_log)

    if target is None:
        # Все local-кандидаты в этом цикле — известные шумовые объекты
        # (excluded). Ни один из 5 модулей ROI-подтверждения тоже не
        # получит цель в этом цикле (они ходят через тот же fc.load_primary_target()),
        # поэтому реестр здесь НЕ обновляем — не было ни одной новой проверки.
        s_bearing, s_compass = fc.bearing_compass(suppressed["centroid_dx_km"], suppressed["centroid_dy_km"])
        s_distance = math.hypot(suppressed["centroid_dx_km"], suppressed["centroid_dy_km"])
        entry = fp_log.get(suppressed["false_positive_signature"], {})
        suppressed_info = {
            "signature": suppressed["false_positive_signature"],
            "area_km2": suppressed["area_km2"],
            "distance_km": round(s_distance, 1),
            "bearing_deg": round(s_bearing, 0),
            "compass": s_compass,
            "not_confirmed_streak": entry.get("not_confirmed_streak"),
            "total_not_confirmed": entry.get("total_not_confirmed"),
            "excluded_since": entry.get("excluded_since"),
        }
        out = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "suppressed_known_false_positive",
            "cloud_forecast_timestamp": cf.get("timestamp"),
            "suppressed_target": suppressed_info,
            "system": system_info,
            "system_candidates": system_candidates_list,
        }
        out["verdict"] = _build_suppressed_verdict(suppressed_info, system_info)
        _write(out)
        print(f"  [OK] eumetsat_target_summary.py: подавлено (известный шумовой объект), {out['verdict']}")
        return

    bearing_deg, compass_dir = fc.bearing_compass(target["centroid_dx_km"], target["centroid_dy_km"])
    distance_km = math.hypot(target["centroid_dx_km"], target["centroid_dy_km"])

    out = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
        "cloud_forecast_timestamp": cf.get("timestamp"),
        "target_id": target["target_id"],
        "target_area_km2": target["area_km2"],
        "target_distance_km": round(distance_km, 1),
        "target_bearing_deg": round(bearing_deg, 0),
        "target_compass": compass_dir,
        "system": system_info,
        "system_candidates": system_candidates_list,
    }
    if suppressed is not None:
        # Ближе есть известный шумовой объект, но он подавлен — выбрана
        # следующая по расстоянию нормальная цель. Пишем для прозрачности,
        # не влияет на verdict основной цели.
        out["also_suppressed_nearby"] = {
            "signature": suppressed["false_positive_signature"],
            "area_km2": suppressed["area_km2"],
        }

    # --- движение цели (скорость/направление/ETA/CPA) — берём из ТОГО ЖЕ
    # cloud_forecast.json, если он сейчас смотрит на тот же самый объект
    # (target_id+class совпадают): с 2026-08-08 выбор "ближайшего облака" в
    # cloud_forecast.py синхронизирован с тем же реестром подавления, что и
    # выбор здесь (см. docs/topics/eumetsat.md), так что чаще всего это одна
    # и та же цель — но при рассинхроне снапшотов (гонка обновлений между
    # прогонами) можем и не совпасть, тогда просто не показываем движение.
    if cf.get("target_id") == target["target_id"] and cf.get("class") == "local" and cf.get("speed_kmh") is not None:
        out["target_movement"] = {
            "speed_kmh": cf["speed_kmh"],
            "direction_compass": cf.get("direction_compass"),
            "cpa_km": cf.get("cpa_km"),
            "eta_min": cf.get("eta_min"),
            "verdict": cf.get("verdict"),
        }

    # --- существование цели: трио ir/geocolour/phase_type ---
    existence = {}
    votes_true = 0
    votes_false = 0
    target_phase = None
    for key, filename in EXISTENCE_MODULES.items():
        data = _load_json(filename)
        tc = (data or {}).get("target_confirmation")
        if tc is None:
            existence[key] = {"confirmed": None, "reason": "модуль недоступен или ещё не отработал"}
            continue
        confirmed = tc.get("confirmed")
        existence[key] = {
            "confirmed": confirmed,
            "timestamp": data.get("timestamp"),
        }
        if confirmed is True:
            votes_true += 1
        elif confirmed is False:
            votes_false += 1
        # Вид облаков (фаза) — данные уже посчитаны cloud_phase_type.py для
        # ROI этой же цели (target_confirmation.roi_dominant_phase_label),
        # просто раньше не пробрасывались в текст "Итога" (см.
        # docs/topics/eumetsat.md, запись 2026-08-08).
        if key == "cloud_phase_type" and tc.get("roi_dominant_phase_label"):
            target_phase = {
                "label": tc["roi_dominant_phase_label"],
                "cloud_fraction": tc.get("roi_cloud_fraction"),
            }
    if target_phase is not None:
        out["target_phase"] = target_phase

    total_voted = votes_true + votes_false
    if total_voted == 0:
        consensus = "insufficient_data"
    elif votes_false == 0:
        consensus = "confirmed"
    elif votes_true == 0:
        consensus = "not_confirmed"
    else:
        consensus = "disputed"  # ключевой случай — именно он раньше терялся

    out["existence"] = {
        "modules": existence,
        "votes_confirmed": votes_true,
        "votes_not_confirmed": votes_false,
        "consensus": consensus,
    }

    # --- отдельные да/нет-факты про цель ---
    phenomena = {}
    for key, filename in PHENOMENON_MODULES.items():
        data = _load_json(filename)
        tc = (data or {}).get("target_confirmation")
        if tc is None:
            phenomena[key] = {"confirmed": None, "reason": "модуль недоступен или ещё не отработал"}
        else:
            phenomena[key] = {"confirmed": tc.get("confirmed"), "timestamp": data.get("timestamp")}
    out["phenomena"] = phenomena

    # --- человекочитаемый текстовый вывод (шаг 7, rule-based первая версия) ---
    out["verdict"] = _build_verdict(out)

    # --- обновление реестра ложных срабатываний по итогам ЭТОЙ проверки ---
    # (см. docs/topics/eumetsat.md, запись от 2026-08-07). Апдейт только
    # здесь — единственный писатель файла, чтобы не было гонки коммитов
    # между модулями.
    sig = fc.false_positive_signature(target["centroid_dx_km"], target["centroid_dy_km"])
    fp_log[sig] = _update_false_positive_entry(fp_log.get(sig), consensus, out["timestamp"])
    fc.save_false_positive_log(fp_log)

    _write(out)
    print(f"  [OK] eumetsat_target_summary.py: {consensus} "
          f"({votes_true} за / {votes_false} против), {out['verdict']}")


def _update_false_positive_entry(entry, consensus, now_iso):
    """Streak-логика по аналогии с уже принятой в проекте для PWS-давления
    (2 последовательные проверки в одном направлении). Здесь: 3 not_confirmed
    подряд -> excluded (порог согласован с пользователем 2026-08-07),
    2 confirmed/disputed подряд -> снова active. disputed трактуется как
    "было хотя бы одно подтверждение" — не копит streak к исключению,
    поскольку хотя бы один канал видел цель реальной. insufficient_data
    сюда никогда не попадает — эта функция вызывается только когда target
    реально прошёл through существование-проверку (см. main())."""
    entry = dict(entry) if entry else {
        "not_confirmed_streak": 0,
        "confirmed_streak": 0,
        "total_not_confirmed": 0,
        "total_confirmed": 0,
        "status": "active",
    }
    if consensus == "not_confirmed":
        entry["not_confirmed_streak"] = entry.get("not_confirmed_streak", 0) + 1
        entry["confirmed_streak"] = 0
        entry["total_not_confirmed"] = entry.get("total_not_confirmed", 0) + 1
        if entry["not_confirmed_streak"] >= fc.FALSE_POSITIVE_STREAK_THRESHOLD:
            # Ставим/обновляем excluded_since даже если статус уже был
            # excluded — если мы вообще досюда дошли, значит объект только
            # что прошёл повторную проверку (TTL истёк) и снова не
            # подтвердился: перезапускаем TTL-таймер на новый цикл ожидания.
            entry["status"] = "excluded"
            entry["excluded_since"] = now_iso
    elif consensus in ("confirmed", "disputed"):
        entry["confirmed_streak"] = entry.get("confirmed_streak", 0) + 1
        entry["not_confirmed_streak"] = 0
        if consensus == "confirmed":
            entry["total_confirmed"] = entry.get("total_confirmed", 0) + 1
        if entry["confirmed_streak"] >= fc.FALSE_POSITIVE_REACTIVATE_STREAK:
            entry["status"] = "active"
            entry.pop("excluded_since", None)
    entry["last_seen"] = now_iso
    return entry


def _build_suppressed_verdict(suppressed_info, system_info):
    """Вердикт, когда единственный/ближайший local-кандидат — уже известный
    шумовой объект, подавленный по реестру ложных срабатываний (см.
    docs/topics/eumetsat.md, запись от 2026-08-07)."""
    base = (f"Известный шумовой объект в {suppressed_info['distance_km']:.0f}км "
            f"{suppressed_info['compass']} (~{suppressed_info['area_km2']:.0f}км²) — "
            f"подавлено (не подтверждался {suppressed_info['not_confirmed_streak']} раз подряд).")
    if system_info:
        base += " Отдельно: " + _system_sentence(system_info)
    return base


def _build_verdict(out):
    """Rule-based текстовый синтез шага 7 — первая версия. Собирает всё
    выше в одно связное предложение. AI-генерация как опция позже, если
    понадобится более живой текст (см. docs/topics/eumetsat.md)."""
    ex = out["existence"]
    consensus = ex["consensus"]
    dist = out["target_distance_km"]
    compass = out["target_compass"]
    area = out["target_area_km2"]
    phase = out.get("target_phase")
    phase_str = f", {phase['label']}" if phase else ""

    if consensus == "confirmed":
        base = f"Облачная масса ({area:.0f}км²{phase_str}) в {dist:.0f}км {compass} подтверждена всеми доступными каналами."
    elif consensus == "not_confirmed":
        base = f"CLM отметил цель в {dist:.0f}км {compass}, но остальные каналы облачность там не видят — вероятно, ложное срабатывание."
    elif consensus == "disputed":
        agree = [k for k, v in ex["modules"].items() if v.get("confirmed") is True]
        disagree = [k for k, v in ex["modules"].items() if v.get("confirmed") is False]
        night_hint = ""
        if _is_night(out["cloud_forecast_timestamp"] or out["timestamp"]) and "cloud_phase_type" in disagree:
            night_hint = " (ночь — rgb_cloudphase/rgb_cloudtype дают систематическое ложное «безоблачно» без солнечного света, см. docs/topics/eumetsat.md)"
        base = (f"Цель в {dist:.0f}км {compass}{phase_str} — каналы расходятся: "
                f"{'/'.join(agree) or '—'} подтверждают, {'/'.join(disagree) or '—'} нет"
                f"{night_hint}.")
    else:
        base = f"Цель в {dist:.0f}км {compass} — недостаточно данных для подтверждения."

    # --- движение (скорость/направление/куда идёт/через сколько дойдёт) —
    # только если существование подтверждено хотя бы частично (нет смысла
    # описывать движение объекта, который сами каналы не видят).
    move = out.get("target_movement")
    if move and consensus in ("confirmed", "disputed"):
        v = move["verdict"]
        if v in ("приближается", "уже у города"):
            eta_str = f"~{round(move['eta_min'])} мин" if move.get("eta_min") is not None else "скоро"
            base += f" Движется в сторону станции, {eta_str} до сближения (~{move['speed_kmh']:.0f} км/ч)."
        elif v == "пройдёт мимо, город, скорее всего, не заденет":
            base += (f" Идёт на {move.get('direction_compass') or '?'} со скоростью "
                     f"~{move['speed_kmh']:.0f} км/ч, пройдёт мимо на ≈{move.get('cpa_km', 0):.0f}км, "
                     f"город, скорее всего, не заденет.")
        elif v == "удаляется":
            base += f" Удаляется (~{move['speed_kmh']:.0f} км/ч)."
        elif v == "почти стоит на месте":
            base += " Почти не движется."

    precip = out["phenomena"].get("precip_forecast", {}).get("confirmed")
    lightning = out["phenomena"].get("lightning_forecast", {}).get("confirmed")
    extras = []
    if precip is True:
        extras.append("наблюдаются осадки")
    if lightning is True:
        extras.append("зафиксирована гроза")
    if extras:
        base += " " + ", ".join(extras).capitalize() + "."

    if out.get("system"):
        base += " Отдельно: " + _system_sentence(out["system"])
    return base


def _system_sentence(s, capitalize=False):
    """Общий текст про систему синоптического масштаба — используется и в
    основном verdict (система найдена вместе с локальной целью), и в
    system_only. Дописывает обогащение (фаза/осадки/гроза), если оно
    доступно (см. docs/topics/eumetsat.md, обсуждение 2026-08-06) — само
    существование системы не подтверждается отдельно (не нужно при такой
    площади), это только описание содержимого."""
    word = "Система" if capitalize else "система"
    base = (f"{word} синоптического масштаба ({s['area_km2']:.0f}км²) "
            f"в {s['distance_km']:.0f}км {s['compass']}")
    extras = []
    if s.get("frontlike"):
        axis = s.get("elongation_axis_compass")
        deg = s.get("elongation_axis_deg")
        deg_str = f" ({deg:.0f}°)" if deg is not None else ""
        extras.append(f"вытянута {axis}{deg_str}, похоже на фронт" if axis else "похоже на фронт")
    if s.get("phase_label") and s["phase_label"] != "безоблачно":
        extras.append(s["phase_label"])
    if s.get("has_precip") is True:
        extras.append("осадки")
    if s.get("has_lightning") is True:
        extras.append("гроза")
    if extras:
        base += " (" + ", ".join(extras) + ")"
    return base + "."


def _build_system_only_verdict(system_info):
    """Случай, когда локальных компактных масс нет, но есть крупная
    система — она не проходит через ROI-подтверждение (см. комментарий в
    fc.load_primary_target), просто сообщаем факт (+ обогащение, если есть)."""
    if system_info is None:
        return "Целей нет."
    return "Локальных облачных масс нет. " + _system_sentence(system_info, capitalize=True)


def _write(out):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

