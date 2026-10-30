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
table{border-collapse:collapse;width:100%}th.srt{cursor:pointer;user-select:none}.stk th{position:sticky;top:0;background:#161b22}td,th{padding:3px 5px;text-align:right;border-bottom:1px solid #21262d;font-size:11.5px;white-space:nowrap}
td:first-child,th:first-child{text-align:left}.sc{overflow-x:auto}
.up{color:#26a69a}.dn{color:#ef5350}.fl{color:#8b949e}
canvas{display:block;width:100%;height:420px;touch-action:none}
.f{display:flex;flex-direction:column;gap:2px;margin:6px 0}.f label{font-size:11.5px;color:#8b949e}
.f input,.f select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px;font-size:13px}
.sec{margin-top:10px;font-weight:600;color:#e6edf3;border-bottom:1px solid #30363d;padding-bottom:2px}
.sm{font-size:11.5px;color:#8b949e}.eq{font-size:28px;font-weight:700;margin:4px 0}.eq span{font-size:14px;font-weight:600}.need{margin-top:10px;padding:9px 11px;border-radius:6px;background:#16233a;border:1px solid #1f6feb;font-size:13px}.need b{font-size:18px}
input.nm{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px;font-size:13px;flex:1;min-width:120px}
.posb{border:1px solid #30363d;border-radius:8px;padding:8px 10px;margin-top:8px;background:#0d1117}
.prow{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:6px 0}.prow b{min-width:82px}.prow input,.prow select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px;font-size:13px}.prow input{flex:1;min-width:120px}
.prop{border:1px solid #30363d;border-radius:8px;padding:8px 10px;margin-top:8px;background:#0d1117}.pbt{display:flex;gap:8px;margin-top:8px}.pbt button{flex:1;padding:10px;font-size:13px}
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
 <div class=card id=cch><h4 id=chT></h4><div class=t id=rng></div><div class=t id=vbar2></div>
  <div id=chinfo style="font:11.5px ui-monospace,monospace;color:#8b949e;min-height:30px;white-space:pre-line"></div><canvas id=c></canvas>
  <div class=sm>голубые линии — канал сделки (короткий фрагмент от входа до выхода, верхняя и нижняя границы; кнопка «Каналы»); жёлтая EMA20 и фиолетовая EMA200 — по кнопке «EMA»; ▲ лонг / ▼ шорт — вход, ■ — выход, красный пунктир — начальный стоп, линия вход→выход зелёная при плюсе. Время локальное. Перетаскивание — прокрутка, щипок или колесо — масштаб, тап — перекрестие. Страницу прокручивай, касаясь вне графика.</div></div>
 <div class=card><h4>Сделки</h4><div class=sc id=tbl>загрузка…</div></div>
</div>
<div id=vLive style="display:none"><div id=runs>загрузка…</div></div>
<script>
const $=id=>document.getElementById(id);
const S={sym:null,pairs:[],cfg:null,tab:'hist',D:null,runs:null,acc:{},track:'me',sort:{}};
const LS=(k,d)=>{try{const v=localStorage.getItem(k);return v===null?d:v==='1'}catch(e){return d}},LSset=(k,v)=>{try{localStorage.setItem(k,v?'1':'0')}catch(e){}};
const V={n:480,off:0,vz:1,vo:0,vtf:'',ch:LS('cl_ch',true),ema:LS('cl_ema',false)},Gc={start:0,end:0,bw:5,L:4,hover:-1};
const TFMS={'1m':60000,'3m':180000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000,'2h':7200000,'4h':14400000,'6h':21600000,'8h':28800000,'12h':43200000,'1d':86400000};
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:7;return p.toFixed(d)}
const p2=n=>String(n).padStart(2,'0');
function ft(t){const d=new Date(t);return p2(d.getDate())+'.'+p2(d.getMonth()+1)+' '+p2(d.getHours())+':'+p2(d.getMinutes())}
const sg=v=>(v>=0?'+':'')+v.toFixed(2);const cls=v=>v>0?'up':v<0?'dn':'fl';
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(j.error)throw new Error(j.error);if(path==='/api/runs'&&j.runs){S.prop=j.proposals||S.prop;S.pairsAll=j.pairs_all||S.pairsAll;S.man=j.manual||{}}return j}
const ST_NAME={hand_both:'отбой + пробой моего канала',hand_bounce:'отбой от моего канала',hand_breakout:'пробой моей структуры',tl_both:'отбой + пробой канала робота',tl_bounce:'отбой от канала робота',tl_breakout:'пробой канала/треугольника робота',pattern:'свечной паттерн разворота',cross200:'пересечение EMA20×EMA200',cross20:'цена пересекла EMA20',cross50:'цена пересекла EMA50',close_ema20:'закрытие за EMA20',break_trigger:'закрытие за экстремумом паттерна',ema20_slope:'EMA20 развернулась',rsi_level:'RSI вернулся',macd_turn:'MACD растёт',volume:'объём выше среднего',strong_body:'сильное тело свечи',break_swing:'слом структуры',pullback_ema20:'возврат к EMA20',rsi_band:'RSI в нейтральной зоне',ext_dist:'откат от экстремума 12 ч',stoch_dir:'Stochastic в сторону сделки',macd_sign:'MACD по направлению сделки',ema50_slope:'наклон EMA50',ema50_trend:'тренд по EMA50',ema50_pullback:'возврат к EMA50',stochrsi_cross:'Stoch RSI в зоне 20/80',ema200_side:'цена по сторону EMA200'};
function stDesc(st){return (st||[]).filter(x=>x.t).map((x,i)=>{let s=ST_NAME[x.t];if(x.t==='pattern'&&x.f&&x.f!=='none')s+=' ('+x.f+')';if(x.p&&['hand_both','hand_bounce','hand_breakout','tl_both','tl_bounce','tl_breakout','volume','strong_body','rsi_level','ema20_slope','pullback_ema20','rsi_band','ext_dist','stoch_dir','ema50_slope','ema50_pullback','stochrsi_cross'].includes(x.t))s+=' '+x.p;if(i>0)s+=' (≤'+x.w+' св.)';return s}).join(' → ')}
function describe(c){
 const em={stages:'вход по уровням фильтра: '+(stDesc(c.stages)||'—')+(c.entry_trigger==='breakout'?'; вход по пробою экстремума сигнальной свечи (до 3 св.)':''),pattern20:'вход: после паттерна разворота — первое закрытие свечи за EMA20 (выше — лонг, ниже — шорт) в пределах '+c.arm_k+' свечей',cross200:'вход: пересечение EMA20 × EMA200',close20:'вход: закрытие свечи за EMA20 после пересечения (выше — лонг, ниже — шорт)',state20:'вход: любая свеча, закрывшаяся за EMA20, когда позиции нет'}[c.entry_mode];
 const st={prev:'стоп за экстремумом предыдущей свечи (не ближе '+c.min_stop_pct+'%'+(c.min_stop_atr?' и '+c.min_stop_atr+' ATR':'')+')',pct:'стоп '+c.min_stop_pct+'% от входа',pivot:'стоп на последнем pivot',sig3:'стоп за экстремумом 3 свечей сигнала −0.2 ATR (не ближе 0.5 ATR)',channel:'стоп за линией канала +'+c.ch_stop_pct+'%'+(c.ch_stop_atr?' +'+c.ch_stop_atr+' ATR':'')+(c.ch_min_stop_pct?' (не ближе '+c.ch_min_stop_pct+'%)':'')+' (для входов по линиям; иначе — за экстремумом предыдущей свечи)'}[c.stop_mode];
 const be='при +'+c.be_trigger+'% стоп переносится на +'+c.be_lock+'% от входа'+(c.be_intrabar?' (внутри свечи: если свеча взвела БУ и закрылась за стопом — выход по цене стопа в ней же)':' (по свече: стоп взводится в конце свечи)')+(c.tp_mode==='channel'?'; цель на противоположной линии канала −'+c.ch_tp_gap_pct+'%'+(c.ch_tp_gap_atr?' −'+c.ch_tp_gap_atr+' ATR':'')+(c.ch_min_rr?' (вход только при R ≥ '+c.ch_min_rr+')':'')+(c.ch_follow?', уровни следуют за линиями':', уровни фиксируются при входе'):(c.tp_r?'; цель '+c.tp_r+'R':''))+(c.max_bars?'; выход по времени через '+c.max_bars+' св.':'');
 const tr={none:'без трейлинга',pct:'трейлинг '+c.trail_dist+'% от экстремума',atr:'трейлинг '+c.trail_dist+' ATR от экстремума',pivot:'трейлинг по pivot'}[c.trail_mode];
 const pt0=(c.pat_filter&&c.pat_filter!=='none'?' (только значимые: '+({level:'у уровня',volume:'с повышенным объёмом',extreme:'на новом экстремуме',stretch:'после растяжения от EMA20','level+volume':'у уровня и с объёмом','extreme+volume':'на экстремуме и с объёмом',sweep:'со съёмом экстремума 12 ч',sweep16:'со съёмом экстремума 4 ч','sweep+volume':'со съёмом 12 ч и объёмом'}[c.pat_filter])+')':''),pt={off:'паттерны не используются',trail:'паттерн разворота включает трейлинг под минимумом (лонг) / максимумом (шорт) предыдущей свечи, не хуже безубытка',exit:'паттерн закрывает позицию при плюсе ≥ '+c.pat_min+'%'}[c.pat_mode]+(c.pat_mode!=='off'||c.entry_mode==='pattern20'?pt0:'');
 return [c.tf,em,c.rev_exit?'обратный сигнал закрывает позицию':'обратный сигнал позицию не закрывает',st,be,tr,pt,'комиссия '+c.fee+'% за сторону',(c.stake_base?'ставка '+({fixed:'фиксированная',fixed_profit:'фиксированная + накопленный профит'}[c.stake_mode]||'')+' '+c.stake_base+' $ (мин. '+c.stake_min+' $)'+(c.martingale&&c.martingale!=='off'?', мартингейл: '+({double:'удвоение',double_plus:'удвоение + '+c.mart_pct+'% убытка предыдущей'}[c.martingale]||'')+(c.mart_max?' (до '+c.mart_max+' увеличений подряд)':''):''):'')].filter(Boolean).join('; ')+'.';
}
const FIELDS=[
 {k:'tf',l:'Таймфрейм',t:'sel',o:[['1m','1 минута'],['3m','3 минуты'],['5m','5 минут'],['15m','15 минут'],['30m','30 минут'],['1h','1 час'],['2h','2 часа'],['4h','4 часа'],['6h','6 часов'],['8h','8 часов'],['12h','12 часов'],['1d','1 день']]},
 {sec:'Вход'},
 {k:'entry_mode',l:'Правило входа',t:'sel',o:[['stages','уровни фильтра (редактор ниже)'],['pattern20','после паттерна разворота: первое закрытие за EMA20'],['cross200','пересечение EMA20 × EMA200'],['close20','закрытие свечи за EMA20 после пересечения'],['state20','любая свеча, закрывшаяся за EMA20, когда позиции нет']]},
 {stg:1},
 {k:'tl_src',l:'Каналы робота: чем строить',t:'sel',o:[['old','прежний (пивоты с подтверждением 5 свечей)'],['fast','быстрый (3 точки, канал на следующей свече, пробой по закрытию, перерисовка)']]},
 {k:'fc_minw',l:'Быстрый канал: ширина не меньше, в ATR (по умолч. 1.5)',t:'num'},
 {k:'fc_maxw',l:'Быстрый канал: ширина не больше, в ATR (по умолч. 8)',t:'num'},
 {k:'tl_min_w',l:'Канал робота (прежний): ширина не меньше, в ATR (по умолч. 1.5)',t:'num'},
 {k:'tl_max_w',l:'Канал робота: ширина не больше, в ATR (по умолч. 14 — это до ~20% цены; уже — ближе стоп и цель)',t:'num'},
 {k:'arm_k',l:'Сколько свечей ждать закрытия за EMA20 после паттерна (для входа «после паттерна»)',t:'num'},
 {k:'pat_filter',l:'Какие паттерны считать значимыми',t:'sel',o:[['none','все паттерны'],['volume','только с повышенным объёмом'],['level','только у уровня поддержки/сопротивления'],['extreme','только на новом экстремуме'],['sweep','только после ложного пробоя (съём экстремума)']]},
 {k:'rev_exit',l:'Обратный сигнал входа закрывает позицию (разворот)',t:'chk'},
 {k:'entry_trigger',l:'Как входить после сигнала',t:'sel',o:[['open','по открытию следующей свечи'],['breakout','по пробою экстремума сигнальной свечи (ждать до 3 свечей)']]},
 {sec:'Начальный стоп'},
 {k:'stop_mode',l:'Правило стопа',t:'sel',o:[['prev','за экстремумом предыдущей свечи'],['pct','фиксированный процент от входа'],['pivot','на последнем подтверждённом pivot'],['sig3','за экстремумом 3 свечей сигнала с небольшим запасом (0.2 ATR), не ближе 0.5 ATR'],['channel','за линией канала + запас (для входов «отбой/пробой» по моим линиям и линиям робота)']]},
 {k:'ch_stop_pct',l:'Стоп за линией канала: запас, % от входа',t:'num'},
 {k:'ch_stop_atr',l:'Стоп за линией канала: запас, в ATR (0 — не использовать)',t:'num'},
 {k:'ch_min_stop_pct',l:'Стоп по каналу не ближе, % от входа (0 — без ограничения)',t:'num'},
 {k:'min_stop_pct',l:'Не ближе, % от входа («предыдущая свеча») / размер стопа, % («фиксированный»)',t:'num'},
 {k:'min_stop_atr',l:'Стоп не ближе, в ATR (ATR — средний размах свечи; 0 — не использовать)',t:'num'},
 {sec:'Цель'},
 {k:'tp_mode',l:'Правило цели',t:'sel',o:[['r','кратная риску R (поле ниже)'],['channel','на противоположной линии канала (только отбой по линиям; пробои пропускаются)']]},
 {k:'tp_r',l:'Фиксированная цель, кратная риску R (0 — нет)',t:'num'},
 {k:'ch_tp_gap_pct',l:'Цель по каналу: не доходить до линии, % от входа',t:'num'},
 {k:'ch_tp_gap_atr',l:'Цель по каналу: не доходить до линии, в ATR (0 — не использовать)',t:'num'},
 {k:'ch_min_rr',l:'Вход только если цель по каналу ≥ столько R (0 — без фильтра)',t:'num'},
 {k:'ch_follow',l:'Стоп и цель следуют за наклонными линиями канала (выкл — фиксируются при входе; стоп только подтягивается)',t:'chk'},
 {k:'max_bars',l:'Выход по времени: закрыть по закрытию свечи через столько свечей после входа (0 — нет)',t:'num'},
 {sec:'Безубыток'},
 {k:'be_trigger',l:'Точка перехода в безубыток: при какой прибыли, %',t:'num'},
 {k:'be_lock',l:'Размер безубытка: стоп переносится на вход ± %',t:'num'},
 {k:'be_intrabar',l:'БУ внутри свечи: если свеча дошла до триггера БУ и закрылась за БУ-стопом — выход по цене стопа в этой же свече (как стоп-ордер на бирже). Выкл — стоп взводится в конце свечи, выход по открытию следующей',t:'chk'},
 {sec:'Трейлинг после безубытка'},
 {k:'trail_mode',l:'Правило трейлинга',t:'sel',o:[['none','нет'],['pct','на расстоянии, % от экстремума'],['atr','на расстоянии в ATR (средний размах свечи) от экстремума'],['pivot','по pivot']]},
 {k:'trail_dist',l:'Расстояние трейлинга (% или ATR по выбранному правилу)',t:'num'},
 {sec:'Свечные паттерны разворота'},
 {k:'pat_mode',l:'Что делает паттерн (против позиции)',t:'sel',o:[['off','ничего'],['trail','включает трейлинг под минимумом/максимумом предыдущей свечи (не хуже безубытка)'],['exit','закрывает позицию, если плюс не меньше порога']]},
 {k:'pat_min',l:'Порог плюса для закрытия по паттерну, %',t:'num'},
 {sec:'Нарисованные мной линии'},
 {k:'hand_forward',l:'Торговать по моим линиям только после момента рисования (выкл — прогнать на истории; это с подглядыванием: линии нарисованы задним числом)',t:'chk'},
 {k:'hand_tf_mode',l:'На каких таймфреймах торговать мои рисунки',t:'sel',o:[['junior','на том, где нарисовано, и на младших'],['own','только на том, где нарисовано'],['any','на любых (старшие тоже)']]},
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
const TRIG_OPT=[['','— не выбрано —'],
 ['pattern','Свечной паттерн разворота (молот, поглощение, звезда…)'],
 ['cross200','Пересечение EMA20 и EMA200'],
 ['cross20','Цена закрылась по другую сторону EMA20'],
 ['cross50','Цена закрылась по другую сторону EMA50'],
 ['tl_both','Отбой И пробой канала, флэта или треугольника, построенного роботом (P — допуск касания для отбоя, в долях ATR, 0.3; запас пробоя 0.2 ATR)'],
 ['tl_bounce','Отбой от границы канала или флэта, построенного роботом (P — допуск касания, в долях ATR, по умолч. 0.3)'],
 ['tl_breakout','Пробой канала, флэта или треугольника, построенного роботом (P — запас за линией, в долях ATR, по умолч. 0.2)'],
 ['hand_both','Отбой И пробой моих рисунков сразу (P — допуск касания для отбоя, в долях ATR, 0.3; запас пробоя 0.2 ATR). Отбой: цель — противоположная граница; пробой: цель — граница + ширина канала'],
 ['hand_bounce','Отбой от моего канала или флэта, нарисованного на 18093 (P — допуск касания, в долях ATR, 0.3)'],
 ['hand_breakout','Пробой моего канала, флэта или треугольника, нарисованного на 18093 (P — запас, в долях ATR, 0.2)']];
const CONF_OPT=[['','— пусто, уровень пропускается —'],
 ['close_ema20','EMA20: свеча закрылась за линией (выше — лонг, ниже — шорт)'],
 ['pullback_ema20','EMA20: цена вернулась к линии, откат (P — как близко, в долях ATR, по умолч. 0.9)'],
 ['ema20_slope','EMA20: линия развернулась в сторону сделки (P — за сколько свечей, по умолч. 3)'],
 ['ema50_trend','EMA50: тренд — цена по сторону EMA50, и EMA50 не направлена против сделки'],
 ['ema50_pullback','EMA50: цена вернулась к линии, откат (P — как близко, в долях ATR, по умолч. 0.8)'],
 ['ema50_slope','EMA50: линия наклонена в сторону сделки (P — за сколько свечей, по умолч. 5)'],
 ['ema200_side','EMA200: цена по сторону EMA200 (лонг — выше, шорт — ниже)'],
 ['rsi_level','RSI: вернулся выше P для лонга (ниже 100−P для шорта), по умолч. 45'],
 ['macd_turn','MACD: гистограмма растёт 2 свечи подряд (лонг) / падает (шорт)'],
 ['macd_sign','MACD: гистограмма по направлению сделки и растёт'],
 ['stoch_dir','Stochastic: в сторону сделки (лонг выше P, шорт ниже 100−P, по умолч. 50)'],
 ['stochrsi_cross','Stoch RSI: K пересекла D в зоне перепроданности 20 (лонг) / перекупленности 80 (шорт)'],
 ['volume','Объём: у свечи объём выше среднего (P — во сколько раз, по умолч. 1.2)']];
const ST_OPT=TRIG_OPT.concat(CONF_OPT.slice(1));
const PF_OPT=[['none','все паттерны'],['volume','только с повышенным объёмом'],['level','только у уровня поддержки/сопротивления'],['extreme','только на новом экстремуме'],['sweep','только после ложного пробоя (съём экстремума)']];
const PF_NAME={none:'все',level:'у уровня',volume:'с объёмом',extreme:'на экстремуме',stretch:'после растяжения от EMA20','level+volume':'у уровня и с объёмом','extreme+volume':'на экстремуме и с объёмом',sweep:'после ложного пробоя',sweep16:'после ложного пробоя (4 ч)','sweep+volume':'после ложного пробоя с объёмом'};
function stageForm(){let h='<div class=sec>Фильтр входа по уровням</div><div class=sm>Работает при правиле входа «уровни фильтра». Уровень 1 — триггер (что запускает поиск входа), уровни 2–5 — подтверждения: каждое проверяется только после предыдущего, пустой пропускается. «Окно» — сколько свечей ждать этот уровень после предыдущего. P — число для условия (0 — значение по умолчанию). ATR — средний размах свечи за последние 14 свечей: «0.3 ATR» — это треть обычной свечи, так расстояния не зависят от цены монеты.</div>';
 for(let i=0;i<5;i++){h+='<div class=f><label>Уровень '+(i+1)+'</label><select id=s'+i+'_t>'+(i===0?TRIG_OPT:CONF_OPT).map(o=>'<option value="'+o[0]+'">'+o[1]+'</option>').join('')+'</select>'+
  '<div class=t style="padding:2px 0"><span class=sm>P</span><input id=s'+i+'_p type=number step=any inputmode=decimal style="width:70px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px"> <span class=sm>окно, св.</span><input id=s'+i+'_w type=number inputmode=numeric style="width:70px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:6px"></div>'+
  '<select id=s'+i+'_f'+(i?' style="display:none"':'')+'>'+PF_OPT.map(o=>'<option value="'+o[0]+'">'+o[1]+(i?'':' (если триггер — свечной паттерн)')+'</option>').join('')+'</select></div>'}
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
function ensureOpt(id,v,names){const s=$(id);if(!s||v==null||v==='')return;if(!Array.from(s.options).some(o=>o.value===String(v))){const o=document.createElement('option');o.value=String(v);o.textContent=((names&&names[v])||String(v))+' (устаревший пункт)';s.appendChild(o)}}
function setForm(c){const st=(c.stages||[]).slice(0,5);while(st.length<5)st.push({t:'',p:0,w:12,f:'none'});st.forEach((x,i)=>{ensureOpt('s'+i+'_t',x.t,ST_NAME);ensureOpt('s'+i+'_f',x.f,PF_NAME);$('s'+i+'_t').value=x.t||'';$('s'+i+'_p').value=x.p||0;$('s'+i+'_w').value=x.w||12;$('s'+i+'_f').value=x.f||'none'});FIELDS.forEach(f=>{if(f.sec||f.stg)return;const e=$('f_'+f.k);if(f.t==='chk')e.checked=!!c[f.k];else{if(f.t==='sel')ensureOpt('f_'+f.k,c[f.k],f.k==='pat_filter'?PF_NAME:null);e.value=c[f.k]}})}
function readForm(){const c={};c.stages=[0,1,2,3,4].map(i=>({t:$('s'+i+'_t').value,p:parseFloat($('s'+i+'_p').value)||0,w:parseInt($('s'+i+'_w').value)||12,f:$('s'+i+'_f').value}));FIELDS.forEach(f=>{if(f.sec||f.stg)return;const e=$('f_'+f.k);c[f.k]=f.t==='chk'?e.checked:f.t==='num'?parseFloat(e.value):e.value});return c}
function mkTabs(){$('tabs').innerHTML='';[['hist','История / текущие правила'],['live','Живая бумага']].forEach(([k,l])=>{const b=document.createElement('button');b.textContent=l;if(S.tab===k)b.className='on';b.onclick=()=>setTab(k);$('tabs').appendChild(b)})}
function setTab(k){S.tab=k;$('vHist').style.display=k==='hist'?'block':'none';$('vLive').style.display=k==='live'?'block':'none';mkTabs();if(k==='live')loadRuns();else load()}
function mkPairs(){$('pairs').innerHTML='';S.pairs.forEach(p=>{const b=document.createElement('button');b.textContent=p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;V.off=0;V.vz=1;V.vo=0;Gc.hover=-1;mkPairs();load()};$('pairs').appendChild(b)})}
function mkr(){$('rng').innerHTML='';[[192,'192 св.'],[480,'480 св.'],[960,'все 960']].forEach(([n,l])=>{const b=document.createElement('button');b.textContent=l;if(V.n===n)b.className='on';b.onclick=()=>{V.n=n;V.off=0;V.vz=1;V.vo=0;Gc.hover=-1;mkr();chart()};$('rng').appendChild(b)});(S.D&&S.D.cfg?['5m','15m','30m','1h','2h','4h','6h','12h','1d']:[]).forEach(tf=>{const cur=V.vtf||S.D.cfg.tf,b=document.createElement('button');b.textContent=tf+(tf===S.D.cfg.tf?' •':'');if(cur===tf)b.className='on';b.title=tf===S.D.cfg.tf?'ТФ правил (по нему считаются сделки)':'показать график на этом ТФ; сделки остаются от ТФ правил';b.onclick=()=>{V.vtf=tf===S.D.cfg.tf?'':tf;V.off=0;V.vz=1;V.vo=0;Gc.hover=-1;load()};$('rng').appendChild(b)});[['ch','Каналы'],['ema','EMA']].forEach(([k,l])=>{const b=document.createElement('button');b.textContent=l+': '+(V[k]?'ВКЛ':'выкл');if(V[k])b.className='on';b.onclick=()=>{V[k]=!V[k];LSset('cl_'+k,V[k]);mkr();chart()};$('rng').appendChild(b)})}
async function load(){
 try{const j=await api('/api/trades?sym='+S.sym+'&bars=960'+(V.vtf?'&vtf='+V.vtf:''));if(j.sym!==S.sym)return;S.D=j;S.cfg=j.cfg;renderHist()}catch(e){$('tbl').textContent='Ошибка: '+e.message}
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
{let e=$('sumLS');if(!e){e=document.createElement('div');e.id='sumLS';e.className='card';$('sum').parentNode.insertAdjacentElement('afterend',e)}
const sp6=D.period?D.period.from_ms+0.6*(D.period.to_ms-D.period.from_ms):null;
const sd=k=>{const A=T.filter(x=>x.side===k),m=A.length,wn=A.filter(x=>x.net>0).length,sn=A.reduce((a,x)=>a+x.net,0),gg=A.reduce((a,x)=>a+x.gross,0),us=A.reduce((a,x)=>a+(x.usd||0),0),bb=A.filter(x=>x.be).length,oo=A.filter(x=>x.open).length;
 const Bs=A.slice().sort((a,b)=>a.t_out-b.t_out);let cu=0,pe=0,md=0;Bs.forEach(x=>{cu+=x.net;if(cu>pe)pe=cu;if(pe-cu>md)md=pe-cu});
 const bt=m?Math.max(...A.map(x=>x.net)):0,wt=m?Math.min(...A.map(x=>x.net)):0;
 let pa='—',pb='—';if(sp6!==null){const A1=A.filter(x=>x.t_in<sp6),B1=A.filter(x=>x.t_in>=sp6);pa=A1.length+' / '+sg(A1.reduce((a,x)=>a+x.net,0))+'%';pb=B1.length+' / '+sg(B1.reduce((a,x)=>a+x.net,0))+'%'}
 return {m,wn,sn,gg,us,bb,oo,md,bt,wt,pa,pb}};
const L=sd('L'),S=sd('S');
const cl=v=>'<b class=\"'+cls(v)+'\">'+sg(v)+'%</b>';
const rw=(n,f)=>'<tr><td>'+n+'</td><td>'+f(L)+'</td><td>'+f(S)+'</td></tr>';
e.innerHTML='<div style=\"font-weight:600;margin-bottom:4px\">Лонги и шорты отдельно</div><table><tr><th></th><th class=up>ЛОНГ</th><th class=dn>ШОРТ</th></tr>'
+rw('Сделок',x=>x.m+(x.oo?' (откр. '+x.oo+')':''))
+rw('Прибыльных',x=>x.m?x.wn+' ('+Math.round(x.wn/x.m*100)+'%)':'—')
+rw('Сумма Net %',x=>cl(x.sn))
+rw('Net, USDT (на '+N+')',x=>'<b class=\"'+cls(x.sn)+'\">'+sg(x.sn*N/100)+'</b>')
+rw('Профит, $ (по ставкам)',x=>'<b class=\"'+cls(x.us)+'\">'+sg(x.us)+' $</b>')
+rw('До комиссий %',x=>sg(x.gg)+'%')
+rw('Средний Net %',x=>x.m?sg(x.sn/x.m)+'%':'—')
+rw('Лучшая / худшая',x=>x.m?sg(x.bt)+' / '+sg(x.wt):'—')
+rw('Дошли до БУ',x=>x.bb+' из '+x.m)
+rw('Макс. просадка %',x=>x.md>0?'-'+x.md.toFixed(2)+'%':'0%')
+rw('Подбор 60%: сд. / Net',x=>x.pa)
+rw('Проверка 40%: сд. / Net',x=>x.pb)
+'</table>'}
 let h='<table><tr><th>Сторона</th><th>Вход</th><th>Цена</th><th>Стоп0</th><th>Риск%</th><th>Выход</th><th>Цена</th><th>Причина</th><th>Net%</th><th>MFE</th><th>MAE</th><th>Ставка $</th><th>$</th></tr>';
 T.slice().sort((a,b)=>b.t_in-a.t_in).forEach(x=>{h+='<tr><td class="'+(x.side==='L'?'up':'dn')+'">'+(x.side==='L'?'ЛОНГ':'ШОРТ')+'</td><td>'+ft(x.t_in)+'</td><td>'+fmt(x.p_in)+'</td><td>'+fmt(x.stop0)+'</td><td>'+x.risk.toFixed(2)+'</td><td>'+(x.open?'—':ft(x.t_out))+'</td><td>'+(x.open?fmt(x.p_out)+' (тек.)':fmt(x.p_out))+'</td><td>'+x.reason+(x.be&&x.reason!=='безубыток'?' ✓БУ':'')+'</td><td class="'+cls(x.net)+'"><b>'+sg(x.net)+'</b></td><td>'+x.mfe.toFixed(2)+'</td><td>'+x.mae.toFixed(2)+'</td><td>'+(x.stake!=null?x.stake.toFixed(2):'—')+'</td><td class="'+cls(x.usd||0)+'"><b>'+(x.usd!=null?sg(x.usd):'—')+'</b></td></tr>'});
 $('tbl').innerHTML=n?h+'</table>':'За выбранный период сигналов не было';
 $('chT').textContent=D.sym+' · правила '+c.tf+(V.vtf?' · график '+V.vtf:'');mkr();chart();
}
function handLbl(id){const m=(S.hand||{})[id];if(!m)return '—';return ({channel:'канал',range:'флэт',triangle:'треугольник'}[m.kind]||m.kind)+' '+m.tf+' · создан '+ft(m.created)+(m.deleted?' (удалён '+ft(m.deleted)+')':'')}
function runCard(r){
 const st=r.stats,N=S.runs?S.notional:100,act=r.stop_ms==null;
 let h='<div class=card><h4>Прогон #'+r.id+' · '+r.name+' · '+r.sym+' · '+(act?'<span class=up>идёт</span>':'<span class=fl>остановлен '+ft(r.stop_ms)+'</span>')+'</h4>';
 h+='<div class=sm>'+(r.start_ms>0?'с '+ft(r.start_ms):'торгует по свечам после рисования канала')+' · '+describe(r.cfg)+'</div>';
 const wr=st.n?Math.round(st.win/st.n*100)+'%':'—',sp=st.net*N/100;
 h+='<div class=grid style="margin-top:6px">'+[['Сделок',st.n+(st.open?' (открыта '+st.open+')':'')],['Прибыльных',wr],['Net %','<span class="'+cls(st.net)+'" style="display:inline;font-size:16px">'+sg(st.net)+'%</span>'],['Net, USDT (на '+N+')',sg(sp)],['До комиссий %',sg(st.gross)+'%'],['Дошли до БУ',r.trades.filter(x=>x.be).length+' из '+r.trades.length]].concat(st.money?[['Профит, $ (по ставкам)','<span class="'+cls(st.money.profit)+'" style="display:inline;font-size:16px">'+sg(st.money.profit)+' $</span>'],['Макс. ставка, $',st.money.max_stake.toFixed(2)],['Макс. просадка, $','-'+st.money.max_dd.toFixed(2)]]:[]).map(x=>'<div><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join('')+'</div>';
 h+='<details data-k=t'+r.id+' style="margin-top:6px"><summary class=sm>Сделки ('+r.trades.length+')</summary><div class=sc>';
 if(r.trades.length){h+='<table><tr><th>Сторона</th><th>Рисунок</th><th>Вход</th><th>Цена</th><th>Стоп0 / цель</th><th>Выход</th><th>Цена</th><th>Причина</th><th>Безубыток</th><th>Net%</th><th>Ставка $</th><th>$</th></tr>';
  r.trades.slice().sort((a,b)=>b.t_in-a.t_in).forEach(x=>{h+='<tr><td class="'+(x.side==='L'?'up':'dn')+'">'+(x.side==='L'?'ЛОНГ':'ШОРТ')+(x.sig==='k'?' · пробой':x.sig==='b'?' · отбой':x.sig==='f'?' · возврат':'')+'</td><td>'+handLbl(x.sid)+'</td><td>'+ft(x.t_in)+'</td><td>'+fmt(x.p_in)+'</td><td>'+fmt(x.stop0)+(x.tp?' / цель '+fmt(x.tp):'')+'</td><td>'+(x.open?'—':ft(x.t_out))+'</td><td>'+(x.open?fmt(x.p_out)+' (тек.)':fmt(x.p_out))+'</td><td>'+x.reason+'</td><td>'+(x.be?'<span class=up>✓ стоп '+fmt(x.stop)+'</span>':'—')+'</td><td class="'+cls(x.net)+'"><b>'+sg(x.net)+'</b></td><td>'+(x.stake!=null?x.stake.toFixed(2):'—')+'</td><td class="'+cls(x.usd||0)+'"><b>'+(x.usd!=null?sg(x.usd):'—')+'</b></td></tr>'});h+='</table>'}else h+='<div class=sm>пока сделок нет</div>';
 h+='</div></details><div class=t>'+(act?'<button class=bad onclick="runAct(\'stop\','+r.id+')">■ Остановить</button>':'')+'<button onclick="runAct(\'delete\','+r.id+')">Удалить</button></div></div>';
 return h;
}
const money=v=>(v<0?'−':'')+Math.abs(v).toFixed(2)+' $';
const smoney=v=>(v>=0?'+':'−')+Math.abs(v).toFixed(2)+' $';
const TRK={me:['Вы','Счёт «Вы» — торговля по вашим рисункам'],bot:['Бот','Счёт «Бот» — каналы и треугольники находит робот'],both:['Вместе','Счёт «Вместе» — позиции, которые предложил бот и вы открыли кнопкой'],cand:['Кандидат','Счёт «Кандидат» — сигналы бота, прошедшие фильтр (цель близко); открываются сами, без вашего решения'],exp:['Эксп.','Эксперименты — параллельные проверки идей'],vp:['Профиль','Счёт «Профиль» — отбой и пробой канала с фильтром по профилю объёма (POC, VAH, VAL); канал и старт профиля по ZigZag']};
function trackBar(){const A=S.acc||{};return '<div class=t>'+['me','bot','both','cand','vp','exp'].map(k=>{const a=A[k]&&A[k].account;return '<button data-trk='+k+(S.track===k?' class=on':'')+'>'+TRK[k][0]+(a?' · '+money(a.equity):'')+'</button>'}).join('')+'</div>'}
function loadLine(){const L=S.load;if(!L)return '';const w=L.weight?' · запросы к Binance '+L.weight+' из '+L.limit+' в мин.':'';return '<div class=sm style="margin:6px 2px">Загрузка: пар '+L.pairs+' из '+L.cap+' · прогонов '+L.runs+w+(L.calc_s!=null?' · расчёт '+L.calc_s+' с':'')+(L.ban?' · <b>Binance просит паузу '+L.ban+' с</b>':'')+'</div>'}
function rotCard(){const vp=S.track==='vp',sc=S.screen,d0=sc&&sc.data,d=d0&&(vp?d0.vp:d0),act=new Set((S.runs||[]).filter(r=>r.stop_ms==null&&(!vp||r.track==='vp')).map(r=>r.sym)),VL=(S.load&&S.load.vp)||{},AD=vp?'vpadd':'add',DR=vp?'vpdrop':'drop';
let h='<details class=card data-k=rot><summary style="font-size:15px;font-weight:600">Ротация пар · предложения бота'+(vp?' (Профиль)':'')+'</summary>';
if(!d)return h+'<div class=sm style="margin-top:8px">'+(sc&&sc.err?'Не удалось построить список: '+sc.err:'Список строится, это занимает несколько минут после запуска…')+'</div></details>';
const cands=d.cands.filter(c=>!act.has(c.sym)),rep=d.replace.filter(c=>act.has(c.sym));
h+='<div class=sm style="margin-top:8px">Обновлён '+ft(d0.ts*1000)+'. Критерий: размах дневной свечи за 14 дней в % от цены (волатильность), оборот за сутки от '+(d.min_vol/1e6).toFixed(1)+' млн $, минимальный ордер биржи не больше 6 $, история не короче '+d.min_days+' дней. Бот ничего не добавляет и не убирает сам: решение за вами.'+(vp?' Здесь пара добавляется и убирается только в Профиле, другие вкладки не затрагиваются. Максимум: '+(VL.cap_pairs||30)+' пар и '+(VL.cap_runs||120)+' прогонов (пары × таймфреймы); сейчас '+(VL.pairs||0)+' пар, '+(VL.runs||0)+' прогонов.':'')+'</div>';
h+='<div class=sm style="margin-top:8px"><b>Сейчас в работе</b> (размах дня): '+d.cur.filter(x=>act.has(x.sym)).map(x=>x.sym.replace('USDT','')+' '+(x.rng14==null?'—':x.rng14+'%')).join(' · ')+' · типичная пара биржи ≈ '+d.typical+'% · лучшие кандидаты ≈ '+d.median+'%</div>';
h+='<div class=sm style="margin-top:10px"><b>Предложения заменить</b></div>';
if(rep.length)h+='<div class=sc><table><tr><th>Пара</th><th>Почему</th><th></th></tr>'+rep.map(c=>'<tr><td>'+c.sym+'</td><td style="white-space:normal;text-align:left">'+c.why.join('; ')+'</td><td><button data-'+DR+'='+c.sym+'>Убрать</button></td></tr>').join('')+'</table></div>';
else h+='<div class=sm>Пока нет: по текущим парам не выполнено ни одно условие замены.</div>';
h+='<div class=sm style="margin-top:10px"><b>Кандидаты на добавление</b> ('+(vp?'каждая пара добавит '+((VL.tfs||[]).length)+' прогонов, ТФ: '+(VL.tfs||[]).join(', '):'каждая пара добавляет 10 прогонов')+')</div>';
if(cands.length)h+='<div class=sc><table><tr><th>Пара</th><th>Размах дня</th><th>Оборот 24ч</th><th>Цена</th><th></th></tr>'+cands.map(c=>'<tr><td>'+c.sym+'</td><td>'+c.rng14+'%</td><td>'+(c.vol/1e6).toFixed(1)+' млн</td><td>'+c.price+'</td><td><button data-'+AD+'='+c.sym+'>Добавить</button></td></tr>').join('')+'</table></div>';
else h+='<div class=sm>Подходящих кандидатов сейчас нет.</div>';
return h+'</details>'}
async function loadScreen(){try{S.screen=await api('/api/screen')}catch(e){}if(S.tab==='live'&&S.runs)renderRuns();setTimeout(loadScreen,S.screen&&S.screen.data?300000:20000)}
async function vpPairAct(a,sym){if(S.pbusy)return;const L=(S.load&&S.load.vp)||{},tf=(L.tfs||[]).join(', ');const t=a==='vp_add_pair'?'Добавить '+sym+' в Профиль? Будет создано '+(L.tfs||[]).length+' прогонов (ТФ: '+tf+'), статистика пойдёт с этого момента.':'Убрать '+sym+' из Профиля? Его прогоны Профиля остановятся, открытые позиции закроются по текущей цене. История сохранится, другие вкладки не затрагиваются.';if(!confirm(t))return;S.pbusy=1;try{const j=await api('/api/runs',{action:a,sym:sym});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.hand=j.hand||S.hand;S.load=j.load||S.load;renderRuns()}catch(e){alert(e.message)}S.pbusy=0}
function vpTfCard(){const L=(S.load&&S.load.vp)||null;if(!L)return '';const cur=L.tfs||[],sel=S.vpTfSel||cur.slice(),all=L.tf_all||[],n=(L.pairs||0)*sel.length,same=sel.length===cur.length&&sel.every(t=>cur.includes(t));
const chips=all.map(t=>'<button data-vtf='+t+' style="margin:2px 4px 2px 0;'+(sel.includes(t)?'background:#1f6feb;color:#fff':'')+'">'+t+'</button>').join('');
return '<div class=card><b>Таймфреймы Профиля</b><div class=sm style="margin:6px 0">Сейчас: '+cur.join(', ')+'. Пар '+L.pairs+' из '+L.cap_pairs+', прогонов '+L.runs+' из '+L.cap_runs+'. Низкие таймфреймы дают больше сделок, но и больше шума. Добавленные таймфреймы стартуют с этого момента (история не пересчитывается); снятые останавливаются, их позиции закрываются по текущей цене, статистика остаётся. Настройки ZigZag общие для всех таймфреймов (поле 0 — значения по умолчанию для каждого).</div><div>'+chips+'</div><div class=sm style="margin:6px 0">После применения: '+L.pairs+' пар × '+sel.length+' ТФ = '+n+' прогонов (лимит '+L.cap_runs+')</div><button '+(same||!sel.length||n>L.cap_runs?'disabled':'')+' onclick="vpTfApply()">Применить таймфреймы</button> <span id=vptmsg class=sm></span></div>'}
async function vpTfApply(){const sel=S.vpTfSel,cur=((S.load&&S.load.vp)||{}).tfs||[];if(!sel||!sel.length)return;if(cur.some(t=>!sel.includes(t))&&!confirm('Снятые таймфреймы остановятся, их открытые позиции закроются по текущей цене. Продолжить?'))return;const m=$('vptmsg');if(m)m.textContent='Применяю и пересчитываю… до минуты';try{const j=await api('/api/runs',{action:'vp_tfs',tfs:sel});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.hand=j.hand||S.hand;S.load=j.load||S.load;S.vpTfSel=null;renderRuns()}catch(e){const m2=$('vptmsg');if(m2)m2.textContent='Ошибка: '+e.message}}
async function pairAct(a,sym){if(S.pbusy)return;const t=a==='add_pair'?'Добавить '+sym+'? Будет создано 10 прогонов (5 таймфреймов × Вы и Бот), статистика по ним пойдёт с этого момента.':'Убрать '+sym+'? Все его прогоны остановятся, открытые позиции закроются по текущей цене. История и статистика сохранятся.';if(!confirm(t))return;S.pbusy=1;try{const j=await api('/api/runs',{action:a,sym:sym});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.hand=j.hand||S.hand;S.load=j.load||S.load;renderRuns()}catch(e){alert(e.message)}S.pbusy=0}
function bindTrk(){bindPairs();document.querySelectorAll('#runs [data-trk]').forEach(b=>{b.onclick=()=>{S.track=b.dataset.trk;renderRuns()}});document.querySelectorAll('#runs [data-add]').forEach(b=>{b.onclick=()=>pairAct('add_pair',b.dataset.add)});document.querySelectorAll('#runs [data-vpadd]').forEach(b=>{b.onclick=()=>vpPairAct('vp_add_pair',b.dataset.vpadd)});document.querySelectorAll('#runs [data-vpdrop]').forEach(b=>{b.onclick=()=>vpPairAct('vp_drop_pair',b.dataset.vpdrop)});document.querySelectorAll('#runs [data-vstf]').forEach(b=>{b.onclick=()=>{S.vpSetTf=b.dataset.vstf;S.vpDirty=0;renderRuns()}});document.querySelectorAll('#runs [data-vtf]').forEach(b=>{b.onclick=()=>{const L=(S.load&&S.load.vp)||{},s=(S.vpTfSel||(L.tfs||[]).slice()).slice(),t=b.dataset.vtf,i=s.indexOf(t);if(i>=0)s.splice(i,1);else s.push(t);S.vpTfSel=s;renderRuns()}});document.querySelectorAll('#runs [data-drop]').forEach(b=>{b.onclick=()=>pairAct('drop_pair',b.dataset.drop)});document.querySelectorAll('#runs th[data-st]').forEach(b=>{b.onclick=()=>{const id=b.dataset.st,c=+b.dataset.sc,o=S.sort[id];S.sort[id]=o&&o.c===c?{c:c,d:-o.d}:{c:c,d:+b.dataset.sd};renderRuns()}})}
function stbl(id,cols,rows,def){const st=S.sort[id]||def||null;let R=rows.slice();if(st&&cols[st.c]&&cols[st.c].v){const f=cols[st.c].v,d=st.d;R.sort((a,b)=>{const x=f(a),y=f(b),nx=x==null||x!==x,ny=y==null||y!==y;if(nx||ny)return nx&&ny?0:nx?1:-1;return(typeof x==='string'?x.localeCompare(y):x-y)*d})}
return '<table><tr>'+cols.map((c,i)=>'<th class=srt data-st='+id+' data-sc='+i+' data-sd='+(c.t?1:-1)+'>'+c.l+(st&&st.c===i?(st.d>0?' ▲':' ▼'):'')+'</th>').join('')+'</tr>'+R.map(r=>'<tr>'+cols.map(c=>c.h(r)).join('')+'</tr>').join('')+'</table>'}
function acctCard(a,title){if(!a)return '';const p=a.pos,c=a.pnl>=0?'up':'dn';
let h='<div class=card><h4>'+title+'</h4><div class=sm>Старт '+money(a.start)+' · плечо '+a.lev+'x, изолированная маржа · каждая позиция по минимальной ставке '+money(a.stake)+' (маржа '+money(a.margin_each)+') · одновременно, пока занято не больше '+Math.round(a.use*100)+'% баланса (сейчас до '+a.max_pos+' позиций), остальное — запас на просадку</div>';
h+='<div class=eq>'+money(a.equity)+' <span class='+c+'>'+smoney(a.pnl)+' ('+sg(a.ret_pct)+'%)</span></div>';
h+='<div class=grid><div><span>Баланс кошелька</span><b>'+money(a.balance)+'</b></div><div><span>Нереализованный PnL</span><b class='+(a.unreal>=0?'up':'dn')+'>'+smoney(a.unreal)+'</b></div><div><span>В марже</span><b>'+money(a.margin)+'</b></div><div><span>Доступно</span><b>'+money(a.available)+'</b></div></div>';
if(a.positions.length)h+='<div class=sm style="margin-top:8px">Открытые позиции ('+a.positions.length+'):</div>'+a.positions.map(p=>'<div class="sm posb"><b>'+p.sym+' '+p.tf+' '+(p.side==='L'?'LONG':'SHORT')+'</b>'+(p.sig==='k'?' · пробой':p.sig==='b'?' · отбой':p.sig==='f'?' · возврат':'')+' · вход '+p.p_in+' · сейчас '+p.mark+' · стоп '+p.stop+(p.tp?' · цель '+p.tp:'')+' · ликвидация '+p.liq_price+(p.be?' · ✓ безубыток':'')+'<br>размер '+money(p.notional)+' · маржа '+money(p.margin)+' · результат '+smoney(p.upnl)+' (ROE '+sg(p.roe)+'%)'+posCtl(p)+'</div>').join('');
else h+='<div class=sm style="margin-top:8px">Позиций нет — ждёт сигнал</div>';
h+='<div class=sm style="margin-top:6px">Взято '+a.taken+' · закрыто '+a.closed+' · прибыльных '+(a.win_pct==null?'—':a.win_pct+'%')+' · пропущено (не хватило свободной маржи) '+a.skipped+' · макс. одновременно '+a.maxc+' · '+a.status+'</div>';
if(a.log.length){const lc=[{l:'Пара · ТФ',t:1,v:t=>t.sym+' '+t.tf,h:t=>'<td>'+t.sym+' · '+t.tf+'</td>'},{l:'Сторона',t:1,v:t=>t.side+(t.sig||''),h:t=>'<td>'+(t.side==='L'?'лонг':'шорт')+(t.sig==='k'?' · пробой':t.sig==='b'?' · отбой':t.sig==='f'?' · возврат':'')+(t.liq?' · ЛИКВИДАЦИЯ':'')+'</td>'},{l:'Вход',v:t=>t.t_in,h:t=>'<td>'+ft(t.t_in)+'</td>'},{l:'Выход',v:t=>t.open?9e15:t.t_out,h:t=>'<td>'+(t.open?'—':ft(t.t_out))+'</td>'},{l:'Net%',v:t=>t.net,h:t=>'<td class='+cls(t.net)+'>'+sg(t.net)+'</td>'},{l:'PnL',v:t=>t.pnl,h:t=>'<td class='+cls(t.pnl)+'>'+smoney(t.pnl)+'</td>'},{l:'БУ',v:t=>t.be?1:0,h:t=>'<td>'+(t.be?'<span class=up>✓</span>':'—')+'</td>'},{l:'Баланс',v:t=>t.open?null:t.bal_after,h:t=>'<td>'+(t.open?'открыта':money(t.bal_after))+'</td>'},{l:'Действия',v:t=>t.open?1:0,h:t=>'<td style="white-space:nowrap">'+(t.open?rowCtl(t):'')+'</td>'}];h+='<details data-k=acl_'+S.track+'><summary class=sm>Сделки счёта · взято '+a.taken+' · закрыто '+a.closed+' · прибыльных '+a.wins+' из '+a.closed+(a.win_pct==null?'':' ('+a.win_pct+'%)')+'</summary>'+(a.taken>a.log.length?'<div class=sm>Показаны последние '+a.log.length+'. ':'<div class=sm>')+'Порядок по умолчанию — по времени выхода; нажмите на заголовок столбца, чтобы отсортировать.</div><div class=\"sc stk\" style=\"max-height:340px;overflow-y:auto\">'+stbl('acl_'+S.track,lc,a.log,{c:3,d:-1})+'</div></details>'}
return h+'</div>'}
function sigCard(s,both){if(!s)return '';let h='<div class=card><h4>'+(both?'Все предложения бота · если брать каждое':'Все сигналы · сколько нужно денег')+'</h4><div class=sm>'+(both?'Для сравнения с вашим отбором: что было бы, если бы вы открывали каждое предложение. ':'')+'Каждый сигнал учтён отдельно, без ограничения «одна позиция». Ставка на каждый сигнал та же, что у счёта: '+money(s.notional)+' (маржа '+money(s.margin)+' при 5x).</div>';
if(!s.n)return h+'<div class=sm style="margin-top:8px">Сигналов пока нет.</div></div>';
h+='<div class=grid style="margin-top:8px"><div><span>Сигналов</span><b>'+s.n+(s.open?' (откр. '+s.open+')':'')+'</b></div><div><span>Прибыльных</span><b>'+(s.win_pct==null?'—':s.win_pct+'%')+'</b></div><div><span>Итого</span><b class='+(s.total>=0?'up':'dn')+'>'+smoney(s.total)+'</b></div><div><span>Пик одновременных позиций</span><b>'+s.peak+'</b></div><div><span>Макс. просадка</span><b>'+money(s.max_dd)+'</b></div></div>';
h+='<div class=need>Чтобы взять все эти сигналы, нужно на старте ≈ <b>'+money(s.need)+'</b><br><span class=sm>пик одновременных позиций '+s.peak+' → маржа '+money(s.peak_margin)+', с запасом (занято не больше '+Math.round(s.use*100)+'% баланса) '+money(s.peak_need)+' + запас на максимальную просадку '+money(s.max_dd)+'. Доходность на этот капитал: '+(s.roi==null?'—':sg(s.roi)+'%')+'</span></div>';
return h+'</div>'}
const MODE_N={auto:'Торгует сам',propose:'Только предлагает',off:'Выкл'},PST={opened:'открыта вами',rejected:'отклонена',missed:'без решения'};
const ago=ms=>{const m=Math.max(0,Math.round(ms/60000));return m<60?m+' мин':m<2880?Math.round(m/60)+' ч':Math.round(m/1440)+' дн'};
function ap(j){S.runs=j.runs;S.notional=j.notional;S.hand=j.hand||S.hand;S.acc=j.accounts||{};S.load=j.load||S.load;S.prop=j.proposals||S.prop;S.pairsAll=j.pairs_all||S.pairsAll;S.man=j.manual||{}}
function posCtl(p){if(p.run==null)return '';const k=p.run+'|'+p.kt+'|'+p.side,m=(S.man||{})[k];let h='';
if(m)h+='<div class=sm style="margin-top:4px;color:#d29922">'+(m.mode==='trail'?'трейлинг '+m.pct+'% · стоп сейчас '+fmt(m.lvl):'ручной стоп '+fmt(m.lvl)+' ('+m.pct+'% от цены при установке)')+'</div>';
if(S.mp===k)h+='<div class=sm style="margin-top:4px">Стоп — фиксированный уровень на этом расстоянии от цены сейчас. Трейлинг — уровень идёт за лучшей ценой на этом расстоянии, только в сторону прибыли. Работает вместе со стопом стратегии: сработает то, что ближе. Кнопки — в строке этой позиции в журнале «Сделки счёта» (последний столбец). Цена проверяется каждые ~5 с, закрытие по цене в момент срабатывания.</div>';
return h}
function rowCtl(t){if(t.run==null)return '';const k=t.run+'|'+t.kt+'|'+t.side,m=(S.man||{})[k];
let h='<button data-pg=1 data-run="'+t.run+'" data-t="'+t.kt+'" data-side="'+t.side+'">📈 График</button> <button data-pc="'+k+'" data-sym="'+t.sym+' '+t.tf+' '+(t.side==='L'?'LONG':'SHORT')+'">Закрыть</button> <button data-ps="'+k+'">Стоп / трейлинг</button>';
if(S.mp===k)h+=' <input id=mpv type=number step=0.1 min=0.05 max=50 value="'+(S.mpv||1)+'" oninput="S.mpv=this.value" style="width:64px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:5px"> % <button data-pm=stop data-k="'+k+'">Стоп</button><button data-pm=trail data-k="'+k+'">Трейлинг</button>'+(m?'<button data-pm=clear data-k="'+k+'">Снять</button>':'');
return h}
async function posAct(k,body){if(S.pbusy)return;const a=k.split('|');S.pbusy=1;try{ap(await api('/api/runs',Object.assign({run:+a[0],kt:+a[1],side:a[2]},body)));S.mp=null}catch(e){alert(e.message)}S.pbusy=0;renderRuns()}
function botPairs(){const m={};(S.runs||[]).forEach(r=>{if(r.stop_ms==null&&(r.track||'me')==='bot'){const md=r.mode||'auto';m[r.sym]=m[r.sym]&&m[r.sym]!==md?'mixed':md}});const all=new Set((S.pairsAll||[]).concat((S.runs||[]).filter(r=>r.stop_ms==null).map(r=>r.sym)));return Array.from(all).sort().map(s=>({sym:s,mode:m[s]||'off'}))}
function pairsCard(){const L=botPairs(),na=L.filter(x=>x.mode==='auto').length,np=L.filter(x=>x.mode==='propose').length;
let h='<details class=card data-k=bpairs><summary style="font-size:15px;font-weight:600">Пары бота · сам торгует '+na+' · только предлагает '+np+'</summary><div class=sm style="margin:8px 0">Выбор пар для стороны «Бот» (сторона «Вы» от этого не меняется). «Торгует сам» — бот сам открывает и закрывает позиции, они идут в счёт «Бот». «Только предлагает» — бот ищет сигналы, но не открывает: предложения появляются во вкладке «Вместе», где вы нажимаете «Открыть» или «Отклонить». «Выкл» — бот по паре не работает. При смене режима прежние прогоны пары останавливаются (открытые позиции закрываются по текущей цене, история сохраняется), новые стартуют с текущего момента.</div>';
h+=L.map(x=>'<div class=prow><b>'+x.sym+'</b>'+['auto','propose','off'].map(k=>'<button data-bm='+k+' data-sym='+x.sym+(x.mode===k?' class=on':'')+'>'+MODE_N[k]+'</button>').join('')+(x.mode==='mixed'?'<span class=sm>разные режимы</span>':'')+'</div>').join('');
h+='<div class=prow><input id=bpSym placeholder="Новая пара, напр. SOLUSDT" autocapitalize=characters><select id=bpMode><option value=propose>Только предлагает</option><option value=auto>Торгует сам</option></select><button id=bpAdd class=go>Добавить</button></div>';
return h+'</details>'}
async function botAct(sym,mode){if(S.pbusy)return;const tx={auto:'Бот будет САМ открывать и закрывать позиции по '+sym+' (5 прогонов, статистика с этого момента).',propose:'Бот будет только ПРЕДЛАГАТЬ позиции по '+sym+': они появятся во вкладке «Вместе» с кнопками «Открыть» и «Отклонить». Сам он их не откроет.',off:'Выключить бота по '+sym+'? Его открытые позиции закроются по текущей цене, история сохранится.'};if(!confirm(tx[mode]+(mode!=='off'?' Прежние прогоны бота по этой паре (если есть) остановятся: позиции закроются по текущей цене, история сохранится.':'')))return;S.pbusy=1;try{ap(await api('/api/runs',{action:'bot_pair',sym:sym,mode:mode}))}catch(e){alert(e.message)}S.pbusy=0;renderRuns()}
const pdKey=p=>p.run+'|'+p.t_in+'|'+p.side;
function pdBtns(p){const w=(S.pdec||{})[pdKey(p)];if(w)return '<div class=pbt><button disabled style="opacity:.7;background:#6e7681;color:#fff;cursor:wait">'+w+'</button></div>';return "<div class=pbt><button class=go data-pd=open data-run="+p.run+" data-t="+p.t_in+" data-side="+p.side+">Открыть</button><button class=bad data-pd=reject data-run="+p.run+" data-t="+p.t_in+" data-side="+p.side+">Отклонить</button></div>"}
function toast(t,bad){let e=$('toast');if(!e){e=document.createElement('div');e.id='toast';e.style.cssText='position:fixed;left:50%;bottom:90px;transform:translateX(-50%);color:#fff;padding:12px 20px;border-radius:10px;font-size:15px;z-index:99;box-shadow:0 2px 12px #000a';document.body.appendChild(e)}e.style.background=bad?'#8e2c2c':'#238636';e.textContent=t;e.style.display='block';clearTimeout(S.tt);S.tt=setTimeout(()=>{e.style.display='none'},2500)}
async function decide(b){if(S.pbusy)return;const p=((S.prop||{}).pending||[]).find(x=>String(x.run)===b.dataset.run&&String(x.t_in)===b.dataset.t&&x.side===b.dataset.side),op=b.dataset.pd==='open';
if(!confirm((op?'ОТКРЫТЬ позицию?':'ОТКЛОНИТЬ предложение?')+(p?'\n\n'+p.sym+' · '+p.tf+' · '+(p.side==='L'?'LONG':'SHORT')+(op?'\nпо текущей цене '+fmt(p.cur):''):'')))return;
S.pbusy=1;const k=p?pdKey(p):b.dataset.run+'|'+b.dataset.t+'|'+b.dataset.side;(S.pdec=S.pdec||{})[k]=op?'Открываю…':'Отклоняю…';renderRuns();
try{ap(await api('/api/runs',{action:'decide',run:+b.dataset.run,t_in:+b.dataset.t,side:b.dataset.side,dec:b.dataset.pd}));toast(op?'✓ Открыто':'✓ Отклонено')}catch(e){toast('Ошибка: '+e.message,1);try{ap(await api('/api/runs'))}catch(_){}}delete S.pdec[k];S.pbusy=0;renderRuns()}
function bindPairs(){document.querySelectorAll('#runs [data-pc]').forEach(b=>{b.onclick=()=>{if(confirm('Закрыть '+b.dataset.sym+' по текущей цене? Результат попадёт в статистику; прогон продолжит работать, следующий сигнал откроет новую позицию.'))posAct(b.dataset.pc,{action:'pos_close'})}});document.querySelectorAll('#runs [data-ps]').forEach(b=>{b.onclick=()=>{S.mp=S.mp===b.dataset.ps?null:b.dataset.ps;renderRuns()}});document.querySelectorAll('#runs [data-pm]').forEach(b=>{b.onclick=()=>{const m=b.dataset.pm,v=parseFloat(($('mpv')||{}).value);if(m!=='clear'&&!(v>0)){alert('Укажите расстояние в %, например 1');return}posAct(b.dataset.k,{action:'pos_stop',mode:m,pct:v})}});document.querySelectorAll('#runs [data-bm]').forEach(b=>{b.onclick=()=>{if(!b.classList.contains('on'))botAct(b.dataset.sym,b.dataset.bm)}});const a=$('bpAdd');if(a)a.onclick=()=>{const s=($('bpSym').value||'').trim().toUpperCase();if(!s){alert('Введите пару, например SOLUSDT');return}botAct(s.endsWith('USDT')?s:s+'USDT',$('bpMode').value)};document.querySelectorAll('#runs [data-pd]').forEach(b=>{b.onclick=()=>decide(b)});document.querySelectorAll('#runs [data-pg]').forEach(b=>{b.onclick=()=>propChart(b)})}
function grpRow(n,g){return '<tr><td>'+n+'</td><td>'+g.n+'</td><td>'+g.closed+'</td><td>'+(g.win_pct==null?'—':g.win_pct+'%')+'</td><td class='+cls(g.net)+'>'+sg(g.net)+'</td><td class='+cls(g.pnl)+'>'+smoney(g.pnl)+'</td></tr>'}
function pgDraw(D){const cv=$('pgc');if(!cv)return;const C=D.chart,N=C.t.length,dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=Math.round(Math.min(window.innerHeight*0.62,520));cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
const Lm=4,Rm=62,Bm=16,pw=W-Lm-Rm,L=D.lines,ia=Math.max(0,C.t.findIndex(t=>t>=D.t_in)),V=S.pgv||(S.pgv={n:0,off:0,vz:1,vo:0});V.vz=Math.max(0.15,Math.min(12,V.vz||1));V.vo=V.vo||0;if(!V.n)V.n=Math.max(60,Math.min(N,N-Math.max(0,ia-60)+4));V.n=Math.max(15,Math.min(N,Math.round(V.n)));V.off=Math.max(-(V.n-5),Math.min(N-15,Math.round(V.off)));const end=N-V.off,E=Math.min(N,end),n0=Math.max(0,end-V.n),bars=V.n,bw=pw/bars,XE=Math.max(N+4,end+2);
const X=i=>Lm+(i-n0+0.5)*bw,ixT=t=>{let b=0;for(let i=0;i<N;i++){if(C.t[i]<=t)b=i}return b};
let hi=-1e99,lo=1e99;for(let i=n0;i<E;i++){hi=Math.max(hi,C.h[i]);lo=Math.min(lo,C.l[i])}
if(hi<lo){hi=C.c[N-1]*1.01;lo=C.c[N-1]*0.99}
const rg=(hi-lo)||hi*0.01,cen=(hi+lo)/2+V.vo*rg,half=rg*0.525/V.vz;hi=cen+half;lo=cen-half;const Y=p=>6+(hi-p)/(hi-lo)*(H-Bm-12);S.pgG={Lm:Lm,pw:pw,H:H,Bm:Bm,bw:bw,pxVo:1.05/V.vz/(H-Bm-12)};
g.font='10px system-ui';g.textBaseline='middle';g.textAlign='left';g.fillStyle='#6e7681';g.strokeStyle='#1b222c';
for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5;g.beginPath();g.moveTo(Lm,Y(p));g.lineTo(Lm+pw,Y(p));g.stroke();g.fillText(fmt(p),Lm+pw+4,Y(p))}
const stp=Math.max(1,Math.ceil(90/bw));g.textAlign='center';for(let i=n0;i<E;i+=stp)g.fillText(ft(C.t[i]),Math.min(X(i),W-Rm-30),H-7);g.textAlign='left';
for(let i=n0;i<E;i++){const up=C.c[i]>=C.o[i],x=X(i),w=Math.max(1,bw*0.7);g.strokeStyle=g.fillStyle=up?'#26a69a':'#ef5350';g.beginPath();g.moveTo(x,Y(C.h[i]));g.lineTo(x,Y(C.l[i]));g.stroke();if(bw>=1.6)g.fillRect(x-w/2,Y(Math.max(C.o[i],C.c[i])),w,Math.max(1,Y(Math.min(C.o[i],C.c[i]))-Y(Math.max(C.o[i],C.c[i]))))}
g.strokeStyle='#e3b341';g.lineWidth=1.2;g.beginPath();let on=false;for(let i=n0;i<E;i++){const v=C.ema20[i];if(v==null){on=false;continue}if(!on){g.moveTo(X(i),Y(v));on=true}else g.lineTo(X(i),Y(v))}g.stroke();g.lineWidth=1;
const seg=(i0,p0,i1,p1,col,w)=>{g.save();g.beginPath();g.rect(Lm,0,pw,H-Bm);g.clip();g.strokeStyle=col;g.lineWidth=w;g.beginPath();g.moveTo(X(i0),Y(p0));g.lineTo(X(i1),Y(p1));g.stroke();g.restore()};
const lbl=(txt,i0)=>{};
let drawn=false;
if(D.struct&&D.struct.A&&D.struct.B){const col={channel:'#58a6ff',range:'#f0883e',triangle:'#d2a8ff'}[D.struct.kind]||'#58a6ff',ext=[D.struct.A,D.struct.B];
 ext.forEach(a=>{const i1=ixT(a[0]),i2=ixT(a[2]);if(i1===i2){seg(n0,a[1],XE,a[1],col,1.8);return}const k=(a[3]-a[1])/(i2-i1);seg(Math.min(n0,i1),a[1]+k*(Math.min(n0,i1)-i1),XE,a[1]+k*(XE-i1),col,1.8)});drawn=true}
else if(D.ch){const c=D.ch,i0=c.i0-D.off,i1=c.i1-D.off,sl=(a,b)=>(b-a)/Math.max(1,i1-i0);[c.lo,c.up].forEach(v=>{const k=sl(v[0],v[1]);seg(i0,v[0],XE,v[1]+k*(XE-i1),'#79c0ff',1.8)});drawn=true}
const HL=(p,col,dash,txt)=>{if(p==null)return;const o=p>hi?1:p<lo?-1:0,yy=Math.max(9,Math.min(H-Bm-9,Y(p)));if(!o){g.strokeStyle=col;g.setLineDash(dash);g.beginPath();g.moveTo(Math.max(Lm,X(ia)),yy);g.lineTo(Lm+pw,yy);g.stroke();g.setLineDash([])}g.fillStyle=col;g.fillRect(Lm+pw+1,yy-7,Rm-2,14);g.fillStyle='#0d1117';g.font='bold 10px system-ui';g.fillText((o>0?'↑':o<0?'↓':'')+txt+' '+fmt(p),Lm+pw+3,yy);g.font='10px system-ui'};
if(D.vp){const V=D.vp,mw=pw*0.28;V.v.forEach((q,r)=>{const p0=V.lo+r*V.st,p1=p0+V.st;if(p1<lo||p0>hi||!q)return;const inVA=p0>=V.val-1e-12&&p1<=V.vah+1e-12,ya=Y(Math.min(p1,hi)),yb=Y(Math.max(p0,lo));g.fillStyle=inVA?'rgba(88,166,255,0.30)':'rgba(139,148,158,0.24)';g.fillRect(Lm,ya,mw*q/1000,Math.max(1,yb-ya-1))});(V.hvn||[]).forEach(p=>{if(p>lo&&p<hi){const yy=Y(p);g.fillStyle='rgba(88,166,255,0.95)';g.fillRect(Lm,yy-1,7,2)}});HL(V.poc,'#f2cc60',[5,3],'POC');HL(V.vah,'#58a6ff',[2,3],'VAH');HL(V.val,'#58a6ff',[2,3],'VAL');if(V.ypoc)HL(V.ypoc,'#d2a8ff',[2,4],'вчера POC')}
(D.walls||[]).slice().sort((a,b)=>b.v-a.v).slice(0,8).forEach(w=>{if(!(w.p>lo&&w.p<hi))return;const yy=Y(w.p),cc=w.s==='b'?'46,160,67':'248,81,73';g.save();g.fillStyle='rgba('+cc+',0.18)';g.fillRect(Lm,yy-3,pw,6);g.strokeStyle='rgba('+cc+',0.9)';g.lineWidth=1;g.setLineDash([6,3]);g.beginPath();g.moveTo(Lm,yy);g.lineTo(Lm+pw,yy);g.stroke();g.restore();g.fillStyle='rgba('+cc+',1)';g.font='9px system-ui';g.textAlign='left';g.fillText((w.s==='b'?'покупатели ':'продавцы ')+'×'+w.m+' · '+(w.v>=1000?(w.v/1000).toFixed(1)+'k':w.v)+'$',Lm+4,yy-8);g.font='10px system-ui'});
HL(L.tp,'#3fb950',[],'цель');HL(L.be_trigger,'#d29922',[3,3],'до БУ');HL(L.be,'#f0883e',[5,3],'БУ');HL(L.stop0,'#f85149',[],'стоп');if(L.stop!==L.stop0)HL(L.stop,'#ff7b72',[2,3],'стоп тек.');HL(L.entry,'#58a6ff',[],'вход');
const xa=X(ia),y=Y(L.entry),sz=5;if(ia>=n0&&ia<E&&y>0&&y<H-Bm){g.fillStyle=D.side==='L'?'#3fb950':'#f85149';g.beginPath();if(D.side==='L'){g.moveTo(xa-sz,y+sz*2);g.lineTo(xa+sz,y+sz*2);g.lineTo(xa,y+2)}else{g.moveTo(xa-sz,y-sz*2);g.lineTo(xa+sz,y-sz*2);g.lineTo(xa,y-2)}g.fill()}
const lp=C.c[N-1];if(lp>lo&&lp<hi){g.strokeStyle='#8b949e';g.setLineDash([2,3]);g.beginPath();g.moveTo(Lm,Y(lp));g.lineTo(Lm+pw,Y(lp));g.stroke();g.setLineDash([]);g.fillStyle='#30363d';g.fillRect(Lm+pw+1,Y(lp)-7,Rm-2,14);g.fillStyle='#fff';g.fillText(fmt(lp),Lm+pw+4,Y(lp))}
if(!drawn){g.fillStyle='#8b949e';g.textAlign='left';g.fillText('линия канала для этой сделки не сохранилась',Lm+6,H-24)}}
function pgBind(){const c=$('pgc'),P=new Map();let g0=null,lt=0;c.style.touchAction='none';
const pxy=e=>{const r=c.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}},zone=q=>{const G=S.pgG;return q.x>G.Lm+G.pw?'price':(q.y>G.H-G.Bm-2)?'time':'plot'};
c.onpointerdown=e=>{c.setPointerCapture(e.pointerId);const q=pxy(e),V=S.pgv;P.set(e.pointerId,q);if(P.size===1)g0={x:q.x,y:q.y,off:V.off,vo:V.vo,vz:V.vz,n:V.n,zone:zone(q),moved:false};else if(P.size===2&&g0){const a=[...P.values()];g0.pinch={dx:Math.abs(a[0].x-a[1].x),dy:Math.abs(a[0].y-a[1].y),n:V.n,vz:V.vz};g0.moved=true}};
c.onpointermove=e=>{if(!P.has(e.pointerId)||!g0)return;const q=pxy(e),V=S.pgv,G=S.pgG;P.set(e.pointerId,q);
 if(P.size===2&&g0.pinch){const a=[...P.values()],dx=Math.abs(a[0].x-a[1].x),dy=Math.abs(a[0].y-a[1].y);if(g0.pinch.dy>g0.pinch.dx*1.2){V.vz=g0.pinch.vz*Math.max(dy,10)/Math.max(g0.pinch.dy,10)}else{V.n=Math.round(g0.pinch.n*Math.max(g0.pinch.dx,10)/Math.max(dx,10))}pgDraw(S.pg);return}
 const dx=q.x-g0.x,dy=q.y-g0.y;if(Math.abs(dx)>5||Math.abs(dy)>5)g0.moved=true;if(!g0.moved)return;
 if(g0.zone==='price')V.vz=g0.vz*Math.exp(-dy/120);else if(g0.zone==='time')V.n=Math.round(g0.n*Math.exp(-dx/120));else{V.off=Math.round(g0.off+dx/G.bw);V.vo=g0.vo+dy*G.pxVo}
 pgDraw(S.pg)};
c.onpointerup=e=>{if(P.size===1&&g0&&!g0.moved){const t=Date.now();if(t-lt<350){S.pgv=null;lt=0;P.delete(e.pointerId);g0=null;pgDraw(S.pg);return}lt=t}P.delete(e.pointerId);if(!P.size)g0=null};
c.onpointercancel=e=>{P.delete(e.pointerId);if(!P.size)g0=null};
c.onwheel=e=>{e.preventDefault();const V=S.pgv,f=e.deltaY>0?1.15:0.87;if(e.shiftKey)V.vz=V.vz/f;else if(e.altKey)V.off+=(e.deltaY>0?1:-1)*Math.max(1,Math.round(V.n*0.1));else V.n=Math.round(V.n*f);pgDraw(S.pg)};c.ondblclick=()=>{S.pgv=null;pgDraw(S.pg)}}
async function pgTick(){const m=$('pgm');if(!m||m.style.display==='none'||!S.pgb){return}try{const D=await api('/api/prop_chart?run='+S.pgb.run+'&t_in='+S.pgb.t+'&side='+S.pgb.side);if(m.style.display!=='none'){S.pg=D;pgDraw(D);const e=$('pgs');if(e)e.textContent=(D.open?'идёт':'закрыта: '+D.reason)+' · обновлено '+new Date().toLocaleTimeString().slice(0,8)}}catch(e){}}
async function propChart(b){let m=$('pgm');if(!m){m=document.createElement('div');m.id='pgm';m.style.cssText='position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.82);overflow:auto;padding:8px';document.body.appendChild(m)}
S.pgv=null;S.pgb={run:b.dataset.run,t:b.dataset.t,side:b.dataset.side};m.style.display='block';m.innerHTML='<div class=card style="margin:0"><div style="display:flex;justify-content:space-between;align-items:center"><b>Загрузка графика…</b><button id=pgx>✕</button></div></div>';$('pgx').onclick=()=>{m.style.display='none'};
try{const D=await api('/api/prop_chart?run='+b.dataset.run+'&t='+b.dataset.t+'&t_in='+b.dataset.t+'&side='+b.dataset.side);S.pg=D;const st=D.struct,kd={channel:'канал',range:'флэт',triangle:'треугольник'};
m.innerHTML='<div class=card style="margin:0"><div style="display:flex;justify-content:space-between;align-items:center"><b>'+D.sym+' · '+D.tf+' · '+(D.side==='L'?'LONG':'SHORT')+(D.sig==='k'?' · пробой':D.sig==='b'?' · отбой':D.sig==='f'?' · возврат':'')+'</b><button id=pgx>✕</button></div><div class=sm style="margin:4px 0">'+(st?kd[st.kind]+' #'+st.id+' (ваш рисунок)':D.ch?'канал бота (синие линии)':'канал не сохранился')+' · голубая — вход, красная — стоп, жёлтая пунктир — до безубытка, оранжевая — безубыток'+(D.lines.tp?', зелёная — цель':'')+'. Жёлтая кривая — EMA20.'+(D.walls&&D.walls.length?' Зелёные/красные полосы — стенки стакана (покупатели/продавцы, ×N — во сколько раз крупнее обычного окна 0.06%), '+(D.open?'сейчас':'на момент входа')+', снимок '+new Date(D.walls_t).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})+'.':(D.open?'':' Стенок на момент входа нет: запись стакана идёт с 28.10 16:32 UTC.'))+(D.vp?' Профиль объёма от начала формации ('+(D.vp.mode==='flat'?'Флэт':'Тренд')+'): гистограмма слева (светлее — зона стоимости), POC жёлтая, VAH/VAL синие, вчерашний POC сиреневая, синие засечки — узлы HVN.':'')+'</div><canvas id=pgc style="width:100%;display:block"></canvas><div class=sm id=pgs style="margin-top:4px"></div><div class=sm>Живой график: обновляется каждые 10 с. Тяните по графику — сдвиг по времени и цене; по правой шкале — масштаб по цене, по нижней — по времени; щипок (по горизонтали/вертикали) — то же; двойной тап — сброс.</div></div>';
$('pgx').onclick=()=>{m.style.display='none'};pgBind();pgDraw(D);if(!S.pgT)S.pgT=setInterval(pgTick,10000)}catch(e){m.innerHTML='<div class=card style="margin:0"><b>Ошибка:</b> '+e.message+' <button id=pgx>✕</button></div>';$('pgx').onclick=()=>{m.style.display='none'}}}
function lgStat(a,since,fw){const L=((a&&a.log)||[]).filter(t=>!t.open&&(since==null||(fw?t.t_in>=since:t.t_in<since)));if(!L.length)return 'сделок нет';const w=L.filter(t=>t.pnl>0).length,n=L.reduce((s,t)=>s+t.net,0),p=L.reduce((s,t)=>s+t.pnl,0);return L.length+' сд. · плюс '+Math.round(100*w/L.length)+'% · в среднем '+(n/L.length>=0?'+':'')+(n/L.length).toFixed(3)+'% за сделку · итог '+smoney(p)}
function sgLine(s){return s.n+' сигн., плюс '+(s.win_pct==null?'—':s.win_pct+'%')+', итог '+smoney(s.total)}
function fTxt(f){const p=[];if(f.min_stop_atr)p.push('стоп не ближе '+f.min_stop_atr+' ATR');if(f.max_stop_atr)p.push('стоп не дальше '+f.max_stop_atr+' ATR');if(f.max_tp_atr)p.push('цель не дальше '+f.max_tp_atr+' ATR');if(f.min_rr)p.push('выгода/риск не меньше '+f.min_rr);p.push(f.sides==='LS'?'лонг и шорт':f.sides==='L'?'только лонг':'только шорт');return p.join(' · ')}
function fDt(ms){return new Date(ms).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}
function vLine(s){return s.n+' сигн., плюс '+(s.win_pct==null?'—':s.win_pct+'%')+', '+(s.avg_net==null?'':'в среднем '+(s.avg_net>=0?'+':'')+s.avg_net.toFixed(3)+'% за сделку, ')+'итог '+smoney(s.total)}
function verCard(C){const V=C.versions||[];if(!V.length)return '';let h='<div class=sm style="margin-top:8px"><b>История версий фильтра</b> — у каждой версии свой период; результат считается по сигналам, пришедшим пока она действовала, поэтому смена фильтра ничего не стирает</div>';V.forEach((v,i)=>{h+='<div class=sm style="margin-top:6px"><b>№'+(V.length-i)+' · '+fDt(v.since)+' — '+(v.until?fDt(v.until):'сейчас')+'</b><br>'+fTxt(v.f)+'<br>с фильтром: '+vLine(v.cand)+'<br>без фильтра (тот же период): '+vLine(v.all)+'</div>'});return h}
function vpSetTf(){const t=((S.load&&S.load.vp)||{}).tfs||[];return t.includes(S.vpSetTf)?S.vpSetTf:(t[0]||'5m')}
function vpCard(){const tfs=((S.load&&S.load.vp)||{}).tfs||[],TF=vpSetTf(),VR=(S.runs||[]).filter(r=>r.stop_ms==null&&r.track==='vp'&&r.cfg.tf===TF),R=VR[0],C=R?R.cfg:{};const F=[['vp_mode','Режим','sel',['auto','flat','trend'],{auto:'авто (Флэт, если есть, иначе Тренд)',flat:'только Флэт',trend:'только Тренд'}],['vp_va','Зона стоимости, % объёма','num'],['vp_rows','Строк профиля','num'],['zz_depth','ZigZag Depth (0 — по таймфрейму)','num'],['zz_dev','ZigZag Deviation, % (0 — по таймфрейму)','num'],['zz_back','ZigZag Backstep (0 — по таймфрейму)','num'],['vp_flat_delta','Дельта флэта, % (вершины/впадины на близких уровнях)','num'],['vp_hvn','HVN: объём строки не меньше N средних','num'],['vp_lvn','LVN (пустота): не больше доли средней','num'],['vp_sl_atr','Стоп пробоя за границей, ATR','num'],['vp_rr','Риск/прибыль у пробоя','num'],['vp_min_rr','Минимальный риск/прибыль сигнала','num'],['vp_be_frac','Безубыток на доле пути к цели','num'],['vp_bo_entry','Вход на пробое','sel',['close','retest'],{close:'на открытии после закрытия свечи',retest:'на ретесте границы'}],['vp_be_poc','Безубыток при достижении POC','bool'],['vp_bounce','Торговать отбой','bool'],['vp_breakout','Торговать пробой','bool'],['vp_return','Возврат после ложного пробоя','bool']];let h='<details class=card data-k=vpset><summary style="font-size:15px;font-weight:600">Настройки профиля объёма · '+TF+(R?'':' (нет прогонов)')+'</summary><div style="margin:8px 0">'+tfs.map(t=>'<button data-vstf='+t+(t===TF?' class=on':'')+' style="margin-right:4px">'+t+'</button>').join('')+'</div><div class=sm style="margin:8px 0">Настройки отдельные для каждого таймфрейма: сохранение действует на все пары этого ТФ ('+VR.length+' прогонов), остальные ТФ не меняются; история на этом ТФ пересчитывается. Дата старта профиля общая (карточка выше). Профиль всегда считается от начала формации до текущей свечи: во Флэте — от самой левой вершины/впадины серии, в Тренде — от начала последнего завершённого луча ZigZag.</div>';h+=F.map(f=>{const v=C[f[0]];let i;if(f[2]==='sel')i='<select id=vpf_'+f[0]+'>'+f[3].map(o=>'<option value='+o+(v===o?' selected':'')+'>'+f[4][o]+'</option>').join('')+'</select>';else if(f[2]==='bool')i='<input type=checkbox id=vpf_'+f[0]+(v?' checked':'')+'>';else if(f[2]==='txt')i='<input id=vpf_'+f[0]+' value="'+(v||'auto')+'" style="width:150px">';else i='<input id=vpf_'+f[0]+' type=number step=any value="'+(v==null?'':v)+'" style="width:90px">';return '<div class=prow><span class=sm style="flex:1">'+f[1]+'</span>'+i+'</div>'}).join('');return h+'<button id=vpsave onclick="vpSave()" style="margin-top:8px">Сохранить для '+TF+' ('+VR.length+' прогонов)</button> <span id=vpmsg class=sm></span></details>'}
function vpStartCard(){const R=(S.runs||[]).find(r=>r.stop_ms==null&&r.track==='vp');if(!R)return '';const u=ms=>new Date(ms).toISOString().slice(0,16).replace('T',' ');return '<div class=card><b>Счёт «Профиль» считается с:</b> '+u(R.start_ms)+' UTC<div class=sm style="margin:6px 0">Сделки раньше этой даты в журнал и баланс не входят. Дата по UTC (Одесса = UTC+2/+3).</div><div class=prow><input id=vps_start value="'+u(R.start_ms)+'" style="width:150px"> <button onclick="vpStart()">Применить дату</button> <button onclick="vpStart(\'now\')">С этого момента</button></div><span id=vps_msg class=sm></span></div>'}
async function vpStart(v){const s=v||$('vps_start').value.trim(),m=$('vps_msg');if(m)m.textContent='Пересчёт счёта… до минуты';try{const j=await api('/api/runs',{action:'vp_start',start:s});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.vpDirty=0;renderRuns()}catch(e){const m2=$('vps_msg');if(m2)m2.textContent='Ошибка: '+e.message}}
async function vpSave(){const cfg={};document.querySelectorAll('[id^=vpf_]').forEach(e=>{const k=e.id.slice(4);cfg[k]=e.type==='checkbox'?e.checked:e.type==='number'?(e.value===''?undefined:+e.value):e.value});const b=$('vpsave'),m=$('vpmsg');if(b)b.disabled=true;if(m)m.textContent='Сохраняю и пересчитываю… до минуты';try{const j=await api('/api/runs',{action:'vp_cfg',cfg:cfg,tf:vpSetTf()});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.load=j.load||S.load;S.vpDirty=0;renderRuns();const m2=$('vpmsg');if(m2)m2.textContent='Сохранено '+new Date().toLocaleTimeString('ru-RU')}catch(e){if(b)b.disabled=false;if(m)m.textContent='Ошибка: '+e.message}}
document.addEventListener('input',e=>{if(e.target&&e.target.id&&/^vp[fs]_/.test(e.target.id))S.vpDirty=1},true);document.addEventListener('change',e=>{if(e.target&&e.target.id&&/^vp[fs]_/.test(e.target.id))S.vpDirty=1},true)
function expCard(){const E=(S.acc||{}).exp||{};const st=o=>o&&o.n?('сделок '+o.n+(o.open?' (+'+o.open+' откр.)':'')+' · плюс '+Math.round(o.w/o.n*100)+'% · средний '+sg(o.avg)+'% · сумма '+sg(o.sum)+'%'):('сделок нет'+(o&&o.open?' (откр. '+o.open+')':''));
const bar=(p)=>{const w=Math.min(100,p);return '<div style="height:8px;background:#21262d;border-radius:4px;margin:6px 0"><div style="width:'+w+'%;height:8px;background:'+(p>=100?'#3fb950':p>=50?'#d29922':'#58a6ff')+';border-radius:4px"></div></div><div class=sm>Набрано '+p+' из 50 (минимум для первого вывода) · до 100 (надёжнее)'+(p>=100?' — <b>можно делать вывод</b>':p>=50?' — <b>можно сделать первый вывод</b>':'')+'</div>'};
const dt=ms=>ms?new Date(ms).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';
const tfs=x=>Object.keys(x.per_tf||{}).map(tf=>'<div class=sm>'+tf+': эксперимент — '+st(x.per_tf[tf].exp)+'<br>&nbsp;&nbsp;&nbsp;&nbsp;база — '+st(x.per_tf[tf].base)+'</div>').join('');
let h='<div class=card><h4>Эксперименты (проверка вперёд)</h4><div class=sm>Это не счета, а параллельные прогоны для проверки идей. Считаются только сделки после запуска. Основные счета эти прогоны не затрагивают.</div></div>';
const A=E.A,B=E.B;
if(A)h+='<div class=card><h4>А · пробой по тренду канала</h4><div class=sm>Прогонов '+A.runs+' (1h, 4h). Разрешён пробой в сторону наклона канала. Запуск '+dt(A.since)+'.<br>Прогресс считается по сделкам, которых у обычного бота нет (то есть именно пробои по тренду).</div>'+bar(A.progress)+'<div class=sm><b>Только пробои по тренду:</b> '+st(A.extra)+'<br><b>Все сделки эксперимента:</b> '+st(A.exp)+'<br><b>Обычный бот, те же пары и ТФ:</b> '+st(A.base)+'</div>'+tfs(A)+'</div>';
if(B)h+='<div class=card><h4>Б · лесенка БУ</h4><div class=sm>Прогонов '+B.runs+' (5m, 15m, 1h). Те же сигналы, что у бота; на 75% пути к цели стоп уходит на 35% пути. Запуск '+dt(B.since)+'.<br>Прогресс считается по парным закрытым сделкам, где лесенка изменила результат (остальные у обоих одинаковы).</div>'+bar(B.progress)+'<div class=sm><b>Эксперимент:</b> '+st(B.exp)+'<br><b>Обычный бот:</b> '+st(B.base)+'<br>Выходов по лесенке: '+B.lad+' · парных сделок: '+B.pairs+' · лучше / хуже базы: '+B.better+' / '+B.worse+' · сумма разницы: '+sg(B.diff)+'%</div>'+tfs(B)+'</div>';
const mkCD=(x,ttl,desc)=>x?'<div class=card><h4>'+ttl+'</h4><div class=sm>Прогонов '+x.runs+' (15m, 1h, 4h). '+desc+' Запуск '+dt(x.since)+'.<br>Прогресс считается по закрытым сделкам, у которых цель отличается от обычной.</div>'+bar(x.progress)+'<div class=sm><b>Эти сделки у эксперимента:</b> '+st(x.changed)+'<br><b>Те же сделки у обычного бота:</b> '+st(x.changed_base)+'<br><b>Все сделки эксперимента:</b> '+st(x.exp)+'<br><b>Обычный бот, те же пары и ТФ:</b> '+st(x.base)+'</div>'+tfs(x)+'</div>':'';
h+=mkCD(E.C,'В · цель треугольника по высоте основания','У пробоя треугольника цель = высота основания от пробитой границы (раньше цели часто не было).')+mkCD(E.D,'Г · цель у ближайшего уровня','У пробоя цель у ближайшего подтверждённого пивота по ходу сделки (не ближе 0.5 ATR).');
return h}
function candCard(){const A=S.acc||{},C=A.cand||{},F=C.filter,B=(A.both||{}).signals,K=C.signals;if(!F)return '';
const sd=F.sides==='LS'?'лонг и шорт':F.sides==='L'?'только лонг':'только шорт';
const rule=[F.min_stop_atr?'стоп не ближе '+F.min_stop_atr+' ATR':'',F.max_tp_atr?'цель не дальше '+F.max_tp_atr+' ATR':'',F.max_stop_atr?'стоп не дальше '+F.max_stop_atr+' ATR':'',F.min_rr?'выгода/риск не меньше '+F.min_rr:''].filter(x=>x).join(' · ')||'без ограничений';
let h='<div class=card><h4>Фильтр счёта «Кандидат»</h4><div class=sm>Берёт сигналы бота, прошедшие фильтр, и открывает их сам, без вашего решения (вход по цене бота). Фильтр: '+rule+' · '+sd+'. Прошло '+F.passed+' из '+F.total+' сигналов. Условия взяты из разбора 150 закрытых предложений: стоп уже 0.9 ATR выбивается шумом чаще (плюс 16% против 40%), а цель ближе даёт чуть лучше. Итог в той выборке всё равно отрицательный — это гипотеза, её проверяют новые сделки.</div>';
if(B&&K)h+='<div class=sm style="margin-top:6px">Без фильтра (все предложения): '+B.n+' сигн., плюс '+(B.win_pct==null?'—':B.win_pct+'%')+', итог '+smoney(B.total)+'<br>С фильтром: '+K.n+' сигн., плюс '+(K.win_pct==null?'—':K.win_pct+'%')+', итог '+smoney(K.total)+'</div>';
const AB=(A.bot||{}).account,AC=C.account,sn=F.since,sd0=sn?new Date(sn).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
h+='<div class=sm style="margin-top:8px"><b>Сравнение по сделкам</b> (закрытые, в % позиции)<br>Бот · все: '+lgStat(AB,null,true)+'<br>Кандидат · все: '+lgStat(AC,null,true)+'</div>';
h+=verCard(C);
const V=S.cf||{},g=(k)=>V[k]!==undefined?V[k]:F[k];
h+='<div class=sm style="margin-top:8px"><b>Править фильтр</b> (0 — условие выключено). Расстояния считаются от входа бота, ATR — размах свечи входного ТФ, так пары сравнимы между собой.</div>'
+'<div class=sm style="margin-top:4px">Стоп не ближе, ATR: <input type=number step=0.1 min=0 style="width:64px" value="'+g('min_stop_atr')+'" oninput="S.cf=S.cf||{};S.cf.min_stop_atr=this.value"></div>'
+'<div class=sm style="margin-top:4px">Цель не дальше, ATR: <input type=number step=0.1 min=0 style="width:64px" value="'+g('max_tp_atr')+'" oninput="S.cf=S.cf||{};S.cf.max_tp_atr=this.value"></div>'
+'<div class=sm style="margin-top:4px">Стоп не дальше, ATR: <input type=number step=0.1 min=0 style="width:64px" value="'+g('max_stop_atr')+'" oninput="S.cf=S.cf||{};S.cf.max_stop_atr=this.value"></div>'
+'<div class=sm style="margin-top:4px">Выгода/риск не меньше: <input type=number step=0.1 min=0 style="width:64px" value="'+g('min_rr')+'" oninput="S.cf=S.cf||{};S.cf.min_rr=this.value"></div>'
+'<div class=sm style="margin-top:4px">Стороны: <select onchange="S.cf=S.cf||{};S.cf.sides=this.value"><option value=LS'+(g('sides')==='LS'?' selected':'')+'>лонг и шорт</option><option value=L'+(g('sides')==='L'?' selected':'')+'>только лонг</option><option value=S'+(g('sides')==='S'?' selected':'')+'>только шорт</option></select></div>'
+'<div style="margin-top:8px"><button onclick="saveCand(false)">Сохранить</button> <button onclick="saveCand(true)">По умолчанию</button></div>';
return h+'</div>'}
async function saveCand(rs){try{await api('/api/cand',rs?{reset:true}:{filter:S.cf||{}});S.cf=null;await loadRuns()}catch(e){alert(e.message)}}
function propCard(){const P=S.prop||{pending:[],rows:[],stats:null},st=P.stats,np=botPairs().filter(x=>x.mode==='propose').length;
let h='<div class=card><h4>Предложения бота · сейчас</h4><div class=sm>Бот ищет сигналы по парам в режиме «Только предлагает» и сам их не открывает. «Открыть» — позиция попадёт в счёт «Вместе» по текущей цене и дальше пойдёт по тем же правилам (стоп, безубыток, цель), что и у бота. «Отклонить» — предложение уйдёт, а мы запомним, чем бы оно кончилось.</div>';
if(!np)h+='<div class=sm style="margin-top:8px;color:#d29922">Нет пар в режиме «Только предлагает». Откройте блок «Пары бота» выше и переведите нужные пары в этот режим — бот начнёт присылать предложения.</div>';
else if(!P.pending.length)h+='<div class=sm style="margin-top:8px">Предложений сейчас нет — бот следит за парами в режиме «Только предлагает» ('+np+', по 5 таймфреймов каждая).</div>';
h+=P.pending.map(p=>'<div class=prop><div><b>'+p.sym+' · '+p.tf+' · '+(p.side==='L'?'LONG':'SHORT')+'</b>'+(p.sig==='k'?' · пробой':p.sig==='b'?' · отбой':p.sig==='f'?' · возврат':'')+'</div><div class=sm style="margin-top:3px">предложено '+ft(p.t_in)+' ('+ago(Date.now()-p.t_in)+' назад) · вход бота '+fmt(p.p_in)+' · сейчас '+fmt(p.cur)+' (<span class='+cls(p.move)+'>'+sg(p.move)+'%</span> от входа бота)</div><div class=sm>стоп '+fmt(p.stop)+' (−'+p.to_stop.toFixed(2)+'% от текущей цены)'+(p.tp?' · цель '+fmt(p.tp)+' (+'+p.to_tp.toFixed(2)+'%)':'')+(p.rr?' · выгода/риск '+p.rr.toFixed(2):'')+(p.be?' · ✓ безубыток уже взведён':'')+'</div>'+(p.stop_pct!=null?'<div class=sm>вход→стоп '+p.stop_pct.toFixed(2)+'%'+(p.stop_atr!=null?' ('+p.stop_atr.toFixed(1)+' ATR)':'')+(p.tp_pct!=null?' · вход→цель '+p.tp_pct.toFixed(2)+'%'+(p.tp_atr!=null?' ('+p.tp_atr.toFixed(1)+' ATR)':''):'')+(p.atr!=null?' · 1 ATR = '+p.atr.toFixed(2)+'%':'')+'</div>':'')+(p.atr!=null?'<div class=sm>фильтр «Кандидат»: '+(p.cand_ok?'<b class=up>проходит</b>':'не проходит — '+p.cand_why)+'</div>':'')+pdBtns(p)+'<div class=pbt style="margin-top:6px"><button data-pg=1 data-run='+p.run+' data-t='+p.t_in+' data-side='+p.side+' style="width:100%">📈 График</button></div></div>').join('');
h+='</div>';
if(!st||(!st.all.n&&!np))return h;
h+='<div class=card><h4>Статистика решений</h4><div class=sm>Net% — результат закрытых позиций после комиссии; $ — при ставке 6 $ на позицию. Для «отклонено» и «без решения» это то, что получил бы бот, если бы позицию открыли. Ждут решения сейчас: '+st.pending+'.</div>';
h+='<div class=sc><table><tr><th>Решение</th><th>Шт</th><th>Закрыто</th><th>Прибыльных</th><th>Net%</th><th>$</th></tr>'+grpRow('Открыто вами',st.opened)+grpRow('Отклонено',st.rejected)+grpRow('Без решения',st.missed)+grpRow('Все предложения',st.all)+'</table></div>';
if(st.decided_closed)h+='<div class=need>Точность решений: <b>'+st.right+' из '+st.decided_closed+' ('+st.right_pct+'%)</b><br><span class=sm>засчитывается, если вы открыли то, что закрылось в плюс, или отклонили то, что закрылось в минус. Ваш отбор: '+sg(st.opened.net)+'% против '+sg(st.all.net)+'%, если бы брали каждое предложение (все закрытые).</span></div>';
else h+='<div class=sm style="margin-top:8px">Точность решений появится, когда закроется первая позиция, по которой вы приняли решение.</div>';
h+='</div>';
const rw=P.rows||[];
if(rw.length){const hc=[{l:'Пара · ТФ',t:1,v:r=>r.sym+' '+r.tf,h:r=>'<td>'+r.sym+' · '+r.tf+'</td>'},{l:'Сторона',t:1,v:r=>r.side+(r.sig||''),h:r=>'<td>'+(r.side==='L'?'лонг':'шорт')+(r.sig==='k'?' · пробой':r.sig==='b'?' · отбой':r.sig==='f'?' · возврат':'')+'</td>'},{l:'Предложено',v:r=>r.t_in,h:r=>'<td>'+ft(r.t_in)+'</td>'},{l:'Решение',t:1,v:r=>r.status,h:r=>'<td>'+PST[r.status]+(r.t_dec?' '+ft(r.t_dec):'')+'</td>'},{l:'Net%',v:r=>r.net,h:r=>'<td class='+(r.status==='opened'?cls(r.net):'fl')+'>'+(r.status==='opened'?'':'(')+(r.open?'идёт ':'')+sg(r.net)+(r.status==='opened'?'':')')+'</td>'},{l:'Итог',t:1,v:r=>r.open?'открыта':r.reason,h:r=>'<td>'+(r.open?'открыта':r.reason)+(r.be?' ✓БУ':'')+'</td>'}];
h+='<details class=card data-k=prh><summary style="font-size:15px;font-weight:600">История предложений ('+rw.length+')</summary><div class=sm style="margin:8px 0 2px">В скобках — результат, который получил бы бот (вы не открывали). Нажмите на заголовок, чтобы отсортировать.</div><div class="sc stk" style="max-height:340px;overflow-y:auto">'+stbl('prop',hc,rw,{c:2,d:-1})+'</div></details>'}
return h}
function renderRuns(){const ae=document.activeElement;if(ae&&(ae.tagName==='INPUT'||ae.tagName==='SELECT')&&ae.closest&&ae.closest('#runs'))return;const SK=e=>{const d=e.closest('details');return d?d.dataset.k:'sum'},SC={};document.querySelectorAll('#runs .sc').forEach(e=>{SC[SK(e)]=[e.scrollLeft,e.scrollTop]});const WX=window.scrollX,WY=window.scrollY;const OPEN=new Set(Array.from(document.querySelectorAll('#runs details[open]')).map(e=>e.dataset.k));const AK=(S.acc||{})[S.track]||{},R=(S.runs||[]).filter(r=>(r.track||'me')===S.track&&(S.track!=='bot'||(r.mode||'auto')!=='propose'));const VPV={};if(S.vpDirty)document.querySelectorAll('#runs [id^=vpf_],#runs [id^=vps_]').forEach(e=>{VPV[e.id]=e.type==='checkbox'?e.checked:e.value});const FIN=h=>{$('runs').innerHTML=h;bindTrk();document.querySelectorAll('#runs details').forEach(e=>{if(OPEN.has(e.dataset.k))e.open=true});Object.keys(VPV).forEach(id=>{const e=document.getElementById(id);if(e){if(e.type==='checkbox')e.checked=VPV[id];else e.value=VPV[id]}});document.querySelectorAll('#runs .sc').forEach(e=>{const s=SC[SK(e)];if(s){e.scrollLeft=s[0];e.scrollTop=s[1]}});window.scrollTo(WX,WY)};if(S.track==='exp'){FIN(loadLine()+trackBar()+expCard());return}const top=loadLine()+rotCard()+trackBar()+(S.track!=='me'&&S.track!=='cand'&&S.track!=='vp'?pairsCard():'')+(S.track==='vp'?vpStartCard()+vpTfCard()+vpCard():'')+acctCard(AK.account,TRK[S.track][1])+sigCard(AK.signals,S.track==='both');if(S.track==='both'){FIN(top+propCard());return}if(S.track==='cand'){FIN(top+candCard());return}if(!R.length){FIN(top+'<div class=card>Прогонов этой стороны пока нет.</div>');return}
 const last=r=>r.trades.length?Math.max.apply(null,r.trades.map(x=>x.t_in)):0;
 const has=R.filter(r=>r.stats.n>0).sort((a,b)=>(b.stats.open-a.stats.open)||(last(b)-last(a))),emp=R.filter(r=>r.stats.n===0);
 const sc0=[{l:'#',v:r=>r.id,h:r=>'<td>'+r.id+'</td>'},{l:'Пара · ТФ',t:1,v:r=>r.sym+' '+r.cfg.tf,h:r=>'<td>'+r.sym+' · '+r.cfg.tf+'</td>'},{l:'Сделок',v:r=>r.stats.n,h:r=>'<td>'+r.stats.n+'</td>'},{l:'Откр.',v:r=>r.stats.open,h:r=>'<td>'+(r.stats.open||'—')+'</td>'},{l:'Net%',v:r=>r.stats.net,h:r=>'<td class=\"'+cls(r.stats.net)+'\"><b>'+sg(r.stats.net)+'</b></td>'}];
 let h=top+'<div class=card><h4>Сводка по прогонам</h4><div class=sm>Прогонов '+R.length+' · со сделками '+has.length+' · открытых позиций '+R.reduce((s,r)=>s+r.stats.open,0)+'</div>';
 if(has.length){h+='<div class=sc>'+stbl('sum_has',sc0,has)+'</div>'}
 else h+='<div class=sm>Сделок пока нет: вход только когда свеча коснулась границы активного (не удалённого) канала — отбой, или закрылась за ней — пробой. Сигналы считаются только по свечам после момента, когда канал нарисован.</div>';
 h+='</div>'+has.map(runCard).join('');
 if(emp.length){const et='<div class=sc>'+stbl('sum_emp',sc0,emp.slice().sort((a,b)=>a.id-b.id),{c:0,d:1})+'</div>';h+='<details class=card data-k=emp style="border-color:#1f6feb"><summary style="font-size:15px;font-weight:600;color:#fff;background:#1f6feb;border-radius:6px;padding:9px 11px">Прогоны без сделок ('+emp.length+')</summary><div class=sm style="margin:8px 0 2px">Прогоны, по которым пока не было ни одной сделки. Подробные карточки — ниже таблицы.</div>'+et+emp.map(runCard).join('')+'</details>'}
 FIN(h)}
async function loadRuns(){try{const j=await api('/api/runs');if(j.loading){$('runs').textContent='Идёт первый расчёт после запуска, обычно до минуты…';return}S.runs=j.runs;S.notional=j.notional;S.hand=j.hand||{};S.acc=j.accounts||{};S.load=j.load||null;if(!S.screenAsked){S.screenAsked=1;loadScreen()}renderRuns()}catch(e){$('runs').textContent='Ошибка: '+e.message}}
async function runAct(a,id){if(a==='delete'&&!confirm('Удалить прогон #'+id+'?'))return;if(a==='stop'&&!confirm('Остановить прогон #'+id+'? Открытая позиция будет закрыта по текущей цене.'))return;try{const j=await api('/api/runs',{action:a,id:id});S.runs=j.runs;S.notional=j.notional;S.acc=j.accounts||{};S.load=j.load||S.load;renderRuns()}catch(e){alert(e.message)}}
function chart(){
 const C=S.D&&S.D.chart;if(!C)return;const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=420;
 cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
 const N=C.t.length,L=4,R=58,B=16,pw=W-L-R;
 V.n=Math.max(10,Math.min(1000,Math.round(V.n)));V.off=Math.max(-(V.n-5),Math.min(Math.round(V.off),N-10));V.vz=Math.max(0.15,Math.min(12,V.vz));
 const end=N-V.off,startRaw=end-V.n,start=Math.max(0,startRaw),endV=Math.min(end,N),bw=pw/(V.n+(V.off===0?2:0));
 const stepMs=TFMS[(C.tf)||(S.D.cfg&&S.D.cfg.tf)||'1h']||3600000,tAt=i=>i<N?C.t[Math.max(0,i)]:C.t[N-1]+(i-N+1)*stepMs;
 Gc.start=start;Gc.end=end;Gc.bw=bw;Gc.L=L;Gc.raw=startRaw;Gc.total=N;Gc.pw=pw;Gc.H=H;Gc.B=B;
 const X=i=>L+(i-startRaw+0.5)*bw;
 const ix=t=>{let b=-1;for(let i=0;i<N;i++){if(C.t[i]<=t)b=i}return b};
 const TR=S.D.trades.map(x=>Object.assign({},x,{a:ix(x.t_in),b:ix(x.t_out)}));
 let hi=-1e99,lo=1e99;for(let i=start;i<endV;i++){hi=Math.max(hi,C.h[i]);lo=Math.min(lo,C.l[i])}
 if(hi<lo){hi=C.c[N-1]*1.01;lo=C.c[N-1]*0.99}
 const rg=hi-lo;TR.forEach(x=>{if(x.a>=start&&x.a<end&&x.stop0>lo-rg*0.15&&x.stop0<hi+rg*0.15){hi=Math.max(hi,x.stop0);lo=Math.min(lo,x.stop0)}});
 const rng0=(hi-lo)||hi*0.01,cen=(hi+lo)/2+V.vo*rng0,half=rng0*0.525/V.vz;hi=cen+half;lo=cen-half;Gc.pxVo=1.05/V.vz/(H-B-12);const Y=p=>6+(hi-p)/(hi-lo)*(H-B-12);
 g.font='10px system-ui';g.textBaseline='middle';g.fillStyle='#6e7681';g.strokeStyle='#1b222c';g.textAlign='left';
 for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5;g.beginPath();g.moveTo(L,Y(p));g.lineTo(L+pw,Y(p));g.stroke();g.fillText(fmt(p),L+pw+4,Y(p))}
 const step=Math.max(1,Math.ceil(90/bw));g.textAlign='center';for(let i=start;i<end;i+=step){g.fillText(ft(tAt(i)),Math.min(X(i),W-R-30),H-7)}g.textAlign='left';
 for(let i=start;i<endV;i++){const up=C.c[i]>=C.o[i],col=up?'#26a69a':'#ef5350',x=X(i),w=Math.max(1,bw*0.7);g.strokeStyle=g.fillStyle=col;g.beginPath();g.moveTo(x,Y(C.h[i]));g.lineTo(x,Y(C.l[i]));g.stroke();if(bw>=1.6)g.fillRect(x-w/2,Y(Math.max(C.o[i],C.c[i])),w,Math.max(1,Y(Math.min(C.o[i],C.c[i]))-Y(Math.max(C.o[i],C.c[i]))))}
 if(V.ema)[['ema20','#e3b341'],['ema200','#bc8cff']].forEach(([k,c])=>{g.strokeStyle=c;g.lineWidth=1.4;g.beginPath();let on=false;for(let i=start;i<endV;i++){const v=C[k][i];if(v==null){on=false;continue}if(!on){g.moveTo(X(i),Y(v));on=true}else g.lineTo(X(i),Y(v))}g.stroke();g.lineWidth=1});
 if(end>N){const xn=X(N-0.5);g.strokeStyle='#30363d';g.setLineDash([4,4]);g.beginPath();g.moveTo(xn,0);g.lineTo(xn,H-B);g.stroke();g.setLineDash([]);g.fillStyle='#6e7681';g.textAlign='left';g.fillText('будущее →',xn+4,H-B-8)}
 if(V.ch)TR.forEach(x=>{if(!x.chl||x.a<0)return;const a=x.a,b=Math.max(x.b,x.a),pre=3,post=1,i0=Math.max(a-pre,start),i1=Math.min(b+post,end-1);if(i1<i0||b<start||a-pre>=end)return;
   const f=(k,i)=>{const v0=x.chl[k],v1=x.chl[k+2];return b===a?v0:v0+(v1-v0)*(i-a)/(b-a)};
   [1,0].forEach(k=>{g.strokeStyle='#79c0ff';g.lineWidth=1.8;g.beginPath();g.moveTo(X(i0),Y(f(k,i0)));g.lineTo(X(i1),Y(f(k,i1)));g.stroke();g.lineWidth=1});
   g.strokeStyle='rgba(121,192,255,.35)';g.setLineDash([2,3]);[a,b].forEach(i=>{if(i<start||i>=end)return;g.beginPath();g.moveTo(X(i),Y(f(1,i)));g.lineTo(X(i),Y(f(0,i)));g.stroke()});g.setLineDash([])});
 const sz=Math.max(3,Math.min(6,bw*1.2));
 TR.forEach(x=>{if(x.a<0&&x.b<0)return;const col=x.net>0?'#3fb950':'#f85149',a=Math.max(x.a,0),b=Math.max(x.b,0);
  if(Math.max(a,b)<start||Math.min(a,b)>=end)return;const xa=X(a),xb=X(b);
  if(x.a>=0){g.strokeStyle='rgba(248,81,73,.7)';g.setLineDash([2,3]);g.beginPath();g.moveTo(xa,Y(x.stop0));g.lineTo(xb,Y(x.stop0));g.stroke();g.setLineDash([]);
   g.strokeStyle=col;g.setLineDash([5,3]);g.beginPath();g.moveTo(xa,Y(x.p_in));g.lineTo(xb,Y(x.p_out));g.stroke();g.setLineDash([]);
   if(x.a>=start&&x.a<end){g.fillStyle=x.side==='L'?'#3fb950':'#f85149';g.beginPath();const y=Y(x.p_in);if(x.side==='L'){g.moveTo(xa-sz,y+sz*1.8);g.lineTo(xa+sz,y+sz*1.8);g.lineTo(xa,y+2)}else{g.moveTo(xa-sz,y-sz*1.8);g.lineTo(xa+sz,y-sz*1.8);g.lineTo(xa,y-2)}g.fill()}}
  if(x.b>=start&&x.b<end&&!x.open){g.fillStyle=col;g.fillRect(xb-sz/2,Y(x.p_out)-sz/2,sz,sz)}});
 const lp=C.c[N-1];if(lp>lo&&lp<hi&&V.off===0){g.strokeStyle='#8b949e';g.setLineDash([2,3]);g.beginPath();g.moveTo(L,Y(lp));g.lineTo(L+pw,Y(lp));g.stroke();g.setLineDash([]);g.fillStyle='#30363d';g.fillRect(L+pw+1,Y(lp)-7,R-2,14);g.fillStyle='#fff';g.fillText(fmt(lp),L+pw+4,Y(lp))}
 let hv=Gc.hover;if(hv>=start&&hv<end){const x=X(hv);g.strokeStyle='rgba(201,209,217,.4)';g.setLineDash([3,3]);g.beginPath();g.moveTo(x,0);g.lineTo(x,H-B);g.stroke();g.setLineDash([])}else hv=-1;
 const i=hv>=0?hv:N-1;let s=ft(C.t[i])+'  O '+fmt(C.o[i])+' H '+fmt(C.h[i])+' L '+fmt(C.l[i])+' C '+fmt(C.c[i])+(V.ema?'  EMA20 '+fmt(C.ema20[i])+' EMA200 '+fmt(C.ema200[i]):'');
 TR.forEach(x=>{if(x.a===i)s+='\n▸ вход '+(x.side==='L'?'ЛОНГ':'ШОРТ')+' '+fmt(x.p_in)+', стоп '+fmt(x.stop0)+' (риск '+x.risk.toFixed(2)+'%)'+(x.chl?', канал '+fmt(x.chl[0])+' … '+fmt(x.chl[1]):'');if(x.b===i&&!x.open)s+='\n■ выход '+fmt(x.p_out)+' · '+x.reason+' · Net '+sg(x.net)+'%'});
 $('chinfo').textContent=s;
}
const cvv=document.getElementById('c'),ptrs=new Map();let g0=null;
const pxy=e=>{const r=cvv.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}};
const zoneAt=(x,y)=>x>Gc.L+Gc.pw?'price':(y>Gc.H-Gc.B-2&&y<=Gc.H)?'time':'plot';
const idxAt=x=>Math.max(0,Math.min(Gc.total-1,Math.floor(Gc.raw+(x-Gc.L)/Gc.bw)));
cvv.addEventListener('pointerdown',e=>{cvv.setPointerCapture(e.pointerId);const q=pxy(e);ptrs.set(e.pointerId,q);
 if(ptrs.size===1){g0={x:q.x,y:q.y,off:V.off,vo:V.vo,vz:V.vz,n:V.n,zone:zoneAt(q.x,q.y),moved:false}}
 else if(ptrs.size===2&&g0){const a=[...ptrs.values()];g0.pinch={dx:Math.abs(a[0].x-a[1].x),dy:Math.abs(a[0].y-a[1].y),n:V.n,vz:V.vz};g0.moved=true}});
cvv.addEventListener('pointermove',e=>{const q=pxy(e);
 if(!ptrs.has(e.pointerId)){if(e.pointerType==='mouse'&&S.D&&S.D.chart){Gc.hover=idxAt(q.x);chart()}return}
 ptrs.set(e.pointerId,q);if(!g0||!S.D||!S.D.chart)return;
 if(ptrs.size===2&&g0.pinch){const a=[...ptrs.values()],dx=Math.abs(a[0].x-a[1].x),dy=Math.abs(a[0].y-a[1].y);
  if(g0.pinch.dy>g0.pinch.dx*1.2){V.vz=g0.pinch.vz*Math.max(dy,10)/Math.max(g0.pinch.dy,10)}else{V.n=Math.round(g0.pinch.n*Math.max(g0.pinch.dx,10)/Math.max(dx,10))}chart();return}
 const dx=q.x-g0.x,dy=q.y-g0.y;if(Math.abs(dx)>5||Math.abs(dy)>5)g0.moved=true;if(!g0.moved)return;
 if(g0.zone==='price')V.vz=g0.vz*Math.exp(-dy/120);
 else if(g0.zone==='time')V.n=Math.round(g0.n*Math.exp(-dx/120));
 else{V.off=Math.round(g0.off+dx/Gc.bw);V.vo=g0.vo+dy*Gc.pxVo}
 chart()});
cvv.addEventListener('pointerup',e=>{const q=ptrs.get(e.pointerId)||pxy(e);if(ptrs.size===1&&g0&&!g0.moved&&S.D&&S.D.chart){Gc.hover=idxAt(q.x);chart()}ptrs.delete(e.pointerId);if(!ptrs.size)g0=null});
cvv.addEventListener('pointercancel',e=>{ptrs.delete(e.pointerId);if(!ptrs.size)g0=null});
cvv.addEventListener('wheel',e=>{e.preventDefault();const f=e.deltaY>0?1.15:0.87;if(e.shiftKey)V.vz=V.vz/f;else if(e.altKey)V.off+=(e.deltaY>0?1:-1)*Math.max(1,Math.round(V.n*0.1));else V.n=Math.round(V.n*f);chart()},{passive:false});
function mkView2(){const b=$('vbar2');b.innerHTML='';
 [['↔+',()=>{V.n=Math.max(10,Math.round(V.n*0.8))}],['↔−',()=>{V.n=Math.min(1000,Math.round(V.n*1.25))}],['↕+',()=>{V.vz=Math.min(12,V.vz*1.25)}],['↕−',()=>{V.vz=Math.max(0.15,V.vz/1.25)}],
  ['◀',()=>{V.off+=Math.max(1,Math.round(V.n*0.25))}],['▶',()=>{V.off-=Math.max(1,Math.round(V.n*0.25))}],['⟲',()=>{V.n=480;V.off=0;V.vz=1;V.vo=0}]].forEach(([l,f])=>{const x=document.createElement('button');x.textContent=l;x.onclick=()=>{f();chart()};b.appendChild(x)});
 const h=document.createElement('span');h.style.cssText='font-size:11px;color:#8b949e';h.textContent='тяни график — сдвиг (вправо за последнюю свечу — будущее); щипок по горизонтали/вертикали — масштаб; ось цены справа / ось времени снизу — тяни для масштаба; ⟲ — сброс';b.appendChild(h)}
mkView2();
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
