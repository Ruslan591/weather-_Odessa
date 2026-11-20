# -*- coding: utf-8 -*-
"""Разовая чистка теней: удаляет НЕзакрытые (ждёт входа / открытые) тени на таймфреймах вне списка (по умолчанию оставляем только 5m) вместе с двойниками варианта B и их сообщениями в канале. Закрытые остаются.
Запускать при остановленном tg-bot-regr (бот держит записи в памяти и перезаписал бы файл). Использование: python3 shadow_drop_tf.py [5m,...]"""
import json, os, shutil, sys, time, urllib.parse, urllib.request
P = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr"); F = P + "/shadow.json"
keep = set((sys.argv[1] if len(sys.argv) > 1 else "5m").split(","))
d = json.load(open(F, encoding="utf-8")); its = d["items"]; shutil.copy(F, F + ".bak_" + time.strftime("%Y%m%d_%H%M%S"))
rm = {i["id"] for i in its if not i.get("legacy") and i.get("tf") not in keep and i.get("status") in ("gate", "open")}
tw = {(i["sym"], i["side"], i["tf"], i.get("t0")) for i in its if i["id"] in rm}
rm |= {i["id"] for i in its if not i.get("legacy") and i.get("var") == "B" and (i["sym"], i["side"], i["tf"], i.get("t0")) in tw and i.get("status") in ("gate", "filtered")}
tok = os.environ.get("TG_TOKEN"); chat = os.environ.get("TG_CHAT_SHADOW"); gone = 0
for iid in sorted(rm):
    m = d.get("msg", {}).get(str(iid)) or {}
    for k in ("a", "b", "c"):
        mid = m.get(k)
        if tok and chat and isinstance(mid, int) and mid > 0:
            try: urllib.request.urlopen("https://api.telegram.org/bot%s/deleteMessage?%s" % (tok, urllib.parse.urlencode({"chat_id": chat, "message_id": mid})), timeout=15); gone += 1
            except Exception as e: print("deleteMessage %s/%s: %r" % (iid, k, e)[:150])
    d["msg"].pop(str(iid), None)
d["items"] = [i for i in its if i["id"] not in rm]
tmp = F + ".tmp"; json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), default=str); os.replace(tmp, F)
print("removed ids:", sorted(rm), "channel messages deleted:", gone, "left:", len(d["items"]))
