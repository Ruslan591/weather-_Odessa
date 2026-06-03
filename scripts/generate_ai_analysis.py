#!/usr/bin/env python3
"""
generate_ai_analysis.py — генерация синоптического анализа через Claude API.
Запрашивает open-meteo (ансамбль), агрегирует данные по дням,
отправляет в Claude, сохраняет data/forecast_analysis.json.
Вызывается из check_model_runs.py после run_pipeline().
"""

import json, os, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
import hashlib

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE   = os.path.join(BASE_DIR, "data", "forecast_analysis.json")
ENV_FILE      = os.path.join(BASE_DIR, ".env")
TIMEOUT       = 30

LAT, LON      = 46.43, 30.74
TIMEZONE      = "Europe/Kiev"

# ── Ключ из .env ──────────────────────────────────────────────────────────────

def load_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY")

# ── Запрос open-meteo ─────────────────────────────────────────────────────────

HOURLY_FIELDS = ",".join([
    "temperature_2m","apparent_temperature","dewpoint_2m",
    "relative_humidity_2m","precipitation","precipitation_probability",
    "weathercode","pressure_msl","windspeed_10m","winddirection_10m","windgusts_10m",
    "cloudcover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
    "cape","lifted_index",
    "temperature_850hPa","temperature_700hPa","temperature_500hPa",
    "geopotential_height_850hPa","geopotential_height_700hPa","geopotential_height_500hPa","geopotential_height_300hPa",
    "relative_humidity_925hPa","relative_humidity_850hPa","relative_humidity_700hPa","relative_humidity_500hPa","relative_humidity_300hPa",
    "cloud_cover_925hPa","cloud_cover_850hPa","cloud_cover_700hPa","cloud_cover_500hPa","cloud_cover_300hPa",
    "vertical_velocity_500hPa","vertical_velocity_700hPa","vertical_velocity_850hPa",
    "freezinglevel_height","snowfall",
])

def fetch_ensemble():
    url = (
        f"https://ensemble-api.open-meteo.com/v1/ensemble"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&models=ecmwf_ifs04"
        f"&forecast_days=7"
        f"&timezone={TIMEZONE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

# ── Агрегация по дням ─────────────────────────────────────────────────────────

def mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def rnd(v, d=1):
    return round(v, d) if v is not None else None

def aggregate_days(data):
    h = data.get("hourly", {})
    times = h.get("time", [])
    n = len(times)

    def col(key):
        arr = h.get(key, [])
        return [arr[i] if i < len(arr) else None for i in range(n)]

    T2m   = col("temperature_2m")
    Td    = col("dewpoint_2m")
    RH    = col("relative_humidity_2m")
    Prec  = col("precipitation")
    PrecP = col("precipitation_probability")
    WC    = col("weathercode")
    P     = col("pressure_msl")
    WS    = col("windspeed_10m")
    WD    = col("winddirection_10m")
    WG    = col("windgusts_10m")
    CC    = col("cloudcover")
    CAPE  = col("cape")
    LI    = col("lifted_index")
    T850  = col("temperature_850hPa")
    T700  = col("temperature_700hPa")
    T500  = col("temperature_500hPa")
    Z850  = col("geopotential_height_850hPa")
    Z700  = col("geopotential_height_700hPa")
    Z500  = col("geopotential_height_500hPa")
    Z300  = col("geopotential_height_300hPa")
    RH850 = col("relative_humidity_850hPa")
    RH700 = col("relative_humidity_700hPa")
    RH500 = col("relative_humidity_500hPa")
    W500  = col("vertical_velocity_500hPa")
    W700  = col("vertical_velocity_700hPa")
    W850  = col("vertical_velocity_850hPa")
    FRZ   = col("freezinglevel_height")
    Snow  = col("snowfall")
    CCL   = col("cloud_cover_low")
    CCM   = col("cloud_cover_mid")
    CCH   = col("cloud_cover_high")

    # группировка по датам
    from collections import defaultdict
    days = defaultdict(list)
    for i, t in enumerate(times):
        date = t[:10]
        days[date].append(i)

    now_local = datetime.now(timezone.utc).astimezone()
    today_str = now_local.strftime("%Y-%m-%d")

    result = []
    for date, idxs in sorted(days.items()):
        # Только сегодня + 4 дня вперёд
        if date < today_str:
            continue
        if len(result) >= 5:
            break

        def v(arr): return [arr[i] for i in idxs]

        # Ночь/день/вечер разбивка по часам
        hours_of_day = [int(times[i][11:13]) for i in idxs]
        night_idx  = [idxs[j] for j,h in enumerate(hours_of_day) if h < 6 or h >= 21]
        day_idx    = [idxs[j] for j,h in enumerate(hours_of_day) if 6 <= h < 21]

        def sub(arr, sub_idx): return [arr[i] for i in sub_idx if arr[i] is not None]

        T_vals = v(T2m)
        T_valid = [x for x in T_vals if x is not None]

        prec_sum = sum(x for x in v(Prec) if x is not None)
        snow_sum = sum(x for x in v(Snow) if x is not None)

        # Доминантный weathercode
        wc_list = [x for x in v(WC) if x is not None]
        wc_dom = max(set(wc_list), key=wc_list.count) if wc_list else None

        # Омега — знак и величина
        w500_avg = mean(v(W500))
        w700_avg = mean(v(W700))
        w850_avg = mean(v(W850))

        # Ветер — средний и максимальный
        ws_vals = [x for x in v(WS) if x is not None]
        wg_vals = [x for x in v(WG) if x is not None]

        # Изотерма 0°C
        frz_vals = [x for x in v(FRZ) if x is not None]

        day_data = {
            "date": date,
            "T": {
                "min": rnd(min(T_valid)) if T_valid else None,
                "max": rnd(max(T_valid)) if T_valid else None,
                "mean": rnd(mean(T_valid)),
                "night_mean": rnd(mean(sub(T2m, night_idx))),
                "day_mean": rnd(mean(sub(T2m, day_idx))),
            },
            "Td_mean": rnd(mean(v(Td))),
            "RH_mean": rnd(mean(v(RH))),
            "precip_mm": rnd(prec_sum, 1),
            "precip_prob_max": max((x for x in v(PrecP) if x is not None), default=None),
            "snow_cm": rnd(snow_sum, 1),
            "weathercode_dom": wc_dom,
            "pressure_mean": rnd(mean(v(P))),
            "wind": {
                "mean_kmh": rnd(mean(ws_vals)),
                "max_kmh": rnd(max(ws_vals)) if ws_vals else None,
                "gust_max_kmh": rnd(max(wg_vals)) if wg_vals else None,
            },
            "cloud": {
                "total_mean": rnd(mean(v(CC))),
                "low_mean": rnd(mean(v(CCL))),
                "mid_mean": rnd(mean(v(CCM))),
                "high_mean": rnd(mean(v(CCH))),
            },
            "CAPE_max": rnd(max((x for x in v(CAPE) if x is not None), default=None)),
            "LI_min": rnd(min((x for x in v(LI) if x is not None), default=None)),
            "upper": {
                "T850": rnd(mean(v(T850))),
                "T700": rnd(mean(v(T700))),
                "T500": rnd(mean(v(T500))),
                "Z850": rnd(mean(v(Z850))),
                "Z700": rnd(mean(v(Z700))),
                "Z500": rnd(mean(v(Z500))),
                "Z300": rnd(mean(v(Z300))),
                "RH850": rnd(mean(v(RH850))),
                "RH700": rnd(mean(v(RH700))),
                "RH500": rnd(mean(v(RH500))),
                "omega500": rnd(w500_avg, 3),
                "omega700": rnd(w700_avg, 3),
                "omega850": rnd(w850_avg, 3),
            },
            "freeze_level_m": rnd(mean(frz_vals)),
        }
        result.append(day_data)

    return result

# ── Хэш данных для проверки изменений ────────────────────────────────────────

def data_hash(days):
    # Хэш по ключевым полям — если не изменился, не перегенерируем
    key = json.dumps([{
        "date": d["date"],
        "T": d["T"],
        "precip_mm": d["precip_mm"],
        "upper": d["upper"],
    } for d in days], sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]

# ── Промпт ────────────────────────────────────────────────────────────────────

WMO_CODES = {
    0:"ясно", 1:"преимущественно ясно", 2:"переменная облачность", 3:"пасмурно",
    45:"туман", 48:"изморозь", 51:"слабая морось", 53:"морось", 55:"сильная морось",
    61:"слабый дождь", 63:"дождь", 65:"сильный дождь",
    71:"слабый снег", 73:"снег", 75:"сильный снег", 77:"снежная крупа",
    80:"ливень", 81:"сильный ливень", 82:"очень сильный ливень",
    85:"снегопад", 86:"сильный снегопад",
    95:"гроза", 96:"гроза с градом", 99:"сильная гроза с градом",
}

def build_prompt(days):
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M местного")

    lines = [
        f"Время генерации: {now_str}",
        f"Место: Одесса, Украина (46.43°N, 30.74°E, побережье Чёрного моря)",
        "",
        "Ты — опытный синоптик. Напиши профессиональный синоптический анализ прогноза погоды.",
        "Используй все предоставленные данные: температуру по уровням, геопотенциал,",
        "вертикальное движение (омега), влажность, облачность, CAPE, LI, нулевую изотерму.",
        "Анализируй связи между параметрами. Текст живой, профессиональный, без шаблонных фраз.",
        "Если предвидятся значительные события (грозы, шторм, резкое похолодание/потепление,",
        "сильные осадки) — акцентируй на них. Пиши по-русски.",
        "",
        "ДАННЫЕ ПРОГНОЗА (ансамбль ECMWF, почасовые агрегаты по дням):",
        "",
    ]

    day_labels = ["СЕГОДНЯ", "ЗАВТРА", "День +2", "День +3", "День +4"]

    for i, d in enumerate(days):
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        label = day_labels[i] if i < len(day_labels) else f"День +{i}"
        wc_label = WMO_CODES.get(d.get("weathercode_dom"), f"код {d.get('weathercode_dom')}")
        u = d["upper"]
        lines += [
            f"── {label} ({dt.strftime('%d.%m')}) ──",
            f"  Температура: {d['T']['min']}…{d['T']['max']}°C  (день {d['T']['day_mean']}°C, ночь {d['T']['night_mean']}°C)",
            f"  Осадки: {d['precip_mm']} мм  вероятность до {d['precip_prob_max']}%  снег {d['snow_cm']} см",
            f"  Погода: {wc_label}",
            f"  Давление: {d['pressure_mean']} гПа",
            f"  Ветер: средний {d['wind']['mean_kmh']} км/ч  макс {d['wind']['max_kmh']} км/ч  порывы {d['wind']['gust_max_kmh']} км/ч",
            f"  Облачность: общая {d['cloud']['total_mean']}%  низкая {d['cloud']['low_mean']}%  средняя {d['cloud']['mid_mean']}%  высокая {d['cloud']['high_mean']}%",
            f"  CAPE: {d['CAPE_max']} Дж/кг  LI: {d['LI_min']}",
            f"  Нулевая изотерма: {d['freeze_level_m']} м",
            f"  T850/700/500: {u['T850']}°C / {u['T700']}°C / {u['T500']}°C",
            f"  Z850/700/500/300: {u['Z850']} / {u['Z700']} / {u['Z500']} / {u['Z300']} м",
            f"  RH850/700/500: {u['RH850']}% / {u['RH700']}% / {u['RH500']}%",
            f"  Омега 850/700/500: {u['omega850']} / {u['omega700']} / {u['omega500']} Па/с",
            "",
        ]

    lines += [
        "СТРУКТУРА ОТВЕТА (строго):",
        "1. ## Сегодня — подробный анализ (3-5 предложений)",
        "2. ## Завтра — подробный анализ (3-5 предложений)",
        "3. ## Ближайшие 3 дня — общий обзор (3-4 предложения)",
        "4. ## ⚠️ Предупреждения — только если есть реальные риски (гроза, шторм, сильные осадки). Если рисков нет — этот раздел пропусти.",
        "5. ## Тенденция — краткий прогноз изменений за горизонтом (1-2 предложения)",
        "",
        "Не используй таблицы. Не повторяй цифры из данных дословно — интерпретируй их синоптически.",
    ]

    return "\n".join(lines)

# ── Запрос к Claude API ───────────────────────────────────────────────────────

def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    return resp["content"][0]["text"]

# ── Основная логика ───────────────────────────────────────────────────────────

def main():
    api_key = load_api_key()
    if not api_key:
        print("  [AI] ANTHROPIC_API_KEY не найден — пропускаю генерацию анализа")
        return

    print("\n  🤖 Генерация синоптического анализа...")

    # Загружаем текущий результат (если есть)
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # Запрашиваем данные
    try:
        raw = fetch_ensemble()
    except Exception as e:
        print(f"  [AI] Ошибка open-meteo: {e}")
        return

    days = aggregate_days(raw)
    if not days:
        print("  [AI] Нет данных для анализа")
        return

    # Проверяем изменились ли данные
    current_hash = data_hash(days)
    prev_hash = existing.get("data_hash", "")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if current_hash == prev_hash and existing.get("text"):
        # Данные не изменились — обновляем только метку времени
        existing["last_checked"] = now_iso
        existing["changed"] = False
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"  [AI] Данные не изменились — обновлена метка времени")
        return

    # Данные изменились — генерируем новый анализ
    prompt = build_prompt(days)
    print(f"  [AI] Промпт: ~{len(prompt.split())} слов, запрос к Claude...")

    try:
        text = call_claude(prompt, api_key)
    except Exception as e:
        print(f"  [AI] Ошибка Claude API: {e}")
        return

    result = {
        "generated_at": now_iso,
        "last_checked": now_iso,
        "changed": True,
        "data_hash": current_hash,
        "days_count": len(days),
        "text": text,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  [AI] ✅ Анализ сохранён ({len(text)} символов)")

if __name__ == "__main__":
    main()