#!/usr/bin/env python3
"""
fetch_bufr_obs.py — парсит BUFR-наблюдения с Meteomanz для ст. 33837
и дописывает записи в data/bufr_YYYY.json.

Запуск:
    python3 scripts/fetch_bufr_obs.py [--hours N] [--dry-run]
"""
import re, json, os, time, datetime
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATION  = "33837"
SYNOP_HOURS = [3, 9, 15, 21]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
    "Referer":    "https://www.meteomanz.com/",
}

# ── HTML-парсинг ──────────────────────────────────────────────────────────────

def fetch_html(dt: datetime.datetime) -> str:
    url = (
        f"https://www.meteomanz.com/sy1?ty=hd&ind={STATION}&l=1"
        f"&d1={dt.day:02d}&m1={dt.month:02d}&y1={dt.year}"
        f"&d2={dt.day:02d}&m2={dt.month:02d}&y2={dt.year}"
        f"&h1={dt.hour:02d}Z&h2={dt.hour:02d}Z&min=0&rt=0&ext=1"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def _val(html: str, label: str):
    """
    Ищет паттерн двух видов:
      <b><i>Label: </i></b> число<br>
      <b><i>Label: </i></b> текст (число)<br>   <- берём число в скобках
    Возвращает float или None.
    """
    pat = re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>"
    m = re.search(pat, html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw in ("-", "", "—"):
        return None
    # Число в скобках в конце: "Some text (123.4)"
    m2 = re.search(r'\((-?[\d.]+)\)\s*$', raw)
    if m2:
        try: return float(m2.group(1))
        except ValueError: return None
    # Просто число
    m3 = re.match(r'^-?[\d.]+', raw)
    if m3:
        try: return float(m3.group())
        except ValueError: return None
    return None

def _txt(html: str, label: str):
    """Возвращает текстовое значение поля (до скобок или до <br>)."""
    pat = re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>"
    m = re.search(pat, html, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw in ("-", "", "—"):
        return None
    # Убираем часть в скобках в конце
    txt = re.sub(r'\s*\(-?[\d.]+\)\s*$', '', raw).strip()
    return txt or None

def parse_obs(html: str, dt: datetime.datetime) -> dict | None:
    if "BUFR report" not in html or "No data for the selected dates" in html:
        return None

    # Облачные типы — их три подряд с одним label
    def cloud_code(label):
        m = re.search(re.escape(f"<b><i>{label}: </i></b>") + r"\s*(.*?)<br>", html)
        if not m: return None
        raw = m.group(1).strip()
        if raw in ("-", ""): return None
        m2 = re.search(r"\((\d+)\)\s*$", raw)
        return int(m2.group(1)) if m2 else None

    # Парсинг через дескрипторы BUFR (_ext_val/_ext_txt)
    def _ext_val(h, desc, occ=0):
        pat = re.escape(f"<b>{desc} <i>") + r"[^<]+</i> </b>\s*(.*?)<br>"
        ms = list(re.finditer(pat, h))
        if occ >= len(ms): return None
        raw = ms[occ].group(1).strip()
        if raw in ("-", "", "\u2014"): return None
        m2 = re.search(r"\((-?[\d.]+)\)\s*$", raw)
        if m2:
            try: return float(m2.group(1))
            except ValueError: return None
        m3 = re.match(r"^-?[\d.]+", raw)
        if m3:
            try: return float(m3.group())
            except ValueError: return None
        return None

    def _ext_txt(h, desc, occ=0):
        pat = re.escape(f"<b>{desc} <i>") + r"[^<]+</i> </b>\s*(.*?)<br>"
        ms = list(re.finditer(pat, h))
        if occ >= len(ms): return None
        raw = ms[occ].group(1).strip()
        if raw in ("-", "", "\u2014"): return None
        txt = re.sub(r"\s*\(-?[\d.]+\)\s*$", "", raw).strip()
        return txt or None

    wind_spd_ms_m = re.search(
        r'011002 <i>[^<]+</i> </b>\s*([\d.]+)\s*Km/h\s*\((-?[\d.]+)\)', html
    )
    if wind_spd_ms_m:
        wind_spd_kmh = float(wind_spd_ms_m.group(1))
        wind_spd_ms  = float(wind_spd_ms_m.group(2))
    else:
        wind_spd_kmh = None
        wind_spd_ms  = None

    obs = {
        "dt":      dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": STATION,

        # Давление (Па → гПа, тенденция Па*10 → гПа)
        "station_pressure":       round(_ext_val(html, "010004") / 100, 1) if _ext_val(html, "010004") else None,
        "slp":                    round(_ext_val(html, "010051") / 100, 1) if _ext_val(html, "010051") else None,
        "pressure_tendency_val":  round(_ext_val(html, "010061") / 100, 1) if _ext_val(html, "010061") else None,
        "pressure_tendency_code": _ext_val(html, "010063"),
        "pressure_tendency_txt":  _ru(_ext_val(html, "010063"), TEND_RU),
        "pressure_change_24h":    _ext_val(html, "010062"),

        # Температура и влажность (K → °C)
        "temp":     round(_ext_val(html, "012101") - 273.15, 1) if _ext_val(html, "012101") else None,
        "dew":      round(_ext_val(html, "012103") - 273.15, 1) if _ext_val(html, "012103") else None,
        "humidity": _ext_val(html, "013003"),

        # Ветер
        "wind_dir":                _ext_val(html, "011001"),
        "wind_spd_kmh":            wind_spd_kmh,
        "wind_spd_ms":             wind_spd_ms,
        "wind_gust_spd_10min_ms":  _ext_val(html, "011041", 0),
        "wind_gust_dir_10min":     _ext_val(html, "011043", 0),
        "wind_gust_spd_180min_ms": _ext_val(html, "011041", 1),
        "wind_gust_dir_180min":    _ext_val(html, "011043", 1),

        # Видимость
        "visibility": _ext_val(html, "020001"),

        # Облачность
        "cloud_cover_pct":   _ext_val(html, "020010"),
        "cloud_amount":      _ext_val(html, "020011", 0),
        "cloud_base_m":      _ext_val(html, "020013", 0),
        "cloud_type_cl":     _ext_val(html, "020012", 0),
        "cloud_type_cm":     _ext_val(html, "020012", 1),
        "cloud_type_ch":     _ext_val(html, "020012", 2),
        "cloud_type_cl_txt": _ru(_ext_val(html, "020012", 0), CL_RU),
        "cloud_type_cm_txt": _ru(_ext_val(html, "020012", 1), CM_RU),
        "cloud_type_ch_txt": _ru(_ext_val(html, "020012", 2), CH_RU),

        # Погода
        "weather_now":       _ext_val(html, "020003"),
        "weather_now_txt":   _ru(_ext_val(html, "020003"), WW_RU),
        "weather_past1":     _ext_val(html, "020004"),
        "weather_past1_txt": _ru(_ext_val(html, "020004"), W_PAST_RU),
        "weather_past2":     _ext_val(html, "020005"),
        "weather_past2_txt": _ru(_ext_val(html, "020005"), W_PAST_RU),

        # Осадки
        "precip_period1_mm": _ext_val(html, "013011", 0),
        "precip_period2_mm": _ext_val(html, "013011", 1),
        "precip_24h_mm":     _ext_val(html, "013023"),
        "snow_depth_m":      _ext_val(html, "013013"),

        # Температура почвы
        "ground_temp":         round(_ext_val(html, "012120") - 273.15, 1) if _ext_val(html, "012120") else None,
        "ground_min_temp_12h": round(_ext_val(html, "012113") - 273.15, 1) if _ext_val(html, "012113") else None,
        "ground_state":        _ext_val(html, "020062"),

        # Экстремумы температуры
        "temp_max_12h": round(_ext_val(html, "012111") - 273.15, 1) if _ext_val(html, "012111") else None,
        "temp_min_12h": round(_ext_val(html, "012112") - 273.15, 1) if _ext_val(html, "012112") else None,
        "temp_change":  _ext_val(html, "012049"),

        # Инсоляция
        "sunshine_period1_s": _ext_val(html, "014031", 0),
        "sunshine_24h_s":     _ext_val(html, "014031", 1),

        # Испарение
        "evaporation": _ext_val(html, "013033"),

        # Радиация период 1
        "rad1_lw":      _ext_val(html, "014002", 0),
        "rad1_sw":      _ext_val(html, "014004", 0),
        "rad1_net":     _ext_val(html, "014016", 0),
        "rad1_global":  _ext_val(html, "014028", 0),
        "rad1_diffuse": _ext_val(html, "014029", 0),
        "rad1_direct":  _ext_val(html, "014030", 0),

        # Радиация период 2
        "rad2_lw":      _ext_val(html, "014002", 1),
        "rad2_sw":      _ext_val(html, "014004", 1),
        "rad2_net":     _ext_val(html, "014016", 1),
        "rad2_global":  _ext_val(html, "014028", 1),
        "rad2_diffuse": _ext_val(html, "014029", 1),
        "rad2_direct":  _ext_val(html, "014030", 1),
    }
    return obs

# ── JSON I/O ──────────────────────────────────────────────────────────────────

def load_bufr_json(year: int) -> list:
    path = os.path.join(BASE_DIR, f"data/bufr_{year}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bufr_json(year: int, records: list):
    path = os.path.join(BASE_DIR, f"data/bufr_{year}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def dt_exists(records: list, dt: datetime.datetime) -> bool:
    key = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return any(r.get("dt") == key for r in records)

# ── Основная логика ───────────────────────────────────────────────────────────

def fetch_and_append(dt: datetime.datetime, dry_run=False) -> bool:
    records = load_bufr_json(dt.year)
    if dt_exists(records, dt):
        print(f"  уже есть: {dt:%Y-%m-%d %H}:00 UTC")
        return False

    try:
        html = fetch_html(dt)
    except Exception as e:
        print(f"  fetch ошибка {dt:%Y-%m-%d %H}:00 UTC: {e}")
        return False

    obs = parse_obs(html, dt)
    if obs is None:
        print(f"  нет данных: {dt:%Y-%m-%d %H}:00 UTC")
        return False

    non_null = sum(1 for v in obs.values() if v is not None and v != obs["dt"] and v != obs["station"])
    print(f"  {dt:%Y-%m-%d %H}:00 UTC  T={obs.get('temp')}°C  "
          f"SLP={obs.get('slp')}hPa  wind={obs.get('wind_spd_ms')}m/s  "
          f"fields={non_null}")

    if not dry_run:
        records.append(obs)
        records.sort(key=lambda r: r["dt"])
        save_bufr_json(dt.year, records)
    return True

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch BUFR obs from Meteomanz")
    parser.add_argument("--hours", type=int, default=1,
                        help="Сколько последних сроков забрать (default=1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Не писать файл, только показать что нашли")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Добрать N последних суток (например --backfill 3)")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    if args.backfill > 0:
        candidates = []
        for d in range(args.backfill + 1):
            day = now - datetime.timedelta(days=d)
            for h in SYNOP_HOURS:
                candidates.append(
                    day.replace(hour=h, minute=0, second=0, microsecond=0)
                )
        targets = sorted([c for c in candidates if c <= now])
    else:
        candidates = []
        for d in range(2):
            day = now - datetime.timedelta(days=d)
            for h in SYNOP_HOURS:
                candidates.append(
                    day.replace(hour=h, minute=0, second=0, microsecond=0)
                )
        candidates.sort(reverse=True)
        targets = [c for c in candidates if c <= now][:args.hours]
        targets = list(reversed(targets))

    for dt in targets:
        fetch_and_append(dt, dry_run=args.dry_run)
        time.sleep(2)

if __name__ == "__main__":
    main()