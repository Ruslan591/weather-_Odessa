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
                return json.loads(r.read().decode()).get("ok", False)
        except urllib.error.HTTPError as e:
            log("TG HTTP %s" % e.code)
        except Exception as e:
            log("TG %s" % type(e).__name__)
        time.sleep(2)
    return False


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


def rain_text_ongoing(ro, now):
    if ro["beyond"]:
        s = "⏱ По прогнозу Ансамбля осадки продолжатся не менее чем до %s" % hhmm(ro["end"])
    else:
        s = "⏱ По прогнозу Ансамбля осадки закончатся около %s" % hhmm(ro["end"])
    extra = []
    if ro["peak_e"] > now:
        when = ("сейчас, до %s" % hhmm(ro["peak_e"])) if ro["peak_b"] <= now else (
            "%s–%s" % (hhmm(ro["peak_b"]), hhmm(ro["peak_e"])))
        extra.append("наибольшая интенсивность ~%s мм/ч (%s)" % (f1(ro["peak_rate"]), when))
    if ro["remaining"] >= 0.1:
        extra.append("до конца ещё ~%s мм" % f1(ro["remaining"]))
    return s + ("; " + "; ".join(extra) if extra else "") + "."


# ---------------------------------------------------------------- единый пост: ГМЦ + частные станции + прогноз

def official_lines(sy, now):
    t = sy["time"]
    age = (now - t).total_seconds() / 3600.0
    head = "🏛 <b>Официальная сводка ГМЦ</b> (Одесса, 33837), срок %s (%s UTC)" % (
        hhmm(t), t.strftime("%H:%M"))
    if age > SYNOP_MAX_AGE_H + 1:
        head += " ⚠ данные устарели (%d ч назад)" % round(age)
    L = [head]
    p1 = []
    if sy["temp"] is not None:
        s = "🌡 %s °C" % f1(sy["temp"])
        if sy["dew"] is not None:
            s += " (точка росы %s °C%s)" % (f1(sy["dew"]), (", влажность ~%s%%" % f0(sy["rh"])) if sy["rh"] is not None else "")
        p1.append(s)
    if sy["p_sea"] is not None:
        s = "давление %s гПа" % f1(sy["p_sea"])
        if sy["tend"] is not None:
            if abs(sy["tend"]) < 0.1:
                s += " (без изменений за 3 ч)"
            else:
                s += " (%s %s гПа за 3 ч)" % ("падение" if sy["tend"] < 0 else "рост", f1(abs(sy["tend"])))
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
    p3 = []
    if sy.get("ww_text"):
        p3.append("в срок: %s" % sy["ww_text"])
    if sy["precip"] is not None and (sy["precip"] > 0 or sy["precip_trace"]):
        amt = "следы" if sy["precip_trace"] and sy["precip"] == 0 else "%s мм" % f1(sy["precip"])
        p3.append("осадки%s: %s" % ((" за %d ч" % sy["precip_h"]) if sy["precip_h"] else "", amt))
    if sy["daily"] is not None and sy["daily"] > 0:
        p3.append("суточная сумма осадков: %s мм" % f0(sy["daily"]))
    if p3:
        L.append("🌧 " + "; ".join(p3) + ".")
    return L


def private_lines(ok, raining, gusty, now):
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
            out.append("🌧 Дождь по всему городу (%d из %d районов), сильнее: %s." % (
                len(rs_), len(ok), ", ".join("%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in rs_[:3])))
        else:
            out.append("🌧 Дождь: %s." % ", ".join("%s %s мм/ч" % (esc(s["name"]), f1(s["int"])) for s in rs_))
        eps = [(s["ep"]["acc"], s["name"], s["ep"]["start"]) for s in raining if s.get("ep")]
        if eps:
            best = max(eps)
            mean_acc = statistics.mean(a for a, _, _ in eps)
            t0 = min(t for _, _, t in eps)
            out.append("С %s выпало до %s мм (%s), в среднем %s мм." % (
                hhmm(t0), f1(best[0]), esc(best[1]), f1(mean_acc)))
    elif not gusty:
        out.append("Порывов и осадков сейчас нет.")
    daily = [(s["ptot"], s["name"]) for s in ok if s.get("ptot") is not None and s["ptot"] >= 0.1]
    if daily:
        best = max(daily)
        out.append("За сутки (с 00:00): до %s мм (%s)." % (f1(best[0]), esc(best[1])))
    return out


def forecast_block(hours, ro, fo, raining, now):
    L = []
    if fo:
        L += front_text(fo)
    if raining:
        if ro:
            L.append(rain_text_ongoing(ro, now))
        elif hours:
            L.append("⏱ По прогнозу Ансамбля значимых осадков в ближайшие часы нет.")
    elif ro and ro["start"] < now + timedelta(hours=12):
        L.append(rain_text_upcoming(ro))
    return L


def build_digest(ok, raining, gusty, sy, hours, ro, fo, now):
    lnow = now.astimezone(KYIV)
    L = ["📋 <b>Сводка по Одессе, %s</b>" % lnow.strftime("%H:%M")]
    if sy:
        L += official_lines(sy, now)
    L.append("")
    L.append("📡 <b>Частные станции</b> (%d из %d)" % (len(ok), len(STATIONS)))
    L += private_lines(ok, raining, gusty, now)
    fb = forecast_block(hours, ro, fo, raining, now)
    if fb:
        L.append("")
        L.append("🔮 <b>Прогноз (Ансамбль)</b>")
        L += fb
    return "\n".join(L)


def main():
    args = set(sys.argv[1:])
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
            "temp": last["temp"], "hum": last["hum"], "wind": last["wind"], "p": last["p"],
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
    raining = [s for sid, s in st.items() if s["ok"] and rs.get(sid)]
    gusty = sorted([s for s in ok if s["gust"] >= GUST_MS], key=lambda s: -s["gust"])

    # 3. Ансамбль и официальная сводка ГМЦ
    hours = get_ensemble(state, now, source)
    ro = rain_outlook(hours, now) if hours else None
    fo = front_outlook(hours, now) if hours else None
    sy = synop.fetch_latest(now, log=log)

    alerts = []   # (text, silent)

    # 4. дождь: начало / конец
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
        if ro and ro["start"] <= now + timedelta(hours=1):
            txt += "\n" + rain_text_ongoing(ro, now)
        alerts.append(("%s\n🕐 %s" % (txt, hhmm(now)), False))
        state["rain_city"] = True
        state["fc_warned"] = False
    elif not raining and city_active:
        eps = [(s["ep"], s["name"]) for s in ok if s.get("ep") and (now - s["ep"]["last_wet"]) <= timedelta(minutes=120)]
        extra = ""
        if eps:
            t0 = min(e["start"] for e, _ in eps)
            t1 = max(e["last_wet"] for e, _ in eps)
            extra = " Шёл с %s до %s." % (hhmm(t0), hhmm(t1))
            best = max(eps, key=lambda x: x[0]["acc"])
            if best[0]["acc"] >= 0.1:
                mean_acc = statistics.mean(e["acc"] for e, _ in eps)
                extra += " Выпало до %s мм (%s), в среднем %s мм." % (f1(best[0]["acc"]), esc(best[1]), f1(mean_acc))
        alerts.append(("🌤 <b>Дождь закончился.</b>%s\n🕐 %s" % (extra, hhmm(now)), False))
        state["rain_city"] = False
        state["fc_warned"] = False

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
            alerts.append(("%s до <b>%s м/с</b>\nРайоны: %s (м/с).%s\n🕐 %s" % (
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
        body = ["☔ <b>Ожидаются осадки</b> (прогноз Ансамбля) %s, около %s." % (lead_txt, hhmm(max(ro["start"], now)))]
        if fo:
            body += front_text(fo)
        body.append(rain_text_upcoming(ro))
        body.append("Сейчас: %s." % now_summary(ok))
        body.append("🕐 %s" % hhmm(now))
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
    hourly = new_hour and not alerts and (gusty or raining)
    messages = list(alerts)
    if hourly or synop_new or force_digest:
        messages.append((build_digest(ok, raining, gusty, sy, hours, ro, fo, now), True))
        if synop_new and sy_iso:
            state["synop_sent"] = sy_iso
    if new_hour:
        state["digest_hour"] = hour_key

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
