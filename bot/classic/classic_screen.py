"""classic_screen.py — подбор пар для ротации: кандидаты на добавление и пары, которые стоит заменить. Решение всегда за пользователем.

Отбор кандидатов (спот Binance, пары к USDT):
  - торгуется, не стейблкоин/фиат и не токен с плечом (UP/DOWN/BULL/BEAR);
  - минимальный ордер биржи не больше ставки 6 $ (иначе позицию не открыть);
  - оборот за 24 ч не ниже MIN_VOL (ликвидность не главное, но стопы не должны проскакивать);
  - история не короче MIN_DAYS (детектору каналов нужна история);
  - ранжирование по среднему размаху дневной свечи за 14 закрытых дней в % от цены (волатильность в процентах, а не цена монеты).
Замена: у текущей пары размах заметно ниже, чем у лучших кандидатов; или нет сделок за неделю и больше; или сделок >= 10 и итог в минусе.
"""
import asyncio
import statistics

STABLE = {"USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "USDD", "EUR", "EURI", "AEUR", "UST", "USTC", "XUSD", "BFUSD", "USD1", "GBP", "TRY", "BRL", "RUB", "UAH", "ARS", "PLN", "RON", "CZK", "JPY", "MXN", "COP", "ZAR", "NGN", "IDRT", "BIDR", "AUD"}
BAD_SUFFIX = ("UP", "DOWN", "BULL", "BEAR")
MIN_VOL = 1_500_000.0
MIN_DAYS = 60
STAKE = 6.0
POOL = 40


def _min_notional(filters):
    for f in filters:
        if f.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL"):
            try:
                return float(f.get("minNotional") or 0)
            except ValueError:
                return 0.0
    return 0.0


def _range14(kl):
    done = kl[:-1]  # последняя дневная свеча ещё не закрыта
    last = done[-14:]
    if len(last) < 7:
        return None, len(done)
    v = [(float(k[2]) - float(k[3])) / float(k[4]) * 100.0 for k in last if float(k[4]) > 0]
    return (sum(v) / len(v) if v else None), len(done)


async def build(getter, cur_pairs, pair_stats, now_ms):
    info = await getter("/api/v3/exchangeInfo", {"symbolStatus": "TRADING"})
    meta = {}
    for s in info.get("symbols", []):
        if s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING" or not s.get("isSpotTradingAllowed"):
            continue
        b = s.get("baseAsset", "")
        if b in STABLE or b.endswith(BAD_SUFFIX):
            continue
        meta[s["symbol"]] = _min_notional(s.get("filters", []))
    tick = {t["symbol"]: t for t in await getter("/api/v3/ticker/24hr", {}) if t["symbol"] in meta}
    pool = []
    for sym, t in tick.items():
        try:
            price, hi, lo, vol = float(t["lastPrice"]), float(t["highPrice"]), float(t["lowPrice"]), float(t["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if price <= 0 or vol < MIN_VOL or meta[sym] > STAKE or sym in cur_pairs:
            continue
        pool.append((sym, (hi - lo) / price * 100.0, vol, price))
    pool.sort(key=lambda x: -x[1])
    want = [p[0] for p in pool[:POOL]] + [s for s in cur_pairs]
    det = {}
    for sym in want:
        try:
            kl = await getter("/api/v3/klines", {"symbol": sym, "interval": "1d", "limit": 90})
        except Exception:
            continue
        r, days = _range14(kl)
        det[sym] = (r, days)
        await asyncio.sleep(0.12)
    cands = []
    for sym, r24, vol, price in pool[:POOL]:
        r, days = det.get(sym, (None, 0))
        if r is None or days < MIN_DAYS:
            continue
        cands.append({"sym": sym, "rng14": round(r, 2), "vol": round(vol), "price": price, "days": days, "min_notional": meta[sym]})
    cands.sort(key=lambda c: -c["rng14"])
    cands = cands[:15]
    med = statistics.median([c["rng14"] for c in cands]) if cands else 0.0
    cur, rep = [], []
    for sym in cur_pairs:
        r, days = det.get(sym, (None, 0))
        ps = pair_stats.get(sym, {"n": 0, "net": 0.0, "start": now_ms})
        cur.append({"sym": sym, "rng14": round(r, 2) if r is not None else None, "n": ps["n"], "net": round(ps["net"], 2)})
        why = []
        if r is not None and med and r < 0.6 * med:
            why.append("размах дня %.1f%% против ≈%.1f%% у лучших кандидатов" % (r, med))
        run_days = (now_ms - ps["start"]) / 86400000.0
        if run_days >= 7 and ps["n"] == 0:
            why.append("нет ни одной сделки за %d дн." % int(run_days))
        if ps["n"] >= 10 and ps["net"] < 0:
            why.append("сделок %d, итог %.2f%%" % (ps["n"], ps["net"]))
        if why:
            rep.append({"sym": sym, "rng14": round(r, 2) if r is not None else None, "n": ps["n"], "net": round(ps["net"], 2), "why": why})
    return {"cands": cands, "replace": rep, "cur": cur, "median": round(med, 2), "min_vol": MIN_VOL, "min_days": MIN_DAYS, "checked": len(det)}
