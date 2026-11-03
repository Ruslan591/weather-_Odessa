# -*- coding: utf-8 -*-
"""Патч 3 вкладки «Claude» на 18091: блок «Заявки (отложенные лимиты)» - график 5m с линиями канала, уровнем пробоя, лимитным ордером (время установки),
стопом и целью, список недавних заявок. Требует патч 2 и pos.py с orders в snapshot. Идемпотентен, бэкап *.bak_claude_tab3. Запуск: python patch_claude_tab3.py [каталог_панели]"""
import os, shutil, sys
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
HTML = os.path.join(D, "classic_pos_html.py")

JS = r"""function clHm(ms){const d=new Date(ms);return p2(d.getHours())+':'+p2(d.getMinutes())}
function clWhy(a){return a&&a.length?'<div class=sm style="margin-top:6px"><b>Из чего исходил:</b><ol style="margin:4px 0 0 18px;padding:0">'+a.map(w=>'<li style="margin-bottom:3px">'+String(w).replace(/@@(\d+)@@/g,(m,x)=>ft(+x))+'</li>').join('')+'</ol></div>':''}
function clOChart(o){const C=(o.cand||[]).slice(-150);if(C.length<5)return '';const has=o.price>0,W=360,H=270,L=4,Rr=66,F=has?26:4,N=C.length,T=N+F,t0=C[0][0],dt=300000,tE=t0+(T-1)*dt,tL=C[N-1][0];
let lo=Math.min(...C.map(c=>c[3])),hi=Math.max(...C.map(c=>c[2]));
if(has){lo=Math.min(lo,o.price,o.stop);hi=Math.max(hi,o.price,o.stop);if(o.tp>0){const rg=hi-lo;if(o.tp>=lo-rg&&o.tp<=hi+rg){lo=Math.min(lo,o.tp);hi=Math.max(hi,o.tp)}}}
if(o.chan)[o.chan.upper,o.chan.lower].forEach(ln=>{if(!ln)return;const v=ln.p1+ln.s*(tL-ln.t1),rg=hi-lo;if(v>=lo-rg*.5&&v<=hi+rg*.5){lo=Math.min(lo,v);hi=Math.max(hi,v)}});
const pad=(hi-lo)*.06||hi*.001;lo-=pad;hi+=pad;
const X=t=>L+((t-t0)/dt+.5)*(W-L-Rr)/T,Y=v=>H-18-(v-lo)/(hi-lo)*(H-30),pr=v=>(+v).toPrecision(5),vis=t=>t>=t0&&t<=tE;
let s="<svg viewBox='0 0 "+W+" "+H+"' style='width:100%;height:auto;background:#11151c;border-radius:8px;overflow:hidden'>";
const x1=has?X(o.placed_t):0,x2=has?X(o.expire_t):0;
if(has){const yp=Y(o.price),ys=Y(o.stop);s+="<rect x='"+x1+"' y='"+Math.min(yp,ys)+"' width='"+(x2-x1)+"' height='"+Math.abs(ys-yp)+"' fill='#da3633' opacity='.16'/>";if(o.tp>=lo&&o.tp<=hi){const yt=Y(o.tp);s+="<rect x='"+x1+"' y='"+Math.min(yp,yt)+"' width='"+(x2-x1)+"' height='"+Math.abs(yt-yp)+"' fill='#2ea043' opacity='.16'/>"}}
C.forEach(c=>{const col=c[4]>=c[1]?'#2ea043':'#da3633',x=X(c[0]);s+="<line x1='"+x+"' x2='"+x+"' y1='"+Y(c[2])+"' y2='"+Y(c[3])+"' stroke='"+col+"'/><rect x='"+(x-1.1)+"' y='"+Y(Math.max(c[1],c[4]))+"' width='2.2' height='"+Math.max(1,Math.abs(Y(c[1])-Y(c[4])))+"' fill='"+col+"'/>"});
C.forEach(c=>{const d=new Date(c[0]);if(d.getMinutes()===0&&d.getHours()%2===0){const x=X(c[0]);s+="<line x1='"+x+"' x2='"+x+"' y1='"+(H-18)+"' y2='"+(H-14)+"' stroke='#586069'/><text x='"+(x-9)+"' y='"+(H-4)+"' fill='#8b949e' font-size='8'>"+clHm(c[0])+"</text>"}});
const seg=(ln,col)=>{if(!ln)return '';const ta=Math.max(ln.t1,t0),pa=ln.p1+ln.s*(ta-ln.t1),pb=ln.p1+ln.s*(tE-ln.t1);return "<line x1='"+X(ta)+"' x2='"+X(tE)+"' y1='"+Y(pa)+"' y2='"+Y(pb)+"' stroke='"+col+"' stroke-width='1.3'/>"};
if(o.chan){s+=seg(o.chan.upper,'#3b82f6')+seg(o.chan.lower,'#3b82f6')}
const B=o.basis;if(B){const pts=(B.anchors||[]).concat(B.third?[B.third]:[]);pts.forEach((q,k)=>{if(!vis(q.t))return;const x=X(q.t),y=Y(q.p),third=q.n==='L3'||q.n==='H3';s+="<circle cx='"+x+"' cy='"+y+"' r='3.6' fill='"+(third?'none':'#e3b341')+"' stroke='#e3b341' stroke-width='1.4'/><text x='"+(x+5)+"' y='"+(y+(q.n[0]==='H'?-5:11))+"' fill='#e3b341' font-size='9'>"+q.n+"</text>"})}
if(o.level){const lv=o.level,xa=X(Math.max(lv.t_from,t0)),xb=X(lv.t_to),yl=Y(lv.p);s+="<line x1='"+xa+"' x2='"+X(tE)+"' y1='"+yl+"' y2='"+yl+"' stroke='#f85149' stroke-width='1.2'/><line x1='"+xa+"' x2='"+xb+"' y1='"+yl+"' y2='"+yl+"' stroke='#ff9f1c' stroke-width='3.2' opacity='.85'/><text x='"+(xa+2)+"' y='"+(yl-4)+"' fill='#ff9f1c' font-size='8'>окно уровня (24 св.)</text>";if(lv.t_ext&&vis(lv.t_ext))s+="<circle cx='"+X(lv.t_ext)+"' cy='"+yl+"' r='3' fill='#ff9f1c'/>"}
if(o.breakout&&vis(o.breakout.t)){const bx=X(o.breakout.t),up=o.breakout.dir==='up',by=Y(o.breakout.close);s+="<text x='"+(bx-14)+"' y='"+(by+(up?-8:14))+"' fill='#d2a8ff' font-size='9'>"+(up?'▲ пробой':'▼ пробой')+"</text>"}
if(has){const buy=o.side==='long',oc=buy?'#3fb950':'#ff7b72';
s+="<line x1='"+x1+"' x2='"+x1+"' y1='6' y2='"+(H-18)+"' stroke='#c9d1d9' stroke-dasharray='1 3'/><text x='"+Math.max(2,x1-30)+"' y='11' fill='#c9d1d9' font-size='9'>выставлен "+clHm(o.placed_t)+"</text>";
const hl=(v,col,t,w,dash)=>{if(!(v>=lo&&v<=hi))return '';return "<line x1='"+x1+"' x2='"+x2+"' y1='"+Y(v)+"' y2='"+Y(v)+"' stroke='"+col+"' stroke-width='"+w+"'"+(dash?" stroke-dasharray='4 3'":"")+"/><text x='"+(W-Rr+3)+"' y='"+(Y(v)+3)+"' fill='"+col+"' font-size='9'>"+t+" "+pr(v)+"</text>"};
s+=hl(o.price,oc,(buy?'BUY':'SELL'),2.6,false)+hl(o.stop,'#f85149','стоп',1,true)+hl(o.tp,'#3fb950','цель',1,true)}
if(o.px>=lo&&o.px<=hi)s+="<line x1='"+L+"' x2='"+(W-Rr)+"' y1='"+Y(o.px)+"' y2='"+Y(o.px)+"' stroke='#58a6ff' stroke-dasharray='1 2'/><text x='"+(W-Rr+3)+"' y='"+(Y(o.px)+3)+"' fill='#58a6ff' font-size='9'>цена "+pr(o.px)+"</text>";
return s+"</svg>"}
function clPair(){const v=($('clps')||{}).value;if(!v)return;S.clpsel=v;api('/api/claude',{action:'chart',sym:v}).then(j=>{S.clpv=j;renderRuns()}).catch(e=>alert(e.message))}
function clOrders(C){const O=C.orders;if(!O)return '';const P=O.pending||[],R=O.recent||[];
let h='<div class=sm style="margin-top:10px"><b>Заявки (отложенные лимиты)</b> · активных '+P.length+'. Продажа на верхней границе нисходящего канала, покупка на нижней границе восходящего; после пробоя канала лимит на пробитом уровне. Время на графике и в списке - по часам телефона. Жёлтые точки - опорные вершины канала (H1, H2) и третья точка параллельной линии (L3), оранжевая полоса - окно, где найден уровень.</div>';
if(O.error)h+='<div class=sm style="color:#f85149">ошибка модуля заявок: '+O.error+'</div>';
P.forEach(o=>{h+='<div class="sm posb"><b>'+o.sym+' '+(o.side==='long'?'BUY':'SELL')+' лимит '+(+o.price).toPrecision(5)+'</b> · '+o.rule_ru+'<br>выставлена <b>'+ft(o.placed_t)+'</b> · действует до '+ft(o.expire_t)+' · стоп '+(+o.stop).toPrecision(5)+' · цель '+(+o.tp).toPrecision(5)+' · риск '+o.risk_pct.toFixed(2)+'% · цена сейчас '+(+o.px).toPrecision(5)+' (до заявки '+o.dist_pct.toFixed(2)+'%)<div style="margin-top:8px">'+clOChart(o)+'</div>'+clWhy(o.why)+'</div>'});
if(!P.length)h+='<div class=sm style="margin-top:4px">Активных заявок нет: сканер ждёт канал или пробой.</div>';
h+='<div class=sm style="margin:8px 0 4px">Разметка сканера по паре (проверить, правильно ли бот видит канал): <select id=clps onchange="S.clpsel=this.value">'+(O.pairs||[]).map(p=>'<option'+(S.clpsel===p?' selected':'')+'>'+p+'</option>').join('')+'</select> <button onclick="clPair()">показать</button></div>';
if(S.clpv&&!S.clpv.error)h+='<div class="sm posb"><b>'+S.clpv.sym+' 5m</b> · '+S.clpv.rule_ru+' · ATR '+(+S.clpv.atr).toPrecision(3)+'<div style="margin-top:8px">'+clOChart(S.clpv)+'</div>'+clWhy(S.clpv.why)+'</div>';
if(R.length)h+='<details data-k=acl_ord style="margin-top:6px"><summary class=sm>Недавние заявки ('+R.length+')</summary>'+R.map(o=>'<div class=sm>'+ft(o.placed_t)+' → '+(o.t_end?ft(o.t_end):'—')+' · '+o.sym+' '+(o.side==='long'?'BUY':'SELL')+' '+(+o.price).toPrecision(5)+' · '+o.status_ru+(o.reason?': '+o.reason:'')+(o.pos_id?' (позиция #'+o.pos_id+')':'')+'</div>').join('')+'</details>';
return h}
"""

def main():
    s = open(HTML, encoding="utf-8").read()
    if "function clOrders(" in s:
        print("already patched"); return
    assert "function clCard(){" in s and s.count("function clCard(){") == 1, "патч 2 не применён"
    assert "'''" not in JS
    a = "if(C.open.length)h+='<div class=sm style=\"margin-top:8px\">Открытые позиции ('"
    assert s.count(a) == 1, s.count(a)
    s = s.replace("function clCard(){", JS + "function clCard(){", 1)
    s = s.replace(a, "h+=clOrders(C);" + a, 1)
    shutil.copy(HTML, HTML + ".bak_claude_tab3")
    open(HTML, "w", encoding="utf-8").write(s)
    print("patched")

if __name__ == "__main__":
    main()
