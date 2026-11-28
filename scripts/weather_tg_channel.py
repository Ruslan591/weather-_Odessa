#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram-канал погоды Одессы (docs/topics/weather_tg_channel.md).

Запуск на VPS по cron каждые 10 минут (/etc/cron.d/weather-tg).
Секреты и ID канала: /opt/weather-tg/tg.env
  WEATHER_TG_TOKEN, WEATHER_TG_CHAT_ID, WU_KEYS (через запятую).
Состояние: /opt/weather-tg/state.json

Модули: weather_tg_ensemble.py (Ансамбль, порт fc-ensemble.js),
        weather_tg_synop.py (официальная сводка ГМЦ, SYNOP 33837).

Правила:
  порыв >= 8 м/с -> предупреждение (со звуком), повтор только при усилении на 4 м/с;
  дождь: начало / конец (со звуком), подтверждение по 2 сводкам станции подряд,
         конец по 3 сухим сводкам подряд, район или «по всему городу»;
  прогноз ТОЛЬКО по Ансамблю: осадки (начало, пик, окончание, сумма), давление
         (минимум) и тип фронта по температуре и ветру;
  аномалии по наблюдениям: давление и температура;
  единый пост (без звука): официальная сводка ГМЦ + данные частных станций + прогноз;
         выходит при каждом новом сроке ГМЦ (раз в 3 часа) и в остальные часы
         только если сейчас порыв или осадки.

Флаги: --dry (ничего не отправлять и не сохранять),
       --digest (принудительно сформировать единый пост),
       --ens (только проверить расчёт Ансамбля и прогнозные строки).
"""
import fcntl
import html
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
import weather_tg_ensemble as ens  # noqa: E402
import weather_tg_synop as synop  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KYIV = ens.KYIV

BASE = os.environ.get("WTG_DIR", "/opt/weather-tg")
ENV_FILE = os.path.join(BASE, "tg.env")
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "run.log")
CACHE_DIR = os.path.join(BASE, "cache")

# Названия районов; поправка давления станции к уровню моря (pws_stations.js)
STATIONS = [
    ("IODESA137", "пос. Котовского"),
    ("IODESA138", "Центр"),
    ("IODESA139", "Среднефонтанская площадь"),
    ("IODESS41", "Адмиральский"),
    ("IODESS44", "Аркадия"),
    ("IODESS16", "Таирова"),
    ("IODESS31", "Южная окраина"),
    ("IODESS37", "Западная часть"),
    ("IKRASN91", "Северная окраина"),
]
# Как говорить о месте: «на Таирова» (решение пользователя 27.11), остальные по правилам русского языка; неизвестное имя остаётся как есть.
STATION_AT = {"Таирова": "на Таирова", "Аркадия": "в Аркадии", "Центр": "в Центре", "Адмиральский": "в Адмиральском",
              "пос. Котовского": "в пос. Котовского", "Западная часть": "в западной части",
              "Среднефонтанская площадь": "на Среднефонтанской площади",
              "Южная окраина": "на южной окраине", "Северная окраина": "на северной окраине"}


def at_station(name):
    return STATION_AT.get(name, name)


# Ближний пригород: в статистику «по городу» входит, но районом города НЕ называется (решение пользователя 25.11.2026).
# Названия для канала (решение пользователя 27.11): IODESS31 (Савиньон, 46.328N 30.680E, ~18 км ЮЮЗ от Центра) = «Южная окраина»,
# IKRASN91 (пос. Степовое, 46.664N 30.805E, ~20 км на север) = «Северная окраина», IODESS37 (Застава) = «Западная часть»,
# IODESA139 (Чудо Город) = «Среднефонтанская площадь». На сайте (pws_page.js, pws_stations.js) прежние названия.
SUBURB_SIDS = {"IKRASN91", "IODESS31"}
# Датчик дождя на станции «Среднефонтанская площадь» (бывш. Чудо Город) даёт ложные импульсы: учитывать его осадки только вместе с другими станциями
# (решение пользователя 26.11.2026). Один такой датчик не создаёт ни «начался дождь», ни «осадки за сутки».
RAIN_UNRELIABLE = {"IODESA139"}


def rain_day(items):
    """Осадки за сутки по станциям: items [(мм, имя, sid)]. Дождь подтверждён, если >=0,2 мм у двух станций и хотя бы
    у одной надёжной. Возвращает ((мм, имя, sid) максимума среди надёжных, число станций) или None."""
    conf = [x for x in items if x[0] is not None and x[0] >= 0.2]
    rel = [x for x in conf if x[2] not in RAIN_UNRELIABLE]
    if len(conf) < 2 or not rel:
        return None
    return max(rel), len(conf)


P_OFFSET = {"IODESA137": -5.3, "IODESA138": 10.3, "IODESA139": 1.2, "IODESS41": 4.2, "IODESS44": -1.8,
            "IODESS16": 1.2, "IODESS31": 17.9, "IODESS37": 8.2, "IKRASN91": -1.5}

GUST_MS = 8.0          # порог порыва, м/с
GUST_STEP = 4.0        # повторное предупреждение при усилении на столько м/с
GUST_QUIET_POLLS = 3   # столько опросов подряд без порывов = эпизод окончен
RAIN_MM_H = 0.1        # порог осадков, мм/ч
RAIN_END_DRY = 3       # сухих сводок подряд для конца дождя
EP_GAP = 6             # допустимый сухой разрыв внутри одного дождя, сводок (~30 мин)
CITY_WIDE_MIN = 3      # «по всему городу»: дождь в >= 3 районах и в более чем половине работающих станций
STALE_MIN = 45         # станция без свежих данных считается офлайн (WU отдаёт данные с задержкой 15-20 мин)
ENS_REFRESH_MIN = 60   # как часто пересчитывать Ансамбль
FC_MIN_MM = 0.1        # осадки в часе прогноза, мм
FC_WARN_HOURS = 3      # предупреждать об осадках, если начало ближе этого
FRONT_DROP_HPA = 3.0   # падение давления до минимума, чтобы говорить о фронте
FRONT_WITHIN_H = 12    # минимум давления должен быть ближе этого (часов)
FRONT_COOLDOWN_H = 8
SYNOP_MAX_AGE_H = 3.5  # старше — не объявляем как новый срок
P_CHANGE_HPA = 3.0     # аномалия: изменение давления за 3 часа
T_CHANGE_C = 4.0       # аномалия: изменение температуры за 1 час
ANOM_COOLDOWN_H = 3

import weather_tg_ai as ai  # noqa: E402

AI_BUDGET_S = 240   # общий бюджет ожидания Gemini на запуск (решение пользователя: до ~5 минут)


def log(msg):
    print("[%s] %s" % (datetime.now(KYIV).strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def load_env():
    env = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def trim_log():
    try:
        if os.path.getsize(LOG_FILE) > 2 * 1024 * 1024:
            with open(LOG_FILE, "rb") as f:
                f.seek(-512 * 1024, os.SEEK_END)
                tail = f.read()
            with open(LOG_FILE, "wb") as f:
                f.write(tail)
    except Exception:
        pass


# ---------------------------------------------------------------- данные

def fetch_station(sid, keys, start):
    for i in range(len(keys)):
        key = keys[(start + i) % len(keys)]
        url = "https://api.weather.com/v2/pws/observations/all/1day?" + urllib.parse.urlencode({
            "stationId": sid, "format": "json", "units": "m",
            "numericPrecision": "decimal", "apiKey": key})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            if not body.strip():
                return []
            return json.loads(body).get("observations") or []
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                continue
            if e.code == 204:
                return []
            log("WU %s: HTTP %s" % (sid, e.code))
            return None
        except Exception as e:
            log("WU %s: %s" % (sid, type(e).__name__))
            return None
    log("WU %s: все ключи отклонены" % sid)
    return None


def parse_obs(o):
    m = o.get("metric") or {}
    try:
        ts = datetime.strptime(o.get("obsTimeUtc", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    gust = m.get("windgustHigh")
    wind = m.get("windspeedAvg")
    pr = m.get("pressureMin")
    if pr is None:
        pr = m.get("pressureMax")
    if m.get("tempAvg") is None:
        return None  # сводка без температуры/ветра/осадков (работает только барометр)
    return {
        "ts": ts,
        "temp": m.get("tempAvg"),
        "hum": o.get("humidityAvg"),
        "wind": None if wind is None else wind / 3.6,
        "gust": None if gust is None else gust / 3.6,
        "dir": o.get("winddirAvg"),
        "p": pr,
        "rate": m.get("precipRate") or 0.0,
        "ptot": m.get("precipTotal"),
    }


def wet_flags(obs):
    """Для каждой сводки: мокрая ли (rate >= порога или прирост precipTotal >= порога)."""
    flags = []
    prev = None
    for o in obs:
        d = 0.0
        dt = None
        if prev is not None:
            dt = max((o["ts"] - prev["ts"]).total_seconds() / 3600.0, 5.0 / 60.0)
            if o["ptot"] is not None and prev["ptot"] is not None:
                d = o["ptot"] - prev["ptot"] if o["ptot"] >= prev["ptot"] else o["ptot"]
        o["dp"] = d
        inten = o["rate"] or 0.0
        if dt:
            inten = max(inten, d / dt)
        o["int"] = inten
        flags.append((o["rate"] or 0.0) >= RAIN_MM_H or d >= RAIN_MM_H)
        prev = o
    return flags


def delta(obs, key, minutes, tol_min=12):
    last = obs[-1]
    target = last["ts"] - timedelta(minutes=minutes)
    best = min(obs, key=lambda o: abs((o["ts"] - target).total_seconds()))
    if abs((best["ts"] - target).total_seconds()) > tol_min * 60:
        return None
    if best.get(key) is None or last.get(key) is None:
        return None
    return last[key] - best[key]


def f1(x):
    return ("%.1f" % x).replace(".", ",")


def f0(x):
    return "%d" % round(x)


def compass(deg):
    names = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    return names[int((deg + 22.5) // 45) % 8]


def mean_dir(items):
    x = sum(s * math.sin(math.radians(d)) for d, s in items)
    y = sum(s * math.cos(math.radians(d)) for d, s in items)
    if abs(x) < 1e-6 and abs(y) < 1e-6:
        return None
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def city_wide(n, total):
    return n >= CITY_WIDE_MIN and n > total / 2.0


def esc(s):
    return html.escape(str(s))


def now_summary(ok):
    """Строка «сейчас» по городу (медианы по станциям)."""
    def med(key):
        v = [s[key] for s in ok if s.get(key) is not None]
        return statistics.median(v) if v else None
    parts = []
    t = med("temp")
    if t is not None:
        parts.append("%s °C" % f0(t))
    w = med("wind")
    if w is not None:
        items = [(s["dir"], s["wind"]) for s in ok if s.get("dir") is not None and s.get("wind") is not None]
        md = mean_dir(items) if items else None
        parts.append("ветер %s%s м/с" % ((compass(md) + " ") if md is not None else "", f0(w)))
    g = max([s["gust"] for s in ok if s.get("gust") is not None] or [None]) if ok else None
    if g is not None:
        parts.append("порывы до %s м/с" % f1(g))
    p = med("p")
    if p is not None:
        parts.append("давление %s гПа" % f0(p))
    h = med("hum")
    if h is not None:
        parts.append("влажность %s%%" % f0(h))
    return ", ".join(parts)


def hhmm(dt):
    return dt.astimezone(KYIV).strftime("%H:%M")


# ---------------------------------------------------------------- отправка

def tg_send(env, text, silent):
    data = urllib.parse.urlencode({
        "chat_id": env["WEATHER_TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "disable_notification": "true" if silent else "false",
        "disable_web_page_preview": "true"}).encode()
    url = "https://api.telegram.org/bot%s/sendMessage" % env["WEATHER_TG_TOKEN"]
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
                j = json.loads(r.read().decode())
                return (j.get("result", {}).get("message_id") or True) if j.get("ok") else False   # id сообщения (для ссылок), True если id нет
        except urllib.error.HTTPError as e:
            log("TG HTTP %s" % e.code)
        except Exception as e:
            log("TG %s" % type(e).__name__)
        time.sleep(2)
    return False


def tg_send_photo(env, png, caption, silent):
    b = "----wtg%d" % int(time.time() * 1000)
    parts = []
    for k, v in (("chat_id", env["WEATHER_TG_CHAT_ID"]), ("caption", caption if len(caption) <= 1000 else caption[:caption.rfind("\n", 0, 1000)]), ("parse_mode", "HTML"),
                 ("disable_notification", "true" if silent else "false")):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"card.png\"\r\n"
                  "Content-Type: image/png\r\n\r\n" % b).encode() + png + b"\r\n")
    parts.append(("--%s--\r\n" % b).encode())
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendPhoto" % env["WEATHER_TG_TOKEN"],
                                 data=b"".join(parts), headers={"Content-Type": "multipart/form-data; boundary=" + b})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except urllib.error.HTTPError as e:
        log("TG photo HTTP %s %s" % (e.code, e.read()[:200]))
    except Exception as e:
        log("TG photo %s" % type(e).__name__)
    return False


def card_data(ok, raining, now, epi):
    """Данные для карточки PWS (медианы по частным станциям)."""
    def med(key):
        v = [s[key] for s in ok if s.get(key) is not None]
        return statistics.median(v) if v else None
    items = [(s["dir"], s["wind"]) for s in ok if s.get("dir") is not None and s.get("wind") is not None]
    dp = [d for d in (delta(s["obs"], "p", 180) for s in ok) if d is not None]
    g = max([s["gust"] for s in ok if s.get("gust") is not None] or [0.0])
    d = {"title": "В среднем по городу", "subtitle": "Частные метеостанции",
         "badge": "обновлено %s" % hhmm(now),
         "temp": med("temp"), "hum": med("hum"), "wind": med("wind"), "gust": g,
         "wind_dir": mean_dir(items) if items else None, "pressure": med("p"),
         "p_trend": statistics.median(dp) if len(dp) >= 3 else None, "lines": []}
    import weather_tg_card as _card
    d["feels"] = _card.feels_like(d["temp"], d["wind"], d["hum"])
    daily = [s["ptot"] for s in ok if s.get("ptot") is not None]
    d["rain_total"] = max(daily) if daily else 0.0
    d["rain_total_sub"] = "за сутки, макс. по районам"
    if raining:
        d["rain_rate"] = max(s["int"] for s in raining)
    return d


def gmc_data(sy):
    t = sy["time"]
    lines = []
    if sy.get("precip") is not None and (sy["precip"] > 0 or sy.get("precip_trace")):
        amt = "следы" if sy.get("precip_trace") and sy["precip"] == 0 else "%s мм" % f1(sy["precip"])
        lines.append("Осадки%s: %s" % ((" за %d ч" % sy["precip_h"]) if sy.get("precip_h") else "", amt))
    if sy.get("daily") is not None and sy["daily"] > 0:
        lines.append("Суточная сумма осадков: %s мм" % f0(sy["daily"]))
    ww = sy.get("ww_text") or ""
    return {"obs_local": t.astimezone(KYIV).strftime("%d.%m %H:%M"), "obs_utc": t.strftime("%H:%M"),
            "temp": sy.get("temp"), "hum": sy.get("rh"), "wind": sy.get("wind"), "wind_dir": sy.get("wind_dir"),
            "gust": sy.get("gust"), "pressure": sy.get("p_sea"), "p_trend": sy.get("tend"),
            "n_total": sy.get("n_total"), "cloud_txt": synop.cloud_text(sy.get("n_total")), "vis": sy.get("vis"),
            "ww_known": sy.get("ww") is not None, "ww_text": ww, "rain": any(x in ww for x in ("дожд", "морос", "ливн", "гроз", "снег", "лив")),
            "lines": lines}


def caption_pws(ok, raining, gusty, now, epi, fb):
    L = ["📡 <b>Частные метеостанции, %s</b>" % hhmm(now)]
    pl = private_lines(ok, raining, gusty, now, epi)
    if pl and pl[0].startswith("🌡"):
        pl = pl[1:]
    L += pl
    if fb:
        L.append("")
        L.append("🔮 <b>Прогноз</b>")
        L += fb
    return "\n".join(L)


def caption_gmc(sy, now):
    ol = official_lines(sy, now)
    L = [ol[0]]
    if ol and ol[-1].startswith("🌧"):
        L.append(ol[-1])
    return "\n".join(L)


# ---------------------------------------------------------------- основной цикл


def wet_episode(obs, flags):
    """Последний дождь станции: начало, накопленная сумма (мм), время последней мокрой сводки."""
    last_i = len(obs) - 1
    e = None
    for k in range(last_i, -1, -1):
        if flags[k]:
            e = k
            break
    if e is None:
        return None
    start = e
    dry = 0
    for j in range(e - 1, -1, -1):
        if flags[j]:
            start = j
            dry = 0
        else:
            dry += 1
            if dry > EP_GAP:
                break
    acc = sum(obs[k]["dp"] for k in range(start, last_i + 1))
    return {"start": obs[start]["ts"], "acc": acc, "last_wet": obs[e]["ts"]}


def parse_iso(t):
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rain_again_header(now, start, lead_txt, end_iso):
    """Заголовок прогноза осадков со связкой с недавним окончанием дождя (меньше 2 ч назад), иначе None.
    До часа между концом и новым началом: «Осадки возобновятся», до двух часов: «Снова ожидаются осадки»."""
    try:
        t_end = parse_iso(end_iso)
    except Exception:
        return None
    if now < t_end or now - t_end > timedelta(hours=2):
        return None
    when = max(start, now)
    word = "Осадки возобновятся" if when - t_end <= timedelta(hours=1) else "Снова ожидаются осадки"
    return "☔ <b>%s</b> %s, около %s." % (word, lead_txt, hhmm(when))


# ---------------------------------------------------------------- Ансамбль: часы и прогнозные выводы

def get_ensemble(state, now, source=None, force=False):
    c = state.get("ens")
    hours = None
    if c:
        try:
            hours = [{"dt": datetime.fromisoformat(r[0]).replace(tzinfo=KYIV), "T": r[1], "P": r[2],
                      "W": r[3], "G": r[4], "D": r[5], "R": r[6], "C": r[7]} for r in c["h"]]
            age = (now - parse_iso(c["t"])).total_seconds() / 60.0
            if age < ENS_REFRESH_MIN and not force:
                return hours
        except Exception:
            hours = None
    new = ens.compute_ensemble(now.astimezone(KYIV), CACHE_DIR, model_source=source, log=log)
    if new:
        state["ens"] = {"t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "h": [[h["dt"].strftime("%Y-%m-%dT%H:%M"), h["T"], h["P"], h["W"], h["G"],
                               h["D"], h["R"], h["C"]] for h in new]}
        return new
    return hours


def ens_window(hours, now):
    idx = 0
    for i, h in enumerate(hours):
        if h["dt"] <= now:
            idx = i
    return hours[idx: idx + 25]


def rain_outlook(hours, now, horizon_h=24):
    """Первый эпизод осадков по Ансамблю: начало, конец, пик, сумма, остаток."""
    seq = []
    for h in hours:
        if h["R"] is None:
            continue
        end = h["dt"]
        begin = end - timedelta(hours=1)
        if end > now and begin < now + timedelta(hours=horizon_h):
            seq.append((begin, end, h["R"]))
    ep = []
    dry = 0
    started = False
    broke = False
    for b, e, mm in seq:
        if mm >= FC_MIN_MM:
            started = True
            dry = 0
            ep.append((b, e, mm))
        elif started:
            dry += 1
            if dry >= 2:
                broke = True
                break
            ep.append((b, e, mm))
    while ep and ep[-1][2] < FC_MIN_MM:
        ep.pop()
    if not ep:
        return None
    imax = max(range(len(ep)), key=lambda i: ep[i][2])
    pm = ep[imax][2]
    lo = hi = imax
    while lo > 0 and ep[lo - 1][2] >= 0.9 * pm:
        lo -= 1
    while hi < len(ep) - 1 and ep[hi + 1][2] >= 0.9 * pm:
        hi += 1
    remaining = 0.0
    for b, e, mm in ep:
        frac = min(1.0, max(0.0, (e - max(b, now)).total_seconds() / 3600.0))
        remaining += mm * frac
    beyond = (not broke) and ep[-1][1] == seq[-1][1]
    return {"start": ep[0][0], "end": ep[-1][1], "peak_b": ep[lo][0], "peak_e": ep[hi][1],
            "peak_rate": pm, "total": sum(x[2] for x in ep), "remaining": remaining, "beyond": beyond}


def angdiff(a, b):
    return ((b - a + 540) % 360) - 180


def front_outlook(hours, now):
    """Минимум давления и тип фронта (по Ансамблю): холодный, тёплый или ложбина."""
    ser = [h for h in ens_window(hours, now) if h["P"] is not None and h["T"] is not None]
    if len(ser) < 8:
        return None
    p0 = ser[0]["P"]
    imin = min(range(1, len(ser)), key=lambda i: ser[i]["P"])
    pmin = ser[imin]["P"]
    if p0 - pmin < FRONT_DROP_HPA:
        return None
    if ser[imin]["dt"] - now > timedelta(hours=FRONT_WITHIN_H):
        return None
    falling_on = imin >= len(ser) - 2
    ib = max(0, imin - 3)
    ia = min(len(ser) - 1, imin + 6)
    kind = "trough"
    dT = None
    if ia - imin >= 2:
        dT = ser[ia]["T"] - ser[ib]["T"]
        db, da = ser[ib]["D"], ser[ia]["D"]
        veer = angdiff(db, da) if (db is not None and da is not None) else 0
        rise = max(ser[i + 1]["P"] - ser[i]["P"] for i in range(imin, ia))
        if dT <= -3.0 or (dT <= -1.5 and veer >= 45 and rise >= 1.0):
            kind = "cold"
        elif dT >= 2.5:
            kind = "warm"
    gw = [ser[i] for i in range(max(0, imin - 3), min(len(ser), imin + 10)) if ser[i]["G"] is not None]
    g = max(gw, key=lambda h: h["G"]) if gw else None
    rise_after = ser[min(imin + 3, len(ser) - 1)]["P"] - pmin
    return {"kind": kind, "pmin": pmin, "tmin": ser[imin]["dt"], "drop": p0 - pmin,
            "falling_on": falling_on, "rise_after": rise_after, "dT": dT,
            "T_after": ser[ia]["T"], "t_after": ser[ia]["dt"], "dir_after": ser[ia]["D"],
            "gust": g["G"] if g else None, "gust_t": g["dt"] if g else None}


KIND_NAME = {"cold": "холодный атмосферный фронт", "warm": "тёплый атмосферный фронт",
             "trough": "барическая ложбина (область пониженного давления)"}


def front_text(fo):
    L = []
    first = "Приближается %s." % KIND_NAME[fo["kind"]]
    if fo["falling_on"]:
        rest = " Давление продолжит снижаться как минимум до %s (ниже %s гПа)." % (
            hhmm(fo["tmin"]), f1(fo["pmin"]))
    else:
        rest = " Минимальное давление %s гПа ожидается около %s%s." % (
            f1(fo["pmin"]), hhmm(fo["tmin"]), ", затем рост" if fo["rise_after"] >= 1.0 else "")
    L.append("🌀 <b>%s</b>%s" % (first, rest))
    parts = []
    if fo["kind"] in ("cold", "warm") and fo["dT"] is not None:
        parts.append("%s температуры на ~%s °C (до %s °C к %s)" % (
            "понижение" if fo["dT"] < 0 else "повышение", f0(abs(fo["dT"])), f0(fo["T_after"]),
            hhmm(fo["t_after"])))
        if fo["dir_after"] is not None:
            parts.append("ветер повернёт на %s" % compass(fo["dir_after"]))
    if fo["gust"] is not None and fo["gust"] >= GUST_MS:
        parts.append("порывы до %s м/с около %s" % (f0(fo["gust"]), hhmm(fo["gust_t"])))
    if parts:
        L.append("Ожидается: " + ", ".join(parts) + ".")
    return L


def rain_text_upcoming(ro):
    s = "🌧 Осадки: с %s до ~%s" % (hhmm(ro["start"]), hhmm(ro["end"]))
    if ro["beyond"]:
        s = "🌧 Осадки: с %s, до конца прогнозного периода" % hhmm(ro["start"])
    s += "; наибольшая интенсивность ~%s мм/ч (%s–%s); всего ~%s мм." % (
        f1(ro["peak_rate"]), hhmm(ro["peak_b"]), hhmm(ro["peak_e"]), f1(ro["total"]))
    return s


def current_rate(hours, now):
    """Прогнозная интенсивность (мм/ч) в текущем часе и время, до которого она сохранится."""
    cur = None
    idx = None
    for i, h in enumerate(hours):
        if h["R"] is not None and h["dt"] - timedelta(hours=1) <= now < h["dt"]:
            cur, idx = h["R"], i
            break
    if cur is None:
        return None, None
    run_end = hours[idx]["dt"]
    tol = max(0.1, 0.3 * cur)
    for h in hours[idx + 1:]:
        if h["R"] is None or abs(h["R"] - cur) > tol:
            break
        run_end = h["dt"]
    return cur, run_end


def rain_text_ongoing(ro, now, hours, peak=None):
    """Текст про идущий дождь: конец, пик, текущая интенсивность, остаток. Короткими предложениями."""
    if ro["beyond"]:
        out = ["⏱ По прогнозу осадки продолжатся не менее чем до %s." % hhmm(ro["end"])]
    else:
        out = ["⏱ По прогнозу осадки закончатся около %s." % hhmm(ro["end"])]
    cur, run_end = current_rate(hours or [], now)
    keep = None   # «сохранится на этом уровне до ...»
    if cur is not None and cur >= 0.05 and run_end is not None:
        keep = "до конца осадков" if run_end >= ro["end"] else "до %s" % hhmm(run_end)
    s2 = None
    if peak:
        pv = " (~%s мм/ч)" % f1(peak["value"]) if peak.get("value") else ""
        if peak["recent"]:
            s2 = "Сейчас наблюдается пик интенсивности%s" % pv
            cur, keep = None, None
        else:
            if peak["e"] - peak["b"] >= timedelta(minutes=30):
                s2 = "Пик интенсивности пришёлся на период с %s до %s%s" % (hhmm(peak["b"]), hhmm(peak["e"]), pv)
            else:
                s2 = "Пик интенсивности пришёлся на %s%s" % (hhmm(peak["t"]), pv)
            if cur is not None and cur >= 0.05:
                if peak.get("value") and cur < peak["value"] - 0.05:
                    s2 += ", сейчас она снизилась до ~%s мм/ч" % f1(cur)
                else:
                    s2 += ", сейчас ~%s мм/ч" % f1(cur)
                if keep:
                    s2 += " и сохранится на этом уровне %s" % keep
    elif cur is not None and cur >= 0.05:
        s2 = "Сейчас интенсивность ~%s мм/ч" % f1(cur)
        if keep:
            s2 += ", она сохранится на этом уровне %s" % keep
    if s2:
        out.append(s2 + ".")
    if ro["peak_b"] > now and ro["peak_rate"] >= 1.5 * max(cur or 0.0, 0.1):
        out.append("Усиление до ~%s мм/ч ожидается с %s до %s." % (f1(ro["peak_rate"]), hhmm(ro["peak_b"]), hhmm(ro["peak_e"])))
    if ro["remaining"] >= 0.1:
        out.append("До окончания осадков ожидается ещё ~%s мм." % f1(ro["remaining"]))
    return " ".join(out)


def episode_info(ok, state, now):
    """Текущий дождь по городу: стабильное начало, накопленная сумма (по станциям эпизода)."""
    ep_st = [s for s in ok if s.get("ep") and (now - s["ep"]["last_wet"]) <= timedelta(minutes=90)]
    if not ep_st:
        return None
    start = min(s["ep"]["start"] for s in ep_st)
    prev = state.get("ep_start")
    if prev:
        try:
            start = min(start, parse_iso(prev))
        except Exception:
            pass
    best = max(ep_st, key=lambda s: s["ep"]["acc"])
    return {"start": start, "acc": best["ep"]["acc"], "name": best["name"],
            "mean": statistics.mean(s["ep"]["acc"] for s in ep_st), "stations": ep_st}


def observed_peak(epi, now):
    """Когда по наблюдениям частных станций дождь был сильнее всего (по 10-минутным интервалам)."""
    if not epi:
        return None
    buckets = {}
    best_t = {}
    for s in epi["stations"]:
        for o in s["obs"]:
            if o["ts"] < epi["start"]:
                continue
            k = o["ts"].replace(minute=(o["ts"].minute // 10) * 10, second=0, microsecond=0)
            if o["int"] > buckets.get(k, 0.0):
                buckets[k] = o["int"]
                best_t[k] = o["ts"]
    if not buckets:
        return None
    ks = sorted(buckets)
    pk = max(ks, key=lambda k: buckets[k])
    pv = buckets[pk]
    if pv < RAIN_MM_H:
        return None
    i = ks.index(pk)
    lo = hi = i
    thr = 0.75 * pv
    step = timedelta(minutes=10)
    while lo > 0 and ks[lo - 1] == ks[lo] - step and buckets[ks[lo - 1]] >= thr:
        lo -= 1
    while hi < len(ks) - 1 and ks[hi + 1] == ks[hi] + step and buckets[ks[hi + 1]] >= thr:
        hi += 1
    end = ks[hi] + step
    return {"t": best_t[pk], "b": ks[lo], "e": end, "value": pv,
            "recent": (now - end) <= timedelta(minutes=15)}


# ---------------------------------------------------------------- единый пост: ГМЦ + частные станции + прогноз

def official_lines(sy, now):
    t = sy["time"]
    age = (now - t).total_seconds() / 3600.0
    head = "🏛 <b>Официальная сводка ГМЦ</b> (Одесса), наблюдения %s (%s UTC)" % (
        hhmm(t), t.strftime("%H:%M"))
    if age > SYNOP_MAX_AGE_H + 1:
        head += " ⚠ данные устарели (%d ч назад)" % round(age)
    L = [head]
    p1 = []
    if sy["temp"] is not None:
        p1.append("🌡 %s °C" % f1(sy["temp"]))
    if sy["rh"] is not None:
        p1.append("влажность %s%%" % f0(sy["rh"]))
    if sy["p_sea"] is not None:
        s = "давление %s гПа" % f1(sy["p_sea"])
        if sy["tend"] is not None:
            if abs(sy["tend"]) < 0.1:
                s += " (за 3 ч без изменений)"
            elif sy["tend"] < 0:
                s += " (за 3 ч упало на %s гПа)" % f1(abs(sy["tend"]))
            else:
                s += " (за 3 ч выросло на %s гПа)" % f1(sy["tend"])
        p1.append(s)
    if p1:
        L.append(" · ".join(p1))
    p2 = []
    if sy["wind"] is not None:
        if sy["wind"] == 0:
            s = "💨 штиль"
        else:
            s = "💨 ветер %s%s м/с" % ((compass(sy["wind_dir"]) + " ") if sy["wind_dir"] is not None else "", f0(sy["wind"]))
        if sy["gust"] is not None:
            s += ", порывы до %s м/с" % f0(sy["gust"])
        p2.append(s)
    if sy["vis"] is not None:
        p2.append("видимость %s км" % (f1(sy["vis"]) if sy["vis"] < 10 else f0(sy["vis"])))
    if p2:
        L.append(" · ".join(p2))
    if sy.get("n_total") is not None:
        cl = "☁ облачность %d/8, %s" % (sy["n_total"], synop.cloud_text(sy["n_total"])) if sy["n_total"] < 9 else "☁ %s" % synop.cloud_text(9)
        if sy.get("base_m") and 0 < (sy["n_total"] or 0) < 9:
            cl += ", нижняя граница %s" % sy["base_m"]
        L.append(cl)
    p3 = []
    if sy.get("ww_text"):
        p3.append("В момент наблюдения %s" % sy["ww_text"])
    elif sy.get("ww") is not None:
        p3.append("в момент наблюдения явлений нет")
    if sy["precip"] is not None and (sy["precip"] > 0 or sy["precip_trace"]):
        amt = "следы" if sy["precip_trace"] and sy["precip"] == 0 else "%s мм" % f1(sy["precip"])
        p3.append("осадки%s: %s" % ((" за %d ч" % sy["precip_h"]) if sy["precip_h"] else "", amt))
    if sy["daily"] is not None and sy["daily"] > 0:
        p3.append("суточная сумма осадков: %s мм" % f0(sy["daily"]))
    if p3:
        L.append("🌧 " + "; ".join(p3) + ".")
    return L


def private_lines(ok, raining, gusty, now, epi):
    out = []
    parts = []
    temps = sorted(s["temp"] for s in ok if s["temp"] is not None)
    if temps:
        lo, hi = temps[0], temps[-1]
        parts.append("🌡 %s °C" % (f0(lo) if round(lo) == round(hi) else "%s…%s" % (f0(lo), f0(hi))))
    ws = [s for s in ok if s.get("wind") is not None]
    if ws:
        items = [(s["dir"], s["wind"]) for s in ws if s.get("dir") is not None]
        md = mean_dir(items) if items else None
        parts.append("💨 ветер %s%s м/с" % ((compass(md) + " ") if md is not None else "",
                                           f0(statistics.median(s["wind"] for s in ws))))
    ps = [s["p"] for s in ok if s.get("p") is not None]
    if ps:
        parts.append("давление %s гПа" % f0(statistics.median(ps)))
    hs = [s["hum"] for s in ok if s.get("hum") is not None]
    if hs:
        parts.append("влажность %s%%" % f0(statistics.median(hs)))
    if parts:
        out.append(" · ".join(parts))
    if gusty:
        out.append("💨 Порывы ≥ %s м/с: %s." % (f0(GUST_MS), "; ".join(
            "%s %s" % (esc(s["name"]), f1(s["gust"])) for s in gusty[:5])))
    if raining:
        rs_ = sorted(raining, key=lambda s: -s["int"])
        if city_wide(len(rs_), len(ok)):
            out.append("🌧 Дождь по всему городу, сильнее: %s." % (
                ", ".join("%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in rs_[:3])))
        else:
            out.append("🌧 Дождь: %s." % ", ".join("%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in rs_))
        if epi:
            out.append("Дождь идёт с %s: выпало до %s мм (%s), в среднем %s мм." % (
                hhmm(epi["start"]), f1(epi["acc"]), esc(epi["name"]), f1(epi["mean"])))
    elif not gusty:
        out.append("Порывов и осадков сейчас нет.")
    daily = [(s["ptot"], s["name"]) for s in ok if s.get("ptot") is not None and s["ptot"] >= 0.1]
    if daily:
        best = max(daily)
        out.append("За сутки (с 00:00): до %s мм (%s)." % (f1(best[0]), esc(best[1])))
    return out


def forecast_block(hours, ro, fo, raining, now, peak=None):
    L = []
    if fo:
        L += front_text(fo)
    if raining:
        if ro:
            L.append(rain_text_ongoing(ro, now, hours, peak))
        elif hours:
            L.append("⏱ По прогнозу значимых осадков в ближайшие часы нет.")
    elif ro and ro["start"] < now + timedelta(hours=12):
        L.append(rain_text_upcoming(ro))
    return L


def build_digest(ok, raining, gusty, sy, hours, ro, fo, now, official, epi=None, peak=None):
    lnow = now.astimezone(KYIV)
    L = ["📋 <b>Сводка по Одессе, %s</b>" % lnow.strftime("%H:%M")]
    if official and sy:
        L += official_lines(sy, now)
        L.append("")
    fb = forecast_block(hours, ro, fo, raining, now, peak)
    if fb:
        L.append("🔮 <b>Прогноз</b>")
        L += fb
    return "\n".join(L).strip()


def main():
    args = set(sys.argv[1:])
    if "--dry" not in args and "--card" not in args:
        _lk = open(os.path.join(BASE, "main.lock"), "w")
        try:
            fcntl.flock(_lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("предыдущий запуск ещё идёт (ожидание Gemini), пропуск")
            return 0
    dry = "--dry" in args
    force_digest = "--digest" in args
    ens_only = "--ens" in args
    env = load_env()
    now = datetime.now(timezone.utc)
    lnow = now.astimezone(KYIV)
    state = load_state()

    source = None
    mc = os.environ.get("WTG_MODEL_CACHE")  # тесты: кэш моделей из репозитория вместо Open-Meteo
    if mc:
        _c = json.load(open(mc))
        source = lambda mid: (_c["models"].get(mid) or {}).get("hours")

    if ens_only:
        hours = get_ensemble(state, now, source, force=True)
        if not hours:
            print("ансамбль не посчитан")
            return 1
        day = [h for h in hours if h["dt"].strftime("%Y-%m-%d") == lnow.strftime("%Y-%m-%d") and h["P"] is not None]
        if day:
            pmin = min(day, key=lambda h: h["P"])
            pmax = max(day, key=lambda h: h["P"])
            print("сегодня (%d ч): минимум %s гПа в %s, максимум %s гПа в %s, среднее %s" % (
                len(day), f1(pmin["P"]), hhmm(pmin["dt"]), f1(pmax["P"]), hhmm(pmax["dt"]),
                f1(statistics.mean(h["P"] for h in day))))
        ro = rain_outlook(hours, now)
        fo = front_outlook(hours, now)
        print("--- прогнозные строки ---")
        for l in forecast_block(hours, ro, fo, False, now):
            print(l)
        return 0

    if not dry and ("WEATHER_TG_TOKEN" not in env or "WEATHER_TG_CHAT_ID" not in env):
        log("нет WEATHER_TG_TOKEN / WEATHER_TG_CHAT_ID в %s" % ENV_FILE)
        return 1
    keys = [k for k in env.get("WU_KEYS", "").split(",") if k]
    if not keys:
        log("нет WU_KEYS в %s" % ENV_FILE)
        return 1
    start = int(time.time() // 600)

    # 1. частные станции
    st = {}
    for sid, name in STATIONS:
        raw = fetch_station(sid, keys, start)
        time.sleep(0.3)
        obs = [p for p in (parse_obs(o) for o in (raw or [])) if p]
        obs.sort(key=lambda o: o["ts"])
        if not obs:
            st[sid] = {"name": name, "ok": False}
            continue
        flags = wet_flags(obs)
        last = obs[-1]
        age = (now - last["ts"]).total_seconds() / 60.0
        if age > STALE_MIN:
            st[sid] = {"name": name, "ok": False, "age": age}
            continue
        recent = obs[-2:]
        gobs = max(recent, key=lambda o: o["gust"] or 0)
        st[sid] = {
            "name": name, "ok": True, "age": age, "obs": obs,
            "temp": last["temp"], "hum": last["hum"], "wind": last["wind"],
            "p": (last["p"] + P_OFFSET.get(sid, 0.0)) if last["p"] is not None else None,
            "dir": last["dir"], "gust": gobs["gust"] or 0.0,
            "gust_dir": gobs["dir"], "wind_at_gust": gobs["wind"],
            "int": max(o["int"] for o in recent),
            "ptot": last["ptot"],
            "ep": wet_episode(obs, flags),
            "wet2": len(flags) >= 2 and flags[-1] and flags[-2],
            "dryN": len(flags) >= RAIN_END_DRY and not any(flags[-RAIN_END_DRY:]),
        }
    ok = [s for s in st.values() if s["ok"]]
    if not ok:
        log("нет данных ни по одной станции")
        return 1

    # 2. состояние дождя по станциям
    rs = state.setdefault("rain", {})
    for sid, s in st.items():
        if not s["ok"]:
            rs[sid] = False
        elif s["wet2"]:
            rs[sid] = True
        elif s["dryN"]:
            rs[sid] = False
        else:
            rs.setdefault(sid, False)
    raining_ids = [sid for sid, s in st.items() if s["ok"] and rs.get(sid)]
    if raining_ids and all(sid in RAIN_UNRELIABLE for sid in raining_ids):
        raining_ids = []   # один ненадёжный датчик дождя не считается
    raining = [st[sid] for sid in raining_ids]
    gusty = sorted([s for s in ok if s["gust"] >= GUST_MS], key=lambda s: -s["gust"])

    # 3. эпизод дождя по городу (стабильное начало) и наблюдаемый пик
    epi = episode_info(ok, state, now) if (raining or state.get("rain_city")) else None
    if epi:
        state["ep_start"] = epi["start"].strftime("%Y-%m-%dT%H:%M:%SZ")
    peak = observed_peak(epi, now) if (epi and raining) else None
    if not raining and not state.get("rain_city"):
        state.pop("ep_start", None)

    # 3б. Ансамбль и официальная сводка ГМЦ
    hours = get_ensemble(state, now, source)
    ro = rain_outlook(hours, now) if hours else None
    fo = front_outlook(hours, now) if hours else None
    sy = synop.fetch_latest(now, log=log)

    alerts = []   # (text, silent)

    # 4. дождь: начало / конец
    end_idx, end_head = None, None   # конец дождя в этом запуске (для склейки с прогнозом новых осадков)
    city_active = state.get("rain_city", False)
    if raining and not city_active:
        raining.sort(key=lambda s: -s["int"])
        n = len(raining)
        if city_wide(n, len(ok)):
            top = ", ".join("%s — %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in raining[:3])
            txt = "🌧 <b>Дождь по всему городу.</b>\nСильнее всего: %s." % top
        elif n == 1:
            txt = "🌧 <b>Начался дождь:</b> %s (%s мм/ч)." % (esc(raining[0]["name"]), f1(raining[0]["int"]))
        else:
            lst = ", ".join("%s (%s мм/ч)" % (esc(s["name"]), f1(s["int"])) for s in raining)
            txt = "🌧 <b>Начался дождь:</b> %s." % lst
        if ro and ro["start"] <= now + timedelta(hours=1):
            txt += "\n" + rain_text_ongoing(ro, now, hours, None)
        alerts.append(("%s\n🕐 %s" % (txt, hhmm(now)), False))
        state["rain_city"] = True
        state["fc_warned"] = False
    elif not raining and city_active:
        extra = ""
        if epi:
            t1 = max(st_["ep"]["last_wet"] for st_ in epi["stations"])
            extra = " Шёл с %s до %s." % (hhmm(epi["start"]), hhmm(t1))
            if epi["acc"] >= 0.1:
                extra += " Выпало до %s мм (%s), в среднем %s мм." % (f1(epi["acc"]), esc(at_station(epi["name"])), f1(epi["mean"]))
        end_head = "🌧 <b>Дождь закончился.</b>%s" % extra
        alerts.append(("%s\n🕐 %s" % (end_head, hhmm(now)), False))
        end_idx = len(alerts) - 1
        state["rain_end_t"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state["rain_city"] = False
        state["fc_warned"] = False
        state.pop("ep_start", None)

    # 5. порывы ветра
    gmax = gusty[0]["gust"] if gusty else 0.0
    if gusty:
        state["gust_quiet"] = 0
        if not state.get("gust_active") or gmax >= state.get("gust_level", 0) + GUST_STEP:
            lst = "; ".join("%s %s" % (esc(s["name"]), f1(s["gust"])) for s in gusty[:4])
            w = gusty[0].get("wind_at_gust")
            d = gusty[0].get("gust_dir")
            tail = ""
            if d is not None and w is not None:
                tail = "\nВетер %s, %s м/с." % (compass(d), f0(w))
            head = "💨 <b>Порывы усилились</b>" if state.get("gust_active") else "💨 <b>Порывы ветра</b>"
            alerts.append(("%s до <b>%s м/с</b>\n%s (м/с).%s\n🕐 %s" % (
                head, f1(gmax), lst, tail, hhmm(now)), False))
            state["gust_active"] = True
            state["gust_level"] = gmax
    elif state.get("gust_active"):
        state["gust_quiet"] = state.get("gust_quiet", 0) + 1
        if state["gust_quiet"] >= GUST_QUIET_POLLS:
            state["gust_active"] = False
            state["gust_level"] = 0.0

    # 6. прогноз по Ансамблю: осадки и фронт
    def cooldown(kind, hours_):
        try:
            return (now - parse_iso(state.get(kind, ""))) < timedelta(hours=hours_)
        except Exception:
            return False

    warn_rain = bool(ro and not raining and not state.get("rain_city")
                     and ro["start"] < now + timedelta(hours=FC_WARN_HOURS))
    if warn_rain and not state.get("fc_warned"):
        lead = max(0, int(round((ro["start"] - now).total_seconds() / 60.0)))
        lead_txt = "в ближайшее время" if lead < 15 else "через ~%d мин" % (round(lead / 5.0) * 5)
        head = rain_again_header(now, ro["start"], lead_txt, state.get("rain_end_t", ""))
        body = [head or "☔ <b>Ожидаются осадки</b> %s, около %s." % (lead_txt, hhmm(max(ro["start"], now)))]
        if fo:
            body += front_text(fo)
        body.append(rain_text_upcoming(ro))
        body.append("Сейчас: %s." % now_summary(ok))
        body.append("🕐 %s" % hhmm(now))
        if end_idx is not None and head:
            # конец дождя и новые осадки в одном запуске: один пост вместо двух с разницей в минуты
            alerts[end_idx] = ("%s\n\n%s" % (end_head, "\n".join(body)), False)
        else:
            alerts.append(("\n".join(body), False))
        state["fc_warned"] = True
        if fo:
            state["front_t"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif not warn_rain:
        state["fc_warned"] = False
    if fo and not (warn_rain and state.get("front_t") == now.strftime("%Y-%m-%dT%H:%M:%SZ")) \
            and not cooldown("front_t", FRONT_COOLDOWN_H):
        body = front_text(fo)
        if ro and ro["start"] < now + timedelta(hours=12) and not raining:
            body.append(rain_text_upcoming(ro))
        body.append("Сейчас: %s." % now_summary(ok))
        body.append("🕐 %s" % hhmm(now))
        alerts.append(("\n".join(body), False))
        state["front_t"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 7. аномалии по наблюдениям (медиана по станциям)
    an = state.setdefault("anom", {})
    def cool(kind):
        try:
            return (now - parse_iso(an.get(kind, ""))) < timedelta(hours=ANOM_COOLDOWN_H)
        except Exception:
            return False
    dp = [d for d in (delta(s["obs"], "p", 180) for s in ok) if d is not None]
    if len(dp) >= 3 and not cool("p"):
        m = statistics.median(dp)
        if abs(m) >= P_CHANGE_HPA:
            cur = statistics.median([s["p"] for s in ok if s["p"] is not None])
            word = "падение" if m < 0 else "рост"
            alerts.append(("📉 <b>Быстрое %s давления:</b> %s гПа за 3 ч (сейчас ~%s гПа). Возможна смена погоды.\n🕐 %s" % (
                word, ("+" if m > 0 else "−") + f1(abs(m)), f0(cur), hhmm(now)), False))
            an["p"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    dtp = [d for d in (delta(s["obs"], "temp", 60) for s in ok) if d is not None]
    if len(dtp) >= 3 and not cool("t"):
        m = statistics.median(dtp)
        if abs(m) >= T_CHANGE_C:
            cur = statistics.median([s["temp"] for s in ok if s["temp"] is not None])
            alerts.append(("🌡 <b>Резкое изменение температуры:</b> %s °C за час (сейчас %s °C).\n🕐 %s" % (
                ("+" if m > 0 else "−") + f1(abs(m)), f0(cur), hhmm(now)), False))
            an["t"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if "--card" in args:   # тест карточек: PWS и ГМЦ (если есть) отправляются в канал, состояние не сохраняется
        import weather_tg_card as card
        fb = forecast_block(hours, ro, fo, bool(raining), now, peak)
        pngs = [(card.render_pws(card_data(ok, raining, now, epi)), caption_pws(ok, raining, gusty, now, epi, fb))]
        if sy:
            pngs.append((card.render_gmc(gmc_data(sy)), caption_gmc(sy, now)))
        if dry:
            for i, (p, c) in enumerate(pngs):
                open("/tmp/card%d.png" % i, "wb").write(p)
                print("card%d.png %d bytes; caption %d chars" % (i, len(p), len(c)))
                print(c)
            return 0
        for p, c in pngs:
            print("sent:", tg_send_photo(env, p, c, True))
        return 0

    # 8. единый пост (без звука): ГМЦ + частные станции + прогноз
    hour_key = lnow.strftime("%Y-%m-%dT%H")
    new_hour = state.get("digest_hour") != hour_key
    synop_new = False
    sy_iso = None
    if sy:
        sy_iso = sy["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
        if state.get("synop_sent") != sy_iso:
            if (now - sy["time"]).total_seconds() / 3600.0 <= SYNOP_MAX_AGE_H:
                synop_new = True
            else:
                state["synop_sent"] = sy_iso  # старый срок не объявляем
    hourly = False   # PWS переехали в закреплённое «табло» (weather_tg_board.py), в ленте только ГМЦ и тревоги
    messages = list(alerts)
    digest_meta = None
    if hourly or synop_new or force_digest:
        messages.append((build_digest(ok, raining, gusty, sy, hours, ro, fo, now, official=synop_new or force_digest, epi=epi, peak=peak), True))
        if sy and (synop_new or force_digest) and "--text" not in args:
            try:
                import weather_tg_card as _card
                digest_meta = {"idx": len(messages) - 1, "png": _card.render_gmc(gmc_data(sy)), "sy": sy,
                               "fb": forecast_block(hours, ro, fo, raining, now, peak)}
            except Exception as e:
                log("карточка ГМЦ не собралась (%s), будет текст" % type(e).__name__)
        if synop_new and sy_iso:
            state["synop_sent"] = sy_iso
    if new_hour:
        state["digest_hour"] = hour_key

    # 8б. ИИ: практическая строка к тревогам и вердикт к сводке ГМЦ (при неудаче публикуется шаблон)
    if messages and (not dry or "--ai" in args):
        ai.budget(AI_BUDGET_S)
        n_al = len(alerts)
        new_msgs = []
        for i, (t, silent) in enumerate(messages):
            line = None
            try:
                line = ai.alert_line(t, log, state.get("advice", [])) if i < n_al else ai.verdict(t, state.get("verdicts", []), log, now.astimezone(KYIV))
            except Exception as e:
                log("ai: сбой %s" % type(e).__name__)
            if line:
                if i < n_al:
                    t = t + "\n💬 <i>%s</i>" % esc(line)
                    state["advice"] = (state.get("advice", []) + [line])[-8:]
                else:
                    head, _, rest = t.partition("\n")
                    t = head + "\n💬 <i>%s</i>\n" % esc(line) + rest
                    state["verdicts"] = (state.get("verdicts", []) + [line])[-8:]
            new_msgs.append((t, silent))
        messages = new_msgs
    # 8в. краткосрочный прогноз в конце поста ГМЦ: только когда ничего существенного не ожидается (иначе блок прогноза уже есть)
    force_ol = "--force-outlook" in args   # тест: показать краткосрочный прогноз, даже если блок прогноза уже есть
    if digest_meta and (force_ol or not digest_meta["fb"]) and hours and "--no-outlook" not in args:   # порывы на станциях не повод пропускать: блока про них в сводке нет
        try:
            import weather_tg_outlook as outl
            ol = outl.outlook_lines(hours, now, state, log, use_ai=(not dry or "--ai" in args))
            if ol:
                if force_ol:
                    digest_meta["fb"] = (digest_meta["fb"] or []) + [esc(x) for x in ol]
                else:
                    digest_meta["fb"] = [esc(x) for x in ol]
                    ix = digest_meta["idx"]
                    messages[ix] = (messages[ix][0] + "\n\n🔮 <b>Прогноз</b>\n" + "\n".join(digest_meta["fb"]), messages[ix][1])
        except Exception as e:
            log("outlook: сбой %s: %s" % (type(e).__name__, e))
    if digest_meta:
        verdict = None
        for ln_ in messages[digest_meta["idx"]][0].split("\n")[1:2]:
            if ln_.startswith("💬"):
                verdict = ln_
        cap = ["🏛 <b>Сводка ГМЦ</b>, наблюдения %s" % hhmm(digest_meta["sy"]["time"])]
        if verdict:
            cap.append(verdict)
        if digest_meta["fb"]:
            cap.append("")
            cap.append("🔮 <b>Прогноз</b>")
            cap += digest_meta["fb"]
        digest_meta["caption"] = "\n".join(cap)

    # 9. вывод и отправка
    if dry:
        print("--- станции (%d из %d онлайн) ---" % (len(ok), len(STATIONS)))
        for sid, s in st.items():
            if not s["ok"]:
                print("%-10s %-18s офлайн/нет данных" % (sid, s["name"]))
                continue
            print("%-10s %-18s возраст %4.0f мин  T %5s  ветер %4s  порыв %4s  осадки %4s мм/ч  дождь:%s" % (
                sid, s["name"], s["age"], s["temp"], f1(s["wind"] or 0), f1(s["gust"]), f1(s["int"]),
                "ДА" if rs.get(sid) else "нет"))
        if digest_meta:
            open("/tmp/card_gmc.png", "wb").write(digest_meta["png"])
            print("--- карточка ГМЦ: /tmp/card_gmc.png, подпись:\n%s\n---" % digest_meta.get("caption", ""))
        print("--- сообщения (не отправлены, --dry): %d ---" % len(messages))
        for t, silent in messages:
            print(("[тихо] " if silent else "[звук] ") + t)
            print()
        return 0

    for i, (t, silent) in enumerate(messages):
        sent = False
        if digest_meta and i == digest_meta["idx"]:
            sent = tg_send_photo(env, digest_meta["png"], digest_meta["caption"], silent)
            if sent:
                log("отправлено фото: карточка ГМЦ")
        if not sent:
            sent = tg_send(env, t, silent)
        if sent:
            log("отправлено: " + t.split("\n")[0][:80])
        else:
            log("НЕ отправлено: " + t.split("\n")[0][:80])
    save_state(state)
    trim_log()
    log("ok: станций онлайн %d, дождь %d, порывы %d, сообщений %d" % (len(ok), len(raining), len(gusty), len(messages)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
