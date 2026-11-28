# -*- coding: utf-8 -*-
"""Проба: как загрузить картинку для страницы Telegraph. Печатает результаты вариантов; ничего не публикует в канал."""
import json
import sys
import urllib.parse
import urllib.request
import uuid

import weather_tg_channel as ch
import weather_tg_chart as chart

png = open("/tmp/chart_test.png", "rb").read()


def upload(headers, fname="chart.png", field="file", ctype="image/png"):
    b = uuid.uuid4().hex
    body = (("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (b, field, fname, ctype)).encode()
            + png + ("\r\n--%s--\r\n" % b).encode())
    h = {"Content-Type": "multipart/form-data; boundary=" + b}
    h.update(headers)
    req = urllib.request.Request("https://telegra.ph/upload", data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return "OK %s" % r.read()[:200]
    except Exception as e:
        return "ERR %s %s" % (e, getattr(e, "read", lambda: b"")()[:120])


UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
print("A браузерный UA:", upload({"User-Agent": UA}))
print("B UA+Origin+Referer:", upload({"User-Agent": UA, "Origin": "https://telegra.ph", "Referer": "https://telegra.ph/"}))
print("C поле image:", upload({"User-Agent": UA, "Referer": "https://telegra.ph/"}, field="image"))
# внешний URL в createPage
env = ch.load_env()
src = sys.argv[1] if len(sys.argv) > 1 else "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/icon.png"
nodes = [{"tag": "p", "children": ["тест картинки"]}, {"tag": "img", "attrs": {"src": src}}]
try:
    data = urllib.parse.urlencode({"access_token": env["TELEGRAPH_TOKEN"], "title": "test img", "author_name": "test",
                                   "content": json.dumps(nodes), "return_content": "true"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://api.telegra.ph/createPage", data=data), timeout=30) as r:
        j = json.loads(r.read().decode())
    print("D внешний URL:", j.get("ok"), j.get("result", {}).get("url"), json.dumps(j.get("result", {}).get("content"), ensure_ascii=False)[:300], j.get("error"))
except Exception as e:
    print("D ERR", e)
