#!/usr/bin/env python3
"""
calc_weights.py — пересчёт model_weights.json из месячных файлов.

Режимы запуска:
  GitHub Actions (cron):  python calc_weights.py
  Локально:               LOCAL=1 python calc_weights.py

В GitHub Actions читает data/modeldata/YYYY_MM.json из репозитория и пишет обратно.
Локально читает из LOCAL_DATA_DIR и пишет в LOCAL_OUT.
"""

import os, json, base64, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import threading, queue as _queue

# ── Логирование ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Gist live-лог ─────────────────────────────────────────────────────────────
GIST_ID    = os.environ.get("GIST_ID", "")
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")

_gist_lines = []
_gist_queue = _queue.Queue()

def _gist_worker():
    while True:
        content = _gist_queue.get()
        # Дренируем очередь — берём только последнее накопившееся значение
        while not _gist_queue.empty():
            _gist_queue.task_done()
            content = _gist_queue.get()
        if GIST_ID and GIST_TOKEN:
            data = json.dumps({"files": {"update_live.log": {"content": content}}}).encode()
            req = Request(
                f"https://api.github.com/gists/{GIST_ID}",
                data=data,
                headers={
                    "Authorization": f"Bearer {GIST_TOKEN}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json"
                },
                method="PATCH"
            )
            try:
                with urlopen(req, timeout=15): pass
            except Exception as e:
                log.warning("gist_log error: %s", e)
        _gist_queue.task_done()

threading.Thread(target=_gist_worker, daemon=True).start()

def gist_log(msg):
    log.info(msg)
    if not GIST_ID or not GIST_TOKEN:
        return
    _gist_lines.append(msg)
    # Gist ограничен ~1 МБ — держим только последние 200 строк
    if len(_gist_lines) > 200:
        del _gist_lines[:-200]
    _gist_queue.put("\n".join(_gist_lines))

# ── Конфиг ───────────────────────────────────────────────────────────────────
GITHUB_OWNER   = "ruslan591"
GITHUB_REPO    = "weather-_Odessa"
MODELDATA_DIR  = "data/modeldata"
WEIGHTS_PATH   = "data/model_weights.json"

LOCAL_MODE     = os.environ.get("LOCAL") == "1"
LOCAL_DATA_DIR = Path("/storage/emulated/0/Documents/weather/data/modeldata")
LOCAL_OUT      = Path("/storage/emulated/0/Documents/weather/data/model_weights.json")

SEASON_MAP = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM",  4: "MAM", 5: "MAM",
    6: "JJA",  7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}

# ── GitHub API ────────────────────────────────────────────────────────────────
def gh_headers():
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def http_get(url, headers=None, timeout=60):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def gh_list_dir(path):
    """Возвращает список имён файлов в папке репозитория."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        items = json.loads(http_get(url, gh_headers()))
        return [item["name"] for item in items if item["type"] == "file"]
    except HTTPError as e:
        if e.code == 404:
            log.warning("Папка %s не найдена", path)
            return []
        raise

def gh_get(path):
    """Возвращает (text, sha) или (None, None)."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        resp = json.loads(http_get(url, gh_headers()))
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    sha = resp.get("sha")
    if "content" in resp:
        text = base64.b64decode(resp["content"].replace("\n", "")).decode("utf-8")
        return text, sha
    dl_url = resp.get("download_url")
    if dl_url:
        return http_get(dl_url, timeout=120), sha
    return None, sha

def gh_put(path, content, sha, message):
    """Записывает файл на GitHub. Возвращает новый sha."""
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
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

# ── Утилиты ──────────────────────────────────────────────────────────────────
def utcnow():
    return datetime.now(timezone.utc)

def get_season(year, month):
    s  = SEASON_MAP[month]
    sy = year + 1 if month == 12 else year
    return s, f"{sy}-{s}"

def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

# ── Расчёт весов ─────────────────────────────────────────────────────────────
def compute_mae_per_model(records):
    PARAMS = ["temp", "pressure", "wind", "windDir", "cloudcover", "precip", "visibility"]
    errs = {}
    for rec in records:
        obs = rec.get("obs", {})
        for mid, mdata in rec.get("models", {}).items():
            if mid not in errs:
                errs[mid] = {p: [] for p in PARAMS}
            for param in PARAMS:
                ov = obs.get(param)
                mv = mdata.get(param)
                if ov is None or mv is None:
                    continue
                ae = angle_diff(mv, ov) if param == "windDir" else abs(mv - ov)
                errs[mid][param].append(ae)
    result = {}
    for mid, params in errs.items():
        result[mid] = {}
        for param, vals in params.items():
            if vals:
                result[mid][param] = {"mae": round(sum(vals) / len(vals), 4), "n": len(vals)}
    return result

def top3_for_param(model_mae, param, all_models):
    scored = []
    for mid in all_models:
        if mid in model_mae and param in model_mae[mid]:
            scored.append({"model": mid,
                           "mae":   model_mae[mid][param]["mae"],
                           "n":     model_mae[mid][param]["n"]})
    scored.sort(key=lambda x: x["mae"])
    return scored[:3]

def make_section(period_groups, all_models):
    PARAMS = ["temp", "pressure", "wind", "windDir", "cloudcover", "precip", "visibility"]
    section = {}
    for period_key, recs in sorted(period_groups.items()):
        model_mae = compute_mae_per_model(recs)
        section[period_key] = {}
        for param in PARAMS:
            section[period_key][param] = top3_for_param(model_mae, param, all_models)
    return section

def build_weights(all_records):
    now       = utcnow()
    cutoff_3y = now - timedelta(days=3 * 365)

    groups = {
        "allSeasons": {},
        "allMonths":  {},
        "seasonal":   {},
        "monthly":    {},
    }
    days_set = set()

    for rec in all_records:
        st = rec.get("synopTime", "")
        if len(st) < 8:
            continue
        try:
            y, mo, dd = int(st[:4]), int(st[4:6]), int(st[6:8])
            dt = datetime(y, mo, dd, tzinfo=timezone.utc)
        except Exception:
            continue
        days_set.add(st[:8])
        season, season_key = get_season(y, mo)
        month_key = f"{y}-{st[4:6]}"
        month_num = st[4:6]

        groups["allSeasons"].setdefault(season, []).append(rec)
        groups["allMonths"].setdefault(month_num, []).append(rec)
        if dt >= cutoff_3y:
            groups["seasonal"].setdefault(season_key, []).append(rec)
            groups["monthly"].setdefault(month_key, []).append(rec)

    all_models = sorted({mid for rec in all_records for mid in rec.get("models", {})})
    gist_log(f"  Моделей: {len(all_models)}: {', '.join(all_models)}")

    gist_log("  Считаю allSeasons...")
    sec_all_seasons = make_section(groups["allSeasons"], all_models)
    gist_log("  Считаю allMonths...")
    sec_all_months  = make_section(groups["allMonths"],  all_models)
    gist_log("  Считаю seasonal (3 года)...")
    sec_seasonal    = make_section(groups["seasonal"],   all_models)
    gist_log("  Считаю monthly (3 года)...")
    sec_monthly     = make_section(groups["monthly"],    all_models)

    days_sorted = sorted(days_set)
    return {
        "updated":  now.isoformat(),
        "coverage": {
            "from":    days_sorted[0]  if days_sorted else None,
            "to":      days_sorted[-1] if days_sorted else None,
            "days":    len(days_sorted),
            "records": len(all_records),
        },
        "allSeasons": sec_all_seasons,
        "allMonths":  sec_all_months,
        "seasonal":   sec_seasonal,
        "monthly":    sec_monthly,
    }

# ── Загрузка данных ───────────────────────────────────────────────────────────
def load_records_local():
    all_records = []
    if not LOCAL_DATA_DIR.exists():
        log.error("Папка не найдена: %s", LOCAL_DATA_DIR)
        return []
    files = sorted(LOCAL_DATA_DIR.glob("*.json"))
    log.info("  Файлов локально: %d", len(files))
    for path in files:
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)
        size_kb = path.stat().st_size / 1024
        log.info("  [%s] %s: %d записей · %.1f КБ", ts, path.name, len(recs), size_kb)
        all_records.extend(recs)
    return all_records

def load_records_github():
    all_records = []
    files = sorted(gh_list_dir(MODELDATA_DIR))
    gist_log(f"  Файлов в репозитории: {len(files)}")
    for fname in files:
        if not fname.endswith(".json"):
            continue
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        text, _ = gh_get(f"{MODELDATA_DIR}/{fname}")
        if not text:
            gist_log(f"  [{ts}] ✗ {fname} — не загружен")
            continue
        try:
            recs = json.loads(text)
            size_kb = len(text.encode("utf-8")) / 1024
            gist_log(f"  [{ts}] {fname}: {len(recs)} записей · {size_kb:.1f} КБ")
            all_records.extend(recs)
        except Exception as e:
            gist_log(f"  [{ts}] ✗ {fname} — ошибка парсинга: {e}")
    return all_records

# ── Запуск ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    gist_log("=== calc_weights.py запущен ===")

    if LOCAL_MODE:
        gist_log("Режим: локальный")
        all_records = load_records_local()
    else:
        gist_log("Режим: GitHub Actions")
        all_records = load_records_github()

    if not all_records:
        log.error("Нет данных. Завершение.")
        exit(1)

    gist_log(f"  Всего записей: {len(all_records)}, расчёт весов...")
    weights = build_weights(all_records)

    if LOCAL_MODE:
        with open(LOCAL_OUT, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)
        gist_log(f"✓ Готово локально. {LOCAL_OUT}")
    else:
        _, mw_sha = gh_get(WEIGHTS_PATH)
        content = json.dumps(weights, ensure_ascii=False, indent=2)
        gh_put(WEIGHTS_PATH, content, mw_sha, "update model_weights.json")
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        size_kb = len(content.encode("utf-8")) / 1024
        gist_log(f"  [{ts}] ✓ model_weights.json обновлён · {size_kb:.1f} КБ")

    gist_log(f"  Период: {weights['coverage']['from']} → {weights['coverage']['to']}, дней: {weights['coverage']['days']}")
    gist_log("=== calc_weights.py готово ===")
    _gist_queue.join()  # ждём отправки последнего сообщения перед выходом
