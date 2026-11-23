# -*- coding: utf-8 -*-
"""Официальная сводка ГМЦ: SYNOP станции Одесса (33837).

Источник: data/synop_<год>.txt в репозитории (CSV: станция,год,мес,день,час,мин,телеграмма),
новый срок раз в 3 часа. Разбор групп повторяет synop.js.
"""
import math
import urllib.request
from datetime import datetime, timezone

STATION = "33837"
URL = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/data/synop_%d.txt"

PRECIP_HOURS = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}


def ww_text(code):
    """Погода в срок (код ww таблицы 4677), кратко по-русски."""
    try:
        c = int(code)
    except Exception:
        return None
    special = {
        10: "дымка", 11: "позёмный туман", 12: "позёмный туман", 17: "гроза без осадков",
        18: "шквал", 19: "смерч", 45: "туман", 46: "туман", 47: "туман", 48: "туман с изморозью",
        49: "туман с изморозью", 50: "слабая морось", 51: "слабая морось", 52: "морось",
        53: "морось", 54: "сильная морось", 55: "сильная морось", 56: "переохлаждённая морось",
        57: "переохлаждённая морось", 58: "морось с дождём", 59: "морось с дождём",
        60: "слабый дождь", 61: "слабый дождь", 62: "умеренный дождь", 63: "умеренный дождь",
        64: "сильный дождь", 65: "сильный дождь", 66: "переохлаждённый дождь",
        67: "переохлаждённый дождь", 68: "дождь со снегом", 69: "дождь со снегом",
        70: "слабый снег", 71: "слабый снег", 72: "умеренный снег", 73: "умеренный снег",
        74: "сильный снег", 75: "сильный снег", 76: "ледяные иглы", 77: "снежные зёрна",
        78: "снежные кристаллы", 79: "ледяной дождь", 80: "слабый ливневой дождь",
        81: "умеренный ливневой дождь", 82: "сильный ливневой дождь",
        83: "ливневой дождь со снегом", 84: "сильный ливневой дождь со снегом",
        85: "слабый ливневой снег", 86: "сильный ливневой снег", 87: "снежная крупа",
        88: "снежная крупа", 89: "град", 90: "град", 91: "слабый дождь после грозы",
        92: "сильный дождь после грозы", 93: "слабый снег/град после грозы",
        94: "сильный снег/град после грозы", 95: "гроза с дождём", 96: "гроза с градом",
        97: "сильная гроза с дождём", 98: "гроза с пыльной бурей", 99: "сильная гроза с градом",
    }
    if c in special:
        return special[c]
    if 40 <= c <= 44:
        return "туман"
    if 20 <= c <= 29:
        return "явления за последний час"
    return None  # 00-09, 13-16, 30-39: без осадков / не значимо


def _signed(g):
    if len(g) != 5 or "/" in g[2:]:
        return None
    try:
        v = int(g[2:5]) / 10.0
    except ValueError:
        return None
    return -v if g[1] == "1" else v


def _pressure(g):
    try:
        p = int(g[1:]) / 10.0
    except ValueError:
        return None
    return p + 1000 if p < 500 else p


def _vis_km(vv):
    try:
        v = int(vv)
    except Exception:
        return None
    if v == 0:
        return 0.05
    if v <= 50:
        return v / 10.0
    if 56 <= v <= 80:
        return float(v - 50)
    if 81 <= v <= 88:
        return float(30 + (v - 80) * 5)
    if v == 89:
        return 70.0
    return None


def humidity(t, td):
    if t is None or td is None:
        return None
    def es(x):
        return math.exp(17.625 * x / (243.04 + x))
    return max(0.0, min(100.0, 100.0 * es(td) / es(t)))


def parse(line):
    parts = line.strip().split()
    i = parts.index("AAXX")
    irixhvv = parts[i + 3] if len(parts) > i + 3 else ""
    wg = parts[i + 4] if len(parts) > i + 4 else ""
    sec = "main"
    body, s333, s555 = [], [], []
    for g in parts[i + 5:]:
        g = g.rstrip("=")
        if g == "333":
            sec = "333"
            continue
        if g == "444":
            sec = "444"
            continue
        if g == "555":
            sec = "555"
            continue
        if not g:
            continue
        if sec == "main":
            body.append(g)
        elif sec == "333":
            s333.append(g)
        elif sec == "555":
            s555.append(g)
    d = {"temp": None, "dew": None, "p_sea": None, "p_sta": None, "tend": None,
         "wind_dir": None, "wind": None, "gust": None, "vis": None, "ww": None,
         "precip": None, "precip_h": None, "precip_trace": False, "daily": None,
         "tmin": None, "tmax": None}
    if len(wg) == 5 and wg.isdigit():
        rd = int(wg[1:3])
        d["wind_dir"] = None if rd in (0, 99) else rd * 10
        d["wind"] = int(wg[3:5])
    if len(irixhvv) == 5 and "/" not in irixhvv[3:5]:
        d["vis"] = _vis_km(irixhvv[3:5])
    import re
    for g in body:
        if re.match(r"^1[01/]\d{3}$", g):
            d["temp"] = _signed(g)
        elif re.match(r"^2[01/]\d{3}$", g):
            d["dew"] = _signed(g)
        elif re.match(r"^3\d{4}$", g):
            d["p_sta"] = _pressure(g)
        elif re.match(r"^4\d{4}$", g):
            d["p_sea"] = _pressure(g)
        elif re.match(r"^5\d{4}$", g):
            v = int(g[2:]) / 10.0
            d["tend"] = -v if g[1] in "5678" else v
        elif re.match(r"^6\d{4}$", g):
            rrr = int(g[1:4])
            d["precip_h"] = PRECIP_HOURS.get(g[4])
            if rrr == 990:
                d["precip"], d["precip_trace"] = 0.0, True
            elif 991 <= rrr <= 999:
                d["precip"] = (rrr - 990) / 10.0
            elif rrr <= 988:
                d["precip"] = float(rrr)
        elif re.match(r"^7\d{4}$", g):
            d["ww"] = g[1:3]
    for g in s333:
        if re.match(r"^1[01]\d{3}$", g):
            d["tmax"] = _signed(g)
        elif re.match(r"^2[01]\d{3}$", g):
            d["tmin"] = _signed(g)
    gusts = []
    for g in s333 + s555:
        if re.match(r"^(907|910|911)\d{2}$", g):
            gusts.append(int(g[3:]))
    if gusts:
        d["gust"] = max(gusts)
    for g in s555:
        if re.match(r"^6\d{4}$", g):
            amt = int(g[1:4])
            d["daily"] = float(amt) if amt <= 988 else None
    d["ww_text"] = ww_text(d["ww"]) if d["ww"] is not None else None
    d["rh"] = humidity(d["temp"], d["dew"])
    return d


def fetch_latest(now_utc, log=print):
    """Последняя телеграмма станции 33837 (dict с полем time в UTC) или None."""
    for year in (now_utc.year, now_utc.year - 1):
        try:
            req = urllib.request.Request(URL % year, headers={"User-Agent": "weather-tg/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception as e:
            log("SYNOP %d: %s" % (year, type(e).__name__))
            continue
        best, best_t = None, None
        for raw in text.split("\n"):
            l = raw.strip()
            if not l.startswith(STATION + ","):
                continue
            p = l.split(",")
            if len(p) < 7:
                continue
            try:
                ts = datetime(int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), tzinfo=timezone.utc)
            except Exception:
                continue
            if best_t is None or ts > best_t:
                best_t, best = ts, ",".join(p[6:]).strip()
        if best:
            try:
                d = parse(best)
            except Exception as e:
                log("SYNOP parse: %s" % type(e).__name__)
                return None
            d["time"] = best_t
            return d
    return None
