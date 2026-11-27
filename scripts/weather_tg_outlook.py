# -*- coding: utf-8 -*-
"""Краткосрочный прогноз в конце поста ГМЦ (когда ничего существенного не ожидается).

Горизонт по часу выхода поста (местное время, сроки ГМЦ 02,05,08,11,14,17,20,23):
  08-14 -> до конца суток;  15-22 -> ближайшие 3 дня;  23, 02, 05 -> остаток ночи и завтра.
Данные: Ансамбль (температура, ветер, порывы, осадки, код погоды) + Open-Meteo (облачность, видимость, влажность)
+ море из weather_tg_issue.sea_facts. Видимость всегда не ниже 0. Текст пишет ИИ, при неудаче собирается шаблон.
"""
import json
import urllib.request
from datetime import datetime, timedelta

import weather_tg_ai as ai

OM_URL = ("https://api.open-meteo.com/v1/forecast?latitude=46.43&longitude=30.74&hourly=cloud_cover,visibility,"
          "relative_humidity_2m&timezone=Europe%2FKyiv&forecast_days=5")
SNOW_CODES = {71, 73, 75, 77, 85, 86}
MAX_LEN = {"day": 330, "3days": 560, "night": 380}


def kind_for(lnow):
    h = lnow.hour
    if 15 <= h <= 22:
        return "3days"
    if 8 <= h <= 14:
        return "day"
    return "night"


def fetch_extra(log):
    """{ 'YYYY-MM-DDTHH': (облачность %, видимость м (>=0), влажность %) }; пусто при сбое."""
    try:
        with urllib.request.urlopen(OM_URL, timeout=20) as r:
            d = json.load(r)["hourly"]
        out = {}
        for i, t in enumerate(d["time"]):
            vis = d["visibility"][i]
            out[t[:13]] = (d["cloud_cover"][i], None if vis is None else max(0.0, vis), d["relative_humidity_2m"][i])
        return out
    except Exception as e:
        log("outlook: Open-Meteo недоступен (%s)" % type(e).__name__)
        return {}


def segments(kind, lnow):
    """[(подпись, начало, конец)] в местном времени."""
    mid = lnow.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "day":
        return [("до конца суток", lnow, mid + timedelta(days=1))]
    if kind == "3days":
        return [("сегодня до конца суток", lnow, mid + timedelta(days=1)),
                ("завтра", mid + timedelta(days=1), mid + timedelta(days=2)),
                ("послезавтра", mid + timedelta(days=2), mid + timedelta(days=3))]
    # ночные посты: остаток ночи до 06:00 и завтрашний день
    if lnow.hour >= 12:   # 23:00 -> ночь до 06:00 следующего дня, «завтра» это следующий день
        night_end = mid + timedelta(days=1, hours=6)
        tomorrow = mid + timedelta(days=1)
    else:                 # 02:00, 05:00 -> «завтра» это сегодняшний день
        night_end = mid + timedelta(hours=6)
        tomorrow = mid
    return [("остаток ночи", lnow, night_end), ("днём и вечером", tomorrow + timedelta(hours=6), tomorrow + timedelta(days=1))]


def cloud_word(c):
    if c is None:
        return None
    if c < 20:
        return "ясно"
    if c < 50:
        return "малооблачно"
    if c < 80:
        return "облачно с прояснениями"
    return "пасмурно"


def wind_word(g):
    return "слабый" if g < 5 else "умеренный" if g < 9 else "сильный"


def seg_facts(label, a, b, hours, extra):
    hs = [h for h in hours if a <= h["dt"] < b]
    if len(hs) < 2:
        return None
    ts = [h["T"] for h in hs if h["T"] is not None]
    ws = [h["W"] for h in hs if h["W"] is not None]
    gs = [h["G"] for h in hs if h["G"] is not None]
    rain = [(h["dt"], h["R"]) for h in hs if h["R"] is not None and h["R"] >= 0.1]
    snow = [h["dt"] for h in hs if h["C"] in SNOW_CODES]
    f = {"label": label, "tmin": min(ts) if ts else None, "tmax": max(ts) if ts else None,
         "w": max(ws) if ws else None, "g": max(gs) if gs else None,
         "rain_sum": sum(r for _, r in rain), "rain_from": rain[0][0] if rain else None, "rain_to": rain[-1][0] if rain else None,
         "snow": bool(snow), "cloud": None, "vis_min": None, "fog": [], "haze": []}
    ex = [(h["dt"], extra.get(h["dt"].strftime("%Y-%m-%dT%H"))) for h in hs]
    ex = [(t, e) for t, e in ex if e]
    if ex:
        cl = [e[0] for _, e in ex if e[0] is not None]
        f["cloud"] = sum(cl) / len(cl) if cl else None
        for t, e in ex:
            vis, rh = e[1], e[2]
            if vis is None:
                continue
            f["vis_min"] = vis if f["vis_min"] is None else min(f["vis_min"], vis)
            if vis < 1000:
                f["fog"].append(t)
            elif vis < 10000 and (rh or 0) > 80:
                f["haze"].append(t)
    return f


def _span(ts):
    if not ts:
        return ""
    a, b = ts[0], ts[-1]
    return "около %s" % a.strftime("%H:%M") if a == b else "с %s до %s" % (a.strftime("%H:%M"), b.strftime("%H:%M"))


def facts_text(segs, sea_line):
    """Факты для ИИ и для шаблона: по строке на отрезок."""
    L = []
    for f in segs:
        p = ["%s:" % f["label"]]
        if f["tmin"] is not None:
            p.append("температура от %d до %d °C" % (round(f["tmin"]), round(f["tmax"])))
        if f["w"] is not None:
            p.append("%s ветер до %d м/с, порывы до %d м/с" % (wind_word(f["w"]), round(f["w"]), round(f["g"] or f["w"])))
        cw = cloud_word(f["cloud"])
        if cw:
            p.append("облачность: %s" % cw)
        if f["rain_sum"] >= 0.5:
            p.append(("осадки %s, всего около %.1f мм" % (_span([f["rain_from"], f["rain_to"]]), f["rain_sum"])).replace(".", ","))
        elif f["snow"]:
            p.append("возможен снег")
        else:
            p.append("осадков не ожидается")
        if f["fog"]:
            vk = "менее 0,1 км" if f["vis_min"] < 100 else ("до %.1f км" % (f["vis_min"] / 1000.0)).replace(".", ",")
            p.append("туман %s, видимость %s" % (_span([f["fog"][0], f["fog"][-1]]), vk))
        elif f["haze"]:
            p.append("дымка %s" % _span([f["haze"][0], f["haze"][-1]]))
        elif f["vis_min"] is not None:
            p.append("видимость хорошая")
        L.append(" ".join(p[:1]) + " " + ", ".join(p[1:]) + ".")
    if sea_line:
        L.append(sea_line)
    return "\n".join(L)


def template(facts):
    return facts   # шаблон = сами факты по отрезкам (читаемы без ИИ)


def ask_ai(facts, kind, recent, log, lnow):
    sys_ = ai.BASE + ("Дан краткосрочный прогноз по отрезкам времени. Напиши связный прогноз для горожанина: 2-3 предложения (для «ближайших 3 дней» до 4), "
                      "по порядку отрезков, без перечисления всех цифр: главное про температуру, ветер, облачность, осадки, туман или дымку если они есть, и море одной фразой, если есть строка о море. "
                      "Не упоминай купание и любые занятия на воде. Не пиши про сейчас, только про будущее. Формат ответа: только JSON {\"outlook\": \"...\"}.")
    pr = "ПРОГНОЗ ПО ОТРЕЗКАМ:\n%s\n" % facts
    if recent:
        pr += "\nНедавние прогнозы (не повторяй конструкции):\n- " + "\n- ".join(r[:160] for r in recent[-3:]) + "\n"
    return ai._ask(sys_, pr + "\nВерни только JSON.", "outlook", facts, MAX_LEN[kind], log)


def outlook_lines(hours, now, state, log, use_ai=True):
    """Строки для блока «Прогноз» в конце поста ГМЦ или None. now: aware UTC/любое, hours: Ансамбль (dt в KYIV)."""
    from weather_tg_ensemble import KYIV
    lnow = now.astimezone(KYIV)
    kind = kind_for(lnow)
    extra = fetch_extra(log)
    segs = [s for s in (seg_facts(l, a, b, hours, extra) for l, a, b in segments(kind, lnow)) if s]
    if not segs:
        return None
    sea_line = None
    try:
        import weather_tg_issue as iss
        sea_line = iss.sea_line(iss.sea_facts(now))
    except Exception as e:
        log("outlook: море недоступно (%s)" % type(e).__name__)
    facts = facts_text(segs, sea_line)
    txt = None
    if use_ai:
        ai.budget(120)
        try:
            txt = ask_ai(facts, kind, state.get("outlooks", []), log, lnow)
        except Exception as e:
            log("outlook: ИИ сбой %s" % type(e).__name__)
    if txt:
        state["outlooks"] = (state.get("outlooks", []) + [txt])[-4:]
        return [txt]
    return [ln for ln in template(facts).split("\n") if ln]
