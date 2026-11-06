# -*- coding: utf-8 -*-
"""Патч 10в (2026-11-06): панель 18091, вкладка Claude: блок «Настройки выхода» (отдельно для каждой вкладки-счёта: Классика / AFD / Регрессия / AFD+регрессия),
расстояния от текущей цены до стопа, целей, БУ-порога, трейлинга, ликвидации (цена · % · ATR) у открытых позиций и до заявки/стопа/цели у отложенных заявок.
Идемпотентный. Запуск: patch_exit_ui.py <каталог classic> . Только вкладка Claude (clCard0, clOrders), остальные вкладки не трогаются."""
import sys, os
fh = os.path.join(sys.argv[1], "classic_pos_html.py"); h = open(fh, encoding="utf-8").read()
if "clExitBox" in h: print("panel already patched"); sys.exit(0)
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:90]); return s.replace(old, new)

JS = r"""
var CLX_ST='background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:4px;';
function clxSet(path,el){if(!S.clx)return;const k=path.split('.');const v=el.type==='checkbox'?(el.checked?1:0):el.value;if(k.length===1)S.clx[k[0]]=v;else S.clx[k[0]][k[1]]=v}
if(!window._clxL){window._clxL=1;const f=e=>{const el=e.target;if(el&&el.dataset&&el.dataset.x)clxSet(el.dataset.x,el)};document.addEventListener('input',f);document.addEventListener('change',f)}
function clxV(path){const k=path.split('.');return k.length===1?S.clx[k[0]]:S.clx[k[0]][k[1]]}
function clxN(path,w){const v=clxV(path);return `<input data-x=${path} type=text inputmode=decimal value="${v==null?'':v}" style="width:${w||54}px;${CLX_ST}">`}
function clxSel(path,opts){const v=String(clxV(path));return `<select data-x=${path} style="${CLX_ST}">`+opts.map(o=>`<option value=${o[0]}${v===o[0]?' selected':''}>${o[1]}</option>`).join('')+`</select>`}
function clxChk(path,label){return `<label><input data-x=${path} type=checkbox${clxV(path)?' checked':''}> ${label}</label>`}
function clxSum(X){const U={r:'R',pct:'%',atr:'ATR'},ss=v=>(v>=0?'+':'')+v;
const st=X.stop.mode==='rule'?'по заявке':X.stop.val+' '+U[X.stop.mode]+' от входа';
const BT={r:v=>'+'+v+'R',pct:v=>'+'+v+'%',atr:v=>'+'+v+' ATR',tp:v=>v+'% пути к цели',tp1:v=>'после частичной цели'};
const be=X.be.on?BT[X.be.trig](X.be.val)+' → стоп '+ss(X.be.lock_val)+(X.be.lock_unit==='r'?'R':'%'):'выкл';
const TS={be:'после БУ',r:'с +'+X.trail.start_val+'R',pct:'с +'+X.trail.start_val+'%',atr:'с +'+X.trail.start_val+' ATR',tp1:'после частичной цели',now:'сразу'};
const tr=X.trail.on?TS[X.trail.start]+', дистанция '+X.trail.val+(X.trail.unit==='atr'?' ATR 1h':'%'):'выкл';
const t1=X.tp1.on?X.tp1.part+'% позиции на +'+X.tp1.val+' '+U[X.tp1.unit]:'нет';
const tp=X.tp.mode==='rule'?'по заявке':X.tp.mode==='none'?'нет':'+'+X.tp.val+' '+U[X.tp.mode];
return 'стоп: '+st+' · БУ: '+be+' · трейлинг: '+tr+' · частичная цель: '+t1+' · цель: '+tp+' · перенос на S/R: '+(X.sr.on?'да':'нет')}
function clExitBox(C){const X=C.exit_cfg;if(!X)return '';const ac=S.cla||'';if(!S.clx||S.clxAcct!==ac){S.clx=JSON.parse(JSON.stringify(X));S.clxAcct=ac}
const R=(t,h)=>`<div style="margin-top:8px"><b>${t}</b><br>${h}</div>`;
const UN=[['r','R'],['pct','%'],['atr','ATR 1h']];
return `<details data-k=acl_exit style="margin-top:8px"><summary class=sm><b>Настройки выхода</b> этой вкладки (для всех её позиций): ${clxSum(X)}</summary><div class=sm style="margin-top:6px;color:#8b949e">Каждая вкладка (Классика, AFD, Регрессия, AFD + регрессия) хранит свои настройки. Действуют на все открытые и новые позиции вкладки. R — расстояние от входа до начального стопа, ATR — ATR 1h позиции, проценты — от цены входа. Стоп только подтягивается в сторону прибыли, ослабить его уже стоящий настройка не может. Позиции с ручным стопом (кнопка у позиции) автоматически не двигаются.</div>`
+R('Стоп',clxSel('stop.mode',[['rule','как в заявке'],['pct','фикс. % от входа'],['atr','фикс. ATR 1h от входа']])+' '+clxN('stop.val')+' <span style="color:#8b949e">(число - когда режим не «как в заявке»; ставится при исполнении заявки, у открытых - кнопкой «Применить стоп к открытым»)</span>')
+R('Безубыток',clxChk('be.on','включён')+'<br>переход, когда цена прошла: '+clxSel('be.trig',[['r','+R'],['pct','+%'],['atr','+ATR 1h'],['tp','% пути к цели'],['tp1','после частичной цели']])+' '+clxN('be.val')+'<br>стоп переносится на вход '+clxN('be.lock_val')+' '+clxSel('be.lock_unit',[['pct','%'],['r','R']])+' <span style="color:#8b949e">(+ в сторону прибыли, чтобы покрыть комиссию)</span>')
+R('Трейлинг',clxChk('trail.on','включён')+'<br>старт: '+clxSel('trail.start',[['be','после БУ'],['r','с +R'],['pct','с +%'],['atr','с +ATR 1h'],['tp1','после частичной цели'],['now','сразу']])+' '+clxN('trail.start_val')+' <span style="color:#8b949e">(число для вариантов с +R, +%, +ATR)</span><br>дистанция: '+clxN('trail.val')+' '+clxSel('trail.unit',[['atr','ATR 1h'],['pct','% от входа']]))
+R('Частичная цель',clxChk('tp1.on','включена')+'<br>на расстоянии '+clxN('tp1.val')+' '+clxSel('tp1.unit',UN)+' закрыть '+clxN('tp1.part',44)+'% позиции <span style="color:#8b949e">(остальное идёт к конечной цели или по трейлингу)</span>')
+R('Конечная цель (остаток)',clxSel('tp.mode',[['rule','как в заявке'],['r','R'],['pct','%'],['atr','ATR 1h'],['none','нет цели']])+' '+clxN('tp.val')+' <span style="color:#8b949e">(без цели остаток закрывается стопом, трейлингом или по времени)</span>')
+R('Перенос стопа на уровень',clxChk('sr.on','после БУ подтягивать стоп на подтверждённую линию поддержки/сопротивления'))
+R('Время жизни позиции, ч',clxN('maxh',60)+' <span style="color:#8b949e">(пусто - как у позиции, 0 - без лимита)</span>')
+`<div style="margin-top:10px"><button class=go onclick="clxSave()">Сохранить</button> <button onclick="clxApply()">Применить стоп к открытым</button> <button onclick="clxReset()">Стандарт</button></div></details>`}
async function clxSave(){if(S.clbusy)return;S.clbusy=1;try{const j=await api('/api/claude',{action:'exit_cfg_set',cfg:S.clx});if(j.error)alert(j.error);else{S.cl=j;S.clx=null;alert('Сохранено. Действует на все позиции этой вкладки.')}}catch(e){alert(e.message)}S.clbusy=0;renderRuns()}
async function clxReset(){if(S.clbusy||!confirm('Вернуть стандартные настройки выхода для этой вкладки?'))return;S.clbusy=1;try{const j=await api('/api/claude',{action:'exit_cfg_reset'});if(j.error)alert(j.error);else{S.cl=j;S.clx=null}}catch(e){alert(e.message)}S.clbusy=0;renderRuns()}
async function clxApply(){if(S.clbusy||!confirm('Применить режим стопа к открытым позициям вкладки? Не трогаются позиции в безубытке, с частичной целью и с ручным стопом.'))return;S.clbusy=1;try{const j=await api('/api/claude',{action:'exit_apply_stop'});if(j.error)alert(j.error);else{S.cl=j;alert('Изменён стоп у позиций: '+(j.applied||0))}}catch(e){alert(e.message)}S.clbusy=0;renderRuns()}
function clDv(px,v,atr){if(v==null||!(v>0))return '—';const d=v-px,pc=d/px*100,sg2=x=>(x>=0?'+':'')+x.toFixed(2);return fmt(v)+' · '+sg2(pc)+'% · '+(atr>0?sg2(d/atr)+' ATR':'—')}
function clDist(p){const e=p.eff,X=(S.cl||{}).exit_cfg;if(!e||!X)return '';const px=p.px,a=e.atr1h,row=(n,v)=>`<tr><td style="color:#8b949e;padding:1px 6px 1px 0">${n}</td><td>${v}</td></tr>`;let t='';
t+=row('Стоп'+(p.stop_manual?' (ручной)':(p.armed||p.trail_act?' (подтянут)':'')),clDv(px,p.stop,a));
t+=row('Цель',e.tp==null?'нет цели':clDv(px,e.tp,a));
if(X.tp1.on&&!p.tp1_done)t+=row('Частичная цель ('+X.tp1.part+'%)',e.tp1==null?'не задана (должна быть ближе конечной)':clDv(px,e.tp1,a));
if(!p.armed)t+=row('Порог безубытка',!X.be.on?'выключен':(e.be_px!=null?clDv(px,e.be_px,a):'после частичной цели'));
if(p.trail_act)t+=row('Трейлинг',`работает, дистанция ${fmt(e.trail_dist)} · ${(e.trail_dist/px*100).toFixed(2)}% · ${a>0?(e.trail_dist/a).toFixed(2)+' ATR':'—'}`);else t+=row('Трейлинг',!X.trail.on?'выключен':(e.trail_px!=null?'старт: '+clDv(px,e.trail_px,a):(X.trail.start==='be'?'старт после безубытка':X.trail.start==='tp1'?'старт после частичной цели':'старт сразу')));
t+=row('Ликвидация',clDv(px,e.liq,a));
let s='';if(p.parts&&p.parts.length){const f=p.parts.reduce((x,y)=>x+y.frac,0),u=p.parts.reduce((x,y)=>x+(y.usd||0),0);s=`<div class=sm style="margin-top:3px;color:#3fb950">Закрыто частями ${Math.round(f*100)}% · зафиксировано ${smoney(u)} · в позиции осталось ${Math.round((p.rem==null?1:p.rem)*100)}%</div>`}
return `<div class=sm style="margin-top:6px;color:#8b949e">Расстояния от цены сейчас (цена · % · ATR 1h):</div><table style="font-size:12px;border-collapse:collapse">${t}</table>`+s}
function clOrdDist(o){const px=+o.px,a=+o.atr;return `<div class=sm style="margin-top:4px;color:#8b949e">Расстояния от цены сейчас (цена · % · ATR 5m): заявка ${clDv(px,+o.price,a)}; стоп ${clDv(px,+o.stop,a)}; цель ${clDv(px,+o.tp,a)}</div>`}
"""
h = rep(h, "function clCard(){return clAcctBar()+clCard0()}", JS.strip("\n") + "\nfunction clCard(){return clAcctBar()+clCard0()}")
h = rep(h, "h+=clOrders(C);if(C.open.length)", "h+=clExitBox(C)+clOrders(C);if(C.open.length)")
h = rep(h, "+p.r_now+'R'+clMan(p)+clStopBox(p)+'", "+p.r_now+'R'+clMan(p)+clStopBox(p)+clDist(p)+'")
h = rep(h, "' · цель '+fmt(p.tp)+' · ликвидация '", "' · цель '+(p.eff&&p.eff.tp==null?'нет':fmt(p.tp))+' · ликвидация '")
h = rep(h, "'%)<div style=\"margin-top:8px\">'+clZOChart(o,'o'+o.id)", "'%)'+clOrdDist(o)+'<div style=\"margin-top:8px\">'+clZOChart(o,'o'+o.id)")
h = rep(h, "async function clSetAcct(k){S.cla=k;S.clpv=null;", "async function clSetAcct(k){S.cla=k;S.clx=null;S.clpv=null;")
open(fh, "w", encoding="utf-8").write(h); print("patched panel")
