#!/usr/bin/env python3
"""
calc_model_bias.py — расчёт bias/MAE/RMSE для каждой модели отдельно.

Читает data/modeldata/YYYY_MM.json (уже есть на устройстве).
Пишет data/model_bias.json.

Запуск:
    cd /storage/emulated/0/Documents/weather
    python3 scripts/calc_model_bias.py

Опционально — ограничить период:
    MONTHS=6 python3 scripts/calc_model_bias.py   # только последние 6 месяцев
"""

import os, json, math, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Конфиг ───────────────────────────────────────────────────────────────────
BASE_DIR      = Path("/storage/emulated/0/Documents/weather")
MODELDATA_DIR = BASE_DIR / "data" / "modeldata"
OUT_PATH      = BASE_DIR / "data" / "model_bias.json"

# Если задана переменная окружения MONTHS=N — берём только последние N месяцев
LIMIT_MONTHS  = int(os.environ.get("MONTHS", 0))

SEASON_MAP = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3:  "MAM", 4: "MAM", 5: "MAM",
    6:  "JJA", 7: "JJA", 8: "JJA",
    9:  "SON", 10:"SON", 11:"SON",
}

# Параметры: (поле в models{}, поле в obs{})
PARAM_MAP = {
    "temp":       ("temp",       "temp"),
    "pressure":   ("pressure",   "pressure"),
    "wind":       ("wind",       "wind"),
    "windDir":    ("windDir",    "windDir"),
    "cloudcover": ("cloudcover", "cloudcover"),
    "visibility": ("visibility", "visibility"),
}

# ── Утилиты ──────────────────────────────────────────────────────────────────
def angle_diff_signed(fc, obs):
    """Знаковая разница углов: fc - obs ∈ (-180, 180]."""
    return ((fc - obs + 180) % 360) - 180

def calc_err(fc_val, obs_val, param):
    """Возвращает (err, ae) или None."""
    if fc_val is None or obs_val is None:
        return None
    if param == "windDir":
        err = angle_diff_signed(fc_val, obs_val)
    else:
        err = fc_val - obs_val
    return err, abs(err)

def empty_stats():
    return {"sum_err": 0.0, "sum_ae": 0.0, "sum_sq": 0.0, "n": 0}

def add_to(s, err, ae):
    s["sum_err"] += err
    s["sum_ae"]  += ae
    s["sum_sq"]  += ae * ae
    s["n"]       += 1

def finalize_stats(s):
    n = s["n"]
    if n == 0:
        return None
    return {
        "bias": round(s["sum_err"] / n, 3),
        "mae":  round(s["sum_ae"]  / n, 3),
        "rmse": round(math.sqrt(s["sum_sq"] / n), 3),
        "n":    n,
    }

# ── Загрузка записей ─────────────────────────────────────────────────────────
def load_records():
    if not MODELDATA_DIR.exists():
        log.error("Папка не найдена: %s", MODELDATA_DIR)
        return []

    files = sorted(MODELDATA_DIR.glob("*.json"))
    log.info("Файлов найдено: %d", len(files))

    if LIMIT_MONTHS:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LIMIT_MONTHS * 30)
        cutoff_str = cutoff.strftime("%Y_%m")
        files = [f for f in files if f.stem >= cutoff_str]
        log.info("После фильтра MONTHS=%d: %d файлов", LIMIT_MONTHS, len(files))

    all_records = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                recs = json.load(f)
            log.info("  %s: %d записей", path.name, len(recs))
            all_records.extend(recs)
        except Exception as e:
            log.warning("  ✗ %s: %s", path.name, e)

    return all_records

# ── Основной расчёт ──────────────────────────────────────────────────────────
def compute_bias(all_records):
    """
    Возвращает структуру:
    {
      model_id: {
        "overall":  {param: stats},
        "bySeason": {season: {param: stats}},
        "byMonth":  {"01"…"12": {param: stats}},
        "byHour":   {"0","3","6",…,"21": {param: stats}},
      }
    }
    """
    # Накопители: [model][bucket_type][bucket_key][param] = empty_stats()
    accum = {}

    skipped = 0
    total   = 0

    for rec in all_records:
        st = rec.get("synopTime", "")
        if len(st) < 10:
            skipped += 1
            continue
        try:
            y   = int(st[:4])
            mo  = int(st[4:6])
            hh  = int(st[8:10])
        except Exception:
            skipped += 1
            continue

        season    = SEASON_MAP.get(mo)
        month_key = f"{mo:02d}"
        hour_key  = str(hh)

        obs    = rec.get("obs", {})
        models = rec.get("models", {})

        for mid, mdata in models.items():
            if mid not in accum:
                accum[mid] = {
                    "overall":  {},
                    "bySeason": {},
                    "byMonth":  {},
                    "byHour":   {},
                }
            m = accum[mid]

            for param, (fc_field, obs_field) in PARAM_MAP.items():
                fc_val  = mdata.get(fc_field)
                obs_val = obs.get(obs_field)
                result  = calc_err(fc_val, obs_val, param)
                if result is None:
                    continue
                err, ae = result

                # overall
                m["overall"].setdefault(param, empty_stats())
                add_to(m["overall"][param], err, ae)

                # bySeason
                if season:
                    m["bySeason"].setdefault(season, {}).setdefault(param, empty_stats())
                    add_to(m["bySeason"][season][param], err, ae)

                # byMonth
                m["byMonth"].setdefault(month_key, {}).setdefault(param, empty_stats())
                add_to(m["byMonth"][month_key][param], err, ae)

                # byHour
                m["byHour"].setdefault(hour_key, {}).setdefault(param, empty_stats())
                add_to(m["byHour"][hour_key][param], err, ae)

        total += 1

    log.info("Обработано: %d записей, пропущено: %d", total, skipped)

    # Финализация
    result = {}
    for mid, m in sorted(accum.items()):
        result[mid] = {
            "overall":  {p: finalize_stats(s) for p, s in m["overall"].items()
                         if finalize_stats(s)},
            "bySeason": {
                season: {p: finalize_stats(s) for p, s in params.items()
                         if finalize_stats(s)}
                for season, params in sorted(m["bySeason"].items())
            },
            "byMonth": {
                mk: {p: finalize_stats(s) for p, s in params.items()
                     if finalize_stats(s)}
                for mk, params in sorted(m["byMonth"].items())
            },
            "byHour": {
                hk: {p: finalize_stats(s) for p, s in params.items()
                     if finalize_stats(s)}
                for hk, params in sorted(m["byHour"].items(), key=lambda x: int(x[0]))
            },
        }

    return result

# ── Сводная таблица для лога ──────────────────────────────────────────────────
SUMMARY_PARAMS = [
    ("temp",       "температуре",  "°C"  ),
    ("pressure",   "давлению",     " гПа"),
    ("wind",       "ветру",        " м/с"),
    ("windDir",    "направлению",  "°"   ),
    ("humidity",   "влажности",    "%"   ),
    ("cloudcover", "облачности",   "%"   ),
    ("visibility", "видимости",    " м"  ),
]

def print_summary(bias_data):
    for param, label, unit in SUMMARY_PARAMS:
        rows = []
        for mid, m in bias_data.items():
            s = m["overall"].get(param)
            if s and s.get("n", 0) > 0:
                rows.append((s["bias"], mid, s["mae"], s["n"]))
        if not rows:
            continue
        rows.sort()
        log.info("")
        log.info("=== СВОДКА: overall bias по %s ===", label)
        for bias, mid, mae, n in rows:
            sign = "+" if bias > 0 else ""
            log.info("  %-40s  bias=%s%.3f%s  MAE=%.3f%s  n=%d",
                     mid, sign, bias, unit, mae, unit, n)

# ── Главная функция ───────────────────────────────────────────────────────────
def main():
    log.info("=== calc_model_bias.py запущен ===")
    log.info("Читаем записи из %s", MODELDATA_DIR)

    records = load_records()
    if not records:
        log.error("Нет данных. Завершение.")
        return

    log.info("Всего записей: %d", len(records))
    log.info("Считаем bias по каждой модели...")

    bias_data = compute_bias(records)

    now = datetime.now(timezone.utc)
    out = {
        "updated":  now.isoformat(),
        "records":  len(records),
        "models":   bias_data,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    size_kb = OUT_PATH.stat().st_size / 1024
    log.info("✓ Записано: %s (%.1f КБ)", OUT_PATH, size_kb)

    print_summary(bias_data)
    log.info("=== Готово ===")

if __name__ == "__main__":
    main()
