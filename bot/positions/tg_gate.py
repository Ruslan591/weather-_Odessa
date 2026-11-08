# -*- coding: utf-8 -*-
"""tg_gate.py -- режимы счёта «Регрессия»: Сон / Монитор / Авто (управляются из Telegram). Только stdlib.

Включается переменной окружения TG_GATE=1 (сервис chan-orders-regr); без неё модуль ничего не делает и ордера ставятся как раньше (Авто без уведомлений).
Файлы в POS_DIR (единственный писатель указан в скобках):
  tg_mode.json   - {"mode","missed","max_missed","answer_win","until"}   (chan_orders)
  tg_outbox.jsonl - события для Telegram: proposal, placed, approved, rejected, missed, stale, mode, sleep, filled  (chan_orders)
  tg_inbox.jsonl  - нажатия пользователя: mode, approve, reject (+код причины)  (tg_bot)
  tg_inbox.off    - смещение прочитанного в inbox (chan_orders)
  tg_watch.json   - алерты и слежения {"seq","items":[{id,sym,side,status(alert|watching|done),ctype,chan,last,...}]}  (chan_orders)
Режимы (Монитор с 2026-11-08 = СЛЕЖЕНИЕ за касаниями линий канала, предложения «точка входа» в нём больше не присылаются):
  sleep   - новых ордеров нет и сообщений о новых точках нет. Уже выставленные ордера и открытые позиции продолжают работать.
  monitor - когда последняя закрытая свеча коснулась или пересекла границу канала по направлению (верхнюю в нисходящем, нижнюю в восходящем), приходит АЛЕРТ с кнопками «Отклонить» (с причиной) и «Следить».
            «Следить»: после закрытия каждой следующей свечи приходит график и кнопки «Продолжать следить / Перестать следить / Выставить ордер». «Выставить ордер»: выбор входа (по рынку / лимит у линии) и цели (противоположная линия, середина, 1/4, 3/4);
            ордер ставится сразу (pending, approved_t). Одновременно в работе не больше max_watch (3) графиков (алерты без ответа + слежения). Алерт без ответа за answer_win свечей -> пропуск (missed);
            подряд пропущенных >= max_missed (3) или истёк таймер until -> режим sleep. Слежение без ответа на 3 обновления подряд или дольше 4 часов завершается само. Старые предложения proposed остались в коде, но в Мониторе не создаются.
  auto    - бот сам ставит ордер как раньше; в Telegram приходит график и кнопка отмены.
После «Поставить»: ордер становится pending с placed_t = начало следующей минуты (без заглядывания в прошлое); если цена уже коснулась уровня или срок почти вышел - «поздно»."""
import json, os, time

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
ENABLED = os.environ.get("TG_GATE", "0") == "1"
WATCHF = os.path.join(D, "tg_watch.json"); MODEF = os.path.join(D, "tg_mode.json"); OUTF = os.path.join(D, "tg_outbox.jsonl"); INF = os.path.join(D, "tg_inbox.jsonl"); OFFF = os.path.join(D, "tg_inbox.off")
MODES = ("sleep", "monitor", "auto"); TFM = 300000
DEFAULT = {"mode": "auto", "missed": 0, "max_missed": 3, "answer_win": 3, "until": None, "max_watch": 3, "watch_unanswered": 3, "watch_hours": 4}


def load_mode():
    m = dict(DEFAULT)
    try: m.update(json.load(open(MODEF, encoding="utf-8")))
    except Exception: pass
    return m


def save_mode(m):
    tmp = MODEF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MODEF)


def emit(ev):
    if not ENABLED: return
    ev = dict(ev); ev.setdefault("ts", int(time.time() * 1000))
    try:
        with open(OUTF, "a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e: print("tg_gate emit err", e, flush=True)


def mode():
    return load_mode()["mode"] if ENABLED else "auto"


def on_place(p, now):
    """Вызывается, когда сканер хочет поставить новый ордер p (id уже присвоен). True - добавить в orders."""
    if not ENABLED: return True
    m = load_mode()
    if m["mode"] in ("sleep", "monitor"): return False     # Монитор: вместо предложений работает слежение (watch_scan)
    emit({"type": "placed", "id": p["id"]}); return True


def on_cancel(o, was, why):
    """Из cancel() в chan_orders: если отменено предложение или ордер не по команде пользователя, снять кнопки в Telegram."""
    if ENABLED and was in ("proposed", "pending") and not str(why).startswith("отменён пользователем"): emit({"type": "stale", "id": o["id"], "why": why})


def _go_sleep(orders, cancel, now):
    """Переход в сон: предложения снимаются, а ордера, которые пользователь не подтверждал (поставлены в Авто), отменяются. Подтверждённые им ордера и открытые позиции остаются (позиции ведёт бот)."""
    n = 0
    W = _wload()
    if _end_watches(W, now, "режим сна"): _wsave(W, now)
    for o in orders:
        if o["status"] == "proposed": cancel(o, "режим сна", now)
        elif o["status"] == "pending" and not o.get("approved_t"): cancel(o, "режим сна: ордер не подтверждён вами", now); n += 1
    return n


def _wload():
    try: return json.load(open(WATCHF, encoding="utf-8"))
    except Exception: return {"seq": 0, "items": []}


def _wsave(W, now=None):
    now = now or int(time.time() * 1000)
    W["items"] = [x for x in W["items"] if x["status"] != "done" or now - x.get("t_end", now) < 86400000]
    tmp = WATCHF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(W, f, ensure_ascii=False)
    os.replace(tmp, WATCHF)


def watch_needed(sym):
    """Нужно ли chan_orders считать канал для слежения по этой паре (только Монитор)."""
    return ENABLED and load_mode()["mode"] == "monitor"


def _last(info):
    return {k: info.get(k) for k in ("t", "o", "h", "l", "c", "atr", "R", "S", "Rn", "Sn")}


def _episode(info, line=None):
    """Эпизод у линии (line: upper | lower; по умолчанию линия по направлению канала): серия подряд идущих свечей (по текущим линиям), которые коснулись или пересекли линию, заканчивающаяся последней свечой.
    state: touch (касание, ни одна свеча не закрылась за линией), cross (последняя свеча закрылась за линией, первая), break (>=2 закрытий за линией, пробой формируется), back (были закрытия за линией, последняя вернулась внутрь)."""
    a = info["atr"]; run = []
    if line is None: line = "upper" if info["ctype"] == "channel_down" else "lower"
    up = line == "upper"
    for t, o_, h_, l_, c_, R_, S_ in reversed(info.get("hist") or []):
        if not ((h_ >= R_ - 0.1 * a) if up else (l_ <= S_ + 0.1 * a)): break
        run.append((t, (c_ > R_) if up else (c_ < S_), h_ if up else l_))
    if not run: return None
    run.reverse(); nb = sum(1 for r in run if r[1]); lb = run[-1][1]
    st = "break" if (nb >= 2 and lb) else ("cross" if (nb >= 1 and lb) else ("back" if nb >= 1 else "touch"))
    return {"state": st, "n_run": len(run), "n_beyond": nb, "t_start": run[0][0], "start_px": run[0][2]}


def _shift(x, info):
    """Насколько линия (в ATR) сместилась из-за перестройки канала: новое значение линии на последней свече минус значение по прежним параметрам канала."""
    try:
        ln = (x.get("chan") or {}).get("upper" if x["side"] == "short" else "lower"); new = info["R"] if x["side"] == "short" else info["S"]
        return round((new - (ln["p1"] + ln["s"] * (info["t"] - ln["t1"]))) / info["atr"], 2)
    except Exception: return None


def watch_scan(info, now):
    """Раз на новую закрытую свечу пары (из cycle). info: sym, t, o, h, l, c, atr, ctype, R, S, Rn, Sn, chan."""
    if not ENABLED: return
    m = load_mode()
    if m["mode"] != "monitor": return
    W = _wload(); items = W["items"]; ch = False; sym = info["sym"]
    for x in items:
        if x["sym"] == sym and x["status"] == "watching" and info["t"] > (x.get("last") or {}).get("t", 0):
            ep = _episode(info, x.get("line")) if info.get("ctype") else None
            x["shift"] = _shift(x, info) if info.get("ctype") else None
            x["last"] = _last(info); x["chan"] = info.get("chan") or x.get("chan"); x["updates"] += 1; x["unanswered"] += 1; ch = True
            x["state"] = ep["state"] if ep else "away"; x["n_beyond"] = ep["n_beyond"] if ep else 0
            if x["unanswered"] > int(m.get("watch_unanswered", 3)): x.update(status="done", reason="нет ответа на обновления", t_end=now); emit({"type": "watch_end", "wid": x["id"], "why": "нет ответа на %d обновления подряд" % int(m.get("watch_unanswered", 3))})
            elif now - x["t_follow"] > float(m.get("watch_hours", 4)) * 3600000: x.update(status="done", reason="прошло %s ч" % m.get("watch_hours", 4), t_end=now); emit({"type": "watch_end", "wid": x["id"], "why": "слежение длится дольше %s ч" % m.get("watch_hours", 4)})
            else: emit({"type": "watch_update", "wid": x["id"]})
    active = [x for x in items if x["status"] in ("alert", "watching")]
    if info.get("ctype") and info.get("R") is not None and len(active) < int(m.get("max_watch", 3)) and not any(x["sym"] == sym for x in active) and info["R"] - info["S"] >= 1.5 * info["atr"]:
        down = info["ctype"] == "channel_down"; a = info["atr"]; main_line = "upper" if down else "lower"
        lines = [main_line] + ([("lower" if down else "upper")] if m.get("watch_counter", True) else [])   # линия по тренду, затем противоположная (коррекция / разворот)
        for line in lines:
            side = "short" if line == "upper" else "long"      # side = направление отбоя от этой линии
            ep = _episode(info, line)
            cool = any(x["sym"] == sym and x["side"] == side and x["status"] == "done" and now - x.get("t_end", 0) < 1800000 for x in items)
            if not ep or cool: continue
            W["seq"] += 1; line_px = info["R"] if line == "upper" else info["S"]
            x = {"id": W["seq"], "sym": sym, "side": side, "line": line, "counter": line != main_line, "status": "alert", "ctype": info["ctype"], "chan": info.get("chan"), "chan0": info.get("chan"), "t_alert": info["t"], "created": now,
                 "deadline": now + int(m.get("answer_win", 3)) * TFM, "line_px": line_px, "touch_px": ep["start_px"], "atr": a, "last": _last(info), "updates": 0, "unanswered": 0,
                 "state0": ep["state"], "state": ep["state"], "n_beyond": ep["n_beyond"], "n_run": ep["n_run"], "t_ref": ep["t_start"], "shift": None}
            items.append(x); emit({"type": "alert", "wid": x["id"]}); ch = True; break
    if ch: _wsave(W, now)


def _end_watches(W, now, why):
    n = 0
    for x in W["items"]:
        if x["status"] in ("alert", "watching"):
            x.update(status="done", reason=why, t_end=now); n += 1; emit({"type": "watch_end", "wid": x["id"], "why": why})
    return n


def _read_inbox():
    try: size = os.path.getsize(INF)
    except OSError: return []
    try: off = int(open(OFFF).read().strip() or 0)
    except Exception: off = 0
    if off > size: off = 0
    out = []
    with open(INF, "rb") as f:
        f.seek(off); data = f.read()
    cut = data.rfind(b"\n")
    if cut < 0: return []
    for ln in data[:cut + 1].split(b"\n"):
        if ln.strip():
            try: out.append(json.loads(ln.decode("utf-8", "replace")))
            except Exception: pass
    with open(OFFF, "w") as f: f.write(str(off + cut + 1))
    return out


def _wevent(e, W, m, orders, now, mkorder, price_fn, jobs):
    """Нажатия пользователя по алертам и слежениям (w_follow, w_continue, w_stop, w_reject, w_place). True, если W изменён."""
    t = e.get("type"); x = next((i for i in W["items"] if i["id"] == e.get("wid")), None)
    if not x or x["status"] not in ("alert", "watching"):
        emit({"type": "watch_ack", "wid": e.get("wid"), "ok": False, "why": "уже не актуально"}); return False
    ts = int(e.get("ts") or now); was = x["status"]
    if t == "w_follow":
        if was != "alert": emit({"type": "watch_ack", "wid": x["id"], "ok": False, "why": "слежение уже идёт"}); return False
        if ts > x["deadline"]:
            x.update(status="done", reason="поздно: время на ответ вышло", t_end=now); emit({"type": "watch_end", "wid": x["id"], "why": "поздно: время на ответ вышло"}); return True
        x.update(status="watching", t_follow=now, unanswered=0); m["missed"] = 0
        emit({"type": "watch_ack", "wid": x["id"], "ok": True, "what": "follow"}); jobs.append((dict(x, _w=1), "w_follow", {"latency_s": round((ts - x["created"]) / 1000)})); return True
    if t == "w_continue":
        x["unanswered"] = 0; m["missed"] = 0; emit({"type": "watch_ack", "wid": x["id"], "ok": True, "what": "continue"}); jobs.append((dict(x, _w=1), "w_continue", {"n": x["updates"]})); return True
    if t == "w_stop":
        x.update(status="done", reason="остановлено пользователем", t_end=now); m["missed"] = 0
        emit({"type": "watch_end", "wid": x["id"], "why": "слежение остановлено вами"}); jobs.append((dict(x, _w=1), "w_stop", {"n": x["updates"]})); return True
    if t == "w_reject":
        code = e.get("code") or "none"; x.update(status="done", reason="отклонено: %s" % code, t_end=now, rej_reason=code); m["missed"] = 0
        emit({"type": "watch_end", "wid": x["id"], "why": "отклонено", "code": code}); jobs.append((dict(x, _w=1), "w_reject", {"reason": code, "reason_text": (e.get("text") or "")[:300] or None, "was": was})); return True
    if t == "w_place":
        if mkorder is None: emit({"type": "watch_ack", "wid": x["id"], "ok": False, "what": "place", "why": "постановка недоступна"}); return False
        try: px = price_fn(x["sym"]) if price_fn else None
        except Exception: px = None
        o, why = mkorder(x, e.get("entry"), e.get("target"), px or x["last"]["c"], e.get("setup") or "bounce")
        if not o: emit({"type": "watch_ack", "wid": x["id"], "ok": False, "what": "place", "why": why}); return False
        o["id"] = max([q["id"] for q in orders] + [0]) + 1; o["approved_t"] = now; o["src_watch"] = x["id"]; orders.append(o)
        x.update(status="done", reason="ордер #%d" % o["id"], t_end=now, order_id=o["id"]); m["missed"] = 0
        emit({"type": "placed", "id": o["id"], "src": "watch", "wid": x["id"]}); emit({"type": "watch_end", "wid": x["id"], "why": "ордер #%d выставлен" % o["id"], "order": o["id"]})
        jobs.append((dict(x, _w=1), "w_place", {"entry": e.get("entry"), "target": e.get("target"), "setup": e.get("setup") or "bounce", "order_id": o["id"], "price": o["price"]})); return True
    return False


def apply(orders, now, cancel, touched, mkorder=None, price_fn=None):
    """Применить нажатия пользователя и сроки. Возвращает список заданий для журнала [(order_copy, action, extra)].
    Вызывается под pos.lock() в chan_orders; touched(o) -> True, если цена уже коснулась уровня ордера после выставления."""
    jobs = []
    if not ENABLED: return jobs
    m = load_mode(); m0 = json.dumps(m, sort_keys=True); by = {o["id"]: o for o in orders}; W = _wload(); wch = False
    for e in _read_inbox():
        t = e.get("type"); ts = int(e.get("ts") or now)
        if t == "mode" and e.get("mode") in MODES:
            m["mode"] = e["mode"]; m["missed"] = 0; h = e.get("hours")
            m["until"] = int(now + float(h) * 3600000) if h else None
            nc = _go_sleep(orders, cancel, now) if m["mode"] == "sleep" else 0
            if m["mode"] == "auto": _end_watches(W, now, "режим авто"); wch = True
            if m["mode"] == "sleep": W = _wload()
            emit({"type": "mode", "mode": m["mode"], "until": m["until"], "why": "user", "cancelled": nc})
        elif t and t.startswith("w_"):
            wch = _wevent(e, W, m, orders, now, mkorder, price_fn, jobs) or wch
        elif t in ("approve", "reject"):
            o = by.get(e.get("id"))
            if not o: emit({"type": "ack", "id": e.get("id"), "ok": False, "why": "ордер не найден"}); continue
            st = o["status"]
            if t == "approve":
                if st != "proposed": emit({"type": "approved", "id": o["id"], "ok": False, "why": "уже не актуально (статус: %s)" % st}); continue
                if ts > o.get("ans_deadline", 0): emit({"type": "approved", "id": o["id"], "ok": False, "why": "поздно: время на ответ вышло"}); continue
                newp = (int(now) // 60000 + 1) * 60000
                if touched(o): o.update(status="late", reason="поздно: цена уже коснулась уровня", t_end=int(now)); emit({"type": "approved", "id": o["id"], "ok": False, "why": "поздно: цена уже коснулась уровня"}); jobs.append((dict(o), "approve_late", {"latency_s": round((ts - o["placed_t"]) / 1000)})); continue
                if int(o["expire_t"]) <= newp + 120000: o.update(status="late", reason="поздно: срок ордера почти вышел", t_end=int(now)); emit({"type": "approved", "id": o["id"], "ok": False, "why": "поздно: срок ордера почти вышел"}); continue
                o.update(status="pending", placed_t=newp, approved_t=ts); m["missed"] = 0
                emit({"type": "approved", "id": o["id"], "ok": True, "placed_t": newp}); jobs.append((dict(o), "approve", {"latency_s": round((ts - (newp - 60000)) / 1000)}))
            else:
                code = e.get("code") or "none"
                if st == "proposed": o.update(status="rejected", reason="отклонён пользователем: %s" % code, t_end=int(now), rej_reason=code)
                elif st == "pending": cancel(o, "отменён пользователем: %s" % code, now); o["rej_reason"] = code
                else: emit({"type": "rejected", "id": o["id"], "ok": False, "why": "уже не актуально (статус: %s)" % st}); continue
                m["missed"] = 0; emit({"type": "rejected", "id": o["id"], "ok": True, "code": code}); o["rej_text"] = (e.get("text") or "")[:300] or None
                jobs.append((dict(o), "reject", {"reason": code, "was": st, "reason_text": o["rej_text"]}))
    for o in orders:
        if o["status"] == "proposed" and now >= o.get("ans_deadline", 0):
            o.update(status="missed", reason="нет ответа", t_end=int(o.get("ans_deadline", now))); m["missed"] += 1
            emit({"type": "missed", "id": o["id"], "n": m["missed"]}); jobs.append((dict(o), "missed", {"n": m["missed"]}))
    for x in W["items"]:
        if x["status"] == "alert" and now >= x["deadline"]:
            x.update(status="done", reason="нет ответа", t_end=now); m["missed"] += 1; wch = True
            emit({"type": "watch_end", "wid": x["id"], "why": "нет ответа", "missed": m["missed"]}); jobs.append((dict(x, _w=1), "w_missed", {"n": m["missed"]}))
    if wch: _wsave(W, now)
    if m["mode"] == "monitor":
        why = "missed" if m["missed"] >= m["max_missed"] else ("timer" if m.get("until") and now >= m["until"] else None)
        if why:
            m["mode"] = "sleep"; n = m["missed"]; m["until"] = None
            nc = _go_sleep(orders, cancel, now)
            emit({"type": "sleep", "why": why, "n": n, "cancelled": nc})
    if json.dumps(m, sort_keys=True) != m0: save_mode(m)
    return jobs
