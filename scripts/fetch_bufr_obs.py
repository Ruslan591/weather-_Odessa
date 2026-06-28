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
        f"&h1={dt.hour:02d}Z&h2={dt.hour:02d}Z&min=0&rt=0"
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

    # Осадки за период — два поля 013011
    precip_matches = re.findall(
        r'Total precipitation/total water equivalent: </i></b>\s*(.*?)<br>', html
    )
    def precip_val(idx):
        if idx >= len(precip_matches): return None
        raw = precip_matches[idx].strip()
        if raw in ("-", ""): return None
        m = re.search(r'\((-?[\d.]+)\)', raw)
        return float(m.group(1)) / 10 if m else None  # Pa→mm equiv

    # Радиация — два блока по 6 полей
    rad_labels = [
        "Long-wave radiation, integrated over period specified",
        "Short-wave radiation, integrated over period specified",
        "Net radiation, integrated over period specified",
        "Global solar radiation (high accuracy), integrated over period specified",
        "Diffuse solar radiation (high accuracy), integrated over period specified",
        "Direct solar radiation (high accuracy), integrated over period specified",
    ]
    def rad_block(html, block=0):
        """Парсим block-й блок радиации (0=первый период, 1=второй)."""
        result = {}
        keys = ["lw","sw","net","global","diffuse","direct"]
        for i, lbl in enumerate(rad_labels):
            pat = re.escape(f"<b><i>{lbl}: </i></b>") + r"\s*(.*?)<br>"
            all_m = list(re.finditer(pat, html))
            if block < len(all_m):
                raw = all_m[block].group(1).strip()
                m2 = re.search(r'\((-?[\d.]+)\)', raw)
                result[keys[i]] = float(m2.group(1)) if m2 and raw not in ("-","") else None
            else:
                result[keys[i]] = None
        return result

    rad1 = rad_block(html, 0)
    rad2 = rad_block(html, 1)

    # Порывы — два блока (10 мин и 180 мин)
    gust_spd = re.findall(
        r'Maximum wind gust speed: </i></b>\s*(.*?)<br>', html
    )
    gust_dir = re.findall(
        r'Maximum wind gust direction: </i></b>\s*(.*?)<br>', html
    )
    def gust_v(lst, idx):
        if idx >= len(lst): return None
        raw = lst[idx].strip()
        if raw in ("-", ""): return None
        m = re.search(r'\((-?[\d.]+)\)', raw)
        return float(m.group(1)) if m else None

    # Инсоляция — два значения (разные периоды)
    sun_matches = re.findall(
        r'Total sunshine: </i></b>\s*(.*?)<br>', html
    )
    def sun_val(idx):
        if idx >= len(sun_matches): return None
        raw = sun_matches[idx].strip()
        if raw in ("-", ""): return None
        m = re.search(r'\((-?[\d.]+)\)', raw)
        return float(m.group(1)) if m else None

    wind_spd_kmh = _val(html, "Wind speed")  # в км/ч — Meteomanz показывает так
    # Но в скобках уже м/с: "7.2 Km/h (2.0)"
    wind_spd_ms_m = re.search(
        r'Wind speed: </i></b>\s*[\d.]+\s*Km/h\s*\((-?[\d.]+)\)', html
    )
    wind_spd_ms = float(wind_spd_ms_m.group(1)) if wind_spd_ms_m else (
        round(wind_spd_kmh / 3.6, 1) if wind_spd_kmh else None
    )

    obs = {
        "dt":      dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": STATION,

        # Давление
        "station_pressure":        _val(html, "Pressure"),
        "slp":                     _val(html, "Pressure reduced to mean sea level"),
        "pressure_tendency_val":   _val(html, "3-hour pressure change"),
        "pressure_tendency_code":  _val(html, "Characteristic of pressure tendency"),
        "pressure_tendency_txt":   _txt(html, "Characteristic of pressure tendency"),
        "pressure_change_24h":     _val(html, "24-hour pressure change"),

        # Температура и влажность
        "temp":     _val(html, "Temperature/air temperature"),
        "dew":      _val(html, "Dewpoint temperature"),
        "humidity": _val(html, "Relative humidity"),

        # Ветер
        "wind_dir":      _val(html, "Wind direction"),
        "wind_spd_kmh":  wind_spd_kmh,
        "wind_spd_ms":   wind_spd_ms,
        "wind_gust_spd_10min_ms":  gust_v(gust_spd, 0),
        "wind_gust_dir_10min":     gust_v(gust_dir, 0),
        "wind_gust_spd_180min_ms": gust_v(gust_spd, 1),
        "wind_gust_dir_180min":    gust_v(gust_dir, 1),

        # Видимость
        "visibility": _val(html, "Horizontal visibility"),

        # Облачность
        "cloud_cover_pct":  _val(html, "Cloud cover (total)"),
        "cloud_amount":     _val(html, "Cloud amount (Observing rules for base of lowest cloud and cloud types of FM 12 SYNOP and FM 13 SHIP apply)"),
        "cloud_base_m":     _val(html, "Height of base of cloud"),
        "cloud_type_cl":    cloud_code("Low cloud type"),
        "cloud_type_cm":    cloud_code("Medium cloud type"),
        "cloud_type_ch":    cloud_code("High cloud type"),

        # Погода
        "weather_now":    _val(html, "Present weather"),
        "weather_past1":  _val(html, "Past weather (1)"),
        "weather_past2":  _val(html, "Past weather (2)"),
        "weather_now_txt":   _txt(html, "Present weather"),
        "weather_past1_txt": _txt(html, "Past weather (1)"),
        "weather_past2_txt": _txt(html, "Past weather (2)"),

        # Осадки
        "precip_period1_mm":  precip_val(0),
        "precip_period2_mm":  precip_val(1),
        "precip_24h_mm":      _val(html, "Total precipitation past 24 hours"),
        "snow_depth_m":       _val(html, "Total snow depth"),

        # Температура почвы
        "ground_temp":          _val(html, "Ground temperature"),
        "ground_min_temp_12h":  _val(html, "Ground minimum temperature, past 12 hours"),
        "ground_state":         _val(html, "State of the ground (with or without snow)"),

        # Экстремумы температуры
        "temp_max_12h":  _val(html, "Maximum temperature, at height and over period specified"),
        "temp_min_12h":  _val(html, "Minimum temperature, at height and over period specified"),
        "temp_change":   _val(html, "Temperature change over specified period"),

        # Инсоляция
        "sunshine_period1_s":  sun_val(0),
        "sunshine_24h_s":      sun_val(1),

        # Испарение
        "evaporation":  _val(html, "Evaporation/evapotranspiration"),

        # Радиация период 1
        "rad1_lw":      rad1["lw"],
        "rad1_sw":      rad1["sw"],
        "rad1_net":     rad1["net"],
        "rad1_global":  rad1["global"],
        "rad1_diffuse": rad1["diffuse"],
        "rad1_direct":  rad1["direct"],

        # Радиация период 2
        "rad2_lw":      rad2["lw"],
        "rad2_sw":      rad2["sw"],
        "rad2_net":     rad2["net"],
        "rad2_global":  rad2["global"],
        "rad2_diffuse": rad2["diffuse"],
        "rad2_direct":  rad2["direct"],
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