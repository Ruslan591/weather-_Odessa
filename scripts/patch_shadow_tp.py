# patch_shadow_tp: график теней показывает реальную цель движка (exit_cfg.levels), а не плановую p.tp. Идемпотентно.
import sys, py_compile
f = sys.argv[1]
s = open(f, encoding="utf-8").read()
if "EC.levels" in s: print("ALREADY"); sys.exit(0)
a1 = "except Exception as _e: SL = None\n"
n1 = a1 + "try:\n    import exit_cfg as EC\nexcept Exception: EC = None\n"
a2 = '''"ev": _evc(i.get("ev"))}
        out.append(r)'''
n2 = '''"ev": _evc(i.get("ev"))}
        if EC and src:      # цель на графике = цель движка (exit_cfg), план остаётся в tp_plan
            try:
                pp = dict(src); pp.setdefault("side", i.get("side")); pp.setdefault("entry", r["entry"])
                tpe = EC.levels(pp).get("tp")
                if tpe: r["tp_plan"] = r["tp"]; r["tp"] = tpe
            except Exception: pass
        out.append(r)'''
if s.count(a1) != 1 or s.count(a2) != 1: print("ANCHOR_FAIL", s.count(a1), s.count(a2)); sys.exit(1)
s = s.replace(a1, n1).replace(a2, n2)
open(f, "w", encoding="utf-8").write(s)
py_compile.compile(f, doraise=True)
print("PATCHED")
