# -*- coding: utf-8 -*-
"""Проверка цепочки управления ордером на VPS: WebSocket порта 18111 -> live_web -> acct-api -> chan_orders.manual_order. Шлёт действия по несуществующему ордеру 0: ожидается отказ «ордер не найден», ничего не меняется. Токен читается из token.txt и не печатается."""
import asyncio, json, aiohttp
TOK = open("/opt/trading-bot/live/token.txt").read().strip()
async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://127.0.0.1:18111/live/ws") as ws:
            await ws.send_str(json.dumps({"tok": TOK}))
            hello = json.loads((await asyncio.wait_for(ws.receive(), 10)).data)
            print("hello ctl=%s" % hello.get("ctl"))
            for i, q in enumerate(({"a": "ord_edit", "id": 0, "stop": 1.0}, {"a": "ord_cancel", "id": 0}, {"a": "ord_edit", "id": 0, "price": "x"})):
                await asyncio.sleep(1.0)
                await ws.send_str(json.dumps(dict({"q": "act", "rid": "t%d" % i}, **q)))
                while True:
                    m = json.loads((await asyncio.wait_for(ws.receive(), 15)).data)
                    if m.get("t") == "ack": print(q["a"], "ok=%s err=%s" % (m.get("ok"), str(m.get("err"))[:90])); break
asyncio.run(main())
