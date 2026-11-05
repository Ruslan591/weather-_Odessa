# -*- coding: utf-8 -*-
"""Патч 9 (2026-11-05): панель 18091/8091, вкладка Claude: блок «Пропущенные входы (виртуальные)» (сводка, признаки победителей/проигравших, таблица с графиком). Идемпотентный. Данные: chan_orders.miss_summary / miss_view. Запуск: patch_missed_ui.py <classic dir> <positions dir>."""
import sys, os
D = sys.argv[1]; P = sys.argv[2]; fh = os.path.join(D, "classic_pos_html.py"); fp = os.path.join(P, "pos.py")
h = open(fh, encoding="utf-8").read(); q = open(fp, encoding="utf-8").read()
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:70]); return s.replace(old, new)
JS = r'''async function clMiss(id){try{const j=await api(`/api/claude`,{action:`miss_chart`,id:id});S.clcl=j}catch(e){alert(e.message);return}renderRuns();setTimeout(()=>{const e=document.getElementById(`clclosed`);if(e)e.scrollIntoView({block:`start`})},60)}
function clMissBlock(C){const M=C.miss;if(!M||!M.all)return ``;const pc=String.fromCharCode(37),A=M.all;
const FN={atr_pct:`ATR 5m, `+pc+` цены`,tick_atr:`шаг цены в ATR`,brk_close_atr:`закрытие пробоя за уровнем, ATR`,brk_range_atr:`размах свечи пробоя, ATR`,vol_ratio:`объём свечи пробоя к среднему`,width_atr:`ширина канала, ATR`,dep_atr:`отход от уровня к решению, ATR`,struct:`доля с горизонтальным уровнем`};
const RN={stop:`стоп`,tp:`цель 2R`,time:`по окну`,run:`идёт`};
let h=`<details data-k=acl_miss style=margin-top:8px><summary class=sm>Пропущенные входы (виртуально): что было бы, если бы входили по рынку (завершено: `+(A.n||0)+`, считается: `+M.pending+`)</summary>`;
h+=`<div class=sm>Это не сделки, а учёт пропусков. События: цена ушла после подтверждения, возврата к уровню не было, возврат был без свечи подтверждения. Виртуальный вход по рынку в момент решения, стоп за уровнем плюс 0.5 ATR (не меньше 0.5`+pc+`), цель 2R, окно 6 часов, стоп раньше цели при одной свече. Нужен, чтобы понять цену ретест-входа и научиться отделять пробои, которые уходят, от тех, что разворачиваются. Выводы можно делать от 30 событий в группе.</div>`;
if(!A.n)return h+`<div class=sm style=margin-top:6px>Завершённых пока нет.</div></details>`;
h+=`<div class=sm style=margin-top:6px><b>Всего `+A.n+`</b> · прибыльных `+A.win+pc+` · сумма `+A.sumR+`R · средняя `+A.avgR+`R · цена доходила до +2R в `+A.ran+` из `+A.n+`</div>`;
h+=`<div class=sc><table><tr><th>Тип</th><th>событий</th><th>прибыльных</th><th>средняя R</th><th>сумма R</th><th>до +2R</th></tr>`+M.kinds.map(k=>`<tr><td>`+k.label+`</td><td>`+(k.n||0)+`</td><td>`+(k.n?k.win+pc:`—`)+`</td><td>`+(k.n?k.avgR:`—`)+`</td><td>`+(k.n?k.sumR:`—`)+`</td><td>`+(k.n?k.ran:`—`)+`</td></tr>`).join(``)+`</table></div>`;
h+=`<div class=sm style=margin-top:8px><b>Чем отличаются прибыльные от убыточных</b> (среднее значение признака на момент пробоя)</div><div class=sc><table><tr><th>Признак</th><th>прибыльные</th><th>убыточные</th></tr>`+Object.keys(FN).map(k=>{const f=M.feats[k]||{};return `<tr><td>`+FN[k]+`</td><td>`+(f.win==null?`—`:f.win)+`</td><td>`+(f.lose==null?`—`:f.lose)+`</td></tr>`}).join(``)+`</table></div>`;
h+=`<div class=sm style=margin-top:8px><b>Последние события</b></div><div class=sc><table><tr><th>Пара</th><th></th><th>Тип</th><th>Пробой</th><th>Итог</th><th>R</th><th>в плюс до</th><th></th></tr>`+M.rows.map(r=>`<tr><td>`+r.sym+`</td><td>`+(r.dir===`up`?`лонг`:`шорт`)+`</td><td>`+r.label+`</td><td>`+clHm(r.t_break)+`</td><td>`+(RN[r.res]||r.res)+`</td><td>`+r.r+`</td><td>`+r.mfe+`R</td><td><button onclick=clMiss(`+r.id+`)>график</button></td></tr>`).join(``)+`</table></div></details>`;return h}
'''
if "clMissBlock" not in h:
    h = rep(h, "h+=clShadowBlock(C)+clClosedBlock();return h+'</div>'}", "h+=clShadowBlock(C)+clMissBlock(C)+clClosedBlock();return h+'</div>'}")
    h = rep(h, "function clClosedBlock(){", JS + "function clClosedBlock(){")
    h = rep(h, "style=margin-top:8px><div class=sm>`+head+`</div>", "style=margin-top:8px><div class=sm>`+(p.vhead||head)+`</div>")
if '"miss_chart"' not in q:
    q = rep(q, '    if o.get("action") == "closed_chart":   # патч 8', '    if o.get("action") == "miss_chart":   # патч 9\n        try:\n            import chan_orders\n            return chan_orders.miss_view(int(o.get("id", 0)))\n        except Exception as e:\n            return {"error": str(e)}\n    if o.get("action") == "closed_chart":   # патч 8')
    q = rep(q, '"shadow": _shadow(), "ts"', '"shadow": _shadow(), "miss": _miss(), "ts"')
    q = rep(q, "def _shadow():   # патч 8", "def _miss():   # патч 9\n    try:\n        import chan_orders\n        return chan_orders.miss_summary()\n    except Exception as e:\n        return None\n\ndef _shadow():   # патч 8")
open(fh, "w", encoding="utf-8").write(h); open(fp, "w", encoding="utf-8").write(q); print("patch 9 applied")
