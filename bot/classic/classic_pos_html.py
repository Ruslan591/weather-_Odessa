HTML = r'''<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Классика · позиции</title>
<style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px system-ui,sans-serif}
.t{display:flex;flex-wrap:wrap;gap:4px;padding:4px 6px;align-items:center}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:5px 9px;font-size:12px}
button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}button.go{background:#238636;border-color:#238636;color:#fff}button.bad{background:#8b2d2d;border-color:#8b2d2d;color:#fff}
.card{margin:6px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px}
.card h4{margin:0 0 6px;font-size:13px;color:#e6edf3}
summary{cursor:pointer}
.grid{display:flex;flex-wrap:wrap;gap:14px}.grid div span{display:block;font-size:11px;color:#8b949e}.grid div b{font-size:16px}
table{border-collapse:collapse;width:100%}td,th{padding:3px 5px;text-align:right;border-bottom:1px solid #21262d;font-size:11.5px;white-space:nowrap}
td:first-child,th:first-child{text-align:left}.sc{overflow-x:auto}
.up{color:#26a69a}.dn{color:#ef5350}.fl{color:#8b949e}
canvas{display:block;width:100%;height:420px;touch-action:none}
.f{display:flex;flex-direction:column;gap:2px;margin:6px 0}.f label{font-size:11.5px;color:#8b949e}
.f input,.f select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px;font-size:13px}
.sec{margin-top:10px;font-weight:600;color:#e6edf3;border-bottom:1px solid #30363d;padding-bottom:2px}
.sm{font-size:11.5px;color:#8b949e}
input.nm{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px;font-size:13px;flex:1;min-width:120px}
</style></head><body>
<div class=card><h4 id=ttl>Классика · позиции</h4><div id=rules class=sm></div></div>
<div class=t id=pairs></div>
<div class=t id=tabs></div>
<details class=card id=cfgBox><summary><b>⚙ Конструктор правил</b> <span class=sm>— свои значения стопа, безубытка, трейлинга, входа и паттернов</span></summary>
 <div id=cfgForm></div>
 <div class=t><button id=bApply class=on>Применить к истории</button><button id=bReset>Сбросить к рекомендованным</button></div>
 <div class=t><input id=runName class=nm placeholder="Название живого прогона"><button id=bRun class=go>▶ Запустить живой прогон</button></div>
 <div id=cfgMsg class=sm></div>
 <div class=sm>«Применить» пересчитывает историю по этим правилам. «Живой прогон» фиксирует правила и копит сделки вперёд на бумаге (с текущего момента); историю можно менять, прогон не изменится.</div>
</details>
<div id=vHist>
 <div class=card><div class=grid id=sum></div></div>
 <div class=card id=cch><h4 id=chT></h4><div class=t id=rng></div>
  <div id=chinfo style="font:11.5px ui-monospace,monospace;color:#8b949e;min-height:30px;white-space:pre-line"></div><canvas id=c></canvas>
  <div class=sm>жёлтая EMA20, фиолетовая EMA200; ▲ лонг / ▼ шорт — вход, ■ — выход, красный пунктир — начальный стоп, линия вход→выход зелёная при плюсе. Время локальное. Перетаскивание — прокрутка, щипок или колесо — масштаб, тап — перекрестие. Страницу прокручивай, касаясь вне графика.</div></div>
 <div class=card><h4>Сделки</h4><div class=sc id=tbl>загрузка…</div></div>
</div>
<div id=vLive style="display:none"><div id=runs>загрузка…</div></div>
<script>
const $=id=>document.getElementById(id);
const S={sym:null,pairs:[],cfg:null,tab:'hist',D:null,runs:null};
const V={n:480,off:0},Gc={start:0,end:0,bw:5,L:4,hover:-1};
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:7;return p.toFixed(d)}
const p2=n=>String(n).padStart(2,'0');
function ft(t){const d=new Date(t);return p2(d.getDate())+'.'+p2(d.getMonth()+1)+' '+p2(d.getHours())+':'+p2(d.getMinutes())}
const sg=v=>(v>=0?'+':'')+v.toFixed(2);const cls=v=>v>0?'up':v<0?'dn':'fl';
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(j.error)throw new Error(j.error);return j}
const ST_NAME={hand_bounce:'отбой от моего канала',hand_breakout:'пробой моей границы',tl_bounce:'отбой от линии тренда',tl_breakout:'пробой треугольника',pattern:'паттерн разворота',cross200:'пересечение EMA20×EMA200',cross20:'пересечение цены и EMA20',close_ema20:'закрытие за EMA20',break_trigger:'закрытие за экстремумом паттерна',ema20_slope:'разворот EMA20',rsi_level:'RSI вернулся',macd_turn:'MACD растёт',volume:'объём',strong_body:'сильное тело свечи',break_swing:'слом структуры',pullback_ema20:'возврат к EMA20',rsi_band:'RSI в нейтральной зоне',ext_dist:'откат от экстремума 12 ч',stoch_dir:'Stoch в сторону сделки',macd_sign:'MACD по знаку сделки и растёт',ema50_slope:'наклон EMA50 в сторону',ema50_trend:'тренд по EMA50',ema50_pullback:'откат к EMA50',stochrsi_cross:'пересечение Stoch RSI в зоне'};
function stDesc(st){return (st||[]).filter(x=>x.t).map((x,i)=>{let s=ST_NAME[x.t];if(x.t==='pattern'&&x.f&&x.f!=='none')s+=' ('+x.f+')';if(x.p&&['hand_bounce','hand_breakout','tl_bounce','tl_breakout','volume','strong_body','rsi_level','ema20_slope','pullback_ema20','rsi_band','ext_dist','stoch_dir','ema50_slope','ema50_pullback','stochrsi_cross'].includes(x.t))s+=' '+x.p;if(i>0)s+=' (≤'+x.w+' св.)';return s}).join(' → ')}
function describe(c){
 const em={stages:'вход по уровням фильтра: '+(stDesc(c.stages)||'—')+(c.entry_trigger==='breakout'?'; вход по пробою экстремума сигнальной свечи (до 3 св.)':''),pattern20:'вход: после паттерна разворота — первое закрытие свечи за EMA20 (выше — лонг, ниже — шорт) в пределах '+c.arm_k+' свечей',cross200:'вход: пересечение EMA20 × EMA200',close20:'вход: закрытие свечи за EMA20 после пересечения (выше — лонг, ниже — шорт)',state20:'вход: любая свеча, закрывшаяся за EMA20, когда позиции нет'}[c.entry_mode];
 const st={prev:'стоп за экстремумом предыдущей свечи (не ближе '+c.min_stop_pct+'%'+(c.min_stop_atr?' и '+c.min_stop_atr+' ATR':'')+')',pct:'стоп '+c.min_stop_pct+'% от входа',pivot:'стоп на последнем pivot',sig3:'стоп за экстремумом 3 свечей сигнала −0.2 ATR (не ближе 0.5 ATR)'}[c.stop_mode];
 const be='при +'+c.be_trigger+'% стоп переносится на +'+c.be_lock+'% от входа'+(c.tp_r?'; цель '+c.tp_r+'R':'')+(c.max_bars?'; выход по времени через '+c.max_bars+' св.':'');
 const tr={none:'без трейлинга',pct:'трейлинг '+c.trail_dist+'% от экстремума',atr:'трейлинг '+c.trail_dist+' ATR от экстремума',pivot:'трейлинг по pivot'}[c.trail_mode];
 const pt0=(c.pat_filter&&c.pat_filter!=='none'?' (только значимые: '+({level:'у уровня',volume:'с повышенным объёмом',extreme:'на новом экстремуме',stretch:'после растяжения от EMA20','level+volume':'у уровня и с объёмом','extreme+volume':'на экстремуме и с объёмом',sweep:'со съёмом экстремума 12 ч',sweep16:'со съёмом экстремума 4 ч','sweep+volume':'со съёмом 12 ч и объёмом'}[c.pat_filter])+')':''),pt={off:'паттерны не используются',trail:'паттерн разворота включает трейлинг под минимумом (лонг) / максимумом (шорт) предыдущей свечи, не хуже безубытка',exit:'паттерн закрывает позицию при плюсе ≥ '+c.pat_min+'%'}[c.pat_mode]+(c.pat_mode!=='off'||c.entry_mode==='pattern20'?pt0:'');
 return [c.tf,em,c.rev_exit?'обратный сигнал закрывает позицию':'обратный сигнал позицию не закрывает',st,be,tr,pt,'комиссия '+c.fee+'% за сторону',(c.stake_base?'ставка '+({fixed:'фиксированная',fixed_profit:'фиксированная + накопленный профит'}[c.stake_mode]||'')+' '+c.stake_base+' $ (мин. '+c.stake_min+' $)'+(c.martingale&&c.martingale!=='off'?', мартингейл: '+({double:'удвоение',double_plus:'удвоение + '+c.mart_pct+'% убытка предыдущей'}[c.martingale]||'')+(c.mart_max?' (до '+c.mart_max+' увеличений подряд)':''):''):'')].filter(Boolean).join('; ')+'.';
}
const FIELDS=[
 {k:'tf',l:'Таймфрейм',t:'sel',o:[['1m','1 минута'],['3m','3 минуты'],['5m','5 минут'],['15m','15 минут'],['30m','30 минут'],['1h','1 час'],['2h','2 часа'],['4h','4 часа'],['6h','6 часов'],['8h','8 часов'],['12h','12 часов'],['1d','1 день']]},
 {sec:'Вход'},
 {k:'entry_mode',l:'Правило входа',t:'sel',o:[['stages','уровни фильтра (редактор ниже)'],['pattern20','после паттерна разворота: первое закрытие за EMA20'],['cross200','пересечение EMA20 × EMA200'],['close20','закрытие свечи за EMA20 после пересечения'],['state20','любая свеча, закрывшаяся за EMA20, когда позиции нет']]},
 {stg:1},
 {k:'arm_k',l:'Сколько свечей ждать закрытия за EMA20 после паттерна (для входа «после паттерна»)',t:'num'},
 {k:'pat_filter',l:'Какие паттерны считать значимыми',t:'sel',o:[['none','все'],['level','только у уровня (pivot ±0.5 ATR)'],['volume','только с объёмом ≥1.5× среднего'],['extreme','только на новом экстремуме (12 ч на 15m)'],['stretch','только после растяжения ≥1.5 ATR от EMA20'],['level+volume','у уровня и с объёмом'],['extreme+volume','на экстремуме и с объёмом'],['sweep','только со съёмом экстремума 12 ч (ложный пробой и возврат)'],['sweep16','только со съёмом экстремума 4 ч'],['sweep+volume','со съёмом 12 ч и объёмом']]},
 {k:'rev_exit',l:'Обратный сигнал входа закрывает позицию (разворот)',t:'chk'},
 {k:'entry_trigger',l:'Как входить после сигнала',t:'sel',o:[['open','по открытию следующей свечи'],['breakout','по пробою экстремума сигнальной свечи (ждать до 3 свечей)']]},
 {sec:'Начальный стоп'},
 {k:'stop_mode',l:'Правило стопа',t:'sel',o:[['prev','за экстремумом предыдущей свечи'],['pct','фиксированный процент от входа'],['pivot','на последнем подтверждённом pivot'],['sig3','за экстремумом 3 свечей сигнала −0.2 ATR, не ближе 0.5 ATR']]},
 {k:'min_stop_pct',l:'Не ближе, % от входа («предыдущая свеча») / размер стопа, % («фиксированный»)',t:'num'},
 {k:'min_stop_atr',l:'Не ближе, ATR (0 — не использовать)',t:'num'},
 {sec:'Цель'},
 {k:'tp_r',l:'Фиксированная цель, кратная риску R (0 — нет)',t:'num'},
 {k:'max_bars',l:'Выход по времени: закрыть по закрытию свечи через столько свечей после входа (0 — нет)',t:'num'},
 {sec:'Безубыток'},
 {k:'be_trigger',l:'Точка перехода в безубыток: при какой прибыли, %',t:'num'},
 {k:'be_lock',l:'Размер безубытка: стоп переносится на вход ± %',t:'num'},
 {sec:'Трейлинг после безубытка'},
 {k:'trail_mode',l:'Правило трейлинга',t:'sel',o:[['none','нет'],['pct','на расстоянии, % от экстремума'],['atr','на расстоянии, ATR от экстремума'],['pivot','по pivot']]},
 {k:'trail_dist',l:'Расстояние трейлинга (% или ATR по выбранному правилу)',t:'num'},
 {sec:'Свечные паттерны разворота'},
 {k:'pat_mode',l:'Что делает паттерн (против позиции)',t:'sel',o:[['off','ничего'],['trail','включает трейлинг под минимумом/максимумом предыдущей свечи (не хуже безубытка)'],['exit','закрывает позицию, если плюс не меньше порога']]},
 {k:'pat_min',l:'Порог плюса для закрытия по паттерну, %',t:'num'},
 {sec:'Нарисованные мной линии'},
 {k:'hand_forward',l:'Торговать по моим линиям только после момента рисования (выкл — прогнать на истории; это с подглядыванием: линии нарисованы задним числом)',t:'chk'},
 {sec:'Период выборки (даты по UTC)'},
 {k:'period_from',l:'С даты (пусто — по часам ниже)',t:'date'},
 {k:'period_to',l:'По дату включительно (пусто — до сейчас)',t:'date'},
 {sec:'Размер ставки (бумага)'},
 {k:'stake_mode',l:'Ставка',t:'sel',o:[['fixed','фиксированная'],['fixed_profit','фиксированная + накопленный профит (реинвест)']]},
 {k:'stake_base',l:'Базовая ставка, USDT',t:'num'},
 {k:'stake_min',l:'Минимальная ставка, USDT (меньше не ставим)',t:'num'},
 {k:'martingale',l:'Мартингейл после убыточной сделки',t:'sel',o:[['off','нет'],['double','удвоение ставки'],['double_plus','удвоение + % от убытка предыдущей сделки']]},
 {k:'mart_pct',l:'Для «удвоение + %»: сколько % от убытка предыдущей сделки добавить',t:'num'},
 {k:'mart_max',l:'Макс. число увеличений подряд (0 — без ограничения)',t:'num'},
 {sec:'Издержки и показ'},
 {k:'fee',l:'Комиссия за сторону, %',t:'num'},
 {k:'window_h',l:'Показывать сделки за последние, часов (если период задан — не используется, кроме «по» без «с»: тогда это длина периода)',t:'num'},
];
const ST_OPT=[['','— пусто, уровень пропускается —'],['pattern','ТРИГГЕР: свечной паттерн разворота'],['hand_bounce','ТРИГГЕР: отбой от моего канала/флэта, нарисованного на 18093 (P — допуск касания в ATR, 0.3)'],['hand_breakout','ТРИГГЕР: пробой границы моей структуры (канал/флэт/треугольник; P — запас в ATR, 0.2)'],['tl_bounce','ТРИГГЕР: отбой от авто-линии тренда в канале или флэте (P — допуск касания в ATR, умолч. 0.3)'],['tl_breakout','ТРИГГЕР: пробой треугольника (P — запас за линией в ATR, умолч. 0.2)'],['cross200','ТРИГГЕР: пересечение EMA20 × EMA200'],['cross20','ТРИГГЕР: цена закрылась по другую сторону EMA20'],['close_ema20','закрытие свечи за EMA20 (выше — лонг, ниже — шорт)'],['break_trigger','закрытие за экстремумом свечи-триггера'],['ema20_slope','EMA20 развернулась (P — за сколько свечей, по умолч. 3)'],['rsi_level','RSI вернулся выше P (лонг) / ниже 100−P (шорт), по умолч. 45'],['macd_turn','гистограмма MACD растёт 2 свечи подряд (лонг) / падает (шорт)'],['volume','объём свечи ≥ P × среднего за 20 (по умолч. 1.2)'],['strong_body','тело свечи ≥ P ATR в сторону входа (по умолч. 0.8)'],['break_swing','закрытие за последним pivot-экстремумом (слом структуры)'],['pullback_ema20','возврат к EMA20: цена в пределах P ATR от неё (по умолч. 0.9)'],['rsi_band','RSI в нейтральной зоне 49±P (по умолч. 9, т.е. 40–58)'],['ext_dist','расстояние от экстремума 12 ч в сторону сделки от P до P+2.1 ATR (по умолч. 2.4–4.5)'],['stoch_dir','Stochastic(14) в сторону сделки: лонг выше P, шорт ниже 100−P (по умолч. 50)'],['macd_sign','гистограмма MACD по знаку сделки и растёт'],['ema50_slope','EMA50 наклонена в сторону сделки (P — за сколько свечей, по умолч. 5)'],['ema50_trend','тренд: цена по сторону EMA50 и EMA50 не направлена против сделки (5 св.)'],['ema50_pullback','откат: за 6 св. цена подходила к EMA50 ближе P ATR (по умолч. 0.8)'],['stochrsi_cross','Stoch RSI (3,3,14,14): K пересекла D в зоне <P / >100−P за 3 св. (по умолч. 20)']];
const PF_OPT=[['none','все паттерны'],['level','только у уровня'],['volume','только с объёмом'],['extreme','только на новом экстремуме'],['stretch','только после растяжения от EMA20'],['level+volume','у уровня и с объёмом'],['extreme+volume','на экстремуме и с объёмом'],['sweep','со съёмом экстремума 12 ч'],['sweep16','со съёмом экстремума 4 ч'],['sweep+volume','со съёмом 12 ч и объёмом']];
function stageForm(){let h='<div class=sec>Фильтр входа по уровням</div><div class=sm>Работает при правиле входа «уровни фильтра». Первый непустой уровень — триггер, остальные — подтверждения: каждое проверяется только после предыдущего, пустой пропускается. «Окно» — сколько свечей ждать этот уровень после предыдущего. P — параметр условия (0 — по умолчанию).</div>';
 for(let i=0;i<5;i++){h+='<div class=f><label>Уровень '+(i+1)+'</label><select id=s'+i+'_t>'+ST_OPT.map(o=>'<option value="'+o[0]+'">'+o[1]+'</option>').join('')+'</select>'+
  '<div class=t style="padding:2px 0"><span class=sm>P</span><input id=s'+i+'_p type=number step=any inputmode=decimal style="width:70px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px"> <span class=sm>окно, св.</span><input id=s'+i+'_w type=number inputmode=numeric style="width:70px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px"></div>'+
  '<select id=s'+i+'_f>'+PF_OPT.map(o=>'<option value="'+o[0]+'">'+o[1]+' (для триггера-паттерна)</option>').join('')+'</select></div>'}
 return h}
function buildForm(){
 let h='';FIELDS.forEach(f=>{
  if(f.stg){h+=stageForm();return}
  if(f.sec){h+='<div class=sec>'+f.sec+'</div>';return}
  h+='<div class=f><label for=f_'+f.k+'>'+f.l+'</label>';
  if(f.t==='sel')h+='<select id=f_'+f.k+'>'+f.o.map(o=>'<option value="'+o[0]+'">'+o[1]+'</option>').join('')+'</select>';
  else if(f.t==='chk')h+='<input type=checkbox id=f_'+f.k+' style="width:22px;height:22px">';
  else if(f.t==='date')h+='<input id=f_'+f.k+' type=date>';
  else h+='<input id=f_'+f.k+' type=number step=any inputmode=decimal>';
  h+='</div>'});
 $('cfgForm').innerHTML=h;
}
function setForm(c){const st=(c.stages||[]).slice(0,5);while(st.length<5)st.push({t:'',p:0,w:12,f:'none'});st.forEach((x,i)=>{$('s'+i+'_t').value=x.t||'';$('s'+i+'_p').value=x.p||0;$('s'+i+'_w').value=x.w||12;$('s'+i+'_f').value=x.f||'none'});FIELDS.forEach(f=>{if(f.sec||f.stg)return;const e=$('f_'+f.k);if(f.t==='chk')e.checked=!!c[f.k];else e.value=c[f.k]})}
function readForm(){const c={};c.stages=[0,1,2,3,4].map(i=>({t:$('s'+i+'_t').value,p:parseFloat($('s'+i+'_p').value)||0,w:parseInt($('s'+i+'_w').value)||12,f:$('s'+i+'_f').value}));FIELDS.forEach(f=>{if(f.sec||f.stg)return;const e=$('f_'+f.k);c[f.k]=f.t==='chk'?e.checked:f.t==='num'?parseFloat(e.value):e.value});return c}
function mkTabs(){$('tabs').innerHTML='';[['hist','История / текущие правила'],['live','Живая бумага']].forEach(([k,l])=>{const b=document.createElement('button');b.textContent=l;if(S.tab===k)b.className='on';b.onclick=()=>setTab(k);$('tabs').appendChild(b)})}
function setTab(k){S.tab=k;$('vHist').style.display=k==='hist'?'block':'none';$('vLive').style.display=k==='live'?'block':'none';mkTabs();if(k==='live')loadRuns();else load()}
function mkPairs(){$('pairs').innerHTML='';S.pairs.forEach(p=>{const b=document.createElement('button');b.textContent=p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;V.off=0;Gc.hover=-1;mkPairs();load()};$('pairs').appendChild(b)})}
function mkr(){$('rng').innerHTML='';[[192,'192 св.'],[480,'480 св.'],[960,'все 960']].forEach(([n,l])=>{const b=document.createElement('button');b.textContent=l;if(V.n===n)b.className='on';b.onclick=()=>{V.n=n;V.off=0;Gc.hover=-1;mkr();chart()};$('rng').appendChild(b)})}
async function load(){
 try{const j=await api('/api/trades?sym='+S.sym+'&bars=960');if(j.sym!==S.sym)return;S.D=j;S.cfg=j.cfg;renderHist()}catch(e){$('tbl').textContent='Ошибка: '+e.message}
}
function renderHist(){
 const D=S.D,c=D.cfg,T=D.trades,n=T.length,N=D.notional;
 const dts=ms=>new Date(ms).toISOString().slice(0,10);$('ttl').textContent='Позиции · '+D.sym+' · '+c.tf+' · '+(D.period?'период '+dts(D.period.from_ms)+' — '+dts(D.period.to_ms)+(D.period.data_from_ms>D.period.from_ms?' (данные только с '+dts(D.period.data_from_ms)+')':''):'за '+(c.window_h>=48?(c.window_h/24)+' сут':c.window_h+' ч'));
 $('rules').textContent=describe(c);
 const w=T.filter(x=>x.net>0).length,s=T.reduce((a,x)=>a+x.net,0),sp=s*N/100,gs=T.reduce((a,x)=>a+x.gross,0);
 const best=n?Math.max(...T.map(x=>x.net)):0,worst=n?Math.min(...T.map(x=>x.net)):0,be=T.filter(x=>x.be).length,op=T.filter(x=>x.open).length;
 const TS=T.slice().sort((a,b)=>a.t_out-b.t_out);let cum=0,pk=0,mdd=0,ddFrom=0,ddTo=0,pkT=TS.length?TS[0].t_in:0,strk=0,sNet=0,worstS=0,worstSnet=0;
TS.forEach(x=>{cum+=x.net;if(cum>pk){pk=cum;pkT=x.t_out}if(pk-cum>mdd){mdd=pk-cum;ddFrom=pkT;ddTo=x.t_out}
 if(x.net<=0){strk++;sNet+=x.net;if(strk>worstS||(strk===worstS&&sNet<worstSnet)){worstS=strk;worstSnet=sNet}}else{strk=0;sNet=0}});
const dd=ms=>{const d=new Date(ms).toISOString();return d.slice(8,10)+'.'+d.slice(5,7)};
const ddRows=[['Макс. просадка (по закрытым сделкам)',n?'<span class="'+cls(-mdd)+'" style="display:inline;font-size:16px">'+(mdd>0?'-'+mdd.toFixed(2)+'%</span> ('+dd(ddFrom)+' → '+dd(ddTo)+')':'0%</span>'):'—'],['Худшая серия убытков',n?worstS+' подряд / '+sg(worstSnet)+'%':'—'],['Net / макс. просадка',mdd>0?(s/mdd).toFixed(2):'—']];
const M=D.money||{profit:0,max_stake:0,max_dd:0,avg_stake:0};const moneyRows=[['Профит, $ (по ставкам)','<span class="'+cls(M.profit)+'" style="display:inline;font-size:16px">'+sg(M.profit)+' $</span>'],['Ставка: макс. / средняя, $',M.max_stake.toFixed(2)+' / '+M.avg_stake.toFixed(2)],['Макс. просадка, $','-'+M.max_dd.toFixed(2)]];
$('sum').innerHTML=moneyRows.concat([['Сделок',n],['Прибыльных',n?w+' ('+Math.round(w/n*100)+'%)':'—'],['Сумма Net %','<span class="'+cls(s)+'" style="display:inline;font-size:16px">'+sg(s)+'%</span>'],['Net, USDT (на '+N+')','<span class="'+cls(sp)+'" style="display:inline;font-size:16px">'+sg(sp)+'</span>'],['До комиссий %',sg(gs)+'%'],['Дошли до БУ',be+' из '+n],['Лучшая / худшая',sg(best)+' / '+sg(worst)],['Открытых',op]]).concat(ddRows).concat(D.period?(()=>{const sp0=D.period.from_ms+0.6*(D.period.to_ms-D.period.from_ms),A=T.filter(x=>x.t_in<sp0),B=T.filter(x=>x.t_in>=sp0),sa=A.reduce((a,x)=>a+x.net,0),sb=B.reduce((a,x)=>a+x.net,0);return [['Подбор (первые 60%): сделок / Net %',A.length+' / '+sg(sa)+'%'],['Проверка (последние 40%): сделок / Net %',B.length+' / '+sg(sb)+'%']]})():[]).map(x=>'<div><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join('');
 let h='<table><tr><th>Сторона</th><th>Вход</th><th>Цена</th><th>Стоп0</th><th>Риск%</th><th>Выход</th><th>Цена</th><th>Причина</th><th>Net%</th><th>MFE</th><th>MAE</th><th>Ставка $</th><th>$</th></tr>';
 T.slice().sort((a,b)=>b.t_in-a.t_in).forEach(x=>{h+='<tr><td class="'+(x.side==='L'?'up':'dn')+'">'+(x.side==='L'?'ЛОНГ':'ШОРТ')+'</td><td>'+ft(x.t_in)+'</td><td>'+fmt(x.p_in)+'</td><td>'+fmt(x.stop0)+'</td><td>'+x.risk.toFixed(2)+'</td><td>'+(x.open?'—':ft(x.t_out))+'</td><td>'+(x.open?fmt(x.p_out)+' (тек.)':fmt(x.p_out))+'</td><td>'+x.reason+(x.be&&x.reason!=='безубыток'?' ✓БУ':'')+'</td><td class="'+cls(x.net)+'"><b>'+sg(x.net)+'</b></td><td>'+x.mfe.toFixed(2)+'</td><td>'+x.mae.toFixed(2)+'</td><td>'+(x.stake!=null?x.stake.toFixed(2):'—')+'</td><td class="'+cls(x.usd||0)+'"><b>'+(x.usd!=null?sg(x.usd):'—')+'</b></td></tr>'});
 $('tbl').innerHTML=n?h+'</table>':'За выбранный период сигналов не было';
 $('chT').textContent=D.sym+' · '+c.tf;chart();
}
function runCard(r){
 const st=r.stats,N=S.runs?S.notional:100,act=r.stop_ms==null;
 let h='<div class=card><h4>#'+r.id+' · '+r.name+' · '+r.sym+' · '+(act?'<span class=up>идёт</span>':'<span class=fl>остановлен '+ft(r.stop_ms)+'</span>')+'</h4>';
 h+='<div class=sm>с '+ft(r.start_ms)+' · '+describe(r.cfg)+'</div>';
 const wr=st.n?Math.round(st.win/st.n*100)+'%':'—',sp=st.net*N/100;
 h+='<div class=grid style="margin-top:6px">'+[['Сделок',st.n+(st.open?' (открыта '+st.open+')':'')],['Прибыльных',wr],['Net %','<span class="'+cls(st.net)+'" style="display:inline;font-size:16px">'+sg(st.net)+'%</span>'],['Net, USDT (на '+N+')',sg(sp)],['До комиссий %',sg(st.gross)+'%']].concat(st.money?[['Профит, $ (по ставкам)','<span class="'+cls(st.money.profit)+'" style="display:inline;font-size:16px">'+sg(st.money.profit)+' $</span>'],['Макс. ставка, $',st.money.max_stake.toFixed(2)],['Макс. просадка, $','-'+st.money.max_dd.toFixed(2)]]:[]).map(x=>'<div><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join('')+'</div>';
 h+='<details style="margin-top:6px"><summary class=sm>Сделки ('+r.trades.length+')</summary><div class=sc>';
 if(r.trades.length){h+='<table><tr><th>Сторона</th><th>Вход</th><th>Цена</th><th>Стоп0</th><th>Выход</th><th>Цена</th><th>Причина</th><th>Net%</th><th>Ставка $</th><th>$</th></tr>';
  r.trades.slice().sort((a,b)=>b.t_in-a.t_in).forEach(x=>{h+='<tr><td class="'+(x.side==='L'?'up':'dn')+'">'+(x.side==='L'?'ЛОНГ':'ШОРТ')+'</td><td>'+ft(x.t_in)+'</td><td>'+fmt(x.p_in)+'</td><td>'+fmt(x.stop0)+'</td><td>'+(x.open?'—':ft(x.t_out))+'</td><td>'+(x.open?fmt(x.p_out)+' (тек.)':fmt(x.p_out))+'</td><td>'+x.reason+'</td><td class="'+cls(x.net)+'"><b>'+sg(x.net)+'</b></td><td>'+(x.stake!=null?x.stake.toFixed(2):'—')+'</td><td class="'+cls(x.usd||0)+'"><b>'+(x.usd!=null?sg(x.usd):'—')+'</b></td></tr>'});h+='</table>'}else h+='<div class=sm>пока сделок нет</div>';
 h+='</div></details><div class=t>'+(act?'<button class=bad onclick="runAct(\'stop\','+r.id+')">■ Остановить</button>':'')+'<button onclick="runAct(\'delete\','+r.id+')">Удалить</button></div></div>';
 return h;
}
function renderRuns(){const R=S.runs||[];$('runs').innerHTML=R.length?R.slice().reverse().map(runCard).join(''):'<div class=card>Прогонов пока нет. Задай правила в конструкторе и нажми «Запустить живой прогон».</div>'}
async function loadRuns(){try{const j=await api('/api/runs');S.runs=j.runs;S.notional=j.notional;renderRuns()}catch(e){$('runs').textContent='Ошибка: '+e.message}}
async function runAct(a,id){if(a==='delete'&&!confirm('Удалить прогон #'+id+'?'))return;if(a==='stop'&&!confirm('Остановить прогон #'+id+'? Открытая позиция будет закрыта по текущей цене.'))return;try{const j=await api('/api/runs',{action:a,id:id});S.runs=j.runs;S.notional=j.notional;renderRuns()}catch(e){alert(e.message)}}
function chart(){
 const C=S.D&&S.D.chart;if(!C)return;const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=420;
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
 $('chinfo').textContent=s;
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
window.addEventListener('resize',()=>{if(S.D&&S.tab==='hist')chart()});
$('bApply').onclick=async()=>{try{const j=await api('/api/config',{config:readForm()});S.cfg=j.config;setForm(j.config);$('cfgMsg').textContent='Применено, история пересчитана';load()}catch(e){$('cfgMsg').textContent='Ошибка: '+e.message}};
$('bReset').onclick=async()=>{try{const j=await api('/api/config',{reset:true});S.cfg=j.config;setForm(j.config);$('cfgMsg').textContent='Сброшено к рекомендованным';load()}catch(e){$('cfgMsg').textContent='Ошибка: '+e.message}};
$('bRun').onclick=async()=>{try{const j=await api('/api/runs',{action:'start',name:$('runName').value||('Прогон '+S.sym),sym:S.sym,config:readForm()});S.runs=j.runs;S.notional=j.notional;$('cfgMsg').textContent='Прогон запущен';$('cfgBox').open=false;setTab('live')}catch(e){$('cfgMsg').textContent='Ошибка: '+e.message}};
(async()=>{buildForm();mkTabs();mkr();
 try{const r=await api('/api/pairs');S.pairs=r.pairs}catch(e){S.pairs=['ZECUSDT']}
 S.sym=S.pairs[0];mkPairs();
 try{const c=await api('/api/config');S.cfg=c.config;setForm(c.config)}catch(e){}
 load();setInterval(()=>{if(S.tab==='hist')load();else loadRuns()},15000)})();
</script></body></html>'''
