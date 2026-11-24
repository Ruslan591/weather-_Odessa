#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Закреплённое «табло» канала: только частные станции (PWS) с ощущаемой температурой.

Одно сообщение, которое редактируется каждые 15 минут (cron */15). В ленту ничего не добавляется.
Состояние: /opt/weather-tg/board_state.json (message_id). Если сообщение удалено, создаётся и закрепляется заново.
Запуск: python3 weather_tg_board.py [--dry]
"""
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_tg_channel as ch  # noqa: E402

KYIV = ch.KYIV
BOARD_STATE = os.path.join(ch.BASE, "board_state.json")
FRESH_MIN = 45
# шкала ощущаемой: 10 сегментов от −20 до +40 °C (по 6 °C)
SEGS = ["🟪", "🟦", "🟦", "🟦", "🟩", "🟩", "🟨", "🟧", "🟥", "🟥"]
CATS = [(-100, "сильный мороз"), (-20, "мороз"), (-10, "морозно"), (0, "холодно"), (6, "прохладно"), (14, "умеренно"),
        (22, "комфортно"), (27, "тепло"), (32, "жарко"), (38, "сильная жара")]


def tv(x, nd=0):
    if x is None:
        return "—"
    r = round(x, nd)
    s = ("%.1f" % abs(r)).replace(".", ",") if nd else "%d" % abs(r)
    return "+" + s if r > 0 else ("−" + s if r < 0 else "0")


def feels(t, w, rh):
    """Ощущаемая: охлаждение ветром (T<=10 °C, ветер >4,8 км/ч), иначе кажущаяся температура Стедмана."""
    v = (w or 0.0) * 3.6
    if t <= 10 and v > 4.8:
        return 13.12 + 0.6215 * t - 11.37 * v ** 0.16 + 0.3965 * t * v ** 0.16
    if rh is None:
        return t
    e = rh / 100.0 * 6.105 * math.exp(17.27 * t / (237.7 + t))
    return t + 0.33 * e - 0.70 * (w or 0.0) - 4.00


def scale(f):
    i = max(0, min(9, int((f + 20) // 6)))
    bar = "".join("⚪" if k == i else seg for k, seg in enumerate(SEGS))
    cat = CATS[0][1]
    for lim, name in CATS:
        if f >= lim:
            cat = name
    return bar, cat


def collect(env, now):
    keys = [k for k in env.get("WU_KEYS", "").split(",") if k]
    start = int(time.time() // 600)
    out = []
    for sid, name in ch.STATIONS:
        raw = ch.fetch_station(sid, keys, start)
        time.sleep(0.3)
        obs = [p for p in (ch.parse_obs(o) for o in (raw or [])) if p]
        obs.sort(key=lambda o: o["ts"])
        if not obs or (now - obs[-1]["ts"]) > timedelta(minutes=FRESH_MIN):
            continue
        last = obs[-1]
        recent = obs[-2:]
        out.append({"name": name, "obs": obs, "temp": last["temp"], "hum": last["hum"], "wind": last["wind"], "dir": last["dir"],
                    "p": (last["p"] + ch.P_OFFSET.get(sid, 0.0)) if last["p"] is not None else None,
                    "gust": max((o["gust"] or 0.0) for o in recent), "int": max(o["int"] for o in recent), "ptot": last["ptot"]})
    return out


def med(ok, key):
    v = [s[key] for s in ok if s.get(key) is not None]
    return statistics.median(v) if v else None


def build_board(ok, now):
    ln = now.astimezone(KYIV)
    t = med(ok, "temp")
    if t is None:
        return None
    w, rh, p = med(ok, "wind"), med(ok, "hum"), med(ok, "p")
    f = feels(t, w, rh)
    bar, cat = scale(f)
    temps = sorted(s["temp"] for s in ok if s["temp"] is not None)
    L = ["📡 <b>Одесса сейчас</b> · %s" % ln.strftime("%H:%M"), ""]
    L.append("🌡 <b>%s°</b> · ощущается как <b>%s°</b>" % (tv(t, 1), tv(f)))
    L.append("%s %s" % (bar, cat))
    if len(temps) >= 3 and temps[-1] - temps[0] >= 1.0:
        L.append("<i>по районам от %s° до %s°</i>" % (tv(temps[0], 1), tv(temps[-1], 1)))
    L.append("")
    items = [(s["dir"], s["wind"]) for s in ok if s.get("dir") is not None and s.get("wind") is not None]
    md = ch.mean_dir(items) if items else None
    g = max((s["gust"] for s in ok if s.get("gust") is not None), default=None)
    if w is not None:
        wl = "💨 ветер %s%s м/с" % ((ch.compass(md) + " ") if md is not None else "", ch.f0(w))
        if g is not None and g >= 3:
            wl += ", порывы до %s" % ch.f0(g)
        L.append(wl)
    parts = []
    if rh is not None:
        parts.append("💧 влажность %s%%" % ch.f0(rh))
    if p is not None:
        dp = [d for d in (ch.delta(s["obs"], "p", 180) for s in ok) if d is not None]
        s_ = "🧭 %s гПа" % ch.f0(p)
        if len(dp) >= 3:
            d = statistics.median(dp)
            s_ += " (%s)" % ("без изменений" if abs(d) < 0.3 else ("↓ %s за 3 ч" % ch.f1(abs(d)) if d < 0 else "↑ %s за 3 ч" % ch.f1(d)))
        parts.append(s_)
    if parts:
        L.append(" · ".join(parts))
    rain = [s for s in ok if s.get("int") and s["int"] >= 0.1]
    daily = [(s["ptot"], s["name"]) for s in ok if s.get("ptot") is not None and s["ptot"] >= 0.1]
    if rain:
        top = max(rain, key=lambda s: s["int"])
        L.append("🌧 идёт дождь: до %s мм/ч (%s)" % (ch.f1(top["int"]), ch.esc(top["name"])))
    else:
        L.append("☂ осадков сейчас нет")
    if daily:
        b = max(daily)
        L.append("за сутки с 00:00: до %s мм (%s)" % (ch.f1(b[0]), ch.esc(b[1])))
    L += ["", "<i>Частные станции, медиана по городу. Обновляется каждые 15 минут.</i>"]
    return "\n".join(L)


def api(env, method, params):
    url = "https://api.telegram.org/bot%s/%s" % (env["WEATHER_TG_TOKEN"], method)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=urllib.parse.urlencode(params).encode()), timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": "HTTP %s" % e.code}
    except Exception as e:
        return {"ok": False, "description": type(e).__name__}


def load_bs():
    try:
        return json.load(open(BOARD_STATE, encoding="utf-8"))
    except Exception:
        return {}


def main():
    dry = "--dry" in sys.argv
    env = ch.load_env()
    now = datetime.now(timezone.utc)
    ok = collect(env, now)
    if not ok:
        ch.log("board: нет свежих данных PWS")
        return 1
    text = build_board(ok, now)
    if not text:
        return 1
    if dry:
        print(text)
        return 0
    bs = load_bs()
    chat = env["WEATHER_TG_CHAT_ID"]
    mid = bs.get("message_id")
    if mid:
        r = api(env, "editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if r.get("ok") or "not modified" in str(r.get("description", "")):
            return 0
        ch.log("board: правка не удалась (%s), создаю заново" % r.get("description"))
    r = api(env, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_notification": "true", "disable_web_page_preview": "true"})
    if not r.get("ok"):
        ch.log("board: sendMessage не удался: %s" % r.get("description"))
        return 1
    mid = r["result"]["message_id"]
    pr = api(env, "pinChatMessage", {"chat_id": chat, "message_id": mid, "disable_notification": "true"})
    if not pr.get("ok"):
        ch.log("board: не закрепилось (нужны права администратора «закреплять сообщения»): %s" % pr.get("description"))
    json.dump({"message_id": mid, "created": now.isoformat()}, open(BOARD_STATE, "w", encoding="utf-8"))
    ch.log("board: создано сообщение %s (закреплено: %s)" % (mid, pr.get("ok")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
