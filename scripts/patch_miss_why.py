# -*- coding: utf-8 -*-
"""Журнал пропущенных пробоев (chan_missed.json), 22.11: в запись добавляется причина пропуска: why (текст причины из события пробоя, например «после подтверждения цена ушла от линии на X ATR (не успеваем)» или «не вернулась на линию») и why_st (статус события skipped/expired). Старые записи дописываются при следующем проходе miss_update по ключу события, если событие ещё есть. Идемпотентный. Использование: python3 patch_miss_why.py chan_orders.py"""
import os, sys
R = [
 ('''    m = load_missed(); have = {x["key"]: x for x in m}; n = 0; ch = False
    for e in load_events():
''', '''    m = load_missed(); have = {x["key"]: x for x in m}; n = 0; ch = False
    evs = load_events(); evk = {e_["key"]: e_ for e_ in evs}
    for x_ in m:      # причина пропуска у записей, сделанных до этого патча
        if "why" not in x_ and x_.get("key") in evk: x_["why"] = evk[x_["key"]].get("reason") or ""; x_["why_st"] = evk[x_["key"]].get("status"); ch = True
    for e in evs:
'''),
 ("feat=feat, **sim)", 'feat=feat, why=rs, why_st=e["status"], **sim)'),
]
MARK = 'why=rs, why_st=e["status"]'
def patch(path):
    s = open(path, encoding="utf-8").read(); n = os.path.basename(path)
    if MARK in s: print("ALREADY", n); return 0
    for old, new in R:
        if s.count(old) != 1: print("ANCHOR_FAIL", n, s.count(old), old[:50]); return 1
    for old, new in R: s = s.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(s); print("APPLIED", n); return 0
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
