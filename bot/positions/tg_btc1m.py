# -*- coding: utf-8 -*-
"""tg_btc1m.py -- фильтр входа по BTCUSDT 1m (по ЗАКРЫТЫМ минутным свечам). Только stdlib, без побочных эффектов, без сети в чистых функциях.
Проверка перед входом по альту (сигнал на 5m): что делает BTC прямо сейчас. gate(side) -> {ok, allowed, blocked, good, bad, snap}.
Вход РАЗРЕШЁН, если нет блокировки и выполнено хотя бы одно из трёх условий (для SHORT; для LONG зеркально):
  1) импульс: последние 2 закрытые свечи BTC строго красные (close<open);
  2) положение: цена BTC ниже EMA9 (1m) и удаляется от неё вниз (расстояние больше, чем на предыдущей свече);
  3) осциллятор: RSI14 (1m) от 40 до 60 и направлен вниз (ниже, чем 2 свечи назад).
БЛОКИРОВКА SHORT: (а) в последних 3 свечах аномально крупная зелёная (тело >= BIG_K x медианного тела предыдущих 20) или 3 закрытия подряд вверх; (б) RSI14 < 30.
БЛОКИРОВКА LONG: (а) крупная красная в последних 3 свечах или 3 закрытия подряд вниз; (б) RSI14 > 70.
Нет данных (сеть, мало свечей) -> gate возвращает None, вызывающий код фильтр не применяет (не блокирует).
Выключить: POS_DIR/tg_btc1m.json {"enabled": false}, либо удалить файл (tg_express подключает через try/except).
Пороги: EMA_N=9, RSI_N=14, BIG_K=3.0 -- начальные, подбираются по опыту."""
import json, os, time, urllib.request

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CFG = os.path.join(D, "tg_btc1m.json")
BASE = "https://data-api.binance.vision/api/v3/klines"
EMA_N = 9; RSI_N = 14; BIG_K = 3.0; MS = 60000; _cache = {"t": 0, "ks": None}


def enabled():
    try: return bool(json.load(open(CFG, encoding="utf-8")).get("enabled", True))
    except Exception: return True


def klines(limit=80):
    """Закрытые 1m свечи BTCUSDT [(o,h,l,c)...]; кэш 20 с. None при ошибке."""
    now = time.time()
    if _cache["ks"] and now - _cache["t"] < 20: return _cache["ks"]
    u = "%s?symbol=BTCUSDT&interval=1m&limit=%d" % (BASE, limit)
    for _ in range(2):
        try:
            raw = json.load(urllib.request.urlopen(u, timeout=8)); nowms = int(now * 1000)
            ks = [(float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in raw if int(k[0]) + MS <= nowms]
            if len(ks) >= 40: _cache["t"] = now; _cache["ks"] = ks; return ks
        except Exception: time.sleep(0.5)
    return _cache["ks"] if (_cache["ks"] and now - _cache["t"] < 120) else None


def ema(xs, n):
    e = sum(xs[:n]) / n; out = [None] * (n - 1) + [e]; k = 2.0 / (n + 1)
    for x in xs[n:]: e = x * k + e * (1 - k); out.append(e)
    return out


def rsi(xs, n):
    """RSI по Уайлдеру, список значений (первые n None)."""
    out = [None] * len(xs)
    if len(xs) <= n: return out
    g = [max(xs[i] - xs[i - 1], 0.0) for i in range(1, len(xs))]; l = [max(xs[i - 1] - xs[i], 0.0) for i in range(1, len(xs))]
    ag = sum(g[:n]) / n; al = sum(l[:n]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _mode():
    """rsi (по умолчанию, спецификация 2026-11-11) или legacy (старые 3 условия + блокировки). tg_btc1m.json {"mode": "legacy"}."""
    try: return str(json.load(open(CFG, encoding="utf-8")).get("mode", "rsi"))
    except Exception: return "rsi"


ACT_BRK = 1.0     # «активно падает/растёт» на пробое: RSI14 BTC 1m изменился минимум на столько пунктов за 2 свечи (допущение Claude)


def _rsi_rule(rs, rsd, sg, setup):
    """Правила RSI(14) BTC 1m по стороне сделки и стратегии. Возвращает (in_range, dir_ok, blocked, (lo, hi), block_txt)."""
    if setup == "breakout":
        lo, hi = (35.0, 50.0) if sg < 0 else (50.0, 65.0); act = ACT_BRK; lim = 30.0 if sg < 0 else 70.0
    else:
        lo, hi = (45.0, 65.0) if sg < 0 else (35.0, 55.0); act = 0.0; lim = 32.0 if sg < 0 else 68.0
    blocked = rs < lim if sg < 0 else rs > lim
    return lo <= rs <= hi, rsd * sg > act, blocked, (lo, hi), lim


def evaluate(ks, side, setup="bounce"):
    """Чистая функция (используется и в бэктесте): ks = закрытые свечи (o,h,l,c), side long|short, setup bounce|breakout. None, если свечей мало."""
    if not ks or len(ks) < 40: return None
    sg = 1 if side == "long" else -1; nm = "LONG" if sg > 0 else "SHORT"
    o = [k[0] for k in ks]; c = [k[3] for k in ks]
    e = ema(c, EMA_N); r = rsi(c, RSI_N)
    if e[-1] is None or e[-2] is None or r[-1] is None or r[-3] is None: return None
    body = [abs(c[i] - o[i]) for i in range(len(c))]
    med = sorted(body[-23:-3])[10] or 1e-9                      # медианное тело 20 свечей до последних трёх
    dirn = lambda i: (c[i] - o[i]) * sg                          # >0: свеча по направлению сделки
    impulse = dirn(-1) > 0 and dirn(-2) > 0
    d_now = (c[-1] - e[-1]) * sg; d_prev = (c[-2] - e[-2]) * sg
    pos = d_now > 0 and d_now > d_prev
    rs = r[-1]; rs_ok = 40 <= rs <= 60 and (rs - r[-3]) * sg > 0
    big = [i for i in (-1, -2, -3) if dirn(i) < 0 and body[i] >= BIG_K * med]
    run3 = all((c[i] - c[i - 1]) * sg < 0 for i in (-1, -2, -3))
    exh = rs < 30 if sg < 0 else rs > 70
    mine = "красные" if sg < 0 else "зелёные"; opp = "зелёная" if sg < 0 else "красная"
    blocks = []
    if big: blocks.append("крупная %s свеча BTC (тело x%.1f от обычного)" % (opp, body[big[0]] / med))
    if run3: blocks.append("BTC 3 минуты подряд идёт против %s" % ("шорта (растёт)" if sg < 0 else "лонга (падает)"))
    if exh: blocks.append("RSI BTC 1m %.0f: %s" % (rs, "перепродан, жди отскок" if sg < 0 else "перекуплен, жди откат"))
    goods = []
    if impulse: goods.append("2 свечи подряд: %s" % mine)
    if pos: goods.append("%s EMA%d и уходит %s" % ("ниже" if sg < 0 else "выше", EMA_N, "вниз" if sg < 0 else "вверх"))
    if rs_ok: goods.append("RSI %.0f %s" % (rs, "вниз" if sg < 0 else "вверх"))
    allowed = bool(goods); ok = allowed and not blocks
    if _mode() != "legacy":      # спецификация 2026-11-11: только RSI14 BTC 1m (диапазон + направление + запретная зона), свечи/EMA в решении не участвуют
        rsd_ = rs - r[-3]; inr, dok, blk, (lo, hi), lim = _rsi_rule(rs, rsd_, sg, setup)
        allowed = inr and dok; ok = allowed and not blk; blocks = []
        if blk: blocks.append("RSI BTC 1m %.0f %s %g: %s запрещён" % (rs, "<" if sg < 0 else ">", lim, "шорт" if sg < 0 else "лонг"))
        if not inr: blocks.append("RSI BTC 1m %.0f вне диапазона %g-%g" % (rs, lo, hi))
        if inr and not dok: blocks.append("RSI BTC 1m %.0f %s (%+.1f за 2 свечи)" % (rs, ("не падает активно" if sg < 0 else "не растёт активно") if setup == "breakout" else ("не направлен вниз" if sg < 0 else "не направлен вверх"), rsd_))
        goods = ["RSI BTC 1m %.0f в зоне %g-%g и %s (%+.1f)" % (rs, lo, hi, "падает" if sg < 0 else "растёт", rsd_)] if ok else []
    cols = "".join("g" if c[i] > o[i] else ("r" if c[i] < o[i] else "d") for i in (-3, -2, -1))
    snap = {"side": side, "ok": ok, "cols": cols, "emad": round((c[-1] / e[-1] - 1) * 100, 3), "rsd": round(rs - r[-3], 1), "imp": int(impulse), "pos": int(pos), "rsi": round(rs, 1), "rsi_ok": int(rs_ok), "big": int(bool(big)), "run3": int(run3), "exh": int(exh), "setup": setup, "t": int(time.time())}
    if ok: good = "BTC 1m за %s: %s" % (nm, ", ".join(goods)); bad = ""
    else: good = ""; bad = "BTC 1m против %s: %s" % (nm, "; ".join(blocks) if blocks else "нет подтверждения (RSI %.0f, свечи/EMA не в сторону сделки)" % rs)
    return {"ok": ok, "allowed": allowed, "blocked": bool(blocks), "good": good, "bad": bad, "snap": snap}


LASTF = os.path.join(D, "tg_btc1m_last.json")


def _save_last(side, snap):
    """Последний снимок по стороне (читают tg_gate для ордера и decisions для журнала). Пишет только tg_bot (процесс с gate)."""
    try:
        try: st = json.load(open(LASTF, encoding="utf-8"))
        except Exception: st = {}
        st[side] = snap; tmp = LASTF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh: json.dump(st, fh, separators=(",", ":"))
        os.replace(tmp, LASTF)
    except Exception: pass


def gate(side, setup="bounce", save=True):
    """Живой вызов: None, если выключено или нет данных (тогда фильтр не применяется). Снимок пишется в tg_btc1m_last.json."""
    if not enabled(): return None
    try: g = evaluate(klines(), side, setup)
    except Exception: return None
    if g and save: _save_last(side, g["snap"])
    return g


def line():
    """Строка для постов слежения: RSI BTC 1m и вердикт отбой/пробой по обеим сторонам. "" если выключено или нет данных."""
    g = {(sd, st): gate(sd, st, save=False) for sd in ("short", "long") for st in ("bounce", "breakout")}
    if not all(g.values()): return ""
    sn = g[("short", "bounce")]["snap"]; ic = {"r": "🔴", "g": "🟢", "d": "⚪"}; mk = lambda x: "✅" if x["ok"] else "⛔"
    return "₿ BTC 1m: %s, RSI %.0f%s\n   отбой: SHORT %s LONG %s | пробой: SHORT %s LONG %s" % ("".join(ic[x] for x in sn["cols"]), sn["rsi"], "↑" if sn["rsd"] > 0 else ("↓" if sn["rsd"] < 0 else "→"), mk(g[("short", "bounce")]), mk(g[("long", "bounce")]), mk(g[("short", "breakout")]), mk(g[("long", "breakout")]))
