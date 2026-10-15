HTML = r'''<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Классика · позиции</title>
<style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px system-ui,sans-serif}
.t{display:flex;flex-wrap:wrap;gap:4px;padding:4px 6px}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:4px 8px;font-size:12px}
button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
.card{margin:6px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px}
.card h4{margin:0 0 6px;font-size:13px;color:#e6edf3}
.grid{display:flex;flex-wrap:wrap;gap:14px}.grid div span{display:block;font-size:11px;color:#8b949e}.grid div b{font-size:16px}
table{border-collapse:collapse;width:100%}td,th{padding:3px 5px;text-align:right;border-bottom:1px solid #21262d;font-size:11.5px;white-space:nowrap}
td:first-child,th:first-child{text-align:left}.sc{overflow-x:auto}
.up{color:#26a69a}.dn{color:#ef5350}.fl{color:#8b949e}
canvas{display:block;width:100%;height:420px;touch-action:none}
</style></head><body>
<div class=card><h4 id=ttl>Позиции за 24 ч</h4><div id=rules style="color:#8b949e;font-size:11.5px"></div></div>
<div class=t id=pairs></div>
<div class=card><div class=grid id=sum></div></div>
<div class=card id=cch style="display:none"><h4 id=chT></h4><div class=t id=rng></div><div id=chinfo style="font:11.5px ui-monospace,monospace;color:#8b949e;min-height:30px"></div><canvas id=c></canvas><div style="color:#8b949e;font-size:11px">жёлтая EMA20, фиолетовая EMA200; ▲ лонг / ▼ шорт — вход, ■ — выход, красный пунктир — начальный стоп, линия вход→выход зелёная при плюсе. Время локальное. Перетаскивание — прокрутка, щипок или колесо — масштаб, тап — перекрестие. Страницу прокручивай, касаясь вне графика.</div></div>
<div class=card><h4>Сделки</h4><div class=sc id=tbl>загрузка…</div></div>
<div class=card id=cpair style="display:none"><h4>По парам</h4><div class=sc id=pp></div></div>
<script>
const $=id=>document.getElementById(id);
const S={sym:'ALL',pairs:[],D:null};
const V={n:480,off:0},Gc={start:0,end:0,bw:5,L:4,hover:-1};
const wl=h=>h>=48?(h/24)+' сут':h+' ч';
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:7;return p.toFixed(d)}
const p2=n=>String(n).padStart(2,'0');
function ft(t){const d=new Date(t);return p2(d.getDate())+'.'+p2(d.getMonth()+1)+' '+p2(d.getHours())+':'+p2(d.getMinutes())}
const sg=v=>(v>=0?'+':'')+v.toFixed(2);const cls=v=>v>0?'up':v<0?'dn':'fl';
function mkr(){$('rng').innerHTML='';[[192,'48 ч'],[480,'5 сут'],[960,'10 сут']].forEach(([n,l])=>{const b=document.createElement('button');b.textContent=l;if(V.n===n)b.className='on';b.onclick=()=>{V.n=n;V.off=0;Gc.hover=-1;mkr();chart()};$('rng').appendChild(b)})}
function mk(){$('pairs').innerHTML='';['ALL'].concat(S.pairs).forEach(p=>{const b=document.createElement('button');b.textContent=p==='ALL'?'ВСЕ':p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;V.off=0;Gc.hover=-1;mk();load()};$('pairs').appendChild(b)})}
async function load(){
 try{const r=await fetch('/api/trades?sym='+S.sym+'&bars=960');const j=await r.json();if(j.error){$('tbl').textContent='Ошибка: '+j.error;return}
  if(j.sym!==S.sym)return;S.D=j;render()}catch(e){$('tbl').textContent='Ошибка: '+e}
}
function render(){
 const D=S.D,P=D.params;
 $('ttl').textContent='Позиции за '+wl(P.window_h)+' · '+(S.sym==='ALL'?'все пары':S.sym)+' · '+P.tf;
 const stp=P.stop_mode==='prev'?'за экстремумом предыдущей свечи (лонг — её low, шорт — её high), но не ближе '+P.min_stop_pct+'%'+(P.min_stop_atr?' и '+P.min_stop_atr+' ATR':''):'на последнем подтверждённом pivot';
 const trl={none:'без трейлинга',pct:'трейлинг на расстоянии '+P.trail_dist+'% от экстремума',atr:'трейлинг на расстоянии '+P.trail_dist+' ATR от экстремума',pivot:'трейлинг по pivot'}[P.trail_mode];
 $('rules').textContent='Вход: пересечение EMA20 × EMA200 (лонг и шорт), по открытию следующей свечи. Стоп: '+stp+'. +'+P.be_trigger+'% → безубыток, затем '+trl+'. Разворот при обратном пересечении. Комиссия '+P.fee+'% за сторону (учтена в Net), объём условный '+P.notional+' USDT.';
 const T=D.trades,n=T.length,w=T.filter(x=>x.net>0).length,s=T.reduce((a,x)=>a+x.net,0),sp=T.reduce((a,x)=>a+x.net*P.notional/100,0);
 const best=n?Math.max(...T.map(x=>x.net)):0,worst=n?Math.min(...T.map(x=>x.net)):0,be=T.filter(x=>x.be).length,op=T.filter(x=>x.open).length;
 const gs=T.reduce((a,x)=>a+x.gross,0);
 $('sum').innerHTML=[['Сделок',n],['Прибыльных',n?w+' ('+Math.round(w/n*100)+'%)':'—'],['Сумма Net %','<span class="'+cls(s)+'" style="display:inline;font-size:16px">'+sg(s)+'%</span>'],['Net, USDT','<span class="'+cls(sp)+'" style="display:inline;font-size:16px">'+sg(sp)+'</span>'],['До комиссий %',sg(gs)+'%'],['Дошли до БУ',be+' из '+n],['Лучшая / худшая',sg(best)+' / '+sg(worst)],['Открытых',op]].map(x=>'<div><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join('');
 let h='<table><tr><th>Пара</th><th>Сторона</th><th>Вход</th><th>Цена</th><th>Стоп0</th><th>Риск%</th><th>Выход</th><th>Цена</th><th>Причина</th><th>Net%</th><th>MFE</th><th>MAE</th></tr>';
 T.slice().sort((a,b)=>b.t_in-a.t_in).forEach(x=>{h+='<tr><td>'+x.sym.replace('USDT','')+'</td><td class="'+(x.side==='L'?'up':'dn')+'">'+(x.side==='L'?'ЛОНГ':'ШОРТ')+'</td><td>'+ft(x.t_in)+'</td><td>'+fmt(x.p_in)+'</td><td>'+fmt(x.stop0)+'</td><td>'+x.risk.toFixed(2)+'</td><td>'+(x.open?'—':ft(x.t_out))+'</td><td>'+(x.open?fmt(x.p_out)+' (тек.)':fmt(x.p_out))+'</td><td>'+x.reason+(x.be&&x.reason!=='безубыток'?' ✓БУ':'')+'</td><td class="'+cls(x.net)+'"><b>'+sg(x.net)+'</b></td><td>'+x.mfe.toFixed(2)+'</td><td>'+x.mae.toFixed(2)+'</td></tr>'});
 $('tbl').innerHTML=n?h+'</table>':'За выбранный период сигналов не было';
 if(S.sym==='ALL'){const m={};T.forEach(x=>{(m[x.sym]=m[x.sym]||[]).push(x)});
  let q='<table><tr><th>Пара</th><th>Сделок</th><th>Плюс</th><th>Net %</th></tr>';
  Object.keys(m).sort().forEach(k=>{const a=m[k],ss=a.reduce((z,x)=>z+x.net,0);q+='<tr><td>'+k.replace('USDT','')+'</td><td>'+a.length+'</td><td>'+a.filter(x=>x.net>0).length+'</td><td class="'+cls(ss)+'">'+sg(ss)+'</td></tr>'});
  $('pp').innerHTML=q+'</table>';$('cpair').style.display='block';$('cch').style.display='none'}
 else{$('cpair').style.display='none';$('cch').style.display='block';$('chT').textContent=S.sym+' · 15m';chart()}
}
function chart(){
 const C=S.D.chart;if(!C)return;const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=420;
 cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
 const N=C.t.length,L=4,R=58,B=16,pw=W-L-R;
 V.n=Math.max(20,Math.min(V.n,N));V.off=Math.max(0,Math.min(V.off,N-20));
 const end=N-V.off,start=Math.max(0,end-V.n),cnt=end-start,bw=pw/(cnt+(V.off===0?2:0));
 Gc.start=start;Gc.end=end;Gc.bw=bw;Gc.L=L;
 const X=i=>L+(i-start+0.5)*bw;
 const ix=t=>{let b=-1;for(let i=0;i<N;i++){if(C.t[i]<=t)b=i}return b};
 const TR=S.D.trades.map(x=>Object.assign({},x,{a:ix(x.t_in),b:ix(x.t_out)}));
 let hi=-1e99,lo=1e99;for(let i=start;i<end;i++){hi=Math.max(hi,C.h[i]);lo=Math.min(lo,C.l[i])}
 const rg=hi-lo;TR.forEach(x=>{if(x.a>=start&&x.a<end&&x.stop0>lo-rg*0.15&&x.stop0<hi+rg*0.15){hi=Math.max(hi,x.stop0);lo=Math.min(lo,x.stop0)}});
 const pad=(hi-lo)*0.05||hi*0.01;hi+=pad;lo-=pad;const Y=p=>6+(hi-p)/(hi-lo)*(H-B-12);
 g.font='10px system-ui';g.textBaseline='middle';g.fillStyle='#6e7681';g.strokeStyle='#1b222c';g.textAlign='left';
 for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5;g.beginPath();g.moveTo(L,Y(p));g.lineTo(L+pw,Y(p));g.stroke();g.fillText(fmt(p),L+pw+4,Y(p))}
 const step=Math.max(1,Math.ceil(90/bw));g.textAlign='center';for(let i=start;i<end;i+=step){g.fillText(ft(C.t[i]),Math.min(X(i),W-R-30),H-7)}g.textAlign='left';
 for(let i=start;i<end;i++){const up=C.c[i]>=C.o[i],col=up?'#26a69a':'#ef5350',x=X(i),w=Math.max(1,bw*0.7);g.strokeStyle=g.fillStyle=col;g.beginPath();g.moveTo(x,Y(C.h[i]));g.lineTo(x,Y(C.l[i]));g.stroke();if(bw>=1.6)g.fillRect(x-w/2,Y(Math.max(C.o[i],C.c[i])),w,Math.max(1,Y(Math.min(C.o[i],C.c[i]))-Y(Math.max(C.o[i],C.c[i]))))}
 [['ema20','#e3b341'],['ema200','#bc8cff']].forEach(([k,c])=>{g.strokeStyle=c;g.lineWidth=1.4;g.beginPath();let on=false;for(let i=start;i<end;i++){const v=C[k][i];if(v==null){on=false;continue}if(!on){g.moveTo(X(i),Y(v));on=true}else g.lineTo(X(i),Y(v))}g.stroke();g.lineWidth=1});
 const sz=Math.max(3,Math.min(6,bw*1.2));
 TR.forEach(x=>{if(x.a<0&&x.b<0)return;const col=x.net>0?'#3fb950':'#f85149',a=Math.max(x.a,0),b=Math.max(x.b,0);
  if(Math.max(a,b)<start||Math.min(a,b)>=end)return;const xa=X(a),xb=X(b);
  if(x.a>=0){g.strokeStyle='rgba(248,81,73,.7)';g.setLineDash([2,3]);g.beginPath();g.moveTo(xa,Y(x.stop0));g.lineTo(xb,Y(x.stop0));g.stroke();g.setLineDash([]);
   g.strokeStyle=col;g.setLineDash([5,3]);g.beginPath();g.moveTo(xa,Y(x.p_in));g.lineTo(xb,Y(x.p_out));g.stroke();g.setLineDash([]);
   if(x.a>=start&&x.a<end){g.fillStyle=x.side==='L'?'#3fb950':'#f85149';g.beginPath();const y=Y(x.p_in);if(x.side==='L'){g.moveTo(xa-sz,y+sz*1.8);g.lineTo(xa+sz,y+sz*1.8);g.lineTo(xa,y+2)}else{g.moveTo(xa-sz,y-sz*1.8);g.lineTo(xa+sz,y-sz*1.8);g.lineTo(xa,y-2)}g.fill()}}
  if(x.b>=start&&x.b<end&&!x.open){g.fillStyle=col;g.fillRect(xb-sz/2,Y(x.p_out)-sz/2,sz,sz)}});
 const lp=C.c[N-1];if(lp>lo&&lp<hi&&V.off===0){g.strokeStyle='#8b949e';g.setLineDash([2,3]);g.beginPath();g.moveTo(L,Y(lp));g.lineTo(L+pw,Y(lp));g.stroke();g.setLineDash([]);g.fillStyle='#30363d';g.fillRect(L+pw+1,Y(lp)-7,R-2,14);g.fillStyle='#fff';g.fillText(fmt(lp),L+pw+4,Y(lp))}
 let hv=Gc.hover;if(hv>=start&&hv<end){const x=X(hv);g.strokeStyle='rgba(201,209,217,.4)';g.setLineDash([3,3]);g.beginPath();g.moveTo(x,0);g.lineTo(x,H-B);g.stroke();g.setLineDash([])}else hv=-1;
 const i=hv>=0?hv:N-1;let s=ft(C.t[i])+'  O '+fmt(C.o[i])+' H '+fmt(C.h[i])+' L '+fmt(C.l[i])+' C '+fmt(C.c[i])+'  EMA20 '+fmt(C.ema20[i])+' EMA200 '+fmt(C.ema200[i]);
 TR.forEach(x=>{if(x.a===i)s+='\n▸ вход '+(x.side==='L'?'ЛОНГ':'ШОРТ')+' '+fmt(x.p_in)+', стоп '+fmt(x.stop0)+' (риск '+x.risk.toFixed(2)+'%)';if(x.b===i&&!x.open)s+='\n■ выход '+fmt(x.p_out)+' · '+x.reason+' · Net '+sg(x.net)+'%'});
 $('chinfo').style.whiteSpace='pre-line';$('chinfo').textContent=s;
}
const cvv=document.getElementById('c'),ptrs=new Map();let sx=0,so=0,moved=false,p0=0,pn=0;
const idxAt=x=>{const r=cvv.getBoundingClientRect();return Math.max(Gc.start,Math.min(Gc.end-1,Gc.start+Math.floor((x-r.left-Gc.L)/Gc.bw)))};
cvv.addEventListener('pointerdown',e=>{cvv.setPointerCapture(e.pointerId);ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
 if(ptrs.size===1){sx=e.clientX;so=V.off;moved=false}else if(ptrs.size===2){const a=[...ptrs.values()];p0=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);pn=V.n;moved=true}});
cvv.addEventListener('pointermove',e=>{
 if(!ptrs.has(e.pointerId)){if(e.pointerType==='mouse'&&S.D&&S.D.chart){Gc.hover=idxAt(e.clientX);chart()}return}
 ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
 if(ptrs.size===2){const a=[...ptrs.values()],d=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);V.n=Math.max(20,Math.min(960,Math.round(pn*p0/Math.max(d,1))));chart();return}
 const dx=e.clientX-sx;if(Math.abs(dx)>4)moved=true;if(moved){V.off=Math.round(so+dx/Gc.bw);chart()}});
cvv.addEventListener('pointerup',e=>{if(ptrs.size===1&&!moved&&S.D&&S.D.chart){Gc.hover=idxAt(e.clientX);chart()}ptrs.delete(e.pointerId)});
cvv.addEventListener('pointercancel',e=>ptrs.delete(e.pointerId));
cvv.addEventListener('wheel',e=>{e.preventDefault();V.n=Math.max(20,Math.min(960,Math.round(V.n*(e.deltaY>0?1.15:0.87))));chart()},{passive:false});
window.addEventListener('resize',()=>{if(S.D&&S.sym!=='ALL')chart()});
(async()=>{try{const r=await fetch('/api/pairs');S.pairs=(await r.json()).pairs}catch(e){}mk();mkr();load();setInterval(load,15000)})();
</script></body></html>'''
