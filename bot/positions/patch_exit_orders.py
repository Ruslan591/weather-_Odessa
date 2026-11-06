# -*- coding: utf-8 -*-
"""Патч 10б (2026-11-06): chan_orders.py берёт стоп при исполнении заявки из настроек выхода счёта (exit_cfg.stop_at_fill): по заявке (по умолчанию) или фикс. расстояние pct/atr. Идемпотентный. Запуск: patch_exit_orders.py <каталог>"""
import sys, os
f = os.path.join(sys.argv[1], "chan_orders.py"); s = open(f, encoding="utf-8").read()
if "stop_at_fill" in s: print("already patched"); sys.exit(0)
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:80]); return s.replace(old, new)
s = rep(s, '            side = 1 if o["side"] == "long" else -1; R = abs(fp - o["stop"])\n            if R <= 0 or (side > 0 and o["stop"] >= fp) or (side < 0 and o["stop"] <= fp): cancel(o, "стоп по ту сторону входа", ft); continue\n            a1 = at1.get(oid, o["atr"] * 3.46)\n',
 '            side = 1 if o["side"] == "long" else -1; a1 = at1.get(oid, o["atr"] * 3.46)\n            try:\n                import exit_cfg; stp = exit_cfg.stop_at_fill(exit_cfg.load(), side, fp, a1, o["stop"])   # патч 10б: стоп по настройкам счёта\n            except Exception: stp = o["stop"]\n            R = abs(fp - stp)\n            if R <= 0 or (side > 0 and stp >= fp) or (side < 0 and stp <= fp): cancel(o, "стоп по ту сторону входа", ft); continue\n')
s = rep(s, '"t_in": ft, "entry": fp, "px_signal": o["price"], "stop0": o["stop"], "stop": o["stop"], "tp": o["tp"],', '"t_in": ft, "entry": fp, "px_signal": o["price"], "stop0": stp, "stop": stp, "tp": o["tp"],')
open(f, "w", encoding="utf-8").write(s); print("patched chan_orders.py")
