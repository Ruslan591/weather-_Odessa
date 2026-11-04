# -*- coding: utf-8 -*-
"""Патч 7 (2026-11-04): ручной стоп на панели 18091 «Claude». Идемпотентный. Запуск: patch_stop_ui.py <classic dir> <positions dir>
Что чинит (дефекты со слов пользователя): 1) вводится ЦЕНА стопа, а не проценты; 2) поле и состояние у КАЖДОЙ позиции своё (раньше одно общее значение S.clmv и одно поле на все);
3) после установки стоп сразу виден на графике и в тексте позиции; 4) автообновление (15 с) не перерисовывает блок, пока курсор в поле ввода, а ручной стоп не затирается
трейлингом/БУ/авто-переносом на S/R (флаг stop_manual, кнопка «Вернуть авто»). Сервер: pos.api_action(action=stop, price=...), action=auto, перед правкой позиция догоняется до «сейчас»."""
import sys, os
D = sys.argv[1]; P = sys.argv[2]; fh = os.path.join(D, "classic_pos_html.py"); fp = os.path.join(P, "pos.py")
h = open(fh, encoding="utf-8").read(); q = open(fp, encoding="utf-8").read()
def seg(s, a, b, new):
    i = s.index(a); j = s.index(b, i); return s[:i] + new + s[j:]
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:70]); return s.replace(old, new)

if "clStopBox" not in h:
    h = seg(h, "function clCtl(id){", "function clBind(){",
            "function clCtl(id){return '<button data-cc=\\\"'+id+'\\\">Закрыть</button>'}\n")
    h = seg(h, "function clBind(){", "\nasync function clAct",
            "function clBind(){document.querySelectorAll('#runs [data-cc]').forEach(b=>{b.onclick=()=>{clAct('close',+b.dataset.cc,0)}});"
            "document.querySelectorAll('#runs [data-cm]').forEach(b=>{b.onclick=()=>{const k=+b.dataset.k,a=b.dataset.cm,num=id=>parseFloat(String((document.getElementById(id)||{}).value).replace(',','.'));"
            "if(a==='stop'){const v=num('clsp_'+k);if(!(v>0)){alert('Укажите ЦЕНУ стопа числом, например 0.02830');return}clAct('stop',k,{price:v})}"
            "else if(a==='trail'){const v=num('cltp_'+k);if(!(v>0)){alert('Укажите расстояние трейлинга в процентах, например 0.6');return}clAct('trail',k,{pct:v})}"
            "else clAct('auto',k,{})}})}")
    h = seg(h, "async function clAct", "\nfunction clMan(p)",
            "async function clAct(a,id,x){if(S.clbusy)return;if(a==='close'&&!confirm('Закрыть позицию #'+id+' по текущей цене?'))return;S.clbusy=1;"
            "try{const j=await api('/api/claude',Object.assign({action:a,id:id},(x&&typeof x==='object')?x:{pct:x||0}));if(j.error)alert(j.error);else{S.cl=j;if(S.clin)delete S.clin[id]}}catch(e){alert(e.message)}S.clbusy=0;renderRuns()}")
    h = seg(h, "function clMan(p)", "\nfunction clHm",
            "function clMan(p){let h='';const c='<div class=sm style=\\\"margin-top:4px;color:#d29922\\\">';"
            "if(p.manual_trail)h+=c+'ручной трейлинг '+p.manual_trail+'% · стоп сейчас '+fmt(p.stop)+'</div>';"
            "if(p.stop_manual)h+=c+'ручной стоп '+fmt(p.stop)+' (установлен '+clHm(p.stop_manual_t)+'); БУ-перенос, трейлинг и перенос на уровень для этой позиции отключены, пока не нажато «Вернуть авто»</div>';"
            "if(p.sr_level&&!p.stop_manual)h+='<div class=sm style=\\\"margin-top:4px;color:#a371f7\\\">стоп по линии S/R '+fmt(p.sr_level.p)+' ('+p.sr_level.touches+' касания), перенесён '+clHm(p.sr_level.set_t)+'</div>';return h}\n"
            "function clStopBox(p){const id=p.id;S.clin=S.clin||{};const I=S.clin[id]=S.clin[id]||{};const sv=I.stop!==undefined?I.stop:String(+(+p.stop).toPrecision(7)),tv=I.trail!==undefined?I.trail:String(p.manual_trail||0.6);"
            "const st='background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:5px;';"
            "return '<div class=sm style=\\\"margin-top:6px\\\">Стоп, цена: <input id=clsp_'+id+' type=text inputmode=decimal value=\\\"'+sv+'\\\" oninput=\\\"S.clin['+id+'].stop=this.value\\\" style=\\\"width:100px;'+st+'\\\"> <button data-cm=stop data-k=\\\"'+id+'\\\">Поставить стоп</button></div>"
            "<div class=sm style=\\\"margin-top:4px\\\">Трейлинг, % от цены: <input id=cltp_'+id+' type=text inputmode=decimal value=\\\"'+tv+'\\\" oninput=\\\"S.clin['+id+'].trail=this.value\\\" style=\\\"width:64px;'+st+'\\\"> <button data-cm=trail data-k=\\\"'+id+'\\\">Включить трейлинг</button>'+(p.stop_manual?' <button data-cm=auto data-k=\\\"'+id+'\\\">Вернуть авто</button>':'')+'</div>"
            "<div class=sm style=\\\"margin-top:2px;color:#8b949e\\\">Стоп - цена, не проценты: '+(p.side==='long'?'лонг ниже текущей цены ':'шорт выше текущей цены ')+fmt(p.px)+', ликвидация '+fmt(p.liq_px)+'. Каждая позиция со своим полем.</div>'}")
    h = rep(h, "+p.r_now+'R'+clMan(p)+'<div style=", "+p.r_now+'R'+clMan(p)+clStopBox(p)+'<div style=")
    h = rep(h, "if(S.clzBusy)return;FIN(loadLine()+trackBar()+clCard())", "if(S.clzBusy)return;{const ae=document.activeElement;if(ae&&/^cl[st]p_/.test(ae.id||''))return}FIN(loadLine()+trackBar()+clCard())")
    lvl = "if(p.sr_level&&p.sr_level.p>0)sp.hl.push({v:p.sr_level.p,col:'#a371f7',txt:'S/R',w:1,dash:[2,2],t1:(p.sr_level.t_touch||[])[0]});"
    h = rep(h, "{v:p.px,col:'#58a6ff',txt:'цена',w:1,dash:[1,2]});", "{v:p.px,col:'#58a6ff',txt:'цена',w:1,dash:[1,2]});" + lvl, 2)
    open(fh, "w", encoding="utf-8").write(h); print("patched panel")
else: print("panel already patched")

if "stop_manual" not in q:
    q = rep(q, "        ps = load(); p = next((x for x in ps if x[\"id\"] == pid and x[\"status\"] == \"open\"), None)\n        if not p: return {\"error\": \"позиция не найдена или уже закрыта\"}",
               "        ps = _update(); p = next((x for x in ps if x[\"id\"] == pid and x[\"status\"] == \"open\"), None)   # патч 7: сначала догоняем свечи до «сейчас»\n        if not p: return {\"error\": \"позиция не найдена или уже закрыта\"}")
    q = rep(q, "        elif act in (\"stop\", \"trail\"):\n            if not (0.05 <= pct <= 20): return {\"error\": \"расстояние от 0.05 до 20 %\"}\n            dist = px * pct / 100\n            new_stop = px - side * dist                                   # лонг: ниже цены, шорт: выше цены\n            if act == \"stop\":\n                p[\"stop\"] = new_stop; p[\"manual_stop\"] = round(pct, 3)\n            else:\n                p[\"trail_dist\"]",
               "        elif act == \"stop\":   # патч 7: вводится ЦЕНА стопа\n"
               "            try: sp = float(str(o.get(\"price\", \"\")).replace(\",\", \".\"))\n"
               "            except Exception: return {\"error\": \"укажите цену стопа числом\"}\n"
               "            liq = p[\"entry\"] * (1 - side * LIQ / 100)\n"
               "            if side > 0 and not (liq < sp < px * 0.9998): return {\"error\": \"лонг: стоп должен быть ниже текущей цены %.8g и выше ликвидации %.8g\" % (px, liq)}\n"
               "            if side < 0 and not (px * 1.0002 < sp < liq): return {\"error\": \"шорт: стоп должен быть выше текущей цены %.8g и ниже ликвидации %.8g\" % (px, liq)}\n"
               "            old = p[\"stop\"]; p[\"stop\"] = sp; p[\"stop_manual\"] = True; p[\"stop_manual_t\"] = now; p[\"manual_stop_px\"] = sp; p.pop(\"manual_stop\", None); p.pop(\"manual_trail\", None)\n"
               "            p.setdefault(\"stop_hist\", []).append({\"t\": now, \"from\": old, \"to\": sp, \"by\": \"manual\"})\n"
               "        elif act == \"auto\":\n"
               "            p.pop(\"stop_manual\", None); p.pop(\"manual_stop_px\", None)\n"
               "        elif act == \"trail\":\n"
               "            if not (0.05 <= pct <= 20): return {\"error\": \"расстояние трейлинга от 0.05 до 20 %\"}\n"
               "            dist = px * pct / 100\n"
               "            if True:\n"
               "                p.pop(\"stop_manual\", None); p.pop(\"manual_stop_px\", None)\n"
               "                p[\"trail_dist\"]")
    q = rep(q, "        p[\"armed\"] = True; p[\"stop\"] = min(p[\"stop\"], p[\"lock_px\"]) if side < 0 else max(p[\"stop\"], p[\"lock_px\"]); p[\"armed_t\"] = t + 60000\n    if p[\"armed\"]:",
               "        p[\"armed\"] = True; p[\"armed_t\"] = t + 60000\n        if not p.get(\"stop_manual\"): p[\"stop\"] = min(p[\"stop\"], p[\"lock_px\"]) if side < 0 else max(p[\"stop\"], p[\"lock_px\"])\n    if p[\"armed\"] and not p.get(\"stop_manual\"):")
    open(fp, "w", encoding="utf-8").write(q); print("patched pos.py")
else: print("pos.py already patched")
