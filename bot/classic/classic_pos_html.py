HTML = r'''<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1"><title>Классика · позиции</title>
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
canvas{display:block;width:100%;height:340px}
</style></head><body>
<div class=card><h4 id=ttl>Позиции за 24 ч</h4><div id=rules style="color:#8b949e;font-size:11.5px"></div></div>
<div class=t id=pairs></div>
<div class=card><div class=grid id=sum></div></div>
<div class=card id=cch style="display:none"><h4 id=chT></h4><canvas id=c></canvas><div style="color:#8b949e;font-size:11px">жёлтая EMA20, фиолетовая EMA200; ▲ лонг / ▼ шорт — вход, ■ — выход, красный пунктир — начальный стоп, линия вход→выход зелёная при плюсе. Время локальное.</div></div>
<div class=card><h4>Сделки</h4><div class=sc id=tbl>загрузка…</div></div>
<div class=card id=cpair style="display:none"><h4>По парам</h4><div class=sc id=pp></div></div>
<script>
const $=id=>document.getElementById(id);
const S={sym:'ALL',pairs:[],D:null};
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:7;return p.toFixed(d)}
const p2=n=>String(n).padStart(2,'0');
function ft(t){const d=new Date(t);return p2(d.getDate())+'.'+p2(d.getMonth()+1)+' '+p2(d.getHours())+':'+p2(d.getMinutes())}
const sg=v=>(v>=0?'+':'')+v.toFixed(2);const cls=v=>v>0?'up':v<0?'dn':'fl';
function mk(){$('pairs').innerHTML='';['ALL'].concat(S.pairs).forEach(p=>{const b=document.createElement('button');b.textContent=p==='ALL'?'ВСЕ':p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;mk();load()};$('pairs').appendChild(b)})}
async function load(){
 try{const r=await fetch('/api/trades?sym='+S.sym);const j=await r.json();if(j.error){$('tbl').textContent='Ошибка: '+j.error;return}
  if(j.sym!==S.sym)return;S.D=j;render()}catch(e){$('tbl').textContent='Ошибка: '+e}
}
function render(){
 const D=S.D,P=D.params;
 $('ttl').textContent='Позиции за '+P.window_h+' ч · '+(S.sym==='ALL'?'все пары':S.sym)+' · '+P.tf;
 $('rules').textContent='Вход: пересечение EMA20 × EMA200 (лонг и шорт), по открытию следующей свечи. Начальный стоп — последний подтверждённый pivot. +'+P.be_trigger+'% → стоп в безубыток, далее трейлинг по pivot. Разворот при обратном пересечении. Комиссия '+P.fee+'% за сторону (учтена в Net), объём условный '+P.notional+' USDT.';
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
 else{$('cpair').style.display='none';$('cch').style.display='block';$('chT').textContent=S.sym+' · 15m · последние ~48 ч';chart()}
}
function chart(){
 const C=S.D.chart;if(!C)return;const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=340;
 cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
 const N=C.t.length,L=4,R=58,B=16,pw=W-L-R,bw=pw/(N+1);const X=i=>L+(i+0.5)*bw;
 let hi=-1e99,lo=1e99;for(let i=0;i<N;i++){hi=Math.max(hi,C.h[i]);lo=Math.min(lo,C.l[i])}
 S.D.trades.forEach(x=>{[x.stop0].forEach(v=>{if(v>lo-(hi-lo)*0.15&&v<hi+(hi-lo)*0.15){hi=Math.max(hi,v);lo=Math.min(lo,v)}})});
 const pad=(hi-lo)*0.05;hi+=pad;lo-=pad;const Y=p=>6+(hi-p)/(hi-lo)*(H-B-12);
 g.font='10px system-ui';g.textBaseline='middle';g.fillStyle='#6e7681';g.strokeStyle='#1b222c';
 for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5;g.beginPath();g.moveTo(L,Y(p));g.lineTo(L+pw,Y(p));g.stroke();g.fillText(fmt(p),L+pw+4,Y(p))}
 for(let i=0;i<N;i+=Math.round(N/6)){g.textAlign='center';g.fillText(ft(C.t[i]),X(i),H-7)}g.textAlign='left';
 for(let i=0;i<N;i++){const up=C.c[i]>=C.o[i],col=up?'#26a69a':'#ef5350',x=X(i),w=Math.max(1,bw*0.7);g.strokeStyle=g.fillStyle=col;g.beginPath();g.moveTo(x,Y(C.h[i]));g.lineTo(x,Y(C.l[i]));g.stroke();g.fillRect(x-w/2,Y(Math.max(C.o[i],C.c[i])),w,Math.max(1,Y(Math.min(C.o[i],C.c[i]))-Y(Math.max(C.o[i],C.c[i]))))}
 [['ema20','#e3b341'],['ema200','#bc8cff']].forEach(([k,c])=>{g.strokeStyle=c;g.lineWidth=1.4;g.beginPath();let on=false;for(let i=0;i<N;i++){const v=C[k][i];if(v==null){on=false;continue}if(!on){g.moveTo(X(i),Y(v));on=true}else g.lineTo(X(i),Y(v))}g.stroke();g.lineWidth=1});
 const ix=t=>{let b=-1;for(let i=0;i<N;i++){if(C.t[i]<=t)b=i}return b};
 S.D.trades.forEach(x=>{const a=ix(x.t_in),b=ix(x.t_out);if(a<0&&b<0)return;const col=x.net>0?'#3fb950':'#f85149',xa=X(Math.max(a,0)),xb=X(Math.max(b,0));
  if(a>=0){g.strokeStyle='rgba(248,81,73,.7)';g.setLineDash([2,3]);g.beginPath();g.moveTo(xa,Y(x.stop0));g.lineTo(xb,Y(x.stop0));g.stroke();g.setLineDash([]);
   g.strokeStyle=col;g.setLineDash([5,3]);g.beginPath();g.moveTo(xa,Y(x.p_in));g.lineTo(xb,Y(x.p_out));g.stroke();g.setLineDash([]);
   g.fillStyle=x.side==='L'?'#3fb950':'#f85149';g.beginPath();const y=Y(x.p_in);if(x.side==='L'){g.moveTo(xa-5,y+9);g.lineTo(xa+5,y+9);g.lineTo(xa,y+1)}else{g.moveTo(xa-5,y-9);g.lineTo(xa+5,y-9);g.lineTo(xa,y-1)}g.fill()}
  if(b>=0&&!x.open){g.fillStyle=col;g.fillRect(xb-3,Y(x.p_out)-3,6,6)}});
}
window.addEventListener('resize',()=>{if(S.D&&S.sym!=='ALL')chart()});
(async()=>{try{const r=await fetch('/api/pairs');S.pairs=(await r.json()).pairs}catch(e){}mk();load();setInterval(load,15000)})();
</script></body></html>'''
