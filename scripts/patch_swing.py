# -*- coding: utf-8 -*-
"""Подключает swing_stop к pos.step (перенос стопа за ближайший локальный экстремум после разворотной свечи 1m). Работает только для позиций с флагом p["sw"] (его ставят тени). Идемпотентный. Использование: python3 patch_swing.py pos.py"""
import os, sys
OLD = '    mh = cfg["maxh"] if cfg["maxh"] is not None else p["max_h"]\n'
NEW = '''    try:   # перенос стопа за ближайший локальный экстремум после разворотной свечи (swing_stop, docs/topics/shadow_notes.md), только позиции с флагом sw
        if p.get("sw"):
            import swing_stop; _s = swing_stop.apply(p, side, k)
            if _s: decisions.auto(p, "swing", _s[0], _s[1], t + 60000, c)
    except Exception as e: print("swing err", p.get("sym"), e, flush=True)
''' + OLD
MARK = "import swing_stop; _s = swing_stop.apply"
def patch(path):
    s = open(path, encoding="utf-8").read(); n = os.path.basename(path)
    if MARK in s: print("ALREADY", n); return 0
    if s.count(OLD) != 1: print("ANCHOR_FAIL", n, s.count(OLD)); return 1
    open(path, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1)); print("APPLIED", n); return 0
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
