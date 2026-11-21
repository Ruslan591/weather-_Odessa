# -*- coding: utf-8 -*-
"""Панель «Онлайн» (live_web.py + index.html), 21.11: (1) на графике тени показываются все события сопровождения: БУ, БУ2, частичная цель, трейлинг, S/R, перенос стопа за экстремум (swing), лесенка, цель дальше (tp_ext); ступенчатые линии движущегося стопа и цели; (2) на графиках появился таймфрейм 1с (свечи 1s Binance, до 1000 штук за запрос). Идемпотентный.
Использование: python3 patch_chart.py live_web.py index.html"""
import os, sys

EVJS = r"""  if(CH.ev&&CH.ev.length){const EK={be:['БУ','#8b94a7'],be2:['БУ2','#8b94a7'],tp1:['ч.цель','#2ebd85'],trail_start:['трейл','#c77dff'],sr:['S/R','#4c8dff'],swing:['swing','#f0b90b'],mgr_ladder:['лест.','#8b94a7'],tp_ext:['цель+','#2ebd85']};
    const evs=CH.ev.filter(e=>e&&e.t&&EK[e.k]).sort((a,b)=>a.t-b.t);let st=CH.stop0||CH.stop,tg=CH.tp;const sp=[[CH.t_in,st]],tpp=[[CH.t_in,tg]];
    for(const e of evs){if(['be','be2','sr','swing','mgr_ladder'].includes(e.k)&&e.new!=null){st=e.new;sp.push([e.t,st])}if(e.k==='tp_ext'){if(e.stop_to!=null){st=e.stop_to;sp.push([e.t,st])}if(e.new!=null){tg=e.new;tpp.push([e.t,tg])}}}
    const te=CH.t_out||(cs[cs.length-1][0]+iv);sp.push([te,st]);tpp.push([te,tg]);
    const stepL=(pts,col)=>{c.save();c.setLineDash([2,3]);c.lineWidth=1.4;c.strokeStyle=col;c.beginPath();for(let i=0;i<pts.length-1;i++){const xa=X(Math.floor(pts[i][0]/iv)*iv)+bw/2,xb=X(Math.floor(pts[i+1][0]/iv)*iv)+bw/2,y=Y(pts[i][1]);c.moveTo(xa,y);c.lineTo(xb,y);if(i<pts.length-2)c.lineTo(xb,Y(pts[i+1][1]))}c.stroke();c.restore()};
    if(sp.length>2)stepL(sp,'#f6465d');if(tpp.length>2)stepL(tpp,'#2ebd85');
    let k2=0;for(const e of evs){if(e.t<t0||e.t>t1)continue;const pv=e.new!=null?e.new:e.px;if(pv==null)continue;const x=X(Math.floor(e.t/iv)*iv)+bw/2,y=Y(pv),m=EK[e.k];c.fillStyle=m[1];c.strokeStyle='#0b0e14';c.lineWidth=1.2;c.beginPath();c.moveTo(x,y-5);c.lineTo(x+5,y);c.lineTo(x,y+5);c.lineTo(x-5,y);c.closePath();c.fill();c.stroke();c.fillStyle=m[1];c.fillText(m[0],Math.min(x+7,pw-34),y+(k2++%2?13:-6))}}
"""
EVPY = '''def _evc(ev):
    """События сопровождения тени для графика панели (компактно, не больше 40 последних)."""
    out = []
    for e in (ev or [])[-40:]:
        if isinstance(e, dict): out.append({k: e[k] for k in ("t", "k", "old", "new", "px", "frac", "reason", "stop_from", "stop_to", "n") if k in e})
    return out


def build_shadow():'''
R = {
 "index.html": [
  ("const IVMS={'1m':60000,", "const IVMS={'1s':1000,'1m':60000,"),
  ("return d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}", "return d.toLocaleTimeString('ru-RU',iv<6e4?{hour:'2-digit',minute:'2-digit',second:'2-digit'}:{hour:'2-digit',minute:'2-digit'})}"),
  ("closed:1,ch:p.ch});", "closed:1,ch:p.ch,ev:p.ev});"),
  ("  c.lineWidth=1;const lab=[];", EVJS + "  c.lineWidth=1;const lab=[];"),
 ],
 "live_web.py": [
  ('IVS = {"1m": 60000,', 'IVS = {"1s": 1000, "1m": 60000,'),
  ("def build_shadow():", EVPY),
  ('if i.get("var") == "B" else i["id"])}', 'if i.get("var") == "B" else i["id"]), "ev": _evc(i.get("ev"))}'),
 ],
}
def patch(path):
    n = os.path.basename(path); s = open(path, encoding="utf-8").read(); rc = 0
    for old, new in R[n]:
        if new in s: print("ALREADY", n, old[:30].replace("\n", " ")); continue
        if s.count(old) != 1: print("ANCHOR_FAIL", n, s.count(old), old[:40]); rc = 1; continue
        s = s.replace(old, new, 1); print("APPLIED", n, old[:30].replace("\n", " "))
    if rc == 0: open(path, "w", encoding="utf-8").write(s)
    return rc
if __name__ == "__main__": sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
