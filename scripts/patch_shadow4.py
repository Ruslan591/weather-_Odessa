# -*- coding: utf-8 -*-
"""Тени v4 (docs/topics/shadow_positions.md): патч поверх файлов с патчами v2 и v3. Идемпотентный. Использование: python3 patch_shadow4.py tg_bot.py live_web.py index.html
tg_bot.py: секунды во времени (hms) в сообщениях теней и в журнале реальных позиций (открыта / закрыта), вариант B не выкладывается в канал (только статистика и страница), заметки пользователя из канала «Фон» -> shadow_notes.jsonl с тихим подтверждением.
live_web.py: поля var и reg у теней. index.html: раздел «Теневые»: время с секундами, таймфрейм, вариант B отдельно от итога."""
import os, sys

NOTE = '''def shadow_note(m):
    """Сообщение пользователя в канале теней (ответ на сообщение тени или текст с #номером) -> shadow_notes.jsonl; бот отвечает тихим подтверждением."""
    try:
        chat = ENV.get("TG_CHAT_SHADOW")
        if not chat or not SH or str((m.get("chat") or {}).get("id")) != str(chat): return
        txt = m.get("text") or m.get("caption") or ""
        if not txt.strip() or txt.startswith("/"): return
        ids = SH.note_add(txt, mid=m.get("message_id"), reply_to=(m.get("reply_to_message") or {}).get("message_id"), t=int((m.get("date") or time.time()) * 1000))
        ack = "📝 Записал" + ((" к тени " + ", ".join("#%s" % i for i in ids)) if ids else " (без привязки к тени: ответьте на сообщение тени или укажите #номер)") + "."
        tg_try("sendMessage", {"chat_id": chat, "text": ack, "reply_to_message_id": m.get("message_id"), "disable_notification": "true"})
    except Exception as e: log("shadow note: %s" % e)


def shadow_tg_loop():'''

BOT = [
 ("hms", 'def hhmm(ms): return datetime.fromtimestamp(ms / 1000, T._tz()).strftime("%H:%M")\n', 'def hhmm(ms): return datetime.fromtimestamp(ms / 1000, T._tz()).strftime("%H:%M")\ndef hms(ms): return datetime.fromtimestamp(ms / 1000, T._tz()).strftime("%H:%M:%S")      # время с секундами (контроль входа)\n', "def hms(ms)"),
 ("t1", "SH.text_gate(it, hhmm, shadow_link(it))", "SH.text_gate(it, hms, shadow_link(it))", "SH.text_gate(it, hms, shadow_link(it))"),
 ("t2", "SH.caption(it, hhmm, float(kl[-1][4]) if kl else None)", "SH.caption(it, hms, float(kl[-1][4]) if kl else None)", "SH.caption(it, hms,"),
 ("t3", 'SH.postmortem(it, hhmm)', 'SH.postmortem(it, hms)', "SH.postmortem(it, hms)"),
 ("t4", "SH.summary_text(hhmm)", "SH.summary_text(hms)", "SH.summary_text(hms)"),
 ("j1", '· закрыта %s · %s" % (ic, p["id"], sym, p["side"].upper(), hhmm(p["t_out"]),', '· закрыта %s · %s" % (ic, p["id"], sym, p["side"].upper(), hms(p["t_out"]),', 'p["side"].upper(), hms(p["t_out"]),'),
 ("j2", '· открыта %s" % (p["id"], sym, p["side"].upper(), hhmm(p["t_in"]))', '· открыта %s" % (p["id"], sym, p["side"].upper(), hms(p["t_in"]))', 'p["side"].upper(), hms(p["t_in"])'),
 ("bskip", '        if it["status"] == "taken": continue\n        iid = it["id"]; m = SH.msg_get(iid)', '        if it["status"] == "taken" or (it.get("var") == "B" and not SH.cfg().get("b_post")): continue      # вариант B: только статистика и страница\n        iid = it["id"]; m = SH.msg_get(iid)', 'it.get("var") == "B" and not SH.cfg().get("b_post")'),
 ("note", "def shadow_tg_loop():", NOTE, "def shadow_note"),
 ("upd", 'elif "channel_post" in u: seen_chat(u["channel_post"].get("chat"))', 'elif "channel_post" in u: seen_chat(u["channel_post"].get("chat")); shadow_note(u["channel_post"])', 'shadow_note(u["channel_post"])'),
]

LIVE = [("var", '"ch": {k: ch[k] for k in ("upper", "lower", "type") if k in ch} or None}', '"ch": {k: ch[k] for k in ("upper", "lower", "type") if k in ch} or None, "var": i.get("var") or "A", "reg": i.get("reg")}', '"var": i.get("var") or "A"')]

HTML_NEW = '''function dts(ms){const d=new Date(ms);return d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function tms(ms){return new Date(ms).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
const SH_RU={target:'цель',stop:'стоп','trail/BE':'БУ/трейл',time:'время',liquidation:'ликвидация'};
function renderShadow(){ /*SHADOW_V3*/
  const ALL=S.sh||[],A=ALL.filter(p=>p.var!=='B'),Bv=ALL.filter(p=>p.var==='B'),sm=$('#ssum'),el=$('#shad');if(!sm||!el)return;sm.replaceChildren();el.replaceChildren();
  if(!ALL.length){sm.textContent='Теневых сделок пока нет: сигналы «ЗАХОДИТЬ», по которым не открыта сделка, ведутся здесь на бумаге по тем же правилам входа и сопровождения, что ваши ручные';return}
  const act=A.filter(p=>p.status==='gate'||p.status==='open'),cl=A.filter(p=>p.status==='closed'),fl=A.filter(p=>p.status==='filtered'),w=cl.filter(p=>(p.net_pct||0)>0).length,R=cl.reduce((x,p)=>x+(p.r_mult||0),0),cfR=fl.reduce((x,p)=>x+(p.cf_r||0),0);
  sm.append('В работе '+act.length+' · вошли и закрыты '+cl.length);
  if(cl.length)sm.append(' (плюс '+w+' / минус '+(cl.length-w)+', итого ',h('b',cls(R),sg(R,2)+' R'),')');
  if(fl.length)sm.append(' · фильтр входа не пустил '+fl.length+' (без фильтра было бы ',h('b',cls(cfR),sg(cfR,2)+' R'),')');
  if(Bv.length){const bc=Bv.filter(p=>p.status==='closed'),bR=bc.reduce((x,p)=>x+(p.r_mult||0),0);sm.append(h('div','mut small','Вариант B (вход ждёт пробоя канала регрессии свечи контроля): вошли и закрыты '+bc.length+', итого '+sg(bR,2)+' R, в работе '+Bv.filter(p=>p.status==='gate'||p.status==='open').length))}
  const done=ALL.filter(p=>p.status==='closed'||p.status==='filtered').sort((a,b)=>(b.t_out||b.t_sig||0)-(a.t_out||a.t_sig||0));
  for(const p of ALL.filter(p=>p.status==='gate'||p.status==='open').concat(done.slice(0,S.shN||15))){const r=h('div','ar'),s=p.side==='long'?1:-1,rk=Math.abs(p.entry-p.stop),cur=p.status==='open'?px(p.sym):null,live=cur!=null&&rk>0?(cur-p.entry)*s/rk:null;
    let lab,val;if(p.status==='gate'){lab='ждёт свечу контроля'+(p.tries?' ('+p.tries+')':'');val=null}else if(p.status==='open'){lab='идёт';val=live}else if(p.status==='closed'){lab=SH_RU[p.reason]||p.reason||'';val=p.r_mult}else{lab='не вошла';val=p.cf_r}
    const why=p.status==='filtered'?'не вошла'+(p.cf_r!=null?', без фильтра '+sg(p.cf_r,2)+' R':''):(p.status==='gate'?'ждёт свечу контроля':'');
    r.onclick=()=>openChart({id:'S'+p.id,sh:1,sym:p.sym,side:p.side,entry:p.entry,exit:p.exit,stop:p.stop,tp:p.tp,t_in:p.t_in,t_out:p.t_out||Date.now(),reason:'👻 тень'+(p.var==='B'?' B':'')+' '+(p.tf||'5m')+', вход '+tms(p.t_in)+', '+(p.status==='filtered'?'без фильтра, ':'')+(SH_RU[p.reason]||p.reason||why),net_pct:p.net_pct,r_mult:p.status==='filtered'?p.cf_r:p.r_mult,closed:1,ch:p.ch});
    r.append(h('span','mut small','👻'+p.id+(p.var==='B'?'B':'')),h('span','mut small',dts(p.status==='closed'?p.t_out:(p.status==='open'?p.t_in:(p.t_sig||p.t_in)))),h('b',null,p.sym.replace('USDT','')),side(p.side),h('span','small mut',(p.kind==='break'?'пробой':'отбой')+' '+(p.tf||'5m')),h('span','sp'),h('span','small mut',lab),h('b',cls(val),val==null?'—':(p.status==='filtered'?'('+sg(val,2)+')':sg(val,2))+' R'),h('span','mut','📈'));el.append(r)}
  if(done.length>(S.shN||15)){const m=h('button','cb','Показать ещё');m.style.margin='8px 0';m.onclick=()=>{S.shN=(S.shN||15)+30;dirty()};el.append(m)}
}
'''


def patch(path):
    base = os.path.basename(path); s = open(path, encoding="utf-8").read(); out = s; bad = 0
    if base == "tg_bot.py":
        for name, old, new, marker in BOT:
            if marker in out: print("ALREADY", base, name); continue
            if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
            out = out.replace(old, new, 1); print("APPLIED", base, name)
    elif base == "live_web.py":
        for name, old, new, marker in LIVE:
            if marker in out: print("ALREADY", base, name); continue
            if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
            out = out.replace(old, new, 1); print("APPLIED", base, name)
    elif base == "index.html":
        if "SHADOW_V3" in out: print("ALREADY", base, "renderShadow")
        else:
            a = out.find("const SH_RU="); b = out.find("function renderArch(){")
            if a < 0 or b < a: print("ANCHOR_FAIL", base, "renderShadow"); bad += 1
            else: out = out[:a] + HTML_NEW + out[b:]; print("APPLIED", base, "renderShadow")
    else: print("SKIP", path); return 0
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
