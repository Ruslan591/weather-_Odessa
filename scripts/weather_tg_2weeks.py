# -*- coding: utf-8 -*-
"""Пост «Погода на 2 недели»: страница на Telegraph + анонс в канале (Instant View). Раз в день 09:30 по Киеву.

  python3 weather_tg_2weeks.py [--dry] [--force] [--no-ai] [--no-publish] [--page-only] [--setup]

Страница по макету: общий обзор, первая неделя (группы похожих дней, не по дням), вторая неделя общим текстом, море.
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


def phenomena(day, extra):
    """Туман/дымка по почасовым данным Open-Meteo на день (только ближайшие 5 суток)."""
    fog, haze = [], []
    for h in range(24):
        e = extra.get(datetime(day.year, day.month, day.day, h).strftime("%Y-%m-%dT%H"))
        if not e or e[1] is None:
            continue
        if e[1] < 1000:
            fog.append(h)
        elif e[1] < 10000 and (e[2] or 0) > 80:
            haze.append(h)
    out = []
    if fog:
        out.append("туман с %02d:00 до %02d:00" % (fog[0], fog[-1]))
    if haze:
        out.append("дымка с %02d:00 до %02d:00" % (haze[0], haze[-1]))
    return out


def group_days(days, stats):
    """Группы подряд идущих похожих дней; не более 5 групп."""
    groups = []
    for d in days:
        s = stats[d]
        if groups:
            g = groups[-1]
            p = stats[g[-1]]
            if abs(s["hi"] - p["hi"]) <= 2.5 and abs(s["lo"] - p["lo"]) <= 2.5 and s["wet"] == p["wet"] and len(g) < 3:
                g.append(d)
                continue
        groups.append([d])
    while len(groups) > 5:   # склеиваем соседние группы с наименьшим различием
        best, bi = None, 0
        for i in range(len(groups) - 1):
            a, b = stats[groups[i][-1]], stats[groups[i + 1][0]]
            diff = abs(a["hi"] - b["hi"]) + abs(a["lo"] - b["lo"]) + 5 * abs(a["wet"] - b["wet"])
            if best is None or diff < best:
                best, bi = diff, i
        groups[bi:bi + 2] = [groups[bi] + groups[bi + 1]]
    return groups


def label(g):
    a, b = g[0], g[-1]
    f = lambda d: "%s %02d.%02d" % (rv.WD[d.weekday()], d.day, d.month)
    return f(a) if a == b else "%s – %s" % (f(a), f(b))


def rng(vals):
    lo, hi = min(vals), max(vals)
    return rv.sg(lo) if round(lo) == round(hi) else "от %s до %s" % (rv.sg(lo), rv.sg(hi))


def group_fact(g, stats, extra):
    ss = [stats[d] for d in g]
    wet = max(s["wet"] for s in ss)
    snow = any(s["snow"] for s in ss)
    pm = max(s["pm"] for s in ss)
    pr = "осадков не ожидается" if wet == 0 else ("%s снег" % ("вероятен" if wet == 2 else "возможен") if snow else
                                                  ("осадки, до %d мм" % round(pm) if wet == 2 else "возможны осадки, до %d мм" % round(pm)))
    gust = max(s["gust"] for s in ss)
    sp = max(s["spread"] for s in ss)
    conf = "прогноз надёжный" if sp <= 2.5 else ("прогноз умеренно надёжный" if sp <= 5 else "модели заметно расходятся")
    ph = []
    for d in g:
        for x in phenomena(d, extra):
            ph.append("%s %02d.%02d" % (x, d.day, d.month))
    s = "%s: днём %s °C, ночью %s °C, %s" % (label(g), rng([x["hi"] for x in ss]), rng([x["lo"] for x in ss]), pr)
    if gust >= 12:
        s += ", порывы до %d м/с" % round(gust)
    if ph:
        s += ", " + "; ".join(ph)
    return s + ", " + conf + "."


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


def build_nodes(dateline, overview, w1_title, groups, w2_title, w2_text, sea_line):
    N = lambda tag, *ch_, **a: dict({"tag": tag, "children": list(ch_)}, **({"attrs": a} if a else {}))
    nodes = [N("p", N("em", dateline)), N("p", overview), N("h4", w1_title)]
    for lab, txt in groups:
        nodes.append(N("p", N("b", lab + ". "), txt))
    nodes += [N("h4", w2_title), N("p", w2_text)]
    if sea_line:
        s = re.sub(r"^🌊\s*Море:\s*", "", sea_line)
        nodes += [N("h4", "Море"), N("p", s[:1].upper() + s[1:])]
    nodes.append(N("p", N("em", "Автоматический прогноз, обновляется ежедневно.")))
    return nodes


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
def build(now, state, log, use_ai):
    ln = now.astimezone(KYIV)
    today = ln.date()
    daily = rv.fetch_daily(log)
    days = [today + timedelta(days=i) for i in range(14)]
    ok_days = [d for d in days if daily.get(d, {}).get("tmax") and daily[d].get("tmin")]
    if len(ok_days) < 10:
        log("2weeks: данных мало (%d из 14), пост пропущен" % len(ok_days))
        return None
    stats = {d: day_stats(daily[d]) for d in ok_days}
    w1 = [d for d in days[:7] if d in stats]
    w2 = [d for d in days[7:] if d in stats]
    extra = outl.fetch_extra(log)
    groups = group_days(w1, stats)
    gl = [group_fact(g, stats, extra) for g in groups]
    cold = min(ok_days, key=lambda d: stats[d]["lo"])
    warm = max(ok_days, key=lambda d: stats[d]["hi"])
    wet_days = [d for d in ok_days if stats[d]["wet"]]
    summ = ["Самая холодная ночь: %s %02d.%02d, около %s °C." % (rv.WD[cold.weekday()], cold.day, cold.month, rv.sg(stats[cold]["lo"])),
            "Самый тёплый день: %s %02d.%02d, около %s °C." % (rv.WD[warm.weekday()], warm.day, warm.month, rv.sg(stats[warm]["hi"])),
            ("Осадки возможны: %s." % ", ".join("%02d.%02d" % (d.day, d.month) for d in wet_days)) if wet_days else "Осадков в ближайшие две недели не ожидается."]
    w2_lines = [x for x in (rv.day_facts(d, daily[d], today) for d in w2) if x]
    tend = tendency_text()
    sea_line = None
    try:
        import weather_tg_issue as iss
        sea_line = iss.sea_line(iss.sea_facts(now))
    except Exception as e:
        log("2weeks: море недоступно (%s)" % type(e).__name__)
    facts = "ОБЩЕЕ:\n%s\nПЕРВАЯ НЕДЕЛЯ (группы дней):\n%s\nВТОРАЯ НЕДЕЛЯ (по дням, только как справка):\n%s\n" % (
        "\n".join(summ), "\n".join("%d. %s" % (i + 1, x) for i, x in enumerate(gl)), "\n".join(w2_lines))
    if tend:
        facts += "ТЕНДЕНЦИЯ (текст сайта, основа для обзора):\n%s\n" % tend
    title = "Погода в Одессе на 2 недели: %s" % rv.span_title(days[0], days[-1])
    overview = w2_text = None
    gtexts = None
    if use_ai:
        ai.budget(200)
        fields = {"overview": 420, "week2": 520}
        for i in range(len(groups)):
            fields["g%d" % (i + 1)] = 260
        sys_ = ai.BASE + ("Напиши текст страницы «Погода на 2 недели» для Telegraph. Поля JSON: overview (общий характер двух недель: что преобладает, "
                          "самая холодная ночь и самый тёплый день, когда ждать перемену; 3-4 предложения), g1..g%d (по одному тексту на каждую группу первой недели "
                          "в том же порядке, 1-2 предложения, про температуру, осадки и явления; метки дат НЕ повторяй), week2 (вторая неделя общим текстом, "
                          "3-4 предложения, без перечисления дней, с оценкой уверенности моделей). Если есть раздел ТЕНДЕНЦИЯ, опирайся на него, а не придумывай заново. "
                          "Не ссылайся на сайт и на модели по именам. Формат ответа: только JSON с этими полями." % len(groups))
        res = rv.ask_multi(sys_, "ДАННЫЕ:\n%s\nВерни только JSON." % facts, fields, facts, log)
        if res:
            overview, w2_text = res["overview"], res["week2"]
            gtexts = [res["g%d" % (i + 1)] for i in range(len(groups))]
    if not overview:   # шаблон при сбое ИИ
        overview = " ".join(summ)
        gtexts = [re.sub(r"^[^:]+: ", "", x) for x in gl]
        w2_text = tend or "Подробный прогноз на вторую неделю будет в следующем выпуске."
    nodes = build_nodes("Погода Одесса, %s %d" % (rv.dm(today), today.year), overview,
                        "Первая неделя, %s" % rv.span_title(days[0], days[6]).replace("–", "–"),
                        [(label(g), t) for g, t in zip(groups, gtexts)],
                        "Вторая неделя, %s" % rv.span_title(days[7], days[13]), w2_text, sea_line)
    return title, nodes, overview, ("ИИ" if use_ai and gtexts and res else "шаблон")


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
    if not force and ln.hour != SEND_HOUR:
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
