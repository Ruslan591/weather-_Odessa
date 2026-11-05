# -*- coding: utf-8 -*-
"""Микро-API счёта «Claude» для параллельных счетов (AFD / Регрессия / Комбо). Запуск: POS_DIR=<каталог счёта> CHAN_SRC=<afd|regr|combo> ACCT_PORT=<порт> python acct_api.py
GET /api/claude -> pos.snapshot(); POST /api/claude {action,...} -> pos.api_action(o). Слушает только 127.0.0.1; панель 18091 пересылает сюда запросы с ?acct=<имя>."""
import os, sys, asyncio
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from aiohttp import web
import pos
# Быстрые свечи для снимка: одно keep-alive соединение + кэш 20 с (без этого каждый запрос тратит ~1.3 с на TLS, снимок с 3 позициями = 15 с). Только в этом процессе.
import json, threading, time, http.client
_kc = {}; _kl = threading.Lock(); _kconn = [None]
def _fast_kl(sym, tf, limit=1000, start=None):
    key = (sym, tf, limit, start); now = time.time()
    with _kl:
        c = _kc.get(key)
        if c and now - c[0] < 20: return c[1]
        path = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (sym, tf, limit) + ("&startTime=%d" % start if start else "")
        d = None
        for attempt in (1, 2):
            try:
                if _kconn[0] is None: _kconn[0] = http.client.HTTPSConnection("data-api.binance.vision", timeout=20)
                _kconn[0].request("GET", path); r = _kconn[0].getresponse(); body = r.read()
                if r.status != 200: raise RuntimeError("klines HTTP %d" % r.status)
                d = json.loads(body); break
            except Exception:
                try: _kconn[0].close()
                except Exception: pass
                _kconn[0] = None
                if attempt == 2: raise
        _kc[key] = (now, d)
        if len(_kc) > 300:
            for k in [k for k, v in _kc.items() if now - v[0] > 60]: _kc.pop(k, None)
        return d
pos.kl = _fast_kl
async def api(req):
    loop = asyncio.get_running_loop()
    try:
        if req.method == "POST":
            o = await req.json(); res = await loop.run_in_executor(None, pos.api_action, o)
        else:
            res = await loop.run_in_executor(None, pos.snapshot)
    except Exception as e:
        res = {"error": str(e)}
    return web.json_response(res)
app = web.Application(); app.router.add_route("*", "/api/claude", api)
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=int(os.environ.get("ACCT_PORT", "18101")), print=None)
