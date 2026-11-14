# -*- coding: utf-8 -*-
"""Менеджер сделки (манименеджмент по классам), счёт «Регрессия». Решение пользователя 2026-11-14: стоп, порог и точка безубытка, цель и частичное закрытие
считаются математически, отдельно для каждого вида сделки; один шаблон на все сделки не годится. docs/topics/exit_math.md.

Как работает (версия 1):
  1. Класс сделки при исполнении заявки (chan_orders кладёт p["cls"]): для входов из слежения «пробой|отбой x по|против|flat режима рынка», для лимитов правил канала limit_top / limit_bottom.
  2. Правила класса (attach): ступенчатый стоп «лесенка» (чем дальше цена ушла в нашу сторону, тем ближе к входу и дальше за вход подтягивается стоп; стоп только ужесточается),
     порог БУ и его замок в R, трейлинг. Уровни лесенки и порог БУ масштабируются скоростью класса (медиана хода цены в R по прошлым сделкам класса, PRIORS): быстрый класс получает более далёкие
     уровни, медленный - более близкие. Классы с малым числом сделок берут общие уровни. Все числа правятся без перезапуска: POS_DIR/mgr_cfg.json (по классам и общие, enabled=false выключает менеджер).
  3. «Что было бы»: для каждой позиции с менеджером параллельно считается копия по прежним правилам счёта (p["base"], mgr_off); итог обеих виден рядом.
Менеджер не ослабляет стоп и ничего не открывает; ошибки менеджера не должны ломать трекер (все вызовы обёрнуты в try).
Реальных ордеров нет (бумага)."""
import copy, json, os

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
CF = os.path.join(D, "mgr_cfg.json")

# Профиль классов по закрытым сделкам счёта на 2026-11-14 (scripts/exit_slice.py): медиана хода цены в нашу сторону (MFE в R) и число сделок. Это описание прошлого, не прогноз; обновляется вручную / mgr_cfg.json.
PRIORS = {"bounce|with": (0.70, 23), "bounce|flat": (0.34, 21), "bounce|against": (0.15, 4), "breakout|with": (1.04, 18), "breakout|against": (0.98, 23),
          "breakout|flat": (0.48, 25), "limit_top": (1.03, 106), "limit_bottom": (0.85, 63)}
BASE_MED = 0.90     # медиана «в среднем по счёту»: класс с такой скоростью получает коэффициент 1.0
MIN_N = 15          # меньше сделок в классе: коэффициент 1.0
DEFAULT = {
    "enabled": False,   # ВЫКЛЮЧЕНО по умолчанию: проверка на путях цены 295 сделок (scripts/mgr_sim.py, 2026-11-14) показала, что лесенка v1 ухудшает итог (-35.9 R -> -52.9 R); включать только после нового варианта правил, см. docs/topics/exit_math.md
    "speed": {"min": 0.5, "max": 1.2},
    "common": {"lad": [[0.5, -0.45], [0.8, -0.10]], "be_r": 1.0, "lock_r": 0.15, "trail_atr": 1.5},   # lad: [[MFE в R, стоп в R от входа], ...]; lock_r: замок БУ в R (покрывает комиссии ~0.12R)
    "classes": {},      # {"bounce|with": {"lad": [...], "be_r": 0.8, ...}} - переопределения
}
_cache = [None, None]


def load():
    try: m = os.stat(CF).st_mtime
    except OSError: m = None
    if _cache[0] == m and _cache[1] is not None: return _cache[1]
    c = copy.deepcopy(DEFAULT)
    if m is not None:
        try:
            s = json.load(open(CF, encoding="utf-8"))
            for k in ("enabled",): c[k] = s.get(k, c[k])
            for k in ("speed", "common"): c[k].update(s.get(k) or {})
            c["classes"] = s.get("classes") or {}
        except Exception: c = copy.deepcopy(DEFAULT)
    _cache[0] = m; _cache[1] = c
    return c


def classify(o):
    """Класс по заявке: для tg_* 'setup|rel' (rel: with|against|flat по согласию стороны с режимом рынка), для лимитов правил канала limit_top / limit_bottom."""
    rule = o.get("rule") or ""
    if rule in ("tg_market", "tg_stop", "tg_limit"):
        rg = (o.get("regime") or {}).get("regime"); side = o.get("side")
        rel = "flat" if rg in (None, "flat") else ("with" if (rg == "down") == (side == "short") else "against")
        return "%s|%s" % (o.get("setup") or "bounce", rel)
    if rule == "chan_top": return "limit_top"
    if rule == "chan_bottom": return "limit_bottom"
    return "other"


def factor(cls, c=None):
    c = c or load(); med, n = PRIORS.get(cls, (None, 0))
    if med is None or n < MIN_N: return 1.0
    return max(c["speed"]["min"], min(c["speed"]["max"], med / BASE_MED))


def params(cls, c=None):
    """Итоговые правила класса: общие + переопределения класса; уровни лесенки и порог БУ умножены на коэффициент скорости (если для класса не задан свой явный lad / be_r)."""
    c = c or load(); f = factor(cls, c); p = copy.deepcopy(c["common"]); ov = c["classes"].get(cls) or {}
    if "lad" not in ov: p["lad"] = [[round(l * f, 3), s] for l, s in p["lad"]]
    if "be_r" not in ov: p["be_r"] = round(p["be_r"] * f, 3)
    p.update(ov); p["f"] = round(f, 3)
    return p


def attach(p):
    """Один раз на позицию с классом: фиксирует правила класса p['mgr'] и создаёт копию для сравнения p['base'] (прежние правила счёта). Возвращает True, если что-то добавлено."""
    c = load()
    if not c.get("enabled") or not p.get("cls") or p.get("mgr_off") or "mgr" in p or p.get("status") != "open" or p.get("xr") == "flat_brk": return False
    m = params(p["cls"], c); p["mgr"] = m
    sd = 1 if p["side"] == "long" else -1; p["be_px"] = p["entry"] + sd * p["R"] * m["be_r"]; p["lock_px"] = p["entry"] + sd * p["R"] * m["lock_r"]; p["be_r"] = m["be_r"]   # для показа; рабочие уровни считает exit_cfg.levels
    b = {k: copy.deepcopy(v) for k, v in p.items() if k not in ("base", "mgr", "mgr_hist")}
    b["mgr_off"] = True; p["base"] = b
    return True


def cfg_for(p, c):
    """Настройки выхода позиции с менеджером: счёт c (exit_cfg), поверх порог БУ, замок и трейлинг класса. Стоп, цель, tp1 и S/R остаются как в настройках счёта."""
    m = p.get("mgr")
    if not m or p.get("mgr_off"): return c
    e = copy.deepcopy(c)
    e["be"].update(on=1, trig="r", val=float(m["be_r"]), lock_unit="r", lock_val=float(m["lock_r"]))
    e["trail"].update(unit="atr", val=float(m["trail_atr"]))
    return e


def ladder(p, side, t):
    """Лесенка стопа: по достигнутому ходу цены (MFE в R) стоп подтягивается на уровень ступени, только в сторону защиты. Возвращает (old, new, mfe_r, lvl) или None."""
    m = p.get("mgr")
    if not m or p.get("mgr_off") or p.get("stop_manual") or not m.get("lad"): return None
    R = p["R"]; e = p["entry"]
    mfe = ((e - p["lo"]) if side < 0 else (p["hi"] - e)) / R
    tgt = None
    for lvl, s in sorted(m["lad"]):
        if mfe >= lvl: tgt = (lvl, e + side * s * R)
    if tgt is None or (tgt[1] - p["stop"]) * side <= 0: return None
    old = p["stop"]; p["stop"] = tgt[1]; p.setdefault("mgr_hist", []).append({"t": t, "from": old, "to": tgt[1], "mfe_r": round(mfe, 2), "lvl": tgt[0]})
    return old, tgt[1], round(mfe, 2), tgt[0]
