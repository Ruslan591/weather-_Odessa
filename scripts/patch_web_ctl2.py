# -*- coding: utf-8 -*-
"""Страница онлайн (порт 18111), версия 6: таймфреймы H4 и D1 на графике; галочка «Следить» в блоке «Слежения у линий»
(слежение без вопросов о продолжении, в сон не уходит); действия со страницы по ордерам, позициям и слежению сообщаются в Telegram
и пишутся в журнал решений (kind=ord_manual для ордеров, w_keep / w_keep_off для слежений; по позициям журнал decisions.manual уже был).
Накладывается на файлы по якорям, повторный запуск ничего не меняет. Использование: python3 patch_web_ctl2.py FILE [FILE...]
(имена: chan_orders.py, pos.py, tg_gate.py, decisions.py, tg_bot.py, live_web.py, index.html). Печатает APPLIED / ALREADY / ANCHOR_FAIL. Деплой: scripts/deploy_web_ctl2.sh. docs/topics/live_web.md"""
import os, sys

TG_GATE_FUNCS = r'''def emit_any(ev):
    """Событие в очередь tg_bot независимо от TG_GATE (нужно процессу acct-api, где шлюз выключен). Только если для счёта работает tg_bot (есть tg_msgs.json)."""
    try:
        if not os.path.exists(os.path.join(D, "tg_msgs.json")): return
        ev = dict(ev); ev.setdefault("ts", int(time.time() * 1000))
        with open(OUTF, "a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e: print("tg_gate emit_any err", e, flush=True)


def keep_active(W=None):
    """Есть ли слежения с галочкой «Следить» (они не дают боту уйти в сон)."""
    W = W or _wload()
    return any(x.get("keep") and x["status"] in ("alert", "watching") for x in W["items"])


def web_keep(wid, on, now=None):
    """Галочка «Следить» со страницы онлайн (вызывать под pos.lock()). on: слежение идёт без вопросов о продолжении и не заканчивается по таймеру, по «нет ответа» и «цена ушла»;
    бот с такими слежениями автоматически в сон не уходит. Алерт без ответа галочка превращает в слежение. Возвращает (копия слежения, ошибка)."""
    now = now or int(time.time() * 1000)
    W = _wload(); x = next((i for i in W["items"] if i["id"] == wid), None)
    if not x or x["status"] not in ("alert", "watching"): return None, "слежение уже не актуально (закончилось)"
    m = load_mode()
    if m["mode"] != "monitor": return None, "слежение работает только в режиме Монитор"
    was = x["status"]
    if on:
        if was == "alert": x.update(status="watching", t_follow=now)
        x.update(keep=True, keep_t=now, unanswered=0)
        if m.get("missed"): m["missed"] = 0; save_mode(m)
    else:
        x.update(keep=False, unanswered=0, t_follow=now)     # снятие галочки: чистый счёт, чтобы слежение не закрылось сразу
    _wsave(W, now)
    return dict(x, was=was), None


'''

DEC_FUNC = r'''def ord_manual(b, a, action, px=None, kl=None, o=None, **kw):
    """Ручное действие пользователя по ждущему ордеру со страницы онлайн (ord_cancel / ord_edit). b и a - ордер до и после правки (a = None при отмене). Источник для обучения: что и во что поправил, на каком расстоянии цены."""
    try:
        now = int(time.time() * 1000); o = o or {}
        f = lambda x: {k: _r(x.get(k) or 0, 8) for k in ("price", "stop", "tp")} if x else None
        cur = a or b; risk = lambda x: abs(x["price"] - x["stop"]) / x["price"] * 100 if x and x.get("price") else None
        rr = lambda x: round(abs(x["tp"] - x["price"]) / abs(x["price"] - x["stop"]), 2) if x and x.get("price") and x["price"] != x["stop"] else None
        p = dict(sym=b["sym"] + "USDT", side=b["side"], entry=b["price"], R=abs(b["price"] - b["stop"]), id=b["id"], t_in=b.get("placed_t", now), atr1h=None)
        ctx = _context(p, px or b["price"], kl, now); atr = b.get("atr") or 0
        rec = dict(t=now, kind="ord_manual", by="manual", action=action, order_id=b["id"], sym=b["sym"], side=b["side"], rule=b.get("rule"), setup=b.get("setup"), line=b.get("line"), counter=b.get("counter"),
                   ctype=b.get("ctype"), src_watch=b.get("src_watch"), auto=b.get("auto_express"), edits=len(b.get("edits") or []), age_min=round((now - (b.get("placed_t") or now)) / 60000, 1),
                   px_now=_r(px or 0, 8), atr=_r(atr, 6), dist_atr=round((px - b["price"]) / atr, 2) if px and atr else None, risk_pct_from=round(risk(b), 3) if risk(b) else None, risk_pct_to=round(risk(cur), 3) if risk(cur) else None,
                   rr_from=rr(b), rr_to=rr(cur), tag=str(o.get("tag") or "")[:60], note=str(o.get("note") or "")[:300], **{"from": f(b), "to": f(a)})
        rec.update(kw); rec.update(ctx); _write(rec)
    except Exception as e: print("decisions ord_manual err", e, flush=True)

'''

CO_FUNCS = r'''def manual_order_j(o):
    """manual_order со страницы онлайн + журнал обучения (decisions kind=ord_manual) + сообщение в Telegram (событие web_ord)."""
    act = o.get("action")
    try: oid = int(o.get("id"))
    except Exception: return manual_order(o)
    before = next((dict(v) for v in load_orders() if v["id"] == oid), None)
    res = manual_order(o)
    if before and isinstance(res, dict) and res.get("ok"):
        try:
            after = None if act == "ord_cancel" else next((dict(v) for v in load_orders() if v["id"] == oid), None)
            try: px = float(pos.price(before["sym"] + "USDT"))
            except Exception: px = None
            import decisions
            decisions.ord_manual(before, after, act, px, pos.kl, o)
            g = lambda x: {k: x.get(k) for k in ("price", "stop", "tp")} if x else None
            tg_gate.emit_any({"type": "web_ord", "id": oid, "act": act, "sym": before["sym"], "side": before["side"], "rule": before.get("rule"), "from": g(before), "to": g(after), "px": px})
        except Exception as e: log("web order journal/notify: %s" % e)
    return res


def manual_watch(o):
    """Галочка «Следить» у слежения (страница онлайн -> live_web -> acct-api -> pos.api_action). Под pos.lock(); журнал w_keep / w_keep_off; сообщение в Telegram (событие watch_keep)."""
    try: wid = int(o.get("id"))
    except Exception: return {"error": "не указано слежение"}
    on = bool(o.get("on"))
    with pos.lock():
        x, err = tg_gate.web_keep(wid, on)
    if err: return {"error": err}
    _tg_journal(dict(x, _w=1), "w_keep" if on else "w_keep_off", {"via": "page", "was": x.get("was")})
    tg_gate.emit_any({"type": "watch_keep", "wid": wid, "on": on, "sym": x["sym"], "side": x.get("side"), "line": x.get("line"), "was": x.get("was")})
    log("WATCH %d %s keep=%s (page)" % (wid, x["sym"], on))
    return {"ok": True, "id": wid, "keep": on}


'''

POS_NOTIFY = r'''def _web_pos_notify(act, p, px, o, now):
    """Действие со страницы онлайн по позиции -> сообщение в Telegram (событие web_pos). Журнал обучения пишет decisions.manual в самом действии."""
    try:
        import tg_gate
        try: tp = exit_cfg.levels(p)["tp"]
        except Exception: tp = None
        tg_gate.emit_any({"type": "web_pos", "act": act, "id": p["id"], "sym": p["sym"], "side": p["side"], "px": px, "entry": p.get("entry"), "stop": p.get("stop"), "tp": tp,
                          "price": o.get("price"), "pct": o.get("pct"), "net_pct": p.get("net_pct"), "r_mult": p.get("r_mult"), "pnl_usd": p.get("pnl_usd")})
    except Exception as e: print("web pos notify err", e, flush=True)


'''

TG_BOT_EVENTS = r'''    elif t == "web_pos":     # действие со страницы онлайн по позиции (порт 18111)
        try:
            fp_ = lambda v: ("%.8g" % float(v)) if v not in (None, "") else "—"
            a = ev.get("act"); nm = "#%s %s %s" % (ev.get("id"), str(ev.get("sym", "")).replace("USDT", ""), str(ev.get("side", "")).upper())
            what = {"close": "закрыта по рынку (~%s)" % fp_(ev.get("px")), "stop": "стоп → %s" % fp_(ev.get("price")), "tp": "цель → %s" % fp_(ev.get("price")), "tp_auto": "цель возвращена автоматике",
                    "auto": "стоп возвращён автоматике", "trail": "трейлинг %s%% от цены" % ev.get("pct")}.get(a, str(a))
            extra = ""
            if a == "close" and ev.get("net_pct") is not None: extra = "\nИтог: %+.2f%%%s%s" % (float(ev["net_pct"]), (", %+.2f R" % float(ev["r_mult"])) if ev.get("r_mult") is not None else "", (", %+.3f $" % float(ev["pnl_usd"])) if ev.get("pnl_usd") is not None else "")
            api("sendMessage", chat_id=CHAT, text="🖥 Со страницы: позиция %s: %s\nВход %s · стоп %s · цель %s · цена %s%s" % (nm, what, fp_(ev.get("entry")), fp_(ev.get("stop")), fp_(ev.get("tp")), fp_(ev.get("px")), extra))
        except Exception as e: log("web_pos event: %s" % e)
    elif t == "web_ord":     # действие со страницы онлайн по ждущему ордеру
        try:
            fp_ = lambda v: ("%.8g" % float(v)) if v not in (None, "") else "—"
            nm = "#%s %s %s" % (ev.get("id"), ev.get("sym"), str(ev.get("side", "")).upper()); b = ev.get("from") or {}; a = ev.get("to") or {}
            if ev.get("act") == "ord_cancel": txt = "🖥 Со страницы: ордер %s отменён\nВход %s · стоп %s · цель %s · цена %s" % (nm, fp_(b.get("price")), fp_(b.get("stop")), fp_(b.get("tp")), fp_(ev.get("px")))
            else:
                ch = [("вход", "price"), ("стоп", "stop"), ("цель", "tp")]; lines = ["%s: %s → %s" % (n_, fp_(b.get(k)), fp_(a.get(k))) for n_, k in ch if b.get(k) != a.get(k)]
                txt = "🖥 Со страницы: ордер %s изменён\n%s\nЦена сейчас %s. Автоматика этот ордер больше не пересчитывает." % (nm, "\n".join(lines) or "без изменений", fp_(ev.get("px")))
            api("sendMessage", chat_id=CHAT, text=txt)
        except Exception as e: log("web_ord event: %s" % e)
    elif t == "watch_keep":     # галочка «Следить» на странице онлайн
        try:
            wid = ev.get("wid"); on = bool(ev.get("on")); w = watch_get(wid) or {}
            nm = "%s %s (%s линия)" % (ev.get("sym"), str(ev.get("side", "")).upper(), "верхняя" if ev.get("line") == "upper" else "нижняя")
            if on:
                api("sendMessage", chat_id=CHAT, text="🔒 Со страницы: слежение %s включено галочкой «Следить». Бот ведёт его без вопросов о продолжении, график придёт после каждой свечи; пока оно идёт, в сон бот автоматически не уходит. Снять: галочка на странице или «⏹ Перестать следить»." % nm)
                if ev.get("was") == "alert": edit_watch(wid, "👁 Слежу (галочка на странице). Следующий график пришлю после закрытия свечи.", watch_buttons(wid, "update"))
            else:
                api("sendMessage", chat_id=CHAT, text="🔓 Со страницы: галочка «Следить» снята у слежения %s. Дальше обычные правила: вопрос о продолжении после каждой свечи, остановка без ответа." % nm)
        except Exception as e: log("watch_keep event: %s" % e)
'''

EDITS = {
"tg_gate.py": [
 ("funcs", 'def mode():\n    return load_mode()["mode"] if ENABLED else "auto"', TG_GATE_FUNCS + 'def mode():\n    return load_mode()["mode"] if ENABLED else "auto"', "def web_keep("),
 ("scan_keep", '            if not exp and x["unanswered"] > int(m.get("watch_unanswered", 3)):',
  '            if x.get("keep"): emit({"type": "watch_update", "wid": x["id"]})     # галочка «Следить»: без вопросов, без остановки по времени, «нет ответа» и «цена ушла»\n            elif not exp and x["unanswered"] > int(m.get("watch_unanswered", 3)):', 'if x.get("keep"): emit({"type": "watch_update"'),
 ("gone", 'gone = [y for y in active if y["status"] == "watching" and int(y.get("away_n") or 0) >= 2]', 'gone = [y for y in active if y["status"] == "watching" and not y.get("keep") and int(y.get("away_n") or 0) >= 2]', 'and not y.get("keep") and int'),
 ("sleep_guard", '    if m["mode"] == "monitor" and not m.get("express"):\n        why = ', '    if m["mode"] == "monitor" and not m.get("express") and not keep_active(W):     # слежение с галочкой «Следить» не даёт уйти в сон по пропускам и таймеру\n        why = ', 'and not keep_active(W)'),
],
"decisions.py": [
 ("func", 'def manual(p, px, kl, kind, old, new, o=None, **kw):', DEC_FUNC + 'def manual(p, px, kl, kind, old, new, o=None, **kw):', "def ord_manual("),
],
"chan_orders.py": [
 ("funcs", 'def pair_view(sym):', CO_FUNCS + 'def pair_view(sym):', "def manual_order_j("),
],
"pos.py": [
 ("route", 'in ("ord_cancel", "ord_edit"):   # ручное управление ждущим ордером (страница онлайн)', 'in ("ord_cancel", "ord_edit", "watch_keep"):   # ручное управление ждущим ордером и слежением (страница онлайн)', '"ord_edit", "watch_keep"):'),
 ("route2", 'return chan_orders.manual_order(o)', 'return chan_orders.manual_watch(o) if o.get("action") == "watch_keep" else chan_orders.manual_order_j(o)', 'chan_orders.manual_order_j(o)'),
 ("notify_def", 'def api_action(o):', POS_NOTIFY + 'def api_action(o):', "def _web_pos_notify("),
 ("notify_call", '        else: return {"error": "неизвестное действие"}\n        save(ps)\n    return snapshot()', '        else: return {"error": "неизвестное действие"}\n        save(ps)\n        _web_pos_notify(act, p, px, o, now)     # сообщение в Telegram о действии со страницы\n    return snapshot()', 'px, o, now)     # сообщение в Telegram'),
],
"tg_bot.py": [
 ("events", '    elif t == "max_watch":\n', TG_BOT_EVENTS + '    elif t == "max_watch":\n', 'elif t == "web_pos":'),
 ("buttons", '    if kind == "alert": return [[{"text": "👁 Следить", "callback_data": "wa:%d" % wid}',
  '    if kind != "alert" and (watch_get(wid) or {}).get("keep"):     # галочка «Следить» (страница): вопроса о продолжении нет\n        return [[{"text": "📌 Выставить ордер", "callback_data": "wp:%d" % wid}, {"text": "⏹ Перестать следить", "callback_data": "ws:%d" % wid}], off]\n    if kind == "alert": return [[{"text": "👁 Следить", "callback_data": "wa:%d" % wid}', '(watch_get(wid) or {}).get("keep")'),
 ("caption", '    cap = T.caption_watch(w, kind); V = None; Bk = None; auto = None\n', '    cap = T.caption_watch(w, kind); V = None; Bk = None; auto = None\n    if w.get("keep") and not express_on(): cap += "\\n🔒 Галочка «Следить»: без вопросов, без сна"\n', '🔒 Галочка «Следить»'),
],
"live_web.py": [
 ("ivs", 'IVS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}', 'IVS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}', '"4h": 14400000'),
 ("acts", 'ACTS = {"close", "stop", "tp", "tp_auto", "auto", "trail", "ord_cancel", "ord_edit"}', 'ACTS = {"close", "stop", "tp", "tp_auto", "auto", "trail", "ord_cancel", "ord_edit", "watch_keep"}', '"ord_edit", "watch_keep"}'),
 ("body", '        if a == "trail": body["pct"] = float(q.get("pct"))', '        if a == "trail": body["pct"] = float(q.get("pct"))\n        if a == "watch_keep": body["on"] = bool(q.get("on"))', 'if a == "watch_keep": body["on"]'),
 ("derive", '"tf": w.get("t_follow") or w.get("created"), "ch": w.get("chan")})', '"tf": w.get("t_follow") or w.get("created"), "ch": w.get("chan"), "keep": bool(w.get("keep"))})', '"keep": bool(w.get("keep"))'),
],
"index.html": [
 ("ivms", "const IVMS={'1m':60000,'5m':300000,'15m':900000,'1h':3600000};", "const IVMS={'1m':60000,'5m':300000,'15m':900000,'1h':3600000,'4h':14400000,'1d':86400000};", "'4h':14400000"),
 ("ivlabel", "h('button','cb'+(CH.iv===iv?' on':''),iv)", "h('button','cb'+(CH.iv===iv?' on':''),({'4h':'H4','1d':'D1'})[iv]||iv)", "({'4h':'H4','1d':'D1'})[iv]||iv"),
 ("xlabels", "c.fillText(new Date(Math.round(t/iv)*iv).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),",
  "c.fillText(xlab(Math.round(t/iv)*iv,iv),", "xlab(Math.round(t/iv)*iv,iv)"),
 ("keeprow", "function gotAck(m){if(m.rid!==pendAct)return;",
  r'''function xlab(t,iv){const d=new Date(t);if(iv>=864e5)return d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'});if(iv>=144e5)return d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})+' '+String(d.getHours()).padStart(2,'0');return d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}
let pendW=null;
function keepRow(w){const lb=document.createElement('label');lb.className='small';lb.style.cssText='display:flex;align-items:center;gap:8px;margin-top:8px;padding:6px 0;cursor:pointer';
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!w.keep;cb.disabled=!S.ctl;cb.style.cssText='width:20px;height:20px;flex:none';
  lb.onclick=e=>e.stopPropagation();
  cb.onchange=()=>{const r=Math.random().toString(36).slice(2,8);pendW=r;send({q:'act',a:'watch_keep',id:w.id,on:cb.checked,rid:r})};
  lb.append(cb,h('span',w.keep?'g':'mut',w.keep?'Следить: бот ведёт без вопросов и не уходит в сон':(S.ctl?'Следить':'Следить (управление только на порту 18111)')));return lb}
function gotAck(m){if(m.rid===pendW){pendW=null;if(!m.ok)alert('Отказ: '+(m.err||'ошибка'));return}if(m.rid!==pendAct)return;''', "function keepRow(w)"),
 ("watchcard", "(w.tf?' · слежу с '+tm(w.tf):'')));we.append(c)}", "(w.tf?' · слежу с '+tm(w.tf):'')));c.append(keepRow(w));we.append(c)}", "c.append(keepRow(w))"),
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
