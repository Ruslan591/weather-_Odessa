#!/usr/bin/env python3
"""
rebuild_modeldata.py — аналог buildHistory.html на Python.

Читает SYNOP с GitHub, запрашивает open-meteo, пишет
data/modeldata/modelData_YYYY_MM.json обратно на GitHub.

Запуск (из папки проекта):
    cd /storage/emulated/0/Documents/weather

    # Все недостающие месяцы (рекомендуется):
    GITHUB_TOKEN=ghp_xxx python3 scripts/rebuild_modeldata.py --fill

    # Конкретный период (перезаписывает существующие):
    GITHUB_TOKEN=ghp_xxx python3 scripts/rebuild_modeldata.py 2023-12 2024-02

    # Один месяц:
    GITHUB_TOKEN=ghp_xxx python3 scripts/rebuild_modeldata.py 2024-01 2024-01

Переменные окружения:
    GITHUB_TOKEN  — обязательно
    DELAY_MODEL   — пауза между моделями в секундах (по умолчанию 0.5)
    DELAY_MONTH   — пауза между месяцами в секундах (по умолчанию 2)
"""

import os, sys, re, json, math, time, base64, logging, calendar
from datetime import datetime, timezone, date
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from pathlib import Path

# ── Логирование ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Конфиг ───────────────────────────────────────────────────────────────────
STATION      = "33837"
LAT          = 46.4406
LON          = 30.7703
SYNOP_HOURS  = {0, 3, 6, 9, 12, 15, 18, 21}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER = "ruslan591"
GITHUB_REPO  = "weather-_Odessa"

DELAY_MODEL  = float(os.environ.get("DELAY_MODEL", 0.5))
DELAY_MONTH  = float(os.environ.get("DELAY_MONTH", 2.0))

MODELS = [
    "ecmwf_ifs",
    "icon_eu",
    "icon_global",
    "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe",
    "gfs_global",
    "gem_global",
    "cma_grapes_global",
]

MODEL_FIELDS = (
    "temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,cloud_cover,precipitation,weather_code,"
    "visibility,dew_point_2m"
)

GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── HTTP ─────────────────────────────────────────────────────────────────────
def http_get(url, headers=None, timeout=40):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def http_get_json(url, headers=None, timeout=40):
    return json.loads(http_get(url, headers, timeout))

def retry(fn, attempts=3, delay=10, label=""):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "429" in msg and i < attempts - 1:
                wait = 30
                log.warning("  %s rate limit — жду %ds...", label, wait)
                time.sleep(wait)
            elif i == attempts - 1:
                raise
            else:
                log.warning("  %s retry %d/%d: %s", label, i+1, attempts, e)
                time.sleep(delay)

# ── GitHub API ────────────────────────────────────────────────────────────────
def gh_headers():
    h = dict(GH_HEADERS)
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

def gh_get_text(path):
    """Возвращает (text, sha) или (None, None)."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        resp = http_get_json(url, gh_headers(), timeout=30)
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    sha = resp.get("sha")
    if "content" in resp:
        text = base64.b64decode(resp["content"].replace("\n", "")).decode("utf-8")
        return text, sha
    dl = resp.get("download_url")
    if dl:
        return http_get(dl, timeout=60), sha
    return None, sha

def gh_put(path, text, sha, message):
    """Записывает файл на GitHub, возвращает новый sha."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    body = {"message": message, "content": encoded}
    if sha:
        body["sha"] = sha
    data = json.dumps(body).encode("utf-8")
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    req = Request(url, data=data,
                  headers={**gh_headers(), "Content-Type": "application/json"},
                  method="PUT")
    with urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return resp["content"]["sha"]

def gh_list_dir(path):
    """Возвращает список имён файлов в папке на GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        items = http_get_json(url, gh_headers(), timeout=20)
        return [f["name"] for f in items if isinstance(f, dict)]
    except HTTPError as e:
        if e.code == 404:
            return []
        raise

# ── Парсинг SYNOP ─────────────────────────────────────────────────────────────
LINE_RE = re.compile(
    r"^33837,(\d{4}),(\d{2}),(\d{2}),(\d{2}),(\d{2}),(AAXX\s.+)$"
)

def parse_synop_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    y, mo, dd, hh, mm, telegram = m.groups()
    if "NILL" in telegram:
        return None
    hour = int(hh)
    if hour not in SYNOP_HOURS:
        return None

    tk = f"{y}{mo}{dd}{hh}{mm}"
    parts = telegram.split()

    # Останавливаемся перед секцией 333
    try:
        sec333 = parts.index("333")
    except ValueError:
        sec333 = len(parts)
    main = parts[:sec333]

    # iRiXhVV → видимость
    try:
        aaxi = parts.index("AAXX")
    except ValueError:
        aaxi = 0

    visibility = None
    if len(main) > aaxi + 3:
        irixhvv = main[aaxi + 3]
        if len(irixhvv) == 5 and not "/" in irixhvv[3:5]:
            vv = int(irixhvv[3:5])
            if vv <= 50:   visibility = vv * 100
            elif vv <= 80: visibility = (vv - 50) * 1000
            elif vv == 89: visibility = 70000

    # Nddff → облачность, ветер
    cloudcover = wind_dir = wind = None
    if len(main) > aaxi + 4:
        wg = main[aaxi + 4]
        if len(wg) == 5 and wg.isdigit():
            N = int(wg[0])
            cloudcover = round(N / 8 * 100) if N <= 8 else None
            wind_dir   = int(wg[1:3]) * 10
            wind       = int(wg[3:5])

    # Группы с индексами
    temp = dew = pressure = precip = ww = None
    for g in main[aaxi + 5:]:
        g = g.rstrip("=")
        if len(g) != 5:
            continue
        # 1SnTTT — температура
        if re.match(r"^1[01]\d{3}$", g):
            temp = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        # 2SnTdTd — точка росы
        elif re.match(r"^2[01]\d{3}$", g):
            dew = (-1 if g[1] == "1" else 1) * int(g[2:]) / 10
        # 4PPPP — давление у.м.
        elif re.match(r"^4\d{4}$", g):
            val = int(g[1:])
            p = (1000 + val / 10) if val < 5000 else (val / 10)
            pressure = p if 920 < p < 1050 else None
        # 6RRRt — осадки
        elif re.match(r"^6\d{4}$", g):
            rrr = int(g[1:4])
            precip = 0.1 if rrr >= 990 else (0 if rrr == 0 else rrr)
        # 7wwW1W2 — погода
        elif re.match(r"^7\d{4}$", g):
            ww = int(g[1:3])

    if temp is None:
        return None

    # Относительная влажность из температуры и точки росы
    humidity = None
    if dew is not None:
        try:
            humidity = round(
                100 * math.exp((17.625 * dew) / (243.04 + dew))
                    / math.exp((17.625 * temp) / (243.04 + temp))
            )
        except Exception:
            pass

    return {
        "telegramKey": tk,
        "obs": {
            "synopTime":  tk,
            "temp":       temp,
            "pressure":   pressure,
            "wind":       wind,
            "windDir":    wind_dir,
            "cloudcover": cloudcover,
            "precip":     precip,
            "ww":         ww,
            "visibility": visibility,
            "dew":        dew,
            "humidity":   humidity,
            "synop":      telegram,
        }
    }

def parse_synop_text(text):
    result, seen = [], set()
    for line in text.splitlines():
        rec = parse_synop_line(line)
        if rec and rec["telegramKey"] not in seen:
            seen.add(rec["telegramKey"])
            result.append(rec)
    return result

# ── Open-Meteo ────────────────────────────────────────────────────────────────
def fetch_model_month(model_id, start_date, end_date):
    url = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={MODEL_FIELDS}"
        f"&models={model_id}"
        f"&start_date={start_date}&end_date={end_date}"
        "&timezone=UTC&wind_speed_unit=ms"
    )
    data = retry(lambda: http_get_json(url, timeout=40),
                 attempts=3, delay=10, label=model_id)
    return data.get("hourly")

# ── Сборка записей ────────────────────────────────────────────────────────────
def build_records(month_synops, hourly_by_model):
    records = []
    # Берём массив времени из первой успешной модели
    time_arr = None
    for h in hourly_by_model.values():
        if h:
            time_arr = h.get("time", [])
            break
    if not time_arr:
        return records

    for rec in month_synops:
        tk = rec["telegramKey"]
        target = f"{tk[:4]}-{tk[4:6]}-{tk[6:8]}T{tk[8:10]}:00"

        try:
            hi = next(i for i, t in enumerate(time_arr) if t.startswith(target))
        except StopIteration:
            continue

        def v(h, field):
            arr = h.get(field) if h else None
            if arr and hi < len(arr):
                val = arr[hi]
                return val if val is not None else None
            return None

        models_data = {}
        for mid, h in hourly_by_model.items():
            if not h:
                continue
            wd = v(h, "wind_direction_10m")
            models_data[mid] = {
                "temp":        v(h, "temperature_2m"),
                "pressure":    v(h, "pressure_msl"),
                "wind":        v(h, "wind_speed_10m"),
                "windDir":     round(wd / 10) * 10 if wd is not None else None,
                "gusts":       v(h, "wind_gusts_10m"),
                "cloudcover":  v(h, "cloud_cover"),
                "precip":      v(h, "precipitation"),
                "weatherCode": v(h, "weather_code"),
                "visibility":  v(h, "visibility"),
                "dewPoint":    v(h, "dew_point_2m"),
                "temp850":     None,
            }

        records.append({
            "synopTime":    tk,
            "forecastHour": None,
            "obs":          rec["obs"],
            "models":       models_data,
        })

    return records

# ── Обработка одного месяца ───────────────────────────────────────────────────
def process_month(year, month, all_synops):
    label      = f"{month:02d}.{year}"
    prefix     = f"{year}{month:02d}"
    start_date = f"{year}-{month:02d}-01"
    last_day   = calendar.monthrange(year, month)[1]
    end_date   = f"{year}-{month:02d}-{last_day:02d}"

    month_synops = [s for s in all_synops if s["telegramKey"].startswith(prefix)]
    if not month_synops:
        log.info("%s: нет сводок — пропуск", label)
        return None

    log.info("%s: %d сводок — загрузка моделей...", label, len(month_synops))

    hourly_by_model = {}
    for mid in MODELS:
        for attempt in range(3):
            try:
                h = fetch_model_month(mid, start_date, end_date)
                hourly_by_model[mid] = h
                log.info("  ✓ %s", mid)
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg and attempt < 2:
                    log.warning("  ⏳ %s — rate limit, жду 30с...", mid)
                    time.sleep(30)
                elif attempt == 2:
                    log.error("  ✗ %s — %s", mid, e)
                    hourly_by_model[mid] = None
                else:
                    time.sleep(5)
        time.sleep(DELAY_MODEL)

    records = build_records(month_synops, hourly_by_model)
    log.info("%s: собрано %d из %d записей", label, len(records), len(month_synops))
    return records

# ── GitHub: загрузка/сохранение одного файла ─────────────────────────────────
def gh_path_for(year, month):
    return f"data/modeldata/modelData_{year}_{month:02d}.json"

def save_to_github(year, month, records):
    path = gh_path_for(year, month)
    label = f"{month:02d}.{year}"

    # Получаем текущий sha (если файл уже есть)
    _, sha = gh_get_text(path)

    content = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    try:
        new_sha = gh_put(path, content, sha,
                         f"rebuild modelData {year}_{month:02d}")
        size_kb = len(content.encode()) / 1024
        log.info("%s: залито на GitHub (%.1f КБ)", label, size_kb)
        return new_sha
    except Exception as e:
        log.error("%s: ошибка записи на GitHub: %s", label, e)
        return None

# ── Загрузка SYNOP с GitHub ───────────────────────────────────────────────────
def load_all_synops(from_year, to_year):
    all_synops = []
    for year in range(from_year, to_year + 1):
        path = f"data/synop_{year}.txt"
        log.info("Загружаю %s...", path)
        text, _ = gh_get_text(path)
        if not text:
            log.warning("  ✗ %s — не найден", path)
            continue
        recs = parse_synop_text(text)
        log.info("  ✓ %d сводок", len(recs))
        all_synops.extend(recs)
    return all_synops

# ── Список уже существующих месяцев на GitHub ─────────────────────────────────
def get_existing_months():
    names = gh_list_dir("data/modeldata")
    existing = set()
    for name in names:
        m = re.match(r"modelData_(\d{4})_(\d{2})\.json", name)
        if m:
            existing.add((int(m.group(1)), int(m.group(2))))
    return existing

# ── Генерация списка месяцев ──────────────────────────────────────────────────
def month_range(from_ym, to_ym):
    months = []
    y, m = from_ym
    while (y, m) <= to_ym:
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    if not GITHUB_TOKEN:
        log.error("Нужна переменная GITHUB_TOKEN")
        sys.exit(1)

    args = sys.argv[1:]
    fill_only    = "--fill"     in args
    download_mode = "--download" in args
    args = [a for a in args if a not in ("--fill", "--download")]

    if download_mode:
        local_dir = args[0] if args else "data/modeldata"
        download_all(local_dir)
        return

    now = datetime.now(timezone.utc)
    # По умолчанию: с 2023-01 по предыдущий месяц
    prev_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)

    if len(args) >= 2:
        from_ym = tuple(int(x) for x in args[0].split("-"))
        to_ym   = tuple(int(x) for x in args[1].split("-"))
    elif len(args) == 1:
        from_ym = to_ym = tuple(int(x) for x in args[0].split("-"))
    else:
        from_ym = (2023, 1)
        to_ym   = prev_month

    months = month_range(from_ym, to_ym)
    log.info("Период: %d-%02d → %d-%02d (%d месяцев)",
             from_ym[0], from_ym[1], to_ym[0], to_ym[1], len(months))

    if fill_only:
        log.info("Режим --fill: проверяю существующие файлы на GitHub...")
        existing = get_existing_months()
        log.info("  Уже есть: %d месяцев", len(existing))
        months = [(y, m) for y, m in months if (y, m) not in existing]
        log.info("  Осталось обработать: %d месяцев", len(months))

    if not months:
        log.info("Нечего делать — все месяцы уже есть.")
        return

    # Загружаем SYNOP за нужный диапазон лет
    from_year = min(y for y, m in months)
    to_year   = max(y for y, m in months)
    log.info("Загружаю SYNOP %d–%d...", from_year, to_year)
    all_synops = load_all_synops(from_year, to_year)
    log.info("Всего сводок SYNOP: %d", len(all_synops))
    log.info("─" * 50)

    ok = skip = err = 0
    for i, (year, month) in enumerate(months, 1):
        log.info("[%d/%d] Обрабатываю %02d.%d...", i, len(months), month, year)
        try:
            records = process_month(year, month, all_synops)
            if records is None:
                skip += 1
            elif records:
                save_to_github(year, month, records)
                ok += 1
            else:
                log.warning("%02d.%d: 0 записей", month, year)
                skip += 1
        except Exception as e:
            log.error("%02d.%d: критическая ошибка: %s", month, year, e)
            err += 1

        log.info("─" * 50)
        if i < len(months):
            time.sleep(DELAY_MONTH)

    log.info("=== Готово: загружено %d, пропущено %d, ошибок %d ===", ok, skip, err)

def download_all(local_dir):
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    log.info("Получаю список файлов на GitHub...")
    names = gh_list_dir("data/modeldata")
    names = [n for n in names if re.match(r"modelData_\d{4}_\d{2}\.json", n)]
    log.info("Файлов на GitHub: %d", len(names))

    ok = err = skip = 0
    for i, name in enumerate(sorted(names), 1):
        local_path = local_dir / name
        if local_path.exists():
            log.info("[%d/%d] %s — уже есть, пропуск", i, len(names), name)
            skip += 1
            continue
        log.info("[%d/%d] %s — скачиваю...", i, len(names), name)
        try:
            text, _ = gh_get_text(f"data/modeldata/{name}")
            if text:
                local_path.write_text(text, encoding="utf-8")
                size_kb = local_path.stat().st_size / 1024
                log.info("  ✓ %.1f КБ", size_kb)
                ok += 1
            else:
                log.warning("  ✗ пустой ответ")
                err += 1
        except Exception as e:
            log.error("  ✗ %s", e)
            err += 1
        time.sleep(0.3)

    log.info("=== Скачано %d, пропущено %d, ошибок %d ===", ok, skip, err)

if __name__ == "__main__":
    main()
