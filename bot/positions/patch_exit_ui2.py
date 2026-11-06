# -*- coding: utf-8 -*-
"""Патч 10г (2026-11-06): в карточке позиции вкладки Claude убраны таблица расстояний (clDist) и тексты под графиком (подсказка по жестам и описание канала); остаётся «Тезис».
Подсказка жестов остаётся у графиков заявок. Идемпотентный. Запуск: patch_exit_ui2.py <каталог classic>"""
import sys, os
f = os.path.join(sys.argv[1], "classic_pos_html.py"); h = open(f, encoding="utf-8").read()
if "nohint:1" in h: print("already patched"); sys.exit(0)
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:90]); return s.replace(old, new)
# 1. таблица расстояний у позиции
h = rep(h, "+clStopBox(p)+clDist(p)+", "+clStopBox(p)+")
# 2. подсказка жестов в clZBox: не показываем, если sp.nohint
k = h.index("Тяните график вбок"); st = h.rfind("+'<div class=sm", 0, k); assert st > 0
end_marker = "листается).</div></div>'}"; assert h.count(end_marker) == 1
h = h[:st] + "+(sp.nohint?'':" + h[st + 1:]
h = rep(h, end_marker, "листается).</div>')+'</div>'}")
# 3. текст про канал под графиком позиции (clZChart)
k = h.index("Канал и точки - как они были в момент выставления лимита"); st = h.rfind("+'<div class=sm", 0, k); en = h.index("</div>", k) + 6
assert h[en] == "'" and st > 0 and en - st < 700, (st, en)
h = h[:st] + h[en + 1:]
# 4. флаг nohint для графиков позиций Claude
h = rep(h, "F=26,sp={cand:C,", "F=26,sp={nohint:1,cand:C,")
h = rep(h, "F=8,te=tL+F*dt,sp={cand:C,dt:dt,F:F,n0:96,", "F=8,te=tL+F*dt,sp={nohint:1,cand:C,dt:dt,F:F,n0:96,")
assert h.count("nohint:1") == 2, h.count("nohint:1")
open(f, "w", encoding="utf-8").write(h); print("patched")
