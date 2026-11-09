# -*- coding: utf-8 -*-
"""tg_bot.py -- Telegram-бот счёта «Регрессия» (сервис tg-bot-regr). Окружение: /opt/tg-notify/venv (matplotlib), POS_DIR=/opt/trading-bot/positions_regr.

Только исходящие запросы к api.telegram.org (long polling), входящих портов нет. Принимает команды ТОЛЬКО от TG_USER_ID.
Связь с торговой логикой через файлы (см. tg_gate.py): читает tg_outbox.jsonl (события), пишет tg_inbox.jsonl (нажатия). В orders.json и tg_mode.json НЕ пишет.
Меню: /mode (сон / монитор / авто, для монитора таймер 1/2/4/8 ч или без), /status. Под предложением: «Поставить» / «Отклонить» (с причиной); под ордером в авто: «Отменить ордер»."""
import json, os, sys, time, threading, traceback
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_notify as T
try: import tg_express as X        # мнение бота в экспрессе; удалить файл -> работает без него
except Exception: X = None
try: import tg_target as TGT      # самообучение цели (Авто и экспресс); см. tg_target.py
except Exception: TGT = None
try: import tg_learn as LRN        # журнал «согласен / не согласен»; можно отключить кнопкой или удалить файл
except Exception: LRN = None

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
        if m.get("until"): s += "\nТаймер до %s%s" % (hhmm(m["until"]), " (в экспрессе не действует)" if m.get("express") else "")
        if m.get("express"): s += "\n⚡ Экспресс слежение ВКЛ: счётчик пропусков и таймер не действуют, анализ с мнением бота приходит после каждой закрытой свечи, пока не выключите." + ("\n🧠 Обучение (запись ваших ответов): %s" % ("вкл" if LRN and LRN.enabled() else "выкл") if LRN else "")
        if m.get("alerts_off"): s += "\n🔕 Новые алерты отключены (идущие слежения продолжаются). Таймер идёт."
    s += {"sleep": "\nНовых ордеров нет, уведомлений о новых точках нет. Открытые позиции продолжает вести бот; неподтверждённые вами ордера отменены.",
          "monitor": "\nБот присылает момент, когда цена касается или пересекает линию канала. Вы решаете: «Отклонить» или «Следить», а при слежении после каждой свечи можно выставить ордер. Одновременно не больше трёх графиков в работе.",
          "auto": "\nБот ставит ордера сам и присылает график."}.get(m["mode"], "")
    return s


MENU = [[{"text": "😴 Сон", "callback_data": "m:sleep"}, {"text": "👁 Монитор", "callback_data": "m:monitor"}, {"text": "🤖 Авто", "callback_data": "m:auto"}], [{"text": "💼 Счёт и позиции", "callback_data": "st"}, {"text": "📋 Ордера", "callback_data": "ol"}]]
REFRESH = [[{"text": "🔄 Обновить", "callback_data": "st"}]]


def menu(off=None):
    """Главное меню; в Мониторе добавляется кнопка отключения / включения алертов (off - явное состояние из события)."""
    m = mode_state()
    if m.get("mode") != "monitor": return MENU
    if off is None: off = bool(m.get("alerts_off"))
    rows = MENU + [[{"text": "🔔 Включить алерты" if off else "🔕 Отключить алерты", "callback_data": "al:1" if off else "al:0"}]]
    ex = bool(m.get("express"))
    rows.append([{"text": "⚡ Выключить экспресс" if ex else "⚡ Экспресс слежение", "callback_data": "ex:0" if ex else "ex:1"}])
    if ex and LRN: rows.append([{"text": "🧠 Обучение: %s (нажмите, чтобы %s)" % (("вкл", "выключить") if LRN.enabled() else ("выкл", "включить")), "callback_data": "xl:0" if LRN.enabled() else "xl:1"}])
    return rows
ORD_RULE = {"tg_stop": "стоп-ордер на вход", "tg_market": "по рынку", "tg_limit": "лимит у линии", "chan_top": "авто: от верхней границы", "chan_bottom": "авто: от нижней границы", "retest_up": "авто: ретест после пробоя вверх", "retest_down": "авто: ретест после пробоя вниз"}


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


POSTSF = os.path.join(os.path.dirname(MSGF), "tg_posts.jsonl")      # журнал постов слежения: чтобы связывать посты пары в цепочку и отмечать моменты задним числом


def post_add(rec):
    try:
        with open(POSTSF, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e: log("post_add: %s" % e)


def posts_tail(n=3000):
    try: lines = open(POSTSF, encoding="utf-8").read().split("\n")[-n:]
    except OSError: return []
    out = []
    for ln in lines:
        try: out.append(json.loads(ln))
        except Exception: pass
    return out


def post_get(mid): return next((p for p in reversed(posts_tail()) if p.get("mid") == mid), None)
def post_last_mid(sym): return next((p["mid"] for p in reversed(posts_tail()) if p.get("sym") == sym), None)


def retro_row(done=False):
    return [{"text": "📝 Отмечено: здесь надо было заходить" if done else "🎯 Здесь надо было заходить", "callback_data": "xn" if done else "xr"}]


def express_on():
    m = mode_state(); return bool(m.get("express")) and m.get("mode") == "monitor"


def watch_buttons(wid, kind, V=None, retro_done=False):
    off = [{"text": "🔕 Отключить алерты", "callback_data": "al:0"}]
    if express_on():     # экспресс: слежение уже идёт само, «Продолжать» не нужно
        if V is None: V = (msgs_load().get("w%d" % wid) or {}).get("v")
        rows = [[{"text": "📌 Выставить ордер", "callback_data": "wp:%d" % wid}, {"text": "❌ Отклонить", "callback_data": "wr:%d" % wid}, {"text": "⏹ Стоп", "callback_data": "ws:%d" % wid}]]
        if V and V.get("call") == "enter" and LRN and LRN.enabled():
            if V.get("ans") is None: rows.append([{"text": "✅ Согласен открыть сейчас", "callback_data": "xa:%d:1" % wid}, {"text": "🚫 Не согласен", "callback_data": "xa:%d:0" % wid}])
            else: rows.append([{"text": "📝 Записано: %s" % ("согласен" if V["ans"] else "не согласен"), "callback_data": "xn"}])
        if V and LRN and LRN.enabled(): rows.append(retro_row(retro_done))
        return rows + [[{"text": "⚡ Выключить экспресс", "callback_data": "ex:0"}] + off]
    if kind == "alert": return [[{"text": "👁 Следить", "callback_data": "wa:%d" % wid}, {"text": "❌ Отклонить", "callback_data": "wr:%d" % wid}], off]
    return [[{"text": "▶️ Продолжать следить", "callback_data": "wc:%d" % wid}, {"text": "⏹ Перестать следить", "callback_data": "ws:%d" % wid}], [{"text": "📌 Выставить ордер", "callback_data": "wp:%d" % wid}], off]


def send_watch(wid, kind):
    w = watch_get(wid)
    if not w: return
    key = "w%d" % wid; m = msgs_load(); old = m.get(key)
    if old and kind == "update":     # у предыдущего графика этой пары снимаем кнопки (в экспрессе остаётся только отметка «здесь надо было заходить»)
        try:
            keep = [retro_row(bool(LRN and LRN.has_mark(old["mid"], 2)))] if (old.get("v") and LRN and LRN.enabled()) else []
            api("editMessageReplyMarkup", chat_id=CHAT, message_id=old["mid"], reply_markup={"inline_keyboard": keep})
        except Exception as e: log("strip old buttons: %s" % e)
    kl = jload("/tmp/klcache/%s_5m_1000.json" % w["sym"], [])
    cap = T.caption_watch(w, kind); V = None
    if X and express_on():     # экспресс: добавляем мнение бота (заходить или ждать) и, если заходить, подсказку из журнала
        try:
            V = X.verdict(w, kl)
            if V:
                cap = cap.replace("\nСледить или отклонить?", "\n⚡ Экспресс: слежу автоматически.") + "\n\n" + V["text"]
                if V["call"] == "enter" and LRN and LRN.enabled():
                    try: cap += "\n" + LRN.note(V)
                    except Exception as e: log("learn note: %s" % e)
                if len(cap) > 940: cap = cap[:937] + "..."
        except Exception as e: log("express verdict: %s" % e); V = None
    btn = watch_buttons(wid, kind, V)
    prev = post_last_mid(w["sym"]); photo = True       # ответ на предыдущий пост этой пары: в Telegram виден как цитата, нажатие переносит к нему
    try: r = T.send_photo(T.render_watch(w, kl), cap, btn, reply_to=prev)
    except Exception as e:
        log("render watch fail %s: %s" % (wid, e)); r = T.send_text(cap, btn, reply_to=prev); photo = False
    mid_new = r["result"]["message_id"]
    m = msgs_load(); m[key] = {"mid": mid_new, "cap": cap, "kind": kind, "photo": photo}
    if V: m[key]["v"] = {k: V.get(k) for k in ("call", "feat", "plan", "geo", "t", "sym", "side")}; m[key]["v"]["ans"] = None
    msgs_save(m)
    post_add({"mid": mid_new, "wid": wid, "sym": w["sym"], "kind": kind, "ts": int(time.time() * 1000), "prev": prev, "v": m[key].get("v")})


def edit_watch(wid, status, buttons=None):
    m = msgs_load(); rec = m.get("w%d" % wid)
    if not rec: api("sendMessage", chat_id=CHAT, text="Слежение %d: %s" % (wid, status)); return
    cap = rec["cap"] + "\n\n" + status; kb = {"inline_keyboard": buttons or []}
    try:
        if rec.get("photo"): api("editMessageCaption", chat_id=CHAT, message_id=rec["mid"], caption=cap, reply_markup=kb)
        else: api("editMessageText", chat_id=CHAT, message_id=rec["mid"], text=cap, reply_markup=kb)
    except Exception as e: log("edit watch fail %s: %s" % (wid, e))


def plan_price(w, setup, entry):
    """Цена входа для выбранного сетапа/типа входа (те же формулы, что _tg_mkorder в chan_orders). Возвращает (цена, ошибка)."""
    L = w.get("last") or {}
    if L.get("Rn") is None: return None, "нет данных канала"
    a = float(L["atr"]); R, S = float(L["Rn"]), float(L["Sn"]); px = float(L["c"])
    up = (w.get("line") or ("upper" if w["side"] == "short" else "lower")) == "upper"; line = R if up else S; brk = setup == "k"
    s = (1 if up else -1) if brk else (-1 if up else 1)
    if brk:
        if entry == "market": return px, None
        if entry == "stop":
            price = line + s * 0.15 * a
            return (price, None) if (price - px) * s > 0.05 * a else (None, "цена уже за уровнем стоп-ордера (%s): выберите вход по рынку" % T.fmt_px(price))
        price = line + s * 0.1 * a
        return (price, None) if (px - price) * s >= 0.15 * a else (None, "ретест невозможен: цена ещё не ушла за линию (линия %s)" % T.fmt_px(line))
    if entry == "market": return px, None
    if entry == "limit": return (line if ((s < 0 and px < line) or (s > 0 and px > line)) else px), None
    price = (float(L["l"]) if s < 0 else float(L["h"])) + s * 0.1 * a
    return (price, None) if (price - px) * s > 0.05 * a else (None, "цена уже за уровнем стоп-ордера (%s): выберите вход по рынку" % T.fmt_px(price))


def target_options(w, entry, setup="b"):
    """Цели с оценкой прибыли и R:R. setup: b (отбой от линии) | k (пробой линии). Возвращает (список (подпись, код), ошибка)."""
    price, err = plan_price(w, setup, entry)
    if err: return [], err
    L = w.get("last") or {}; a = float(L["atr"]); R, S = float(L["Rn"]), float(L["Sn"]); H = R - S
    up = (w.get("line") or ("upper" if w["side"] == "short" else "lower")) == "upper"; line = R if up else S; brk = setup == "k"
    s = (1 if up else -1) if brk else (-1 if up else 1)
    risk = max(1.2 * a, 0.005 * price); out = []
    if brk: items = (("h05", "0.5 высоты канала за линией", 0.5), ("h1", "1 высота канала за линией", 1.0), ("h15", "1.5 высоты канала за линией", 1.5))
    else: items = (("opp", "противоположная линия", None), ("mid", "середина канала", 0.5), ("q1", "1/4 канала", 0.25), ("q3", "3/4 канала", 0.75))
    for code, label, f in items:
        if brk: tp = line + s * f * H
        else: tp = ((S + 0.1 * a) if s < 0 else (R - 0.1 * a)) if f is None else ((R - f * H) if s < 0 else (S + f * H))
        gain = (tp - price) * s
        if gain < max(0.0015 * price, 0.5 * a): out.append(("%s · уже пройдена/слишком близко" % label, "x")); continue
        out.append(("%s · +%.2f%% · R:R %.1f" % (label, gain / price * 100, gain / risk), code))
    return out, None


def setup_menu(w, wid):
    up = (w.get("line") or ("upper" if w["side"] == "short" else "lower")) == "upper"
    bs, ks = ("SHORT", "LONG") if up else ("LONG", "SHORT"); ln = "верхней" if up else "нижней"
    return [[{"text": "↩️ Отбой: %s от %s линии" % (bs, ln), "callback_data": "wps:%d:b" % wid}], [{"text": "💥 Пробой: %s через %s линию" % (ks, "верхнюю" if up else "нижнюю"), "callback_data": "wps:%d:k" % wid}], [{"text": "↩ назад", "callback_data": "wpb:%d" % wid}]]


def entry_menu(wid, setup):
    if setup == "k": rows = [[{"text": "📈 По рынку", "callback_data": "wpe:%d:k:market" % wid}], [{"text": "🎯 Стоп-ордер за линией", "callback_data": "wpe:%d:k:stop" % wid}], [{"text": "📌 Лимит на ретесте", "callback_data": "wpe:%d:k:limit" % wid}]]
    else: rows = [[{"text": "📈 По рынку", "callback_data": "wpe:%d:b:market" % wid}], [{"text": "📌 Лимит у линии", "callback_data": "wpe:%d:b:limit" % wid}], [{"text": "🎯 Стоп-ордер (после движения от линии)", "callback_data": "wpe:%d:b:stop" % wid}]]
    return rows + [[{"text": "↩ назад", "callback_data": "wp:%d" % wid}]]


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
        elif ev.get("what") == "follow": edit_watch(wid, "👁 Слежу. Следующий график пришлю после закрытия свечи.", watch_buttons(wid, "update") if express_on() else None)
        elif ev.get("what") == "continue": edit_watch(wid, "▶️ Продолжаю следить.")
    elif t == "watch_end":
        wid = ev.get("wid"); why = ev.get("why", "")
        if ev.get("code"): why += " (%s)" % REASON_RU.get(ev["code"], ev["code"])
        if ev.get("missed"): why += ". Пропущено подряд: %d из %d" % (ev["missed"], mode_state().get("max_missed", 3))
        edit_watch(wid, "⏹ " + why)
    elif t == "mode":
        txt = mode_text()
        if ev.get("mode") == "sleep": txt += "\nОтменено неподтверждённых ордеров: %d." % ev.get("cancelled", 0)
        api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": menu()})
    elif t == "express":
        if ev.get("refused"): api("sendMessage", chat_id=CHAT, text="⚡ Экспресс доступен только в режиме Монитор. Сначала включите Монитор: /mode", reply_markup={"inline_keyboard": menu()})
        else: api("sendMessage", chat_id=CHAT, text=("⚡ Экспресс слежение включено.\n" if ev.get("on") else "⚡ Экспресс выключен: счётчик пропусков и таймер снова действуют.\n") + mode_text(), reply_markup={"inline_keyboard": menu()})
    elif t == "alerts":
        off = bool(ev.get("off")); n = ev.get("cancelled", 0)
        txt = ("🔕 Алерты отключены. Новых алертов не будет" + (", алерты без ответа сняты (%d)" % n if n else "") + ". Идущие слежения продолжаются. Выставленные ордера и позиции работают как раньше, таймер идёт.\nВключить: кнопка ниже или /alerts") if off else "🔔 Алерты включены. Новые касания линий снова будут приходить."
        api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": menu(off)})
    elif t == "sleep":
        why = {"missed": "пропущено подряд %s предложений" % ev.get("n"), "timer": "истёк таймер монитора"}.get(ev.get("why"), "")
        api("sendMessage", chat_id=CHAT, text="😴 Ухожу в сон: %s.\nОтменено неподтверждённых ордеров: %d. Открытые позиции продолжает вести бот (стоп, безубыток, трейлинг).\nВключить снова: /mode" % (why, ev.get("cancelled", 0)), reply_markup={"inline_keyboard": menu()})
    elif t == "filled":
        o = load_order(oid)
        if o: api("sendMessage", chat_id=CHAT, text="▶️ Позиция #%s открыта: %s %s по %s (%s, ордер #%s)." % (ev.get("pos"), o["sym"], o["side"].upper(), T.fmt_px(o.get("fill_px") or o["price"]), ORD_RULE.get(o.get("rule"), "лимит"), oid), reply_markup={"inline_keyboard": REFRESH + MENU[:1]})


_res_t = [0.0]; _pos_t = [0.0]


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
        if LRN and time.time() - _res_t[0] > 300:      # раз в 5 минут дописываем исходы (цель/стоп) к записям журнала
            _res_t[0] = time.time()
            try: LRN.resolve(lambda sym: jload("/tmp/klcache/%s_5m_1000.json" % sym, []))
            except Exception: log("learn resolve: " + traceback.format_exc()[-300:])
        if TGT and time.time() - _pos_t[0] > 300:      # самообучение цели: закрытые позиции счёта -> дальность отбоя в выборку (tg_target.py)
            _pos_t[0] = time.time()
            try: TGT.learn_positions(limit=2)
            except Exception: log("learn positions: " + traceback.format_exc()[-300:])
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


def status_data():
    """Данные для картинки-карточки счёта (tg_notify.render_status)."""
    m = mode_state(); orders = jload(ORDF, [])
    pend = sorted([o for o in orders if o.get("status") == "pending"], key=lambda x: x["id"]); prop = sum(1 for o in orders if o.get("status") == "proposed"); now = int(time.time() * 1000)
    mo = m.get("mode", "auto"); info = []
    if mo == "sleep": info.append("Новых ордеров и уведомлений нет. Открытые позиции продолжает вести бот.")
    elif mo == "monitor":
        parts = (["Таймер до %s" % hhmm(m["until"])] if m.get("until") else []) + ["пропущено подряд %d из %d" % (m.get("missed", 0), m.get("max_missed", 3))]
        info.append(" · ".join(parts))
        if m.get("alerts_off"): info.append("Новые алерты отключены (идущие слежения продолжаются)")
        if m.get("express"): info.append("⚡ Экспресс: анализ после каждой свечи, пропуски и таймер не действуют")
    else: info.append("Бот ставит ордера сам и присылает график.")
    ws = [x for x in (jload(WATCHF, {}).get("items") or []) if x.get("status") in ("alert", "watching")]
    d = {"acct": ACCT, "sub": "", "mode": mo, "mode_ru": {"sleep": "Сон", "monitor": "Монитор", "auto": "Авто"}.get(mo, mo), "info": info, "equity": None, "tiles": [], "positions": [],
         "orders": {"pend": len(pend), "prop": prop, "rows": [(o["sym"], o["side"].upper(), "%s · вход %s · цель %s · через %d мин" % (ORD_RULE.get(o.get("rule"), o.get("rule")), T.fmt_px(o["price"]), T.fmt_px(o["tp"]), max(0, int((o["expire_t"] - now) / 60000)))) for o in pend[:5]]},
         "watches": [("%s %s: %s" % (x["sym"], x["side"].upper(), "ждёт вашего решения" if x["status"] == "alert" else "слежу (%d св.)" % x.get("updates", 0)), "#e3b341" if x["status"] == "alert" else "#c9d1d9") for x in ws],
         "max_watch": m.get("max_watch", 3), "stamp": datetime.now(T._tz()).strftime("%H:%M:%S")}
    try:
        sn = fetch_snapshot(); a = sn["account"]; opn = sn.get("open", []); tot = a["equity"] - a["start"]; wh = "#e6edf3"
        d.update(sub="бумажный счёт · старт %.0f $ · плечо %d× · ставка %.0f $" % (a["start"], a["lev"], a["stake"]), equity=a["equity"], chg_usd=tot, chg_pct=tot / a["start"] * 100,
                 tiles=[("Кошелёк", "%.2f $" % (a["start"] + a["realized"]), wh), ("Нереализ. PnL", "%s $" % sg(a["unreal"]), "#26a69a" if a["unreal"] >= 0 else "#ef5350"), ("В марже", "%.2f $" % a["open_margin"], wh), ("Доступно", "%.2f $" % a["free"], wh)],
                 positions=[{"sym": str(p["sym"]).replace("USDT", ""), "side": p["side"].upper(), "pct": p["unreal_pct"], "usd": p["unreal_usd"], "be": bool(p.get("armed")), "part": p.get("rem", 1) < 0.999} for p in opn[:8]])
    except Exception as e:
        log("snapshot fail: %s" % e); d["sub"] = "бумажный счёт"
    return d


def status_caption(d):
    if d.get("equity") is None: return "Счёт «%s»: баланс и позиции получить не удалось" % ACCT
    return "Счёт «%s»: %.2f $ (%s) · позиций %d · ордеров ждут %d" % (ACCT, d["equity"], sg(d["chg_pct"], 2, "%"), len(d["positions"]), d["orders"]["pend"])


def status_kb():
    rows = [[{"text": "🔄 Обновить", "callback_data": "st"}, {"text": "📋 Ордера", "callback_data": "ol"}]] + MENU[:1]
    mm = menu()
    if len(mm) > len(MENU): rows.extend(mm[len(MENU):])      # в Мониторе: кнопки алертов, экспресса (и обучения)
    return rows


def status_card(msg=None):
    """Карточка счёта картинкой. msg - сообщение с нажатой кнопкой: если это уже картинка, обновляем её на месте, иначе присылаем новую. Если картинку построить не удалось, текстовая карточка."""
    try: d = status_data(); png = T.render_status(d); cap = status_caption(d)
    except Exception:
        log("status render fail: " + traceback.format_exc()[-400:]); txt = status_text()
        if msg and not msg.get("photo"): api("editMessageText", chat_id=CHAT, message_id=msg["message_id"], text=txt, reply_markup={"inline_keyboard": REFRESH + MENU[:1]})
        else: api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": REFRESH + MENU[:1]})
        return
    if msg and msg.get("photo"):
        try: T._post("editMessageMedia", {"chat_id": CHAT, "message_id": msg["message_id"], "media": json.dumps({"type": "photo", "media": "attach://photo", "caption": cap}, ensure_ascii=False), "reply_markup": json.dumps({"inline_keyboard": status_kb()})}, {"photo": ("status.png", png, "image/png")})
        except Exception as e: log("status edit media: %s" % e)
    else: T.send_photo(png, cap, status_kb())


def edit_text(msg, **kw):
    """Правка текстового сообщения; если нажата кнопка под картинкой (текст в ней править нельзя), шлём новое сообщение."""
    if msg.get("photo"): api("sendMessage", chat_id=CHAT, text=kw["text"], reply_markup=kw.get("reply_markup"))
    else: api("editMessageText", chat_id=CHAT, message_id=msg["message_id"], **kw)


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
            edit_text(msg, text="Монитор: на какое время включить? Счётчик пропусков работает всегда.", reply_markup={"inline_keyboard": [[{"text": "1 ч", "callback_data": "mt:1"}, {"text": "2 ч", "callback_data": "mt:2"}, {"text": "4 ч", "callback_data": "mt:4"}, {"text": "8 ч", "callback_data": "mt:8"}], [{"text": "без таймера", "callback_data": "mt:0"}, {"text": "↩ назад", "callback_data": "mb"}]]})
        else:
            inbox({"type": "mode", "mode": p[1]}); api("answerCallbackQuery", callback_query_id=cid, text="Переключаю: %s" % MODE_RU[p[1]])
    elif p[0] == "ex":
        inbox({"type": "express", "on": p[1] == "1"}); api("answerCallbackQuery", callback_query_id=cid, text="Включаю экспресс…" if p[1] == "1" else "Выключаю экспресс…")
    elif p[0] == "xl":
        if LRN: LRN.set_enabled(p[1] == "1")
        api("answerCallbackQuery", callback_query_id=cid, text="Обучение включено" if p[1] == "1" else "Обучение выключено (журнал сохранён)")
        api("sendMessage", chat_id=CHAT, text=mode_text(), reply_markup={"inline_keyboard": menu()})
    elif p[0] == "xn": api("answerCallbackQuery", callback_query_id=cid, text="Ответ уже записан")
    elif p[0] == "xr":      # отметка задним числом: «здесь надо было заходить»
        pr = post_get(mid); V = (pr or {}).get("v")
        if not V or not LRN or not LRN.enabled(): api("answerCallbackQuery", callback_query_id=cid, text="Обучение выключено или нет данных по этому посту"); return
        if LRN.has_mark(mid, 2): api("answerCallbackQuery", callback_query_id=cid, text="Уже отмечено"); return
        try: LRN.record(V, 2, pr.get("wid"), mid)
        except Exception as e: log("learn retro: %s" % e); api("answerCallbackQuery", callback_query_id=cid, text="Не удалось записать"); return
        api("answerCallbackQuery", callback_query_id=cid, text="Записал: здесь надо было заходить")
        rec = msgs_load().get("w%d" % (pr.get("wid") or -1)) or {}
        kb = watch_buttons(pr["wid"], rec.get("kind", "update"), rec.get("v"), retro_done=True) if rec.get("mid") == mid else [retro_row(True)]
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": kb})
    elif p[0] == "xa":
        wid = int(p[1]); ok = p[2] == "1"; mm = msgs_load(); rec = mm.get("w%d" % wid) or {}; V = rec.get("v")
        if not V or not LRN or not LRN.enabled(): api("answerCallbackQuery", callback_query_id=cid, text="Обучение выключено или пост устарел"); return
        if V.get("ans") is not None: api("answerCallbackQuery", callback_query_id=cid, text="Ответ уже записан"); return
        try: LRN.record(V, 1 if ok else 0, wid, mid)
        except Exception as e: log("learn record: %s" % e); api("answerCallbackQuery", callback_query_id=cid, text="Не удалось записать"); return
        V["ans"] = 1 if ok else 0; mm["w%d" % wid] = rec; msgs_save(mm)
        api("answerCallbackQuery", callback_query_id=cid, text="Записал: %s" % ("согласен" if ok else "не согласен"))
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": watch_buttons(wid, rec.get("kind", "update"), V)})
    elif p[0] == "al":
        on = p[1] == "1"; inbox({"type": "alerts", "on": on}); api("answerCallbackQuery", callback_query_id=cid, text="Включаю алерты…" if on else "Отключаю алерты…")
    elif p[0] == "mt":
        h = float(p[1]); inbox({"type": "mode", "mode": "monitor", "hours": h or None}); api("answerCallbackQuery", callback_query_id=cid, text="Монитор включается")
    elif p[0] == "st":
        api("answerCallbackQuery", callback_query_id=cid, text="Собираю данные…")
        try: status_card(msg)
        except Exception as e: log("status card: %s" % e)
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
        wid = int(p[1]); w = watch_get(wid)
        if not w: api("answerCallbackQuery", callback_query_id=cid, text="слежение уже не актуально"); return
        api("answerCallbackQuery", callback_query_id=cid)
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": setup_menu(w, wid)})
    elif p[0] == "wps":
        wid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid)
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": entry_menu(wid, p[2])})
    elif p[0] == "wpb":
        wid = int(p[1]); api("answerCallbackQuery", callback_query_id=cid); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": watch_buttons(wid, "update")})
    elif p[0] == "wpe":
        wid = int(p[1]); setup, entry = (p[2], p[3]) if len(p) >= 4 else ("b", p[2]); w = watch_get(wid)     # старый формат: wpe:wid:entry = отбой
        opts, err = target_options(w, entry, setup) if w else ([], "слежение уже не актуально")
        if err: api("answerCallbackQuery", callback_query_id=cid, text=err, show_alert="true"); return
        api("answerCallbackQuery", callback_query_id=cid)
        rows = [[{"text": lab, "callback_data": "wpt:%d:%s:%s:%s" % (wid, setup, entry, code)}] for lab, code in opts if code != "x"] + [[{"text": lab, "callback_data": "wpe:%d:%s:%s" % (wid, setup, entry)}] for lab, code in opts if code == "x"]
        rows.append([{"text": "↩ назад", "callback_data": "wps:%d:%s" % (wid, setup)}]); api("editMessageReplyMarkup", chat_id=CHAT, message_id=mid, reply_markup={"inline_keyboard": rows})
    elif p[0] == "wpt":
        wid = int(p[1]); setup, entry, tgt = (p[2], p[3], p[4]) if len(p) >= 5 else ("b", p[2], p[3])     # старый формат: wpt:wid:entry:target = отбой
        inbox({"type": "w_place", "wid": wid, "entry": entry, "target": tgt, "setup": "breakout" if setup == "k" else "bounce"}); api("answerCallbackQuery", callback_query_id=cid, text="Ставлю ордер…")
        edit_watch(wid, "⏳ Ставлю ордер (%s, %s, цель: %s)…" % ("пробой" if setup == "k" else "отбой", {"market": "по рынку", "limit": "лимит", "stop": "стоп-ордер"}.get(entry, entry), tgt))
    elif p[0] == "mb":
        api("answerCallbackQuery", callback_query_id=cid); api("editMessageText", chat_id=CHAT, message_id=mid, text=mode_text(), reply_markup={"inline_keyboard": menu()})
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
    if t.startswith(("/start", "/mode", "/menu")): api("sendMessage", chat_id=CHAT, text=mode_text(), reply_markup={"inline_keyboard": menu()})
    elif t.startswith("/alerts"):
        on = bool(mode_state().get("alerts_off")); inbox({"type": "alerts", "on": on})
        api("sendMessage", chat_id=CHAT, text="Включаю алерты…" if on else "Отключаю алерты…")
    elif t.startswith(("/orders", "/ordera")): txt, kb = orders_list(); api("sendMessage", chat_id=CHAT, text=txt, reply_markup={"inline_keyboard": kb})
    elif t.startswith(("/status", "/balance")): status_card()
    else: api("sendMessage", chat_id=CHAT, text="Команды: /mode (режим), /alerts (алерты вкл/выкл), /status (состояние), /orders (ордера и отмена).")


def main():
    log("tg_bot start, POS_DIR=%s" % D)
    try: api("setMyCommands", commands=[{"command": "mode", "description": "Режим: сон / монитор / авто"}, {"command": "status", "description": "Счёт, баланс, позиции"}, {"command": "orders", "description": "Выставленные ордера и отмена"}, {"command": "alerts", "description": "Алерты: отключить / включить"}])
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
