# -*- coding: utf-8 -*-
"""Единая нумерация теней (21.11): в канале, в подтверждении заметки и в панели «Онлайн» один и тот же номер: A #65, B #65B (один сигнал, разные фильтры). Идемпотентный.
Использование: python3 patch_numbers.py tg_bot.py live_web.py index.html (файлы определяются по имени)."""
import os, sys
P = {
 "tg_bot.py": [('"#%s" % i for i in ids', '"#%s" % t for t in SH.tags(ids)')],
 "live_web.py": [('"var": i.get("var") or "A", "reg": i.get("reg")}', '"var": i.get("var") or "A", "reg": i.get("reg"), "sn": i.get("sn") or ((i.get("ref") or i["id"]) if i.get("var") == "B" else i["id"])}')],
 "index.html": [("p.id+(p.var==='B'?'B':'')", "(p.sn||p.id)+(p.var==='B'?'B':'')")],
}
def patch(path):
    n = os.path.basename(path); s = open(path, encoding="utf-8").read(); rc = 0
    for old, new in P[n]:
        if new in s: print("ALREADY", n); continue
        if s.count(old) != 1: print("ANCHOR_FAIL", n, s.count(old)); rc = 1; continue
        s = s.replace(old, new, 1); open(path, "w", encoding="utf-8").write(s); print("APPLIED", n)
    return rc
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
