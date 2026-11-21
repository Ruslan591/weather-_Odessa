# -*- coding: utf-8 -*-
"""Тест tp_ext на синтетике. Запуск: python test_ext.py <каталог с tp_ext.py>. Печатает строку ext ..."""
import sys; sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
import tp_ext as X
def mk(h): return [[i * 900000, 100, hh, 99, 100] for i, hh in enumerate(h)]
CS_LV = mk([101, 101.5, 105, 102, 101, 100, 100]); CS_NEAR = mk([101, 101.5, 102.4, 102, 101, 100, 100]); CS_FREE = mk([101, 101.2, 101.4, 101, 100.5, 100, 100])
def run(cs, side=1, **kw):
    X.OVERRIDE.clear(); X.OVERRIDE.update(kw)
    p = {"status": "open", "sym": "X", "entry": 100.0, "R": 1.0, "stop": 99.0, "tp": 102.0}; k = (10 * 900000, 100.9, 101.95, 100.8, 101.9)
    if side < 0: p = {"status": "open", "sym": "X", "entry": 100.0, "R": 1.0, "stop": 101.0, "tp": 98.0}; k = (10 * 900000, 99.1, 99.2, 98.05, 98.1); cs = [[a, o, 200 - l, 200 - h, c] for a, o, h, l, c in cs]
    r = X.apply(p, side, k, kl15=lambda s: cs)
    return None if r is None else (round(r[1], 2), round(r[3], 2), p.get("ext_n"))
print("ext", run(CS_LV), run(CS_NEAR), run(CS_FREE), run(CS_LV, side=-1), run(CS_LV, trig=0.99), run(CS_LV, max_n=0))
