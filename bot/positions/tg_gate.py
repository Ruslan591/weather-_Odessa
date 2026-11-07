# -*- coding: utf-8 -*-
"""tg_gate.py -- режимы счёта «Регрессия»: Сон / Монитор / Авто (управляются из Telegram). Только stdlib.

Включается переменной окружения TG_GATE=1 (сервис chan-orders-regr); без неё модуль ничего не делает и ордера ставятся как раньше (Авто без уведомлений).
Файлы в POS_DIR (единственный писатель указан в скобках):
  tg_mode.json   - {"mode","missed","max_missed","answer_win","until"}   (chan_orders)
  tg_outbox.jsonl - события для Telegram: proposal, placed, approved, rejected, missed, stale, mode, sleep, filled  (chan_orders)
  tg_inbox.jsonl  - нажатия пользователя: mode, approve, reject (+код причины)  (tg_bot)
  tg_inbox.off    - смещение прочитанного в inbox (chan_orders)
Режимы:
  sleep   - новых ордеров нет и сообщений о новых точках нет. Уже выставленные ордера и открытые позиции продолжают работать.
  monitor - найденная точка приходит в Telegram как предложение (статус proposed); без ответа за answer_win свечей (по умолчанию 3 = 15 минут) или до истечения срока самого ордера
            предложение пропускается (missed), ордер НЕ ставится; подряд пропущенных >= max_missed (по умолчанию 3) или истёк таймер until -> режим переходит в sleep с уведомлением.
  auto    - бот сам ставит ордер как раньше; в Telegram приходит график и кнопка отмены.
После «Поставить»: ордер становится pending с placed_t = начало следующей минуты (без заглядывания в прошлое); если цена уже коснулась уровня или срок почти вышел - «поздно»."""
import json, os, time

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
ENABLED = os.environ.get("TG_GATE", "0") == "1"
MODEF = os.path.join(D, "tg_mode.json"); OUTF = os.path.join(D, "tg_outbox.jsonl"); INF = os.path.join(D, "tg_inbox.jsonl"); OFFF = os.path.join(D, "tg_inbox.off")
MODES = ("sleep", "monitor", "auto"); TFM = 300000
DEFAULT = {"mode": "auto", "missed": 0, "max_missed": 3, "answer_win": 3, "until": None}


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
    if m["mode"] == "sleep": return False
    if m["mode"] == "monitor":
        p["status"] = "proposed"; p["ans_deadline"] = min(int(p["expire_t"]), int(now) + int(m["answer_win"]) * TFM)
        emit({"type": "proposal", "id": p["id"]}); return True
    emit({"type": "placed", "id": p["id"]}); return True


def on_cancel(o, was, why):
    """Из cancel() в chan_orders: если отменено предложение, снять кнопки в Telegram."""
    if ENABLED and was == "proposed": emit({"type": "stale", "id": o["id"], "why": why})


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


def apply(orders, now, cancel, touched):
    """Применить нажатия пользователя и сроки. Возвращает список заданий для журнала [(order_copy, action, extra)].
    Вызывается под pos.lock() в chan_orders; touched(o) -> True, если цена уже коснулась уровня ордера после выставления."""
    jobs = []
    if not ENABLED: return jobs
    m = load_mode(); m0 = json.dumps(m, sort_keys=True); by = {o["id"]: o for o in orders}
    for e in _read_inbox():
        t = e.get("type"); ts = int(e.get("ts") or now)
        if t == "mode" and e.get("mode") in MODES:
            m["mode"] = e["mode"]; m["missed"] = 0; h = e.get("hours")
            m["until"] = int(now + float(h) * 3600000) if h else None
            if m["mode"] == "sleep":
                for o in orders:
                    if o["status"] == "proposed": cancel(o, "режим сна", now)
            emit({"type": "mode", "mode": m["mode"], "until": m["until"], "why": "user"})
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
                m["missed"] = 0; emit({"type": "rejected", "id": o["id"], "ok": True, "code": code}); jobs.append((dict(o), "reject", {"reason": code, "was": st}))
    for o in orders:
        if o["status"] == "proposed" and now >= o.get("ans_deadline", 0):
            o.update(status="missed", reason="нет ответа", t_end=int(o.get("ans_deadline", now))); m["missed"] += 1
            emit({"type": "missed", "id": o["id"], "n": m["missed"]}); jobs.append((dict(o), "missed", {"n": m["missed"]}))
    if m["mode"] == "monitor":
        why = "missed" if m["missed"] >= m["max_missed"] else ("timer" if m.get("until") and now >= m["until"] else None)
        if why:
            m["mode"] = "sleep"; n = m["missed"]; m["until"] = None
            for o in orders:
                if o["status"] == "proposed": cancel(o, "режим сна", now)
            emit({"type": "sleep", "why": why, "n": n})
    if json.dumps(m, sort_keys=True) != m0: save_mode(m)
    return jobs
