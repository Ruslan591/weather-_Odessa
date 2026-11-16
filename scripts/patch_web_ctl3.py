# -*- coding: utf-8 -*-
"""Страница онлайн, версия 7 (поверх patch_web_ctl2.py): галочка «Следить» нажимается только квадратом; на графике слежения кнопки постановки ордера (Отбой/Пробой -> вход -> цель);
сообщения о включении/снятии галочки в Telegram отключены; живая проверка входа по рынку смотрит свечу 1m САМОЙ ПАРЫ, а не BTC (tg_live1m.json {"source": "btc"} вернёт старое);
шкала открытой позиции зелёная, когда стоп уже в зоне безубытка. Использование: python3 patch_web_ctl3.py FILE [FILE...]. Печатает APPLIED / ALREADY / ANCHOR_FAIL. Деплой: scripts/deploy_web_ctl3.sh. docs/topics/live_web.md"""
import os, re, sys

TG_GATE_INBOX = r'''def inbox_any(ev):
    """Событие пользователя в очередь tg_gate (как нажатие кнопки в Telegram) из другого процесса, например со страницы онлайн через acct-api."""
    ev = dict(ev); ev.setdefault("ts", int(time.time() * 1000))
    with open(INF, "a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")


'''

CO_PAIR = r'''def _pair_live_candle(sym):
    """Текущая (ещё не закрытая) свеча 1m самой пары (SYMUSDT): (open, last) или None при ошибке."""
    import urllib.request
    u = "https://data-api.binance.vision/api/v3/klines?symbol=%sUSDT&interval=1m&limit=1" % sym
    for _ in range(2):
        try:
            k = json.load(urllib.request.urlopen(u, timeout=5))[-1]
            return float(k[1]), float(k[4])
        except Exception: time.sleep(0.3)
    return None


'''

CO_WORDER = r'''WP_ENTRY = ("market", "limit", "stop")
WP_TGT = {"b": ("opp", "mid", "q1", "q3"), "k": ("h05", "h1", "h15")}


def manual_watch_order(o):
    """Постановка ордера из слежения со страницы онлайн: то же, что кнопки Telegram (сценарий -> вход -> цель). Кладёт событие w_place в очередь tg_gate; ордер, проверки и сообщения делает ближайший цикл (как для кнопки в Telegram)."""
    try: wid = int(o.get("id"))
    except Exception: return {"error": "не указано слежение"}
    st = "k" if o.get("setup") == "k" else "b"; entry = o.get("entry"); tgt = o.get("target")
    if entry not in WP_ENTRY: return {"error": "неизвестный тип входа"}
    if tgt not in WP_TGT[st]: return {"error": "неизвестная цель"}
    W = tg_gate._wload(); x = next((i for i in W["items"] if i["id"] == wid), None)
    if not x or x["status"] not in ("alert", "watching"): return {"error": "слежение уже не актуально"}
    if tg_gate.load_mode()["mode"] != "monitor": return {"error": "ордер из слежения ставится только в режиме Монитор"}
    tg_gate.inbox_any({"type": "w_place", "wid": wid, "entry": entry, "target": tgt, "setup": "breakout" if st == "k" else "bounce", "via": "page"})
    log("WATCH %d %s: ордер со страницы поставлен в очередь (%s, %s, цель %s)" % (wid, x["sym"], "пробой" if st == "k" else "отбой", entry, tgt))
    return {"ok": True, "id": wid, "queued": True}


'''

TG_KEEP_NEW = '''    elif t == "watch_keep":     # галочка «Следить» на странице онлайн: сообщений о включении и снятии нет (тихо); у алерта убираем кнопки
        try:
            wid = ev.get("wid")
            if ev.get("on") and ev.get("was") == "alert": edit_watch(wid, "👁 Слежу (галочка на странице). Следующий график пришлю после закрытия свечи.", watch_buttons(wid, "update"))
        except Exception as e: log("watch_keep event: %s" % e)
'''

WATCH_CTL_JS = r'''/* ---- постановка ордера из слежения (как кнопки в Telegram: сценарий -> вход -> цель) ---- */
function buildWatchCtl(pn){
  const bs=CH.side.toUpperCase(),ks=CH.side==='short'?'LONG':'SHORT';
  for(const [l,s] of [['↩ Отбой '+bs,'b'],['💥 Пробой '+ks,'k']]){const b=h('button','cb',l);b.onclick=()=>wEntry(s);pn.append(b)}
}
function wEntry(s){
  const k=s==='k',way=k?(CH.side==='short'?'LONG':'SHORT'):CH.side.toUpperCase(),nm=usd(CH.sym).replace('USDT','');
  const E=k?[['Рынок','market'],['Стоп за линией','stop'],['Лимит на ретесте','limit']]:[['Рынок','market'],['Лимит у линии','limit'],['Стоп-ордер','stop']];
  sheet((k?'Пробой ':'Отбой ')+way+' '+nm,'Как входить:',E.map(([l,e])=>[l,()=>wTarget(s,e,l)]).concat([['Отмена']]))
}
function wTarget(s,e,el){
  const k=s==='k',way=k?(CH.side==='short'?'LONG':'SHORT'):CH.side.toUpperCase(),nm=usd(CH.sym).replace('USDT','');
  const T=k?[['0.5 канала','h05'],['1 канал','h1'],['1.5 канала','h15']]:[['Противоп. линия','opp'],['Середина','mid'],['1/4 канала','q1'],['3/4 канала','q3']];
  sheet((k?'Пробой ':'Отбой ')+way+' '+nm+' · '+el,'Цель: доля канала или высота канала за линией',T.map(([l,t])=>[l,()=>act('watch_order',{entry:e,setup:s,target:t}),'grn']).concat([['Отмена']]))
}
'''

KEEP_OLD = r'''function keepRow(w){const lb=document.createElement('label');lb.className='small';lb.style.cssText='display:flex;align-items:center;gap:8px;margin-top:8px;padding:6px 0;cursor:pointer';
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!w.keep;cb.disabled=!S.ctl;cb.style.cssText='width:20px;height:20px;flex:none';
  lb.onclick=e=>e.stopPropagation();
'''
KEEP_NEW = r'''function keepRow(w){const lb=document.createElement('div');lb.className='small';lb.style.cssText='display:flex;align-items:center;gap:12px;margin-top:8px;padding:4px 0';
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!w.keep;cb.disabled=!S.ctl;cb.style.cssText='width:30px;height:30px;flex:none;margin:0';
  cb.onclick=e=>e.stopPropagation();
'''

EDITS = {
"tg_gate.py": [
 ("inbox", 'def keep_active(W=None):', TG_GATE_INBOX + 'def keep_active(W=None):', "def inbox_any("),
 ("via", '"order_id": o["id"], "price": o["price"], "auto": auto}))', '"order_id": o["id"], "price": o["price"], "auto": auto, "via": e.get("via")}))', '"auto": auto, "via": e.get("via")}'),
],
"chan_orders.py": [
 ("pair_candle", 'def _l1m_emit(o, state, bo, bc, moved=None, mx=None):', CO_PAIR + 'def _l1m_emit(o, state, bo, bc, moved=None, mx=None):', "def _pair_live_candle("),
 ("emit", '"moved": moved, "mx": mx, "side": o["side"]})', '"moved": moved, "mx": mx, "side": o["side"], "sym": o["sym"], "src": (o.get("live1m") or {}).get("src")})', '"sym": o["sym"], "src": (o.get("live1m")'),
 ("cancel1", 'подтверждения BTC 1m не было"', 'подтверждения свечи 1m не было"', 'подтверждения свечи 1m не было"'),
 ("cand", '    cd = (candle_fn or _btc_live_candle)()\n    if not cd: log("live1m %s: нет свечи BTC 1m, вход без проверки" % o["sym"]); return "go", None',
  '    src = "btc" if str(cfg.get("source", "pair")) == "btc" else "pair"     # по умолчанию свеча 1m самой пары; {"source": "btc"} в tg_live1m.json возвращает проверку по BTC\n    cd = (candle_fn or ((lambda: _btc_live_candle()) if src == "btc" else (lambda: _pair_live_candle(o["sym"]))))()\n    nmc = "BTC" if (src == "btc" and not candle_fn) else o["sym"]\n    if not cd: log("live1m %s: нет свечи %s 1m, вход без проверки" % (o["sym"], nmc)); return "go", None', 'nmc = "BTC" if'),
 ("wait", '        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now}\n        log("live1m %s %s: свеча BTC 1m не по ходу (o %.2f c %.2f), ждём (попытка %d)" % (o["sym"], o["side"], bo, bc, o["live1m_tries"]))',
  '        o["live1m"] = {"ok": 0, "o": bo, "c": bc, "px": px, "t": now, "src": src}\n        log("live1m %s %s: свеча %s 1m не по ходу (o %.8g c %.8g), ждём (попытка %d)" % (o["sym"], o["side"], nmc, bo, bc, o["live1m_tries"]))', '"t": now, "src": src}\n        log('),
 ("tpclose", 'return "cancel", "BTC 1m подтвердил, но цель уже слишком близко к цене входа"', 'return "cancel", "свеча 1m подтвердила, но цель уже слишком близко к цене входа"', '"свеча 1m подтвердила'),
 ("go", '    o["live1m"] = {"ok": 1, "o": bo, "c": bc, "px": px, "t": now, "tries": o["live1m_tries"]}\n    log("live1m %s %s: свеча BTC 1m по ходу (o %.2f c %.2f), вход по %.6g (попытка %d)" % (o["sym"], o["side"], bo, bc, newp, o["live1m_tries"]))',
  '    o["live1m"] = {"ok": 1, "o": bo, "c": bc, "px": px, "t": now, "tries": o["live1m_tries"], "src": src}\n    log("live1m %s %s: свеча %s 1m по ходу (o %.8g c %.8g), вход по %.6g (попытка %d)" % (o["sym"], o["side"], nmc, bo, bc, newp, o["live1m_tries"]))', '"tries": o["live1m_tries"], "src": src}'),
 ("worder", 'def pair_view(sym):', CO_WORDER + 'def pair_view(sym):', "def manual_watch_order("),
],
"pos.py": [
 ("route", '"ord_edit", "watch_keep"):', '"ord_edit", "watch_keep", "watch_order"):', '"watch_keep", "watch_order"):'),
 ("route2", 'return chan_orders.manual_watch(o) if o.get("action") == "watch_keep" else chan_orders.manual_order_j(o)',
  'return {"watch_keep": chan_orders.manual_watch, "watch_order": chan_orders.manual_watch_order}.get(o.get("action"), chan_orders.manual_order_j)(o)', 'chan_orders.manual_watch_order}.get('),
],
"live_web.py": [
 ("acts", '"ord_edit", "watch_keep"}', '"ord_edit", "watch_keep", "watch_order"}', '"watch_keep", "watch_order"}'),
 ("body", '        if a == "watch_keep": body["on"] = bool(q.get("on"))', '        if a == "watch_keep": body["on"] = bool(q.get("on"))\n        if a == "watch_order": body.update(entry=str(q.get("entry")), setup=str(q.get("setup")), target=str(q.get("target")))', 'if a == "watch_order": body.update('),
 ("l1m_w", '"⏳ %s: свеча BTC 1m не по ходу (%+.3f%%), попытка %s" % (nm, (bc / bo - 1) * 100 if bo else 0, o.get("live1m_tries"))',
  '"⏳ %s: свеча %s 1m не по ходу (%+.3f%%), попытка %s" % (nm, "BTC" if l1.get("src", "btc") == "btc" else o.get("sym"), (bc / bo - 1) * 100 if bo else 0, o.get("live1m_tries"))', 'свеча %s 1m не по ходу'),
 ("l1m_g", '"✅ %s: свеча BTC 1m по ходу, вход открыт (попытка %s)" % (nm, o.get("live1m_tries"))', '"✅ %s: свеча %s 1m по ходу, вход открыт (попытка %s)" % (nm, "BTC" if l1.get("src", "btc") == "btc" else o.get("sym"), o.get("live1m_tries"))', 'свеча %s 1m по ходу, вход открыт'),
],
"tg_bot.py": [
 ("keep", None, None, "сообщений о включении и снятии нет (тихо)"),   # заменяется целым блоком ниже
 ("cn", '            bo, bc = float(ev["o"]), float(ev["c"]); pc = (bc / bo - 1) * 100 if bo else 0.0\n', '            bo, bc = float(ev["o"]), float(ev["c"]); pc = (bc / bo - 1) * 100 if bo else 0.0\n            cn = "BTC" if (ev.get("src") == "btc" or not ev.get("sym")) else ev["sym"]     # свеча какой пары проверялась\n', 'cn = "BTC" if (ev.get("src")'),
 ("txt_w", '"⏳ Вход не открыт: свеча BTC 1m не по ходу %s (%+.3f%%)%s. Повторю проверку, попытка %s, %s" % (way.upper(), pc,', '"⏳ Вход не открыт: свеча %s 1m не по ходу %s (%+.3f%%)%s. Повторю проверку, попытка %s, %s" % (cn, way.upper(), pc,', '"⏳ Вход не открыт: свеча %s 1m'),
 ("txt_g", '"✅ Свеча BTC 1m по ходу %s (%+.3f%%): вход открыт, попыток %s%s" % (way.upper(), pc,', '"✅ Свеча %s 1m по ходу %s (%+.3f%%): вход открыт, попыток %s%s" % (cn, way.upper(), pc,', '"✅ Свеча %s 1m'),
],
"index.html": [
 ("keeprow", KEEP_OLD, KEEP_NEW, "cb.style.cssText='width:30px;height:30px"),
 ("lasta", "let pendAct=null;", "let pendAct=null,lastA=null;", "lastA=null;"),
 ("act", "function act(a,extra){const r=Math.random().toString(36).slice(2,8);pendAct=r;", "function act(a,extra){const r=Math.random().toString(36).slice(2,8);pendAct=r;lastA=a;", "pendAct=r;lastA=a;"),
 ("ack", "if(m.ok)toast('Выполнено. Бот подтвердил.',true);", "if(m.ok)toast(lastA==='watch_order'?'Запрос принят: ордер поставит бот в ближайшем цикле, итог придёт в Telegram':'Выполнено. Бот подтвердил.',true);", "lastA==='watch_order'"),
 ("ctlrow", "const on=S.ctl&&CH&&(CH.kind==='pos'||CH.kind==='pend');pn.hidden=!on;if(!on)return;if(CH.kind==='pend')return buildOrdCtl(pn);",
  "const on=S.ctl&&CH&&(CH.kind==='pos'||CH.kind==='pend'||(CH.kind==='watch'&&!CH.gone));pn.hidden=!on;if(!on)return;if(CH.kind==='pend')return buildOrdCtl(pn);if(CH.kind==='watch')return buildWatchCtl(pn);", "return buildWatchCtl(pn);"),
 ("watchctl", "/* ---- управление ждущим ордером ---- */", WATCH_CTL_JS + "/* ---- управление ждущим ордером ---- */", "function buildWatchCtl("),
 ("scale", "uu.style.left=f(p.entry)+'%';br.append(uu,i);c.append(br);", "uu.style.left=f(p.entry)+'%';if((p.side==='long'?1:-1)*(p.stop-p.entry)>=-p.entry*0.0002)br.style.background='linear-gradient(90deg,#1d6b4d,var(--g))';br.append(uu,i);c.append(br);", "linear-gradient(90deg,#1d6b4d"),
],
}


def patch(path):
    base = os.path.basename(path)
    if base not in EDITS: print("SKIP", base); return 0
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in EDITS[base]:
        if marker in out: print("ALREADY", base, name); continue
        if base == "tg_bot.py" and name == "keep":
            m = re.search(r'    elif t == "watch_keep":.*?(?=    elif t == "max_watch":)', out, re.S)
            if not m: print("ANCHOR_FAIL", base, name, 0); bad += 1; continue
            out = out[:m.start()] + TG_KEEP_NEW + out[m.end():]; print("APPLIED", base, name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", base, name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
