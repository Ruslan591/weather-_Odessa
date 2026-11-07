# -*- coding: utf-8 -*-
"""Бумажные позиции Claude (эксперимент пользователя): открыть позицию по рынку, дальше учёт по минутным свечам Binance.
Правила выхода (как в записи позиции): стоп, цель, безубыток с замком после +be_r R, трейлинг trail_atr x ATR1h от экстремума после БУ, выход по времени.
Внутри свечи порядок событий неизвестен: сначала проверяется стоп, потом цель; БУ и трейлинг применяются после свечи (консервативно).
Команды: open | update | status | loop. Данные: /opt/trading-bot/positions/positions.json. Реальных ордеров НЕ ставит."""
import argparse, contextlib, fcntl, json, os, sys, time, urllib.request
import exit_cfg   # патч 10: настройки выхода счёта (exit_cfg.json в каталоге счёта)
import decisions   # патч 11: журнал решений (decisions.jsonl в каталоге счёта)
D = os.environ.get("POS_DIR", "/opt/trading-bot/positions"); F = os.path.join(D, "positions.json")
FEE = 0.05; SLIP = 0.02          # % за сторону (комиссия) и проскальзывание на входе и на рыночных/стоповых выходах
BASE = "https://data-api.binance.vision/api/v3/klines"
START = 7.0; LEV = 5; STAKE = 6.0; LIQ = 19.6      # счёт как на вкладках 18091: старт 7 $, плечо 5x, изолированная маржа, позиция 6 $ (маржа 1.20 $), ликвидация около -19.6% против входа

@contextlib.contextmanager
def lock():
    os.makedirs(D, exist_ok=True)
    with open(os.path.join(D, "positions.lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)

def kl(sym, tf, limit=1000, start=None):
    u = "%s?symbol=%s&interval=%s&limit=%d" % (BASE, sym, tf, limit) + ("&startTime=%d" % start if start else "")
    return json.load(urllib.request.urlopen(u, timeout=20))
def load(): return json.load(open(F)) if os.path.exists(F) else []
def save(p):
    os.makedirs(D, exist_ok=True); tmp = F + ".tmp"; json.dump(p, open(tmp, "w"), ensure_ascii=False, indent=1); os.replace(tmp, F)
def tstr(ms): return time.strftime("%m-%d %H:%M", time.gmtime(ms / 1000)) + " UTC"
def atr1h(sym):
    d = kl(sym, "1h", 100); h = [float(x[2]) for x in d]; l = [float(x[3]) for x in d]; c = [float(x[4]) for x in d]; a = None
    for i in range(1, len(c)):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])); a = tr if a is None else a + (tr - a) / 14
    return a

def cmd_open(a):
    d = kl(a.sym, "1m", 2); px = float(d[-1][4]); now = int(time.time() * 1000)
    if a.zone and not (a.zone[0] <= px <= a.zone[1]):
        print("NO ENTRY: price %s outside zone %s" % (px, a.zone)); return 2
    side = 1 if a.side == "long" else -1
    entry = px * (1 + side * SLIP / 100)
    R = abs(entry - a.stop)
    if (side > 0 and a.stop >= entry) or (side < 0 and a.stop <= entry): print("bad stop"); return 3
    at = atr1h(a.sym)
    p = {"id": max([x["id"] for x in load()] + [0]) + 1, "sym": a.sym, "side": a.side, "t_in": now, "entry": entry, "px_signal": px,
         "stop0": a.stop, "stop": a.stop, "tp": a.tp, "R": R, "R_pct": R / entry * 100, "be_r": a.be_r, "lock_pct": a.lock,
         "be_px": entry + side * R * a.be_r, "lock_px": entry * (1 + side * a.lock / 100), "armed": False,
         "trail_dist": a.trail * at, "atr1h": at, "max_h": a.maxh, "stake": a.stake, "lev": LEV, "thesis": a.thesis,
         "last_t": (now // 60000) * 60000, "hi": entry, "lo": entry, "status": "open"}
    with lock():
        ps = load(); ps.append(p); save(ps)
    print("OPENED #%d %s %s entry %.6f (signal px %.6f) stop %.6f (R %.2f%%) tp %.6f be at %.6f lock %.6f trail %.6f" % (
        p["id"], a.sym, a.side, entry, px, a.stop, p["R_pct"], a.tp, p["be_px"], p["lock_px"], p["trail_dist"]))
    return 0

def fees(p, reason=None):
    """Комиссия круга, %: вход (fee_in, по умолчанию тейкер) + выход (цель лимитом fee_tp, иначе тейкер). Лимитные позиции chan_orders: 0.02 + 0.02 на цели, 0.02 + 0.05 на стопе."""
    return p.get("fee_in", FEE) + (p.get("fee_tp", FEE) if reason == "target" else FEE)

def close(p, px, t, reason, market):
    """Итог сделки с учётом частичных закрытий (p['parts'], доля остатка p['rem']): net = сумма вкладов частей + остаток; комиссия входа распределена по долям."""
    side = 1 if p["side"] == "long" else -1
    ex = px * (1 - side * SLIP / 100) if market else px
    rem = p.get("rem", 1.0); parts_c = sum(x["contrib_pct"] for x in p.get("parts", []))
    net = parts_c + rem * (side * (ex / p["entry"] - 1) * 100 - fees(p, reason))
    p.update(status="closed", t_out=t, exit=ex, reason=reason, net_pct=round(net, 3), r_mult=round(net / p["R_pct"], 3),
             pnl_usd=round(p["stake"] * net / 100, 3),
             mfe_pct=round((p["entry"] - p["lo"]) / p["entry"] * 100 if side < 0 else (p["hi"] - p["entry"]) / p["entry"] * 100, 3),
             mae_pct=round((p["hi"] - p["entry"]) / p["entry"] * 100 if side < 0 else (p["entry"] - p["lo"]) / p["entry"] * 100, 3))

def partial(p, px, t, frac, why):
    """Закрыть долю frac ИСХОДНОЙ позиции лимитом по px (комиссия выхода как у цели). Вклад в итог хранится в p['parts']."""
    side = 1 if p["side"] == "long" else -1; rem = p.get("rem", 1.0); frac = min(frac, rem)
    gross = side * (px / p["entry"] - 1) * 100
    contrib = frac * (gross - fees(p, "target"))
    p.setdefault("parts", []).append({"t": t, "px": px, "frac": round(frac, 6), "why": why, "contrib_pct": round(contrib, 5), "usd": round(p["stake"] * contrib / 100, 4)})
    p["rem"] = round(rem - frac, 6)

def step(p, k):
    t, o, h, l, c = int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])
    side = 1 if p["side"] == "long" else -1; stop = p["stop"]
    cfg = exit_cfg.load(); L = exit_cfg.levels(p, cfg)
    liq = p["entry"] * (1 - side * LIQ / 100)
    if (h >= liq) if side < 0 else (l <= liq):
        rem = p.get("rem", 1.0); parts_c = sum(x["contrib_pct"] for x in p.get("parts", []))
        close(p, liq, t + 60000, "liquidation", False); p["net_pct"] = round(parts_c + rem * (-100.0 / LEV), 3); p["pnl_usd"] = round(p["stake"] * p["net_pct"] / 100, 3); return
    hit = (h >= stop) if side < 0 else (l <= stop)
    if hit:
        gap = max(stop, o) if side < 0 else min(stop, o)
        close(p, gap, t + 60000, "stop" if not (p["armed"] or p.get("trail_act")) else "trail/BE", True); return
    reach = lambda px: (l <= px) if side < 0 else (h >= px)
    tp1 = L["tp1"]
    if tp1 is not None and not p.get("tp1_done") and reach(tp1):   # частичная цель: часть позиции лимитом, остаток дальше
        frac = cfg["tp1"]["part"] / 100.0
        partial(p, tp1, t + 60000, frac, "tp1"); p["tp1_done"] = True; p["tp1_t"] = t + 60000; decisions.auto(p, "tp1", None, tp1, t + 60000, c, frac=frac)
    if L["tp"] is not None and reach(L["tp"]):
        close(p, L["tp"], t + 60000, "target", False); return
    p["hi"] = max(p["hi"], h); p["lo"] = min(p["lo"], l)
    b = cfg["be"]
    if not p["armed"] and b["on"] and ((L["be_px"] is not None and reach(L["be_px"])) or (b["trig"] == "tp1" and p.get("tp1_done"))):
        _os = p["stop"]; p["armed"] = True; p["armed_t"] = t + 60000
        if not p.get("stop_manual"): p["stop"] = min(p["stop"], L["lock_px"]) if side < 0 else max(p["stop"], L["lock_px"])
        decisions.auto(p, "be", _os, p["stop"], t + 60000, c)
    tr = cfg["trail"]
    if not p.get("trail_act") and (tr["on"] or p.get("manual_trail")):
        st = tr["start"]
        if p.get("manual_trail") or (st == "be" and p["armed"]) or st == "now" or (st == "tp1" and p.get("tp1_done")) or (L["trail_px"] is not None and reach(L["trail_px"])):
            p["trail_act"] = True; p["trail_t"] = t + 60000; decisions.auto(p, "trail_start", p["stop"], p["stop"], t + 60000, c)
    if p.get("trail_act") and (tr["on"] or p.get("manual_trail")) and not p.get("stop_manual"):
        tl = p["lo"] + L["trail_dist"] if side < 0 else p["hi"] - L["trail_dist"]
        p["stop"] = min(p["stop"], tl) if side < 0 else max(p["stop"], tl)
    mh = cfg["maxh"] if cfg["maxh"] is not None else p["max_h"]
    if mh and (t + 60000 - p["t_in"]) / 3600000 >= mh: close(p, c, t + 60000, "time", True)

def cmd_update():
    with lock(): return _update()

def _update():
    ps = load(); changed = False; now = int(time.time() * 1000)
    for p in ps:
        if p["status"] != "open": continue
        while p["status"] == "open":
            d = kl(p["sym"], "1m", 1000, p["last_t"] + 60000)
            d = [k for k in d if int(k[0]) + 60000 <= now]
            if not d: break
            for k in d:
                step(p, k); p["last_t"] = int(k[0]); changed = True
                if p["status"] != "open": break
            if len(d) < 1000: break
    for p in ps:   # патч 6: после БУ стоп подтягивается на подтверждённую линию поддержки/сопротивления (sr_stop.py)
        if p["status"] == "open" and p.get("armed") and exit_cfg.load()["sr"]["on"]:
            try:
                import sr_stop
                _n0 = len(p.get("sr_hist", []))
                if sr_stop.apply(p, kl, now, lambda m: print(m, flush=True)): changed = True
                if len(p.get("sr_hist", [])) > _n0:
                    _h = p["sr_hist"][-1]; decisions.auto(p, "sr", _h.get("from"), _h.get("to"), now, _h.get("px"), level=_h.get("level"), touches=_h.get("touches"))
            except Exception as e: print("sr_stop err", p.get("sym"), e, flush=True)
    if changed: save(ps)
    return ps

def price(sym): return float(kl(sym, "1m", 1)[-1][4])

def _attach_chan(q):
    """Положить в открытую позицию из заявки: канал, опорные точки, уровень, пробой, время выставления; свечи 5m."""
    try:
        if q.get("src") != "chan": return
        o = json.load(open(os.path.join(D, "orders.json")))
        a = [x for x in o if x.get("id") == q.get("order_id")]
        if not a: return
        a = a[0]
        for k in ("chan", "basis", "level", "breakout", "placed_t", "expire_t", "ctype", "rule", "atr", "why"):
            if a.get(k) is not None: q["o_" + k] = a[k]
        q["cand"] = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(q["sym"], "5m", 300)]
        q["o_dt"] = 300000
    except Exception as e:
        q["o_err"] = str(e)[:80]

def _eff(p):
    L = exit_cfg.levels(p); L["liq"] = p["entry"] * (1 - (1 if p["side"] == "long" else -1) * LIQ / 100); L["atr1h"] = p.get("atr1h"); L["R"] = p["R"]; return L

def snapshot():
    ps = cmd_update(); opn = []; closed = []; realized = 0.0; unreal = 0.0; margin = 0.0
    for p in ps:
        side = 1 if p["side"] == "long" else -1
        if p["status"] == "open":
            px = price(p["sym"]); rem = p.get("rem", 1.0); u = sum(x["contrib_pct"] for x in p.get("parts", [])) + rem * (side * (px / p["entry"] - 1) * 100 - fees(p)); ud = p["stake"] * u / 100; m = p["stake"] / p.get("lev", LEV) * rem
            unreal += ud; margin += m
            q = dict(p); q.update(px=px, unreal_pct=round(u, 3), unreal_usd=round(ud, 3), r_now=round(u / p["R_pct"], 2), margin=m,
                                 liq_px=p["entry"] * (1 - side * LIQ / 100), trail_pct=round(exit_cfg.levels(p)["trail_dist"] / px * 100, 3), rem=rem, eff=_eff(p), tp=_eff(p)["tp"] if _eff(p)["tp"] is not None else p["tp"], be_px=_eff(p)["be_px"] if _eff(p)["be_px"] is not None else p["be_px"], cand=[[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(p["sym"], "15m", 300)])
            _attach_chan(q); opn.append(q)
        else:
            realized += p.get("pnl_usd", 0.0); closed.append(p)
    closed.sort(key=lambda p: -p["t_out"])
    return {"account": {"start": START, "lev": LEV, "stake": STAKE, "margin": STAKE / LEV, "realized": round(realized, 3), "unreal": round(unreal, 3),
                        "equity": round(START + realized + unreal, 3), "free": round(START + realized - margin, 3), "open_margin": round(margin, 3), "closed": len(closed)},
            "open": opn, "closed": closed, "journal": decisions.summary(), "exit_cfg": exit_cfg.load(), "exit_default": exit_cfg.DEFAULT, "orders": _orders(), "shadow": _shadow(), "miss": _miss(), "ts": int(time.time() * 1000)}

def _orders():
    try:
        import chan_orders
        return chan_orders.orders_view()
    except Exception as e:
        return {"pending": [], "recent": [], "error": str(e)}

def _miss():   # патч 9
    try:
        import chan_orders
        return chan_orders.miss_summary()
    except Exception as e:
        return None

def _shadow():   # патч 8
    try:
        import chan_orders
        return chan_orders.shadow_summary()
    except Exception as e:
        return None

def _apply_stop():
    """Применить режим стопа (pct|atr) к ОТКРЫТЫМ позициям, которые ещё не в БУ, без частичной цели и без ручного стопа: новый начальный стоп на расстоянии от входа, пересчёт R."""
    c = exit_cfg.load()
    if c["stop"]["mode"] == "rule": return {"error": "режим стопа «как в заявке»: менять нечего"}
    ps = _update(); n = 0; now = int(time.time() * 1000)
    for p in ps:
        if p["status"] != "open" or p.get("armed") or p.get("tp1_done") or p.get("stop_manual"): continue
        side = 1 if p["side"] == "long" else -1; ns = exit_cfg.stop_at_fill(c, side, p["entry"], p.get("atr1h") or 0.0, p["stop0"])
        if not ns or (side > 0 and ns >= p["entry"]) or (side < 0 and ns <= p["entry"]): continue
        px = price(p["sym"])
        if (side > 0 and ns >= px) or (side < 0 and ns <= px): continue   # цена уже за новым стопом: не трогаем
        old = p["stop"]; R = abs(p["entry"] - ns); p.update(stop=ns, stop0=ns, R=R, R_pct=R / p["entry"] * 100, be_px=p["entry"] + side * R * p.get("be_r", 1.0)); n += 1
        p.setdefault("stop_hist", []).append({"t": now, "from": old, "to": ns, "by": "exit_cfg"})
    save(ps); r = snapshot(); r["applied"] = n; return r

def api_action(o):
    if o.get("action") == "chart":
        try:
            import chan_orders
            return chan_orders.pair_view(o.get("sym"))
        except Exception as e:
            return {"error": str(e)}
    if o.get("action") == "miss_chart":   # патч 9
        try:
            import chan_orders
            return chan_orders.miss_view(int(o.get("id", 0)))
        except Exception as e:
            return {"error": str(e)}
    if o.get("action") == "closed_chart":   # патч 8
        try:
            import chan_orders
            return chan_orders.closed_view(int(o.get("id", 0)))
        except Exception as e:
            return {"error": str(e)}
    act = o.get("action")
    if act in ("exit_cfg_set", "exit_cfg_reset", "exit_apply_stop"):   # патч 10
        with lock():
            if act == "exit_cfg_reset": exit_cfg.save(exit_cfg.DEFAULT_COPY())
            elif act == "exit_cfg_set":
                c, err = exit_cfg.validate(o.get("cfg"))
                if err: return {"error": err}
                exit_cfg.save(c)
            else: return _apply_stop()
        return snapshot()
    if act == "journal_get":   # патч 11: выгрузка журнала (full=1 - со свечами и уровнями)
        rows = decisions.all_rows(5000, int(o["id"]) if o.get("id") else None)
        if not o.get("full"): rows = [{k: v for k, v in r.items() if k not in decisions.BIG} for r in rows]
        return {"rows": rows, "n": len(rows)}
    pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)
    with lock():
        ps = _update(); p = next((x for x in ps if x["id"] == pid and x["status"] == "open"), None)   # патч 7: сначала догоняем свечи до «сейчас»
        if not p: return {"error": "позиция не найдена или уже закрыта"}
        side = 1 if p["side"] == "long" else -1; px = price(p["sym"]); now = int(time.time() * 1000)
        if act == "close":
            decisions.manual(p, px, kl, "close", p["stop"], px, o)
            close(p, px, now, "manual", True)
        elif act == "stop":   # патч 7: вводится ЦЕНА стопа
            try: sp = float(str(o.get("price", "")).replace(",", "."))
            except Exception: return {"error": "укажите цену стопа числом"}
            liq = p["entry"] * (1 - side * LIQ / 100)
            if side > 0 and not (liq < sp < px * 0.9998): return {"error": "лонг: стоп должен быть ниже текущей цены %.8g и выше ликвидации %.8g" % (px, liq)}
            if side < 0 and not (px * 1.0002 < sp < liq): return {"error": "шорт: стоп должен быть выше текущей цены %.8g и ниже ликвидации %.8g" % (px, liq)}
            old = p["stop"]; p["stop"] = sp; p["stop_manual"] = True; p["stop_manual_t"] = now; p["manual_stop_px"] = sp; p.pop("manual_stop", None); p.pop("manual_trail", None)
            p.setdefault("stop_hist", []).append({"t": now, "from": old, "to": sp, "by": "manual"})
            decisions.manual(p, px, kl, "stop", old, sp, o)
        elif act == "tp":   # патч 11: ручная цена цели (лимит), главнее настроек выхода
            try: tg = float(str(o.get("price", "")).replace(",", "."))
            except Exception: return {"error": "укажите цену цели числом"}
            if side > 0 and not (tg > px * 1.0002): return {"error": "лонг: цель должна быть выше текущей цены %.8g" % px}
            if side < 0 and not (tg < px * 0.9998): return {"error": "шорт: цель должна быть ниже текущей цены %.8g" % px}
            old = exit_cfg.levels(p)["tp"]; p["tp_manual"] = tg; p["tp_manual_t"] = now
            p.setdefault("tp_hist", []).append({"t": now, "from": old, "to": tg, "by": "manual"})
            decisions.manual(p, px, kl, "tp", old, tg, o)
        elif act == "tp_auto":
            old = p.get("tp_manual"); p.pop("tp_manual", None); p.pop("tp_manual_t", None)
            decisions.manual(p, px, kl, "tp_release", old, exit_cfg.levels(p)["tp"], o)
        elif act == "auto":
            decisions.manual(p, px, kl, "release", p["stop"], p["stop"], o)
            p.pop("stop_manual", None); p.pop("manual_stop_px", None)
        elif act == "trail":
            if not (0.05 <= pct <= 20): return {"error": "расстояние трейлинга от 0.05 до 20 %"}
            dist = px * pct / 100
            if True:
                p.pop("stop_manual", None); p.pop("manual_stop_px", None)
                _os = p["stop"]; p["trail_dist"] = dist; p["armed"] = True; p["manual_trail"] = round(pct, 3)
                p["hi"] = max(p["hi"], px); p["lo"] = min(p["lo"], px)
                tr = p["lo"] + dist if side < 0 else p["hi"] - dist
                p["stop"] = min(p["stop"], tr) if side < 0 else max(p["stop"], tr)
                decisions.manual(p, px, kl, "trail", _os, p["stop"], o, pct=pct)
        else: return {"error": "неизвестное действие"}
        save(ps)
    return snapshot()

def cmd_status():
    ps = cmd_update()
    for p in ps:
        if p["status"] == "open":
            px = float(kl(p["sym"], "1m", 1)[-1][4]); side = 1 if p["side"] == "long" else -1
            print("#%d OPEN %s %s since %s entry %.6f now %.6f unreal %.2f%% (%.2fR) stop %.6f%s tp %.6f" % (
                p["id"], p["sym"], p["side"], tstr(p["t_in"]), p["entry"], px, side * (px / p["entry"] - 1) * 100 - fees(p),
                (side * (px / p["entry"] - 1) * 100 - fees(p)) / p["R_pct"], p["stop"], " (BE armed)" if p["armed"] else "", p["tp"]))
        else:
            print("#%d CLOSED %s %s %s -> %s exit %.6f %s net %.2f%% (%.2fR) MFE %.2f%% MAE %.2f%%" % (
                p["id"], p["sym"], p["side"], tstr(p["t_in"]), tstr(p["t_out"]), p["exit"], p["reason"], p["net_pct"], p["r_mult"], p["mfe_pct"], p["mae_pct"]))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["open", "update", "status", "loop"])
    ap.add_argument("sym", nargs="?"); ap.add_argument("side", nargs="?", choices=["long", "short"]); ap.add_argument("stop", nargs="?", type=float); ap.add_argument("tp", nargs="?", type=float)
    ap.add_argument("--be-r", dest="be_r", type=float, default=1.0); ap.add_argument("--lock", type=float, default=0.2); ap.add_argument("--trail", type=float, default=1.5)
    ap.add_argument("--maxh", type=float, default=72); ap.add_argument("--stake", type=float, default=STAKE); ap.add_argument("--thesis", default=""); ap.add_argument("--zone", type=float, nargs=2)
    a = ap.parse_args()
    if a.cmd == "open": sys.exit(cmd_open(a))
    elif a.cmd == "update": cmd_update()
    elif a.cmd == "status": cmd_status()
    else:
        while True:
            try: cmd_update()
            except Exception as e: print("err", e, flush=True)
            time.sleep(30)
