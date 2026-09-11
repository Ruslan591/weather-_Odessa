"""
open_meteo_guard.py — общий circuit breaker для запросов к Open-Meteo,
разделяемый между независимыми cron-процессами (vps_pipeline.py,
update.py, open_meteo_frontal_confirm.py, open_meteo_field_fetch.py,
open_meteo_very_far_line.py).

Контекст: инцидент 10-11.09.2026 (docs/ai/MODEL_UPDATE_OUTAGE.md) — все
8 моделей словили HTTP 429 одновременно, ни один из независимых
скриптов/pipeline не знал, что остальные тоже заблокированы, и продолжал
попытки на каждом cron-тике (5 мин) в течение ~11 часов, пока не сбросилась
(предположительно суточная) квота Open-Meteo в полночь UTC.

Архитектура (см. docs/ai/MODEL_UPDATE_OUTAGE.md, Proposal v3 + уточнение
GPT про единый атомарный gate()):
  - Два состояния: CLOSED (норма) / OPEN (cooldown).
  - Один файл состояния (НЕ коммитится в git — как существующие
    _throttle_*.json, персистентный VPS-диск между cron-запусками) +
    отдельный lock-файл (fcntl.flock, тот же паттерн, что и в
    vps-github-bridge для git-операций).
  - Guard НЕ делает HTTP-запросов сам. Единственная точка, которой
    разрешено пробовать реальный запрос после истечения cooldown —
    "probe owner": проверка ecmwf_ifs в vps_pipeline.py (самый дешёвый
    существующий вызов, meta.json, без ретраев). Все остальные 4 точки
    входа вызывают gate(probe_owner=False) и просто пропускают свой шаг,
    пока состояние не станет CLOSED.
  - Backoff растёт ТОЛЬКО от провала recovery-probe (30м → 1ч → 2ч,
    потолок), а не от параллельных 429 у запросов, стартовавших ДО
    трипа — такие 429 при уже открытом OPEN являются no-op.

Использование (в каждой из 5 точек входа):
    import open_meteo_guard as guard

    gate = guard.gate(probe_owner=<True только для ecmwf_ifs-проверки>)
    if gate == "skip":
        ...пропустить шаг, 0 запросов...
        continue / return
    try:
        <обычный HTTP-запрos(ы) к Open-Meteo>
        if gate == "probe":
            guard.report_probe_result(success=True)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            if gate == "probe":
                guard.report_probe_result(success=False)
            else:
                guard.record_429()
            break  # не продолжать по остальным моделям в этом цикле
        raise
"""
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_cooldown.json")
LOCK_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_cooldown.lock")

# Backoff по числу trips (провалов recovery-probe): 30м → 1ч → 2ч (потолок).
_BACKOFF_SECONDS = {1: 1800, 2: 3600}
_BACKOFF_CEILING = 7200

_DEFAULT_STATE = {
    "state": "CLOSED",
    "cooldown_until": None,
    "trips": 0,
    "probe_claimed_at": None,
}


def _now():
    return datetime.now(timezone.utc)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _load():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # подстраховка на случай частично побитого/старого файла
        merged = dict(_DEFAULT_STATE)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULT_STATE)


def _save(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def _with_lock(fn):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def gate(probe_owner=False):
    """Единая атомарная точка входа (под flock). Возвращает:
      "proceed" — CLOSED, работать штатно;
      "probe"   — OPEN, cooldown истёк, ЭТОТ вызов атомарно получил
                  право на пробный запрос (только если probe_owner=True);
      "skip"    — во всех остальных случаях (OPEN и cooldown ещё активен;
                  ИЛИ cooldown истёк, но caller не probe_owner; ИЛИ probe
                  уже занят кем-то другим) — 0 запросов.
    """
    def _do():
        st = _load()
        if st.get("state", "CLOSED") == "CLOSED":
            return "proceed"

        cooldown_until = st.get("cooldown_until")
        now = _now()
        if cooldown_until:
            try:
                still_cooling = now < _parse(cooldown_until)
            except Exception:
                still_cooling = False
        else:
            still_cooling = False

        if still_cooling:
            return "skip"

        # cooldown истёк — окно для recovery-probe
        if not probe_owner:
            return "skip"
        if st.get("probe_claimed_at"):
            return "skip"  # probe уже кем-то застолблен (защита от гонки)

        st["probe_claimed_at"] = _fmt(now)
        _save(st)
        return "probe"

    return _with_lock(_do)


def record_429():
    """Вызывается НЕ-probe точками входа при первом 429 в своём цикле.
    Если CLOSED -> OPEN (база 30 мин, trips=1). Если уже OPEN -> no-op
    (это "хвостовой" запрос, стартовавший до того, как ворота закрылись —
    backoff от таких запросов НЕ растёт, см. Proposal v3 п.2)."""
    def _do():
        st = _load()
        if st.get("state", "CLOSED") == "CLOSED":
            st["state"] = "OPEN"
            st["trips"] = 1
            st["cooldown_until"] = _fmt(_now() + timedelta(seconds=_BACKOFF_SECONDS[1]))
            st["probe_claimed_at"] = None
            _save(st)
        # иначе — уже OPEN, ничего не меняем

    _with_lock(_do)


def report_probe_result(success):
    """Вызывается ТОЛЬКО probe-owner'ом (ecmwf_ifs-проверка в
    vps_pipeline.py) после реальной попытки запроса, выполненной этим
    caller'ом (guard сам сеть не трогает)."""
    def _do():
        st = _load()
        if success:
            st["state"] = "CLOSED"
            st["trips"] = 0
            st["cooldown_until"] = None
            st["probe_claimed_at"] = None
        else:
            trips = st.get("trips", 0) + 1
            wait_s = _BACKOFF_SECONDS.get(trips, _BACKOFF_CEILING)
            st["state"] = "OPEN"
            st["trips"] = trips
            st["cooldown_until"] = _fmt(_now() + timedelta(seconds=wait_s))
            st["probe_claimed_at"] = None
        _save(st)

    _with_lock(_do)


def status():
    """Только для диагностики/логов — не участвует в основной логике."""
    return _load()
