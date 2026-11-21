# -*- coding: utf-8 -*-
"""Тест правила входа (patch_gate_multi.py): запускается из каталога с chan_orders.py, env POS_DIR/CHAN_SRC/CHAN_EDGE/TG_GATE как у сервиса. Печатает строку gate ... и строки проверок."""
import time, sys, os
sys.path.insert(0, os.getcwd())
import chan_orders as C
C._l1m_emit = lambda *a, **k: None; C.log = lambda m: None
far = int(time.time() * 1000) - 5 * 3600000
def g(tf, sec, cd=(7.29, 7.28), rf=None, side='short'):
    o = {'sym': 'X', 'side': side, 'atr': 0.05, 'line_px': 7.30, 'price': 7.29, 'stop': 7.35, 'tp': 7.10, 'tf': tf}
    ms = C._CTRL_MS[C._CTRL_TF[tf]]; base = far - far % ms
    return C._live1m_gate(o, base + int(sec * 1000), cfg={'enabled': True, 'max_dist_atr': 0.9}, price_fn=lambda s: 7.28, candle_fn=lambda: cd, run_fn=rf)[0]
print('gate', g('5m', 9), g('5m', 11), g('15m', 49), g('15m', 51), g('1h', 149), g('1h', 151), g('4h', 599), g('4h', 670))
print('run', g('5m', 30, rf=lambda *a: 5.0), g('5m', 30, rf=lambda *a: 15.0), g('1h', 3070, cd=(7.28, 7.29)), g('1h', 3070, rf=lambda tf, *a: 100.0 if tf == '15m' else 999.0), g('1h', 3070, rf=lambda tf, *a: 20.0 if tf == '5m' else 999.0), g('1h', 3070, rf=lambda tf, *a: 4.0 if tf == '1m' else 999.0), g('1h', 3070, rf=lambda *a: 999.0))
try:
    now = int(time.time() * 1000); k = C._pair_live_candle_tf('BTC', '15m')
    print('live1s', k is not None and round(C._dir_run_s('BTC', '15m', k[2], k[0], 1, now) or -1, 1), k is not None and round(C._dir_run_s('BTC', '1h', k[2] - 3070000, k[0], 1, now) or -1, 1))
except Exception as e: print('live1s ERR', repr(e))
