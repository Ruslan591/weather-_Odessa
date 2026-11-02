# -*- coding: utf-8 -*-
"""Ожидатель входов для бумажных позиций Claude (правила R1-R4 из docs/topics/bot_positions.md).
Правила заданы ДО запуска и не подгоняются. Открывает позицию через pos.py open, когда на закрытой свече 15m выполнен триггер.
Запуск: python pos_watch.py [--dry] [--once]. Журнал: watch.log, состояние: watch_state.json. Реальных ордеров не ставит."""
import json, os, sys, time, subprocess, calendar
D = "/opt/trading-bot/positions"; sys.path.insert(0, D)
import pos
SHORT = "XRP DOGE ADA DOT APT ATOM SOL LINK AVAX SUI LTC BNB ETH".split(); LONG = ["HAEDAL"]
COUNTER = "BTC ETH SOL XRP DOGE ADA BNB LINK AVAX SUI LTC DOT".split()   # лонг против тренда: только пробой максимума 24 ч; не больше одной такой позиции
EXPIRE = calendar.timegm((2026, 11, 4, 22, 0, 0)) * 1000
MAXOPEN = 3; RISK_CAP = 1.5; TP_R = 3.0; MAXH = 24
ST = os.path.join(D, "watch_state.json"); LOG = os.path.join(D, "watch.log")
DRY = "--dry" in sys.argv; ONCE = "--once" in sys.argv
def log(m):
    s = time.strftime("%m-%d %H:%M:%S", time.gmtime()) + " " + m
    print(s, flush=True)
    open(LOG, "a").write(s + "\n")
def ema(v, n):
    k = 2 / (n + 1); e = v[0]; o = []
    for x in v: e = x * k + e * (1 - k); o.append(e)
    return o
def atr(h, l, c, n=14):
    a = None
    for i in range(1, len(c)):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])); a = tr if a is None else a + (tr - a) / n
    return a
def score(d):
    c = [float(x[4]) for x in d[:-1]]; e20 = ema(c, 20); e50 = ema(c, 50); e200 = ema(c, 200)
    return (1 if c[-1] > e50[-1] else -1) + (1 if e20[-1] > e50[-1] else -1) + (1 if e50[-1] > e50[-6] else -1) + (1 if e50[-1] > e200[-1] else -1)
def load_state():
    return json.load(open(ST)) if os.path.exists(ST) else {}
def check(sym, side, st, counter=False, key=None):
    s2 = sym + "USDT"; now = int(time.time() * 1000)
    d15 = pos.kl(s2, "15m", 250)
    d15 = [k for k in d15 if int(k[0]) + 900000 <= now]
    t = int(d15[-1][0])
    key = key or sym
    if st.get(key) == t: return None
    st[key] = t
    d1 = pos.kl(s2, "1h", 260)[:-1] if False else pos.kl(s2, "1h", 260); d4 = pos.kl(s2, "4h", 260)
    s4 = score(d4); s1 = score(d1)
    sgn = -1 if side == "short" else 1
    if not counter and (s4 * sgn < 2 or s1 * sgn < 2): return ("no-trend", s4, s1)
    h1 = [float(x[2]) for x in d1[:-1]]; l1 = [float(x[3]) for x in d1[:-1]]; c1 = [float(x[4]) for x in d1[:-1]]
    a1 = atr(h1, l1, c1); e20h = ema(c1, 20)[-1]
    o = [float(x[1]) for x in d15]; h = [float(x[2]) for x in d15]; l = [float(x[3]) for x in d15]; c = [float(x[4]) for x in d15]
    e15 = ema(c, 20); i = len(c) - 1; px = c[i]
    bear = c[i] < o[i]; bull = c[i] > o[i]
    trig = None
    if side == "short":
        touch = any(h[j] >= e20h for j in range(i - 5, i + 1))
        cross = c[i] < e15[i] and c[i - 1] >= e15[i - 1]
        if touch and bear and cross: trig = "retest"
        brk = c[i] < min(l[i - 96:i]) and bear and (e20h - px) / a1 <= 3.0
        if brk: trig = "break"
        stop = max(h[i - 7:i + 1]) + 0.25 * a1
        risk = (stop / px - 1) * 100
    else:
        touch = any(l[j] <= e20h for j in range(i - 5, i + 1))
        cross = c[i] > e15[i] and c[i - 1] <= e15[i - 1]
        if touch and bull and cross and not counter: trig = "retest"
        brk = c[i] > max(h[i - 96:i]) and bull and (px - e20h) / a1 <= 3.0
        if brk: trig = "break-counter" if counter else "break"
        stop = min(l[i - 7:i + 1]) - 0.25 * a1
        risk = (1 - stop / px) * 100
    if not trig: return ("no-trigger", s4, s1, round(px, 8), round(e20h, 8))
    return (trig, s4, s1, px, stop, risk, a1)
def open_count():
    return len([p for p in pos.load() if p["status"] == "open"])
def main():
    st = load_state(); log("watch start dry=%s expire=%s" % (DRY, time.strftime("%m-%d %H:%M", time.gmtime(EXPIRE / 1000))))
    while True:
        if int(time.time() * 1000) > EXPIRE: log("expired, stop"); return
        for sym, side, cnt in [(x, "short", False) for x in SHORT] + [(x, "long", False) for x in LONG] + [(x, "long", True) for x in COUNTER]:
            key = sym + ("_c" if cnt else "")
            try:
                r = check(sym, side, st, cnt, key)
            except Exception as e:
                log("err %s %s" % (sym, e)); continue
            if not r or r[0] in ("no-trend", "no-trigger"):
                if r and ONCE: log("%s %s: %s %s" % (sym, side, r[0], r[1:]))
                continue
            trig, s4, s1, px, stop, risk, a1 = r
            tp = px + (px - stop) * TP_R if side == "long" else px - (stop - px) * TP_R
            msg = "%s %s trigger=%s px=%.8g stop=%.8g risk=%.2f%% tp=%.8g score4h=%d 1h=%d" % (sym, side, trig, px, stop, risk, tp, s4, s1)
            if risk > RISK_CAP: log("SKIP risk>cap: " + msg); continue
            if any(p["sym"] == sym + "USDT" and p["status"] == "open" for p in pos.load()): log("SKIP already open: " + msg); continue
            if cnt and any(p["status"] == "open" and "COUNTER" in p.get("thesis", "") for p in pos.load()): log("SKIP counter already open: " + msg); continue
            if open_count() >= MAXOPEN: log("SKIP max open: " + msg); continue
            log(("DRY " if DRY else "") + "OPEN " + msg)
            if DRY: continue
            th = ("COUNTER-TREND " if cnt else "") + "auto %s %s: 4h/1h trend %d/%d, 15m confirmed; stop behind 8-candle structure +0.25 ATR1h; target %.0fR; maxh %d" % (trig, side, s4, s1, TP_R, MAXH)
            r2 = subprocess.run([sys.executable, os.path.join(D, "pos.py"), "open", sym + "USDT", side, "%.8g" % stop, "%.8g" % tp, "--maxh", str(MAXH), "--thesis", th], capture_output=True, text=True)
            log("pos.py: " + (r2.stdout + r2.stderr).strip())
        json.dump(st, open(ST, "w"))
        if ONCE: return
        time.sleep(60)
if __name__ == "__main__": main()
