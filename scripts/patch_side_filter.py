import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "_side_block" in s:
    print("ALREADY"); sys.exit(0)
fn = '''def _side_block(it):
    """Фильтр стороны по режиму рынка (shadow_cfg.json: side_filter): режим down - только short, up - только long, flat или нет данных - обе стороны. Режим берётся из it["rg"] на момент сигнала. Отфильтрованное ведётся вхолостую (cf), как у остальных фильтров."""
    try:
        if not cfg().get("side_filter", False): return None
        rg = (it.get("rg") or {}).get("regime"); sd = it.get("side")
        if (rg == "down" and sd == "long") or (rg == "up" and sd == "short"):
            return "фильтр стороны: режим %s, %s не разрешён" % (rg, sd)
    except Exception: pass
    return None


'''
a = "def _tick_gate(E, it):"
assert s.count(a) == 1, "anchor1"
s = s.replace(a, fn + a)
b = '        if it["status"] != "gate": return\n    o = it["o"]; wait'
assert s.count(b) == 1, "anchor2"
s = s.replace(b, '        if it["status"] != "gate": return\n    why_sf = _side_block(it)\n    if why_sf: return _filtered(E, it, why_sf, now)\n    o = it["o"]; wait')
open(p, "w", encoding="utf-8").write(s)
print("PATCHED")
