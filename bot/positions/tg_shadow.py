# -*- coding: utf-8 -*-
"""tg_shadow.py -- «теневые» бумажные позиции по пропущенным сигналам «ЗАХОДИТЬ» (мнение бота enter в посте слежения).

Зачем: пользователь не может открыть часть сигналов по бытовым причинам. Каждый такой сигнал бот ведёт на бумаге до цели, стопа или таймаута,
итог сохраняется в журнал и показывается на странице (раздел «Теневые»), с пометкой. Теневые позиции НЕ попадают на счёт: не занимают слоты,
не меняют баланс, не пишутся в orders.json / positions.json и не участвуют в самообучении порогов (tg_review, tg_corr, tg_learn). Только чтение их файлов.

Файлы в POS_DIR (пишет только tg_bot через этот модуль, остальные читают):
  shadow.json         {"seq": N, "items": [...]}   записи (открытые, закрытые, взятые в реальные ордера)
  shadow_paths.jsonl  по строке на закрытую позицию: ход цены по свечам 5m в R (для разбора и обучения)
  shadow_cfg.json     необязательно: {"enabled": true, "horizon": 48, "max_open": 30, "keep_closed": 500, "path": true}
Отключение: shadow_cfg.json {"enabled": false} или удалить файл (tg_bot подключает модуль через try/except).

Правила модели (единые, без подгонки): вход по рынку по плану вердикта (plan.entry) в момент отправки поста; считаются закрытые свечи 1m, начиная с первой после поста;
стоп и цель из плана вердикта; обе в одной свече 1m = стоп; гэп через стоп = выход по open свечи; таймаут horizon свечей таймфрейма сигнала (по умолчанию 48, не больше 72 ч) = выход по close;
комиссии как в pos.py: вход тейкер 0.05% + проскальзывание 0.02%; выход по цели лимитом 0.02%, по стопу и таймауту 0.05% + 0.02%. Правил сопровождения (БУ, частичное закрытие, трейлинг) здесь нет: по ходу цены
в shadow_paths.jsonl их можно проверять отдельно. Одна теневая позиция на пару и сторону одновременно (повторные «заходить» по той же паре, пока позиция открыта, не дублируются).
Если по этому слежению пользователь или Автоордер всё же поставил ордер (orders.json, src_watch = id слежения), запись получает статус taken и на странице не показывается."""
import json, os, threading, time, urllib.parse, urllib.request

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
F = os.path.join(D, "shadow.json"); PF = os.path.join(D, "shadow_paths.jsonl"); ORDF = os.path.join(D, "orders.json"); CFGF = os.path.join(D, "shadow_cfg.json")
KL = "https://data-api.binance.vision/api/v3/klines"
FEE = 0.05; FEE_LIM = 0.02; SLIP = 0.02           # % за сторону, как в pos.py (тейкер / лимит на цели / проскальзывание)
TFMS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
MAXH = 72 * 3600 * 1000
lock = threading.Lock()
DEF = {"enabled": True, "horizon": 48, "max_open": 30, "keep_closed": 500, "path": True}


def log(m): print(time.strftime("%H:%M:%S"), "shadow:", m, flush=True)


def cfg():
    c = dict(DEF)
    try: c.update(json.load(open(CFGF, encoding="utf-8")))
    except Exception: pass
    return c


def enabled(): return bool(cfg().get("enabled", True))


def _load():
    try:
        d = json.load(open(F, encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list): return d
    except Exception: pass
    return {"seq": 0, "items": []}


def _save(d):
    tmp = F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, F)


def _clean(x):
    try: return json.loads(json.dumps(x, ensure_ascii=False, default=str))
    except Exception: return None


def _f(x):
    try: return float(x)
    except Exception: return None


def _ceil_min(ms): return -(-int(ms) // 60000) * 60000


def record(w, V, Bk=None, mid=None, chat="main", now_ms=None):
    """Вызывается из tg_bot.send_watch после отправки поста, если мнение бота «заходить» и Автоордер ордер не ставит. Возвращает id записи или None."""
    try:
        c = cfg()
        if not c.get("enabled", True): return None
        kind, X = (None, None)
        if V and V.get("call") == "enter": kind, X = "bounce", V
        elif Bk and Bk.get("call") == "enter": kind, X = "break", Bk
        if not X: return None
        p = X.get("plan") or {}; side = p.get("side"); en, st, tp = _f(p.get("entry")), _f(p.get("stop")), _f(p.get("tp"))
        if side not in ("long", "short") or not (en and st and tp): return None
        risk = abs(en - st)
        if risk <= 0 or (side == "long" and not (st < en < tp)) or (side == "short" and not (tp < en < st)): return None
        sym = str(w.get("sym") or ""); tf = str(w.get("tf") or X.get("tf") or "5m")
        if not sym: return None
        now = int(now_ms or time.time() * 1000)
        with lock:
            d = _load(); its = d["items"]
            if any(i.get("status") == "open" and i.get("sym") == sym and i.get("side") == side for i in its): return None
            if sum(1 for i in its if i.get("status") == "open") >= int(c.get("max_open", 30)): return None
            d["seq"] = int(d.get("seq", 0)) + 1
            it = {"id": d["seq"], "sym": sym, "side": side, "kind": kind, "tf": tf, "wid": w.get("id"), "mid": mid, "chat": chat, "t_sig": X.get("t"), "t_in": now, "cur": _ceil_min(now),
                  "entry": en, "stop": st, "tp": tp, "risk": risk, "rr": p.get("rr"), "f": p.get("f"), "status": "open", "mfe": 0.0, "mae": 0.0, "n": 0,
                  "feat": _clean(X.get("feat")), "rows": _clean(X.get("rows")), "b1": _clean(X.get("b1")), "rg": _clean(X.get("rg")), "geo": _clean(X.get("geo")), "ch": _clean({k: v for k, v in (w.get("chan") or {}).items() if k in ("upper", "lower", "type")}), "fails": 0}
            its.append(it); _save(d)
        log("new #%s %s %s %s entry %s stop %s tp %s" % (it["id"], sym, side, kind, en, st, tp))
        return it["id"]
    except Exception as e:
        log("record error: %r" % e); return None


def _klines(sym, start, iv="1m", limit=1000):
    q = urllib.parse.urlencode({"symbol": sym + "USDT", "interval": iv, "startTime": int(start), "limit": limit})
    with urllib.request.urlopen(urllib.request.Request(KL + "?" + q, headers={"User-Agent": "tg-shadow"}), timeout=12) as r: return json.loads(r.read().decode("utf-8"))


def _net(it, ex, reason):
    s = 1 if it["side"] == "long" else -1
    gross = s * (ex / it["entry"] - 1) * 100
    fee = FEE + SLIP + (FEE_LIM if reason == "target" else FEE + SLIP)
    return gross - fee


def _close(it, ex, t, reason):
    net = _net(it, ex, reason); rp = it["risk"] / it["entry"] * 100
    it.update(status="closed", exit=ex, t_out=int(t), reason=reason, net_pct=round(net, 3), r_mult=round(net / rp, 3) if rp else None,
              mfe=round(it["mfe"], 2), mae=round(it["mae"], 2))


def _step(it, rows, now):
    """Обработать закрытые свечи 1m. Возвращает True, если запись изменилась."""
    s = 1 if it["side"] == "long" else -1; en, st, tp, risk = it["entry"], it["stop"], it["tp"], it["risk"]
    tf_ms = TFMS.get(it["tf"], 300000); t_end = it["t_in"] + min(int(cfg().get("horizon", 48)) * tf_ms, MAXH); ch = False
    for k in rows:
        t = int(k[0])
        if t + 60000 > now: break
        if t < it["cur"]: continue
        o, h, l, cl = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        it["cur"] = t + 60000; it["n"] += 1; ch = True
        fav = (h - en) / risk if s > 0 else (en - l) / risk; adv = (en - l) / risk if s > 0 else (h - en) / risk
        if fav > it["mfe"]: it["mfe"] = fav
        if adv > it["mae"]: it["mae"] = adv
        hit_s = (l <= st) if s > 0 else (h >= st); hit_t = (h >= tp) if s > 0 else (l <= tp)
        if hit_s:
            ex = min(o, st) if s > 0 else max(o, st)           # гэп через стоп: выход по open свечи
            _close(it, ex, t, "stop"); return True
        if hit_t: _close(it, tp, t, "target"); return True
        if t + 60000 >= t_end: _close(it, cl, t, "timeout"); return True
    return ch


def _path(it):
    """Ход цены в R по свечам 5m от входа до выхода: [[t, high_R, low_R, close_R], ...] (для всех теневых по одной строке в shadow_paths.jsonl)."""
    rows = _klines(it["sym"], it["t_in"] // 300000 * 300000, "5m", 1000); s = 1 if it["side"] == "long" else -1; en, risk = it["entry"], it["risk"]; out = []
    for k in rows:
        t = int(k[0])
        if t > it["t_out"]: break
        h, l, cl = float(k[2]), float(k[3]), float(k[4])
        out.append([t, round(((h if s > 0 else l) - en) * s / risk, 2), round(((l if s > 0 else h) - en) * s / risk, 2), round((cl - en) * s / risk, 2)])
    return out


def _orders():
    try: return json.load(open(ORDF, encoding="utf-8"))
    except Exception: return []


def run(limit=10):
    """Раз в ~минуту из tg_bot.outbox_loop: ведёт открытые теневые позиции, помечает взятые в реальный ордер, чистит старое. Возвращает список закрытых за этот проход."""
    c = cfg()
    if not c.get("enabled", True): return []
    with lock: d = _load()
    its = d["items"]; now = int(time.time() * 1000); done = []; touched = set(); removed = set(); ords = None
    for it in its:
        if it.get("status") in ("open", "closed") and not it.get("chk"):     # взято ли это слежение в реальный ордер (в течение 30 мин после сигнала)
            if now - it["t_in"] > 1800000: it["chk"] = 1; touched.add(it["id"])
            elif it.get("wid") is not None:
                if ords is None: ords = _orders()
                o = next((x for x in ords if x.get("src_watch") == it["wid"] and (x.get("approved_t") or 0) >= it["t_in"] - 120000), None)
                if o: it["status"] = "taken"; it["taken_oid"] = o.get("id"); it["chk"] = 1; touched.add(it["id"])
    n = 0
    for it in its:
        if it.get("status") != "open": continue
        if n >= limit: break
        n += 1
        try: rows = _klines(it["sym"], it["cur"])
        except Exception as e:
            it["fails"] = it.get("fails", 0) + 1; touched.add(it["id"])
            if it["fails"] >= 20 and now - it["t_in"] > 86400000: it["status"] = "void"; it["reason"] = "нет данных"
            continue
        if not isinstance(rows, list): continue
        it["fails"] = 0
        if _step(it, rows, now):
            touched.add(it["id"])
            if it.get("status") == "closed":
                if c.get("path", True):
                    try:
                        pth = _path(it)
                        with open(PF, "a", encoding="utf-8") as f: f.write(json.dumps({"id": it["id"], "sym": it["sym"], "side": it["side"], "kind": it["kind"], "tf": it["tf"], "t_in": it["t_in"], "t_out": it["t_out"], "entry": it["entry"], "risk": it["risk"],
                                                                                    "reason": it["reason"], "r": it["r_mult"], "step": 300000, "hlc": pth}, ensure_ascii=False, separators=(",", ":")) + "\n")
                    except Exception as e: log("path %s: %r" % (it["id"], e))
                done.append(dict(it)); log("closed #%s %s %s %s %s R" % (it["id"], it["sym"], it["side"], it["reason"], it.get("r_mult")))
    closed = sorted([i for i in its if i.get("status") == "closed"], key=lambda x: x.get("t_out", 0)); kc = int(c.get("keep_closed", 500))
    if len(closed) > kc: removed |= {i["id"] for i in closed[:len(closed) - kc]}
    removed |= {i["id"] for i in its if i.get("status") in ("taken", "void") and now - i["t_in"] > 7 * 86400000}
    if touched or removed:
        with lock:
            cur = _load(); mine = {i["id"]: i for i in its if i["id"] in touched}
            cur["items"] = [mine.get(i["id"], i) for i in cur["items"] if i["id"] not in removed]; _save(cur)     # записи, добавленные record() за время прохода, сохраняются
    return done


def stats(items=None):
    its = items if items is not None else _load()["items"]
    cl = [i for i in its if i.get("status") == "closed"]; op = [i for i in its if i.get("status") == "open"]
    def agg(xs):
        n = len(xs); w = sum(1 for i in xs if (i.get("net_pct") or 0) > 0); r = sum((i.get("r_mult") or 0) for i in xs)
        return {"n": n, "win": w, "R": round(r, 2), "avg": round(r / n, 2) if n else 0.0, "pct": round(sum((i.get("net_pct") or 0) for i in xs), 2)}
    out = {"open": len(op), "all": agg(cl)}
    for key in ("kind", "side", "reason"): out["by_" + key] = {v: agg([i for i in cl if i.get(key) == v]) for v in sorted({i.get(key) for i in cl if i.get(key)})}
    return out


def summary_text(last=8):
    d = _load(); s = stats(d["items"]); a = s["all"]
    if not a["n"] and not s["open"]: return "👻 Теневых позиций пока нет: сигналы «ЗАХОДИТЬ», по которым вы не открыли сделку, ведутся на бумаге и попадают сюда."
    L = ["👻 Теневые позиции (пропущенные сигналы «ЗАХОДИТЬ», на счёт не влияют)", "Открытых: %d · закрытых: %d · плюс %d / минус %d · итого %+.2f R (среднее %+.2f R, чистыми после комиссий)" % (s["open"], a["n"], a["win"], a["n"] - a["win"], a["R"], a["avg"])]
    for key, ru in (("by_kind", {"bounce": "отбой", "break": "пробой"}), ("by_side", {"long": "LONG", "short": "SHORT"}), ("by_reason", {"target": "цель", "stop": "стоп", "timeout": "таймаут"})):
        parts = ["%s %d (%+.2f R)" % (ru.get(k, k), v["n"], v["R"]) for k, v in s[key].items()]
        if parts: L.append(" · ".join(parts))
    cl = sorted([i for i in d["items"] if i.get("status") == "closed"], key=lambda x: x.get("t_out", 0), reverse=True)[:last]
    for i in cl: L.append("#%s %s %s %s: %s %+.2f R" % (i["id"], i["sym"], i["side"].upper(), {"bounce": "отбой", "break": "пробой"}.get(i["kind"], i["kind"]), {"target": "цель", "stop": "стоп", "timeout": "таймаут"}.get(i["reason"], i["reason"]), i.get("r_mult") or 0))
    L.append("Подробности и графики: страница онлайн, раздел «Теневые».")
    return "\n".join(L)
