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

    target = candidates[0]
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
    }

    # --- существование цели: трио ir/geocolour/phase_type ---
    existence = {}
    votes_true = 0
    votes_false = 0
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

    _write(out)
    print(f"  [OK] eumetsat_target_summary.py: {consensus} "
          f"({votes_true} за / {votes_false} против), {out['verdict']}")


def _build_verdict(out):
    """Rule-based текстовый синтез шага 7 — первая версия. Собирает всё
    выше в одно связное предложение. AI-генерация как опция позже, если
    понадобится более живой текст (см. docs/topics/eumetsat.md)."""
    ex = out["existence"]
    consensus = ex["consensus"]
    dist = out["target_distance_km"]
    compass = out["target_compass"]
    area = out["target_area_km2"]

    if consensus == "confirmed":
        base = f"Облачная масса ({area:.0f}км²) в {dist:.0f}км {compass} подтверждена всеми доступными каналами."
    elif consensus == "not_confirmed":
        base = f"CLM отметил цель в {dist:.0f}км {compass}, но остальные каналы облачность там не видят — вероятно, ложное срабатывание."
    elif consensus == "disputed":
        agree = [k for k, v in ex["modules"].items() if v.get("confirmed") is True]
        disagree = [k for k, v in ex["modules"].items() if v.get("confirmed") is False]
        night_hint = ""
        if _is_night(out["cloud_forecast_timestamp"] or out["timestamp"]) and "cloud_phase_type" in disagree:
            night_hint = " (ночь — rgb_cloudphase/rgb_cloudtype дают систематическое ложное «безоблачно» без солнечного света, см. docs/topics/eumetsat.md)"
        base = (f"Цель в {dist:.0f}км {compass} — каналы расходятся: "
                f"{'/'.join(agree) or '—'} подтверждают, {'/'.join(disagree) or '—'} нет"
                f"{night_hint}.")
    else:
        base = f"Цель в {dist:.0f}км {compass} — недостаточно данных для подтверждения."

    precip = out["phenomena"].get("precip_forecast", {}).get("confirmed")
    lightning = out["phenomena"].get("lightning_forecast", {}).get("confirmed")
    extras = []
    if precip is True:
        extras.append("наблюдаются осадки")
    if lightning is True:
        extras.append("зафиксирована гроза")
    if extras:
        base += " " + ", ".join(extras).capitalize() + "."
    return base


def _write(out):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
