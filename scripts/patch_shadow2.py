# -*- coding: utf-8 -*-
"""Тени v2 (docs/topics/shadow_positions.md): патч поверх файлов, где уже стоит патч v1 (scripts/patch_shadow.py). Идемпотентный.
tg_bot.py: запись сигнала с выбором Автоордера (ao_pick), движок тени в своём потоке (SH.loop), отдельный канал TG_CHAT_SHADOW (сигнал и проверка входа, график позиции с событиями, разбор итога), /shadow.
live_web.py: build_shadow() для новой модели (ждёт 1m / идёт / закрыта / не вошла по фильтру). index.html: раздел «Теневые» с новыми состояниями.
Использование: python3 patch_shadow2.py tg_bot.py live_web.py index.html"""
import os, sys

TG_CODE = '''# ---------- Тени: канал TG_CHAT_SHADOW (все события теневых сделок идут только сюда, остальные ленты не затрагиваются; tg_shadow.py) ----------
_SHW = [0.0]


def shadow_link(it):
    try:
        mid = it.get("mid")
        if not mid: return None
        ch = str(kchat(mid))
        return ("пост https://t.me/c/%s/%s" % (ch[4:], rmid(mid))) if ch.startswith("-100") else None
    except Exception: return None


def _shc(method, fields, files=None):
    r = tg_try(method, fields, files)
    if r[0] == "wait": _SHW[0] = time.time() + r[1] + 1
    elif r[0] is False: _SHW[0] = time.time() + 30; log("shadow: ошибка Telegram: %s" % str(r[1])[:200])
    return r


def shadow_kl(sym, t_in, tf):
    """Свечи графика тени на таймфрейме сигнала (5m, 15m, 1h, 4h, 1d); возвращает (свечи, размер свечи мс)."""
    import urllib.request
    tf = tf if tf in ("5m", "15m", "1h", "4h", "1d") else "5m"; bar = T.TFMS.get(tf, 300000)
    return json.load(urllib.request.urlopen("https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=%s&startTime=%d&limit=500" % (sym, tf, max(0, int(t_in) - 60 * bar)), timeout=15)), bar


def _mid_of(r):
    try: return r[1]["result"]["message_id"]
    except Exception: return None


def shadow_tg_step(chat, n_max=4):
    """Один проход: по каждой тени (А) текст сигнала и проверки входа, правится по ходу; (Б) график позиции с событиями, правится; (В) разбор итога отдельным сообщением со звуком."""
    n = 0
    for it in sorted(SH.snapshot(), key=lambda x: x["id"]):
        if n >= n_max or time.time() < _SHW[0]: break
        if it["status"] == "taken": continue
        iid = it["id"]; m = SH.msg_get(iid)
        if m.get("skip"): continue
        now = time.time(); st = it["status"]; ta = SH.text_gate(it, hhmm, shadow_link(it))
        if not m.get("a"):
            r = _shc("sendMessage", {"chat_id": chat, "text": ta, "disable_notification": "true", "disable_web_page_preview": "true"})
            if r[0] is not True or not _mid_of(r): continue
            SH.msg_set(iid, a=_mid_of(r), a_sig=ta, a_t=now); m = SH.msg_get(iid); n += 1
        elif m.get("a_sig") != ta and now - m.get("a_t", 0) >= 20:
            r = _shc("editMessageText", {"chat_id": chat, "message_id": m["a"], "text": ta, "disable_web_page_preview": "true"})
            if r[0] is True: SH.msg_set(iid, a_sig=ta, a_t=now); n += 1
            elif r[0] == "gone": SH.msg_set(iid, a=None); continue
            m = SH.msg_get(iid)
        p = it.get("p")
        if st in ("open", "closed") and p:
            closed = p.get("status") == "closed"; sig = [closed, bool(p.get("armed")), round(p.get("rem", 1.0), 3), p.get("stop"), len(it.get("ev") or [])]
            if m.get("b_sig") != sig or (not closed and now - m.get("b_t", 0) >= 300):
                try:
                    kl, bar = shadow_kl(p["sym"], p["t_in"], it.get("tf")); ob = T.BAR_MS; T.BAR_MS = bar
                    try: png = T.render_position(p, kl, chan=it.get("chan"))
                    finally: T.BAR_MS = ob
                    cap = SH.caption(it, hhmm, float(kl[-1][4]) if kl else None)
                except Exception as e:
                    fl = int(m.get("b_fail", 0)) + 1; log("shadow: график #%s не построен (%d): %s" % (iid, fl, e)); SH.msg_set(iid, b_t=now, b_fail=fl, **({"b_sig": sig} if fl >= 3 else {})); m = SH.msg_get(iid); png = None
                if png:
                    files = {"photo": ("trade.png", png, "image/png")}
                    if m.get("b"): r = _shc("editMessageMedia", {"chat_id": chat, "message_id": m["b"], "media": json.dumps({"type": "photo", "media": "attach://photo", "caption": cap}, ensure_ascii=False)}, files)
                    else: r = _shc("sendPhoto", {"chat_id": chat, "caption": cap, "disable_notification": "true"}, files)
                    if r[0] is True: SH.msg_set(iid, b=(m.get("b") or _mid_of(r)), b_sig=sig, b_t=now, b_fail=0); n += 1
                    elif r[0] == "gone": SH.msg_set(iid, b=None)
                    m = SH.msg_get(iid)
        need_c = (st == "closed" and (m.get("b_sig") or [False])[0] is True) or (st == "filtered" and (not it.get("cf") or it["cf"].get("status") == "closed"))
        if need_c and not m.get("c") and n < n_max:
            f = {"chat_id": chat, "text": SH.postmortem(it, hhmm), "disable_web_page_preview": "true"}; rp = m.get("b") or m.get("a")
            r = _shc("sendMessage", dict(f, reply_to_message_id=rp) if rp else f)
            if r[0] == "gone": r = _shc("sendMessage", f)
            if r[0] is True: SH.msg_set(iid, c=_mid_of(r) or 1); n += 1
    return n


def shadow_tg_loop():
    chat = ENV.get("TG_CHAT_SHADOW")
    if not chat or not SH: log("shadow: TG_CHAT_SHADOW не задан или модуль не загружен: сообщения в канал выключены (записи и страница работают)"); return
    log("shadow: канал %s" % chat)
    try:
        for it in SH.snapshot():     # при первом запуске старые итоги не выкладываем
            if it["status"] in ("closed", "filtered", "void", "taken") and not SH.msg_get(it["id"]): SH.msg_set(it["id"], skip=1)
    except Exception as e: log("shadow: старт: %s" % e)
    while True:
        try: time.sleep(8); shadow_tg_step(chat)
        except Exception: log("shadow tg: " + traceback.format_exc()[-400:]); time.sleep(20)


'''

BOT = [
 ("rec", 'SH.record(w, V, Bk, mid_new, "mon" if dest == MONCHAT else "main")', 'SH.record(w, V, Bk, mid_new, "mon" if dest == MONCHAT else "main", ao_pick(V, Bk))', 'else "main", ao_pick(V, Bk))'),
 ("run", '''        if SH and time.time() - _sh_t[0] > 60:      # теневые позиции: ведём открытые по свечам 1m, закрываем по цели / стопу / таймауту
            _sh_t[0] = time.time()
            try: SH.run()
            except Exception: log("shadow run: " + traceback.format_exc()[-300:])
''', "        # тени v2: движок работает в своём потоке (SH.loop), сообщения в канал шлёт shadow_tg_loop\n", "тени v2: движок работает в своём потоке"),
 ("cmd", "SH.summary_text() if SH else", "SH.summary_text(hhmm) if SH else", "SH.summary_text(hhmm)"),
 ("code", "# ---------- Сводка обучения в канале TG_CHAT_REVIEWS", TG_CODE + "# ---------- Сводка обучения в канале TG_CHAT_REVIEWS", "def shadow_tg_loop"),
 ("thr", "    threading.Thread(target=journal_loop, daemon=True).start()\n", "    threading.Thread(target=journal_loop, daemon=True).start()\n    if SH: threading.Thread(target=SH.loop, daemon=True).start()\n    threading.Thread(target=shadow_tg_loop, daemon=True).start()\n", "target=shadow_tg_loop"),
]

LIVE_NEW = '''SH_V1 = ("id", "sym", "side", "kind", "tf", "entry", "stop", "tp", "t_in", "t_out", "exit", "reason", "net_pct", "r_mult", "mfe", "mae", "status", "rr")


def build_shadow():
    """SHADOW_V2. Тени (пропущенные сигналы «заходить»): ждёт свечу 1m (gate), идёт (open), закрыта (closed), не вошла по фильтру входа (filtered, с итогом «без фильтра» cf_r). Файл shadow.json пишет tg_bot, здесь только чтение."""
    d = jl("shadow.json"); its = d.get("items") if isinstance(d, dict) else None; out = []
    for i in (its or []):
        st = i.get("status")
        if st not in ("gate", "open", "closed", "filtered"): continue
        if "o" not in i and "p" not in i:      # записи первой версии
            r = {k: i.get(k) for k in SH_V1}; r["ch"] = i.get("ch"); out.append(r); continue
        p = i.get("p") or {}; cf = i.get("cf") or {}; o = i.get("o") or {}; pl = i.get("plan") or {}; src = p or cf
        cl = (p if st in ("open", "closed") else cf) or {}; done = cl.get("status") == "closed"
        ch = i.get("chan") or {}
        r = {"id": i["id"], "sym": i["sym"], "side": i["side"], "kind": i.get("kind"), "tf": i.get("tf"), "status": st, "t_sig": i.get("t0"),
             "entry": src.get("entry") or o.get("price") or pl.get("entry"), "stop": src.get("stop0") or o.get("stop") or pl.get("stop"), "tp": src.get("tp") or o.get("tp") or pl.get("tp"),
             "t_in": src.get("t_in") or i.get("t0"), "t_out": cl.get("t_out") if done else None, "exit": cl.get("exit") if done else None, "reason": cl.get("reason") if done else None,
             "net_pct": cl.get("net_pct") if done else None, "r_mult": (cl.get("r_mult") if done else None) if st != "filtered" else None, "cf_r": cf.get("r_mult") if (st == "filtered" and done) else None,
             "mfe": i.get("mfe_r"), "mae": i.get("mae_r"), "why": i.get("why"), "tries": o.get("live1m_tries"), "rr": pl.get("rr"),
             "ch": {k: ch[k] for k in ("upper", "lower", "type") if k in ch} or None}
        out.append(r)
    out.sort(key=lambda x: (x["status"] in ("gate", "open"), x.get("t_out") or x.get("t_sig") or x.get("t_in") or 0), reverse=True)
    return out[:150]


'''

HTML_NEW = '''const SH_RU={target:'цель',stop:'стоп','trail/BE':'БУ/трейл',time:'время',liquidation:'ликвидация'};
function renderShadow(){ /*SHADOW_V2*/
  const A=S.sh||[],sm=$('#ssum'),el=$('#shad');if(!sm||!el)return;sm.replaceChildren();el.replaceChildren();
  if(!A.length){sm.textContent='Теневых сделок пока нет: сигналы «ЗАХОДИТЬ», по которым не открыта сделка, ведутся здесь на бумаге по тем же правилам входа и сопровождения, что ваши ручные';return}
  const act=A.filter(p=>p.status==='gate'||p.status==='open'),cl=A.filter(p=>p.status==='closed'),fl=A.filter(p=>p.status==='filtered'),w=cl.filter(p=>(p.net_pct||0)>0).length,R=cl.reduce((x,p)=>x+(p.r_mult||0),0),cfR=fl.reduce((x,p)=>x+(p.cf_r||0),0);
  sm.append('В работе '+act.length+' · вошли и закрыты '+cl.length);
  if(cl.length)sm.append(' (плюс '+w+' / минус '+(cl.length-w)+', итого ',h('b',cls(R),sg(R,2)+' R'),')');
  if(fl.length)sm.append(' · фильтр входа не пустил '+fl.length+' (без фильтра было бы ',h('b',cls(cfR),sg(cfR,2)+' R'),')');
  const done=A.filter(p=>p.status==='closed'||p.status==='filtered').sort((a,b)=>(b.t_out||b.t_sig||0)-(a.t_out||a.t_sig||0));
  for(const p of act.concat(done.slice(0,S.shN||15))){const r=h('div','ar'),s=p.side==='long'?1:-1,rk=Math.abs(p.entry-p.stop),cur=p.status==='open'?px(p.sym):null,live=cur!=null&&rk>0?(cur-p.entry)*s/rk:null;
    let lab,val;if(p.status==='gate'){lab='ждёт свечу 1m'+(p.tries?' ('+p.tries+')':'');val=null}else if(p.status==='open'){lab='идёт';val=live}else if(p.status==='closed'){lab=SH_RU[p.reason]||p.reason||'';val=p.r_mult}else{lab='не вошла';val=p.cf_r}
    const why=p.status==='filtered'?'не вошла (фильтр входа)'+(p.cf_r!=null?', без фильтра '+sg(p.cf_r,2)+' R':''):(p.status==='gate'?'ждёт свечу 1m':'');
    r.onclick=()=>openChart({id:'S'+p.id,sh:1,sym:p.sym,side:p.side,entry:p.entry,exit:p.exit,stop:p.stop,tp:p.tp,t_in:p.t_in,t_out:p.t_out||Date.now(),reason:'👻 теневая, '+(p.status==='filtered'?'без фильтра, ':'')+(SH_RU[p.reason]||p.reason||why),net_pct:p.net_pct,r_mult:p.status==='filtered'?p.cf_r:p.r_mult,closed:1,ch:p.ch});
    r.append(h('span','mut small','👻'+p.id),h('span','mut small',dt(p.status==='closed'?p.t_out:(p.t_sig||p.t_in))),h('b',null,p.sym.replace('USDT','')),side(p.side),h('span','small mut',p.kind==='break'?'пробой':'отбой'),h('span','sp'),h('span','small mut',lab),h('b',cls(val),val==null?'—':(p.status==='filtered'?'('+sg(val,2)+')':sg(val,2))+' R'),h('span','mut','📈'));el.append(r)}
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
        if "SHADOW_V2" in out: print("ALREADY", base, "build_shadow")
        else:
            a = out.find("SH_F = ("); b = out.find("def derive(snap):")
            if a < 0 or b < a: print("ANCHOR_FAIL", base, "build_shadow"); bad += 1
            else: out = out[:a] + LIVE_NEW + out[b:]; print("APPLIED", base, "build_shadow")
    elif base == "index.html":
        if "SHADOW_V2" in out: print("ALREADY", base, "renderShadow")
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
