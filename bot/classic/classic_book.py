#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classic_book.py — запись стакана Binance (спот, как и свечи классики) по парам классики: раз в 30 с на пару.
В book.db (snap): ts, sym, mid, bid1, ask1, walls (JSON: стенки), prof (JSON: профиль глубины). Стенки — для графика позиции (панель 18091), профиль — для разбора позже.
Стенка = окно 6 б.п. от середины, чья сумма (USDT) >= 3 x типичного окна этой пары в этот момент (медиана непустых окон), локальный максимум в +-2 окна; не больше 5 с каждой стороны.
Пары: pairs.json + активные прогоны (runs.json). Запуск: python3 classic_book.py [--once]. Хранение 30 дней."""
import json, os, sqlite3, sys, time, urllib.request, urllib.error, statistics

DIR = os.environ.get("CLASSIC_DIR", "/opt/trading-bot/classic")
DB = os.path.join(DIR, "book.db")
BASE = "https://api.binance.com"
INTERVAL, LIMIT, WIN_BPS, NBINS, MINMULT, KEEP_DAYS = 30, 500, 6.0, 50, 3.0, 30


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def pairs():
    s = set()
    try:
        s |= set(json.load(open(os.path.join(DIR, "pairs.json"))))
    except Exception:
        pass
    try:
        for r in json.load(open(os.path.join(DIR, "runs.json"))):
            if r.get("stop_ms") is None and r.get("sym"):
                s.add(r["sym"])
    except Exception:
        pass
    return sorted(s)


def fetch(sym):
    req = urllib.request.Request("%s/api/v3/depth?symbol=%s&limit=%d" % (BASE, sym, LIMIT), headers={"User-Agent": "classic-book/1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        w = int(r.headers.get("x-mbx-used-weight-1m") or 0)
        return json.load(r), w


def analyse(d):
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    if not bids or not asks:
        return None
    b1, a1 = bids[0][0], asks[0][0]
    mid = (b1 + a1) / 2
    res = {"mid": mid, "bid1": b1, "ask1": a1}
    walls, prof = [], {}
    for side, lv in (("b", bids), ("a", asks)):
        cov = abs(lv[-1][0] - mid) / mid * 1e4  # покрытие глубины, б.п.
        nb = max(0, min(NBINS, int(cov // WIN_BPS)))  # только полностью покрытые окна
        sums, pw = [0.0] * NBINS, [0.0] * NBINS
        for p, q in lv:
            k = int(abs(p - mid) / mid * 1e4 // WIN_BPS)
            if k < nb:
                sums[k] += p * q; pw[k] += p * p * q
        pos = [x for x in sums[:nb] if x > 0]
        prof[side] = [int(round(x)) for x in sums]
        if len(pos) < 8:
            continue
        typ = statistics.median(pos)
        cand = []
        for k in range(nb):
            if sums[k] >= MINMULT * typ and sums[k] >= max(sums[max(0, k - 2):k + 3]):
                cand.append((sums[k], k))
        for v, k in sorted(cand, reverse=True)[:5]:
            walls.append({"s": side, "p": 0.0, "v": int(round(v)), "m": round(v / typ, 1), "d": round((k + 0.5) * WIN_BPS, 1)})
            # цена окна — взвешенная по объёму: sum(p*p*q)/sum(p*q)
            walls[-1]["p"] = float("%.8g" % (pw[k] / v))
    res["walls"], res["prof"] = walls, prof
    return res


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS snap(ts INTEGER, sym TEXT, mid REAL, bid1 REAL, ask1 REAL, walls TEXT, prof TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS i_snap ON snap(sym, ts)")
    return c


def cycle(c):
    n = 0
    for sym in pairs():
        t0 = time.time()
        try:
            d, w = fetch(sym)
            a = analyse(d)
            if a:
                c.execute("INSERT INTO snap VALUES(?,?,?,?,?,?,?)", (int(time.time() * 1000), sym, a["mid"], a["bid1"], a["ask1"], json.dumps(a["walls"]), json.dumps(a["prof"], separators=(",", ":"))))
                n += 1
            if w > 4000:
                log("вес запросов", w, "— пауза 30 с"); time.sleep(30)
        except urllib.error.HTTPError as e:
            log(sym, "HTTP", e.code)
            if e.code in (418, 429):
                time.sleep(int(e.headers.get("Retry-After") or 60)); 
        except Exception as e:
            log(sym, "ошибка", repr(e)[:120])
        time.sleep(max(0.0, 0.4 - (time.time() - t0)))
    c.commit()
    return n


def main():
    c = db(); last_prune = 0
    while True:
        t0 = time.time()
        n = cycle(c)
        if time.time() - last_prune > 3600:
            c.execute("DELETE FROM snap WHERE ts < ?", (int((time.time() - KEEP_DAYS * 86400) * 1000),)); c.commit(); last_prune = time.time()
        if "--once" in sys.argv:
            log("снимков", n); return
        time.sleep(max(1.0, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
