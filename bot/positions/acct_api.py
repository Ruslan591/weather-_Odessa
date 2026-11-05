# -*- coding: utf-8 -*-
"""Микро-API счёта «Claude» для параллельных счетов (AFD / Регрессия / Комбо). Запуск: POS_DIR=<каталог счёта> CHAN_SRC=<afd|regr|combo> ACCT_PORT=<порт> python acct_api.py
GET /api/claude -> pos.snapshot(); POST /api/claude {action,...} -> pos.api_action(o). Слушает только 127.0.0.1; панель 18091 пересылает сюда запросы с ?acct=<имя>."""
import os, sys, asyncio
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from aiohttp import web
import pos
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
