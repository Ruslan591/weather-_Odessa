# patch_shadow_nb2: метка «в/б» (вне баланса) под плашкой стороны, а не рядом. Аргумент: index.html. Идемпотентно.
import sys
ix = sys.argv[1]; h = open(ix, encoding="utf-8").read()
old = "side(p.side),...(p.nb?[h('span','small a','вне баланса')]:[]),h('span','small mut',(p.kind=="
new = "(()=>{const w=h('div');w.style.cssText='display:flex;flex-direction:column;align-items:flex-start;line-height:1.1';w.append(side(p.side));if(p.nb){const m=h('span','small a','в/б');m.title='вне баланса';m.style.fontSize='11px';w.append(m)}return w})(),h('span','small mut',(p.kind=="
if "'в/б'" in h: print("ALREADY"); sys.exit(0)
if h.count(old) != 1: print("ANCHOR_FAIL", h.count(old)); sys.exit(1)
open(ix, "w", encoding="utf-8").write(h.replace(old, new)); print("PATCHED")
