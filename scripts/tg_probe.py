# -*- coding: utf-8 -*-
"""tg_probe.py: проверка токена Telegram (getMe) и поиск чата пользователя по /start. Секреты и id НЕ печатает, chat/user id дописывает в tg.env."""
import json, urllib.request, urllib.parse
P = "/opt/trading-bot/tg.env"
env = {}
for ln in open(P, encoding="utf-8"):
    if "=" in ln: k, v = ln.strip().split("=", 1); env[k] = v
tok = env.get("TG_TOKEN", "")
def api(m, **kw):
    u = "https://api.telegram.org/bot%s/%s" % (tok, m)
    if kw: u += "?" + urllib.parse.urlencode(kw)
    return json.load(urllib.request.urlopen(u, timeout=20))
me = api("getMe")
print("getMe ok:", me.get("ok"), "bot username:", me.get("result", {}).get("username"))
ups = api("getUpdates", timeout=0).get("result", [])
print("updates:", len(ups))
msgs = [u["message"] for u in ups if "message" in u and u["message"]["chat"]["type"] == "private"]
if msgs:
    m = msgs[-1]
    if "TG_CHAT_ID" not in env:
        with open(P, "a", encoding="utf-8") as f: f.write("TG_CHAT_ID=%s\nTG_USER_ID=%s\n" % (m["chat"]["id"], m["from"]["id"]))
        print("private chat found, ids saved to tg.env (not printed), last text:", repr(m.get("text", ""))[:30])
    else:
        print("TG_CHAT_ID already in tg.env")
else:
    print("no private messages yet: send /start to the bot")
