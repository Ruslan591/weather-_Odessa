# -*- coding: utf-8 -*-
"""Правило входа по рынку из слежения, часть 3 (docs/topics/shadow_notes.md, заметка №6: LTC 1h #42). Применяется ПОСЛЕ patch_gate_age.py и patch_gate_tf.py. Идемпотентный.
Использование: python3 patch_gate_multi.py chan_orders.py
1) Параллельная проверка ВСЕХ младших таймфреймов, а не одной свечи на ступень ниже: 5m -> 1m; 15m -> 5m и 1m; 1h -> 15m, 5m, 1m; 4h -> 1h, 15m, 5m, 1m; 1d -> 4h, 1h, 15m, 5m, 1m. Вход только если все свечи идут по ходу сделки.
2) Доля 1/6 (age_frac) считается как ВРЕМЯ, которое цена непрерывно держится по ходу сделки относительно открытия этой свечи (по закрытиям 1s свечей пары; для свечей от 1h по 1m), а не как возраст свечи. Свеча 15m, которая была против сделки и только что перешла на нужную сторону, ждёт ещё 150 с по ходу. Нет данных 1s -> запасной вариант: возраст свечи и текущее направление (как раньше).
Настройка POS_DIR/tg_live1m.json: {"chain": false} - только одна свеча на ступень ниже (как раньше); {"dir_time": false} - не время по ходу, а возраст свечи; {"age_frac": 0} - только направление."""
import os, sys

HELP_OLD = "def _live1m_gate(o, now, cfg=None, price_fn=None, candle_fn=None):"
HELP_NEW = '''_CHAIN = {"5m": ["1m"], "15m": ["5m", "1m"], "1h": ["15m", "5m", "1m"], "4h": ["1h", "15m", "5m", "1m"], "1d": ["4h", "1h", "15m", "5m", "1m"]}     # все младшие таймфреймы сигнала, от старшего к младшему


def _gate_chain(o, cfg=None):
    cfg = cfg or _live1m_cfg()
    return list(_CHAIN.get(o.get("tf") or "5m", ["1m"])) if cfg.get("chain", True) else [_ctrl_tf(o)]


def _dir_run_s(sym, ctf, t_open, bo, s, tn):
    """Сколько секунд подряд (до сейчас) цена пары держится по ходу сделки относительно открытия свечи ctf: по закрытиям 1s свечей (для ctf от 1h по 1m). Нет данных -> None."""
    import urllib.request
    ms = _CTRL_MS.get(ctf, 60000); iv, step = ("1s", 1000) if ms <= 900000 else ("1m", 60000)
    t0 = max(int(t_open), int(tn) - 999 * step)
    u = "https://data-api.binance.vision/api/v3/klines?symbol=%sUSDT&interval=%s&startTime=%d&limit=1000" % (sym, iv, t0)
    ks = None
    for _ in range(2):
        try: ks = json.load(urllib.request.urlopen(u, timeout=6)); break
        except Exception: time.sleep(0.3)
    if not ks: return None
    last_bad = None
    for k in ks:
        if (float(k[4]) - bo) * s <= 0: last_bad = int(k[0]) + step
    return max(0.0, (tn - (last_bad if last_bad is not None else t0)) / 1000.0)


def _live1m_gate(o, now, cfg=None, price_fn=None, candle_fn=None, run_fn=None):'''

REG_START = '    ctf = "1m" if src == "btc" else _ctrl_tf(o)'
REG_END = '    newp = px * (1 + s * 0.0003); delta = newp - float(o["price"])'
REG_NEW = '''    chain = ["1m"] if src == "btc" else _gate_chain(o, cfg)      # параллельно все младшие таймфреймы сигнала (1h -> 15m, 5m, 1m), все должны идти по ходу сделки
    mv = None if (lp is None or atr <= 0) else round((px - float(lp)) * s / atr, 2)
    frac = float(cfg.get("age_frac", 1.0 / 6.0)); tn = time.time() * 1000.0; live_clock = abs(tn - now) < 120000      # тест с чужими часами берёт now
    info = []; bad = None; got = 0; bo = bc = None; ctf = chain[0]; nmc = "BTC" if (src == "btc" and not candle_fn) else o["sym"]
    for ctf_i in chain:
        cd = (candle_fn or ((lambda: _btc_live_candle()) if src == "btc" else (lambda: _pair_live_candle_tf(o["sym"], ctf_i))))()
        if not cd: log("live1m %s: нет свечи %s %s, эта проверка пропущена" % (o["sym"], nmc, ctf_i)); continue
        bo_i, bc_i = cd[0], cd[1]; t_open = cd[2] if len(cd) > 2 else None
        if not got: bo, bc, ctf = bo_i, bc_i, ctf_i
        got += 1; cms = _CTRL_MS.get(ctf_i, 60000); need = frac * cms / 1000.0 if frac > 0 else 0.0
        age = ((tn - t_open) / 1000.0) if (t_open is not None and live_clock) else (((tn if live_clock else float(now)) % cms) / 1000.0)
        side_ok = (bc_i - bo_i) * s > 0; run = 0.0
        if side_ok:
            run = age; r = None
            if run_fn: r = run_fn(ctf_i, bo_i, s, t_open)
            elif cfg.get("dir_time", True) and live_clock and not candle_fn and t_open is not None and need > 0: r = _dir_run_s(o["sym"], ctf_i, t_open, bo_i, s, tn)
            if r is not None: run = min(run, float(r))
        rec = {"tf": ctf_i, "o": bo_i, "c": bc_i, "run": round(run, 1), "need": round(need, 1), "side": 1 if side_ok else 0, "ok": 1 if (side_ok and run >= need) else 0}
        info.append(rec)
        if not rec["ok"]: bad = rec; bo, bc, ctf = bo_i, bc_i, ctf_i; break
    if not got: log("live1m %s: нет свечей контроля, вход без проверки" % o["sym"]); return "go", None
    o["live1m_tries"] = int(o.get("live1m_tries") or 0) + 1
    if bad:
        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src, "ctf": ctf, "chain": info, "young": 1 if bad["side"] else 0}
        log("live1m %s %s: свеча %s %s %s (o %.8g c %.8g, по ходу %.0f с из %.0f), ждём (попытка %d)" % (o["sym"], o["side"], nmc, ctf, "ещё не продержалась по ходу" if bad["side"] else "не по ходу", bo, bc, bad["run"], bad["need"], o["live1m_tries"]))
        _l1m_emit(o, "wait", bo, bc, mv, mx); return "wait", None
'''
OK_OLD = '''"tries": o["live1m_tries"], "src": src, "ctf": ctf}'''
OK_NEW = '''"tries": o["live1m_tries"], "src": src, "ctf": ctf, "chain": info}'''
MARK = "def _dir_run_s"


def patch(path):
    s = open(path, encoding="utf-8").read(); name = os.path.basename(path)
    if MARK in s: print("ALREADY", name); return 0
    if "def _pair_live_candle_tf" not in s or 'frac = float(cfg.get("age_frac"' not in s: print("NEED_patch_gate_tf_FIRST", name); return 1
    if s.count(HELP_OLD) != 1 or s.count(REG_START) != 1 or s.count(REG_END) != 1 or s.count(OK_OLD) != 1: print("ANCHOR_FAIL", name, s.count(HELP_OLD), s.count(REG_START), s.count(REG_END), s.count(OK_OLD)); return 1
    a, b = s.index(REG_START), s.index(REG_END)
    if a >= b: print("ORDER_FAIL", name); return 1
    out = s[:a] + REG_NEW + s[b:]
    out = out.replace(HELP_OLD, HELP_NEW, 1).replace(OK_OLD, OK_NEW, 1)
    open(path, "w", encoding="utf-8").write(out); print("APPLIED", name); return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
