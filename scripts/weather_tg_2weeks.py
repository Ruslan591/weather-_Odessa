# -*- coding: utf-8 -*-
"""Пост «Предварительный прогноз: вторая неделя»: страница на Telegraph + анонс в канале (Instant View). Раз в неделю, воскресенье 09:30 по Киеву.

  python3 weather_tg_2weeks.py [--dry] [--force] [--no-ai] [--no-publish] [--page-only] [--setup]

Страница: общий обзор второй недели (дни 8–14, встык за «Погодой на неделю») и «чего ждать и насколько надёжно». Первой недели нет: её закрывают краткосрочный прогноз и «на неделю».
Без ссылок на сайт. Данные: дневной прогноз ECMWF, GFS, GEM (Open-Meteo, 16 суток), текст «Тенденция» с сайта
(data/forecast_analysis_gemini.json) как основа для ИИ, явления (туман, дымка) на ближайшие 5 суток из почасовых данных.
Токен Telegraph: TELEGRAPH_TOKEN в .env (создаётся командой --setup один раз).
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import weather_tg_ai as ai
import weather_tg_channel as ch
import weather_tg_outlook as outl
import weather_tg_review as rv

KYIV = ch.KYIV
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twoweeks_state.json")
ANALYSIS_FILES = ["/opt/weather-pipeline/repo/data/forecast_analysis_gemini.json"]
SEND_HOUR = 9
TELEGRAPH = "https://api.telegra.ph/"
AUTHOR = "Погода Одесса"


# ---------- данные ----------
def tendency_text():
    """Раздел «Тенденция» из анализа сайта (без заголовка) или ''."""
    for p in ANALYSIS_FILES:
        try:
            with open(p, encoding="utf-8") as f:
                t = json.load(f).get("text", "")
        except Exception:
            continue
        m = re.search(r"^##\s*Тенденци[^\n]*\n(.*?)(?=^##\s|\Z)", t, re.S | re.M)
        if m:
            return m.group(1).strip()
    return ""


def day_stats(rec):
    hi = sum(rec["tmax"]) / len(rec["tmax"])
    lo = sum(rec["tmin"]) / len(rec["tmin"])
    n = len(rec["pr"]) or 1
    wet = sum(1 for x in rec["pr"] if x >= 1.0)
    snow = sum(1 for x in rec["sn"] if x >= 0.5)
    return {"hi": hi, "lo": lo, "spread": max(rec["tmax"]) - min(rec["tmax"]),
            "wet": 0 if wet == 0 else (2 if wet == n else 1), "snow": snow >= max(1, wet / 2.0) and wet > 0,
            "pm": max(rec["pr"]) if rec["pr"] else 0, "gust": max(rec["g"]) if rec["g"] else 0}


# ---------- Telegraph ----------
def telegraph_call(method, params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(TELEGRAPH + method, data=data), timeout=30) as r:
        j = json.loads(r.read().decode())
    if not j.get("ok"):
        raise RuntimeError("telegraph %s: %s" % (method, j.get("error")))
    return j["result"]


def setup_account(log):
    res = telegraph_call("createAccount", {"short_name": "WeatherOdessa", "author_name": AUTHOR})
    with open(ch.ENV_FILE, "a", encoding="utf-8") as f:
        f.write("\nTELEGRAPH_TOKEN=%s\n" % res["access_token"])
    log("2weeks: аккаунт Telegraph создан, токен записан в .env")


def build_nodes(dateline, overview, outlook):
    N = lambda tag, *ch_, **a: dict({"tag": tag, "children": list(ch_)}, **({"attrs": a} if a else {}))
    return [N("p", N("em", dateline)), N("p", overview), N("h4", "Чего ждать и насколько это надёжно"), N("p", outlook),
            N("p", N("em", "Прогноз на вторую неделю предварительный: он уточняется, актуальный прогноз на неделю выходит по пятницам, субботам и воскресеньям. "
                          "Этот обзор обновляется раз в неделю, по воскресеньям."))]


def publish_page(env, title, nodes):
    return telegraph_call("createPage", {"access_token": env["TELEGRAPH_TOKEN"], "title": title, "author_name": AUTHOR,
                                          "content": json.dumps(nodes, ensure_ascii=False), "return_content": "false"})["url"]


def announce(env, text, url, silent=True):
    data = urllib.parse.urlencode({
        "chat_id": env["WEATHER_TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "disable_notification": "true" if silent else "false",
        "link_preview_options": json.dumps({"is_disabled": False, "url": url, "prefer_large_media": True})}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % env["WEATHER_TG_TOKEN"], data=data), timeout=20) as r:
        return json.loads(r.read().decode()).get("ok", False)


# ---------- сборка ----------
def second_week(ln):
    """Вторая неделя встык за «Погодой на неделю»: пн–вс через одну неделю от ближайшего понедельника."""
    d = ln.date()
    mon = d + timedelta(days=((7 - d.weekday()) % 7) or 7)
    start = mon + timedelta(days=7)
    return start, start + timedelta(days=6)


def build(now, state, log, use_ai):
    ln = now.astimezone(KYIV)
    today = ln.date()
    a, b = second_week(ln)
    daily = rv.fetch_daily(log)
    days = [a + timedelta(days=i) for i in range(7)]
    ok_days = [d for d in days if daily.get(d, {}).get("tmax") and daily[d].get("tmin")]
    if len(ok_days) < 5:
        log("2weeks: данных по второй неделе мало (%d из 7), пост пропущен" % len(ok_days))
        return None
    stats = {d: day_stats(daily[d]) for d in ok_days}
    cold = min(ok_days, key=lambda d: stats[d]["lo"])
    warm = max(ok_days, key=lambda d: stats[d]["hi"])
    wet_days = [d for d in ok_days if stats[d]["wet"]]
    summ = ["Самая холодная ночь: %s %02d.%02d, около %s °C." % (rv.WD[cold.weekday()], cold.day, cold.month, rv.sg(stats[cold]["lo"])),
            "Самый тёплый день: %s %02d.%02d, около %s °C." % (rv.WD[warm.weekday()], warm.day, warm.month, rv.sg(stats[warm]["hi"])),
            ("Осадки возможны: %s." % ", ".join("%02d.%02d" % (d.day, d.month) for d in wet_days)) if wet_days else "Осадков на этой неделе не ожидается."]
    lines = [x for x in (rv.day_facts(d, daily[d], today) for d in ok_days) if x]
    tend = tendency_text()
    facts = "ОБЩЕЕ:\n%s\nВТОРАЯ НЕДЕЛЯ (по дням, только как справка):\n%s\n" % ("\n".join(summ), "\n".join(lines))
    if tend:
        facts += "ТЕНДЕНЦИЯ (текст сайта, основа для обзора):\n%s\n" % tend
    title = "Предварительный прогноз: вторая неделя, %s" % rv.span_title(a, b)
    overview = outlook = None
    res = None
    if use_ai:
        ai.budget(200)
        sys_ = ai.BASE + ("Напиши страницу «Предварительный прогноз: вторая неделя» (период указан в фактах) для Telegraph. Поля JSON: overview "
                          "(общий характер недели: что преобладает, самая холодная ночь и самый тёплый день, когда ждать перемену; 3-4 предложения), "
                          "outlook (чего ждать по осадкам и ветру и насколько прогноз надёжен: на таком горизонте он предварительный; 2-3 предложения). "
                          "Без перечисления дней, без ссылок на сайт и на модели по именам. Если есть раздел ТЕНДЕНЦИЯ, опирайся на него, а не придумывай заново. "
                          "Формат ответа: только JSON {\"overview\": \"...\", \"outlook\": \"...\"}.")
        res = rv.ask_multi(sys_, "ДАННЫЕ:\n%s\nВерни только JSON." % facts, {"overview": 520, "outlook": 420}, facts, log)
        if res:
            overview, outlook = res["overview"], res["outlook"]
    if not overview:   # шаблон при сбое ИИ
        overview = " ".join(summ)
        outlook = tend or "На таком горизонте прогноз предварительный и будет уточняться."
    nodes = build_nodes("Погода Одесса, %s %d" % (rv.dm(today), today.year), overview, outlook)
    return title, nodes, overview, ("ИИ" if res else "шаблон")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    now = datetime.now(timezone.utc)
    ln = now.astimezone(KYIV)
    env = ch.load_env()
    if "--setup" in flags:
        setup_account(ch.log)
        return 0
    force, dry = "--force" in flags, "--dry" in flags
    if not force and (ln.hour != SEND_HOUR or ln.weekday() != 6):   # только воскресенье 09:30
        return 0
    st = load_state()
    key = "sent_" + ln.strftime("%Y-%m-%d")
    if not force and not dry and st.get(key):
        return 0
    r = build(now, st, ch.log, "--no-ai" not in flags)
    if not r:
        return 1
    title, nodes, overview, src = r
    if dry or "--no-publish" in flags:
        print(title)
        print(json.dumps(nodes, ensure_ascii=False, indent=1)[:6000])
        print("--- текст: %s" % src)
        return 0
    if "--page-only" in flags:   # проверка: страница на Telegraph без анонса в канал
        print(publish_page(env, title, nodes))
        print("--- текст: %s" % src)
        return 0
    if not env.get("TELEGRAPH_TOKEN"):
        ch.log("2weeks: нет TELEGRAPH_TOKEN (python3 weather_tg_2weeks.py --setup)")
        return 1
    try:
        url = publish_page(env, title, nodes)
        text = "🗓 <b>%s</b>\n\n%s" % (rv.esc(title), rv.esc(overview))
        sent = announce(env, text, url)
    except Exception as e:
        ch.log("2weeks: сбой публикации: %s" % e)
        return 1
    if not sent:
        ch.log("2weeks: анонс не отправлен")
        return 1
    st[key] = url
    st = {k: v for k, v in st.items() if not k.startswith("sent_") or k[5:] >= (ln - timedelta(days=10)).strftime("%Y-%m-%d")}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    ch.log("2weeks: опубликовано %s (%s)" % (url, src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
