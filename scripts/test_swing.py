# -*- coding: utf-8 -*-
"""Тест swing_stop на синтетическом ходе (short, зеркально long). Запуск: python test_swing.py <каталог с swing_stop.py>. Печатает строку swing ..."""
import sys; sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
import swing_stop as W
C = [(100, 100.05, 99.7, 99.75), (99.75, 99.9, 99.5, 99.55), (99.55, 99.8, 99.3, 99.35), (99.35, 99.5, 99.0, 99.2), (99.2, 99.45, 99.15, 99.4)]
def run(side, cfg):
    W.OVERRIDE.clear(); W.OVERRIDE.update(cfg)
    en = 100.0; p = {"status": "open", "entry": en, "R": 0.5, "stop": en - side * 0.5 * 1.0}
    out = None
    for n, (o, h, l, c) in enumerate(C):
        if side > 0: o, h, l, c = 200 - o, 200 - l, 200 - h, 200 - c
        r = W.apply(p, side, (n * 60000, o, h, l, c))
        if r: out = round(r[1], 2)
    return out
print("swing", run(-1, {"m": 1}), run(1, {"m": 1}), run(-1, {}), run(-1, {"min_mfe": 5.0}), run(-1, {"min_gap_r": 2.0}))
