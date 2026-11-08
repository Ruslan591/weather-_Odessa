# -*- coding: utf-8 -*-
"""tg_bot.py -- Telegram-бот счёта «Регрессия» (сервис tg-bot-regr). Окружение: /opt/tg-notify/venv (matplotlib), POS_DIR=/opt/trading-bot/positions_regr.

Только исходящие запросы к api.telegram.org (long polling), входящих портов нет. Принимает команды ТОЛЬКО от TG_USER_ID.
Связь с торговой логикой через файлы (см. tg_gate.py): читает tg_outbox.jsonl (события), пишет tg_inbox.jsonl (нажатия). В orders.json и tg_mode.json НЕ пишет.
Меню: /mode (сон / монитор / авто, для монитора таймер 1/2/4/8 ч или без), /status. Под предложением: «Поставить» / «Отклонить» (с причиной); под ордером в авто: «Отменить ордер»."""
import json, os, sys, time, threading, traceback
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_notify as T

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
ACCT = os.environ.get("TG_ACCT_NAME", "Регрессия")
OUTF = os.path.join(D, "tg_outbox.jsonl"); OUTOFF = os.path.join(D, "tg_out.off"); INF = os.path.join(D, "tg_inbox.jsonl")
WATCHF = os.path.join(D, "tg_watch.json"); MODEF = os.path.join(D, "tg_mode.json"); MSGF = os.path.join(D, "tg_msgs.json"); ORDF = os.path.join(D, "orders.json"); POSF = os.path.join(D, "positions.json")
ENV = T._env(); ADMIN = int(ENV["TG_USER_ID"]); CHAT = str(ENV["TG_CHAT_ID"])
MODE_RU = {"sleep": "😴 Сон", "monitor": "👁 Монитор", "auto": "🤖 Авто"}
REASONS = [("против импульса", "impulse"), ("пробой границы", "brk"), ("флет", "flat"), ("слабый объём", "vol"), ("уровень не тот", "level"), ("цена не дошла до уровня", "far"), ("поздно: точка пройдена", "passed"), ("не в ту сторону", "wrongdir"), ("другое (написать)", "other"), ("без причины", "none")]
REASON_RU = {c: t for t, c in REASONS}; REASON_RU.update({"late": "далеко/поздно (старый код)", "other": "другое"})
pending_text = {}   # oid ордера, по которому ждём текст причины («другое»)
lock = threading.Lock()


def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)


def api(method, **kw):
    return T._post(method, {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in kw.items()})


def hhmm(ms): return datetime.fromtimestamp(ms / 1000, T._tz()).strftime("%H:%M")


def jload(path, default):
    for _ in range(3):
        try: return json.load(open(path, encoding="utf-8"))
        except Exception: time.sleep(0.2)
    return default


def msgs_load(): return jload(MSGF, {})


def msgs_save(m):
    tmp = MSGF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MSGF)


def inbox(ev):
    ev = dict(ev); ev["ts"] = int(time.time() * 1000)
    with lock, open(INF, "a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_order(oid):
    for o in jload(ORDF, []):
        if o.get("id") == oid: return o
    return None


def mode_state(): return jload(MODEF, {"mode": "auto", "missed": 0, "max_missed": 3, "until": None})


def mode_text():
    m = mode_state(); s = "Режим счёта «%s»: %s" % (ACCT, MODE_RU.get(m["mode"], m["mode"]))
    if m["mode"] == "monitor":
        s += "\nПропущено подряд: %d из %d" % (m.get("missed", 0), m.get("max_missed", 3))
        if m.get("until"): s += "\nТаймер до %s" % hhmm(m["until"])
    s += {"sleep": "\nНовых ордеров нет, уведомлений о новых точках нет. Открытые позиции продолжает вести бот; неподтверждённые вами ордера отменены.",
          "monitor": "\nБот присылает момент, когда цена касается или пересекает линию канала. Вы решаете: «Отклонить» или «Следить», а при слежении после каждой свечи можно выставить ордер. Одновременно не больше трёх графиков в работе.",
          "auto": "\nБот ставит ордера сам и присылает график."}.get(m["mode"], "")
    return s


MENU = [[{"text": "😴 Сон", "callback_data": "m:sleep"}, {"text": "👁 Монитор", "callback_data": "m:monitor"}, {"text": "🤖 Авто", "callback_data": "m:auto"}], [{"text": "💼 Счёт и позиции", "callback_data": "st"}, {"text": "📋 Ордера", "callback_data": "ol"}]]
REFRESH = [[{"text": "🔄 Обновить", "callback_data": "st"}]]
ORD_RULE = {"tg_market": "по рынку", "tg_limit": "лимит у линии", "chan_top": "авто: от верхней границы", "chan_bottom": "авто: от нижней границы", "retest_up": "авто: ретест после пробоя вверх", "retest_down": "авто: ретест после пробоя вниз"}


def sg(x, nd=2, unit=""):
    return ("%+." + str(nd) + "f%s") % (x, unit)


def fetch_snapshot():
    import urllib.request
    return json.load(urllib.request.urlopen("http://127.0.0.1:%s/api/claude" % os.environ.get("ACCT_PORT", "18102"), timeout=40))


def order_buttons(oid):
    rec = msgs_load().get(str(oid), {})
    if rec.get("kind") == "proposal": return [[{"text": "✅ Поставить", "callback_data": "a:%d" % oid}, {"text": "❌ Отклонить", "callback_data": "r:%d" % oid}]]
    return [[{"text": "❌ Отменить ордер", "callback_data": "r:%d" % oid}]]


def watch_get(wid):
    for x in (jload(WATCHF, {}).get("items") or []):
        if x.get("id") == wid: return x
    return None


def watch_buttons(wid, kind):
    if kind == "alert": return [[{"text": "👁 Следить", "callback_data": "wa:%d" % wid}, {"text": "❌ Отклонить", "callback_data": "wr:%d" % wid}]]
    return [[{"text": "▶️ Продолжать следить", "callback_data": "wc:%d" % wid}, {"text": "⏹ Перестать следить", "callback_data": "ws:%d" % wid}], [{"text": "📌 Выставить ордер", "callback_data": "wp:%d" % wid}]]


def send_watch(wid, kind):
    w = watch_get(wid)
    if not w: return
    key = "w%d" % wid; m = msgs_load(); old = m.get(key)
    if old and kind == "update":     # у предыдущего графика этой пары снимаем кнопки
        try: api("editMessageReplyMarkup", chat_id=CHAT, message_id=old["mid"], reply_markup={"inline_keyboard": []})
        except Exception as e: log("strip old buttons: %s" % e)
    kl = jload("/tmp/klcache/%s_5m_1000.json" % w["sym"], [])
    cap = T.caption_watch(w, kind); btn = watch_buttons(wid, kind)
    try: r = T.send_photo(T.render_watch(w, kl), cap, btn); photo = True
    except Exception as e:
        log("render watch fail %s: %s" % (wid, e)); r = T.send_text(cap, btn); photo = False
    m = msgs_load(); m[key] = {"mid": r["result"]["message_id"], "cap": cap, "kind": kind, "photo": photo}; msgs_save(m)


def edit_watch(wid, status, buttons=None):
    m = msgs_load(); rec = m.get("w%d" % wid)
    if not rec: api("sendMessage", chat_id=CHAT, text="Слежение %d: %s" % (wid, status)); return
    cap = rec["cap"] + "\n\n" + status; kb = {"inline_keyboard": buttons or []}
    try:
        if rec.get("photo"): api("editMessageCaption", chat_id=CHAT, message_id=rec["mid"], caption=cap, reply_markup=kb)
        else: api("editMessageText", chat_id=CHAT, message_id=rec["mid"], text=cap, reply_markup=kb)
    except Exception as e: log("edit watch fail %s: %s" % (wid, e))


def target_options(w, entry):
    """Цели по каналу на следующую свечу с оценкой прибыли и R:R (те же формулы, что при постановке в chan_orders)."""
    L = w.get("last") or {}
    if L.get("Rn") is None: return []
    a = float(L["atr"]); s = -1 if w["side"] == "short" else 1; R, S = float(L["Rn"]), float(L["Sn"]); H = R - S; line = R if s < 0 else S; px = float(L["c"])
    price = line if (entry == "limit" and ((s < 0 and px < line) or (s > 0 and px > line))) else px
    risk = max(1.2 * a, 0.005 * price); out = []
    for code, label, f in (("opp", "противоположная линия", None), ("mid", "середина канала", 0.5), ("q1", "1/4 канала", 0.25), ("q3", "3/4 канала", 0.75)):
        tp = ((S + 0.1 * a) if s < 0 else (R - 0.1 * a)) if f is None else ((R - f * H) if s < 0 else (S + f * H))
        gain = (tp - price) * s
        if gain < max(0.0015 * price, 0.5 * a): out.append(("%s · уже пройдена/слишком близко" % label, "x")); continue
        out.append(("%s · +%.2f%% · R:R %.1f" % (label, gain / price * 100, gain / risk), code))
    return out


def send_order(o, kind):
    kl = jload("/tmp/klcache/%s_5m_1000.json" % o["sym"], [])
    cap = T.caption_order(o, ACCT)
    if kind == "proposal":
        cap += "\n\n⏳ Нужно решение до %s (Киев). Без ответа ордер не ставится." % hhmm(o["ans_deadline"])
        btn = [[{"text": "✅ Поставить", "callback_data": "a:%d" % o["id"]}, {"text": "❌ Отклонить", "callback_data": "r:%d" % o["id"]}]]
    elif o.get("src_watch"):
        cap += "\n\n✅ Ордер выставлен вами из слежения (вход %s)." % ("по рынку" if o.get("rule") == "tg_market" else "лимитом у линии")
        btn = [[{"text": "❌ Отменить ордер", "callback_data": "r:%d" % o["id"]}]]
    else:
        cap += "\n\n🤖 Авто: ордер выставлен."
        btn = [[{"text": "❌ Отменить ордер", "callback_data": "r:%d" % o["id"]}]]
    try:
        r = T.send_photo(T.render_order(o, kl), cap, btn); photo = True
    except Exception as e:
        log("render fail %s: %s" % (o["id"], e)); r = T.send_text(cap, btn); photo = False
    m = msgs_load(); m[str(o["id"])] = {"mid": r["result"]["message_id"], "cap": cap, "kind": kind, "photo": photo}; msgs_save(m)


def edit_order(oid, status, buttons=None):
    m = msgs_load(); rec = m.get(str(oid))
    if not rec: api("sendMessage", chat_id=CHAT, text="Ордер %s: %s" % (oid, status)); return
    cap = rec["cap"] + "\n\n" + status; rec["cap_now"] = cap; msgs_save(m)
    kb = {"inline_keyboard": buttons or []}
    try:
        if rec.get("photo"): api("editMessageCaption", chat_id=CHAT, message_id=rec["mid"], caption=cap, reply_markup=kb)
        else: api("editMessageText", chat_id=CHAT, message_id=rec["mid"], text=cap, reply_markup=kb)
    except Exception as e: log("edit fail %s: %s" % (oid, e))


def handle_event(ev):
    t = ev.get("type"); oid = ev.get("id")
    if t in ("proposal", "placed"):
        o = load_order(oid)
        if o: send_order(o, t)
    elif t == "approved":
        if ev.get("ok"): edit_order(oid, "✅ Принято: ордер поставлен (с %s)" % hhmm(ev["placed_t"]))
        else: edit_order(oid, "⚠️ " + ev.get("why", "не удалось"))
    elif t == "rejected":
        if ev.get("ok"): edit_order(oid, "❌ Отклонено (%s)" % REASON_RU.get(ev.get("code"), ev.get("code")))
        else: edit_order(oid, "⚠️ " + ev.get("why", "не удалось"))
    elif t == "missed":
        m = mode_state(); edit_order(oid, "⏱ Пропущено (нет ответа). Подряд: %d из %d" % (ev.get("n", 0), m.get("max_missed", 3)))
    elif t == "stale": edit_order(oid, "↻ Устарело: %s" % ev.get("why", ""))
    elif t == "alert": send_watch(ev["wid"], "alert")
    elif t == "watch_update": send_watch(ev["wid"], "update")
    elif t == "watch_ack":
        wid = ev.get("wid")
        if not ev.get("ok"): api("sendMessage", chat_id=CHAT, text="⚠️ Слежение %s: %s" % (wid, ev.get("why", "не получилось")))
        elif ev.get("what") == "follow": edit_watch(wid, "👁 Слежу. Следующий график пришлю после закрытия свечи.")
        elif ev.get("what") == "continue": edit_watch(wid, "▶️ Продолжаю следить.")
    elif t == "watch_end":
        wid = ev.get("wid"); why = ev.get("why", "")
        if ev.get("code"): why += " (%s)" % REASON_RU.get(ev["code"], ev["code"])
        if ev.get("missed"): why += ". Пропущено подряд: %d из %d" % (ev["missed"], mode_state().get("max_missed", 3))
        edit_watch(wid, "⏹ " + why)
    elif t == "mode":
        txt = mode_text()
        if ev.get("mode") == "sleep": txt += "\nОтменено неподтверждённых ордеров: %d." % ev.get("cancelled", 0)
        api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": MENU})
    elif t == "sleep":
        why = {"missed": "пропущено подряд %s предложений" % ev.get("n"), "timer": "истёк таймер монитора"}.get(ev.get("why"), "")
        api("sendMessage", chat_id=CHAT, text="😴 Ухожу в сон: %s.\nОтменено неподтверждённых ордеров: %d. Открытые позиции продолжает вести бот (стоп, безубыток, трейлинг).\nВключить снова: /mode" % (why, ev.get("cancelled", 0)), reply_markup={"inline_keyboard": MENU})
    elif t == "filled":
        o = load_order(oid)
        if o: api("sendMessage", chat_id=CHAT, text="▶️ Позиция #%s открыта: %s %s по %s (%s, ордер #%s)." % (ev.get("pos"), o["sym"], o["side"].upper(), T.fmt_px(o.get("fill_px") or o["price"]), ORD_RULE.get(o.get("rule"), "лимит"), oid), reply_markup={"inline_keyboard": REFRESH + MENU[:1]})


def outbox_loop():
    while True:
        try:
            try: off = int(open(OUTOFF).read().strip() or 0)
            except Exception: off = 0
            try: size = os.path.getsize(OUTF)
            except OSError: size = 0
            if off > size: off = 0
            if size > off:
                with open(OUTF, "rb") as f: f.seek(off); data = f.read()
                cut = data.rfind(b"\n")
                if cut >= 0:
                    for ln in data[:cut + 1].split(b"\n"):
                        if not ln.strip(): continue
                        try: handle_event(json.loads(ln.decode("utf-8", "replace")))
                        except Exception: log("event error: " + traceback.format_exc()[-400:])
                    with open(OUTOFF, "w") as f: f.write(str(off + cut + 1))
        except Exception: log("outbox loop error: " + traceback.format_exc()[-400:])
        time.sleep(2)


def status_text():
    """Карточка счёта: режим, баланс бумажного счёта (pos.snapshot через acct-api), открытые позиции (пара, net%, pnl, БУ). Входы/стопы/цели без графика не показываем."""
    orders = jload(ORDF, []); pend = sum(1 for o in orders if o.get("status") == "pending"); prop = sum(1 for o in orders if o.get("status") == "proposed")
    out = [mode_text(), ""]
    ws = [x for x in (jload(WATCHF, {}).get("items") or []) if x.get("status") in ("alert", "watching")]
    if ws: out += ["Графиков в работе: %d из %d" % (len(ws), mode_state().get("max_watch", 3))] + ["· %s %s — %s" % (x["sym"], x["side"].upper(), "ждёт вашего решения" if x["status"] == "alert" else "слежу (%d св.)" % x.get("updates", 0)) for x in ws] + [""]
    try:
        sn = fetch_snapshot(); a = sn["account"]; opn = sn.get("open", [])
        tot = a["equity"] - a["start"]; totp = tot / a["start"] * 100
        out += ["💼 Счёт «%s» (бумажный: старт %.0f $, плечо %d×, ставка %.0f $)" % (ACCT, a["start"], a["lev"], a["stake"]),
                "%.2f $   %s $ (%s)" % (a["equity"], sg(tot), sg(totp, 2, "%")),
                "Баланс кошелька: %.2f $" % (a["start"] + a["realized"]), "Нереализованный PnL: %s $" % sg(a["unreal"]),
                "В марже: %.2f $" % a["open_margin"], "Доступно: %.2f $" % a["free"], "",
                "Ордеров ждут исполнения: %d · ждут вашего решения: %d" % (pend, prop), "Открытых позиций: %d" % len(opn)]
        for p in opn[:8]:
            be = "БУ: да" if p.get("armed") else "БУ: нет"
            part = " · часть закрыта" if p.get("rem", 1) < 0.999 else ""
            out.append("· %s %s · net %s · %s $ · %s%s" % (str(p["sym"]).replace("USDT", ""), p["side"].upper(), sg(p["unreal_pct"], 2, "%"), sg(p["unreal_usd"]), be, part))
    except Exception as e:
        log("snapshot fail: %s" % e); out += ["Ордеров ждут исполнения: %d · ждут вашего решения: %d" % (pend, prop), "⚠️ Баланс и позиции сейчас получить не удалось."]
    return "\n".join(out)


def last_px(sym):
    kl = jload("/tmp/klcache/%s_5m_1000.json" % sym, [])
    try: return float(kl[-1][4])
    except Exception: return None


def orders_list():
    """Выставленные ордера (pending), которые ещё не исполнились: текст и кнопка отмены на каждый."""
    pend = [o for o in jload(ORDF, []) if o.get("status") == "pending"]
    if not pend: return "📋 Выставленных ордеров нет.", [[{"text": "🔄 Обновить", "callback_data": "ol"}]]
    now = int(time.time() * 1000); lines = ["📋 Выставленные ордера (%d). Рыночные исполняются за секунды и сразу становятся позицией, лимитные ждут цену." % len(pend)]; kb = []
    for o in sorted(pend, key=lambda x: x["id"]):
        px = last_px(o["sym"]); dist = ""
        if px: dist = " · цена ~%s (%s)" % (T.fmt_px(px), sg((o["price"] - px) / px * 100, 2, "%"))
        left = max(0, int((o["expire_t"] - now) / 60000))
        lines.append("#%d %s %s · %s · вход %s · стоп %s · цель %s%s · истекает через %d мин" % (o["id"], o["sym"], o["side"].upper(), ORD_RULE.get(o.get("rule"), o.get("rule")), T.fmt_px(o["price"]), T.fmt_px(o["stop"]), T.fmt_px(o["tp"]), dist, left))
        kb.append([{"text": "❌ Отменить #%d %s %s" % (o["id"], o["sym"], o["side"].upper()), "callback_data": "oc:%d" % o["id"]}])
    kb.append([{"text": "🔄 Обновить", "callback_data": "ol"}])
    return "\n".join(lines), kb


def on_callback(cq):
    data = cq.get("data", ""); msg = cq.get("message") or {}; mid = msg.get("message_id"); cid = cq["id"]
    if cq["from"]["id"] != ADMIN: api("answerCallbackQuery", callback_query_id=cid, text="нет доступа"); return
    p = data.split(":")
    if p[0] == "m":
        if p[1] == "monitor":
            api("answerCallbackQuery", callback_query_id=cid)
            api("editMessageText", chat_id=CHAT, message_id=mid, text="Монитор: на какое время включить? Счётчик пропусков работает всегда.", reply_markup={"inline_keyboard": [[{"text": "1 ч", "callback_data": "mt:1"}, {"text": "2 ч", "callback_data": "mt:2"}, {"text": "4 ч", "callback_data": "mt:4"}, {"text": "8 ч", "callback_data": "mt:8"}], [{"text": "без таймера", "callback_data": "mt:0"}, {"text": "↩ назад", "callback_data": "mb"}]]})
        else:
            inbox({"type": "mode", "mode": p[1]}); api("answerCallbackQuery", callback_query_id=cid, text="Переключаю: %s" % MODE_RU[p[1]])
    elif p[0] == "mt":
        h = float(p[1]); inbox({"type": "mode", "mode": "monitor", "hours": h or None}); api("answerCallbackQuery", callback_query_id=cid, text="Монитор включается")
    elif p[0] == "st":
        api("answerCallbackQuery", callback_query_id=cid, text="Собираю данные…")
        try: api("editMessageText", chat_id=CHAT, message_id=mid, text=status_text(), reply_markup={"inline_keyboard": REFRESH + MENU[:1]})
        except Exception as e: log("status edit: %s" % e)
    elif p[0] == "ol":
        api("answerCallbackQuery", callback_query_id=cid); txt, kb = orders_list()
        try: api("editMessageText", chat_id=CHAT, message_id=mid, text=txt, reply_markup={"inline_keyboard": kb})
        except Exception as e: log("orders list edit: %s" % e)
    elif p[0] == "oc":
        oid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid); o = load_order(oid)
        if not o or o.get("status") != "pending": txt, kb = orders_list(); api("editMessageText", chat_id=CHAT, message_id=mid, text="Ордер #%d уже не активен.\n\n%s" % (oid, txt), reply_markup={"inline_keyboard": kb}); return
        rows = [[{"text": REASONS[i][0], "callback_data": "oq:%d:%s" % (oid, REASONS[i][1])}, {"text": REASONS[i + 1][0], "callback_data": "oq:%d:%s" % (oid, REASONS[i + 1][1])}] for i in range(0, len(REASONS), 2)]
        rows.append([{"text": "↩ назад к списку", "callback_data": "ol"}])
        api("editMessageText", chat_id=CHAT, message_id=mid, text="Отменить ордер #%d %s %s. Причина отмены:" % (oid, o["sym"], o["side"].upper()), reply_markup={"inline_keyboard": rows})
    elif p[0] == "oq":
        oid = int(p[1]); code = p[2]
        if code == "other":
            pending_text.clear(); pending_text["oid"] = oid; api("answerCallbackQuery", callback_query_id=cid)
            api("sendMessage", chat_id=CHAT, text="✍️ Причина отмены ордера %d: напишите одним сообщением (или /cancel, чтобы вернуться)." % oid, reply_markup={"force_reply": True, "input_field_placeholder": "причина"})
        else:
            pending_text.clear(); inbox({"type": "reject", "id": oid, "code": code}); api("answerCallbackQuery", callback_query_id=cid, text="Отменяю: %s" % REASON_RU.get(code, code))
            api("editMessageText", chat_id=CHAT, message_id=mid, text="⏳ Отменяю ордер #%d (%s)… Через несколько секунд нажмите «Обновить»." % (oid, REASON_RU.get(code, code)), reply_markup={"inline_keyboard": [[{"text": "🔄 Обновить список", "callback_data": "ol"}]]})
    elif p[0] == "wa":
        wid = int(p[1]); inbox({"type": "w_follow", "wid": wid}); api("answerCallbackQuery", callback_query_id=cid, text="Слежу"); edit_watch(wid, "⏳ Принято…")
    elif p[0] == "wc":
        wid = int(p[1]); inbox({"type": "w_continue", "wid": wid}); api("answerCallbackQuery", callback_query_id=cid, text="Продолжаю"); edit_watch(wid, "⏳ Принято…")
    elif p[0] == "ws":
        wid = int(p[1]); inbox({"type": "w_stop", "wid": wid}); api("answerCallbackQuery", callback_query_id=cid, text="Перестаю следить"); edit_watch(wid, "⏳ Останавливаю…")
    elif p[0] == "wr":
        wid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid)
        rows = [[{"text": REASONS[i][0], "callback_data": "wrr:%d:%s" % (wid, REASONS[i][1])}, {"text": REASONS[i + 1][0], "callback_data": "wrr:%d:%s" % (wid, REASONS[i + 1][1])}] for i in range(0, len(REASONS), 2)]
        rows.append([{"text": "↩ назад", "callback_data": "wrr:%d:back" % wid}]); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": rows})
    elif p[0] == "wrr":
        wid = int(p[1]); code = p[2]; w = watch_get(wid); kind = (msgs_load().get("w%d" % wid) or {}).get("kind", "alert")
        if code == "back":
            pending_text.clear(); api("answerCallbackQuery", callback_query_id=cid); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": watch_buttons(wid, kind)})
        elif code == "other":
            pending_text.clear(); pending_text["wid"] = wid; api("answerCallbackQuery", callback_query_id=cid)
            api("sendMessage", chat_id=CHAT, text="✍️ Причина по слежению %d: напишите одним сообщением (или /cancel, чтобы вернуться к кнопкам)." % wid, reply_markup={"force_reply": True, "input_field_placeholder": "причина"})
        else:
            pending_text.clear(); inbox({"type": "w_reject", "wid": wid, "code": code}); api("answerCallbackQuery", callback_query_id=cid, text="Записал: %s" % REASON_RU.get(code, code)); edit_watch(wid, "⏳ Отклоняю (%s)…" % REASON_RU.get(code, code))
    elif p[0] == "wp":
        wid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid)
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": [[{"text": "📈 По рынку", "callback_data": "wpe:%d:market" % wid}, {"text": "📌 Лимит у линии", "callback_data": "wpe:%d:limit" % wid}], [{"text": "↩ назад", "callback_data": "wpb:%d" % wid}]]})
    elif p[0] == "wpb":
        wid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": watch_buttons(wid, "update")})
    elif p[0] == "wpe":
        wid = int(p[1]); entry = p[2]; w = watch_get(wid); api("answerCallbackQuery", callback_query_id=cid)
        opts = target_options(w, entry) if w else []
        rows = [[{"text": lab, "callback_data": "wpt:%d:%s:%s" % (wid, entry, code)}] for lab, code in opts if code != "x"] + [[{"text": lab, "callback_data": "wpe:%d:%s" % (wid, entry)}] for lab, code in opts if code == "x"]
        rows.append([{"text": "↩ назад", "callback_data": "wp:%d" % wid}]); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": rows})
    elif p[0] == "wpt":
        wid = int(p[1]); entry = p[2]; tgt = p[3]; inbox({"type": "w_place", "wid": wid, "entry": entry, "target": tgt}); api("answerCallbackQuery", callback_query_id=cid, text="Ставлю ордер…"); edit_watch(wid, "⏳ Ставлю ордер (%s, цель: %s)…" % ("по рынку" if entry == "market" else "лимит у линии", tgt))
    elif p[0] == "mb":
        api("answerCallbackQuery", callback_query_id=cid); api("editMessageText", chat_id=CHAT, message_id=mid, text=mode_text(), reply_markup={"inline_keyboard": MENU})
    elif p[0] == "a":
        inbox({"type": "approve", "id": int(p[1])}); api("answerCallbackQuery", callback_query_id=cid, text="Принято, применяю…"); edit_order(int(p[1]), "⏳ Принято, применяю…")
    elif p[0] == "r":
        oid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid)
        rows = [[{"text": REASONS[i][0], "callback_data": "rr:%d:%s" % (oid, REASONS[i][1])}, {"text": REASONS[i + 1][0], "callback_data": "rr:%d:%s" % (oid, REASONS[i + 1][1])}] for i in range(0, len(REASONS), 2)]
        rows.append([{"text": "↩ назад", "callback_data": "rr:%d:back" % oid}])
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": rows})
    elif p[0] == "rr":
        oid = int(p[1]); code = p[2]
        if code == "back":
            pending_text.clear(); api("answerCallbackQuery", callback_query_id=cid); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": order_buttons(oid)})
        elif code == "other":
            pending_text["oid"] = oid; api("answerCallbackQuery", callback_query_id=cid)
            api("sendMessage", chat_id=CHAT, text="✍️ Причина по ордеру %d: напишите одним сообщением (или /cancel, чтобы вернуться к кнопкам)." % oid, reply_markup={"force_reply": True, "input_field_placeholder": "причина"})
        else:
            pending_text.clear(); inbox({"type": "reject", "id": oid, "code": code}); api("answerCallbackQuery", callback_query_id=cid, text="Записал: %s" % REASON_RU.get(code, code)); edit_order(oid, "⏳ Отклоняю (%s)…" % REASON_RU.get(code, code))


def on_message(m):
    if m["from"]["id"] != ADMIN: log("ignored message from other user"); return
    raw = (m.get("text") or "").strip(); t = raw.lower()
    if pending_text.get("wid") and raw and not t.startswith("/"):
        wid = pending_text.pop("wid"); inbox({"type": "w_reject", "wid": wid, "code": "other", "text": raw[:300]})
        api("sendMessage", chat_id=CHAT, text="Записал причину: «%s». Отклоняю." % raw[:120]); edit_watch(wid, "⏳ Отклоняю (другое: %s)…" % raw[:80]); return
    if t.startswith("/cancel") and pending_text.get("wid"):
        wid = pending_text.pop("wid"); api("sendMessage", chat_id=CHAT, text="Хорошо, слежение %d по-прежнему ждёт решения." % wid)
        try: api("editMessageReplyMarkup", chat_id=CHAT, message_id=msgs_load()["w%d" % wid]["mid"], reply_markup={"inline_keyboard": watch_buttons(wid, (msgs_load().get("w%d" % wid) or {}).get("kind", "alert"))})
        except Exception as e: log("restore watch buttons: %s" % e)
        return
    if pending_text.get("oid") and raw and not t.startswith("/"):
        oid = pending_text.pop("oid"); inbox({"type": "reject", "id": oid, "code": "other", "text": raw[:300]})
        api("sendMessage", chat_id=CHAT, text="Записал причину: «%s». Отклоняю ордер %d." % (raw[:120], oid)); edit_order(oid, "⏳ Отклоняю (другое: %s)…" % raw[:80]); return
    if t.startswith("/cancel") and pending_text.get("oid"):
        oid = pending_text.pop("oid"); api("sendMessage", chat_id=CHAT, text="Хорошо, ордер %d по-прежнему ждёт решения." % oid)
        try: api("editMessageReplyMarkup", chat_id=CHAT, message_id=msgs_load()[str(oid)]["mid"], reply_markup={"inline_keyboard": order_buttons(oid)})
        except Exception as e: log("restore buttons: %s" % e)
        return
    if t.startswith(("/start", "/mode", "/menu")): api("sendMessage", chat_id=CHAT, text=mode_text(), reply_markup={"inline_keyboard": MENU})
    elif t.startswith(("/orders", "/ordera")): txt, kb = orders_list(); api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": kb})
    elif t.startswith(("/status", "/balance")): api("sendMessage", chat_id=CHAT, text=status_text(), reply_markup={"inline_keyboard": REFRESH})
    else: api("sendMessage", chat_id=CHAT, text="Команды: /mode (режим), /status (состояние), /orders (ордера и отмена).")


def main():
    log("tg_bot start, POS_DIR=%s" % D)
    try: api("setMyCommands", commands=[{"command": "mode", "description": "Режим: сон / монитор / авто"}, {"command": "status", "description": "Счёт, баланс, позиции"}, {"command": "orders", "description": "Выставленные ордера и отмена"}])
    except Exception as e: log("setMyCommands fail: %s" % e)
    threading.Thread(target=outbox_loop, daemon=True).start()
    offset = None
    while True:
        try:
            kw = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if offset is not None: kw["offset"] = offset
            for u in api("getUpdates", **kw).get("result", []):
                offset = u["update_id"] + 1
                try:
                    if "callback_query" in u: on_callback(u["callback_query"])
                    elif "message" in u: on_message(u["message"])
                except Exception: log("update error: " + traceback.format_exc()[-500:])
        except Exception as e:
            log("poll error: %s" % e); time.sleep(5)


if __name__ == "__main__":
    main()
