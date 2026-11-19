# -*- coding: utf-8 -*-
"""Правило входа по рынку из слежения: не подтверждать вход в первые секунды минутной свечи пары (docs/topics/shadow_notes.md, заметка №1: INJUSDT 19.11 15:16).
В _live1m_gate (chan_orders.py): если с открытия текущей свечи 1m пары прошло меньше min_age_s секунд (по умолчанию 10), ждём: направление свечи ещё не видно (один тик даёт «по ходу»), а затем она может пойти против сделки.
Настройка в POS_DIR/tg_live1m.json: {"min_age_s": 10}; 0 выключает правило (применяется сразу, перезапуск не нужен). Идемпотентный. Использование: python3 patch_gate_age.py chan_orders.py"""
import os, sys

OLD = '''    mv = None if (lp is None or atr <= 0) else round((px - float(lp)) * s / atr, 2)
    if (bc - bo) * s <= 0:'''
NEW = '''    mv = None if (lp is None or atr <= 0) else round((px - float(lp)) * s / atr, 2)
    mina = float(cfg.get("min_age_s", 10)); tn = time.time() * 1000.0     # первые секунды минутной свечи: направление ещё не видно (заметка №1, docs/topics/shadow_notes.md); тест с чужими часами берёт now
    age = ((tn if abs(tn - now) < 120000 else float(now)) % 60000) / 1000.0
    if mina > 0 and age < mina:
        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src, "young": 1}
        log("live1m %s %s: свеча %s 1m только началась (%.1f с из %.0f), ждём (попытка %d)" % (o["sym"], o["side"], nmc, age, mina, o["live1m_tries"]))
        _l1m_emit(o, "wait", bo, bc, mv, mx); return "wait", None
    if (bc - bo) * s <= 0:'''
MARK = 'cfg.get("min_age_s", 10)'


def patch(path):
    s = open(path, encoding="utf-8").read()
    if MARK in s: print("ALREADY", os.path.basename(path)); return 0
    if s.count(OLD) != 1: print("ANCHOR_FAIL", os.path.basename(path), s.count(OLD)); return 1
    open(path, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1)); print("APPLIED", os.path.basename(path)); return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
