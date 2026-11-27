# -*- coding: utf-8 -*-
"""Обзорные посты канала: выходные (чт и пт 12:30) и обзор недели (пт, сб, вс 18:30). Время местное (Киев).

  python3 weather_tg_review.py weekend|week [--dry] [--force] [--no-ai]

weekend: суббота и воскресенье по часовому Ансамблю канала (+ облачность/видимость Open-Meteo, море).
week:    следующая неделя пн-вс по дневному прогнозу ECMWF, GFS, GEM (Open-Meteo): Ансамбль канала считает всего 5 суток.
Общий вид: общий обзор + части периода, без разбивки по дням (для недели подробности по дням в раскрывающейся цитате).
Текст пишет ИИ по готовым фактам (ai._ask-подобная проверка чисел), при неудаче собирается шаблон.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import weather_tg_ai as ai
import weather_tg_channel as ch
import weather_tg_outlook as outl

KYIV = ch.KYIV
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_state.json")
SILENT = True
SEND_HOUR = {"weekend": 12, "week": 18}                 # местный час (минуты задаёт cron: :30)
SEND_DAYS = {"weekend": (3, 4), "week": (4, 5, 6)}      # чт, пт | пт, сб, вс (weekday(): пн=0)
MODELS = ["ecmwf_ifs025", "gfs_global", "gem_global"]
DAILY_URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.43&longitude=30.74&timezone=Europe%2FKyiv&forecast_days=16"
             "&models=" + ",".join(MODELS) + "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,wind_gusts_10m_max")
WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WD_FULL = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
MONTH = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def dm(d):
    return "%d %s" % (d.day, MONTH[d.month - 1])


def span_title(a, b):
    if a.month == b.month:
        return "%d–%d %s" % (a.day, b.day, MONTH[a.month - 1])
    return "%s – %s" % (dm(a), dm(b))


def sg(v):
    v = int(round(v))
    return ("+%d" % v if v > 0 else "−%d" % abs(v) if v < 0 else "0")


# ---------- данные для обзора недели ----------
def fetch_daily(log):
    """{date: {tmax:[...], tmin:[...], pr:[...], sn:[...], g:[...]}} по моделям (None отбрасываются); пусто при сбое."""
    try:
        with urllib.request.urlopen(DAILY_URL, timeout=30) as r:
            d = json.load(r)["daily"]
    except Exception as e:
        log("review: Open-Meteo daily недоступен (%s)" % type(e).__name__)
        return {}
    out = {}
    for i, t in enumerate(d["time"]):
        day = datetime.strptime(t, "%Y-%m-%d").date()
        rec = {"tmax": [], "tmin": [], "pr": [], "sn": [], "g": []}
        for key, var in (("tmax", "temperature_2m_max"), ("tmin", "temperature_2m_min"), ("pr", "precipitation_sum"),
                         ("sn", "snowfall_sum"), ("g", "wind_gusts_10m_max")):
            for m in MODELS:
                arr = d.get("%s_%s" % (var, m))
                if arr and i < len(arr) and arr[i] is not None:
                    rec[key].append(arr[i])
        out[day] = rec
    return out


def day_facts(day, rec, today):
    """Строка фактов по одному дню; None, если данных нет."""
    if not rec["tmax"] or not rec["tmin"]:
        return None
    hi, lo = sum(rec["tmax"]) / len(rec["tmax"]), sum(rec["tmin"]) / len(rec["tmin"])
    spread = max(rec["tmax"]) - min(rec["tmax"])
    n = len(rec["pr"]) or 1
    wet = sum(1 for x in rec["pr"] if x >= 1.0)
    pm = max(rec["pr"]) if rec["pr"] else 0
    snow = sum(1 for x in rec["sn"] if x >= 0.5)
    if wet == 0:
        pr = "осадков не ожидается"
    elif snow and snow >= wet / 2.0:
        pr = "%s снег" % ("вероятен" if wet == n else "возможен")
    else:
        pr = ("осадки, до %d мм" % round(pm)) if wet == n else ("возможны осадки, до %d мм" % round(pm))
    gust = max(rec["g"]) if rec["g"] else 0
    ahead = (day - today).days
    conf = "прогноз надёжный" if spread <= 2.5 and ahead <= 7 else ("прогноз умеренно надёжный" if spread <= 5 else "модели заметно расходятся, прогноз ненадёжный")
    s = "%s %s.%s: днём %s °C, ночью %s °C, %s" % (WD[day.weekday()], "%02d" % day.day, "%02d" % day.month, sg(hi), sg(lo), pr)
    if gust >= 12:
        s += ", порывы до %d м/с" % round(gust)
    return s + ", " + conf + "."


def week_bounds(ln):
    d = ln.date()
    start = d + timedelta(days=((7 - d.weekday()) % 7) or 7)   # ближайший понедельник строго после сегодня
    return start, start + timedelta(days=6)


def weekend_bounds(ln):
    d = ln.date()
    sat = d + timedelta(days=(5 - d.weekday()) % 7)
    return sat, sat + timedelta(days=1)


# ---------- ИИ ----------
def ask_multi(sys_, prompt, fields, facts, log):
    """fields: {имя: макс. длина}. Возвращает {имя: текст} либо None. Проверка чисел/слов как в ai._ask."""
    if not ai.gemini_key() and not ai.CALLER:
        log("review: нет ключа Gemini")
        return None
    p = prompt
    for attempt in (1, 2):
        try:
            art, model = ai.CALLER(sys_, p) if ai.CALLER else ai.smart_call(sys_, p)
        except Exception as e:
            log("review: ИИ ошибка: %s" % e)
            return None
        probs, res = [], {}
        for f, mx in fields.items():
            txt = str(art.get(f, "")).strip()
            pr = ai.check(txt, facts, mx)
            res[f] = txt
            if pr:
                probs.append("%s: %s" % (f, "; ".join(pr)))
        if not probs:
            if ai.ERRS:
                log("review: запасной вариант (%s)" % "; ".join(ai.ERRS))
            log("review: текст ok (%s)" % model)
            res["_model"] = model
            return res
        log("review: текст отклонён (%s): %s" % (model, " | ".join(probs)))
        p = prompt + "\nПредыдущий вариант отклонён: %s. Исправь и верни только JSON." % " | ".join(probs)
    return None


def build_weekend(hours, now, state, log, use_ai):
    ln = now.astimezone(KYIV)
    sat, sun = weekend_bounds(ln)
    mid = lambda d: datetime(d.year, d.month, d.day, tzinfo=KYIV)
    extra = outl.fetch_extra(log)
    segs = []
    for lab, day in (("суббота", sat), ("воскресенье", sun)):
        f = outl.seg_facts(lab, mid(day), mid(day) + timedelta(days=1), hours, extra)
        if f:
            segs.append(f)
    if len(segs) < 2:
        log("review: данных по выходным мало (%d), пост пропущен" % len(segs))
        return None
    sea_line = None
    try:
        import weather_tg_issue as iss
        sea_line = iss.sea_line(iss.sea_facts(now))
    except Exception as e:
        log("review: море недоступно (%s)" % type(e).__name__)
    facts = outl.facts_text(segs, sea_line)
    title = "🗓 <b>Погода на выходные, %s</b>" % span_title(sat, sun)
    res = None
    if use_ai:
        ai.budget(150)
        sys_ = ai.BASE + ("Напиши обзор погоды на выходные для Telegram-канала. Поля JSON: overview (общий характер выходных, 1-2 предложения), "
                          "saturday (про субботу, 1-2 предложения), sunday (про воскресенье, 1-2 предложения). Только про будущее; "
                          "про температуру, ветер, облачность, осадки, туман или дымку если они есть, море одной фразой в overview если есть строка о море. "
                          "Формат ответа: только JSON {\"overview\": \"...\", \"saturday\": \"...\", \"sunday\": \"...\"}.")
        pr = "ПРОГНОЗ:\n%s\n" % facts
        rec = state.get("weekend_texts", [])
        if rec:
            pr += "\nНедавние обзоры (не повторяй конструкции):\n- " + "\n- ".join(x[:160] for x in rec[-2:]) + "\n"
        res = ask_multi(sys_, pr + "\nВерни только JSON.", {"overview": 300, "saturday": 330, "sunday": 330}, facts, log)
    if res:
        body = "%s\n\n<b>Суббота, %s</b>\n%s\n\n<b>Воскресенье, %s</b>\n%s" % (
            esc(res["overview"]), dm(sat), esc(res["saturday"]), dm(sun), esc(res["sunday"]))
        state["weekend_texts"] = (state.get("weekend_texts", []) + [res["overview"]])[-3:]
        src = "ИИ " + str(res.get("_model"))
    else:
        body = "\n".join(esc(x) for x in facts.split("\n") if x)
        src = "шаблон"
    return "%s\n\n%s" % (title, body), src


def build_week(now, state, log, use_ai):
    ln = now.astimezone(KYIV)
    a, b = week_bounds(ln)
    daily = fetch_daily(log)
    days = [(a + timedelta(days=i)) for i in range(7)]
    lines = [day_facts(d, daily.get(d, {"tmax": [], "tmin": [], "pr": [], "sn": [], "g": []}), ln.date()) for d in days]
    if sum(1 for x in lines if x) < 5:
        log("review: данных по неделе мало, пост пропущен")
        return None
    lines = [x for x in lines if x]
    facts = "\n".join(lines)
    title = "🗓 <b>Погода на неделю, %s</b>" % span_title(a, b)
    detail = "<blockquote expandable><b>Подробно по дням</b>\n%s</blockquote>" % esc("\n".join(lines))
    res = None
    if use_ai:
        ai.budget(150)
        sys_ = ai.BASE + ("Напиши обзор погоды на следующую неделю (пн-вс) для Telegram-канала. Поля JSON: overview (общий характер недели, главные перемены, "
                          "самый холодный или тёплый день, 2-3 предложения), first (понедельник-среда, 1-2 предложения), "
                          "second (четверг-воскресенье, 1-2 предложения; если модели расходятся, скажи, что прогноз менее надёжен). "
                          "Не перечисляй дни подряд. Если в строках дня указана неопределённость, не выдавай эти дни за точные. "
                          "Формат ответа: только JSON {\"overview\": \"...\", \"first\": \"...\", \"second\": \"...\"}.")
        pr = "ПРОГНОЗ ПО ДНЯМ:\n%s\n" % facts
        rec = state.get("week_texts", [])
        if rec:
            pr += "\nНедавние обзоры (не повторяй конструкции):\n- " + "\n- ".join(x[:160] for x in rec[-2:]) + "\n"
        res = ask_multi(sys_, pr + "\nВерни только JSON.", {"overview": 380, "first": 300, "second": 330}, facts, log)
    if res:
        body = "%s\n\n<b>Пн–Ср, %s – %s</b>\n%s\n\n<b>Чт–Вс, %s – %s</b>\n%s" % (
            esc(res["overview"]), dm(days[0]), dm(days[2]), esc(res["first"]), dm(days[3]), dm(days[6]), esc(res["second"]))
        state["week_texts"] = (state.get("week_texts", []) + [res["overview"]])[-3:]
        src = "ИИ " + str(res.get("_model"))
        return "%s\n\n%s\n\n%s" % (title, body, detail), src
    return "%s\n\n%s" % (title, detail), "шаблон"


# ---------- запуск ----------
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    kind = args[0] if args else ""
    if kind not in SEND_HOUR:
        print("usage: weather_tg_review.py weekend|week [--dry] [--force] [--no-ai]")
        return 2
    dry, force = "--dry" in flags, "--force" in flags
    now = datetime.now(timezone.utc)
    ln = now.astimezone(KYIV)
    if not force and (ln.hour != SEND_HOUR[kind] or ln.weekday() not in SEND_DAYS[kind]):
        return 0   # cron стоит на оба сезона (UTC), лишний запуск молча выходит
    env = ch.load_env()
    if not dry and ("WEATHER_TG_TOKEN" not in env or "WEATHER_TG_CHAT_ID" not in env):
        ch.log("review: нет токена/канала")
        return 1
    st = load_state()
    key = "%s_%s" % (kind, ln.strftime("%Y-%m-%d"))
    if not force and not dry and st.get("sent_" + key):
        return 0
    use_ai = "--no-ai" not in flags
    if kind == "weekend":
        hours = ch.get_ensemble(ch.load_state(), now)
        if not hours:
            ch.log("review: Ансамбль не посчитан, выходные пропущены")
            return 1
        r = build_weekend(hours, now, st, ch.log, use_ai)
    else:
        r = build_week(now, st, ch.log, use_ai)
    if not r:
        return 1
    text, src = r
    if dry:
        print(text)
        print("--- %d символов, текст: %s" % (len(text), src))
        return 0
    if not ch.tg_send(env, text, SILENT):
        ch.log("review: %s НЕ отправлен" % kind)
        return 1
    st["sent_" + key] = True
    st = {k: v for k, v in st.items() if not k.startswith("sent_") or k[-10:] >= (ln - timedelta(days=10)).strftime("%Y-%m-%d")}
    save_state(st)
    ch.log("review: %s отправлен (%d символов, %s)" % (kind, len(text), src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
