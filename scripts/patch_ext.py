# -*- coding: utf-8 -*-
"""Подключает tp_ext к pos.step (цель дальше при запасе хода). Работает только для позиций с флагом p["ext"] (его ставят тени). Идемпотентный. Использование: python3 patch_ext.py pos.py"""
import os, sys
OLD = '    mh = cfg["maxh"] if cfg["maxh"] is not None else p["max_h"]\n'
NEW = '''    try:   # цель дальше при запасе хода (tp_ext, docs/topics/shadow_notes.md, #38), только позиции с флагом ext
        if p.get("ext"):
            import tp_ext; _x = tp_ext.apply(p, side, k)
            if _x: decisions.auto(p, "tp_ext", _x[0], _x[1], t + 60000, c, stop_from=_x[2], stop_to=_x[3], n=p.get("ext_n"))
    except Exception as e: print("tp_ext err", p.get("sym"), e, flush=True)
''' + OLD
MARK = "import tp_ext; _x = tp_ext.apply"
def patch(path):
    s = open(path, encoding="utf-8").read(); n = os.path.basename(path)
    if MARK in s: print("ALREADY", n); return 0
    if s.count(OLD) != 1: print("ANCHOR_FAIL", n, s.count(OLD)); return 1
    open(path, "w", encoding="utf-8").write(s.replace(OLD, NEW, 1)); print("APPLIED", n); return 0
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
