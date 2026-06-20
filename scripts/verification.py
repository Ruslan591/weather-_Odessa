"""
Верификационный блок: сверка прогноза с фактом (SYNOP) по 4 периодам суток.
Периоды (по местному времени устройства): ночь 00-06, утро 06-12, день 12-18, вечер 18-24.
При каждой генерации AI-анализа: сохраняем прогноз+факт за ТЕКУЩИЙ период,
и формируем текстовый блок сверки за ПРЕДЫДУЩИЙ период (если он уже сохранён).
"""
import json
import os
from datetime import datetime, timezone, timedelta

STATION = "33837"
SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

PERIODS = [
    ("night",   0, 6),
    ("morning", 6, 12),
    ("day",     12, 18),
    ("evening", 18, 24),
]
PERIOD_LABELS_RU = {
    "night": "ночь (00-06)", "morning": "утро (06-12)",
    "day": "день (12-18)", "evening": "вечер (18-24)",
}


def local_now():
    # Системный часовой пояс устройства (как и остальной проект, см. now_str в build_prompt)
    return datetime.now(timezone.utc).astimezone()


def current_and_previous_period(now_local=None):
    """Возвращает (date_str_current, period_current, date_str_prev, period_prev) по местному времени."""
    if now_local is None:
        now_local = local_now()
    h = now_local.hour
    idx = h // 6  # 0..3
    cur_period = PERIODS[idx][0]
    cur_date = now_local.strftime("%Y-%m-%d")
    if idx == 0:
        prev_idx = 3
        prev_dt = now_local - timedelta(days=1)
    else:
        prev_idx = idx - 1
        prev_dt = now_local
    prev_period = PERIODS[prev_idx][0]
    prev_date = prev_dt.strftime("%Y-%m-%d")
    return cur_date, cur_period, prev_date, prev_period


def _mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def _rnd(v, d=1):
    return round(v, d) if v is not None else None


def aggregate_forecast_period(raw_hourly, date_str, period_name):
    """
    Агрегирует сырые почасовые данные fetch_ensemble() (raw['hourly'])
    за указанный период (время в raw_hourly уже местное, см. &timezone=Europe/Kiev в запросе).
    """
    times = raw_hourly.get("time", [])
    n = len(times)

    def col(key):
        arr = raw_hourly.get(key, [])
        return [arr[i] if i < len(arr) else None for i in range(n)]

    T2m = col("temperature_2m")
    WS = col("windspeed_10m")
    WG = col("windgusts_10m")
    P = col("pressure_msl")
    Prec = col("precipitation")
    WC = col("weathercode")

    period_def = dict((p[0], (p[1], p[2])) for p in PERIODS)
    h_start, h_end = period_def[period_name]

    idxs = []
    for i, t in enumerate(times):
        if t[:10] != date_str:
            continue
        hour = int(t[11:13])
        if h_start <= hour < h_end:
            idxs.append(i)

    if not idxs:
        return None

    t_vals = [T2m[i] for i in idxs if T2m[i] is not None]
    ws_vals = [WS[i] for i in idxs if WS[i] is not None]
    wg_vals = [WG[i] for i in idxs if WG[i] is not None]
    p_vals = [P[i] for i in idxs if P[i] is not None]
    prec_sum = sum(x for i in idxs for x in [Prec[i]] if x is not None)
    wc_vals = [WC[i] for i in idxs if WC[i] is not None]
    wc_dom = max(set(wc_vals), key=wc_vals.count) if wc_vals else None

    return {
        "T_min": _rnd(min(t_vals)) if t_vals else None,
        "T_max": _rnd(max(t_vals)) if t_vals else None,
        "wind_mean": _rnd(_mean(ws_vals)),
        "wind_max": _rnd(max(ws_vals)) if ws_vals else None,
        "gust_max": _rnd(max(wg_vals)) if wg_vals else None,
        "pressure_mean": _rnd(_mean(p_vals)),
        "precip_mm": _rnd(prec_sum, 1),
        "weathercode": wc_dom,
    }


# ── SYNOP факт ──────────────────────────────────────────────────────────

def parse_synop_line(raw_line):
    m = raw_line.strip()
    parts = m.split(",", 6)
    if len(parts) < 7:
        return None
    st, y, mo, dd, hh, mm, telegram = parts
    if st != STATION:
        return None
    if "NILL" in telegram:
        return None
    hour = int(hh)
    if hour not in SYNOP_HOURS:
        return None

    toks = telegram.split()
    try:
        sec333 = toks.index("333")
    except ValueError:
        sec333 = len(toks)
    main = toks[:sec333]

    aaxi = 0
    try:
        aaxi = toks.index("AAXX")
    except ValueError:
        pass

    grp4 = main[aaxi + 4] if len(main) > aaxi + 4 else ""
    wind_dir = wind = None
    if len(grp4) == 5 and grp4.isdigit():
        wind_dir = int(grp4[1:3]) * 10
        wind = int(grp4[3:5])

    temp = pressure = precip = ww = None
    iR = None
    grp3 = main[aaxi + 3] if len(main) > aaxi + 3 else ""
    if len(grp3) == 5 and grp3[3:5].isdigit():
        iR = int(grp3[0]) if grp3[0].isdigit() else None

    for g in main[aaxi + 5:]:
        g = g.rstrip("=")
        if len(g) != 5:
            continue
        if g[0] == "1" and g[1] in "01" and g[2:].isdigit():
            temp = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        elif g[0] == "4" and g[1:].isdigit():
            val = int(g[1:]) / 10
            pressure = val if val >= 500 else (1000 + val)
            if not (920 < pressure < 1050):
                pressure = None
        elif g[0] == "6" and g[1:4].isdigit() and iR in (0, 1, 2):
            rrr = int(g[1:4])
            precip = 0 if rrr in (0, 990) else (rrr - 990) * 0.1 if rrr >= 991 else rrr
        elif g[0] == "7" and g[1:3].isdigit():
            ww = int(g[1:3])

    if temp is None:
        return None

    return {
        "y": y, "mo": mo, "dd": dd, "hh": hh,
        "temp": temp, "pressure": pressure,
        "wind": wind, "windDir": wind_dir,
        "precip": precip, "ww": ww,
    }


def parse_synop_text(text):
    out = []
    for line in text.splitlines():
        rec = parse_synop_line(line)
        if rec:
            out.append(rec)
    return out


# ww-коды значимой погоды: гроза 17,29,91-99; дождь 50-69,80-84
def ww_has_thunder(ww):
    return ww is not None and (ww == 17 or ww == 29 or 91 <= ww <= 99)


def ww_has_rain(ww):
    return ww is not None and ((50 <= ww <= 69) or (80 <= ww <= 84))


def _synop_local_dt(r):
    """SYNOP-время хранится в UTC; конвертируем в системный часовой пояс устройства."""
    dt_utc = datetime(int(r["y"]), int(r["mo"]), int(r["dd"]), int(r["hh"]), tzinfo=timezone.utc)
    return dt_utc.astimezone()


def aggregate_synop_period(synop_records, date_str, period_name):
    period_def = dict((p[0], (p[1], p[2])) for p in PERIODS)
    h_start, h_end = period_def[period_name]

    matched = []
    for r in synop_records:
        local_dt = _synop_local_dt(r)
        if local_dt.strftime("%Y-%m-%d") != date_str:
            continue
        if h_start <= local_dt.hour < h_end:
            matched.append(r)
    if not matched:
        return None

    temps = [r["temp"] for r in matched if r["temp"] is not None]
    winds = [r["wind"] for r in matched if r["wind"] is not None]
    press = [r["pressure"] for r in matched if r["pressure"] is not None]
    precs = [r["precip"] for r in matched if r["precip"] is not None]
    had_rain = any(ww_has_rain(r["ww"]) for r in matched)
    had_thunder = any(ww_has_thunder(r["ww"]) for r in matched)

    return {
        "T_min": _rnd(min(temps)) if temps else None,
        "T_max": _rnd(max(temps)) if temps else None,
        "wind_mean": _rnd(_mean(winds)),
        "wind_max": _rnd(max(winds)) if winds else None,
        "pressure_mean": _rnd(_mean(press)),
        "precip_mm": _rnd(sum(precs), 1) if precs else 0.0,
        "had_rain": had_rain,
        "had_thunder": had_thunder,
    }


# ── Хранение и формирование текста для промпта ─────────────────────────────

def _fmt_num(v, suffix=""):
    return f"{v}{suffix}" if v is not None else "н/д"


def format_verification_block(prev_date, prev_period, forecast, fact):
    """Формирует компактный текстовый блок 'прогноз vs факт' для промпта."""
    label = PERIOD_LABELS_RU.get(prev_period, prev_period)
    lines = [
        f"СВЕРКА ПРОГНОЗА С ФАКТОМ за прошедший период ({label}, {prev_date}):",
        f"  Прогнозировалось: T {_fmt_num(forecast.get('T_min'),'°C')}..{_fmt_num(forecast.get('T_max'),'°C')}, "
        f"ветер ~{_fmt_num(forecast.get('wind_mean'),' м/с')} (порывы до {_fmt_num(forecast.get('gust_max'),' м/с')}), "
        f"давление {_fmt_num(forecast.get('pressure_mean'),' гПа')}, осадки {_fmt_num(forecast.get('precip_mm'),' мм')}.",
        f"  По факту (SYNOP): T {_fmt_num(fact.get('T_min'),'°C')}..{_fmt_num(fact.get('T_max'),'°C')}, "
        f"ветер ~{_fmt_num(fact.get('wind_mean'),' м/с')} (макс {_fmt_num(fact.get('wind_max'),' м/с')}), "
        f"давление {_fmt_num(fact.get('pressure_mean'),' гПа')}, осадки {_fmt_num(fact.get('precip_mm'),' мм')}, "
        f"дождь: {'да' if fact.get('had_rain') else 'нет'}, гроза: {'да' if fact.get('had_thunder') else 'нет'}.",
    ]
    return "\n".join(lines)


def load_verification_store(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_verification_store(path, store):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def update_and_get_verification(path, raw_hourly, synop_text):
    """
    Главная точка входа. Store общий (не делится по provider — промпт у Claude и Gemini одинаковый).
    1. Считает прогноз+факт за ТЕКУЩИЙ период и сохраняет (перезаписывая) в store.
    2. Возвращает текстовый блок для ПРЕДЫДУЩЕГО периода, если он есть в store.
    Возвращает (block_text_or_None, store) — store нужно сохранить вызывающей стороной.
    """
    store = load_verification_store(path)

    cur_date, cur_period, prev_date, prev_period = current_and_previous_period()

    synop_records = parse_synop_text(synop_text)

    cur_forecast = aggregate_forecast_period(raw_hourly, cur_date, cur_period)
    cur_fact = aggregate_synop_period(synop_records, cur_date, cur_period)
    cur_key = f"{cur_date}_{cur_period}"
    if cur_forecast is not None:
        entry = store.get(cur_key, {})
        entry["forecast"] = cur_forecast
        if cur_fact is not None:
            entry["fact"] = cur_fact
        store[cur_key] = entry

    prev_key = f"{prev_date}_{prev_period}"
    prev_entry = store.get(prev_key)

    block = None
    if prev_entry and prev_entry.get("forecast"):
        prev_fact = prev_entry.get("fact")
        if prev_fact is None:
            prev_fact = aggregate_synop_period(synop_records, prev_date, prev_period)
            if prev_fact is not None:
                prev_entry["fact"] = prev_fact
                store[prev_key] = prev_entry
        if prev_fact is not None:
            block = format_verification_block(prev_date, prev_period, prev_entry["forecast"], prev_fact)

    return block, store
