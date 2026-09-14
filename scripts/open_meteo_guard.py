"""
open_meteo_guard.py — общий circuit breaker + rate-limiter для запросов к
Open-Meteo, разделяемый между независимыми cron-процессами
(vps_pipeline.py, update.py, open_meteo_frontal_confirm.py,
open_meteo_field_fetch.py, open_meteo_very_far_line.py).

Контекст: инцидент 10-11.09.2026 (docs/ai/MODEL_UPDATE_OUTAGE.md) — все
8 моделей словили HTTP 429 одновременно, ни один из независимых
скриптов/pipeline не знал, что остальные тоже заблокированы. Инцидент
13.09.2026 (docs/ai/OPEN_METEO_DISCOVERY_BACKOFF_001.md) — двойной 429
(discovery-полинг каждые 5 мин для здоровых моделей + разовое открытие
шлюза после cooldown без учёта реального forecast/archive-бюджета).

[ПЕРЕПИСАНО 2026-09-13, TASK OPEN_METEO_DISCOVERY_BACKOFF_001, GPT APPROVE
Proposal v4] Архитектура v2:
  - ТРИ состояния circuit breaker'а: CLOSED (норма) / OPEN (cooldown) /
    RECOVERING (контролируемое последовательное восстановление после
    успешного probe, ПЕРЕД полным CLOSED).
  - Отдельный token-bucket rate-limiter для реальных forecast/archive
    HTTP-запросов. meta.json НЕ учитывается в этом бюджете — своя, не
    API-квотная модель ограничений на стороне Open-Meteo (см.
    docs/ai/OPEN_METEO_DISCOVERY_BACKOFF_001.md, Proposal п.2).
  - Guard и limiter объединены под ОДНИМ flock-локом
    (UNIFIED_LOCK_PATH) и одной атомарной функцией reserve_request() —
    решение "можно ли делать запрос" принимается разом для обоих
    механизмов, запись состояния на диск — all-or-nothing: если что-то
    одно отказало, второе тоже не фиксируется, "слот" не теряется
    (см. раздел "Атомарность Guard + Rate Limiter" в Proposal v4).
  - Guard НЕ делает HTTP-запросов сам. Единственная точка, которой
    разрешено пробовать реальный запрос после истечения cooldown —
    "probe owner": проверка ecmwf_ifs в vps_pipeline.py (самый дешёвый
    существующий вызов, meta.json, без ретраев, ВНЕ rate-limiter'а).
  - RECOVERING не гейтит meta-запросы (discovery должен продолжаться и
    не расходует forecast/archive-бюджет) — пауза RECOVERY_INTERVAL_SEC
    применяется ТОЛЬКО к forecast/archive-запросам.
  - Backoff (30м → 1ч → 2ч, потолок) растёт от ДВУХ источников: провала
    probe (как раньше) ИЛИ 429 на forecast/archive ВО ВРЕМЯ RECOVERING
    (новое). "Хвостовые" 429 при уже открытом OPEN (не probe, не
    RECOVERING) — по-прежнему no-op, backoff не растят.

Использование (meta.json discovery, только vps_pipeline.py):
    import open_meteo_guard as guard

    decision = guard.reserve_request("meta", probe_owner=<True для ecmwf_ifs>)
    if decision == "skip":
        continue  # 0 запросов
    try:
        <HTTP-запрос к meta.json>
        guard.report_request_result("meta", "success")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            guard.report_request_result("meta", "429")
            continue
        guard.report_request_result("meta", "error")
        raise

Использование (forecast/archive, ЛЮБАЯ точка входа — update.py,
open_meteo_frontal_confirm.py и т.д. — вызов НЕПОСРЕДСТВЕННО перед КАЖДЫМ
отдельным HTTP-запросом, НЕ один раз на цикл/batch):
    decision = guard.reserve_request("forecast_or_archive")
    if decision == "skip":
        continue  # пропустить именно этот запрос, естественный повтор
                  # на следующей итерации/следующем due-тике
    try:
        <HTTP-запрос к /v1/forecast или /v1/archive>
        guard.report_request_result("forecast_or_archive", "success")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            guard.report_request_result("forecast_or_archive", "429")
            continue
        guard.report_request_result("forecast_or_archive", "error")
        raise

Обратная совместимость: gate()/record_429()/report_probe_result()
сохранены как тонкие обёртки над reserve_request()/report_request_result()
для endpoint_class="meta".
"""
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD_STATE_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_cooldown.json")
LIMITER_STATE_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_rate_window.json")
# [ИЗМЕНЕНО 2026-09-13] Один общий лок вместо отдельных локов guard'а и
# limiter'а — guard-state и limiter-state читаются/решаются/пишутся под
# ОДНИМ flock, чтобы между "разрешил guard" и "разрешил limiter" не мог
# вклиниться другой процесс.
UNIFIED_LOCK_PATH = os.path.join(BASE_DIR, "data", "_open_meteo_request.lock")

# Backoff по числу trips (провалов recovery-probe ИЛИ 429 во время
# RECOVERING): 30м → 1ч → 2ч (потолок).
_BACKOFF_SECONDS = {1: 1800, 2: 3600}
_BACKOFF_CEILING = 7200

# Пауза между последовательно выдаваемыми RECOVERING-разрешениями для
# forecast/archive-запросов — due-очередь, накопившаяся за cooldown,
# разбирается по одному, а не разом.
RECOVERY_INTERVAL_SEC = 30
# Сколько подряд успешных forecast/archive-запросов в RECOVERING нужно,
# чтобы полностью закрыть guard (RECOVERING → CLOSED).
RECOVERING_SUCCESS_TARGET = 3

# Token-bucket для реальных forecast/archive запросов. meta.json НЕ
# учитывается.
LIMITER_CAPACITY = 8
LIMITER_REFILL_SECONDS_PER_TOKEN = 8
# Жёсткий минимальный интервал между ЛЮБЫМИ двумя разрешёнными forecast/
# archive-запросами (межпроцессно).
MIN_INTERVAL_SEC = 3

_DEFAULT_GUARD_STATE = {
    "state": "CLOSED",             # CLOSED | OPEN | RECOVERING
    "cooldown_until": None,
    "trips": 0,
    "probe_claimed_at": None,
    "recovering_streak": 0,
    "last_recovering_grant_at": None,
}

_DEFAULT_LIMITER_STATE = {
    "tokens": float(LIMITER_CAPACITY),
    "last_refill_at": None,
    "last_granted_at": None,
}


def _now():
    return datetime.now(timezone.utc)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(default)
        merged.update(data)
        return merged
    except Exception:
        return dict(default)


def _save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _load_guard():
    return _load(GUARD_STATE_PATH, _DEFAULT_GUARD_STATE)


def _load_limiter():
    return _load(LIMITER_STATE_PATH, _DEFAULT_LIMITER_STATE)


def _with_lock(fn):
    os.makedirs(os.path.dirname(UNIFIED_LOCK_PATH), exist_ok=True)
    with open(UNIFIED_LOCK_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _decide_guard(st, probe_owner, now, endpoint_class):
    """Решение guard'а — ЧИСТО В ПАМЯТИ, ничего не пишет на диск.
    Возвращает (decision, new_state):
      "proceed"    — CLOSED (или meta-запрос во время RECOVERING, которая
                     этой паузой не гейтится) — работать штатно;
      "probe"      — OPEN, cooldown истёк, ЭТОТ вызов атомарно получил
                     право на пробный meta.json-запрос (только probe_owner);
      "recovering" — RECOVERING (forecast/archive), ЭТОМУ вызову выдан
                     очередной последовательный слот (прошло >=
                     RECOVERY_INTERVAL_SEC с прошлой выдачи);
      "skip"       — во всех остальных случаях, 0 запросов.
    """
    state = st.get("state", "CLOSED")

    if state == "CLOSED":
        return "proceed", st

    if state == "RECOVERING":
        if endpoint_class == "meta":
            # meta.json не расходует forecast/archive-бюджет и не
            # участвует в верификации рекавери — discovery продолжается
            # как обычно.
            return "proceed", st
        last_grant = st.get("last_recovering_grant_at")
        if last_grant:
            try:
                ready = now >= _parse(last_grant) + timedelta(seconds=RECOVERY_INTERVAL_SEC)
            except Exception:
                ready = True
        else:
            ready = True
        if not ready:
            return "skip", st
        new_st = dict(st)
        new_st["last_recovering_grant_at"] = _fmt(now)
        return "recovering", new_st

    # state == "OPEN"
    cooldown_until = st.get("cooldown_until")
    if cooldown_until:
        try:
            still_cooling = now < _parse(cooldown_until)
        except Exception:
            still_cooling = False
    else:
        still_cooling = False

    if still_cooling:
        return "skip", st

    # cooldown истёк — окно для recovery-probe (только meta, только probe_owner)
    if endpoint_class != "meta" or not probe_owner:
        return "skip", st
    if st.get("probe_claimed_at"):
        return "skip", st  # probe уже кем-то застолблен (защита от гонки)

    new_st = dict(st)
    new_st["probe_claimed_at"] = _fmt(now)
    return "probe", new_st


def _decide_limiter(st, now):
    """Решение limiter'а — ЧИСТО В ПАМЯТИ. Возвращает (granted: bool, new_state)."""
    last_refill = st.get("last_refill_at")
    tokens = float(st.get("tokens", LIMITER_CAPACITY))
    if last_refill:
        try:
            elapsed = (now - _parse(last_refill)).total_seconds()
        except Exception:
            elapsed = 0.0
    else:
        elapsed = 0.0
    if elapsed > 0:
        tokens = min(LIMITER_CAPACITY, tokens + elapsed / LIMITER_REFILL_SECONDS_PER_TOKEN)

    last_granted = st.get("last_granted_at")
    if last_granted:
        try:
            interval_ok = (now - _parse(last_granted)).total_seconds() >= MIN_INTERVAL_SEC
        except Exception:
            interval_ok = True
    else:
        interval_ok = True

    new_st = dict(st)
    new_st["tokens"] = tokens
    new_st["last_refill_at"] = _fmt(now)

    if tokens < 1.0 or not interval_ok:
        # Рефилл (течение времени) всё равно фиксируем — это не "трата
        # токена", а просто синхронизация часов бакета.
        return False, new_st

    new_st["tokens"] = tokens - 1.0
    new_st["last_granted_at"] = _fmt(now)
    return True, new_st


def reserve_request(endpoint_class, probe_owner=False):
    """Единая атомарная точка входа (под UNIFIED_LOCK_PATH).

    endpoint_class:
      "meta"                — meta.json discovery-проверка (только
                               vps_pipeline.py). Rate-limiter НЕ проверяется.
      "forecast_or_archive" — реальный /v1/forecast или /v1/archive
                               запрос. Проверяются И guard, И limiter.

    Возвращает "proceed" | "probe" | "recovering" | "skip".
    Запись состояния на диск — ТОЛЬКО при финальном разрешении
    (all-or-nothing): если guard сказал "skip" — ничего не пишем; если
    guard разрешил, но limiter отказал — guard-состояние ТОЖЕ не
    сохраняется (слот не потрачен, доступен на следующей попытке).
    Лимитер (при отказе) всё равно фиксирует свой рефилл — это не связано
    с guard-слотом и не требует отдельного отката.
    """
    def _do():
        now = _now()
        guard_st = _load_guard()
        guard_decision, guard_st_new = _decide_guard(guard_st, probe_owner, now, endpoint_class)

        if guard_decision == "skip":
            return "skip"

        if endpoint_class == "meta":
            if guard_st_new is not guard_st:
                _save(GUARD_STATE_PATH, guard_st_new)
            return guard_decision  # "proceed" | "probe"

        # forecast_or_archive — нужно ЕЩЁ И разрешение limiter'а, в ТОЙ ЖЕ
        # критической секции.
        limiter_st = _load_limiter()
        granted, limiter_st_new = _decide_limiter(limiter_st, now)
        _save(LIMITER_STATE_PATH, limiter_st_new)  # рефилл фиксируем всегда
        if not granted:
            # guard_st_new НЕ сохраняем: разрешение guard'а не состоялось
            # для реального запроса, слот не потрачен, откатывать нечего
            # (записи ещё не было).
            return "skip"

        if guard_st_new is not guard_st:
            _save(GUARD_STATE_PATH, guard_st_new)
        return guard_decision  # "proceed" | "recovering"

    return _with_lock(_do)


def report_request_result(endpoint_class, outcome):
    """Единая атомарная точка репорта исхода (под UNIFIED_LOCK_PATH).
    Читает АКТУАЛЬНОЕ guard-состояние с диска на момент репорта (не то,
    что было на момент reserve_request()) — исход применяется корректно,
    даже если между reserve и report состояние успел изменить другой
    процесс.

    outcome ∈ {"success", "429", "error"}:
      "success" — 2xx;
      "429"     — HTTP 429;
      "error"   — любая другая ошибка (не-2xx HTTP, timeout, network) —
                  НЕ success и не 429.
    """
    def _do():
        st = _load_guard()
        state = st.get("state", "CLOSED")
        now = _now()

        if state == "CLOSED":
            if outcome == "429":
                new_st = dict(st)
                new_st["state"] = "OPEN"
                new_st["trips"] = 1
                new_st["cooldown_until"] = _fmt(now + timedelta(seconds=_BACKOFF_SECONDS[1]))
                new_st["probe_claimed_at"] = None
                _save(GUARD_STATE_PATH, new_st)
            # success/error при CLOSED — фиксировать нечего
            return

        if state == "OPEN":
            if st.get("probe_claimed_at"):
                # Это исход probe-попытки (единственный, кто держит
                # probe_claimed_at в этот момент).
                if outcome == "success":
                    new_st = dict(st)
                    new_st["state"] = "RECOVERING"
                    new_st["recovering_streak"] = 0
                    new_st["probe_claimed_at"] = None
                    new_st["last_recovering_grant_at"] = None
                    # trips НЕ сбрасываем здесь — рекаверия ещё не
                    # подтверждена (сбрасывается только при полном успехе
                    # RECOVERING, см. ниже).
                    _save(GUARD_STATE_PATH, new_st)
                elif outcome == "429":
                    trips = st.get("trips", 0) + 1
                    wait_s = _BACKOFF_SECONDS.get(trips, _BACKOFF_CEILING)
                    new_st = dict(st)
                    new_st["state"] = "OPEN"
                    new_st["trips"] = trips
                    new_st["cooldown_until"] = _fmt(now + timedelta(seconds=wait_s))
                    new_st["probe_claimed_at"] = None
                    _save(GUARD_STATE_PATH, new_st)
                else:  # "error" — сетевая помеха, не признак throttling
                    new_st = dict(st)
                    new_st["probe_claimed_at"] = None
                    _save(GUARD_STATE_PATH, new_st)
            else:
                # "Хвостовой" запрос (не probe), стартовавший до/во время
                # закрытия ворот. Только 429 растит backoff, и то — уже
                # обработано выше в ветке CLOSED (переход в OPEN). Здесь
                # state уже OPEN и это не probe — 429/success/error все
                # являются no-op (как в исходной реализации record_429()).
                pass
            return

        if state == "RECOVERING":
            if endpoint_class == "meta":
                # meta.json не участвует в верификации рекавери (не входит
                # в forecast/archive-бюджет, N=3 считается ТОЛЬКО по
                # forecast_or_archive) — исход meta-запроса во время
                # RECOVERING полностью игнорируется, streak не трогаем.
                return
            if outcome == "429":
                trips = st.get("trips", 0) + 1
                wait_s = _BACKOFF_SECONDS.get(trips, _BACKOFF_CEILING)
                new_st = dict(st)
                new_st["state"] = "OPEN"
                new_st["trips"] = trips
                new_st["cooldown_until"] = _fmt(now + timedelta(seconds=wait_s))
                new_st["recovering_streak"] = 0
                new_st["last_recovering_grant_at"] = None
                _save(GUARD_STATE_PATH, new_st)
            elif outcome == "success":
                streak = st.get("recovering_streak", 0) + 1
                new_st = dict(st)
                if streak >= RECOVERING_SUCCESS_TARGET:
                    new_st["state"] = "CLOSED"
                    new_st["trips"] = 0
                    new_st["cooldown_until"] = None
                    new_st["recovering_streak"] = 0
                    new_st["last_recovering_grant_at"] = None
                else:
                    new_st["recovering_streak"] = streak
                _save(GUARD_STATE_PATH, new_st)
            else:
                # "error" — по GPT APPROVE (2026-09-13): recovering_streak
                # НЕ увеличивать и НЕ сбрасывать, state остаётся RECOVERING.
                pass
            return

    _with_lock(_do)


def status():
    """Только для диагностики/логов — не участвует в основной логике."""
    return {"guard": _load_guard(), "limiter": _load_limiter()}


# ---------------------------------------------------------------------------
# Обратная совместимость со старым API (gate/record_429/report_probe_result),
# реализована через reserve_request()/report_request_result() для
# endpoint_class="meta".
# ---------------------------------------------------------------------------

def gate(probe_owner=False):
    return reserve_request("meta", probe_owner=probe_owner)


def record_429():
    report_request_result("meta", "429")


def report_probe_result(success):
    report_request_result("meta", "success" if success else "429")
