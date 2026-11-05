# -*- coding: utf-8 -*-
"""Патч 8 (2026-11-05): панель 18091, вкладка Claude: (1) сводка тени тренда, (2) график закрытых сделок (кнопка «график» в журнале). Идемпотентный.
Запуск: patch_closed_ui.py <classic dir> <positions dir>. Правит classic_pos_html.py и pos.py на VPS; логика данных в chan_orders.py (shadow_summary, closed_view)."""
import sys, os
D = sys.argv[1]; P = sys.argv[2]; fh = os.path.join(D, "classic_pos_html.py"); fp = os.path.join(P, "pos.py")
h = open(fh, encoding="utf-8").read(); q = open(fp, encoding="utf-8").read()
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:70]); return s.replace(old, new)
JS = r'''function clShadowLine(sh){if(!sh||!sh.agree)return ``;const ru={yes:`по направлению`,no:`против`,neutral:`нейтрально`};const L={btc_5m:`BTC 5m`,btc_15m:`BTC 15m`,eth_5m:`ETH 5m`,eth_15m:`ETH 15m`,own_15m:`пара 15m`,own_1h:`пара 1h`};return Object.keys(L).map(k=>L[k]+`: `+(ru[sh.agree[k]]||`нет данных`)).join(` · `)}
function clShadowCell(x){if(!x||!x.n)return `—`;return x.n+` · `+x.win+String.fromCharCode(37)+` · `+(x.avg>=0?`+`:``)+x.avg+`R`}
function clShadowTab(G,ttl){if(!G||!G.n)return `<div class=sm style=margin-top:6px>`+ttl+`: закрытых сделок пока нет</div>`;return `<div class=sm style=margin-top:6px><b>`+ttl+`</b> · сделок `+G.n+` · сумма `+G.sumR+`R</div><div class=sc><table><tr><th>Сигнал</th><th>по направлению</th><th>нейтрально</th><th>против</th></tr>`+G.rows.map(r=>`<tr><td>`+r.label+`</td><td>`+clShadowCell(r.yes)+`</td><td>`+clShadowCell(r.neutral)+`</td><td>`+clShadowCell(r.no)+`</td></tr>`).join(``)+`</table></div>`}
function clShadowBlock(C){const H=C.shadow;if(!H||!H.all)return ``;return `<details data-k=acl_shadow style=margin-top:8px><summary class=sm>Тень тренда: согласие сигнала с заявкой и результат (закрытых с тенью: `+H.all.n+`)</summary><div class=sm>Тень не влияет на вход, это только запись. В ячейке: сделок · доля прибыльных · средний результат в R. «По направлению» значит, что тренд (счёт по EMA от -4 до +4, порог 2) совпал с направлением заявки, «против» - нет. Варианты: BTC и ETH (5m, 15m) и сама пара (15m, 1h). Для решения о фильтре нужно не меньше 30 сделок в группе и разница от 0.3R; пока выборка мала, это только наблюдение.</div>`+clShadowTab(H.v3,`Серия v3 (после правок подтверждения)`)+clShadowTab(H.all,`Все закрытые заявки с тенью`)+`</details>`}
async function clClosed(id){try{const j=await api(`/api/claude`,{action:`closed_chart`,id:id});S.clcl=j}catch(e){alert(e.message);return}renderRuns();setTimeout(()=>{const e=document.getElementById(`clclosed`);if(e)e.scrollIntoView({block:`start`})},60)}
function clClosedOff(){S.clcl=null;renderRuns()}
function clZClosed(p,id){const C=p.cand||[];if(C.length<5)return ``;const dt=p.o_dt||900000,F=6,xo=p.exit,t2=p.t_out,x1=p.o_placed_t||p.t_in,sp={cand:C,dt:dt,F:F,n0:110,ext:[p.entry,p.stop0,p.tp,xo],zones:[],segs:[],pts:[],hl:[],vl:[]},tL=C[C.length-1][0];
sp.zones.push({t1:p.t_in,t2:t2,p1:p.entry,p2:p.stop0,col:`rgba(218,54,51,.16)`});if(p.tp>0)sp.zones.push({t1:p.t_in,t2:t2,p1:p.entry,p2:p.tp,col:`rgba(46,160,67,.16)`});
sp.hl.push({v:p.entry,col:`#cfd6e0`,txt:`вход`,w:1.6,t1:p.t_in,t2:t2},{v:p.stop0,col:`#f85149`,txt:`стоп`,w:1.2,dash:[4,3],t1:p.t_in,t2:t2},{v:p.tp,col:`#3fb950`,txt:`цель`,w:1.2,dash:[4,3],t1:p.t_in,t2:t2},{v:xo,col:`#58a6ff`,txt:`выход`,w:1.4,t1:t2,t2:t2+dt*F});
if(Math.abs(p.stop-p.stop0)>Math.abs(p.stop0)*1e-9){sp.hl.push({v:p.stop,col:`#ffa657`,txt:`стоп итог`,w:1,dash:[2,2],t1:p.t_in,t2:t2});sp.ext.push(p.stop)}
if(p.be_px>0){sp.hl.push({v:p.be_px,col:`#d29922`,txt:`БУ`,w:1,dash:[4,3],t1:p.t_in,t2:t2});sp.ext.push(p.be_px)}
if(x1!==p.t_in)sp.vl.push({t:x1,txt:`выставлен `+clHm(x1)});sp.vl.push({t:p.t_in,txt:`вход `+clHm(p.t_in)});sp.vl.push({t:t2,txt:`выход `+clHm(t2)});
if(p.o_chan)[p.o_chan.upper,p.o_chan.lower].forEach(ln=>{if(!ln)return;sp.segs.push({t1:ln.t1,p1:ln.p1,s:ln.s,col:`#3b82f6`});sp.ext.push(ln.p1+ln.s*(tL-ln.t1))});
const B=p.o_basis;if(B)(B.anchors||[]).concat(B.third?[B.third]:[]).forEach(z=>{sp.pts.push({t:z.t,p:z.p,n:z.n,third:z.n===`L3`||z.n===`H3`})});
if(p.o_level){sp.level=p.o_level;sp.ext.push(p.o_level.p)}if(p.o_breakout)sp.brk=p.o_breakout;
return clZBox(id,sp,330)+`<div class=sm style=margin-top:4px>Свечи `+(p.tf||``)+`. Красная зона - риск по начальному стопу, зелёная - до цели, синяя линия - цена выхода. Канал и точки (если сделка из заявки) - как были в момент выставления.</div>`}
function clClosedBlock(){const p=S.clcl;if(!p)return ``;if(p.error)return `<div class=sm style=margin-top:8px>`+p.error+`</div>`;
const RS={stop:`стоп`,target:`цель`,manual:`вручную`,time:`по времени`,liquidation:`ликвидация`};const rs=RS[p.reason]||(String(p.reason).indexOf(`trail`)===0?`БУ / трейлинг`:p.reason);const pc=String.fromCharCode(37);
const head=`<b>`+p.sym+` `+(p.side===`long`?`LONG`:`SHORT`)+` #`+p.id+`</b> · закрыта: `+rs+` · `+sg(p.net_pct)+pc+` (`+smoney(p.pnl_usd)+`) · `+(+p.r_mult).toFixed(2)+`R · вход `+fmt(p.entry)+` `+ft(p.t_in)+` · выход `+fmt(p.exit)+` `+ft(p.t_out)+` · ход в плюс до `+(+p.mfe_pct).toFixed(2)+pc+`, в минус до `+(+p.mae_pct).toFixed(2)+pc;
const why=p.o_why&&p.o_why.length?clWhy(p.o_why):`<div class=sm style=margin-top:6px>`+(p.thesis||``)+`</div>`;
const hasSh=(p.o_why||[]).some(w=>String(w).indexOf(`Тренд (тень`)===0);
return `<div class=posb id=clclosed style=margin-top:8px><div class=sm>`+head+`</div><div style=margin-top:8px>`+clZClosed(p,`c`+p.id)+`</div>`+why+(p.o_shadow&&!hasSh?`<div class=sm style=margin-top:6px><b>Тень тренда в момент заявки:</b> `+clShadowLine(p.o_shadow)+`</div>`:``)+`<div style=margin-top:8px><button onclick=clClosedOff()>Скрыть график</button></div></div>`}
'''
if "clClosedBlock" not in h:
    h = rep(h, "function clZBox(id,sp,H){S.clzs=S.clzs||{};S.clzs[id]=sp;", "function clZBox(id,sp,H){S.clzs=S.clzs||{};S.clzs[id]=sp;if(sp.level&&sp.level.p>0&&sp.hl&&!sp._lv){sp._lv=1;sp.hl.push({v:sp.level.p,col:'#f85149',txt:'ур.',w:1.2,dash:[6,3]});(sp.ext||[]).push(sp.level.p)}")
    h = rep(h, "(t.open?clCtl(t.id):'')+'</td>'", "(t.open?clCtl(t.id):'<button onclick=clClosed('+t.id+')>график</button>')+'</td>'")
    h = rep(h, "return h+'</div>'}\nfunction expCard(){", "h+=clShadowBlock(C)+clClosedBlock();return h+'</div>'}\n" + JS + "function expCard(){")
if '"closed_chart"' not in q:
    q = rep(q, '    act = o.get("action"); pid = int(o.get("id", 0)); pct', '    if o.get("action") == "closed_chart":   # патч 8\n        try:\n            import chan_orders\n            return chan_orders.closed_view(int(o.get("id", 0)))\n        except Exception as e:\n            return {"error": str(e)}\n    act = o.get("action"); pid = int(o.get("id", 0)); pct')
    q = rep(q, '"orders": _orders(), "ts": int(time.time() * 1000)}', '"orders": _orders(), "shadow": _shadow(), "ts": int(time.time() * 1000)}')
    q = rep(q, "def api_action(o):", "def _shadow():   # патч 8\n    try:\n        import chan_orders\n        return chan_orders.shadow_summary()\n    except Exception as e:\n        return None\n\ndef api_action(o):")
open(fh, "w", encoding="utf-8").write(h); open(fp, "w", encoding="utf-8").write(q); print("patch 8 applied")
