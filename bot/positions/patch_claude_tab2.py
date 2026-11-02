# -*- coding: utf-8 -*-
"""Патч 2 вкладки «Claude» на 18091: вид как у счёта «Профиль» (acctCard): крупный equity, плитки баланса, блок открытой позиции, строка статистики,
журнал «Сделки счёта» с кнопками в строке (Закрыть, Стоп / трейлинг); график 15m и тезис оставлены под позицией.
Требует патч 1 (patch_claude_tab.py). Идемпотентен, бэкап *.bak_claude_tab2. Запуск: python patch_claude_tab2.py [каталог_панели]"""
import os, shutil, sys
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
HTML = os.path.join(D, "classic_pos_html.py")

JS = r"""function clTs(ms){return new Date(ms).toISOString().slice(5,16).replace('T',' ')}
function clChart(p){const C=p.cand.slice(-96),W=360,H=210,L=4,Rr=58;let lo=Math.min(...C.map(c=>c[3]),p.entry,p.stop,p.px),hi=Math.max(...C.map(c=>c[2]),p.entry,p.stop,p.px);const pad=(hi-lo)*.06||hi*.001;lo-=pad;hi+=pad;const X=i=>L+(i+.5)*(W-L-Rr)/C.length,Y=v=>H-8-(v-lo)/(hi-lo)*(H-16);let s="<svg viewBox='0 0 "+W+" "+H+"' style='width:100%;height:auto;background:#11151c;border-radius:8px'>";
C.forEach((c,i)=>{const col=c[4]>=c[1]?'#2ea043':'#da3633',x=X(i);s+="<line x1='"+x+"' x2='"+x+"' y1='"+Y(c[2])+"' y2='"+Y(c[3])+"' stroke='"+col+"'/><rect x='"+(x-1.4)+"' y='"+Y(Math.max(c[1],c[4]))+"' width='2.8' height='"+Math.max(1,Math.abs(Y(c[1])-Y(c[4])))+"' fill='"+col+"'/>"});
const ln=(v,col,t)=>{if(!(v>=lo&&v<=hi))return "";return "<line x1='"+L+"' x2='"+(W-Rr)+"' y1='"+Y(v)+"' y2='"+Y(v)+"' stroke='"+col+"' stroke-dasharray='4 3'/><text x='"+(W-Rr+3)+"' y='"+(Y(v)+3)+"' fill='"+col+"' font-size='9'>"+t+" "+v.toPrecision(5)+"</text>"};
return s+ln(p.entry,'#cfd6e0','вход')+ln(p.stop,'#f85149','стоп')+ln(p.be_px,'#d29922','БУ')+ln(p.tp,'#3fb950','цель')+ln(p.px,'#58a6ff','цена')+"</svg>"}
function clCtl(id){let h='<button data-cc="'+id+'">Закрыть</button> <button data-cs="'+id+'">Стоп / трейлинг</button>';if(S.clmp===id)h+=' <input id=clv type=number step=0.1 min=0.05 max=20 value="'+(S.clmv||0.6)+'" oninput="S.clmv=this.value" style="width:64px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:5px"> % <button data-cm=stop data-k="'+id+'">Стоп</button><button data-cm=trail data-k="'+id+'">Трейлинг</button>';return h}
function clBind(){document.querySelectorAll('#runs [data-cc]').forEach(b=>{b.onclick=()=>clAct('close',+b.dataset.cc,0)});document.querySelectorAll('#runs [data-cs]').forEach(b=>{b.onclick=()=>{const k=+b.dataset.cs;S.clmp=S.clmp===k?null:k;renderRuns()}});document.querySelectorAll('#runs [data-cm]').forEach(b=>{b.onclick=()=>{const v=parseFloat(($('clv')||{}).value);if(!(v>0)){alert('Укажите расстояние в %, например 0.6');return}clAct(b.dataset.cm,+b.dataset.k,v)}})}
async function clAct(a,id,pct){if(S.clbusy)return;if(a==='close'&&!confirm('Закрыть позицию #'+id+' по текущей цене?'))return;S.clbusy=1;try{const j=await api('/api/claude',{action:a,id:id,pct:pct});if(j.error)alert(j.error);else{S.cl=j;S.clmp=null}}catch(e){alert(e.message)}S.clbusy=0;renderRuns()}
function clMan(p){if(p.manual_trail)return '<div class=sm style="margin-top:4px;color:#d29922">ручной трейлинг '+p.manual_trail+'% · стоп сейчас '+fmt(p.stop)+'</div>';if(p.manual_stop)return '<div class=sm style="margin-top:4px;color:#d29922">ручной стоп '+fmt(p.stop)+' ('+p.manual_stop+'% от цены при установке)</div>';return ''}
function clCard(){const C=S.cl;if(!C||C.error)return '<div class=card>Claude: '+((C&&C.error)||'нет данных')+'</div>';
const a=C.account,now=Date.now(),pn=a.equity-a.start,c=pn>=0?'up':'dn';
const Z=C.closed.slice().sort((x,y)=>x.t_out-y.t_out);let bal=a.start;
const done=Z.map(p=>{bal+=p.pnl_usd;return {id:p.id,sym:p.sym,tf:'',side:p.side==='long'?'L':'S',t_in:p.t_in,t_out:p.t_out,open:false,net:p.net_pct,pnl:p.pnl_usd,be:!!p.armed,bal_after:bal,liq:p.reason==='liquidation'}});
const opn=C.open.map(p=>({id:p.id,sym:p.sym,tf:'',side:p.side==='long'?'L':'S',t_in:p.t_in,t_out:null,open:true,net:p.unreal_pct,pnl:p.unreal_usd,be:!!p.armed,bal_after:null,liq:false}));
const log=opn.concat(done),ev=[];log.forEach(t=>{ev.push([t.t_in,1]);ev.push([t.open?now:t.t_out,-1])});ev.sort((x,y)=>x[0]-y[0]||x[1]-y[1]);let cur=0,maxc=0;ev.forEach(e=>{cur+=e[1];if(cur>maxc)maxc=cur});
const wins=done.filter(t=>t.pnl>0).length,wp=done.length?Math.round(wins/done.length*100):null;
let h='<div class=card><h4>Счёт «Claude»</h4><div class=sm>Старт '+money(a.start)+' · плечо '+a.lev+'x, изолированная маржа · каждая позиция по минимальной ставке '+money(a.stake)+' (маржа '+money(a.margin)+') · позиции открывает и ведёт Claude вручную по своему разбору (docs/topics/bot_positions.md), бумага, цены Binance spot</div>';
h+='<div class=eq>'+money(a.equity)+' <span class='+c+'>'+smoney(pn)+' ('+sg(pn/a.start*100)+'%)</span></div>';
h+='<div class=grid><div><span>Баланс кошелька</span><b>'+money(a.start+a.realized)+'</b></div><div><span>Нереализованный PnL</span><b class='+(a.unreal>=0?'up':'dn')+'>'+smoney(a.unreal)+'</b></div><div><span>В марже</span><b>'+money(a.open_margin)+'</b></div><div><span>Доступно</span><b>'+money(a.free)+'</b></div></div>';
if(C.open.length)h+='<div class=sm style="margin-top:8px">Открытые позиции ('+C.open.length+'):</div>'+C.open.map(p=>'<div class="sm posb"><b>'+p.sym+' '+(p.side==='long'?'LONG':'SHORT')+'</b> · вручную · вход '+fmt(p.entry)+' · сейчас '+fmt(p.px)+' · стоп '+fmt(p.stop)+' · цель '+fmt(p.tp)+' · ликвидация '+fmt(p.liq_px)+(p.armed?' · ✓ безубыток':'')+'<br>размер '+money(p.stake)+' · маржа '+money(p.margin)+' · результат '+smoney(p.unreal_usd)+' (ROE '+sg(p.unreal_pct*a.lev)+'%) · '+p.r_now+'R'+clMan(p)+'<div style="margin-top:8px">'+clChart(p)+'</div><details style="margin-top:6px"><summary class=sm>Тезис</summary><div class=sm>'+(p.thesis||'')+'</div></details></div>').join('');
else h+='<div class=sm style="margin-top:8px">Позиций нет — ждёт разбора</div>';
h+='<div class=sm style="margin-top:6px">Взято '+log.length+' · закрыто '+done.length+' · прибыльных '+(wp==null?'—':wp+'%')+' · пропущено (не хватило свободной маржи) 0 · макс. одновременно '+maxc+' · активен</div>';
if(log.length){const lc=[{l:'Пара',t:1,v:t=>t.sym,h:t=>'<td>'+t.sym+'</td>'},{l:'Сторона',t:1,v:t=>t.side,h:t=>'<td>'+(t.side==='L'?'лонг':'шорт')+(t.liq?' · ЛИКВИДАЦИЯ':'')+'</td>'},{l:'Вход',v:t=>t.t_in,h:t=>'<td>'+ft(t.t_in)+'</td>'},{l:'Выход',v:t=>t.open?9e15:t.t_out,h:t=>'<td>'+(t.open?'—':ft(t.t_out))+'</td>'},{l:'Net%',v:t=>t.net,h:t=>'<td class='+cls(t.net)+'>'+sg(t.net)+'</td>'},{l:'PnL',v:t=>t.pnl,h:t=>'<td class='+cls(t.pnl)+'>'+smoney(t.pnl)+'</td>'},{l:'БУ',v:t=>t.be?1:0,h:t=>'<td>'+(t.be?'<span class=up>✓</span>':'—')+'</td>'},{l:'Баланс',v:t=>t.open?null:t.bal_after,h:t=>'<td>'+(t.open?'открыта':money(t.bal_after))+'</td>'},{l:'Действия',v:t=>t.open?1:0,h:t=>'<td style="white-space:nowrap">'+(t.open?clCtl(t.id):'')+'</td>'}];
h+='<details data-k=acl_cl><summary class=sm>Сделки счёта · взято '+log.length+' · закрыто '+done.length+' · прибыльных '+wins+' из '+done.length+(wp==null?'':' ('+wp+'%)')+'</summary><div class=sm>Порядок по умолчанию — по времени выхода; нажмите на заголовок столбца, чтобы отсортировать. Стоп — фиксированный уровень на этом расстоянии от цены сейчас; трейлинг — уровень идёт за лучшей ценой на этом расстоянии, только в сторону прибыли.</div><div class="sc stk" style="max-height:340px;overflow-y:auto">'+stbl('acl_cl',lc,log,{c:3,d:-1})+'</div></details>'}
return h+'</div>'}
"""

def main():
    s = open(HTML, encoding="utf-8").read()
    if "function clBind(" in s:
        print("already patched"); return
    assert "function clAct(" in s and "function expCard(){" in s, "патч 1 не применён"
    i = s.index("function clAct("); j = s.index("function expCard(){")
    s = s[:i] + JS + s[j:]
    a = "if(S.track==='cl'){FIN(loadLine()+trackBar()+clCard());return}"
    assert s.count(a) == 1
    s = s.replace(a, "if(S.track==='cl'){FIN(loadLine()+trackBar()+clCard());clBind();return}")
    shutil.copy(HTML, HTML + ".bak_claude_tab2")
    open(HTML, "w", encoding="utf-8").write(s)
    print("patched")

if __name__ == "__main__":
    main()
