# -*- coding: utf-8 -*-
"""Проба квот Gemini: по одному минимальному запросу к каждой модели цепочки, печатает статус и тело ошибки (без ключа)."""
import json
import sys
import urllib.error
import urllib.request

import weather_tg_ai as ai

if "usage" in sys.argv[1:]:
    # расход по журналу с последнего сброса квоты (00:00 PT = 08:00 UTC зимой, 07:00 UTC летом)
    from collections import Counter
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    off = 8 if now.month in (11, 12, 1, 2, 3) else 7
    since = now.replace(hour=off, minute=0, second=0, microsecond=0)
    if since > now:
        since -= timedelta(days=1)
    c, cp = Counter(), Counter()
    for ln in open(ai.USAGE_LOG, encoding="utf-8"):
        r = json.loads(ln)
        if datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= since:
            c[(r["model"], r["status"])] += 1
            cp[(r["model"], r["purpose"] or "?")] += 1
    print("с", since.isoformat(), "UTC")
    for k, v in sorted(c.items(), key=lambda x: str(x[0])):
        print(k[0], k[1], v)
    print("по назначению:")
    for k, v in sorted(cp.items(), key=lambda x: str(x[0])):
        print(k[0], k[1], v)
    sys.exit(0)
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
