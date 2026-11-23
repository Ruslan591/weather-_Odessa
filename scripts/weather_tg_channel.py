#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram-канал погоды Одессы (docs/topics/weather_tg_channel.md).

Запуск на VPS по cron каждые 10 минут (/etc/cron.d/weather-tg).
Секреты и ID канала: /opt/weather-tg/tg.env
  WEATHER_TG_TOKEN, WEATHER_TG_CHAT_ID, WU_KEYS (через запятую).
Состояние: /opt/weather-tg/state.json

Правила:
  порыв >= 8 м/с -> предупреждение (со звуком), повтор только при усилении на 4 м/с;
  дождь: начало / конец (со звуком), подтверждение по 2 сводкам станции подряд,
         конец по 3 сухим сводкам подряд, район или «по всему городу»;
  прогноз осадок (Open-Meteo, 15 мин) -> предупреждение «через N мин» + сводка сейчас;
  аномалии: быстрое изменение давления (3 ч) и температуры (1 ч);
  почасовая сводка (без звука) только если сейчас порыв или осадки.

Флаги: --dry (ничего не отправлять и не сохранять, вывести таблицу и сообщения),
       --digest (принудительно сформировать часовую сводку).
"""
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # нет tzdata
    KYIV = timezone(timedelta(hours=2))

BASE = os.environ.get("WTG_DIR", "/opt/weather-tg")
ENV_FILE = os.path.join(BASE, "tg.env")
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "run.log")

STATIONS = [
    ("IODESA137", "пос. Котовского"),
    ("IODESA138", "Центр"),
    ("IODESA139", "Чудо Город"),
    ("IODESS41", "Судостроительная"),
    ("IODESS44", "Аркадия"),
    ("IODESS16", "Таирова"),
    ("IODESS31", "Савиньон"),
    ("IODESS37", "Застава"),
    ("IKRASN91", "пос. Степовое"),
]

GUST_MS = 8.0          # порог порыва, м/с
GUST_STEP = 4.0        # повторное предупреждение при усилении на столько м/с
GUST_QUIET_POLLS = 3   # столько опросов подряд без порывов = эпизод окончен
RAIN_MM_H = 0.1        # порог осадков, мм/ч
RAIN_END_DRY = 3       # сухих сводок подряд для конца дождя
CITY_WIDE_MIN = 3      # «по всему городу»: дождь в >= 3 районах и в более чем половине работающих станций
STALE_MIN = 45         # станция без свежих данных считается офлайн (WU отдаёт данные с задержкой 15-20 мин)
LAT, LON = 46.4825, 30.7233
FC_WINDOW_STEPS = 12   # 3 часа по 15 минут
FC_MIN_MM = 0.1        # осадки в шаге прогноза (15 мин), мм
FC_REFRESH_MIN = 30
P_CHANGE_HPA = 3.0     # изменение давления за 3 часа
T_CHANGE_C = 4.0       # изменение температуры за 1 час
ANOM_COOLDOWN_H = 3


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


def fetch_forecast():
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON, "minutely_15": "precipitation",
        "forecast_minutely_15": 24, "hourly": "pressure_msl", "forecast_hours": 24,
        "timezone": "Europe/Kyiv"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "weather-tg/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        times = d["minutely_15"]["time"]
        pr = d["minutely_15"]["precipitation"]
        steps = []
        for t, p in zip(times, pr):
            dt = datetime.fromisoformat(t).replace(tzinfo=KYIV)
            steps.append([dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), p or 0.0])
        press = []
        for t, p in zip(d["hourly"]["time"], d["hourly"]["pressure_msl"]):
            if p is None:
                continue
            dt = datetime.fromisoformat(t).replace(tzinfo=KYIV)
            press.append([dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), p])
        return steps, press
    except Exception as e:
        log("Open-Meteo: %s" % type(e).__name__)
        return None


# ---------------------------------------------------------------- форматирование

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


def parse_iso(t):
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rain_outlook(steps, now):
    """Первый эпизод осадков по прогнозу: начало, конец, пик (мм/ч), сумма."""
    seq = []
    for t, mm in steps:
        end = parse_iso(t)
        if end > now:
            seq.append((end - timedelta(minutes=15), end, mm))
    ep = []
    dry = 0
    started = False
    for b, e, mm in seq:
        if mm >= FC_MIN_MM:
            started = True
            dry = 0
            ep.append((b, e, mm))
        elif started:
            dry += 1
            if dry >= 2:
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
    return {"start": ep[0][0], "end": ep[-1][1], "peak_b": ep[lo][0], "peak_e": ep[hi][1],
            "peak_rate": pm * 4.0, "total": sum(x[2] for x in ep)}


def pressure_outlook(press, now):
    """Минимум давления в ближайшие 12 ч и самый быстрый спад (прогноз MSL, относительные величины)."""
    pts = [(parse_iso(t), p) for t, p in press]
    pts = [x for x in pts if x[0] >= now - timedelta(minutes=59)]
    if len(pts) < 4:
        return None
    hz = pts[:13]
    p0 = hz[0][1]
    tmin, pmin = min(hz, key=lambda x: x[1])
    best = None
    for a, b in zip(hz, hz[1:]):
        d = b[1] - a[1]
        if best is None or d < best[0]:
            best = (d, a[0], b[0])
    return {"drop": p0 - pmin, "tmin": tmin, "falling_on": hz[-1][1] == pmin,
            "fast_rate": best[0], "fast_b": best[1], "fast_e": best[2]}


def forecast_lines(fc, now):
    lines = []
    ro = rain_outlook(fc.get("steps", []), now)
    if ro:
        lines.append("📈 Пик осадков: %s–%s, до %s мм/ч. Осадки с %s до ~%s, всего ~%s мм." % (
            hhmm(ro["peak_b"]), hhmm(ro["peak_e"]), f1(ro["peak_rate"]),
            hhmm(ro["start"]), hhmm(ro["end"]), f1(ro["total"])))
    po = pressure_outlook(fc.get("press", []), now) if fc.get("press") else None
    if po and po["drop"] >= 1.0:
        if po["falling_on"]:
            mn = "падение продолжится минимум до %s" % hhmm(po["tmin"])
        else:
            mn = "минимум около %s" % hhmm(po["tmin"])
        fast = ""
        if po["fast_rate"] <= -0.5:
            fast = ", быстрее всего %s–%s (%s гПа/ч)" % (hhmm(po["fast_b"]), hhmm(po["fast_e"]), f1(po["fast_rate"]).replace("-", "−"))
        lines.append("📉 Давление по прогнозу: %s (−%s гПа к текущему)%s." % (mn, f1(po["drop"]), fast))
    return lines


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
                return json.loads(r.read().decode()).get("ok", False)
        except urllib.error.HTTPError as e:
            log("TG HTTP %s" % e.code)
        except Exception as e:
            log("TG %s" % type(e).__name__)
        time.sleep(2)
    return False


# ---------------------------------------------------------------- основной цикл

def main():
    args = set(sys.argv[1:])
    dry = "--dry" in args
    force_digest = "--digest" in args
    env = load_env()
    if not dry and ("WEATHER_TG_TOKEN" not in env or "WEATHER_TG_CHAT_ID" not in env):
        log("нет WEATHER_TG_TOKEN / WEATHER_TG_CHAT_ID в %s" % ENV_FILE)
        return 1
    keys = [k for k in env.get("WU_KEYS", "").split(",") if k]
    if not keys:
        log("нет WU_KEYS в %s" % ENV_FILE)
        return 1

    state = load_state()
    now = datetime.now(timezone.utc)
    start = int(time.time() // 600)

    # 1. станции
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
            "temp": last["temp"], "hum": last["hum"], "wind": last["wind"], "p": last["p"],
            "dir": last["dir"], "gust": gobs["gust"] or 0.0,
            "gust_dir": gobs["dir"], "wind_at_gust": gobs["wind"],
            "int": max(o["int"] for o in recent),
            "ptot": last["ptot"],
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
    raining = [s for sid, s in st.items() if s["ok"] and rs.get(sid)]

    alerts = []   # (text, silent)
    lnow = now.astimezone(KYIV)

    # 3. дождь: начало / конец
    city_active = state.get("rain_city", False)
    if raining and not city_active:
        raining.sort(key=lambda s: -s["int"])
        n = len(raining)
        if city_wide(n, len(ok)):
            top = ", ".join("%s — %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in raining[:3])
            txt = "🌧 <b>Дождь по всему городу</b> (%d из %d районов).\nСильнее всего: %s." % (n, len(ok), top)
        elif n == 1:
            txt = "🌧 <b>Начался дождь</b> в районе: %s (%s мм/ч)." % (esc(raining[0]["name"]), f1(raining[0]["int"]))
        else:
            lst = ", ".join("%s (%s мм/ч)" % (esc(s["name"]), f1(s["int"])) for s in raining)
            txt = "🌧 <b>Начался дождь</b> в районах: %s." % lst
        alerts.append(("%s\n%s" % (txt, "🕐 " + hhmm(now)), False))
        state["rain_city"] = True
        state["rain_start"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        state["rain_start_tot"] = {sid: s["ptot"] for sid, s in st.items() if s["ok"] and s["ptot"] is not None}
        state["fc_warned"] = False
    elif not raining and city_active:
        started = state.get("rain_start")
        extra = ""
        try:
            t0 = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            extra = " Шёл с %s." % hhmm(t0)
        except Exception:
            pass
        best = None
        for sid, s in st.items():
            t0v = (state.get("rain_start_tot") or {}).get(sid)
            if s["ok"] and s["ptot"] is not None and t0v is not None:
                d = s["ptot"] - t0v if s["ptot"] >= t0v else s["ptot"]
                if best is None or d > best[0]:
                    best = (d, s["name"])
        if best and best[0] >= 0.1:
            extra += " Выпало до %s мм (%s)." % (f1(best[0]), esc(best[1]))
        alerts.append(("🌤 <b>Дождь закончился.</b>%s\n🕐 %s" % (extra, hhmm(now)), False))
        state["rain_city"] = False
        state["fc_warned"] = False

    # 4. порывы ветра
    gusty = sorted([s for s in ok if s["gust"] >= GUST_MS], key=lambda s: -s["gust"])
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
            alerts.append(("%s до <b>%s м/с</b>\nРайоны: %s (м/с).%s\n🕐 %s" % (
                head, f1(gmax), lst, tail, hhmm(now)), False))
            state["gust_active"] = True
            state["gust_level"] = gmax
    elif state.get("gust_active"):
        state["gust_quiet"] = state.get("gust_quiet", 0) + 1
        if state["gust_quiet"] >= GUST_QUIET_POLLS:
            state["gust_active"] = False
            state["gust_level"] = 0.0

    # 5. прогноз осадок
    fc = state.get("fc") or {}
    need = "press" not in fc
    try:
        need = need or (now - datetime.strptime(fc.get("t", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                ).total_seconds() > FC_REFRESH_MIN * 60
    except Exception:
        need = True
    if need:
        res = fetch_forecast()
        if res is not None:
            fc = {"t": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "steps": res[0], "press": res[1]}
            state["fc"] = fc
    upcoming = []
    for t, mm in fc.get("steps", []):
        try:
            end = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        begin = end - timedelta(minutes=15)
        if end > now and begin < now + timedelta(minutes=15 * FC_WINDOW_STEPS):
            upcoming.append((begin, mm))
    wet_steps = [(b, mm) for b, mm in upcoming if mm >= FC_MIN_MM]
    if wet_steps and not state.get("rain_city") and not raining:
        if not state.get("fc_warned"):
            ro = rain_outlook(fc.get("steps", []), now)
            b0 = ro["start"] if ro else wet_steps[0][0]
            lead = max(0, int(round((b0 - now).total_seconds() / 60.0)))
            lead_txt = "в ближайшие минуты" if lead < 10 else "через ~%d мин" % (round(lead / 5.0) * 5)
            body = ["☔ <b>По прогнозу осадки</b> %s (около %s)." % (lead_txt, hhmm(b0))]
            body += forecast_lines(fc, now)
            body.append("Сейчас: %s." % now_summary(ok))
            body.append("🕐 %s" % hhmm(now))
            alerts.append(("\n".join(body), False))
            state["fc_warned"] = True
    elif not wet_steps:
        state["fc_warned"] = False

    # 6. аномалии (медиана по станциям)
    an = state.setdefault("anom", {})
    def cool(kind):
        try:
            t = datetime.strptime(an.get(kind, ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return (now - t) < timedelta(hours=ANOM_COOLDOWN_H)
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

    # 7. почасовая сводка (без звука), только если сейчас порыв или осадки
    hour_key = lnow.strftime("%Y-%m-%dT%H")
    messages = list(alerts)
    new_hour = state.get("digest_hour") != hour_key
    if (new_hour and not alerts and (gusty or raining)) or force_digest:
        lines = ["🕐 <b>Сводка по Одессе, %s</b>" % lnow.strftime("%H:%M")]
        if gusty:
            lines.append("💨 Порывы: " + "; ".join("%s %s" % (esc(s["name"]), f1(s["gust"])) for s in gusty[:5]) + " м/с")
        if raining:
            raining.sort(key=lambda s: -s["int"])
            if city_wide(len(raining), len(ok)):
                lines.append("🌧 Дождь по всему городу, сильнее: " + ", ".join(
                    "%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in raining[:3]))
            else:
                lines.append("🌧 Дождь: " + ", ".join(
                    "%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in raining))
        if not gusty and not raining:
            lines.append("Порывов и осадков нет.")
        lines.append(now_summary(ok))
        messages.append(("\n".join(lines), True))
    if new_hour:
        state["digest_hour"] = hour_key

    # 8. вывод и отправка
    if dry:
        print("--- станции (%d из %d онлайн) ---" % (len(ok), len(STATIONS)))
        for sid, s in st.items():
            if not s["ok"]:
                print("%-10s %-18s офлайн/нет данных" % (sid, s["name"]))
                continue
            print("%-10s %-18s возраст %4.0f мин  T %5s  ветер %4s  порыв %4s  осадки %4s мм/ч  дождь:%s" % (
                sid, s["name"], s["age"], s["temp"], f1(s["wind"] or 0), f1(s["gust"]), f1(s["int"]),
                "ДА" if rs.get(sid) else "нет"))
        print("--- сообщения (не отправлены, --dry): %d ---" % len(messages))
        for t, silent in messages:
            print(("[тихо] " if silent else "[звук] ") + t)
            print()
        return 0

    for t, silent in messages:
        if tg_send(env, t, silent):
            log("отправлено: " + t.split("\n")[0][:80])
        else:
            log("НЕ отправлено: " + t.split("\n")[0][:80])
    save_state(state)
    trim_log()
    log("ok: станций онлайн %d, дождь %d, порывы %d, сообщений %d" % (len(ok), len(raining), len(gusty), len(messages)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
