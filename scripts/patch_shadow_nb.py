# patch_shadow_nb: пометка «вне баланса» в списке теней (5m / flat по shadow_bal.json). Идемпотентно. Аргументы: live_web.py index.html
import sys, py_compile
lw, ix = sys.argv[1], sys.argv[2]
s = open(lw, encoding="utf-8").read(); h = open(ix, encoding="utf-8").read()
if '["nb"] = 1' in s and "p.nb" in h: print("ALREADY"); sys.exit(0)
a1 = 'd = jl("shadow.json"); its = d.get("items") if isinstance(d, dict) else None; out = []\n'
n1 = a1 + '    _bc = jl("shadow_bal.json"); _bc = _bc if isinstance(_bc, dict) else {}; _stf = set(_bc.get("skip_tf", ["5m"])); _srg = set(_bc.get("skip_regime", ["flat"]))\n'
a2 = '        out.append(r)\n    out.sort(key=lambda x: (x["status"] in ("gate", "open")'
n2 = '        if (i.get("tf") in _stf) or ((i.get("rg") or {}).get("regime") in _srg): r["nb"] = 1   # не идёт в баланс (фильтр)\n' + a2
b1 = "h('b',null,p.sym.replace('USDT',''))"
nb1 = b1 + ",...(p.nb?[h('span','small a','\u00a0вне баланса')]:[])"
if s.count(a1) != 1 or s.count(a2) != 1 or h.count(b1) != 1: print("ANCHOR_FAIL", s.count(a1), s.count(a2), h.count(b1)); sys.exit(1)
s = s.replace(a1, n1).replace(a2, n2); h = h.replace(b1, nb1)
open(lw, "w", encoding="utf-8").write(s); open(ix, "w", encoding="utf-8").write(h)
py_compile.compile(lw, doraise=True); print("PATCHED")
