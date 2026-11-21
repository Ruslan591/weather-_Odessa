# -*- coding: utf-8 -*-
"""Перенос стопа за ближайший локальный экстремум после разворотной свечи 1m (docs/topics/shadow_notes.md, разбор ответов канала: #15, #21, #24, #26).
Идея пользователя: цена сделала волну по ходу сделки, появился локальный экстремум и свеча пошла против сделки: стоп переносится не на экстремум, а на САМЫЙ БЛИЖАЙШИЙ
Hi (для short) или Lo (для long) перед этим экстремумом (вариант: за тело свечей), чуть за ним. Тогда откат, который идёт обратно, закрывает сделку около нуля, а не в полном стопе.

Модуль работает на закрытых свечах 1m, вызывается из pos.step только для позиций с флагом p["sw"] (сейчас ставится только теням, остальные счета не затронуты).
Условия срабатывания (для long; для short зеркально через знак side):
  1. Свеча j (предыдущая) - локальный пик хода по сделке: её hi не ниже hi предыдущих sw_k свечей и выше hi текущей свечи i (экстремум не продолжился).
  2. Свеча i идёт против сделки (закрытие ниже открытия), тело не меньше min_body доли диапазона.
  3. Ход к пику j был не меньше min_mfe R от входа.
  4. Новый стоп: минимум lo среди m свечей перед пиком j (самый ближайший локальный Lo), минус буфер buf_pct. Он должен быть не ближе min_gap_r R к текущему закрытию и строже текущего стопа (только ужесточение).
Параметры: POS_DIR/swing_cfg.json (enabled: включает флаг для новых теней; остальные ключи как в DEFAULT); применяются сразу."""
import json, os

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
CF = os.path.join(D, "swing_cfg.json")
DEFAULT = {"enabled": True, "sw_k": 2, "m": 3, "min_mfe": 0.3, "min_body": 0.0, "min_gap_r": 0.2, "buf_pct": 0.02, "keep": 12}
OVERRIDE = {}      # для бэктеста: подмена параметров без файла
_cache = [None, None]


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


def apply(p, side, k, cfg=None):
    """k: свеча 1m (t, o, h, l, c, ...), закрытая. Возвращает (старый стоп, новый стоп, пояснение) или None. Меняет p["stop"], p["sw_c"], p["sw_hist"]."""
    c = cfg or load()
    t, o, h, l, cl = int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])
    hist = p.setdefault("sw_c", []); hist.append([o, h, l, cl]); del hist[:-int(c.get("keep", 12))]
    if p.get("stop_manual") or p.get("status") != "open": return None
    s = 1 if side > 0 else -1
    # нормализованные цены (для short знак меняется: сделка всегда «long», стоп ниже цены)
    fh = [x[1] if s > 0 else -x[2] for x in hist]      # hi по ходу сделки
    fl = [x[2] if s > 0 else -x[1] for x in hist]      # lo против хода
    fo = [x[0] * s for x in hist]; fc = [x[3] * s for x in hist]
    kk = int(c["sw_k"]); mm = int(c["m"])
    if len(hist) < kk + 2: return None
    i = len(hist) - 1; j = i - 1
    if not (fh[j] >= max(fh[j - kk:j]) and fh[j] > fh[i]): return None          # j - пик, дальше экстремум не продолжился
    if fc[i] >= fo[i]: return None                                                # свеча i не против сделки
    rng = fh[i] - fl[i]
    if rng > 0 and (fo[i] - fc[i]) / rng < float(c["min_body"]): return None
    R = p["R"]; en = p["entry"] * s
    if (fh[j] - en) / R < float(c["min_mfe"]): return None
    lo_ix = max(0, j - mm)
    lvl = min(fl[lo_ix:j]) if j > lo_ix else fl[j]
    lvl -= p["entry"] * float(c["buf_pct"]) / 100.0
    if lvl > fc[i] - float(c["min_gap_r"]) * R: return None                       # слишком близко к цене: выбьет шумом
    old = p["stop"]
    if lvl <= old * s: return None                                                # только ужесточение
    new = lvl * s; p["stop"] = new
    p.setdefault("sw_hist", []).append({"t": t + 60000, "from": old, "to": new})
    return old, new, "swing"
