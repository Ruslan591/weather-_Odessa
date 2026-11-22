# -*- coding: utf-8 -*-
"""Правило входа, часть 4 (docs/topics/shadow_notes.md, заметка №6 и ответ пользователя 21.11): свеча САМОГО сигнального таймфрейма (для 15m, 1h, 4h, 1d; 5m не трогаем) тоже должна идти по ходу сделки, по тому же правилу времени (1/6 жизни свечи по ходу: 15m 150 с, 1h 10 мин, 4h 40 мин, 1d 4 ч). Ставится первой в цепочке проверки, затем младшие. Потолок ожидания теперь считается по самой длинной свече цепочки. Применяется ПОСЛЕ patch_gate_multi.py. Идемпотентный.
Использование: python3 patch_gate_sig.py chan_orders.py. Настройка tg_live1m.json: {"sig_tf": false} выключает условие."""
import os, sys
R = [
 ('"1h": 3600000, "4h": 14400000}', '"1h": 3600000, "4h": 14400000, "1d": 86400000}'),
 ('''    return list(_CHAIN.get(o.get("tf") or "5m", ["1m"])) if cfg.get("chain", True) else [_ctrl_tf(o)]
''', '''    tf = o.get("tf") or "5m"
    if not cfg.get("chain", True): return [_ctrl_tf(o)]
    ch = list(_CHAIN.get(tf, ["1m"]))
    if cfg.get("sig_tf", True) and tf in ("15m", "1h", "4h", "1d"): ch = [tf] + ch      # свеча сигнального таймфрейма тоже по ходу сделки (5m не трогаем)
    return ch
'''),
 ('frac * _CTRL_MS.get(_ctrl_tf(o), 60000)) + 300000)', 'frac * max(_CTRL_MS.get(c_, 60000) for c_ in _gate_chain(o, cfg))) + 300000)'),
]
MARK = 'cfg.get("sig_tf", True)'
def patch(path):
    s = open(path, encoding="utf-8").read(); n = os.path.basename(path)
    if MARK in s: print("ALREADY", n); return 0
    if "def _gate_chain" not in s: print("NEED_patch_gate_multi_FIRST", n); return 1
    for old, new in R:
        if s.count(old) != 1: print("ANCHOR_FAIL", n, s.count(old), old[:50]); return 1
    for old, new in R: s = s.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(s); print("APPLIED", n); return 0
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
