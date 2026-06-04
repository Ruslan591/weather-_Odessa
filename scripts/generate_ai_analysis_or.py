#!/usr/bin/env python3
"""
generate_ai_analysis_or.py — генерация синоптического анализа через OpenRouter API.
Запрашивает open-meteo (ансамбль), агрегирует данные по дням,
отправляет в Claude, сохраняет data/forecast_analysis.json.
Вызывается из check_model_runs.py после run_pipeline().
"""

import json, os, urllib.request, urllib.error
import asyncio
import edge_tts
from datetime import datetime, timezone, timedelta
import hashlib

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE   = os.path.join(BASE_DIR, "data", "forecast_analysis_or.json")
ENV_FILE      = os.path.join(BASE_DIR, ".env")
TIMEOUT       = 30

LAT, LON      = 46.43, 30.74
TIMEZONE      = "Europe/Kiev"

# ── Ключ из .env ──────────────────────────────────────────────────────────────

def load_api_key():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("OPENROUTER_API_KEY")

def ai_enabled():
    """Проверяет флаг OR_ANALYSIS_ENABLED в .env (default: true)."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("OR_ANALYSIS_ENABLED="):
                    val = line.strip().split("=", 1)[1].lower()
                    return val not in ("0", "false", "no", "off")
    return True

# ── Запрос open-meteo ─────────────────────────────────────────────────────────

HOURLY_FIELDS = ",".join([
    "temperature_2m","apparent_temperature","dewpoint_2m",
    "relative_humidity_2m","precipitation","precipitation_probability",
    "weathercode","pressure_msl",
    "windspeed_10m","winddirection_10m","windgusts_10m",
    "windspeed_80m","winddirection_80m",
    "cloudcover","cloud_cover_low","cloud_cover_mid","cloud_cover_high",
    "cape","lifted_index","convective_inhibition",
    "freezinglevel_height","snowfall","visibility",
    "temperature_925hPa","temperature_850hPa","temperature_700hPa",
    "temperature_600hPa","temperature_500hPa","temperature_400hPa",
    "temperature_300hPa","temperature_250hPa","temperature_200hPa",
    "dewpoint_925hPa","dewpoint_850hPa","dewpoint_700hPa","dewpoint_500hPa",
    "geopotential_height_925hPa","geopotential_height_850hPa",
    "geopotential_height_700hPa","geopotential_height_600hPa",
    "geopotential_height_500hPa","geopotential_height_400hPa",
    "geopotential_height_300hPa","geopotential_height_250hPa",
    "geopotential_height_200hPa","geopotential_height_150hPa",
    "geopotential_height_100hPa","geopotential_height_50hPa",
    "geopotential_height_30hPa","geopotential_height_10hPa",
    "relative_humidity_925hPa","relative_humidity_850hPa",
    "relative_humidity_700hPa","relative_humidity_500hPa","relative_humidity_300hPa",
    "cloud_cover_925hPa","cloud_cover_850hPa","cloud_cover_700hPa",
    "cloud_cover_500hPa","cloud_cover_300hPa",
    "vertical_velocity_1000hPa","vertical_velocity_925hPa","vertical_velocity_850hPa",
    "vertical_velocity_700hPa","vertical_velocity_600hPa","vertical_velocity_500hPa",
    "vertical_velocity_400hPa","vertical_velocity_300hPa",
    "windspeed_925hPa","winddirection_925hPa",
    "windspeed_850hPa","winddirection_850hPa",
    "windspeed_700hPa","winddirection_700hPa",
    "windspeed_500hPa","winddirection_500hPa",
    "windspeed_300hPa","winddirection_300hPa",
    "windspeed_250hPa","winddirection_250hPa",
    "windspeed_200hPa","winddirection_200hPa",
    "temperature_50hPa","temperature_30hPa","temperature_10hPa",
])

FORECAST_MODELS = [
    "ecmwf_ifs025", "gfs_global", "icon_global", "icon_eu",
    "gem_global", "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe", "cma_grapes_global",
]

def fetch_one_model(model):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly={HOURLY_FIELDS}"
        f"&models={model}"
        f"&forecast_days=7"
        f"&timezone={TIMEZONE}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "weather-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def fetch_ensemble():
    all_hourly = []
    times = None
    for model in FORECAST_MODELS:
        try:
            data = fetch_one_model(model)
            h = data.get("hourly", {})
            if not h.get("time"): continue
            if times is None: times = h["time"]
            all_hourly.append(h)
            print(f"  [AI] ok {model}")
        except Exception as e:
            print(f"  [AI] skip {model}: {e}")
    if not all_hourly:
        raise RuntimeError("Ни одна модель не ответила")
    print(f"  [AI] Усредняю {len(all_hourly)} моделей...")
    n = len(times)
    all_keys = set()
    for h in all_hourly: all_keys.update(h.keys())
    all_keys.discard("time")
    merged = {"time": times}
    for key in all_keys:
        cols = [h[key] for h in all_hourly if key in h and h[key] is not None]
        if not cols: merged[key] = [None]*n; continue
        avg = []
        for i in range(n):
            vals = [c[i] for c in cols if i < len(c) and c[i] is not None]
            avg.append(round(sum(vals)/len(vals), 2) if vals else None)
        merged[key] = avg
    return {"hourly": merged}

# ── Агрегация по дням ─────────────────────────────────────────────────────────

def mean(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None

def rnd(v, d=1):
    return round(v, d) if v is not None else None

def aggregate_days(data):
    h = data.get("hourly", {})
    times = h.get("time", [])
    n = len(times)

    def col(key):
        arr = h.get(key, [])
        return [arr[i] if i < len(arr) else None for i in range(n)]

    T2m   = col("temperature_2m");   Tapp  = col("apparent_temperature")
    Td    = col("dewpoint_2m");       RH    = col("relative_humidity_2m")
    Prec  = col("precipitation");     PrecP = col("precipitation_probability")
    WC    = col("weathercode");       P     = col("pressure_msl")
    WS    = col("windspeed_10m");     WD    = col("winddirection_10m")
    WG    = col("windgusts_10m");     WS80  = col("windspeed_80m")
    CC    = col("cloudcover");        CAPE  = col("cape")
    LI    = col("lifted_index");      CIN   = col("convective_inhibition")
    VIS   = col("visibility");        FRZ   = col("freezinglevel_height")
    Snow  = col("snowfall")
    CCL   = col("cloud_cover_low");   CCM   = col("cloud_cover_mid")
    CCH   = col("cloud_cover_high")
    T925  = col("temperature_925hPa"); T850 = col("temperature_850hPa")
    T700  = col("temperature_700hPa"); T600 = col("temperature_600hPa")
    T500  = col("temperature_500hPa"); T400 = col("temperature_400hPa")
    T300  = col("temperature_300hPa"); T250 = col("temperature_250hPa")
    T200  = col("temperature_200hPa")
    T50   = col("temperature_50hPa"); T30  = col("temperature_30hPa")
    T10   = col("temperature_10hPa")
    Td925 = col("dewpoint_925hPa");   Td850 = col("dewpoint_850hPa")
    Td700 = col("dewpoint_700hPa");   Td500 = col("dewpoint_500hPa")
    Z925  = col("geopotential_height_925hPa"); Z850 = col("geopotential_height_850hPa")
    Z700  = col("geopotential_height_700hPa"); Z600 = col("geopotential_height_600hPa")
    Z500  = col("geopotential_height_500hPa"); Z400 = col("geopotential_height_400hPa")
    Z300  = col("geopotential_height_300hPa"); Z250 = col("geopotential_height_250hPa")
    Z200  = col("geopotential_height_200hPa"); Z150 = col("geopotential_height_150hPa")
    Z100  = col("geopotential_height_100hPa"); Z50  = col("geopotential_height_50hPa")
    Z30   = col("geopotential_height_30hPa");  Z10  = col("geopotential_height_10hPa")
    RH925 = col("relative_humidity_925hPa");   RH850 = col("relative_humidity_850hPa")
    RH700 = col("relative_humidity_700hPa");   RH500 = col("relative_humidity_500hPa")
    RH300 = col("relative_humidity_300hPa")
    CC925 = col("cloud_cover_925hPa"); CC850 = col("cloud_cover_850hPa")
    CC700 = col("cloud_cover_700hPa"); CC500 = col("cloud_cover_500hPa")
    CC300 = col("cloud_cover_300hPa")
    W1000 = col("vertical_velocity_1000hPa"); W925 = col("vertical_velocity_925hPa")
    W850  = col("vertical_velocity_850hPa");  W700 = col("vertical_velocity_700hPa")
    W600  = col("vertical_velocity_600hPa");  W500 = col("vertical_velocity_500hPa")
    W400  = col("vertical_velocity_400hPa");  W300 = col("vertical_velocity_300hPa")
    WS925 = col("windspeed_925hPa");  WD925 = col("winddirection_925hPa")
    WS850 = col("windspeed_850hPa");  WD850 = col("winddirection_850hPa")
    WS700 = col("windspeed_700hPa");  WD700 = col("winddirection_700hPa")
    WS500 = col("windspeed_500hPa");  WD500 = col("winddirection_500hPa")
    WS300 = col("windspeed_300hPa");  WD300 = col("winddirection_300hPa")
    WS250 = col("windspeed_250hPa");  WD250 = col("winddirection_250hPa")
    WS200 = col("windspeed_200hPa");  WD200 = col("winddirection_200hPa")

    # группировка по датам
    from collections import defaultdict
    days = defaultdict(list)
    for i, t in enumerate(times):
        date = t[:10]
        days[date].append(i)

    now_local = datetime.now(timezone.utc).astimezone()
    today_str = now_local.strftime("%Y-%m-%d")

    result = []
    for date, idxs in sorted(days.items()):
        # Только сегодня + 4 дня вперёд
        if date < today_str:
            continue
        if len(result) >= 5:
            break

        def v(arr): return [arr[i] for i in idxs]

        # Ночь/день/вечер разбивка по часам
        hours_of_day = [int(times[i][11:13]) for i in idxs]
        night_idx  = [idxs[j] for j,h in enumerate(hours_of_day) if h < 6 or h >= 21]
        day_idx    = [idxs[j] for j,h in enumerate(hours_of_day) if 6 <= h < 21]

        def sub(arr, sub_idx): return [arr[i] for i in sub_idx if arr[i] is not None]

        T_vals = v(T2m)
        T_valid = [x for x in T_vals if x is not None]

        prec_sum = sum(x for x in v(Prec) if x is not None)
        snow_sum = sum(x for x in v(Snow) if x is not None)

        # Доминантный weathercode
        wc_list = [x for x in v(WC) if x is not None]
        wc_dom = max(set(wc_list), key=wc_list.count) if wc_list else None

        # Омега — знак и величина
        w500_avg = mean(v(W500))
        w700_avg = mean(v(W700))
        w850_avg = mean(v(W850))

        # Ветер — средний и максимальный
        ws_vals = [x for x in v(WS) if x is not None]
        wg_vals = [x for x in v(WG) if x is not None]

        # Изотерма 0°C
        frz_vals = [x for x in v(FRZ) if x is not None]

        import math
        def wmd(ws_a, wd_a):
            pairs=[(ws_a[ii],wd_a[ii]) for ii in idxs if ws_a[ii] is not None and wd_a[ii] is not None]
            if not pairs: return None,None
            u=sum(s*math.sin(math.radians(d)) for s,d in pairs)/len(pairs)
            vv=sum(s*math.cos(math.radians(d)) for s,d in pairs)/len(pairs)
            return rnd(math.sqrt(u*u+vv*vv)),rnd((math.degrees(math.atan2(u,vv))+360)%360)
        ws925m,wd925m=wmd(WS925,WD925); ws850m,wd850m=wmd(WS850,WD850)
        ws700m,wd700m=wmd(WS700,WD700); ws500m,wd500m=wmd(WS500,WD500)
        ws300m,wd300m=wmd(WS300,WD300); ws250m,wd250m=wmd(WS250,WD250)
        ws200m,wd200m=wmd(WS200,WD200)
        day_data = {
            "date": date,
            "T": {
                "min": rnd(min(T_valid)) if T_valid else None,
                "max": rnd(max(T_valid)) if T_valid else None,
                "app_min": rnd(min((x for x in v(Tapp) if x is not None), default=None)),
                "app_max": rnd(max((x for x in v(Tapp) if x is not None), default=None)),
                "night_mean": rnd(mean(sub(T2m, night_idx))),
                "day_mean": rnd(mean(sub(T2m, day_idx))),
            },
            "Td_mean": rnd(mean(v(Td))), "RH_mean": rnd(mean(v(RH))),
            "vis_min": rnd(min((x for x in v(VIS) if x is not None), default=None)),
            "precip_mm": rnd(prec_sum, 1),
            "precip_prob_max": max((x for x in v(PrecP) if x is not None), default=None),
            "snow_cm": rnd(snow_sum, 1),
            "weathercode_dom": wc_dom, "pressure_mean": rnd(mean(v(P))),
            "wind": {
                "mean_kmh": rnd(mean(ws_vals)), "max_kmh": rnd(max(ws_vals)) if ws_vals else None,
                "gust_max_kmh": rnd(max(wg_vals)) if wg_vals else None,
                "spd80": rnd(mean([x for x in v(WS80) if x is not None])),
            },
            "cloud": {
                "total": rnd(mean(v(CC))), "low": rnd(mean(v(CCL))),
                "mid": rnd(mean(v(CCM))), "high": rnd(mean(v(CCH))),
                "c925": rnd(mean(v(CC925))), "c850": rnd(mean(v(CC850))),
                "c700": rnd(mean(v(CC700))), "c500": rnd(mean(v(CC500))),
                "c300": rnd(mean(v(CC300))),
            },
            "conv": {
                "CAPE_max": rnd(max((x for x in v(CAPE) if x is not None), default=None)),
                "CAPE_mean": rnd(mean(v(CAPE))),
                "LI_min": rnd(min((x for x in v(LI) if x is not None), default=None)),
                "CIN": rnd(mean(v(CIN))),
            },
            "tp": {
                "T925":rnd(mean(v(T925))),"T850":rnd(mean(v(T850))),"T700":rnd(mean(v(T700))),
                "T600":rnd(mean(v(T600))),"T500":rnd(mean(v(T500))),"T400":rnd(mean(v(T400))),
                "T300":rnd(mean(v(T300))),"T250":rnd(mean(v(T250))),"T200":rnd(mean(v(T200))),
                "Td925":rnd(mean(v(Td925))),"Td850":rnd(mean(v(Td850))),
                "Td700":rnd(mean(v(Td700))),"Td500":rnd(mean(v(Td500))),
                "def850":rnd((mean(v(T850)) or 0)-(mean(v(Td850)) or 0),1),
                "def700":rnd((mean(v(T700)) or 0)-(mean(v(Td700)) or 0),1),
                "T50":rnd(mean(v(T50))),"T30":rnd(mean(v(T30))),"T10":rnd(mean(v(T10))),
            },
            "gp": {
                "Z925":rnd(mean(v(Z925))),"Z850":rnd(mean(v(Z850))),"Z700":rnd(mean(v(Z700))),
                "Z600":rnd(mean(v(Z600))),"Z500":rnd(mean(v(Z500))),"Z400":rnd(mean(v(Z400))),
                "Z300":rnd(mean(v(Z300))),"Z250":rnd(mean(v(Z250))),"Z200":rnd(mean(v(Z200))),
                "Z150":rnd(mean(v(Z150))),"Z100":rnd(mean(v(Z100))),
                "Z50":rnd(mean(v(Z50))),"Z30":rnd(mean(v(Z30))),"Z10":rnd(mean(v(Z10))),
            },
            "rh": {
                "RH925":rnd(mean(v(RH925))),"RH850":rnd(mean(v(RH850))),
                "RH700":rnd(mean(v(RH700))),"RH500":rnd(mean(v(RH500))),
                "RH300":rnd(mean(v(RH300))),
            },
            "omega": {
                "W1000":rnd(mean(v(W1000)),3),"W925":rnd(mean(v(W925)),3),
                "W850":rnd(mean(v(W850)),3),"W700":rnd(mean(v(W700)),3),
                "W600":rnd(mean(v(W600)),3),"W500":rnd(mean(v(W500)),3),
                "W400":rnd(mean(v(W400)),3),"W300":rnd(mean(v(W300)),3),
            },
            "wp": {
                "925":{"s":ws925m,"d":wd925m},"850":{"s":ws850m,"d":wd850m},
                "700":{"s":ws700m,"d":wd700m},"500":{"s":ws500m,"d":wd500m},
                "300":{"s":ws300m,"d":wd300m},"250":{"s":ws250m,"d":wd250m},
                "200":{"s":ws200m,"d":wd200m},
            },
            "freeze_level_m": rnd(mean(frz_vals)),
        }
        result.append(day_data)

    return result

# ── Хэш данных для проверки изменений ────────────────────────────────────────

def data_hash(days):
    # Хэш по ключевым полям — если не изменился, не перегенерируем
    key = json.dumps([{
        "date": d["date"],
        "T": d["T"],
        "precip_mm": d["precip_mm"],
        "gp_Z500": d.get("gp", {}).get("Z500"),
    } for d in days], sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]

# ── Промпт ────────────────────────────────────────────────────────────────────

WMO_CODES = {
    0:"ясно", 1:"преимущественно ясно", 2:"переменная облачность", 3:"пасмурно",
    45:"туман", 48:"изморозь", 51:"слабая морось", 53:"морось", 55:"сильная морось",
    61:"слабый дождь", 63:"дождь", 65:"сильный дождь",
    71:"слабый снег", 73:"снег", 75:"сильный снег", 77:"снежная крупа",
    80:"ливень", 81:"сильный ливень", 82:"очень сильный ливень",
    85:"снегопад", 86:"сильный снегопад",
    95:"гроза", 96:"гроза с градом", 99:"сильная гроза с градом",
}

def build_prompt(days):
    now_str = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M местного")

    lines = [
        f"Время генерации: {now_str}",
        f"Место: Одесса, Украина (46.43°N, 30.74°E, побережье Чёрного моря)",
        "",
        "Ты — опытный синоптик. Напиши профессиональный синоптический анализ прогноза погоды.",
        "Используй все предоставленные данные: температуру по уровням, геопотенциал,",
        "вертикальное движение (омега), влажность, облачность, CAPE, LI, нулевую изотерму.",
        "Анализируй связи между параметрами. Текст живой, профессиональный, без шаблонных фраз.",
        "Если предвидятся значительные события (грозы, шторм, резкое похолодание/потепление,",
        "сильные осадки) — акцентируй на них. Пиши по-русски.",
        "ВАЖНО: пиши строго в будущем времени — погода ещё не наступила, это прогноз.",
        "Не 'устанавливается', 'наблюдается', 'составляет' — а 'установится', 'ожидается', 'составит'.",
        "Сегодняшний день тоже прогноз, не факт — используй будущее время.",
        "",
        "ДАННЫЕ ПРОГНОЗА (ансамбль 8 моделей: ECMWF/GFS/ICON/GEM/UKMO/ARPEGE/CMA, агрегаты по дням):",
        "",
    ]

    day_labels = ["СЕГОДНЯ", "ЗАВТРА", "День +2", "День +3", "День +4"]

    for i, d in enumerate(days):
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        label = day_labels[i] if i < len(day_labels) else f"День +{i}"
        wc_label = WMO_CODES.get(d.get("weathercode_dom"), f"код {d.get('weathercode_dom')}")
        tp=d.get("tp",{}); gp=d.get("gp",{}); rh=d.get("rh",{})
        om=d.get("omega",{}); wp=d.get("wp",{}); cv=d.get("conv",{})
        cl=d.get("cloud",{}); ws=d.get("wind",{})
        def wdir(deg):
            if deg is None: return "?"
            return ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"][int((deg+22.5)/45)%8]
        lines += [
            f"-- {label} ({dt.strftime('%d.%m')}) --",
            f"  T: {d['T']['min']}..{d['T']['max']}C  ощущ {d['T']['app_min']}..{d['T']['app_max']}C  день {d['T']['day_mean']}C  ночь {d['T']['night_mean']}C",
            f"  Td={d['Td_mean']}C  RH={d['RH_mean']}%  P={d['pressure_mean']}гПа  вид.мин={d.get('vis_min')}м",
            f"  Осадки: {d['precip_mm']}мм  вер.до {d['precip_prob_max']}%  снег {d['snow_cm']}см",
            f"  Погода: {wc_label}",
            f"  Ветер 10м: ср {ws.get('mean_kmh')} макс {ws.get('max_kmh')} пор {ws.get('gust_max_kmh')} км/ч  80м: {ws.get('spd80')} км/ч",
            f"  Облачность: общ {cl.get('total')}% низ {cl.get('low')}% ср {cl.get('mid')}% выс {cl.get('high')}%",
            f"  Облачность по уровням: 925={cl.get('c925')}% 850={cl.get('c850')}% 700={cl.get('c700')}% 500={cl.get('c500')}% 300={cl.get('c300')}%",
            f"  Нулевая изотерма: {d['freeze_level_m']}м",
            f"  КОНВЕКЦИЯ: CAPE макс/ср={cv.get('CAPE_max')}/{cv.get('CAPE_mean')} Дж/кг  LI мин={cv.get('LI_min')}  CIN={cv.get('CIN')}",
            f"  ПРОФИЛЬ Т (C): 925={tp.get('T925')} 850={tp.get('T850')} 700={tp.get('T700')} 600={tp.get('T600')} 500={tp.get('T500')} 400={tp.get('T400')} 300={tp.get('T300')} 250={tp.get('T250')} 200={tp.get('T200')}",
            f"  Точка росы: 925={tp.get('Td925')} 850={tp.get('Td850')} 700={tp.get('Td700')} 500={tp.get('Td500')}  деф T-Td: 850={tp.get('def850')} 700={tp.get('def700')}",
            f"  Стратосфера T: 50={tp.get('T50')}C 30={tp.get('T30')}C 10={tp.get('T10')}C",
            f"  ГЕОПОТЕНЦИАЛ (м): 925={gp.get('Z925')} 850={gp.get('Z850')} 700={gp.get('Z700')} 600={gp.get('Z600')} 500={gp.get('Z500')} 400={gp.get('Z400')} 300={gp.get('Z300')} 250={gp.get('Z250')} 200={gp.get('Z200')} 150={gp.get('Z150')} 100={gp.get('Z100')}",
            f"  Стратосфера Z: 50={gp.get('Z50')} 30={gp.get('Z30')} 10={gp.get('Z10')}",
            f"  ВЛАЖНОСТЬ (%): 925={rh.get('RH925')} 850={rh.get('RH850')} 700={rh.get('RH700')} 500={rh.get('RH500')} 300={rh.get('RH300')}",
            f"  ОМЕГА (Па/с, -=восх): 1000={om.get('W1000')} 925={om.get('W925')} 850={om.get('W850')} 700={om.get('W700')} 600={om.get('W600')} 500={om.get('W500')} 400={om.get('W400')} 300={om.get('W300')}",
            f"  ВЕТЕР: 925={wp.get('925',{}).get('s')}км/ч {wdir(wp.get('925',{}).get('d'))}  850={wp.get('850',{}).get('s')} {wdir(wp.get('850',{}).get('d'))}  700={wp.get('700',{}).get('s')} {wdir(wp.get('700',{}).get('d'))}  500={wp.get('500',{}).get('s')} {wdir(wp.get('500',{}).get('d'))}  300={wp.get('300',{}).get('s')} {wdir(wp.get('300',{}).get('d'))}  200={wp.get('200',{}).get('s')} {wdir(wp.get('200',{}).get('d'))}",
            "",
        ]

    lines += [
        "СТРУКТУРА ОТВЕТА (строго):",
        "1. ## Сегодня — подробный анализ (3-5 предложений)",
        "2. ## Завтра — подробный анализ (3-5 предложений)",
        "3. ## Последующие 3 дня — общий обзор (3-4 предложения)",
        "4. ## ⚠️ Предупреждения — только если есть реальные риски (гроза, шторм, сильные осадки). Если рисков нет — этот раздел пропусти.",
        "5. ## Тенденция — краткий прогноз изменений за горизонтом (1-2 предложения)",
        "",
        "Не используй таблицы. Не повторяй цифры из данных дословно — интерпретируй их синоптически.",
    ]

    return "\n".join(lines)

# ── Запрос к Claude API ───────────────────────────────────────────────────────

async def _generate_tts_async(text, out_path):
    communicate = edge_tts.Communicate(text, voice="ru-RU-SvetlanaNeural", rate="-5%")
    await communicate.save(out_path)

def generate_tts(text, out_path):
    try:
        asyncio.run(_generate_tts_async(text, out_path))
        size_kb = os.path.getsize(out_path) // 1024
        print(f"  [TTS] Сохранено: {out_path} ({size_kb} кб)")
    except Exception as e:
        print(f"  [TTS] Ошибка: {e}")

def call_claude(prompt, api_key):
    payload = json.dumps({
        "model": "google/gemini-2.0-flash-exp:free",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://ruslan591.github.io/weather-_Odessa/",
            "X-Title": "Odessa Weather Forecast",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    return resp["choices"][0]["message"]["content"]

# ── Основная логика ───────────────────────────────────────────────────────────

def main():
    if not ai_enabled():
        print("  [OR] Анализ отключён (AI_ANALYSIS_ENABLED=false в .env)")
        return

    api_key = load_api_key()
    if not api_key:
        print("  [OR] OPENROUTER_API_KEY не найден — пропускаю генерацию анализа")
        return

    print("\n  🤖 Генерация анализа (OpenRouter/Gemini)...")

    # Загружаем текущий результат (если есть)
    existing = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # Запрашиваем данные
    try:
        raw = fetch_ensemble()
    except Exception as e:
        print(f"  [OR] Ошибка open-meteo: {e}")
        return

    days = aggregate_days(raw)
    if not days:
        print("  [OR] Нет данных для анализа")
        return

    # Проверяем изменились ли данные
    current_hash = data_hash(days)
    prev_hash = existing.get("data_hash", "")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if current_hash == prev_hash and existing.get("text"):
        # Данные не изменились — обновляем только метку времени
        existing["last_checked"] = now_iso
        existing["changed"] = False
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"  [OR] Данные не изменились — обновлена метка времени")
        return

    # Данные изменились — генерируем новый анализ
    prompt = build_prompt(days)
    print(f"  [OR] Промпт: ~{len(prompt.split())} слов, запрос к Claude...")

    try:
        text = call_claude(prompt, api_key)
    except Exception as e:
        print(f"  [OR] Ошибка OpenRouter API: {e}")
        return

    result = {
        "generated_at": now_iso,
        "last_checked": now_iso,
        "changed": True,
        "data_hash": current_hash,
        "days_count": len(days),
        "text": text,
    }
    # TTS
    mp3_path = OUTPUT_FILE.replace(".json", ".mp3")
    generate_tts(text, mp3_path)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  [OR] ✅ Анализ сохранён ({len(text)} символов)")

if __name__ == "__main__":
    main()