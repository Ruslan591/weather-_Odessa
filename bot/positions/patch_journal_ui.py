# -*- coding: utf-8 -*-
"""Патч 11б (2026-11-06): панель 18091, вкладка Claude: у позиции поля «Причина стопа» и «заметка», блок «Цель, цена» с причиной, кнопки «Поставить цель» и «Вернуть авто-цель»,
блок «Журнал решений» (последние 30 записей, кнопка выгрузки всего журнала в JSON). Идемпотентный. Запуск: patch_journal_ui.py <каталог classic>"""
import sys, os
f = os.path.join(sys.argv[1], "classic_pos_html.py"); h = open(f, encoding="utf-8").read()
if "clJournalBox" in h: print("already patched"); sys.exit(0)
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:90]); return s.replace(old, new)
JS = r"""
function clv(id){const e=document.getElementById(id);return e?e.value:''}
var CL_TAGS_STOP=['—','под минимум свечи','под уровень','за ценой (подтянул)','в безубыток','защита прибыли','расширил стоп','другое (см. заметку)'];
var CL_TAGS_TP=['—','ближе (фиксирую)','дальше (держу)','к уровню','по ATR','другое (см. заметку)'];
function clTpBox(p){const id=p.id;S.clin=S.clin||{};const I=S.clin[id]=S.clin[id]||{};const st='background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:5px;';
const tv=I.tg!==undefined?I.tg:(p.tp_manual?String(+(+p.tp_manual).toPrecision(7)):String(+(+p.tp).toPrecision(7)));
const opt=(L,v)=>L.map(x=>`<option${x===v?' selected':''}>${x}</option>`).join('');
return `<div class=sm style="margin-top:6px">Причина стопа (в журнал): <select id=clst_${id} onchange="S.clin[${id}].tst=this.value" style="${st}">${opt(CL_TAGS_STOP,I.tst||'—')}</select> <input id=clsn_${id} type=text placeholder="заметка" value="${(I.stn||'').replace(/"/g,'')}" oninput="S.clin[${id}].stn=this.value" style="width:130px;${st}"></div>`
+`<div class=sm style="margin-top:8px">Цель, цена: <input id=cltg_${id} type=text inputmode=decimal value="${tv}" oninput="S.clin[${id}].tg=this.value" style="width:100px;${st}"> <button data-cm=tp data-k="${id}">Поставить цель</button>${p.tp_manual?` <button data-cm=tpauto data-k="${id}">Вернуть авто-цель</button>`:''}</div>`
+`<div class=sm style="margin-top:4px">Причина цели: <select id=cltt_${id} onchange="S.clin[${id}].ttg=this.value" style="${st}">${opt(CL_TAGS_TP,I.ttg||'—')}</select></div>`
+`<div class=sm style="margin-top:2px;color:#8b949e">Цель - цена: лонг выше текущей цены, шорт ниже. Каждый ваш перенос стопа и цели пишется в журнал решений вместе с контекстом (свечи, уровни, расстояния).</div>`}
function clJournalBox(C){const J=C.journal;if(!J)return '';const K={stop:'стоп',tp:'цель',trail:'трейлинг',release:'вернул авто-стоп',tp_release:'вернул авто-цель',close:'закрыл',be:'БУ (авто)',trail_start:'старт трейлинга (авто)',tp1:'частичная цель (авто)',sr:'на уровень S/R (авто)'};
const esc=x=>String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const rows=(J.tail||[]).slice().reverse().map(r=>{const mv=(r.from!=null&&r.to!=null&&r.from!==r.to)?' '+fmt(r.from)+' → '+fmt(r.to):(r.to!=null&&r.kind==='tp1'?' '+fmt(r.to):'');
return `<div class=sm style="margin-top:5px;${r.by==='manual'?'':'color:#8b949e'}">${clHm(r.t)} #${r.id} ${esc(r.sym)} <b>${K[r.kind]||esc(r.kind)}</b>${mv} · цена ${fmt(r.px)} · ${r.r_now}R${r.to_atr5!=null?' · от цены '+r.to_atr5+' ATR5':''}${r.tag&&r.tag!=='—'?' · '+esc(r.tag):''}${r.note?' · «'+esc(r.note)+'»':''}</div>`}).join('');
return `<details data-k=acl_jr style="margin-top:8px"><summary class=sm><b>Журнал решений</b> (записей ${J.n}): переносы стопа и цели с контекстом</summary><div class=sm style="margin-top:6px;color:#8b949e">Ваши действия (светлым) и автособытия бота (серым). Полный журнал со свечами и уровнями выгружается кнопкой ниже.</div><div class=sm style="margin-top:6px"><button onclick="clJDl()">Скачать весь журнал (JSON)</button></div>${rows||'<div class=sm style="margin-top:6px">Пока пусто</div>'}</details>`}
async function clJDl(){try{const j=await api('/api/claude',{action:'journal_get',full:1});const b=new Blob([JSON.stringify(j.rows||[],null,1)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='decisions_'+(S.cla||'classic')+'.json';document.body.appendChild(a);a.click();a.remove()}catch(e){alert(e.message)}}
"""
h = rep(h, "function clCard(){return clAcctBar()+clCard0()}", JS.strip("\n") + "\nfunction clCard(){return clAcctBar()+clCard0()}")
h = rep(h, "h+=clExitBox(C)+clOrders(C);if(C.open.length)", "h+=clExitBox(C)+clJournalBox(C)+clOrders(C);if(C.open.length)")
h = rep(h, "+clStopBox(p)+'", "+clStopBox(p)+clTpBox(p)+'")
h = rep(h, "clAct('stop',k,{price:v})", "clAct('stop',k,{price:v,tag:clv('clst_'+k),note:clv('clsn_'+k)})")
h = rep(h, "else clAct('auto',k,{})}})}", "else if(a==='tp'){const v=num('cltg_'+k);if(!(v>0)){alert('Укажите ЦЕНУ цели числом');return}clAct('tp',k,{price:v,tag:clv('cltt_'+k)})}else if(a==='tpauto'){clAct('tp_auto',k,{})}else clAct('auto',k,{})}})}")
h = rep(h, ";return h}\nfunction clStopBox", ";if(p.tp_manual)h+=c+'ручная цель '+fmt(p.tp_manual)+' (установлена '+clHm(p.tp_manual_t)+'), настройки цели для этой позиции не действуют, пока не нажато «Вернуть авто-цель»</div>';return h}\nfunction clStopBox")
open(f, "w", encoding="utf-8").write(h); print("patched panel")
