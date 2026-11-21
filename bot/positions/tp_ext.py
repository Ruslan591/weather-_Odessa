# -*- coding: utf-8 -*-
"""Цель дальше при запасе хода (docs/topics/shadow_notes.md, заметки #38 и №9). Вызывается из pos.step для позиций с флагом p["ext"] (его ставят только тени).
Идея пользователя (#38 ENA): учитывая потенциал сделки, постепенно переносить цель дальше, параллельно смещая стоп.
Потенциал = свободный ход за целью до ближайшего непробитого swing-экстремума 15m (фрактал K=2, 72 часа назад; для long ближайший swing high выше цели, для short swing low ниже). Нет такого уровня: за целью свободно.
Условия (после закрытия свечи 1m, для long; для short зеркально):
  1. Цена прошла долю trig пути от входа до текущей цели (по hi свечи).
  2. Запас до ближайшего уровня за целью не меньше pot_min R (нет уровня: хватает).
  3. Цель сдвигается на min(step R, запас), стоп переносится на долю lock пути от входа к старой цели (только ужесточение, цена должна быть выше этого стопа). Не более max_n раз на сделку.
Параметры POS_DIR/tp_ext_cfg.json (enabled включает флаг для новых теней), применяются сразу. Подобраны на 500 закрытых сделках: trig 0.95, pot_min 1.0, step 0.5, lock 0.4 (+6.8 R к правилам без неё; шаг цели 2 R вреден)."""
import json, os, time

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
CF = os.path.join(D, "tp_ext_cfg.json")
DEFAULT = {"enabled": True, "trig": 0.95, "pot_min": 1.0, "step": 0.5, "lock": 0.4, "max_n": 3}
OVERRIDE = {}      # для бэктеста
_cache = [None, None]; _k15 = {}


def load():
    if OVERRIDE: c = dict(DEFAULT); c.update(OVERRIDE); return c
    try: m = os.stat(CF).st_mtime
    except OSError: m = None
    if _cache[0] == m and _cache[1] is not None: return _cache[1]
    c = dict(DEFAULT)
    if m is not None:
        try: c.update(json.load(open(CF, encoding="utf-8")))
        except Exception: pass
    _cache[0] = m; _cache[1] = c
    return c


def _kl15(sym):
    now = time.time(); c = _k15.get(sym)
    if c and now - c[0] < 60: return c[1]
    import pos
    d = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in pos.kl(sym, "15m", 300)]
    _k15[sym] = (now, d); return d


def next_level(cs, side, tp, now):
    """Ближайший непробитый swing-экстремум 15m (фрактал K=2) за целью tp; None, если за целью свободно."""
    d = [x for x in cs if x[0] + 900000 <= now][-288:]; n = len(d); best = None
    for j in range(2, n - 2):
        if side > 0:
            v = d[j][2]
            if v <= tp or v < max(d[j - 2][2], d[j - 1][2], d[j + 1][2], d[j + 2][2]): continue
            if max(x[2] for x in d[j + 1:]) > v: continue
        else:
            v = d[j][3]
            if v >= tp or v > min(d[j - 2][3], d[j - 1][3], d[j + 1][3], d[j + 2][3]): continue
            if min(x[3] for x in d[j + 1:]) < v: continue
        if best is None or (v < best if side > 0 else v > best): best = v
    return best


def apply(p, side, k, cfg=None, kl15=None):
    """k: закрытая свеча 1m (t, o, h, l, c, ...). Возвращает (старая цель, новая цель, старый стоп, новый стоп) или None. Меняет p["tp"], p["tp_manual"], p["stop"], p["ext_n"]."""
    c = cfg or load(); n = int(p.get("ext_n") or 0)
    if p.get("status") != "open" or p.get("stop_manual") or n >= int(c["max_n"]): return None
    s = 1 if side > 0 else -1; en = p["entry"]; R = p["R"]; tp = p.get("tp_manual") or p["tp"]; dist = (tp - en) * s
    if dist <= 0 or not R: return None
    best = float(k[2]) if s > 0 else float(k[3])
    if (best - en) * s / dist < float(c["trig"]): return None
    cs = (kl15 or _kl15)(p["sym"]); lv = next_level(cs, s, tp, int(k[0]) + 60000)
    room = 99.0 if lv is None else (lv - tp) * s / R
    if room < float(c["pot_min"]): return None
    newtp = tp + s * min(float(c["step"]), room) * R
    lock = en + s * float(c["lock"]) * dist
    if (float(k[4]) - lock) * s <= 0: return None
    old = p["stop"]; p["tp_manual"] = newtp; p["tp"] = newtp
    p["stop"] = max(old, lock) if s > 0 else min(old, lock); p["ext_n"] = n + 1
    p.setdefault("ext_hist", []).append({"t": int(k[0]) + 60000, "tp_from": tp, "tp_to": newtp, "stop_from": old, "stop_to": p["stop"]})
    return tp, newtp, old, p["stop"]
