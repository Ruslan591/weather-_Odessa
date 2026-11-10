# -*- coding: utf-8 -*-
"""tg_regime.py -- режим рынка: падающий (down) / растущий (up) / флэт (flat). Только stdlib, только ЗАКРЫТЫЕ часовые свечи.
Опора: BTCUSDT 1h (EMA20/50/200, наклон регрессии 24 ч в ATR, ADX14, ход за 24 ч) и ширина рынка (доля корзины из 20 пар в минусе за 24 ч).
6 факторов за каждую сторону. down: медвежьих >= 4 и ADX >= 18; up: бычьих >= 4 и ADX >= 18; иначе flat. Гистерезис: смена режима после 3 подряд подтверждений (оценка раз в 5 мин).
Функции regime_at / classify чистые (используются и в живом боте, и в бэктесте истории: scripts/regime_study.py). Файлы POS_DIR: tg_regime.json (текущий режим), tg_regime_log.jsonl (раз в 30 мин).
Сейчас только ПОКАЗ и запись в ордера/разборы; фильтр входов по режиму не включён. Удалить файл: tg_bot/tg_gate подключают через try/except."""
import json, math, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
REGF = os.path.join(D, "tg_regime.json"); LOGF = os.path.join(D, "tg_regime_log.jsonl")
BASE = "https://data-api.binance.vision/api/v3/klines"
BASKET = ["ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK", "DOT", "LTC", "BCH", "NEAR", "UNI", "ATOM", "ETC", "XLM", "APT", "ARB", "OP"]
NEED = 3; ADX_MIN = 18.0; HOUR = 3600000
RU = {"down": "падающий", "up": "растущий", "flat": "флэт"}


def klines(sym, interval="1h", limit=500, start=None):
    u = "%s?symbol=%sUSDT&interval=%s&limit=%d" % (BASE, sym, interval, limit) + ("&startTime=%d" % start if start else "")
    for _ in range(3):
        try: return json.load(urllib.request.urlopen(u, timeout=25))
        except Exception: time.sleep(1)
    return []


def ema(xs, n):
    """EMA по списку, первые n-1 значений None, затем SMA-затравка."""
    out = [None] * len(xs)
    if len(xs) < n: return out
    e = sum(xs[:n]) / n; out[n - 1] = e; k = 2.0 / (n + 1)
    for i in range(n, len(xs)): e = xs[i] * k + e * (1 - k); out[i] = e
    return out


def atr_last(h, l, c, n=14):
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return sum(tr[-n:]) / n if len(tr) >= n else None


def adx_last(h, l, c, n=14):
    """ADX по Уайлдеру (последнее значение) или None."""
    if len(c) < 2 * n + 2: return None
    tr = []; pdm = []; mdm = []
    for i in range(1, len(c)):
        up = h[i] - h[i - 1]; dn = l[i - 1] - l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0); mdm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    atr = sum(tr[:n]); p = sum(pdm[:n]); m = sum(mdm[:n]); dx = []
    for i in range(n, len(tr) + 1):
        if i > n: atr = atr - atr / n + tr[i - 1]; p = p - p / n + pdm[i - 1]; m = m - m / n + mdm[i - 1]
        pi = 100 * p / atr if atr else 0; mi = 100 * m / atr if atr else 0; dx.append(100 * abs(pi - mi) / (pi + mi) if (pi + mi) else 0)
    if len(dx) < n: return None
    a = sum(dx[:n]) / n
    for x in dx[n:]: a = (a * (n - 1) + x) / n
    return a


def ols_slope(ys):
    n = len(ys); xm = (n - 1) / 2.0; ym = sum(ys) / n
    den = sum((i - xm) ** 2 for i in range(n)); return sum((i - xm) * (ys[i] - ym) for i in range(n)) / den if den else 0.0


def regime_at(h, l, c, down_share=None, median_chg=None):
    """Сырой режим по закрытым часовым свечам BTC (списки до текущей закрытой включительно) и ширине рынка (down_share: доля корзины в минусе за 24 ч, 0..1).
    Возвращает dict {raw, bear, bull, adx, ret24, slope24_atr, ...} или None, если данных мало."""
    if len(c) < 210: return None
    e20 = ema(c, 20)[-1]; e50 = ema(c, 50)[-1]; e200 = ema(c, 200)[-1]; a = atr_last(h, l, c); adx = adx_last(h, l, c)
    if not a or adx is None: return None
    ret24 = c[-1] / c[-25] - 1; ret72 = c[-1] / c[-73] - 1; sl = ols_slope(c[-24:]) * 24 / a
    bear = sum([c[-1] < e50, e20 < e50, c[-1] < e200, sl <= -1.0, ret24 <= -0.01, (down_share is not None and down_share >= 0.65)])
    bull = sum([c[-1] > e50, e20 > e50, c[-1] > e200, sl >= 1.0, ret24 >= 0.01, (down_share is not None and down_share <= 0.35)])
    raw = "down" if (bear >= 4 and adx >= ADX_MIN) else ("up" if (bull >= 4 and adx >= ADX_MIN) else "flat")
    return {"raw": raw, "bear": int(bear), "bull": int(bull), "adx": round(adx, 1), "ret24": round(ret24 * 100, 2), "ret72": round(ret72 * 100, 2), "slope24_atr": round(sl, 2),
            "ema": [round(e20, 1), round(e50, 1), round(e200, 1)], "price": c[-1], "down_share": None if down_share is None else round(down_share, 2), "median_chg": None if median_chg is None else round(median_chg * 100, 2)}


def _closed(ks, now_ms):
    return [k for k in ks if int(k[0]) + HOUR <= now_ms]


def compute(now_ms=None):
    """Живой расчёт: BTC 1h (500 свечей) + 20 пар по 26 свечей. Возвращает dict regime_at или None (нет данных)."""
    now_ms = now_ms or int(time.time() * 1000)
    btc = _closed(klines("BTC", "1h", 500), now_ms)
    if len(btc) < 210: return None
    with ThreadPoolExecutor(max_workers=5) as ex: alts = list(ex.map(lambda s: _closed(klines(s, "1h", 27), now_ms), BASKET))
    chg = []
    for ks in alts:
        if len(ks) >= 25: chg.append(float(ks[-1][4]) / float(ks[-25][4]) - 1)
    ds = (sum(1 for x in chg if x < 0) / len(chg)) if len(chg) >= 12 else None; med = sorted(chg)[len(chg) // 2] if len(chg) >= 12 else None
    f = regime_at([float(k[2]) for k in btc], [float(k[3]) for k in btc], [float(k[4]) for k in btc], ds, med)
    if f: f["t_candle"] = int(btc[-1][0]); f["n_basket"] = len(chg)
    return f


def _load():
    try: return json.load(open(REGF, encoding="utf-8"))
    except Exception: return {}


def update(force=False):
    """Раз в >=5 мин: пересчёт и гистерезис; пишет tg_regime.json. Возвращает текущее состояние."""
    st = _load(); now = int(time.time() * 1000)
    if not force and now - int(st.get("t", 0)) < 290000: return st
    f = compute(now)
    if not f: return st
    cur = st.get("regime"); cand = f["raw"]; n = int(st.get("cand_n", 0))
    if cur is None: cur = cand; n = 0; since = now
    elif cand == cur: n = 0; since = st.get("since", now)
    else:
        n += 1; since = st.get("since", now)
        if n >= NEED: cur = cand; n = 0; since = now
    strength = max(f["bear"], f["bull"]) / 6.0
    st = {"regime": cur, "raw": cand, "cand_n": n, "since": since, "t": now, "strength": round(strength, 2), "detail": f}
    tmp = REGF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, REGF)
    try:
        last = 0
        if os.path.exists(LOGF):
            with open(LOGF, "rb") as fh: fh.seek(max(0, os.path.getsize(LOGF) - 400)); tail = fh.read().decode("utf-8", "ignore").strip().split("\n")[-1]; last = json.loads(tail).get("t", 0)
        if now - last >= 1800000:
            with open(LOGF, "a", encoding="utf-8") as fh: fh.write(json.dumps({"t": now, "regime": cur, "raw": cand, "bear": f["bear"], "bull": f["bull"], "adx": f["adx"], "ret24": f["ret24"], "ds": f["down_share"]}, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception: pass
    return st


def get(max_age_min=30):
    """Текущее состояние из файла (None, если нет или старше max_age_min). Без сети."""
    st = _load()
    if not st or (time.time() * 1000 - int(st.get("t", 0))) > max_age_min * 60000: return None
    return st


def snap():
    """Краткий снимок для записи в ордер/разбор."""
    st = get()
    return None if not st else {"regime": st["regime"], "raw": st.get("raw"), "strength": st.get("strength"), "t": st.get("t")}


def line(side=None, st=None):
    """Строка для поста; side (long/short) - направление сделки: добавляется «по режиму» / «против режима»."""
    st = st or get()
    if not st: return ""
    d = st.get("detail") or {}; r = st["regime"]
    s = "🧭 Рынок: %s (факторов %d из 6; BTC %+.1f%% за 24 ч, ADX %s%s)" % (RU[r], max(d.get("bear", 0), d.get("bull", 0)), d.get("ret24", 0), d.get("adx", "?"), "" if d.get("down_share") is None else ", %d%% корзины в минусе" % round(100 * d["down_share"]))
    if st.get("raw") and st["raw"] != r: s += "; новый режим %s набирает подтверждения %d из %d" % (RU[st["raw"]], st.get("cand_n", 0), NEED)
    if side and r in ("down", "up"): s += "\n" + (("✅ сделка по режиму" if (side == "short") == (r == "down") else "⚠️ сделка ПРОТИВ режима (%s)" % ("лонг на падающем рынке" if side == "long" else "шорт на растущем рынке")))
    return s
