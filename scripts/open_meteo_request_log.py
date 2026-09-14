"""
open_meteo_request_log.py — единый лог фактических HTTP-вызовов к Open-Meteo,
разделяемый между всеми потребителями (vps_pipeline.py, update.py,
open_meteo_frontal_confirm.py; open_meteo_field_fetch.py и
open_meteo_very_far_line.py отключены с 2026-09-05, но модуль готов и для них).

Введено 2026-09-12 по требованию GPT review (OPEN_METEO_REQUEST_ARCHITECTURE_001):
"Нужен единый счётчик/лог реальных HTTP-вызовов Open-Meteo, чтобы следующий
429 можно было количественно разобрать, а не оценивать post factum."

Формат: JSON Lines, один вызов — одна строка, порядок строк в файле = порядок
фактических вызовов (запись только под flock — atomic append, тот же паттерн,
что _open_meteo_cooldown.json в open_meteo_guard.py). НЕ коммитится в git —
персистентный VPS-диск, как остальные _throttle_*/_state_* файлы; это
диагностический журнал, не бизнес-данные.

Поля одной записи:
  ts        — UTC ISO timestamp вызова (время самого HTTP-запроса, не события)
  script    — вызывающий файл, напр. "vps_pipeline.py"
  function  — вызывающая функция, напр. "fetch_run_time_and_interval"
  endpoint  — "meta" | "forecast" | "historical"
  model     — id/metaId модели, или None если запрос не про конкретную модель
  status    — "ok" | "429" | "<HTTP код>" | "error:<текст>" | "skip_gate"
  gate      — "proceed" | "probe" | "skip" | None (если guard.gate() не проверялся в этой точке)
  attempt   — номер попытки ВНУТРИ retry()/локального ретрая (1 = первая)

Порядок строк в файле — уже достаточная "request sequence" (запись строго
под flock), отдельный счётчик не нужен.

Ротация: без внешнего logrotate — при превышении MAX_LINES обрезаем до
последних KEEP_LINES прямо в log(). Диагностика нужна за последние часы/
сутки, не за всю историю проекта.

Использование:
    import open_meteo_request_log as om_log
    om_log.log("vps_pipeline.py", "fetch_run_time_and_interval",
               endpoint="meta", model="ecmwf_ifs025", status="ok", gate="proceed")
"""
import fcntl
import json
import os
from datetime import datetime, timezone

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH  = os.path.join(BASE_DIR, "data", "_open_meteo_requests.jsonl")
LOCK_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_requests.lock")

MAX_LINES  = 20000   # грубый потолок — несколько дней при обычной нагрузке
KEEP_LINES = 15000   # до скольки обрезаем при превышении MAX_LINES
_BYTES_PER_LINE_ESTIMATE = 120  # дешёвый предфильтр по размеру файла в байтах,
                                 # чтобы не читать файл целиком на каждой записи


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(script, function, endpoint, model=None, status="ok", gate=None, attempt=1):
    """Добавляет одну запись в лог. Никогда не бросает исключение наружу —
    диагностика не должна ронять основной pipeline."""
    entry = {
        "ts": _now_iso(),
        "script": script,
        "function": function,
        "endpoint": endpoint,
        "model": model,
        "status": status,
        "gate": gate,
        "attempt": attempt,
    }
    line = json.dumps(entry, ensure_ascii=False)

    try:
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        with open(LOCK_PATH, "a") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                _maybe_rotate()
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
    except Exception:
        pass


def _maybe_rotate():
    """Вызывается уже ПОД flock (см. log()). Читает файл целиком только
    если он подрос настолько, что порог MAX_LINES вообще мог быть превышен
    (дешёвая проверка размера в байтах как предфильтр)."""
    try:
        if os.path.getsize(LOG_PATH) < MAX_LINES * _BYTES_PER_LINE_ESTIMATE:
            return
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_LINES:
            tail = lines[-KEEP_LINES:]
            tmp = LOG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(tail)
            os.replace(tmp, LOG_PATH)
    except Exception:
        pass
