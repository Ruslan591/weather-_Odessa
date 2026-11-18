# -*- coding: utf-8 -*-
"""Страница онлайн, версия 8 (поверх patch_web_ctl3.py): в карточке слежения галочка «Отменить».
Цепочка: страница -> WS act watch_cancel -> live_web.handle_act -> acct-api POST /api/claude -> pos.api_action -> chan_orders.manual_watch_cancel -> tg_gate.inbox_any(w_stop),
то есть то же, что кнопка «Перестать следить» в Telegram: слежение закрывается, пост в Telegram получает watch_end. Работает на порту 18111 (ctl), в любом режиме бота.
Использование: python3 patch_web_ctl4.py FILE [FILE...]. Печатает APPLIED / ALREADY / ANCHOR_FAIL. Деплой: scripts/deploy_web_ctl4.sh. docs/topics/live_web.md"""
import os, sys

CO_CANCEL = r'''def manual_watch_cancel(o):
    """Галочка «Отменить» у слежения (страница онлайн): то же, что «Перестать следить» в Telegram. Кладёт w_stop в очередь tg_gate; закрытие слежения и сообщение в Telegram (watch_end) делает ближайший цикл."""
    try: wid = int(o.get("id"))
    except Exception: return {"error": "не указано слежение"}
    W = tg_gate._wload(); x = next((i for i in W["items"] if i["id"] == wid), None)
    if not x or x["status"] not in ("alert", "watching"): return {"error": "слежение уже не актуально (закончилось)"}
    tg_gate.inbox_any({"type": "w_stop", "wid": wid, "via": "page"})
    log("WATCH %d %s: отмена со страницы поставлена в очередь" % (wid, x["sym"]))
    return {"ok": True, "id": wid, "queued": True}


'''

CANCEL_JS = r'''function cancelRow(w){const lb=document.createElement('div');lb.className='small';lb.style.cssText='display:flex;align-items:center;gap:12px;margin-top:2px;padding:4px 0';
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=false;cb.disabled=!S.ctl;cb.style.cssText='width:30px;height:30px;flex:none;margin:0';
  cb.onclick=e=>e.stopPropagation();
  cb.onchange=()=>{if(!cb.checked)return;if(!confirm('Отменить слежение '+usd(w.sym).replace('USDT','')+'? В Telegram оно тоже закончится.')){cb.checked=false;return}
    const r=Math.random().toString(36).slice(2,8);pendW=r;send({q:'act',a:'watch_cancel',id:w.id,rid:r});toast('Отмена принята: слежение закроется в ближайшем цикле бота',true)};
  lb.append(cb,h('span','r',S.ctl?'Отменить':'Отменить (управление только на порту 18111)'));return lb}
'''

EDITS = {
"chan_orders.py": [
 ("cancel", 'WP_ENTRY = ("market", "limit", "stop")', CO_CANCEL + 'WP_ENTRY = ("market", "limit", "stop")', "def manual_watch_cancel("),
],
"pos.py": [
 ("tuple", '("ord_cancel", "ord_edit", "watch_keep", "watch_order"):', '("ord_cancel", "ord_edit", "watch_keep", "watch_order", "watch_cancel"):', '"watch_order", "watch_cancel"):'),
 ("map", '"watch_order": chan_orders.manual_watch_order}', '"watch_order": chan_orders.manual_watch_order, "watch_cancel": chan_orders.manual_watch_cancel}', 'chan_orders.manual_watch_cancel'),
],
"live_web.py": [
 ("acts", '"watch_keep", "watch_order"}', '"watch_keep", "watch_order", "watch_cancel"}', '"watch_order", "watch_cancel"}'),
],
"index.html": [
 ("fn", 'function gotAck(m){', CANCEL_JS + 'function gotAck(m){', "function cancelRow("),
 ("use", 'c.append(keepRow(w));we.append(c)', 'c.append(keepRow(w));c.append(cancelRow(w));we.append(c)', 'c.append(cancelRow(w))'),
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
