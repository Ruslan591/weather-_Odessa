# -*- coding: utf-8 -*-
"""tg_htf.py -- свечи H1 и H4 как дополнительный фильтр входа (по просьбе пользователя 2026-11-17). Только stdlib, без побочных эффектов.
По ТЕКУЩЕЙ (формирующейся) свече каждого таймфрейма считает три вещи:
  цвет     - close сейчас против open свечи (зелёная / красная);
  размер   - тело свечи |close-open| в долях среднего тела последних n (20) закрытых свечей (0.8x = 80% от обычного);
  фаза     - сколько времени свечи уже прошло (0..100%).
Сильно против сделки: свеча идёт против стороны сделки, тело >= strong (1.0) среднего, фаза >= early (15%); после late (75%) порог ниже в 0.6 раза (свеча почти закрылась против нас).
Свеча в начале (фаза < early) цвет не определяет: нейтрально.
Режим (POS_DIR/tg_htf.json): {"mode": "shadow|block|off", "n": 20, "strong": 1.0, "early": 0.15, "late": 0.75}.
  shadow (по умолчанию) - только показ в посте и запись в feat, вердикт не меняется; block - сильное «против» на H1 или H4 даёт «ждём»; off - без строки.
Сеть: публичные свечи data-api.binance.vision, кэш 40 с; нет данных -> условие не применяется. Удалить файл -> бот работает без блока (tg_express и tg_bot подключают через try/except).
Запись в feat: h = [цвет H1 (1/-1/0), тело H1 в x от среднего, фаза H1, то же для H4]."""
import json, os, time, urllib.request

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CFG = os.path.join(D, "tg_htf.json")
BASE = "https://data-api.binance.vision/api/v3/klines"
PER = {"1h": 3600, "4h": 14400}
NM = {"1h": "H1", "4h": "H4"}
_cache = {}


def cfg():
    c = {"mode": "shadow", "n": 20, "strong": 1.0, "early": 0.15, "late": 0.75}
    try: c.update(json.load(open(CFG, encoding="utf-8")))
    except Exception: pass
    return c


def _kl(sym, iv, limit=30):
    now = time.time(); k = (sym, iv); c = _cache.get(k)
    if c and now - c[0] < 40: return c[1]
    u = "%s?symbol=%sUSDT&interval=%s&limit=%d" % (BASE, sym, iv, limit)
    for _ in range(2):
        try:
            raw = json.load(urllib.request.urlopen(u, timeout=6))
            if len(raw) >= 10: _cache[k] = (now, raw); return raw
        except Exception: time.sleep(0.3)
    return c[1] if (c and now - c[0] < 300) else None


def calc(raw, per_s, now=None, n=20):
    """raw: klines Binance (последняя - формирующаяся). Возвращает {dir, body_x, rng_x, phase, o, c} или None."""
    now = time.time() if now is None else now; nowms = int(now * 1000); per = per_s * 1000
    cur = None; closed = []
    for k in raw:
        t = int(k[0])
        if t + per <= nowms: closed.append(k)
        elif t <= nowms: cur = k
    closed = closed[-n:]
    if cur is None or len(closed) < max(8, n // 2): return None
    ab = sum(abs(float(k[4]) - float(k[1])) for k in closed) / len(closed)
    ar = sum(float(k[2]) - float(k[3]) for k in closed) / len(closed)
    if ab <= 0 or ar <= 0: return None
    o, h, l, c = float(cur[1]), float(cur[2]), float(cur[3]), float(cur[4])
    d = 1 if c > o else (-1 if c < o else 0)
    return {"dir": d, "body_x": abs(c - o) / ab, "rng_x": (h - l) / ar, "phase": min(1.0, max(0.0, (nowms - int(cur[0])) / per)), "o": o, "c": c}


def metrics(sym, now=None):
    """{'1h': {...}, '4h': {...}}; ключи только для таймфреймов с данными; None, если нет ни одного."""
    cf = cfg(); out = {}
    for iv, per in PER.items():
        raw = _kl(sym, iv)
        m = calc(raw, per, now, int(cf["n"])) if raw else None
        if m: out[iv] = m
    return out or None


def status(m, side, cf=None):
    """'with' | 'early' | 'flat' | 'weak' | 'strong' для одного таймфрейма относительно стороны сделки (long/short)."""
    cf = cf or cfg(); sg = 1 if side == "long" else -1
    if m["phase"] < float(cf["early"]): return "early"
    if m["dir"] == 0: return "flat"
    if m["dir"] == sg: return "with"
    thr = float(cf["strong"]) * (0.6 if m["phase"] >= float(cf["late"]) else 1.0)
    return "strong" if m["body_x"] >= thr else "weak"


MARK = {"with": "✓", "early": "·", "flat": "·", "weak": "⚠", "strong": "✗"}


def _fmt(iv, m, side=None, cf=None):
    col = "🟢" if m["dir"] > 0 else ("🔴" if m["dir"] < 0 else "⚪")
    s = "%s %s %.1f×·%d%%" % (NM[iv], col, m["body_x"], round(m["phase"] * 100))
    if side: s += " " + MARK[status(m, side, cf)]
    return s


def cond(side, sym, now=None):
    """(условие (ok, good, bad), запись для feat) или (None, None). В режиме shadow условие всегда ok (только показ); ⚠ в тексте, если в режиме block было бы «ждём»."""
    cf = cfg()
    if cf.get("mode") == "off": return None, None
    ms = metrics(sym, now)
    if not ms: return None, None
    parts = []; strong = []; rec = []
    for iv in ("1h", "4h"):
        m = ms.get(iv)
        if not m: rec += [None, None, None]; continue
        parts.append(_fmt(iv, m, side, cf)); rec += [m["dir"], round(m["body_x"], 2), round(m["phase"], 2)]
        if status(m, side, cf) == "strong": strong.append(NM[iv])
    txt = " | ".join(parts)
    if cf.get("mode") == "block":
        return (not strong, txt, txt + ": %s идёт против %s" % (" и ".join(strong), side.upper())), rec
    return (True, txt + (" (против: только запись)" if strong else ""), ""), rec


def line(sym, side=None):
    """Строка для постов без мнения (не экспресс): «🕯 H1 🔴 0.8×·45% | H4 🟢 1.3×·20%»; × - тело от среднего, % - фаза свечи; \"\" если нет данных или off."""
    cf = cfg()
    if cf.get("mode") == "off": return ""
    ms = metrics(sym)
    if not ms: return ""
    return "🕯 " + " | ".join(_fmt(iv, ms[iv], side, cf) for iv in ("1h", "4h") if iv in ms)
