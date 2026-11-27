# -*- coding: utf-8 -*-
"""Проба квот Gemini: по одному минимальному запросу к каждой модели цепочки, печатает статус и тело ошибки (без ключа)."""
import json
import sys
import urllib.error
import urllib.request

import weather_tg_ai as ai

if "haiku" in sys.argv[1:]:
    print("CHANNEL_CLAUDE_FALLBACK =", ai.env_flag("CHANNEL_CLAUDE_FALLBACK"))
    try:
        print("haiku:", ai.claude_json("claude-haiku-5-5")("Ответь только JSON", 'Верни {"verdict": "ок"}'))
    except Exception as e:
        print("haiku ERR", str(e)[:200])
    sys.exit(0)
key = ai.gemini_key()
for model in (sys.argv[1:] or ["gemini-4-hydrogen", "gemini-3.5-flash", "gemini-2.5-flash"]):
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, key)
    body = {"contents": [{"parts": [{"text": "ok"}]}], "generationConfig": {"maxOutputTokens": 5}}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=40) as r:
            print(model, "HTTP", r.status, "OK")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        print(model, "HTTP", e.code, ai.quota_info(raw) if e.code == 429 else raw[:200].replace("\n", " "))
        if e.code == 429:
            print("RAW:", raw[:900].replace("\n", " "))
    except Exception as e:
        print(model, "ERR", str(e)[:150])
