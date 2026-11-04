# -*- coding: utf-8 -*-
"""Патч 6: автоперенос стопа на линию поддержки/сопротивления после БУ (sr_stop.py). Идемпотентный патч pos.py на VPS. Использование: patch_sr_stop.py <каталог positions>"""
import sys, os
D = sys.argv[1]; f = os.path.join(D, "pos.py"); s = open(f, encoding="utf-8").read()
if "sr_stop.apply" in s: print("already patched"); sys.exit(0)
old = "    if changed: save(ps)\n    return ps\n\ndef price(sym)"
new = ('    for p in ps:   # патч 6: после БУ стоп подтягивается на подтверждённую линию поддержки/сопротивления (sr_stop.py)\n'
       '        if p["status"] == "open" and p.get("armed"):\n'
       '            try:\n'
       '                import sr_stop\n'
       '                if sr_stop.apply(p, kl, now, lambda m: print(m, flush=True)): changed = True\n'
       '            except Exception as e: print("sr_stop err", p.get("sym"), e, flush=True)\n'
       '    if changed: save(ps)\n    return ps\n\ndef price(sym)')
assert s.count(old) == 1, "anchor not found"
open(f, "w", encoding="utf-8").write(s.replace(old, new)); print("patched pos.py")
