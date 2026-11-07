# -*- coding: utf-8 -*-
"""tg_hello.py: тестовое сообщение пользователю (токен и chat id берутся из tg.env, нигде не печатаются)."""
import json, urllib.request, urllib.parse
env = {}
for ln in open("/opt/trading-bot/tg.env", encoding="utf-8"):
    if "=" in ln: k, v = ln.strip().split("=", 1); env[k] = v
d = urllib.parse.urlencode({"chat_id": env["TG_CHAT_ID"], "text": "Связь с ботом установлена. Это тестовое сообщение от системы «Регрессия». Дальше пришлю пример графика ордера."}).encode()
r = json.load(urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % env["TG_TOKEN"], data=d, timeout=20))
print("sent:", r.get("ok"))
