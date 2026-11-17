# -*- coding: utf-8 -*-
"""tg_lead.py -- «паровозик»: связь альта с BTC на 1m (shadow-метрика, только показ и запись, ничего не блокирует). Только stdlib.
Считает по последним n (90) закрытым 1m свечам пары и BTC, общие по времени:
  rho  - корреляция 1m-доходностей, beta = cov(альт, BTC) / var(BTC);
  zB   - ход BTC за k (3) свечи в единицах его шума: sum(r_btc) / (sigma_btc * sqrt(k));
  gap  - (ожидаемый ход альта beta*sum(r_btc) минус фактический sum(r_alt)) * знак хода BTC: > 0 альт отстаёт в сторону BTC;
  zG   - gap / (sigma_resid * sqrt(k)), sigma_resid по ряду r_alt - beta*r_btc (zG > 0: альт отстаёт от BTC, должен догонять);
  L    - лаг 0..3 свечи с максимальной corr(r_alt[t], r_btc[t-L]) (L > 0: альт следует за BTC с задержкой).
Сигнал (только для показа): rho >= rho_min (0.6), |zB| >= zb_min (1.5), zG >= zg_min (1.0) -> «альт отстаёт от BTC, ждём движение в сторону BTC».
Конфиг POS_DIR/tg_lead.json: {"mode": "shadow|off", "n": 90, "k": 3, "rho_min": 0.6, "zb_min": 1.5, "zg_min": 1.0}. Удалить файл -> бот работает без строки (tg_express подключает через try/except).
Сеть: публичные 1m свечи data-api.binance.vision, кэш 25 с на символ; нет данных -> None."""
import json, math, os, time, urllib.request

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CFG = os.path.join(D, "tg_lead.json")
BASE = "https://data-api.binance.vision/api/v3/klines"
_cache = {}


def cfg():
    c = {"mode": "shadow", "n": 90, "k": 3, "rho_min": 0.6, "zb_min": 1.5, "zg_min": 1.0}
    try: c.update(json.load(open(CFG, encoding="utf-8")))
    except Exception: pass
    return c


def _kl(sym, limit=130):
    """Закрытые 1m свечи {open_time_ms: close}; кэш 25 с; None при ошибке."""
    now = time.time(); c = _cache.get(sym)
    if c and now - c[0] < 25: return c[1]
    u = "%s?symbol=%sUSDT&interval=1m&limit=%d" % (BASE, sym, limit)
    for _ in range(2):
        try:
            raw = json.load(urllib.request.urlopen(u, timeout=6)); nowms = int(now * 1000)
            d = {int(k[0]): float(k[4]) for k in raw if int(k[0]) + 60000 <= nowms}
            if len(d) >= 60: _cache[sym] = (now, d); return d
        except Exception: time.sleep(0.3)
    return c[1] if (c and now - c[0] < 180) else None


def _corr(x, y):
    n = len(x)
    if n < 20: return None
    mx = sum(x) / n; my = sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0: return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def calc(ca, cb, n=90, k=3):
    """ca, cb: {t: close} альта и BTC (1m). Возвращает dict метрик или None."""
    ts = sorted(set(ca) & set(cb))[-(n + 1):]
    if len(ts) < 40: return None
    if any(ts[i] - ts[i - 1] != 60000 for i in range(1, len(ts))):     # дыры во времени -> берём хвост без дыр
        j = max(i for i in range(1, len(ts)) if ts[i] - ts[i - 1] != 60000); ts = ts[j:]
        if len(ts) < 40: return None
    ra = [math.log(ca[ts[i]] / ca[ts[i - 1]]) for i in range(1, len(ts))]
    rb = [math.log(cb[ts[i]] / cb[ts[i - 1]]) for i in range(1, len(ts))]
    m = len(ra); ma = sum(ra) / m; mb = sum(rb) / m
    vb = sum((y - mb) ** 2 for y in rb) / m
    if vb <= 0: return None
    beta = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / m / vb
    rho = _corr(ra, rb)
    if rho is None: return None
    res = [x - beta * y for x, y in zip(ra, rb)]; mr = sum(res) / m
    sr = math.sqrt(sum((e - mr) ** 2 for e in res) / m); sb = math.sqrt(vb)
    kk = max(1, min(int(k), m))
    sb_k = sum(rb[-kk:]); sa_k = sum(ra[-kk:])
    zB = sb_k / (sb * math.sqrt(kk))
    gap = (beta * sb_k - sa_k) * (1 if sb_k >= 0 else -1)     # > 0: альт прошёл в сторону BTC меньше, чем следует по бете (отстаёт)
    zG = gap / (sr * math.sqrt(kk)) if sr > 0 else 0.0
    best = (0, rho)
    for L in (1, 2, 3):
        cl = _corr(ra[L:], rb[:-L])
        if cl is not None and cl > best[1] + 0.03: best = (L, cl)
    return {"rho": rho, "beta": beta, "zB": zB, "zG": zG, "L": best[0], "rhoL": best[1], "mb": sb_k * 100, "ma": sa_k * 100, "n": m, "k": kk}


def metrics(sym):
    """Метрики пары sym (например 'ADA') к BTC или None. Выключено ({"mode": "off"}) -> None."""
    c = cfg()
    if c.get("mode") == "off" or sym in ("BTC", "BTCUSDT"): return None
    try:
        a = _kl(sym); b = _kl("BTC")
        if not a or not b: return None
        return calc(a, b, int(c["n"]), int(c["k"]))
    except Exception: return None


def verdict(m):
    """(ключ, короткий текст): lag - альт отстаёт от BTC (в сторону BTC), own - живёт сама (rho мала), none."""
    c = cfg()
    if not m: return None, ""
    if m["rho"] < 0.4: return "own", "своя жизнь"
    if m["rho"] >= float(c["rho_min"]) and abs(m["zB"]) >= float(c["zb_min"]) and m["zG"] >= float(c["zg_min"]):
        return "lag", "отстаёт, ждём %s" % ("вверх" if m["mb"] > 0 else "вниз")
    return "none", "сигнала нет"


def line(m):
    """Короткая строка для поста (до ~110 символов) или ''."""
    if not m: return ""
    key, txt = verdict(m)
    return "📡 1m к BTC: ρ%.2f β%.1f лаг%d · BTC %+.2f%% (z%+.1f) пара %+.2f%% · отст. z%+.1f · %s" % (m["rho"], m["beta"], m["L"], m["mb"], m["zB"], m["ma"], m["zG"], txt)


def rec(m):
    """Компактная запись для feat/журнала: [rho, beta, zB, zG, L, mb, ma]."""
    if not m: return None
    return [round(m["rho"], 2), round(m["beta"], 2), round(m["zB"], 2), round(m["zG"], 2), m["L"], round(m["mb"], 3), round(m["ma"], 3)]
