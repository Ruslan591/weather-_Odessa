# -*- coding: utf-8 -*-
"""Правило входа по рынку из слежения, часть 2 (docs/topics/shadow_notes.md, заметки 1 и 2). Применяется ПОСЛЕ patch_gate_age.py. Идемпотентный. Использование: python3 patch_gate_tf.py chan_orders.py
1) Свеча контроля входа зависит от таймфрейма сигнала: на ступень ниже (5m -> 1m, 15m -> 5m, 1h -> 15m, 4h -> 1h, 1d -> 4h). Раньше всегда 1m: на старших таймфреймах одна минутная свеча может оказаться шумом.
2) Не подтверждать вход, пока свеча контроля моложе доли age_frac (по умолчанию 1/6) своей длины: 1m -> 10 с, 5m -> 50 с, 15m -> 150 с, 1h -> 10 мин, 4h -> 40 мин. Дальше, как и раньше, ждём, пока свеча пойдёт по ходу сделки (вялая монета без движения не отсекается, ожидание продолжается).
3) Потолок ожидания рыночного входа: не меньше 10 минут и не меньше двух долей свечи контроля плюс 5 минут (_gate_cap_ms).
Настройка POS_DIR/tg_live1m.json: {"age_frac": 0.1667}; 0 выключает правило возраста (применяется сразу, перезапуск не нужен)."""
import os, sys

HELP_OLD = "def _live1m_gate(o, now, cfg=None, price_fn=None, candle_fn=None):"
HELP_NEW = '''_CTRL_TF = {"5m": "1m", "15m": "5m", "1h": "15m", "4h": "1h", "1d": "4h"}     # свеча контроля входа: на ступень ниже таймфрейма сигнала
_CTRL_MS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}


def _ctrl_tf(o): return _CTRL_TF.get(o.get("tf") or "5m", "1m")


def _pair_live_candle_tf(sym, ctf):
    """Текущая (ещё не закрытая) свеча ctf самой пары: (open, last, время открытия мс) или None при ошибке."""
    import urllib.request
    u = "https://data-api.binance.vision/api/v3/klines?symbol=%sUSDT&interval=%s&limit=1" % (sym, ctf)
    for _ in range(2):
        try:
            k = json.load(urllib.request.urlopen(u, timeout=5))[-1]
            return float(k[1]), float(k[4]), int(k[0])
        except Exception: time.sleep(0.3)
    return None


def _gate_cap_ms(o, cfg=None):
    """Потолок ожидания рыночного входа из слежения: не меньше 10 минут и не меньше двух долей свечи контроля плюс 5 минут (4h: 25 минут, 1d: 85)."""
    cfg = cfg or _live1m_cfg(); frac = float(cfg.get("age_frac", 1.0 / 6.0)); return max(600000, int(2 * frac * _CTRL_MS.get(_ctrl_tf(o), 60000)) + 300000)


def _live1m_gate(o, now, cfg=None, price_fn=None, candle_fn=None):'''

EDITS = [
 ("helpers", HELP_OLD, HELP_NEW, "def _pair_live_candle_tf"),
 ("candle", '''    cd = (candle_fn or ((lambda: _btc_live_candle()) if src == "btc" else (lambda: _pair_live_candle(o["sym"]))))()
    nmc = "BTC" if (src == "btc" and not candle_fn) else o["sym"]
    if not cd: log("live1m %s: нет свечи %s 1m, вход без проверки" % (o["sym"], nmc)); return "go", None
    bo, bc = cd; o["live1m_tries"] = int(o.get("live1m_tries") or 0) + 1
''', '''    ctf = "1m" if src == "btc" else _ctrl_tf(o)      # свеча контроля: на ступень ниже таймфрейма сигнала (5m -> 1m, 15m -> 5m, 1h -> 15m, 4h -> 1h, 1d -> 4h)
    cd = (candle_fn or ((lambda: _btc_live_candle()) if src == "btc" else (lambda: _pair_live_candle_tf(o["sym"], ctf))))()
    nmc = "BTC" if (src == "btc" and not candle_fn) else o["sym"]
    if not cd: log("live1m %s: нет свечи %s %s, вход без проверки" % (o["sym"], nmc, ctf)); return "go", None
    bo, bc = cd[0], cd[1]; t_open = cd[2] if len(cd) > 2 else None; o["live1m_tries"] = int(o.get("live1m_tries") or 0) + 1
''', "ctf = \"1m\" if src == \"btc\""),
 ("age", '''    mina = float(cfg.get("min_age_s", 10)); tn = time.time() * 1000.0     # первые секунды минутной свечи: направление ещё не видно (заметка №1, docs/topics/shadow_notes.md); тест с чужими часами берёт now
    age = ((tn if abs(tn - now) < 120000 else float(now)) % 60000) / 1000.0
    if mina > 0 and age < mina:
        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src, "young": 1}
        log("live1m %s %s: свеча %s 1m только началась (%.1f с из %.0f), ждём (попытка %d)" % (o["sym"], o["side"], nmc, age, mina, o["live1m_tries"]))
        _l1m_emit(o, "wait", bo, bc, mv, mx); return "wait", None
''', '''    frac = float(cfg.get("age_frac", 1.0 / 6.0)); cms = _CTRL_MS.get(ctf, 60000); tn = time.time() * 1000.0     # пока свеча контроля моложе доли своей длины, направление не видно (заметки 1-2, docs/topics/shadow_notes.md): 1m -> 10 с, 5m -> 50 с, 15m -> 150 с, 1h -> 10 мин, 4h -> 40 мин
    live_clock = abs(tn - now) < 120000      # тест с чужими часами берёт now
    age = ((tn - t_open) / 1000.0) if (t_open is not None and live_clock) else (((tn if live_clock else float(now)) % cms) / 1000.0)
    need = frac * cms / 1000.0
    if frac > 0 and age < need:
        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src, "ctf": ctf, "young": 1}
        log("live1m %s %s: свеча %s %s только началась (%.1f с из %.0f), ждём (попытка %d)" % (o["sym"], o["side"], nmc, ctf, age, need, o["live1m_tries"]))
        _l1m_emit(o, "wait", bo, bc, mv, mx); return "wait", None
''', "need = frac * cms / 1000.0"),
 ("l_against", '''        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src}
        log("live1m %s %s: свеча %s 1m не по ходу (o %.8g c %.8g), ждём (попытка %d)" % (o["sym"], o["side"], nmc, bo, bc, o["live1m_tries"]))''',
  '''        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src, "ctf": ctf}
        log("live1m %s %s: свеча %s %s не по ходу (o %.8g c %.8g), ждём (попытка %d)" % (o["sym"], o["side"], nmc, ctf, bo, bc, o["live1m_tries"]))''', '"src": src, "ctf": ctf}\n        log("live1m %s %s: свеча %s %s не по ходу'),
 ("l_ok", '''    o["live1m"] = {"ok": 1, "o": bo, "c": bc, "px": px, "t": now, "tries": o["live1m_tries"], "src": src}
    log("live1m %s %s: свеча %s 1m по ходу (o %.8g c %.8g), вход по %.6g (попытка %d)" % (o["sym"], o["side"], nmc, bo, bc, newp, o["live1m_tries"]))''',
  '''    o["live1m"] = {"ok": 1, "o": bo, "c": bc, "px": px, "t": now, "tries": o["live1m_tries"], "src": src, "ctf": ctf}
    log("live1m %s %s: свеча %s %s по ходу (o %.8g c %.8g), вход по %.6g (попытка %d)" % (o["sym"], o["side"], nmc, ctf, bo, bc, newp, o["live1m_tries"]))''', '"tries": o["live1m_tries"], "src": src, "ctf": ctf}'),
 ("cap", '''            if now - at_ > 600000: fills.pop(o_["id"], None); cancel(o_, "рыночный ордер не исполнен за 10 минут", now)''',
  '''            if now - at_ > _gate_cap_ms(o_): fills.pop(o_["id"], None); cancel(o_, "рыночный ордер не исполнен за %d мин: свеча контроля так и не показала ход по сделке" % (_gate_cap_ms(o_) // 60000), now)''', "_gate_cap_ms(o_)"),
]


def patch(path):
    s = open(path, encoding="utf-8").read(); out = s; bad = 0
    if 'cfg.get("min_age_s", 10)' not in out and "def _pair_live_candle_tf" not in out: print("NEED_patch_gate_age_FIRST"); return 1
    for name, old, new, marker in EDITS:
        if marker in out: print("ALREADY", name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
