#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Утренний выпуск и вечерние итоги для Telegram-канала погоды Одессы.

Концепция и правила: docs/topics/weather_tg_channel.md (раздел «Дизайн ленты»).
Запуск на VPS по cron (/etc/cron.d/weather-tg), часы указаны в UTC для зимы и лета,
скрипт сам проверяет местный час (Киев) и не отправляет лишнего:
    python3 weather_tg_issue.py morning [--dry] [--force]
    python3 weather_tg_issue.py evening [--dry] [--force]
Прогноз только по Ансамблю (в тексте слово «Ансамбль» не пишем).
Состояние выпусков (для сравнения «обещали / вышло»): /opt/weather-tg/issue_state.json
"""
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_tg_channel as ch  # noqa: E402

KYIV = ch.KYIV
MORNING_H = 7        # местный час утреннего выпуска
EVENING_H = 21       # местный час вечерних итогов
ISSUE_SILENT = True  # выпуски без звука (предупреждения остаются со звуком)
ISSUE_STATE = os.path.join(ch.BASE, "issue_state.json")
HIST_DAYS = 30
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
WDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
SKY = {0: "ясно", 1: "малооблачно", 2: "облачно с прояснениями", 3: "пасмурно"}
SNOW = {71, 73, 75, 77, 85, 86}


# ---------- форматирование ----------
def tv(x, nd=0):
    """Температура со знаком: +7 / −3 / 0 (без единиц)."""
    if x is None:
        return "—"
    r = round(x, nd)
    s = ("%.1f" % abs(r)).replace(".", ",") if nd else "%d" % abs(r)
    return "+" + s if r > 0 else ("−" + s if r < 0 else "0")


def mm_txt(x):
    return ch.f1(x) if x < 10 else ch.f0(x)


def date_ru(d):
    return "%d %s, %s" % (d.day, MONTHS[d.month - 1], WDAYS[d.weekday()])


def hhmm(dt):
    return dt.astimezone(KYIV).strftime("%H:%M")


def esc(s):
    return ch.esc(s)


def pick(rng, variants):
    return variants[rng.randrange(len(variants))]


def feels(t, w):
    """Ощущаемая: охлаждение ветром при T<=10 и ветре >4,8 км/ч, иначе = T."""
    if t is None:
        return None
    v = (w or 0) * 3.6
    if t <= 10 and v > 4.8:
        return 13.12 + 0.6215 * t - 11.37 * v ** 0.16 + 0.3965 * t * v ** 0.16
    return t


def clothes(f):
    if f <= -10:
        return "очень холодно: тёплая куртка, шапка, шарф и перчатки"
    if f <= -3:
        return "зимняя куртка, шапка и перчатки"
    if f <= 3:
        return "тёплая куртка и шапка"
    if f <= 9:
        return "куртка, лучше шапка или капюшон"
    if f <= 15:
        return "лёгкая куртка или плотная кофта"
    if f <= 21:
        return "кофта или рубашка, к вечеру накиньте что-то сверху"
    if f <= 27:
        return "лёгкая одежда, футболка"
    return "жарко: лёгкая одежда, головной убор и вода с собой"


# ---------- данные станций ----------
def collect(env, now):
    keys = [k for k in env.get("WU_KEYS", "").split(",") if k]
    start = int(time.time() // 600)
    out = {}
    for sid, name in ch.STATIONS:
        raw = ch.fetch_station(sid, keys, start)
        time.sleep(0.3)
        obs = [p for p in (ch.parse_obs(o) for o in (raw or [])) if p]
        obs.sort(key=lambda o: o["ts"])
        if obs and (now - obs[-1]["ts"]) < timedelta(hours=3):
            out[sid] = {"name": name, "obs": obs}
    return out


def city_series(st, key, t0, t1):
    """Медиана по станциям в 10-минутных корзинах: [(время UTC, значение)]."""
    b = {}
    for sid, s in st.items():
        for o in s["obs"]:
            v = o.get(key)
            if v is None or not (t0 <= o["ts"] < t1):
                continue
            if key == "p":
                v += ch.P_OFFSET.get(sid, 0.0)
            b.setdefault(int(o["ts"].timestamp() // 600), []).append(v)
    need = 2 if len(st) >= 2 else 1
    return sorted((datetime.fromtimestamp(k * 600, timezone.utc), statistics.median(v))
                  for k, v in b.items() if len(v) >= need)


def station_extreme(st, key, t0, t1, fn):
    """Станция с экстремумом (fn = max/min) по ключу: (значение, имя, время)."""
    best = None
    for sid, s in st.items():
        for o in s["obs"]:
            v = o.get(key)
            if v is None or not (t0 <= o["ts"] < t1):
                continue
            if best is None or fn(v, best[0]) == v and v != best[0]:
                best = (v, s["name"], o["ts"])
    return best


# ---------- прогноз по Ансамблю ----------
def dayfc(hours, a, b):
    """Сводка по прогнозу на окно [a, b] (aware datetime)."""
    H = [h for h in hours if a <= h["dt"] <= b and h["T"] is not None]
    if not H:
        return None
    tmx = max(H, key=lambda h: h["T"])
    tmn = min(H, key=lambda h: h["T"])
    wl = [h for h in H if h["W"] is not None]
    gl = [h for h in H if h["G"] is not None]
    pl = [h for h in H if h["P"] is not None]
    R = [h for h in hours if a < h["dt"] <= b and h["R"] is not None]
    wet = [h for h in R if h["R"] >= ch.FC_MIN_MM]
    groups = []
    for h in wet:
        if groups and (h["dt"] - groups[-1]["last"]) <= timedelta(hours=2):
            g = groups[-1]
            g["last"] = h["dt"]
            g["mm"] += h["R"]
            g["peak"] = max(g["peak"], h["R"])
        else:
            groups.append({"first": h["dt"] - timedelta(hours=1), "last": h["dt"], "mm": h["R"], "peak": h["R"]})
    codes = [int(h["C"]) for h in H if h["C"] is not None]
    cc = Counter(c for c in codes if c in SKY)
    sky = SKY[cc.most_common(1)[0][0]] if cc else None
    fog = sum(1 for c in codes if c in (45, 48)) >= 2
    snow = any(c in SNOW for c in codes) or (bool(wet) and tmx["T"] <= 0.5)
    return {
        "H": H, "tmax": tmx["T"], "tmax_t": tmx["dt"], "tmin": tmn["T"], "tmin_t": tmn["dt"],
        "wmax": max(wl, key=lambda h: h["W"]) if wl else None,
        "gmax": max(gl, key=lambda h: h["G"]) if gl else None,
        "pmin": min(pl, key=lambda h: h["P"]) if pl else None,
        "pmax": max(pl, key=lambda h: h["P"]) if pl else None,
        "rain": sum(h["R"] for h in R), "groups": groups, "sky": sky, "fog": fog, "snow": snow,
    }


def near(hours, dt):
    c = [h for h in hours if h["T"] is not None]
    return min(c, key=lambda h: abs((h["dt"] - dt).total_seconds())) if c else None


def precip_word(d):
    return "снег" if d["snow"] else "дождь"


def rain_phrase(d):
    """Осадки одной фразой: «дождь около 15:00–18:00, до 1,2 мм» или None."""
    if not d["groups"] or d["rain"] < 0.2:
        return None
    w = precip_word(d)
    gs = d["groups"][:2]
    per = " и ".join("%s–%s" % (hhmm(g["first"]), hhmm(g["last"])) if (g["last"] - g["first"]) >= timedelta(hours=2)
                     else "около %s" % hhmm(g["last"] - timedelta(minutes=30)) for g in gs)
    kind = "небольшой %s" % w if d["rain"] < 1.0 else (w if d["rain"] < 5.0 else "сильный %s" % w)
    return "%s %s, всего ~%s мм" % (kind, per, mm_txt(d["rain"]))


# ---------- утренний выпуск ----------
def morning_headline(rng, d, fo, rain_txt):
    if fo and fo["kind"] == "cold":
        return pick(rng, ["Холодный фронт идёт на Одессу", "К вечеру Одессу накроет холодный фронт"])
    if rain_txt and d["rain"] >= 0.5:
        first = d["groups"][0]
        return pick(rng, ["Сегодня без зонта не обойтись", "%s придёт около %s" % (precip_word(d).capitalize(), hhmm(first["last"] - timedelta(minutes=30)))])
    if d["gmax"] and d["gmax"]["G"] >= 12:
        return "Ветреный день: порывы до %s м/с" % ch.f0(d["gmax"]["G"])
    if d["fog"]:
        return "Утро в тумане: осторожнее на дорогах"
    if d["tmax"] <= 0:
        return "Морозный день: до %s°" % tv(d["tmax"])
    if d["tmax"] >= 28:
        return "Жаркий день: до %s°" % tv(d["tmax"])
    if d["sky"] in ("ясно", "малооблачно"):
        return pick(rng, ["Ясный день впереди", "Одесса сегодня на солнце"])
    return "Одесса сегодня: %s, до %s°" % (d["sky"] or "переменно", tv(d["tmax"]))


def morning_lead(rng, d, fo, rain_txt):
    parts = []
    if d["sky"]:
        parts.append("Небо: %s." % d["sky"])
    if fo and fo["kind"] in ("cold", "warm"):
        parts.append("Давление падает, к %s придёт %s атмосферный фронт: %s." % (
            hhmm(fo["tmin"]), "холодный" if fo["kind"] == "cold" else "тёплый",
            "станет холоднее на ~%s °C и усилится ветер" % ch.f0(abs(fo["dT"])) if fo["kind"] == "cold" and fo["dT"] is not None
            else "потеплеет на ~%s °C" % ch.f0(abs(fo["dT"])) if fo["dT"] is not None else "погода сменится"))
    if rain_txt:
        parts.append("Ожидается %s." % rain_txt)
    else:
        parts.append(pick(rng, ["Осадков не ждём.", "Сухо: зонт можно оставить дома."]))
    return " ".join(parts)


def digit_of_day(d, fo, night):
    if d["gmax"] and d["gmax"]["G"] >= 12:
        return "%s м/с" % ch.f0(d["gmax"]["G"]), "порывы ветра около %s" % hhmm(d["gmax"]["dt"])
    if d["rain"] >= 1.0:
        return "%s мм" % mm_txt(d["rain"]), "столько осадков выпадет за день"
    if fo:
        return "%s гПа" % ch.f1(fo["pmin"]), "минимум давления около %s" % hhmm(fo["tmin"])
    if night and night["spread"] >= 1.5:
        return "%s °C" % ch.f1(night["spread"]), "разница ночных температур между районами"
    amp = d["tmax"] - d["tmin"]
    return "%s °C" % ch.f0(amp), "разница между самым тёплым и самым холодным часом дня"


def night_stats(st, now):
    ln = now.astimezone(KYIV)
    t0 = (ln - timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    mins = []
    for sid, s in st.items():
        v = [o["temp"] for o in s["obs"] if t0 <= o["ts"] <= now and o["temp"] is not None]
        if len(v) >= 6:
            mins.append((min(v), s["name"]))
    if len(mins) < 3:
        return None
    mins.sort()
    return {"cold": mins[0], "warm": mins[-1], "spread": mins[-1][0] - mins[0][0],
            "city": statistics.median(m for m, _ in mins)}


def build_morning(st, hours, now):
    ln = now.astimezone(KYIV)
    rng = random.Random(ln.strftime("%Y-%m-%d") + "m")
    a = ln.replace(hour=7, minute=0, second=0, microsecond=0)
    b = ln.replace(hour=23, minute=0, second=0, microsecond=0)
    d = dayfc(hours, a, b)
    if not d:
        return None, None
    fo = ch.front_outlook(hours, now)
    rain_txt = rain_phrase(d)
    night = night_stats(st, now) if st else None
    h8 = near(hours, a + timedelta(hours=1))
    h20 = near(hours, a + timedelta(hours=13))
    wmx = d["wmax"]["W"] if d["wmax"] else 0
    f_cold = feels(min(h8["T"], d["tmax"]), h8["W"] if h8["W"] is not None else wmx)
    lines = ["🌅 <b>%s</b>" % esc(morning_headline(rng, d, fo, rain_txt)),
             "<i>%s</i>" % date_ru(ln), "",
             esc(morning_lead(rng, d, fo, rain_txt)), "",
             "🌡 Утром %s°, днём до %s°, вечером %s°." % (tv(h8["T"]), tv(d["tmax"]), tv(h20["T"] if h20 else None))]
    lines.append("🧥 Одевайтесь так: %s." % clothes(f_cold))
    if rain_txt:
        lines.append("☔ Зонт нужен: %s." % esc(rain_txt))
    if d["gmax"] and d["gmax"]["G"] >= 8:
        lines.append("💨 Порывы до %s м/с около %s." % (ch.f0(d["gmax"]["G"]), hhmm(d["gmax"]["dt"])))
    if night:
        if night["spread"] >= 1.5:
            lines.append("🌙 Ночью между районами разница %s °C: %s — %s°, %s — %s°." % (
                ch.f1(night["spread"]), esc(night["warm"][1]), tv(night["warm"][0], 1), esc(night["cold"][1]), tv(night["cold"][0], 1)))
        else:
            lines.append("🌙 Ночью по городу около %s°." % tv(night["city"]))
    dg, dtxt = digit_of_day(d, fo, night)
    lines += ["", "🔢 <b>Цифра дня:</b> %s — %s." % (dg, dtxt), ""]
    pro = []
    if d["pmin"] and d["pmax"]:
        pro.append("Давление: %s–%s гПа (минимум около %s)." % (ch.f1(d["pmin"]["P"]), ch.f1(d["pmax"]["P"]), hhmm(d["pmin"]["dt"])))
    seq = []
    for hh in (9, 12, 15, 18, 21):
        x = near(hours, ln.replace(hour=hh, minute=0, second=0, microsecond=0))
        if x:
            seq.append("%02d:00 %s°" % (hh, tv(x["T"])))
    pro.append("Температура: " + ", ".join(seq) + ".")
    if d["wmax"]:
        dr = ch.compass(d["wmax"]["D"]) + " " if d["wmax"]["D"] is not None else ""
        pro.append("Ветер до %s%s м/с около %s%s." % (dr, ch.f0(d["wmax"]["W"]), hhmm(d["wmax"]["dt"]),
                   (", порывы до %s м/с" % ch.f0(d["gmax"]["G"])) if d["gmax"] else ""))
    if rain_txt:
        pro.append("Осадки: пик ~%s мм/ч, всего ~%s мм." % (ch.f1(max(g["peak"] for g in d["groups"])), mm_txt(d["rain"])))
    if fo:
        pro.append("Фронт: %s, минимум давления %s гПа около %s, затем %s °C к %s." % (
            {"cold": "холодный", "warm": "тёплый"}.get(fo["kind"], "барическая ложбина"), ch.f1(fo["pmin"]), hhmm(fo["tmin"]),
            tv(fo["T_after"]), hhmm(fo["t_after"])))
    lines.append("<blockquote expandable><b>Для профи</b>\n%s</blockquote>" % esc("\n".join(pro)))
    lines += ["", "#утро"]
    rec = {"date": ln.strftime("%Y-%m-%d"), "pred_tmax": round(d["tmax"], 1), "pred_rain": round(d["rain"], 2)}
    return "\n".join(lines), rec


# ---------- вечерние итоги ----------
def build_evening(st, hours, now, hist):
    ln = now.astimezone(KYIV)
    rng = random.Random(ln.strftime("%Y-%m-%d") + "e")
    t0 = ln.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    ts = city_series(st, "temp", t0, now + timedelta(minutes=1))
    if len(ts) < 12:
        return None, None
    tmx = max(ts, key=lambda x: x[1])
    tmn = min(ts, key=lambda x: x[1])
    gust = station_extreme(st, "gust", t0, now + timedelta(minutes=1), max)
    ps = city_series(st, "p", t0, now + timedelta(minutes=1))
    pt = {}
    for sid, s in st.items():
        v = [o["ptot"] for o in s["obs"] if o["ts"] >= t0 and o["ptot"] is not None]
        if v:
            pt[s["name"]] = max(v)
    rain_max = max(pt.items(), key=lambda kv: kv[1]) if pt else None
    rain_mean = statistics.mean(pt.values()) if pt else 0.0
    had_rain = bool(rain_max and rain_max[1] >= 0.2)
    g = gust[0] if gust else 0.0

    if had_rain and rain_max[1] >= 1.0:
        head = pick(rng, ["День под дождём: до %s мм" % mm_txt(rain_max[1]), "Одесса мокла весь день: до %s мм" % mm_txt(rain_max[1])])
    elif g >= 12:
        head = "День прошёл на ветру: порывы до %s м/с" % ch.f0(g)
    elif had_rain:
        head = "Дождь заглянул ненадолго: до %s мм" % mm_txt(rain_max[1])
    elif tmx[1] - tmn[1] >= 10:
        head = "Контрастный день: от %s° до %s°" % (tv(tmn[1]), tv(tmx[1]))
    else:
        head = pick(rng, ["Спокойный день: от %s° до %s°" % (tv(tmn[1]), tv(tmx[1])), "День позади: %s° в максимуме" % tv(tmx[1])])
    lines = ["🌙 <b>%s</b>" % esc(head), "<i>%s · итоги дня</i>" % date_ru(ln), ""]
    lines.append("🌡 Днём максимум %s° в %s, минимум %s° в %s." % (tv(tmx[1]), hhmm(tmx[0]), tv(tmn[1]), hhmm(tmn[0])))
    if had_rain:
        lines.append("🌧 Осадки за сутки: до %s мм (%s), в среднем по городу %s мм." % (
            mm_txt(rain_max[1]), esc(rain_max[0]), mm_txt(rain_mean)))
    else:
        lines.append("☀️ Осадков за день не было.")
    if gust and g >= 8:
        lines.append("💨 Самый сильный порыв: %s м/с (%s, %s)." % (ch.f1(g), esc(gust[1]), hhmm(gust[2])))
    else:
        lines.append("💨 Ветер весь день спокойный: порывы не выше %s м/с." % ch.f0(g))
    # прогноз против факта
    today = hist.get("today")
    if today and today.get("date") == ln.strftime("%Y-%m-%d"):
        diff = tmx[1] - today["pred_tmax"]
        if abs(diff) <= 1.0:
            verdict = "в точку"
        elif abs(diff) <= 2.0:
            verdict = "близко"
        else:
            verdict = "промахнулись"
        lines += ["", "🎯 <b>Прогноз против факта.</b> Утром обещали максимум %s°, вышло %s° (%s, разница %s°)." % (
            tv(today["pred_tmax"], 1), tv(tmx[1], 1), verdict, ch.f1(abs(diff)))]
        errs = [abs(x["obs_tmax"] - x["pred_tmax"]) for x in hist.get("days", []) if "obs_tmax" in x] + [abs(diff)]
        errs = errs[-7:]
        if len(errs) >= 3:
            lines.append("За последние %d дн. средняя ошибка прогноза максимума — %s °C." % (len(errs), ch.f1(statistics.mean(errs))))
    # завтра
    tom = (ln + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    dt_ = dayfc(hours, tom.replace(hour=7), tom.replace(hour=23)) if hours else None
    pro = []
    if dt_:
        fo = ch.front_outlook(hours, now)
        r = rain_phrase(dt_)
        bits = ["от %s° до %s°" % (tv(dt_["tmin"]), tv(dt_["tmax"]))]
        if dt_["sky"]:
            bits.append(dt_["sky"])
        bits.append(r if r else "без осадков")
        if dt_["gmax"] and dt_["gmax"]["G"] >= 10:
            bits.append("порывы до %s м/с" % ch.f0(dt_["gmax"]["G"]))
        lines += ["", "🔭 <b>Завтра:</b> " + esc(", ".join(bits)) + "."]
        if fo and fo["kind"] in ("cold", "warm"):
            lines.append("🌀 Ночью-утром придёт %s атмосферный фронт: минимум давления около %s." % (
                "холодный" if fo["kind"] == "cold" else "тёплый", hhmm(fo["tmin"])))
    if ps:
        pmn = min(ps, key=lambda x: x[1])
        pmx = max(ps, key=lambda x: x[1])
        pro.append("Давление за день: %s–%s гПа (минимум в %s, максимум в %s)." % (ch.f1(pmn[1]), ch.f1(pmx[1]), hhmm(pmn[0]), hhmm(pmx[0])))
    pro.append("Максимум температуры по городу (медиана станций): %s °C в %s." % (tv(tmx[1], 1), hhmm(tmx[0])))
    if gust:
        pro.append("Порыв %s м/с: %s, %s." % (ch.f1(g), gust[1], hhmm(gust[2])))
    if pt:
        pro.append("Осадки по районам: " + ", ".join("%s %s" % (k, mm_txt(v)) for k, v in sorted(pt.items(), key=lambda kv: -kv[1])[:4]) + " (мм).")
    lines += ["", "<blockquote expandable><b>Для профи</b>\n%s</blockquote>" % esc("\n".join(pro)), "", "#итоги"]
    return "\n".join(lines), {"date": ln.strftime("%Y-%m-%d"), "obs_tmax": round(tmx[1], 1)}


# ---------- запуск ----------
def load_issue_state():
    try:
        with open(ISSUE_STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_issue_state(s):
    tmp = ISSUE_STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ISSUE_STATE)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    kind = args[0] if args else ""
    if kind not in ("morning", "evening"):
        print("usage: weather_tg_issue.py morning|evening [--dry] [--force]")
        return 2
    dry, force = "--dry" in flags, "--force" in flags
    now = datetime.now(timezone.utc)
    ln = now.astimezone(KYIV)
    target = MORNING_H if kind == "morning" else EVENING_H
    if not force and ln.hour != target:
        return 0   # cron стоит на оба сезона (UTC), лишний запуск молча выходит
    env = ch.load_env()
    if not dry and ("WEATHER_TG_TOKEN" not in env or "WEATHER_TG_CHAT_ID" not in env):
        ch.log("issue: нет токена/канала в %s" % ch.ENV_FILE)
        return 1
    ist = load_issue_state()
    key = ln.strftime("%Y-%m-%d")
    if not force and not dry and ist.get("sent_" + kind) == key:
        return 0
    st = collect(env, now)
    mstate = ch.load_state()   # только чтение: берём свежий кэш Ансамбля
    hours = ch.get_ensemble(mstate, now)
    if kind == "morning":
        if not hours:
            ch.log("issue: Ансамбль не посчитан, утренний выпуск пропущен")
            return 1
        text, rec = build_morning(st, hours, now)
    else:
        text, rec = build_evening(st, hours, now, ist)
    if not text:
        ch.log("issue: %s: мало данных, выпуск пропущен" % kind)
        return 1
    if dry:
        print(text)
        print("--- %d символов" % len(text))
        return 0
    if not ch.tg_send(env, text, ISSUE_SILENT):
        ch.log("issue: %s НЕ отправлен" % kind)
        return 1
    ist["sent_" + kind] = key
    if kind == "morning":
        ist["today"] = rec
    else:
        days = [x for x in ist.get("days", []) if x.get("date") != key]
        t = ist.get("today")
        if t and t.get("date") == key:
            days.append({"date": key, "pred_tmax": t["pred_tmax"], "obs_tmax": rec["obs_tmax"]})
        ist["days"] = days[-HIST_DAYS:]
    save_issue_state(ist)
    ch.log("issue: %s отправлен (%d символов)" % (kind, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
