# -*- coding: utf-8 -*-
"""Кэш минутных путей цены закрытых сделок счёта «Регрессия»: для каждой сделки 1m свечи Binance от 120 минут ДО входа до 6 часов ПОСЛЕ выхода.
Результат: /opt/trading-bot/cache/paths_regr.json.gz  {id: {sym, side, t_in, t_out, ks: [[t,o,h,l,c,v],...]}}; уже сохранённые сделки не качаются повторно (можно запускать снова).
Запуск на VPS: /opt/trading-bot/venv/bin/python paths_cache.py. Только чтение с публичного API Binance."""
import gzip, json, os, time, urllib.request, threading
from concurrent.futures import ThreadPoolExecutor

OUT = "/opt/trading-bot/cache/paths_regr.json.gz"
BASE = "https://data-api.binance.vision/api/v3/klines"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
have = {}
if os.path.exists(OUT):
    try: have = json.load(gzip.open(OUT, "rt"))
    except Exception: have = {}
lock = threading.Lock(); done = [0]


def fetch(sym, start, end):
    out = []; t = start
    while t < end and len(out) < 4000:
        u = "%s?symbol=%s&interval=1m&limit=1000&startTime=%d&endTime=%d" % (BASE, sym, t, end)
        d = None
        for i in range(5):
            try: d = json.load(urllib.request.urlopen(u, timeout=25)); break
            except Exception as e: time.sleep(1.5 * (i + 1))
        if not d: break
        out += [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in d]
        t = int(d[-1][0]) + 60000
        if len(d) < 1000: break
        time.sleep(0.2)
    return out


def job(p):
    key = str(p["id"])
    if key in have: return
    ks = fetch(p["sym"], p["t_in"] - 120 * 60000, p["t_out"] + 6 * 3600000)
    time.sleep(0.2)
    with lock:
        have[key] = {"sym": p["sym"], "side": p["side"], "t_in": p["t_in"], "t_out": p["t_out"], "ks": ks}; done[0] += 1
        if done[0] % 25 == 0:
            tmp = OUT + ".tmp"; json.dump(have, gzip.open(tmp, "wt")); os.replace(tmp, OUT); print("saved", len(have), flush=True)


todo = [p for p in snap["closed"] if p.get("t_in") and p.get("t_out")]
print("closed trades %d, already cached %d" % (len(todo), len(have)), flush=True)
with ThreadPoolExecutor(max_workers=4) as ex: list(ex.map(job, todo))
tmp = OUT + ".tmp"; json.dump(have, gzip.open(tmp, "wt")); os.replace(tmp, OUT)
print("DONE", len(have), os.path.getsize(OUT), "bytes", flush=True)
