# -*- coding: utf-8 -*-
"""Настройки выхода счёта «Claude» (панель 18091, вкладка Claude, отдельно для каждой вкладки-счёта): стоп, безубыток (БУ), трейлинг, цели, доля закрытия, перенос стопа на S/R.
Файл настроек лежит в каталоге счёта (POS_DIR/exit_cfg.json), поэтому у Классики / AFD / Регрессии / AFD+регрессии свои настройки. Действуют на ВСЕ позиции счёта (открытые и новые).
Значения по умолчанию = прежнее поведение бота: БУ после +1R с замком 0.2%, трейлинг 1.5 ATR(1h) после БУ, цель и стоп из заявки, без частичного закрытия, перенос на S/R включён, время жизни из позиции.
Единицы расстояния: r (доли R = расстояние входа до начального стопа), pct (% от цены входа), atr (ATR 1h позиции, p['atr1h']).
Реальных ордеров нет (бумага)."""
import json, os
D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
CF = os.path.join(D, "exit_cfg.json")
DEFAULT = {
    "stop":  {"mode": "rule", "val": 0.6},                                              # rule = как в заявке; pct | atr = фиксированное расстояние от входа (при исполнении заявки)
    "be":    {"on": 1, "trig": "r", "val": 1.0, "lock_unit": "pct", "lock_val": 0.2},     # trig: r | pct | atr | tp (% пути к цели) | tp1 (после частичной цели); lock_unit: pct | r
    "trail": {"on": 1, "start": "be", "start_val": 1.0, "unit": "atr", "val": 1.5},      # start: be | r | pct | atr | tp1 | now; unit: atr | pct
    "tp1":   {"on": 0, "unit": "r", "val": 1.0, "part": 50},                              # частичная цель: unit r | pct | atr, part = % позиции
    "tp":    {"mode": "rule", "val": 2.0},                                                # конечная цель на остаток: rule | r | pct | atr | none
    "sr":    {"on": 1},                                                                   # автоперенос стопа на линию S/R после БУ
    "maxh":  None,                                                                        # время жизни, ч: None = как у позиции, 0 = без лимита
}
CHOICES = {("stop", "mode"): ("rule", "pct", "atr"), ("be", "trig"): ("r", "pct", "atr", "tp", "tp1"), ("be", "lock_unit"): ("pct", "r"),
           ("trail", "start"): ("be", "r", "pct", "atr", "tp1", "now"), ("trail", "unit"): ("atr", "pct"),
           ("tp1", "unit"): ("r", "pct", "atr"), ("tp", "mode"): ("rule", "r", "pct", "atr", "none")}
RANGES = {("stop", "val"): (0.05, 50), ("be", "val"): (0.05, 100), ("be", "lock_val"): (-5, 20), ("trail", "start_val"): (0.05, 100), ("trail", "val"): (0.05, 20),
          ("tp1", "val"): (0.05, 100), ("tp1", "part"): (1, 99), ("tp", "val"): (0.05, 100)}
_cache = [None, None]   # (mtime, cfg)

def _merge(src):
    c = json.loads(json.dumps(DEFAULT))
    if isinstance(src, dict):
        for k, v in src.items():
            if k == "maxh": c["maxh"] = v
            elif k in c and isinstance(v, dict): c[k].update({a: b for a, b in v.items() if a in c[k]})
    return c

def load():
    try: m = os.stat(CF).st_mtime
    except OSError: m = None
    if _cache[0] == m and _cache[1] is not None: return _cache[1]
    c = DEFAULT_COPY()
    if m is not None:
        try: c = _merge(json.load(open(CF)))
        except Exception: c = DEFAULT_COPY()
    _cache[0] = m; _cache[1] = c
    return c

def DEFAULT_COPY(): return json.loads(json.dumps(DEFAULT))

def validate(src):
    """Возвращает (cfg, ошибка). Числа приводятся, выбор проверяется по списку, диапазоны ограничены."""
    if not isinstance(src, dict): return None, "настройки должны быть объектом"
    c = _merge(src)
    for (sec, key), ch in CHOICES.items():
        if c[sec][key] not in ch: return None, "%s.%s: допустимо %s" % (sec, key, ", ".join(ch))
    for (sec, key), (lo, hi) in RANGES.items():
        try: c[sec][key] = float(str(c[sec][key]).replace(",", "."))
        except Exception: return None, "%s.%s: нужно число" % (sec, key)
        if not (lo <= c[sec][key] <= hi): return None, "%s.%s: от %g до %g" % (sec, key, lo, hi)
    for sec in ("be", "trail", "tp1", "sr"): c[sec]["on"] = 1 if c[sec].get("on") in (1, True, "1", "true", "on") else 0
    mh = c.get("maxh")
    if mh in (None, ""): c["maxh"] = None
    else:
        try: c["maxh"] = float(str(mh).replace(",", "."))
        except Exception: return None, "maxh: нужно число часов (0 = без лимита)"
        if not (0 <= c["maxh"] <= 720): return None, "maxh: от 0 до 720 часов"
    if c["be"]["trig"] == "tp1" and not c["tp1"]["on"]: return None, "БУ «после частичной цели» требует включённой частичной цели"
    if c["trail"]["start"] == "tp1" and not c["tp1"]["on"]: return None, "трейлинг «после частичной цели» требует включённой частичной цели"
    if c["be"]["trig"] == "tp" and c["tp"]["mode"] == "none": return None, "БУ по доле пути к цели требует конечной цели"
    return c, None

def save(c):
    os.makedirs(D, exist_ok=True); tmp = CF + ".tmp"; json.dump(c, open(tmp, "w"), ensure_ascii=False, indent=1); os.replace(tmp, CF); _cache[0] = None

def dist(p, unit, v):
    """Расстояние в цене. r: v*R; pct: v% от входа; atr: v*ATR1h."""
    if unit == "r": return v * p["R"]
    if unit == "pct": return p["entry"] * v / 100.0
    return v * (p.get("atr1h") or 0.0)

def levels(p, c=None):
    """Эффективные уровни позиции по текущим настройкам: tp (конечная или None), tp1 (или None), be_px (или None), lock_px, trail_px (порог старта трейлинга или None), trail_dist."""
    c = c or load(); side = 1 if p["side"] == "long" else -1; e = p["entry"]; out = {}
    t = c["tp"]
    if t["mode"] == "rule": tp = p.get("tp")
    elif t["mode"] == "none": tp = None
    else: tp = e + side * dist(p, t["mode"], t["val"])
    if p.get("tp_manual"): tp = p["tp_manual"]   # ручная цель (патч 11) главнее настроек
    t1 = c["tp1"]; tp1 = e + side * dist(p, t1["unit"], t1["val"]) if t1["on"] else None
    if tp1 is not None and tp is not None and (tp1 - tp) * side >= 0: tp1 = None   # частичная цель должна быть ближе конечной
    b = c["be"]; be_px = None
    if b["on"]:
        if b["trig"] in ("r", "pct", "atr"): be_px = e + side * dist(p, b["trig"], b["val"])
        elif b["trig"] == "tp" and tp is not None: be_px = e + side * (tp - e) * b["val"] / 100.0
    lock_px = e + side * dist(p, b["lock_unit"], b["lock_val"])
    tr = c["trail"]; trail_px = None
    if tr["on"] and tr["start"] in ("r", "pct", "atr"): trail_px = e + side * dist(p, tr["start"], tr["start_val"])
    if p.get("manual_trail"): td = p["trail_dist"]
    elif tr["unit"] == "atr": td = tr["val"] * (p.get("atr1h") or 0.0)
    else: td = e * tr["val"] / 100.0
    out.update(tp=tp, tp1=tp1, be_px=be_px, lock_px=lock_px, trail_px=trail_px, trail_dist=td)
    return out

def stop_at_fill(c, side, fp, atr1h, rule_stop):
    """Стоп при исполнении заявки: по заявке или фиксированное расстояние (pct | atr ATR1h) от цены входа."""
    s = c["stop"]
    if s["mode"] == "rule": return rule_stop
    d = fp * s["val"] / 100.0 if s["mode"] == "pct" else s["val"] * atr1h
    return fp - side * d
