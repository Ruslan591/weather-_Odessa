# -*- coding: utf-8 -*-
"""Теневые позиции (пропущенные сигналы «ЗАХОДИТЬ» ведутся на бумаге, на счёт не влияют). Патч поверх рабочих файлов VPS, идемпотентный (повтор: ALREADY).
Файлы: tg_bot.py (запись теневой позиции в send_watch, ведение раз в минуту, команда /shadow), live_web.py (раздел «Теневые» на странице: данные), index.html (раздел «Теневые» на странице).
Использование: python3 patch_shadow.py tg_bot.py live_web.py index.html (любое подмножество). Сам модуль: bot/positions/tg_shadow.py. docs/topics/shadow_positions.md"""
import os, sys

BOT = [
 ("import", "except Exception: LRN = None\n",
  "except Exception: LRN = None\ntry: import tg_shadow as SH        # теневые бумажные позиции по пропущенным сигналам «ЗАХОДИТЬ» (на счёт не влияют); удалить файл -> без них\nexcept Exception: SH = None\n", "import tg_shadow as SH"),
 ("timer", "_res_t = [0.0]; _pos_t = [0.0];", "_sh_t = [0.0]; _res_t = [0.0]; _pos_t = [0.0];", "_sh_t = [0.0]"),
 ("record", "    if auto and ao_on():     # Автоордер: ставим через тот же путь",
  '''    if SH and not auto:     # теневая бумажная позиция: сигнал «заходить», который не стал ордером Автоордера (на счёт не влияет, tg_shadow.py)
        try:
            if (V and V.get("call") == "enter") or (Bk and Bk.get("call") == "enter"): SH.record(w, V, Bk, mid_new, "mon" if dest == MONCHAT else "main")
        except Exception as e: log("shadow record: %s" % e)
    if auto and ao_on():     # Автоордер: ставим через тот же путь''', "SH.record(w, V, Bk"),
 ("run", "        time.sleep(2)\n\n\ndef status_text():",
  '''        if SH and time.time() - _sh_t[0] > 60:      # теневые позиции: ведём открытые по свечам 1m, закрываем по цели / стопу / таймауту
            _sh_t[0] = time.time()
            try: SH.run()
            except Exception: log("shadow run: " + traceback.format_exc()[-300:])
        time.sleep(2)


def status_text():''', "SH.run()"),
 ("cmd", '    elif t.startswith("/tf"): tf_picker()\n',
  '    elif t.startswith("/tf"): tf_picker()\n    elif t.startswith("/shadow"): api("sendMessage", chat_id=CHAT, text=(SH.summary_text() if SH else "Теневые позиции недоступны."))\n', 'startswith("/shadow")'),
 ("menu", '{"command": "alerts", "description": "Алерты: отключить / включить"}])',
  '{"command": "alerts", "description": "Алерты: отключить / включить"}, {"command": "shadow", "description": "Теневые позиции (пропущенные сигналы)"}])', '"command": "shadow"'),
]

LIVE = [
 ("fn", "def derive(snap):",
  '''SH_F = ("id", "sym", "side", "kind", "tf", "entry", "stop", "tp", "t_in", "t_out", "exit", "reason", "net_pct", "r_mult", "mfe", "mae", "status", "rr")


def build_shadow():
    """Теневые позиции (пропущенные сигналы «заходить»): открытые и закрытые, без взятых в реальный ордер. Файл shadow.json пишет tg_bot, здесь только чтение."""
    d = jl("shadow.json"); its = d.get("items") if isinstance(d, dict) else None; out = []
    for i in (its or []):
        if i.get("status") not in ("open", "closed"): continue
        r = {k: i.get(k) for k in SH_F}; r["ch"] = i.get("ch"); out.append(r)
    out.sort(key=lambda x: (x["status"] == "open", x.get("t_out") or x.get("t_in") or 0), reverse=True)
    return out[:150]


def derive(snap):''', "def build_shadow("),
 ("syms", '''| {w["sym"] + "USDT" for w in watch}\n''',
  '''| {w["sym"] + "USDT" for w in watch} | {x["sym"] + "USDT" for x in [y for y in build_shadow() if y["status"] == "open"][:6]}\n''', 'for y in build_shadow() if y["status"] == "open"'),
 ("loop", '            ST["syms"] = syms; sig = json.dumps(st, sort_keys=True, ensure_ascii=False, default=str)\n',
  '''            try:
                shl = build_shadow(); ssig = json.dumps(shl, sort_keys=True, ensure_ascii=False, default=str)
                if ssig != ST.get("ssig"): ST["ssig"] = ssig; ST["sh"] = shl; await bcast({"t": "sh", "a": shl})
            except Exception as e: log("shadow: %s" % e)
            ST["syms"] = syms; sig = json.dumps(st, sort_keys=True, ensure_ascii=False, default=str)\n''', 'ST["ssig"]'),
 ("hello", '"arch": ST["arch"], "px": PX', '"arch": ST["arch"], "sh": ST.get("sh") or [], "px": PX', '"sh": ST.get("sh")'),
]

HTML = [
 ("sec", '<h2>Архив закрытых</h2><div class="card small" id="asum"></div><div id="arch"></div>',
  '<h2>👻 Теневые (пропущенные сигналы, на счёт не влияют)</h2><div class="card small" id="ssum"></div><div id="shad"></div>\n<h2>Архив закрытых</h2><div class="card small" id="asum"></div><div id="arch"></div>', 'id="shad"'),
 ("hello", "S.arch=m.arch||[];S.px=m.px||{}", "S.arch=m.arch||[];S.sh=m.sh||[];S.px=m.px||{}", "S.sh=m.sh||[]"),
 ("msg", "    else if(m.t==='arch'){S.arch=m.a||[]}\n", "    else if(m.t==='arch'){S.arch=m.a||[]}\n    else if(m.t==='sh'){S.sh=m.a||[]}\n", "m.t==='sh'"),
 ("call", "  renderArch();\n}\nfunction renderArch(){", "  renderArch();renderShadow();\n}\nfunction renderArch(){", "renderShadow();"),
 ("foot", "  if(CH.closed&&CH.exit!=null)f='Закрыта: '", "  if(CH.sh&&CH.exit==null){const pc_=px(CH.sym);f='👻 Теневая позиция ещё идёт'+(pc_!=null&&CH.entry?' · '+sg((pc_/CH.entry-1)*(CH.side==='long'?1:-1)*100,2)+'% от входа (до комиссий), обновится при повторном открытии':'')}\n  if(CH.closed&&CH.exit!=null)f='Закрыта: '", "CH.sh&&CH.exit==null"),
 ("fn", "function renderArch(){",
  '''const SH_RU={target:'цель',stop:'стоп',timeout:'таймаут'};
function renderShadow(){
  const A=S.sh||[],sm=$('#ssum'),el=$('#shad');if(!sm||!el)return;sm.replaceChildren();el.replaceChildren();
  if(!A.length){sm.textContent='Теневых позиций пока нет: сигналы «ЗАХОДИТЬ», по которым не открыта сделка, ведутся здесь на бумаге';return}
  const op=A.filter(p=>p.status==='open'),cl=A.filter(p=>p.status==='closed').sort((a,b)=>b.t_out-a.t_out),w=cl.filter(p=>(p.net_pct||0)>0).length,R=cl.reduce((x,p)=>x+(p.r_mult||0),0);
  sm.append('Открыто '+op.length+' · закрыто '+cl.length);
  if(cl.length)sm.append(' · плюс '+w+' / минус '+(cl.length-w)+' · успешных '+Math.round(w/cl.length*100)+'% · итого ',h('b',cls(R),sg(R,2)+' R'),' (после комиссий)');
  for(const p of op.concat(cl.slice(0,S.shN||15))){const r=h('div','ar'),o=p.status==='open',cur=o?px(p.sym):null,s=p.side==='long'?1:-1,rk=Math.abs(p.entry-p.stop),live=o&&cur!=null&&rk>0?(cur-p.entry)*s/rk:null,val=o?live:p.r_mult;
    r.onclick=()=>openChart({id:'S'+p.id,sh:1,sym:p.sym,side:p.side,entry:p.entry,exit:p.exit,stop:p.stop,tp:p.tp,t_in:p.t_in,t_out:p.t_out||Date.now(),reason:'👻 теневая, '+(SH_RU[p.reason]||p.reason||''),net_pct:p.net_pct,r_mult:p.r_mult,closed:1,ch:p.ch});
    r.append(h('span','mut small','👻'+p.id),h('span','mut small',dt(o?p.t_in:p.t_out)),h('b',null,p.sym.replace('USDT','')),side(p.side),h('span','small mut',p.kind==='break'?'пробой':'отбой'),h('span','sp'),h('span','small mut',o?'идёт':(SH_RU[p.reason]||'')),h('b',cls(val),val==null?'—':sg(val,2)+' R'),h('span','mut','📈'));el.append(r)}
  if(cl.length>(S.shN||15)){const m=h('button','cb','Показать ещё');m.style.margin='8px 0';m.onclick=()=>{S.shN=(S.shN||15)+30;dirty()};el.append(m)}
}
function renderArch(){''', "function renderShadow("),
]

FILES = {"tg_bot.py": BOT, "live_web.py": LIVE, "index.html": HTML}


def patch(path):
    edits = FILES.get(os.path.basename(path))
    if edits is None: print("SKIP", path); return 0
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in edits:
        if marker in out: print("ALREADY", os.path.basename(path), name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", os.path.basename(path), name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", os.path.basename(path), name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
