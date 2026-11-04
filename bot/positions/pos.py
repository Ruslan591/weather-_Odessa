# -*- coding: utf-8 -*-
"""Бумажные позиции Claude (эксперимент пользователя): открыть позицию по рынку, дальше учёт по минутным свечам Binance.
Правила выхода (как в записи позиции): стоп, цель, безубыток с замком после +be_r R, трейлинг trail_atr x ATR1h от экстремума после БУ, выход по времени.
Внутри свечи порядок событий неизвестен: сначала проверяется стоп, потом цель; БУ и трейлинг применяются после свечи (консервативно).
Команды: open | update | status | loop. Данные: /opt/trading-bot/positions/positions.json. Реальных ордеров НЕ ставит."""
import argparse, contextlib, fcntl, json, os, sys, time, urllib.request
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
    side = 1 if p["side"] == "long" else -1
    ex = px * (1 - side * SLIP / 100) if market else px
    net = side * (ex / p["entry"] - 1) * 100 - fees(p, reason)
    p.update(status="closed", t_out=t, exit=ex, reason=reason, net_pct=round(net, 3), r_mult=round(net / p["R_pct"], 3),
             pnl_usd=round(p["stake"] * net / 100, 3),
             mfe_pct=round((p["entry"] - p["lo"]) / p["entry"] * 100 if side < 0 else (p["hi"] - p["entry"]) / p["entry"] * 100, 3),
             mae_pct=round((p["hi"] - p["entry"]) / p["entry"] * 100 if side < 0 else (p["entry"] - p["lo"]) / p["entry"] * 100, 3))

def step(p, k):
    t, o, h, l, c = int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])
    side = 1 if p["side"] == "long" else -1; stop = p["stop"]
    liq = p["entry"] * (1 - side * LIQ / 100)
    if (h >= liq) if side < 0 else (l <= liq):
        close(p, liq, t + 60000, "liquidation", False); p["net_pct"] = -100.0 / LEV; p["pnl_usd"] = round(-p["stake"] / LEV, 3); return
    hit = (h >= stop) if side < 0 else (l <= stop)
    if hit:
        gap = max(stop, o) if side < 0 else min(stop, o)
        close(p, gap, t + 60000, "stop" if not p["armed"] else "trail/BE", True); return
    if (l <= p["tp"]) if side < 0 else (h >= p["tp"]):
        close(p, p["tp"], t + 60000, "target", False); return
    p["hi"] = max(p["hi"], h); p["lo"] = min(p["lo"], l)
    if not p["armed"] and ((l <= p["be_px"]) if side < 0 else (h >= p["be_px"])):
        p["armed"] = True; p["stop"] = min(p["stop"], p["lock_px"]) if side < 0 else max(p["stop"], p["lock_px"]); p["armed_t"] = t + 60000
    if p["armed"]:
        tr = p["lo"] + p["trail_dist"] if side < 0 else p["hi"] - p["trail_dist"]
        p["stop"] = min(p["stop"], tr) if side < 0 else max(p["stop"], tr)
    if p["max_h"] and (t + 60000 - p["t_in"]) / 3600000 >= p["max_h"]: close(p, c, t + 60000, "time", True)

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
    if changed: save(ps)
    return ps

def price(sym): return float(kl(sym, "1m", 1)[-1][4])

def snapshot():
    ps = cmd_update(); opn = []; closed = []; realized = 0.0; unreal = 0.0; margin = 0.0
    for p in ps:
        side = 1 if p["side"] == "long" else -1
        if p["status"] == "open":
            px = price(p["sym"]); u = side * (px / p["entry"] - 1) * 100 - fees(p); ud = p["stake"] * u / 100; m = p["stake"] / p.get("lev", LEV)
            unreal += ud; margin += m
            q = dict(p); q.update(px=px, unreal_pct=round(u, 3), unreal_usd=round(ud, 3), r_now=round(u / p["R_pct"], 2), margin=m,
                                 liq_px=p["entry"] * (1 - side * LIQ / 100), trail_pct=round(p["trail_dist"] / px * 100, 3), cand=[[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(p["sym"], "15m", 300)])
            opn.append(q)
        else:
            realized += p.get("pnl_usd", 0.0); closed.append(p)
    closed.sort(key=lambda p: -p["t_out"])
    return {"account": {"start": START, "lev": LEV, "stake": STAKE, "margin": STAKE / LEV, "realized": round(realized, 3), "unreal": round(unreal, 3),
                        "equity": round(START + realized + unreal, 3), "free": round(START + realized - margin, 3), "open_margin": round(margin, 3), "closed": len(closed)},
            "open": opn, "closed": closed, "orders": _orders(), "ts": int(time.time() * 1000)}

def _orders():
    try:
        import chan_orders
        return chan_orders.orders_view()
    except Exception as e:
        return {"pending": [], "recent": [], "error": str(e)}

def api_action(o):
    if o.get("action") == "chart":
        try:
            import chan_orders
            return chan_orders.pair_view(o.get("sym"))
        except Exception as e:
            return {"error": str(e)}
    act = o.get("action"); pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)
    with lock():
        ps = load(); p = next((x for x in ps if x["id"] == pid and x["status"] == "open"), None)
        if not p: return {"error": "позиция не найдена или уже закрыта"}
        side = 1 if p["side"] == "long" else -1; px = price(p["sym"]); now = int(time.time() * 1000)
        if act == "close":
            close(p, px, now, "manual", True)
        elif act in ("stop", "trail"):
            if not (0.05 <= pct <= 20): return {"error": "расстояние от 0.05 до 20 %"}
            dist = px * pct / 100
            new_stop = px - side * dist                                   # лонг: ниже цены, шорт: выше цены
            if act == "stop":
                p["stop"] = new_stop; p["manual_stop"] = round(pct, 3)
            else:
                p["trail_dist"] = dist; p["armed"] = True; p["manual_trail"] = round(pct, 3)
                p["hi"] = max(p["hi"], px); p["lo"] = min(p["lo"], px)
                tr = p["lo"] + dist if side < 0 else p["hi"] - dist
                p["stop"] = min(p["stop"], tr) if side < 0 else max(p["stop"], tr)
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
