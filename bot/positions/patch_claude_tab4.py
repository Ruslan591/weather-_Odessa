# -*- coding: utf-8 -*-
"""Patch 4 of the Claude tab on 18091: interactive zoomable charts (positions and orders) instead of static SVG.
Pan by dragging, price scale (right) and time scale (bottom) zoom, pinch, wheel, buttons, double tap reset, tap crosshair with OHLC.
Requires patches 1-3. Idempotent, backup *.bak_claude_tab4. Run: python patch_claude_tab4.py [panel_dir]"""
import os, shutil, sys
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
HTML = os.path.join(D, "classic_pos_html.py")

JS = r"""var CLZR=78,CLZB=18;
function clZv(id){S.clzv=S.clzv||{};return S.clzv[id]||(S.clzv[id]={n:0,off:0,vz:1,vo:0,free:0,cx:null})}
function clZBox(id,sp,H){S.clzs=S.clzs||{};S.clzs[id]=sp;const V=clZv(id);
return '<div class=clzw data-zid="'+id+'"><div style="position:relative;height:'+H+'px;background:#0d1117;border-radius:8px;overflow:hidden"><canvas class=clzc style="display:block;width:100%;height:'+H+'px;touch-action:'+(V.free?'none':'pan-y')+'"></canvas><div class=clzp style="position:absolute;top:0;right:0;width:'+CLZR+'px;height:'+(H-CLZB)+'px;touch-action:none"></div><div class=clzt style="position:absolute;left:0;bottom:0;width:calc(100% - '+CLZR+'px);height:'+CLZB+'px;touch-action:none"></div></div>'
+'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;align-items:center"><button data-zb=tm>время −</button><button data-zb=tp>время +</button><button data-zb=vm>цена −</button><button data-zb=vp>цена +</button><button data-zb=fr'+(V.free?' class=on':'')+'>'+(V.free?'✋ график двигается':'✋ листать страницу')+'</button><button data-zb=rs>⟲</button></div>'
+'<div class=sm style="margin-top:4px">Тяните график вбок — сдвиг по времени; по правой шкале вверх/вниз — масштаб по цене, по нижней шкале вбок — по времени; щипок — масштаб; двойной тап — сброс; тап — перекрестие с ценами свечи. «✋» включает свободное движение и по вертикали (тогда страница на графике не листается).</div></div>'}
function clZDraw(id,cv){const D=S.clzs&&S.clzs[id];if(!D||!cv)return;const C=D.cand,N=C.length;if(N<5)return;
const dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;if(!W||!H)return;cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
const Lm=4,Rm=CLZR,Bm=CLZB,Tm=16,pw=W-Lm-Rm,ph=H-Bm-Tm,dt=D.dt,t0=C[0][0],F=D.F,V=clZv(id),tot=N+F;
V.vz=Math.max(.15,Math.min(12,V.vz||1));V.vo=V.vo||0;if(!V.n)V.n=Math.min(tot,D.n0||110);V.n=Math.max(12,Math.min(tot,V.n));V.off=Math.max(-V.n*.5,Math.min(N-8,V.off||0));
const R=tot-V.off,L0=R-V.n,bw=pw/V.n,X=i=>Lm+(i-L0+.5)*bw,Xt=t=>X((t-t0)/dt),tA=t0+(L0-.5)*dt,tB=t0+(R-.5)*dt;
const i0=Math.max(0,Math.floor(L0)),i1=Math.min(N-1,Math.ceil(R));let hi=-1e99,lo=1e99;for(let i=i0;i<=i1;i++){hi=Math.max(hi,C[i][2]);lo=Math.min(lo,C[i][3])}
if(hi<lo){hi=C[N-1][4]*1.002;lo=C[N-1][4]*.998}
const rg0=(hi-lo)||hi*.002;(D.ext||[]).forEach(v=>{if(v>0&&v>=lo-rg0&&v<=hi+rg0){hi=Math.max(hi,v);lo=Math.min(lo,v)}});
const rg=(hi-lo)||hi*.002,cen=(hi+lo)/2+V.vo*rg,half=rg*.56/V.vz;hi=cen+half;lo=cen-half;const Y=p=>Tm+(hi-p)/(hi-lo)*ph,PR=v=>(+v).toPrecision(5);
S.clzG=S.clzG||{};S.clzG[id]={bw:bw,pxVo:1.12/V.vz/ph,Lm:Lm,pw:pw,Tm:Tm,ph:ph};
g.font='11px system-ui';g.textBaseline='middle';
for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5,y=Y(p);g.strokeStyle='#1b222c';g.lineWidth=1;g.beginPath();g.moveTo(Lm,y);g.lineTo(Lm+pw,y);g.stroke();g.fillStyle='#6e7681';g.textAlign='left';g.fillText(PR(p),Lm+pw+5,y)}
const SM=[5,15,30,60,120,240,360,720,1440,2880],ppm=bw/(dt/60000),sm=SM.find(s=>s*ppm>=66)||2880,tz=new Date().getTimezoneOffset()*60000,sms=sm*60000;g.textAlign='center';
for(let tt=Math.ceil((tA-tz)/sms)*sms+tz;tt<=tB;tt+=sms){const x=Xt(tt);if(x<Lm+12||x>Lm+pw-12)continue;const d=new Date(tt);g.strokeStyle='#161c24';g.beginPath();g.moveTo(x,Tm);g.lineTo(x,Tm+ph);g.stroke();g.fillStyle='#8b949e';g.fillText(d.getHours()===0&&d.getMinutes()===0?p2(d.getDate())+'.'+p2(d.getMonth()+1):clHm(tt),x,H-Bm/2)}
g.save();g.beginPath();g.rect(Lm,Tm,pw,ph);g.clip();
(D.zones||[]).forEach(z=>{const xa=Xt(z.t1),xb=Xt(z.t2),ya=Y(z.p1),yb=Y(z.p2);g.fillStyle=z.col;g.fillRect(xa,Math.min(ya,yb),xb-xa,Math.abs(yb-ya))});
const bwd=Math.max(1,bw*.7);for(let i=i0;i<=i1;i++){const c=C[i],up=c[4]>=c[1],x=X(i);g.strokeStyle=g.fillStyle=up?'#26a69a':'#ef5350';g.lineWidth=1;g.beginPath();g.moveTo(x,Y(c[2]));g.lineTo(x,Y(c[3]));g.stroke();if(bw>=1.8){const yo=Y(c[1]),yc=Y(c[4]);g.fillRect(x-bwd/2,Math.min(yo,yc),bwd,Math.max(1,Math.abs(yo-yc)))}}
(D.segs||[]).forEach(s=>{const ta=Math.max(s.t1,tA),pa=s.p1+s.s*(ta-s.t1),pb=s.p1+s.s*(tB-s.t1);g.strokeStyle=s.col;g.lineWidth=1.6;g.beginPath();g.moveTo(Xt(ta),Y(pa));g.lineTo(Xt(tB),Y(pb));g.stroke()});
if(D.level){const lv=D.level,yl=Y(lv.p),xa=Xt(Math.max(lv.t_from,tA)),xb=Xt(lv.t_to);g.strokeStyle='#f85149';g.lineWidth=1.4;g.beginPath();g.moveTo(xa,yl);g.lineTo(Xt(tB),yl);g.stroke();g.strokeStyle='rgba(255,159,28,.85)';g.lineWidth=4;g.beginPath();g.moveTo(xa,yl);g.lineTo(xb,yl);g.stroke();g.lineWidth=1;g.fillStyle='#ff9f1c';g.textAlign='left';g.fillText('окно уровня (24 св.)',xa+3,yl-8);if(lv.t_ext){g.beginPath();g.arc(Xt(lv.t_ext),yl,3.6,0,6.2832);g.fill()}}
(D.pts||[]).forEach(q=>{const x=Xt(q.t),y=Y(q.p);g.strokeStyle=g.fillStyle='#e3b341';g.lineWidth=1.6;g.beginPath();g.arc(x,y,4.2,0,6.2832);if(q.third)g.stroke();else g.fill();g.lineWidth=1;g.textAlign='left';g.fillText(q.n,x+6,y+(q.n[0]==='H'?-8:10))});
if(D.brk){const b=D.brk,x=Xt(b.t),y=Y(b.close),u=b.dir==='up';g.fillStyle='#d2a8ff';g.textAlign='center';g.fillText(u?'▲ пробой':'▼ пробой',x,y+(u?-11:14))}
(D.vl||[]).forEach(v=>{const x=Xt(v.t);g.strokeStyle='#c9d1d9';g.setLineDash([1,3]);g.beginPath();g.moveTo(x,Tm);g.lineTo(x,Tm+ph);g.stroke();g.setLineDash([]);g.fillStyle='#c9d1d9';g.textAlign='left';g.fillText(v.txt,Math.max(Lm+2,x-34),Tm+8)});
const T=[];(D.hl||[]).forEach(h=>{if(!(h.v>0))return;const y=Y(h.v);if(y>=Tm&&y<=Tm+ph){g.strokeStyle=h.col;g.lineWidth=h.w||1;g.setLineDash(h.dash||[]);g.beginPath();g.moveTo(h.t1==null?Lm:Math.max(Lm,Xt(h.t1)),y);g.lineTo(h.t2==null?Lm+pw:Math.min(Lm+pw,Xt(h.t2)),y);g.stroke();g.setLineDash([]);g.lineWidth=1}T.push({y:y,v:h.v,col:h.col,txt:h.txt})});
g.restore();
T.forEach(t=>{t.o=t.y<Tm?-1:t.y>Tm+ph?1:0;t.y=Math.max(Tm+8,Math.min(Tm+ph-8,t.y))});T.sort((a,b)=>a.y-b.y);for(let k=1;k<T.length;k++)if(T[k].y<T[k-1].y+15)T[k].y=T[k-1].y+15;for(let k=T.length-2;k>=0;k--)if(T[k].y>Tm+ph-8-(T.length-1-k)*15)T[k].y=Tm+ph-8-(T.length-1-k)*15;
g.font='bold 10.5px system-ui';g.textAlign='left';T.forEach(t=>{g.fillStyle=t.col;g.fillRect(Lm+pw+1,t.y-8,Rm-2,16);g.fillStyle='#0d1117';g.fillText((t.o>0?'↑':t.o<0?'↓':'')+t.txt+' '+PR(t.v),Lm+pw+3,t.y)});g.font='11px system-ui';
if(V.cx&&V.cx.x>=Lm&&V.cx.x<=Lm+pw&&V.cx.y>=Tm&&V.cx.y<=Tm+ph){const q=V.cx,ix=Math.round(L0+(q.x-Lm)/bw-.5),pc=hi-(q.y-Tm)/ph*(hi-lo);g.strokeStyle='#8b949e';g.setLineDash([3,3]);g.beginPath();g.moveTo(q.x,Tm);g.lineTo(q.x,Tm+ph);g.moveTo(Lm,q.y);g.lineTo(Lm+pw,q.y);g.stroke();g.setLineDash([]);g.fillStyle='#30363d';g.fillRect(Lm+pw+1,q.y-8,Rm-2,16);g.fillStyle='#fff';g.textAlign='left';g.fillText(PR(pc),Lm+pw+5,q.y);
if(ix>=0&&ix<N){const c=C[ix],d=new Date(c[0]);g.fillStyle='#c9d1d9';g.textAlign='left';g.fillText(p2(d.getDate())+'.'+p2(d.getMonth()+1)+' '+clHm(c[0])+'  O '+PR(c[1])+'  H '+PR(c[2])+'  L '+PR(c[3])+'  C '+PR(c[4]),Lm+2,8)}}}
function clZBind(id,w,cv,pz,tz){const P=new Map();let g0=null,lt=0;const V=()=>clZv(id),draw=()=>clZDraw(id,cv),free=()=>{S.clzBusy=0};
const pt=e=>{const r=cv.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}};
const down=zone=>e=>{try{e.currentTarget.setPointerCapture(e.pointerId)}catch(_){}S.clzBusy=1;const q=pt(e),v=V();P.set(e.pointerId,q);if(P.size===1)g0={x:q.x,y:q.y,off:v.off,vo:v.vo,vz:v.vz,n:v.n,zone:zone,moved:false};else if(P.size===2&&g0){const a=[...P.values()];g0.pinch={dx:Math.abs(a[0].x-a[1].x),dy:Math.abs(a[0].y-a[1].y),n:v.n,vz:v.vz};g0.moved=true}};
const move=e=>{if(!P.has(e.pointerId)||!g0)return;const q=pt(e),v=V(),G=S.clzG[id];P.set(e.pointerId,q);if(!G)return;
if(P.size===2&&g0.pinch){const a=[...P.values()],dx=Math.abs(a[0].x-a[1].x),dy=Math.abs(a[0].y-a[1].y);if(g0.pinch.dy>g0.pinch.dx*1.2)v.vz=g0.pinch.vz*Math.max(dy,10)/Math.max(g0.pinch.dy,10);else v.n=g0.pinch.n*Math.max(g0.pinch.dx,10)/Math.max(dx,10);draw();return}
const dx=q.x-g0.x,dy=q.y-g0.y;if(Math.abs(dx)>5||Math.abs(dy)>5)g0.moved=true;if(!g0.moved)return;
if(g0.zone==='p')v.vz=g0.vz*Math.exp(-dy/120);else if(g0.zone==='t')v.n=g0.n*Math.exp(-dx/120);else{v.off=g0.off+dx/G.bw;v.vo=g0.vo+dy*G.pxVo}draw()};
const up=e=>{if(P.size===1&&g0&&!g0.moved&&g0.zone==='c'){const t=Date.now(),v=V();if(t-lt<350){v.n=0;v.off=0;v.vz=1;v.vo=0;v.cx=null;lt=0}else{v.cx=pt(e);lt=t}draw()}P.delete(e.pointerId);if(!P.size){g0=null;setTimeout(free,700)}};
const cancel=e=>{P.delete(e.pointerId);if(!P.size){g0=null;setTimeout(free,300)}};
[[cv,'c'],[pz,'p'],[tz,'t']].forEach(a=>{a[0].onpointerdown=down(a[1]);a[0].onpointermove=move;a[0].onpointerup=up;a[0].onpointercancel=cancel});
cv.addEventListener('wheel',e=>{e.preventDefault();const v=V(),f=e.deltaY>0?1.15:.87;if(e.shiftKey)v.vz=v.vz/f;else if(e.altKey)v.off+=(e.deltaY>0?1:-1)*Math.max(1,v.n*.1);else v.n=v.n*f;draw()},{passive:false});
w.querySelectorAll('[data-zb]').forEach(b=>{b.onclick=()=>{const v=V(),k=b.dataset.zb;if(k==='tm')v.n=v.n*1.3;else if(k==='tp')v.n=v.n/1.3;else if(k==='vm')v.vz=v.vz/1.3;else if(k==='vp')v.vz=v.vz*1.3;else if(k==='rs'){v.n=0;v.off=0;v.vz=1;v.vo=0;v.cx=null}else if(k==='fr'){v.free=v.free?0:1;cv.style.touchAction=v.free?'none':'pan-y';b.textContent=v.free?'✋ график двигается':'✋ листать страницу';b.classList.toggle('on',!!v.free)}draw()}})}
function clZInit(){document.querySelectorAll('#runs .clzw').forEach(w=>{const id=w.dataset.zid,cv=w.querySelector('.clzc');clZDraw(id,cv);clZBind(id,w,cv,w.querySelector('.clzp'),w.querySelector('.clzt'))})}
function clZOChart(o,id){const C=o.cand||[];if(C.length<5)return '';const has=o.price>0,dt=300000,sp={cand:C,dt:dt,F:has?26:4,n0:has?100:110,ext:[],zones:[],segs:[],pts:[],hl:[],vl:[]},tL=C[C.length-1][0];
if(has){const x1=o.placed_t,x2=o.expire_t,buy=o.side==='long',oc=buy?'#3fb950':'#ff7b72';sp.zones.push({t1:x1,t2:x2,p1:o.price,p2:o.stop,col:'rgba(218,54,51,.18)'});if(o.tp>0)sp.zones.push({t1:x1,t2:x2,p1:o.price,p2:o.tp,col:'rgba(46,160,67,.18)'});
sp.hl.push({v:o.price,col:oc,txt:buy?'BUY':'SELL',w:2.6,t1:x1,t2:x2},{v:o.stop,col:'#f85149',txt:'стоп',w:1.2,dash:[4,3],t1:x1,t2:x2},{v:o.tp,col:'#3fb950',txt:'цель',w:1.2,dash:[4,3],t1:x1,t2:x2});sp.ext.push(o.price,o.stop,o.tp);sp.vl.push({t:x1,txt:'выставлен '+clHm(x1)})}
if(o.chan)[o.chan.upper,o.chan.lower].forEach(ln=>{if(!ln)return;sp.segs.push({t1:ln.t1,p1:ln.p1,s:ln.s,col:'#3b82f6'});sp.ext.push(ln.p1+ln.s*(tL-ln.t1))});
const B=o.basis;if(B)(B.anchors||[]).concat(B.third?[B.third]:[]).forEach(q=>{sp.pts.push({t:q.t,p:q.p,n:q.n,third:q.n==='L3'||q.n==='H3'})});
if(o.level){sp.level=o.level;sp.ext.push(o.level.p)}if(o.breakout)sp.brk=o.breakout;
if(o.px>0)sp.hl.push({v:o.px,col:'#58a6ff',txt:'цена',w:1,dash:[1,2]});return clZBox(id,sp,330)}
function clZChart(p,id){const C=p.cand||[];if(C.length<5)return '';const dt=900000,tL=C[C.length-1][0],F=8,te=tL+F*dt,sp={cand:C,dt:dt,F:F,n0:96,ext:[p.entry,p.stop,p.be_px,p.tp,p.px],zones:[],segs:[],pts:[],hl:[],vl:[{t:p.t_in,txt:'вход '+clHm(p.t_in)}]};
sp.zones.push({t1:p.t_in,t2:te,p1:p.entry,p2:p.stop,col:'rgba(218,54,51,.16)'});if(p.tp>0)sp.zones.push({t1:p.t_in,t2:te,p1:p.entry,p2:p.tp,col:'rgba(46,160,67,.16)'});
sp.hl.push({v:p.entry,col:'#cfd6e0',txt:'вход',w:1.2,dash:[4,3],t1:p.t_in},{v:p.stop,col:'#f85149',txt:'стоп',w:1.2,dash:[4,3],t1:p.t_in},{v:p.be_px,col:'#d29922',txt:'БУ',w:1,dash:[4,3],t1:p.t_in},{v:p.tp,col:'#3fb950',txt:'цель',w:1.2,dash:[4,3],t1:p.t_in},{v:p.px,col:'#58a6ff',txt:'цена',w:1,dash:[1,2]});return clZBox(id,sp,300)}
"""

def main():
    s = open(HTML, encoding="utf-8").read()
    if "function clZInit(" in s:
        print("already patched"); return
    assert "function clOrders(" in s and "function clCard(){" in s, "patches 1-3 not applied"
    assert "'''" not in JS
    def rep(a, b):
        nonlocal s
        assert s.count(a) == 1, (s.count(a), a[:70])
        s = s.replace(a, b)
    rep("function clCard(){", JS + "function clCard(){")
    rep("'+clChart(p)+'", "'+clZChart(p,'p'+p.id)+'")
    rep("'+clOChart(o)+'", "'+clZOChart(o,'o'+o.id)+'")
    rep("'+clOChart(S.clpv)+'", "'+clZOChart(S.clpv,'v'+S.clpv.sym)+'")
    rep("if(S.track==='cl'){FIN(loadLine()+trackBar()+clCard());clBind();return}",
        "if(S.track==='cl'){if(S.clzBusy)return;FIN(loadLine()+trackBar()+clCard());clBind();clZInit();return}")
    shutil.copy(HTML, HTML + ".bak_claude_tab4")
    open(HTML, "w", encoding="utf-8").write(s)
    print("patched")

if __name__ == "__main__":
    main()
