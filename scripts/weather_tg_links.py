# -*- coding: utf-8 -*-
"""Ссылки внизу постов на редкие посты (на неделю, вторая неделя, до конца недели, выходные).

Запись: record(kind, ref) после отправки (ref: id сообщения или полная ссылка, например Telegraph).
Чтение: footer(env, now, kinds) возвращает строку «📎 Подробнее: …» только с актуальными постами или ''.
Формат ссылки на сообщение: публичный канал (WEATHER_TG_USERNAME в tg.env) t.me/имя/номер, частный t.me/c/<id>/<номер> (работает у участников).
"""
import json
import os
from datetime import datetime, timedelta, timezone

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "links.json")
# вид: (подпись, сколько суток ссылка актуальна)
KINDS = {"week": ("прогноз на неделю", 3), "prelim": ("вторая неделя", 7), "rest": ("до конца недели", 2), "weekend": ("на выходные", 2)}


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def record(kind, ref, now=None):
    d = _load()
    d[kind] = {"ref": str(ref), "ts": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def base(env):
    user = (env.get("WEATHER_TG_USERNAME") or "").lstrip("@")
    if user:
        return "https://t.me/" + user
    chat = str(env.get("WEATHER_TG_CHAT_ID", ""))
    return "https://t.me/c/" + chat[4:] if chat.startswith("-100") else None


def url_of(env, ref):
    if ref.startswith("http"):
        return ref
    b = base(env)
    return "%s/%s" % (b, ref) if b else None


def footer(env, now, kinds, limit=3):
    d = _load()
    parts = []
    for k in kinds:
        rec, meta = d.get(k), KINDS.get(k)
        if not rec or not meta:
            continue
        try:
            ts = datetime.strptime(rec["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now - ts > timedelta(days=meta[1]) or now < ts:
            continue
        u = url_of(env, rec["ref"])
        if u:
            parts.append('<a href="%s">%s</a>' % (u, meta[0]))
    parts = parts[:limit]
    return ("📎 Подробнее: " + " · ".join(parts)) if parts else ""
