# -*- coding: utf-8 -*-
"""Patch 5 of the Claude tab on 18091: the chart of an OPEN position from a channel/retest order shows the channel
(lines, anchor points, breakout level, breakout candle), the time the order was placed, on 5m candles.
Patches pos.py (snapshot attaches order data) and classic_pos_html.py (clZChart draws it). Idempotent.
Run: python patch_claude_tab5.py [panel_dir] [positions_dir]"""
import os, shutil, sys
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
P = sys.argv[2] if len(sys.argv) > 2 else "/opt/trading-bot/positions"
HTML = os.path.join(D, "classic_pos_html.py"); POS = os.path.join(P, "pos.py")

PYFUNC = '''
def _attach_chan(q):
    """Положить в открытую позицию из заявки: канал, опорные точки, уровень, пробой, время выставления; свечи 5m."""
    try:
        if q.get("src") != "chan": return
        o = json.load(open(os.path.join(D, "orders.json")))
        a = [x for x in o if x.get("id") == q.get("order_id")]
        if not a: return
        a = a[0]
        for k in ("chan", "basis", "level", "breakout", "placed_t", "expire_t", "ctype", "rule", "atr", "why"):
            if a.get(k) is not None: q["o_" + k] = a[k]
        q["cand"] = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(q["sym"], "5m", 300)]
        q["o_dt"] = 300000
    except Exception as e:
        q["o_err"] = str(e)[:80]

def snapshot():'''

JS = r"""function clZChart(p,id){if(!(p.o_dt>0)||!(p.o_chan||p.o_level))return clZChart0(p,id);
const C=p.cand||[];if(C.length<5)return '';const dt=p.o_dt,tL=C[C.length-1][0],F=26,sp={cand:C,dt:dt,F:F,n0:110,ext:[p.entry,p.stop,p.be_px,p.tp,p.px],zones:[],segs:[],pts:[],hl:[],vl:[]},te=tL+F*dt,x1=p.o_placed_t||p.t_in;
sp.zones.push({t1:p.t_in,t2:te,p1:p.entry,p2:p.stop,col:'rgba(218,54,51,.16)'});if(p.tp>0)sp.zones.push({t1:p.t_in,t2:te,p1:p.entry,p2:p.tp,col:'rgba(46,160,67,.16)'});
sp.hl.push({v:p.entry,col:'#cfd6e0',txt:'вход',w:1.6,t1:p.t_in},{v:p.stop,col:'#f85149',txt:'стоп',w:1.2,dash:[4,3],t1:p.t_in},{v:p.be_px,col:'#d29922',txt:'БУ',w:1,dash:[4,3],t1:p.t_in},{v:p.tp,col:'#3fb950',txt:'цель',w:1.2,dash:[4,3],t1:p.t_in},{v:p.px,col:'#58a6ff',txt:'цена',w:1,dash:[1,2]});
sp.vl.push({t:x1,txt:'лимит выставлен '+clHm(x1)});if(p.t_in!==x1)sp.vl.push({t:p.t_in,txt:'вход '+clHm(p.t_in)});
if(p.o_chan)[p.o_chan.upper,p.o_chan.lower].forEach(ln=>{if(!ln)return;sp.segs.push({t1:ln.t1,p1:ln.p1,s:ln.s,col:'#3b82f6'});sp.ext.push(ln.p1+ln.s*(tL-ln.t1))});
const B=p.o_basis;if(B)(B.anchors||[]).concat(B.third?[B.third]:[]).forEach(q=>{sp.pts.push({t:q.t,p:q.p,n:q.n,third:q.n==='L3'||q.n==='H3'})});
if(p.o_level){sp.level=p.o_level;sp.ext.push(p.o_level.p)}if(p.o_breakout)sp.brk=p.o_breakout;
return clZBox(id,sp,330)+'<div class=sm style=\"margin-top:4px\">Канал и точки - как они были в момент выставления лимита ('+(p.o_rule||'')+'). Синие линии - канал, жёлтые точки - опорные вершины, оранжевая полоса и красная линия - пробитый уровень.</div>'}
"""

def main():
    s = open(HTML, encoding="utf-8").read(); q = open(POS, encoding="utf-8").read()
    if "function clZChart0(" in s and "def _attach_chan(" in q:
        print("already patched"); return
    assert "function clZChart(p,id){" in s and s.count("function clZChart(p,id){") == 1, "patch 4 not applied"
    assert q.count("def snapshot():") == 1 and q.count("opn.append(q)") == 1
    assert "'''" not in JS
    s = s.replace("function clZChart(p,id){", JS + "function clZChart0(p,id){")
    q = q.replace("def snapshot():", PYFUNC.lstrip("\n"), 1).replace("opn.append(q)", "_attach_chan(q); opn.append(q)")
    shutil.copy(HTML, HTML + ".bak_claude_tab5"); shutil.copy(POS, POS + ".bak_claude_tab5")
    open(HTML, "w", encoding="utf-8").write(s); open(POS, "w", encoding="utf-8").write(q)
    print("patched")

if __name__ == "__main__":
    main()
