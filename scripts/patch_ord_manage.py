# -*- coding: utf-8 -*-
"""Управление ждущим ордером со страницы онлайн (порт 18111): отмена, перестановка входа, стопа и цели.
Накладывается на файлы по якорям, повторный запуск ничего не меняет. Использование:
  python3 patch_ord_manage.py FILE [FILE...]   (имена: chan_orders.py, pos.py, live_web.py, index.html)
Печатает APPLIED / ALREADY / ANCHOR_FAIL по каждой правке. Деплой: scripts/deploy_ord_manage.sh. docs/topics/live_web.md"""
import os, sys

MANUAL = r'''def manual_order(o):
    """Ручное управление ждущим ордером (страница онлайн -> live_web -> acct-api -> pos.api_action). Действия: ord_cancel; ord_edit с любыми из price (вход), stop, tp.
    Всё под pos.lock(), как и cycle(), поэтому орудие бота и ручная правка не пересекаются. Ордер с правкой получает флаг man: автоматика (пересчёт границы, «условия исчезли») его не трогает."""
    act = o.get("action")
    try: oid = int(o.get("id"))
    except Exception: return {"error": "не указан ордер"}
    def num(k):
        v = o.get(k)
        if v is None or v == "": return None
        v = float(str(v).replace(",", "."))
        if not (v > 0 and v < 1e12): raise ValueError(k)
        return v
    try: np_, ns, nt = num("price"), num("stop"), num("tp")
    except Exception: return {"error": "цена должна быть положительным числом"}
    now = int(time.time() * 1000)
    with pos.lock():
        orders = load_orders(); x = next((v for v in orders if v["id"] == oid), None)
        if not x or x.get("status") != "pending": return {"error": "ордер не найден или уже не ждёт исполнения (исполнен, отменён или истёк)"}
        if act == "ord_cancel":
            why = "отменён пользователем (страница онлайн)"
            x.update(status="cancelled", reason=why, t_end=now); x.setdefault("edits", []).append({"t": now, "what": "cancel"})
            save_orders(orders); log("ORDER %d %s %s: %s" % (oid, x["sym"], x["side"], why))
            return {"ok": True, "id": oid}
        if act != "ord_edit": return {"error": "неизвестное действие"}
        if np_ is None and ns is None and nt is None: return {"error": "нечего менять"}
        if x.get("rule") == "tg_market": return {"error": "рыночный ордер исполняется сразу, менять нечего (его можно только отменить)"}
        try: cur = float(pos.price(x["sym"] + "USDT"))
        except Exception as e: return {"error": "нет текущей цены: %s" % e}
        lg = x["side"] == "long"; sd = 1 if lg else -1
        price = np_ if np_ is not None else x["price"]; stop = ns if ns is not None else x["stop"]; tp = nt if nt is not None else x["tp"]
        if np_ is not None:
            if x.get("rule") == "tg_stop":
                if not ((price > cur * 1.0002) if lg else (price < cur * 0.9998)): return {"error": "стоп-ордер на вход: цена должна быть %s текущей %.8g" % ("выше" if lg else "ниже", cur)}
            elif not ((price < cur * 0.9998) if lg else (price > cur * 1.0002)):
                return {"error": "лимит %s должен стоять %s текущей цены %.8g (иначе исполнится сразу; для входа сейчас отмените ордер и выставьте по рынку)" % (x["side"], "ниже" if lg else "выше", cur)}
        if not sd * (price - stop) > 0: return {"error": "стоп должен быть %s входа %.8g" % ("ниже" if lg else "выше", price)}
        if not sd * (tp - price) > 0: return {"error": "цель должна быть %s входа %.8g" % ("выше" if lg else "ниже", price)}
        if abs(tp - price) < price * 0.0015: return {"error": "цель ближе 0.15% от входа: комиссии съедят прибыль"}
        liq = price * (1 - sd * pos.LIQ / 100)
        if not ((stop > liq) if lg else (stop < liq)): return {"error": "стоп за ценой ликвидации %.8g" % liq}
        if np_ is not None and ((now // 60000) + 1) * 60000 >= x["expire_t"]: return {"error": "срок жизни ордера почти вышел, переставлять поздно"}
        old = {"price": x["price"], "stop": x["stop"], "tp": x["tp"]}
        x.update(price=price, stop=stop, tp=tp, man=True, edit_t=now)
        if nt is not None: x["man_tp"] = True
        if np_ is not None and np_ != old["price"]:
            x["px_t"] = now; x.setdefault("placed_t0", x["placed_t"]); x["placed_t"] = ((now // 60000) + 1) * 60000   # без заглядывания в прошлое: проверка касания с начала следующей минуты
        if not x.get("approved_t"): x["approved_t"] = now   # ручная правка = пользователь подтвердил ордер (сон его не отменит)
        x.setdefault("edits", []).append({"t": now, "from": old, "to": {"price": price, "stop": stop, "tp": tp}})
        save_orders(orders)
        log("ORDER %d %s %s edited by user: price %.6g->%.6g stop %.6g->%.6g tp %.6g->%.6g" % (oid, x["sym"], x["side"], old["price"], price, old["stop"], stop, old["tp"], tp))
        return {"ok": True, "id": oid, "price": price, "stop": stop, "tp": tp}


'''

EDITS = {
"chan_orders.py": [
 ("manual_def", "def pair_view(sym):", MANUAL + "def pair_view(sym):", "def manual_order(o):"),
 ("retest_loop", '                if x["rule"] in ("retest_up", "retest_down"):\n                    lv = x["level"]["p"]',
  '                if x["rule"] in ("retest_up", "retest_down") and not x.get("man"):\n                    lv = x["level"]["p"]', 'in ("retest_up", "retest_down") and not x.get("man")'),
 ("same_orders", 'same = [x for x in pend_sym if x["rule"] == p["rule"] and x["side"] == p["side"]]',
  'same = [x for x in pend_sym if x["rule"] == p["rule"] and x["side"] == p["side"]]\n                if any(x.get("man") for x in same): continue   # вручную изменённый ордер: не пересчитываем и дубль рядом не ставим', 'if any(x.get("man") for x in same)'),
 ("vanished", 'and x["rule"] in ("chan_top", "chan_bottom") and not any(pp[', 'and x["rule"] in ("chan_top", "chan_bottom") and not x.get("man") and not any(pp[', 'and not x.get("man") and not any(pp['),
 ("replaced_rules", 'if x["status"] == "pending" and ((x["rule"] in ("chan_top", "chan_bottom") and not CHAN_EDGE)', 'if x["status"] == "pending" and not x.get("man") and ((x["rule"] in ("chan_top", "chan_bottom") and not CHAN_EDGE)', 'and not x.get("man") and ((x["rule"]'),
 ("fill_guard", '            if not o or o["status"] != "pending": continue\n            sym = o["sym"] + "USDT"',
  '            if not o or o["status"] != "pending": continue\n            if o.get("px_t") and ft < o["px_t"]: continue   # цену ордера вручную сдвинули после этой свечи: старую заливку не применяем\n            sym = o["sym"] + "USDT"', 'o.get("px_t") and ft < o["px_t"]'),
 ("man_tp", '            ps_.append(p); o.update(status="filled", fill_t=ft, fill_px=fp, pos_id=p["id"], t_end=ft)',
  '            if o.get("man_tp") and o.get("tp") and (o["tp"] - fp) * side > 0:   # цель выставлена вручную на ордере: настройки выхода счёта её не заменяют\n                p["tp_manual"] = o["tp"]; p["tp_manual_t"] = ft; p["thesis"] += " Цель задана вручную на ордере: %.6g." % o["tp"]\n            ps_.append(p); o.update(status="filled", fill_t=ft, fill_px=fp, pos_id=p["id"], t_end=ft)', 'o.get("man_tp") and o.get("tp")'),
],
"pos.py": [
 ("api_ord", 'def api_action(o):\n    if o.get("action") == "chart":',
  'def api_action(o):\n    if o.get("action") in ("ord_cancel", "ord_edit"):   # ручное управление ждущим ордером (страница онлайн)\n        try:\n            import chan_orders\n            return chan_orders.manual_order(o)\n        except Exception as e:\n            return {"error": str(e)}\n    if o.get("action") == "chart":', '"ord_cancel", "ord_edit"'),
],
"live_web.py": [
 ("acts", 'ACTS = {"close", "stop", "tp", "tp_auto", "auto", "trail"}', 'ACTS = {"close", "stop", "tp", "tp_auto", "auto", "trail", "ord_cancel", "ord_edit"}', '"ord_cancel", "ord_edit"}'),
 ("body", '        if a == "trail": body["pct"] = float(q.get("pct"))',
  '        if a == "trail": body["pct"] = float(q.get("pct"))\n        if a == "ord_edit":\n            for k_ in ("price", "stop", "tp"):\n                if q.get(k_) is not None:\n                    v_ = float(q[k_])\n                    if not (0 < v_ < 1e12): raise ValueError(k_)\n                    body[k_] = v_', 'a == "ord_edit":'),
],
"index.html": [
 ("ctl_on", "const on=S.ctl&&CH&&CH.kind==='pos';pn.hidden=!on;if(!on)return;", "const on=S.ctl&&CH&&(CH.kind==='pos'||CH.kind==='pend');pn.hidden=!on;if(!on)return;if(CH.kind==='pend')return buildOrdCtl(pn);", "buildOrdCtl(pn);"),
 ("funcs", "function priceAtY(y){", r'''/* ---- управление ждущим ордером ---- */
function buildOrdCtl(pn){
  const nm=usd(CH.sym).replace('USDT',''),sdn=CH.side.toUpperCase();
  const B=[['Отменить',()=>sheet('Отменить ордер '+sdn+' '+nm+'?','Вход '+fp(CH.entry)+' · стоп '+fp(CH.stop)+' · цель '+fp(CH.tp),[['Назад'],['Отменить ордер',()=>act('ord_cancel'),'red']]),'red'],
    ['Вход',()=>ordPrompt('entry')],['Стоп',()=>ordPrompt('stop')],['Цель',()=>ordPrompt('tp')]];
  for(const [l,f,c] of B){const b=h('button','cb'+(c?' '+c:''),l);b.onclick=f;pn.append(b)}
}
function ordPrompt(key){
  const old=key==='entry'?CH.entry:CH[key],nm={entry:'вход',stop:'стоп',tp:'цель'}[key];
  const v=window.prompt('Новая цена: '+nm+' (сейчас '+fp(old)+')',String(old));if(v==null)return;
  const x=parseFloat(String(v).replace(',','.'));if(!isFinite(x)||x<=0){toast('Неверная цена',false);return}ordConfirm(key,x)
}
function ordConfirm(key,price){
  const cur=px(CH.sym),lg=CH.side==='long',sd=lg?1:-1,stopOrd=CH.rule==='tg_stop',nm={entry:'Вход',stop:'Стоп',tp:'Цель'}[key];
  const fail=t=>{toast(t,false);CH.drag=null;dirty()};
  if(CH.rule==='tg_market')return fail('Рыночный ордер исполняется сразу: менять нечего, его можно только отменить');
  if(key==='entry'&&cur!=null){const ok=stopOrd?(lg?price>cur:price<cur):(lg?price<cur:price>cur);
    if(!ok)return fail(stopOrd?'Стоп-ордер на вход должен быть '+(lg?'выше':'ниже')+' текущей цены':'Лимит должен стоять '+(lg?'ниже':'выше')+' текущей цены, иначе исполнится сразу')}
  const e=key==='entry'?price:CH.entry,s=key==='stop'?price:CH.stop,t=key==='tp'?price:CH.tp;
  const relOk=sd*(e-s)>0&&sd*(t-e)>0;
  if(!relOk&&key!=='entry')return fail(key==='stop'?'Стоп должен быть '+(lg?'ниже':'выше')+' входа':'Цель должна быть '+(lg?'выше':'ниже')+' входа');
  const R=Math.abs(e-s),rr=R?Math.abs(t-e)/R:null,old=key==='entry'?CH.entry:CH[key],dp=(price/old-1)*100;
  const det=fp(old)+' → '+fp(price)+' ('+sg(dp,2)+'%)'+(rr!=null&&relOk?' · риск '+fp(R)+', цель '+rr.toFixed(2)+' R':'');
  const btns=[['Отмена',()=>{CH.drag=null;dirty()}]];
  if(key==='entry'){const dl=price-CH.entry;if(relOk)btns.push(['Только вход',()=>act('ord_edit',{price}),'grn']);btns.push(['Вход + стоп и цель',()=>act('ord_edit',{price,stop:CH.stop+dl,tp:CH.tp+dl}),'grn'])}
  else btns.push(['Подтвердить',()=>act('ord_edit',key==='stop'?{stop:price}:{tp:price}),'grn']);
  sheet(nm+' '+CH.side.toUpperCase()+' '+usd(CH.sym).replace('USDT',''),det+(key==='entry'&&!relOk?' · стоп и цель не на своих сторонах от нового входа, нужно сдвинуть всё':''),btns)
}
function priceAtY(y){''', "function buildOrdCtl(pn){"),
 ("finish", "const d=CH&&CH.drag;if(!d)return;const price=d.price,key=d.key,cur=px(CH.sym),sd=CH.side==='long'?1:-1;",
  "const d=CH&&CH.drag;if(!d)return;if(CH.kind==='pend'){const pr0=d.price;if(pr0==null||!isFinite(pr0)){CH.drag=null;dirty();return}return ordConfirm(d.key,pr0)}const price=d.price,key=d.key,cur=px(CH.sym),sd=CH.side==='long'?1:-1;", "return ordConfirm(d.key,pr0)"),
 ("pdown", "if(P.size===1&&S.ctl&&CH.kind==='pos'&&!CH.gone&&q.x>CH.pw&&CH.labs)", "if(P.size===1&&S.ctl&&(CH.kind==='pos'||CH.kind==='pend')&&!CH.gone&&q.x>CH.pw&&CH.labs)", "(CH.kind==='pos'||CH.kind==='pend')&&!CH.gone"),
 ("dragtxt", "const tx=(CH.drag.key==='stop'?'стоп → ':'цель → ')+fp(pr);", "const tx=(CH.drag.key==='stop'?'стоп → ':CH.drag.key==='entry'?'вход → ':'цель → ')+fp(pr);", "CH.drag.key==='entry'?'вход → '"),
 ("entrykey", "add(CH.entry,'#4c8dff',CH.closed||CH.pos?'вход':'вход (ордер)');", "add(CH.entry,'#4c8dff',CH.closed||CH.pos?'вход':'вход (ордер)',0,CH.kind==='pend'&&S.ctl&&CH.rule!=='tg_market'?'entry':undefined);", "CH.kind==='pend'&&S.ctl&&CH.rule!=='tg_market'?'entry'"),
 ("open_pend", "openChart({kind:'pend',sid:o.id,sym:o.sym,side:o.side,entry:o.price,stop:o.stop,tp:o.tp,line_px:o.line_px,ch:o.ch,oid:o.id})", "openChart({kind:'pend',sid:o.id,sym:o.sym,side:o.side,rule:o.rule,entry:o.price,stop:o.stop,tp:o.tp,line_px:o.line_px,ch:o.ch,oid:o.id})", "side:o.side,rule:o.rule,entry:o.price"),
 ("sync_pend", "if(o){Object.assign(CH,{entry:o.price,stop:o.stop,tp:o.tp,line_px:o.line_px,gone:0});", "if(o){Object.assign(CH,{entry:o.price,stop:o.stop,tp:o.tp,rule:o.rule,line_px:o.line_px,gone:0});", "tp:o.tp,rule:o.rule,line_px"),
],
}

def patch(path):
    base = os.path.basename(path)
    if base not in EDITS: print("SKIP", base); return 0
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in EDITS[base]:
        if marker in out: print("ALREADY", base, name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", base, name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0

if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
