"""classic_panel.py — панель «классического» бота (localhost:18093).
Шаг 1: графики + то, что бот «видит» (тренд по ТФ, pivot, уровни, индикаторы, свечные паттерны). Торговли пока нет."""
import asyncio, datetime, json, os, re, time
import aiohttp
from aiohttp import web
import pandas as pd
import classic_analysis as an
import classic_trendline as tl
import classic_fastchan as fc
import classic_hand as hd
import classic_strategy as cs
import classic_acct as ac
import classic_prop as pr
import classic_screen as scr
from classic_pos_html import HTML as POS_HTML

PORT = 18093
PORT2 = 8091  # панель позиций: на ноутбуке/телефоне проброс 18091 -> 8091
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
TTL = {"1m": 5, "3m": 8, "5m": 10, "15m": 15, "30m": 20, "1h": 30, "2h": 40, "4h": 60, "6h": 80, "8h": 90, "12h": 100, "1d": 120}
ALLTF = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]
MTF = ["1d", "4h", "1h", "15m", "5m"]
HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS_FILE = os.path.join(HERE, "pairs.json")
CAND_FILE = os.path.join(HERE, "cand.json")  # фильтр счёта «Кандидат» (по умолчанию pr.CAND_DEFAULT)
PROP_FILE = os.path.join(HERE, "proposals.json")  # решения «Открыть/Отклонить» по предложениям бота
MAN_FILE = os.path.join(HERE, "manual.json")  # ручное управление открытыми позициями: закрытие, стоп, трейлинг (ключ run|t_in|сторона)
DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "ZECUSDT"]
CACHE, LOCKS = {}, {}
SES = None
CAP_PAIRS = 30  # ориентир по нагрузке на расчёт (2 ядра); биржевой лимит намного выше
TFS_RUN = ["5m", "15m", "1h", "4h", "1d"]
VP_TFS_ALL = ["5m", "15m", "30m", "1h", "4h"]  # таймфреймы, доступные счёту «Профиль» (настройки ZigZag по умолчанию в classic_vp.ZZ_DEF есть до 1h; у 4h — общие 12/1.0/3 или заданные в настройках)
VP_TFS_DEF = ["5m", "15m"]
VP_CAP_PAIRS = 30  # максимум пар в Профиле (совпадает с общим ориентиром CAP_PAIRS: пара из других вкладок тоже считается один раз)
VP_CAP_RUNS = 120  # максимум прогонов Профиля = пары x таймфреймы (замер: прогон Профиля считается ~0.15 с)
VP_TFS_FILE = os.path.join(HERE, "vp_tfs.json")  # выбранные таймфреймы Профиля (если активных прогонов нет)
_BAN = {}  # base -> до какого момента Binance просит паузу (ответ 418/429)
_USED = {"w": 0, "ts": 0.0}  # израсходованный вес за минуту (лимит спота — 6000 на IP)


async def b_get(base, path, params):
    """Единая точка запросов к Binance: учитывает израсходованный вес и просьбу биржи о паузе."""
    now = time.time()
    if now < _BAN.get(base, 0):
        raise RuntimeError("%s: Binance просит паузу ещё %d с" % (base, _BAN[base] - now))
    if base == BASES[0] and _USED["w"] >= 3000 and now - _USED["ts"] < 60:
        await asyncio.sleep(2)  # половина лимита израсходована — притормаживаем
    async with SES.get(base + path, params=params) as r:
        w = r.headers.get("x-mbx-used-weight-1m")
        if w and base == BASES[0]:
            _USED["w"], _USED["ts"] = int(w), time.time()
        if r.status in (418, 429):
            ra = int(r.headers.get("Retry-After") or 60)
            _BAN[base] = time.time() + ra
            raise RuntimeError("%s %s: лимит Binance, пауза %d с" % (base, r.status, ra))
        if r.status != 200:
            raise RuntimeError("%s %s %s" % (base, r.status, (await r.text())[:120]))
        return await r.json()


def load_pairs():
    try:
        with open(PAIRS_FILE) as f:
            p = json.load(f)
            if isinstance(p, list) and p:
                return p
    except Exception:
        pass
    return list(DEFAULT_PAIRS)


def save_pairs(p):
    with open(PAIRS_FILE, "w") as f:
        json.dump(p, f)


async def get_df(sym, tf):
    key = (sym, tf)
    lock = LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        c = CACHE.get(key)
        if c and time.time() - c[0] < TTL.get(tf, 30):
            return c[1]
        data, err = None, None
        for base in BASES:
            try:
                data = await b_get(base, "/api/v3/klines", {"symbol": sym, "interval": tf, "limit": 1000})
                break
            except Exception as e:
                err = e
        if data is None:
            if c:
                return c[1]
            raise RuntimeError(str(err))
        df = pd.DataFrame(data).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
        df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
        for col in "ohlcv":
            df[col] = df[col].astype(float)
        df["t"] = df["t"].astype("int64")
        df["ct"] = df["ct"].astype("int64")
        CACHE[key] = (time.time(), df)
        return df


TFMS = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000,
        "6h": 21600000, "8h": 28800000, "12h": 43200000, "1d": 86400000}
DEEP = {}


async def fetch_back(sym, tf, need_ms, max_pages=120):
    """Свечи назад от текущего момента, пока самая ранняя не станет <= need_ms (или не кончится история монеты)."""
    parts, end, err, listing = [], None, None, False
    for _ in range(max_pages):
        data = None
        for base in BASES:
            try:
                prm = {"symbol": sym, "interval": tf, "limit": 1000}
                if end is not None:
                    prm["endTime"] = end
                data = await b_get(base, "/api/v3/klines", prm)
                break
            except Exception as e:
                err = e
        if not data:
            break
        parts.insert(0, data)
        end = int(data[0][0]) - 1
        if len(data) < 1000:
            listing = True
            break
        if int(data[0][0]) <= need_ms:
            break
    if not parts:
        raise RuntimeError(str(err))
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for col in "ohlcv":
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").reset_index(drop=True), listing


async def get_df_range(sym, tf, start_ms):
    """История с запасом на прогрев (260 свечей до start_ms): глубокая часть кэшируется на час, свежие свечи подмешиваются."""
    need = start_ms - 260 * TFMS[tf]
    key = (sym, tf)
    lock = LOCKS.setdefault(("deep",) + key, asyncio.Lock())
    async with lock:
        d = DEEP.get(key)
        if not (d and time.time() - d[0] < 3600 and (int(d[1].t.iloc[0]) <= need or d[2])):
            df0, listing = await fetch_back(sym, tf, need)
            d = (time.time(), df0, listing)
            DEEP[key] = d
    recent = await get_df(sym, tf)
    return pd.concat([d[1], recent]).drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)


def period_ms(cfg, now):
    """Период выборки из конфига (даты по UTC): (начало_мс, конец_мс) или None, если не задан."""
    pf, pt = cfg.get("period_from") or "", cfg.get("period_to") or ""
    if not pf and not pt:
        return None

    def day(s, end):
        d = datetime.date.fromisoformat(s)
        ms = int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        return ms + 86400000 - 1 if end else ms
    end_ms = min(day(pt, True), now) if pt else now
    start_ms = day(pf, False) if pf else end_ms - int(cfg["window_h"]) * 3600 * 1000
    return (start_ms, end_ms) if end_ms > start_ms else None


async def get_df_long(sym, tf, pages=2):
    """до pages*1000 свечей (для стратегии нужен прогрев EMA200 + 10 суток)."""
    key = (sym, tf, "long")
    lock = LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        c = CACHE.get(key)
        if c and time.time() - c[0] < TTL.get(tf, 30):
            return c[1]
        parts, end, err = [], None, None
        for _ in range(pages):
            data = None
            for base in BASES:
                try:
                    prm = {"symbol": sym, "interval": tf, "limit": 1000}
                    if end is not None:
                        prm["endTime"] = end
                    data = await b_get(base, "/api/v3/klines", prm)
                    break
                except Exception as e:
                    err = e
            if not data:
                break
            parts.insert(0, data)
            end = int(data[0][0]) - 1
            if len(data) < 1000:
                break
        if not parts:
            if c:
                return c[1]
            raise RuntimeError(str(err))
        df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
        df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
        for col in "ohlcv":
            df[col] = df[col].astype(float)
        df["t"] = df["t"].astype("int64")
        df["ct"] = df["ct"].astype("int64")
        df = df.drop_duplicates("t").reset_index(drop=True)
        CACHE[key] = (time.time(), df)
        return df


def split_closed(df):
    now = time.time() * 1000
    if len(df) and df.ct.iloc[-1] > now:
        return df.iloc[:-1].reset_index(drop=True), df.iloc[-1]
    return df.reset_index(drop=True), None


def ok_sym(s):
    return bool(s) and re.fullmatch(r"[A-Z0-9]{5,15}", s) is not None


def fast_chart(closed, atr, shift, keep=6):
    """Быстрый канал (classic_fastchan) для графика: последние каналы с линиями в индексах окна; end — свеча пробоя телом (None — канал действует)."""
    o, h, l, c = closed.o.values, closed.h.values, closed.l.values, closed.c.values
    items, cur = [], None
    for i, st, ev in fc.walk(o, h, l, c, atr):
        if st is not None and (cur is None or st["born"] != cur["born"]):
            if cur is not None and cur["end"] is None:
                cur["end"] = int(i)  # заменён новым каналом (перерисовка на новом пивоте)
            cur = {"born": int(st["born"]), "mode": st["mode"], "kind": st["kind"], "lo": st["lower"], "up": st["upper"], "end": None}
            items.append(cur)
        if ev and cur is not None and cur["end"] is None:
            cur["end"] = int(ev["i"])
    ln = lambda x: {"i1": int(x[0]) - shift, "p1": float(x[1]), "i2": int(x[2]) - shift, "p2": float(x[3]), "s": float(x[4])}
    return {"items": [{"born": it["born"] - shift, "end": None if it["end"] is None else it["end"] - shift, "mode": it["mode"], "kind": it["kind"], "lo": ln(it["lo"]), "up": ln(it["up"])} for it in items[-keep:]]}


async def api_chart(req):
    sym, tf = req.query.get("sym", "BTCUSDT").upper(), req.query.get("tf", "15m")
    if not ok_sym(sym) or tf not in ALLTF:
        return web.json_response({"error": "bad params"}, status=400)
    try:
        df = await get_df(sym, tf)
        closed, live = split_closed(df)
        res = an.analyze(closed, keep=1000)
        try:  # линии тренда для графика (индексы в окне последних 500 свечей, как у остальных рядов)
            ind_ = an.indicators(closed)
            res["tl"] = tl.chart_info(closed.o.values, closed.h.values, closed.l.values, closed.c.values, ind_["atr"].values,
                                      None, len(closed), shift=max(0, len(closed) - 1000))
        except Exception as e_:
            res["tl"] = {"lines": {}, "struct": None, "label": "ошибка линий: " + str(e_)[:80], "sigs": []}
        try:
            res["fc"] = fast_chart(closed, an.indicators(closed)["atr"].values, max(0, len(closed) - 1000))
        except Exception as e_:
            res["fc"] = {"items": [], "err": str(e_)[:80]}
        res["live"] = None if live is None else {k: float(live[k]) for k in "ohlcv"} | {"t": int(live.t)}
        res["sym"], res["tf"] = sym, tf
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"error": str(e)[:300]}, status=502)


async def api_mtf(req):
    sym = req.query.get("sym", "BTCUSDT").upper()
    if not ok_sym(sym):
        return web.json_response({"error": "bad params"}, status=400)
    async def one(tf):
        try:
            closed, _ = split_closed(await get_df(sym, tf))
            return dict(an.summary(closed), tf=tf)
        except Exception as e:
            return {"tf": tf, "error": str(e)[:100]}
    rows = await asyncio.gather(*[one(tf) for tf in MTF])
    return web.json_response({"sym": sym, "rows": rows})


async def api_pairs(req):
    p = load_pairs()
    if req.method == "POST":
        j = await req.json()
        if j.get("add"):
            s = str(j["add"]).upper().strip().replace("/", "")
            if not s.endswith("USDT") and not s.endswith("USDC") and not s.endswith("BTC"):
                s += "USDT"
            if not ok_sym(s):
                return web.json_response({"error": "плохое имя пары"}, status=400)
            try:
                await get_df(s, "1h")
            except Exception as e:
                return web.json_response({"error": "пара не найдена на Binance: " + str(e)[:100]}, status=400)
            if s not in p:
                p.append(s)
        if j.get("del") and j["del"] in p and len(p) > 1:
            p.remove(j["del"])
        save_pairs(p)
    return web.json_response({"pairs": p})


VTFS = {"5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000, "6h": 21600000, "12h": 43200000, "1d": 86400000}


async def api_trades(req):
    sym = req.query.get("sym", "").upper() or load_pairs()[0]
    if not ok_sym(sym):
        return web.json_response({"error": "bad params"}, status=400)
    cfg = load_cfg()
    P = dict(cs.PARAMS, **cfg, sym=sym)
    now = int(time.time() * 1000)
    cutoff = now - cfg["window_h"] * 3600 * 1000
    per = period_ms(cfg, now)
    try:
        df = await (get_df_range(sym, cfg["tf"], per[0]) if per else get_df_long(sym, cfg["tf"]))
    except Exception as e:
        return web.json_response({"error": "нет данных: " + str(e)[:150]}, status=502)
    out, period = [], None
    if per:
        start_ms, end_ms = per
        data_from = int(df.t.iloc[0])
        df = df[df.t <= end_ms].reset_index(drop=True)
        trs = cs.simulate(df, min(end_ms, now), dict(P, sim_from_ms=start_ms))
        for x in trs:
            if x["open"] and end_ms < now:
                x["open"], x["reason"] = False, "конец периода"
        out = [cs.pack([x])[0] for x in trs]
        period = {"from_ms": start_ms, "to_ms": end_ms, "data_from_ms": data_from}
    else:
        for x in cs.simulate(df, now, P):
            if x["open"] or x["t_in"] >= cutoff or x["t_out"] >= cutoff:
                out.append(cs.pack([x])[0])
    money = apply_stakes(out, P)
    vtf = req.query.get("vtf", "")
    dfc = df  # свечи для рисования; по умолчанию — ТФ правил, кнопки графика могут показать любой другой ТФ (сделки остаются от ТФ правил)
    if vtf and vtf != cfg["tf"] and vtf in VTFS:
        try:
            if per:
                dfv = await get_df_range(sym, vtf, max(per[0], per[1] - 1100 * VTFS[vtf]))
                dfv = dfv[dfv.t <= per[1]].reset_index(drop=True)
            else:
                dfv = await get_df_long(sym, vtf)
            if len(dfv) > 50:
                dfc = dfv
            else:
                vtf = ""
        except Exception:
            vtf = ""
    else:
        vtf = ""
    closed, live = split_closed(dfc)
    ind = an.indicators(closed)
    k = max(48, min(960, int(req.query.get("bars", 960))))

    def sl(v):
        return [None if z is None else an._r(float(z)) for z in v]
    chart = {"t": [int(z) for z in dfc.t.values[-k:]], "tf": vtf or cfg["tf"]}
    for c_ in "ohlc":
        chart[c_] = sl(dfc[c_].values[-k:])
    e20, e200 = list(ind["ema20"].values), list(ind["ema200"].values)
    if live is not None:
        e20.append(None); e200.append(None)
    chart["ema20"], chart["ema200"] = sl(e20[-k:]), sl(e200[-k:])
    return web.json_response({"sym": sym, "cfg": cfg, "notional": P["notional"], "trades": out, "chart": chart, "now": now, "period": period, "money": money})


async def pos_index(req):
    return web.Response(text=POS_HTML, content_type="text/html")


CONFIG_FILE = os.path.join(HERE, "config.json")
RUNS_FILE = os.path.join(HERE, "runs.json")
SPEC = {
    "tf": ("sel", ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]),
    "entry_mode": ("sel", ["stages", "pattern20", "cross200", "close20", "state20"]),
    "arm_k": ("num", 1, 200),
    "pat_filter": ("sel", ["none", "level", "volume", "extreme", "stretch", "level+volume", "extreme+volume", "sweep", "sweep16", "sweep+volume"]),
    "entry_trigger": ("sel", ["open", "breakout"]), "tp_r": ("num", 0, 20), "max_bars": ("num", 0, 2000),
    "rev_exit": ("bool",),
    "stop_mode": ("sel", ["prev", "pct", "pivot", "sig3", "channel"]),
    "tp_mode": ("sel", ["r", "channel"]), "be_intrabar": ("bool",), "be_tp_frac": ("num", 0, 1), "be_l_at": ("num", 0, 1), "k_tp_src": ("sel", ["width", "tri_base", "level"]), "be_l_lock": ("num", 0, 1), "tl_src": ("sel", ["old", "fast"]), "fc_minw": ("num", 0.3, 10), "fc_maxw": ("num", 1, 40), "tl_min_w": ("num", 0.5, 10), "tl_max_w": ("num", 2, 40), "ch_stop_pct": ("num", 0, 10), "ch_stop_atr": ("num", 0, 10), "ch_min_stop_pct": ("num", 0, 15),
    "ch_tp_gap_pct": ("num", 0, 10), "ch_tp_gap_atr": ("num", 0, 10), "ch_min_rr": ("num", 0, 20), "ch_follow": ("bool",),
    "min_stop_pct": ("num", 0.05, 15), "min_stop_atr": ("num", 0, 10),
    "be_trigger": ("num", 0.1, 30), "be_lock": ("num", 0, 10),
    "trail_mode": ("sel", ["none", "pct", "atr", "pivot"]), "trail_dist": ("num", 0, 20),
    "pat_mode": ("sel", ["off", "trail", "exit"]), "pat_min": ("num", 0, 50),
    "fee": ("num", 0, 0.5), "window_h": ("num", 6, 2000),
    "period_from": ("date",), "period_to": ("date",), "hand_forward": ("bool",), "hand_tf_mode": ("sel", ["junior", "own", "any"]),
    "stake_mode": ("sel", ["fixed", "fixed_profit"]), "stake_base": ("num", 6, 1000000), "stake_min": ("num", 1, 1000),
    "martingale": ("sel", ["off", "double", "double_plus"]), "mart_pct": ("num", 0, 500), "mart_max": ("num", 0, 20),
}
DEFAULT_CFG = {k: cs.PANEL[k] for k in SPEC}
DEFAULT_CFG["stages"] = cs.PANEL["stages"]
STAGE_TYPES = ["", "pattern", "cross200", "cross20", "cross50", "tl_bounce", "tl_breakout", "tl_both", "hand_bounce", "hand_breakout", "hand_both", "close_ema20", "break_trigger", "ema20_slope", "rsi_level", "macd_turn", "volume", "strong_body", "break_swing", "pullback_ema20", "rsi_band", "ext_dist", "stoch_dir", "macd_sign", "ema50_slope", "ema50_trend", "ema50_pullback", "stochrsi_cross", "ema200_side"]


def clean_stages(v):
    if not isinstance(v, list) or len(v) > 5:
        raise ValueError("stages: список до 5 уровней")
    out = []
    for x in v:
        if not isinstance(x, dict):
            raise ValueError("stages: неверный уровень")
        t = x.get("t", "") or ""
        if t not in STAGE_TYPES:
            raise ValueError("stages: неизвестное условие")
        try:
            pp = float(x.get("p") or 0)
            w = int(float(x.get("w") or 12))
        except Exception:
            raise ValueError("stages: параметр и окно — числа")
        f = x.get("f", "none") or "none"
        if f not in cs.PAT_FILTERS:
            raise ValueError("stages: неизвестный фильтр паттерна")
        if not (0 <= pp <= 100) or not (1 <= w <= 200):
            raise ValueError("stages: параметр 0–100, окно 1–200 свечей")
        out.append({"t": t, "p": pp, "w": w, "f": f})
    ne = [x for x in out if x["t"]]
    if ne and ne[0]["t"] not in cs.TRIGGERS:
        raise ValueError("первый непустой уровень должен быть триггером: паттерн, пересечение EMA20×EMA200 или пересечение цены и EMA20")
    if any(x["t"] in cs.TRIGGERS for x in ne[1:]):
        raise ValueError("триггер может быть только первым непустым уровнем")
    return out


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def clean_cfg(inp, base=None):
    cfg = dict(base or DEFAULT_CFG)
    for k, sp in SPEC.items():
        if k not in inp:
            continue
        v = inp[k]
        if sp[0] == "sel":
            if v not in sp[1]:
                raise ValueError("%s: недопустимое значение" % k)
        elif sp[0] == "bool":
            v = bool(v)
        elif sp[0] == "date":
            v = str(v or "").strip()
            if v:
                try:
                    datetime.date.fromisoformat(v)
                except Exception:
                    raise ValueError("%s: дата в формате ГГГГ-ММ-ДД" % k)
        else:
            try:
                v = float(v)
            except Exception:
                raise ValueError("%s: нужно число" % k)
            if not (sp[1] <= v <= sp[2]):
                raise ValueError("%s: допустимо от %s до %s" % (k, sp[1], sp[2]))
            if k in ("window_h", "max_bars"):
                v = int(v)
        cfg[k] = v
    if "stages" in inp:
        cfg["stages"] = clean_stages(inp["stages"])
    if cfg["stake_base"] < cfg["stake_min"]:
        raise ValueError("базовая ставка меньше минимальной")
    if cfg.get("period_from") and cfg.get("period_to") and cfg["period_from"] > cfg["period_to"]:
        raise ValueError("период: дата «с» позже даты «по»")
    if cfg["be_lock"] >= cfg["be_trigger"]:
        raise ValueError("размер безубытка должен быть меньше точки перехода в безубыток")
    return cfg


def load_cfg():
    try:
        return clean_cfg(jload(CONFIG_FILE, {}))
    except Exception:
        return dict(DEFAULT_CFG)


async def api_config(req):
    try:
        if req.method == "POST":
            j = await req.json()
            if j.get("reset"):
                cfg = dict(DEFAULT_CFG)
            else:
                cfg = clean_cfg(j.get("config") or {}, base=load_cfg())
            jsave(CONFIG_FILE, cfg)
        return web.json_response({"config": load_cfg(), "default": DEFAULT_CFG})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_cand(req):
    """Фильтр счёта «Кандидат»: GET — текущие значения, POST {filter:{...}} или {reset:true}. Каждое изменение параметров добавляет версию в history."""
    try:
        raw = jload(CAND_FILE, {}) or {}
        cur = {k: raw.get(k, v) for k, v in pr.CAND_DEFAULT.items()}
        if req.method == "POST":
            j = await req.json()
            new = dict(cur)
            if j.get("reset"):
                new = dict(pr.CAND_DEFAULT)
            else:
                f = j.get("filter") or {}
                for k in ("min_stop_atr", "max_stop_atr", "max_tp_atr", "min_rr"):
                    if k in f:
                        v = float(f[k])
                        if not (0.0 <= v <= 50.0):
                            raise ValueError("%s: нужно число от 0 до 50 (0 — условие выключено)" % k)
                        new[k] = round(v, 2)
                if "sides" in f:
                    if f["sides"] not in ("LS", "L", "S"):
                        raise ValueError("sides: LS, L или S")
                    new["sides"] = f["sides"]
            if new != cur:  # параметры изменились — закрываем текущую версию и открываем новую; без изменений ничего не пишем
                now_ms = int(time.time() * 1000)
                hist = list(raw.get("history") or [{"since": int(raw.get("since") or now_ms), "until": None, "f": dict(cur)}])
                hist[-1]["until"] = now_ms
                hist.append({"since": now_ms, "until": None, "f": dict(new)})
                jsave(CAND_FILE, dict(new, since=now_ms, history=hist))
                cur = new
        return web.json_response({"filter": cur, "default": pr.CAND_DEFAULT})
    except (ValueError, TypeError) as e:
        return web.json_response({"error": str(e)}, status=400)


def apply_stakes(trs, cfg):
    """Размер ставки и профит в USDT по сделкам (в порядке входа). Ставка: фиксированная (stake_base) или фиксированная + накопленный
    положительный профит; минимум stake_min. Мартингейл после убыточной сделки (net <= 0): double — вдвое больше предыдущей ставки;
    double_plus — вдвое + mart_pct% от долларового убытка предыдущей сделки; после прибыльной — возврат к обычной ставке;
    mart_max > 0 — после стольких увеличений подряд ставка больше не растёт. pnl$ = ставка × net% / 100."""
    base, smin = float(cfg.get("stake_base", 100.0)), float(cfg.get("stake_min", 6.0))
    mode, mart = cfg.get("stake_mode", "fixed"), cfg.get("martingale", "off")
    pct, mmax = float(cfg.get("mart_pct", 50.0)) / 100.0, int(cfg.get("mart_max", 0) or 0)
    prof = peak = max_dd = max_stake = tot = 0.0
    prev_stake, prev_loss, streak = None, 0.0, 0
    for x in sorted(trs, key=lambda t: t["t_in"]):
        s0 = base + (max(prof, 0.0) if mode == "fixed_profit" else 0.0)
        if mart != "off" and streak > 0 and prev_stake:
            if mmax and streak > mmax:
                s = prev_stake
            else:
                s = 2 * prev_stake + (pct * prev_loss if mart == "double_plus" else 0.0)
        else:
            s = s0
        s = max(s, smin)
        usd = s * x["net"] / 100.0
        x["stake"], x["usd"] = round(s, 2), round(usd, 2)
        tot += s
        max_stake = max(max_stake, s)
        if not x["open"]:
            prof += usd
            peak = max(peak, prof)
            max_dd = max(max_dd, peak - prof)
        if x["net"] <= 0:
            streak += 1
            prev_loss = -usd
        else:
            streak, prev_loss = 0, 0.0
        prev_stake = s
    open_usd = sum(x["usd"] for x in trs if x["open"])
    return {"profit": round(prof + open_usd, 2), "max_stake": round(max_stake, 2), "max_dd": round(max_dd, 2),
            "avg_stake": round(tot / len(trs), 2) if trs else 0.0}


def run_stats(tr):
    n = len(tr)
    return {"n": n, "open": sum(1 for x in tr if x["open"]), "net": round(sum(x["net"] for x in tr), 3),
            "gross": round(sum(x["gross"] for x in tr), 3), "win": sum(1 for x in tr if x["net"] > 0)}


_RT = {}  # кэш расчёта живых прогонов: {id: (ключ, время расчёта, сделки)}
RT_FILE = os.path.join(HERE, "rt_cache.json")
_RT_DIRTY = [False]


def _rt_load():
    """Кэш расчётов переживает перезапуск: без него каждый старт — минуты пересчёта всех прогонов."""
    try:
        with open(RT_FILE) as f:
            for k, v in json.load(f).items():
                _RT[int(k)] = (tuple(v[0]), v[1], v[2])
    except Exception:
        pass


def _rt_save(alive):
    for k in [k for k in _RT if k not in alive]:
        del _RT[k]
    tmp = RT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({str(k): [list(v[0]), v[1], v[2]] for k, v in _RT.items()}, f, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    os.replace(tmp, RT_FILE)
    _RT_DIRTY[0] = False


def _hand_mtime():
    try:
        return os.path.getmtime(hd.HAND_FILE)
    except OSError:
        return 0


def mkey(run, t_in, side):
    return "%s|%s|%s" % (run, int(t_in), side)


_MAN_C = {"mt": None, "d": {}}


def man_states():
    """Ручное управление позициями (manual.json); перечитывается только при изменении файла."""
    try:
        mt = os.path.getmtime(MAN_FILE)
    except OSError:
        return {}
    if _MAN_C["mt"] != mt:
        _MAN_C["d"], _MAN_C["mt"] = jload(MAN_FILE, {}), mt
    return _MAN_C["d"]


async def ticker_prices(syms):
    """Свежие цены монет (спот Binance одним запросом)."""
    syms = sorted(set(syms))
    if not syms:
        return {}
    err = None
    for base in BASES:
        try:
            data = await b_get(base, "/api/v3/ticker/price", {"symbols": json.dumps(syms, separators=(",", ":"))})
            return {d["symbol"]: float(d["price"]) for d in data}
        except Exception as e:
            err = e
    raise RuntimeError(str(err))


async def manual_tick():
    """Ручной стоп/трейлинг: раз в несколько секунд сверяем цену с уровнем; при пересечении позиция закрывается по текущей цене (close в manual.json),
    дальше сделку закрывает расчёт прогона (ручное закрытие) или слой «Вместе». Трейлинг тянет уровень за лучшей ценой после установки (только в сторону цены)."""
    act = {k: v for k, v in jload(MAN_FILE, {}).items() if v.get("mode") and not v.get("close") and not v.get("done")}
    p = _SNAP["payload"]
    if not act or not p:
        return
    try:
        px = await ticker_prices([v["sym"] for v in act.values()])
    except Exception:
        return
    opn = {}
    for r in p["runs"]:
        if r["stop_ms"] is None:
            for x in r["trades"]:
                if x["open"]:
                    opn[mkey(r["id"], x["t_in"], x["side"])] = True
    ms, now, ch = jload(MAN_FILE, {}), int(time.time() * 1000), False  # перечитываем: за время запроса цен кнопка могла что-то изменить
    for k, v in ms.items():
        if not v.get("mode") or v.get("close") or v.get("done"):
            continue
        if k not in opn:
            if _SNAP["ts"] * 1000 > v.get("set_ms", 0):  # снимок свежее установки: позиция закрылась сама (стоп/цель/разворот)
                v["done"], ch = True, True
            continue
        cur = px.get(v["sym"])
        if cur is None:
            continue
        L = v["side"] == "L"
        if v["mode"] == "trail":
            v["mext"] = max(v["mext"], cur) if L else min(v["mext"], cur)
            q = v["mext"] * (1 - v["pct"] / 100.0) if L else v["mext"] * (1 + v["pct"] / 100.0)
            if (L and q > v["lvl"]) or ((not L) and q < v["lvl"]):
                v["lvl"] = q
            ch = True
        if (L and cur <= v["lvl"]) or ((not L) and cur >= v["lvl"]):
            v["close"], ch = {"ms": now, "px": cur, "reason": "ручной трейлинг" if v["mode"] == "trail" else "ручной стоп"}, True
            _RT.pop(v["run"], None)
    if ch:
        jsave(MAN_FILE, ms)


async def manual_loop():
    while True:
        try:
            await manual_tick()
        except Exception as e:
            import traceback; print("manual_tick error: %r" % (e,)); traceback.print_exc()
        await asyncio.sleep(5)


WARM_BARS = 1300  # свечей истории до старта прогона: прогрев EMA200/ATR + окно vp_hist_bars=1000 профиля объёма


async def run_trades(run, now):
    """Сделки прогона. Расчёт тяжёлый (50 прогонов), поэтому: считаем в отдельном потоке, а результат кэшируем по ключу
    (рисунки, начало прогона, время последней свечи) — без открытой позиции он не меняется до новой свечи; с открытой обновляем раз в 40 с."""
    hm = _hand_mtime()
    df = await get_df_long(run["sym"], run["cfg"]["tf"])
    # Стабильность расчёта: get_df_long отдаёт только последние ~2000 свечей, на 5m это ~7 суток. Если окно начинается позже старта прогона
    # (или меньше чем за WARM_BARS свечей до него), симуляция стартует с «холодными» индикаторами и ZigZag, а окно сдвигается каждую свечу —
    # сделки (и баланс счёта) меняются от обновления к обновлению. Поэтому докачиваем историю так, чтобы до старта было WARM_BARS свечей.
    tfms_ = TFMS.get(run["cfg"]["tf"])
    if tfms_ and len(df) and int(df["t"].iloc[0]) > run["start_ms"] - WARM_BARS * tfms_:
        try:
            df = await get_df_range(run["sym"], run["cfg"]["tf"], run["start_ms"] - (WARM_BARS - 260) * tfms_)  # get_df_range сама отступает ещё на 260 свечей
        except Exception as e:
            print("run_trades: history extend failed %s %s: %r" % (run["sym"], run["cfg"]["tf"], e))
    key = (hm, run["start_ms"], int(df["t"].iloc[-1]) if len(df) else 0)
    mcl = {}  # ручные закрытия позиций этого прогона (у прогонов «только предлагает» они действуют на позицию пользователя, а не на сделку бота)
    if (run.get("mode") or "auto") != "propose":
        for v in man_states().values():
            if v.get("run") == run["id"] and v.get("close"):
                c_ = v["close"]
                mcl["%d|%s" % (v["t_in"], v["side"])] = (int(c_["ms"]), float(c_["px"]), c_["reason"])
        if mcl:
            key = key + (",".join("%s@%d" % (k_, mcl[k_][0]) for k_ in sorted(mcl)),)
    c = _RT.get(run["id"])
    if c and c[0] == key and (time.time() - c[1] < 40 or not any(x["open"] for x in c[2])):
        return [dict(x) for x in c[2]]
    P = dict(cs.PARAMS, **dict(run["cfg"], sym=run["sym"]))  # sym может уже лежать в cfg (прогоны, созданные скриптом) — раньше это давало TypeError и пустой список сделок
    P["sim_from_ms"] = run["start_ms"]
    P["manual_close"] = mcl
    res = await asyncio.to_thread(cs.simulate, df, now, P)
    _RT[run["id"]] = (key, time.time(), [dict(x) for x in res])
    _RT_DIRTY[0] = True
    return res


BOOK_FILE = os.path.join(HERE, "book.db")  # запись стакана (classic_book.py)


def book_walls(sym, ts_ms=None):
    """Стенки стакана для графика позиции: последний снимок (ts_ms=None, позиция открыта) или снимок на момент входа (ближайший, не дальше 3 мин). -> (список стенок, время снимка) или ([], None)."""
    try:
        import sqlite3
        c = sqlite3.connect("file:%s?mode=ro" % BOOK_FILE, uri=True, timeout=5)
        try:
            if ts_ms is None:
                r = c.execute("SELECT ts, walls FROM snap WHERE sym=? ORDER BY ts DESC LIMIT 1", (sym,)).fetchone()
            else:
                r = c.execute("SELECT ts, walls FROM snap WHERE sym=? AND ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 1", (sym, ts_ms - 180000, ts_ms + 180000, ts_ms)).fetchone()
        finally:
            c.close()
        return (json.loads(r[1]), int(r[0])) if r else ([], None)
    except Exception:
        return [], None


VP_NUM = {"vp_rows": (10, 200), "vp_va": (30, 95), "zz_depth": (0, 200), "zz_dev": (0, 20), "zz_back": (0, 50), "vp_flat_delta": (0.01, 2), "vp_par": (0.05, 2), "vp_hvn": (1.0, 10),
          "vp_lvn": (0.05, 1.0), "vp_tol_atr": (0.05, 2), "vp_buf_atr": (0, 2), "vp_hist_bars": (100, 3000), "vp_ahead_atr": (0.3, 6), "vp_imp_atr": (0, 5), "vp_retest_bars": (1, 60),
          "vp_ret_bars": (1, 60), "vp_sl_atr": (0.1, 5), "vp_rr": (0.5, 10), "vp_min_rr": (0, 10), "vp_be_frac": (0.1, 1)}
VP_SEL = {"vp_mode": ("auto", "flat", "trend"), "vp_bo_entry": ("close", "retest"), "vp_neutral": ("skip", "true")}
VP_BOOL = ("vp_be_poc", "vp_bounce", "vp_breakout", "vp_return")


def vp_clean(upd):
    """Проверка настроек профиля объёма из интерфейса -> словарь для cfg прогонов."""
    out = {}
    for k, (a, b) in VP_NUM.items():
        if upd.get(k) is None: continue
        try: x = float(upd[k])
        except (TypeError, ValueError): raise ValueError("%s: нужно число" % k)
        if not a <= x <= b: raise ValueError("%s: допустимо от %s до %s" % (k, a, b))
        out[k] = int(x) if k in ("vp_rows", "zz_depth", "zz_back", "vp_hist_bars", "vp_retest_bars", "vp_ret_bars") else x
    for k, ch in VP_SEL.items():
        if k in upd:
            if upd[k] not in ch: raise ValueError("%s: допустимо %s" % (k, ", ".join(ch)))
            out[k] = upd[k]
    for k in VP_BOOL:
        if k in upd: out[k] = bool(upd[k])
    if "vp_start" in upd:
        s = str(upd["vp_start"] or "auto").strip()
        if s != "auto" and not re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$", s): raise ValueError("vp_start: «auto» или ГГГГ-ММ-ДД ЧЧ:ММ (UTC)")
        out["vp_start"] = s
    return out


def exp_summary(out):
    """Сводка экспериментальных прогонов (cfg.exp = 'A'/'B') против обычных прогонов бота той же пары и ТФ; только сделки после exp_since (проверка вперёд)."""
    def key(t): return (t["t_in"], t["side"])
    def st(L):
        C = [t for t in L if not t["open"]]
        n = len(C)
        return {"n": n, "w": sum(1 for t in C if t["net"] > 0), "open": len(L) - n,
                "avg": round(sum(t["net"] for t in C) / n, 3) if n else 0.0, "sum": round(sum(t["net"] for t in C), 2)}
    bot = {(r["sym"], r["cfg"]["tf"]): r for r in out if r["track"] == "bot" and r.get("mode") == "propose"}
    res = {}
    for tag in ("A", "B", "C", "D"):
        ea, ba, extra, per, diffs, lad, since, nr = [], [], [], {}, [], 0, None, 0
        ch_e, ch_b = [], []
        for r in out:
            c = r["cfg"]
            if c.get("exp") != tag or r["stop_ms"] is not None: continue
            nr += 1
            s0 = int(c.get("exp_since") or r["start_ms"]); since = s0 if since is None else min(since, s0)
            b = bot.get((r["sym"], c["tf"]))
            et = [t for t in (r.get("trades") or []) if t["t_in"] >= s0]
            bt = [t for t in ((b or {}).get("trades") or []) if t["t_in"] >= s0]
            ea += et; ba += bt
            pe = per.setdefault(c["tf"], ([], [])); pe[0].extend(et); pe[1].extend(bt)
            bm = {key(t): t for t in bt}
            for t in et:
                o = bm.get(key(t))
                if tag == "B" and t["reason"] == "лесенка": lad += 1
                if o is None: extra.append(t)
                elif tag == "B" and not t["open"] and not o["open"]: diffs.append(t["net"] - o["net"])
                elif tag in ("C", "D") and not t["open"] and not o["open"] and abs((t.get("tp") or 0) - (o.get("tp") or 0)) > 1e-12:
                    ch_e.append(t); ch_b.append(o)  # сделки, где цель эксперимента отличается от обычной
        x = {"runs": nr, "since": since, "exp": st(ea), "base": st(ba), "per_tf": {tf: {"exp": st(a), "base": st(b)} for tf, (a, b) in sorted(per.items())}}
        if tag == "A":
            x["extra"] = st(extra)
            x["progress"] = x["extra"]["n"]
        elif tag in ("C", "D"):
            x["changed"] = st(ch_e); x["changed_base"] = st(ch_b); x["progress"] = len(ch_e)
        else:
            x["lad"] = lad; x["pairs"] = len(diffs); x["diff"] = round(sum(diffs), 2)
            x["better"] = sum(1 for d in diffs if d > 0.001); x["worse"] = sum(1 for d in diffs if d < -0.001)
            x["progress"] = x["better"] + x["worse"]  # только сделки, где лесенка реально изменила результат
        res[tag] = x
    return res


def track_of(cfg):
    """Сторона сравнения по первому уровню входа: рисунки пользователя — «me», авто-детектор — «bot», остальное — «other»."""
    if cfg.get("exp"):
        return "exp"  # экспериментальные прогоны (параллельные проверки идей): не входят ни в один счёт и не рисуются во вкладках, анализ — скриптом
    st = [x for x in (cfg.get("stages") or []) if x and x.get("t")]
    t = st[0]["t"] if st else ""
    return "me" if t.startswith("hand_") else "bot" if t.startswith("tl_") else "vp" if t == "vp" else "other"


_SNAP = {"payload": None, "ts": 0.0, "calc_s": None}


async def _stop_run(r, now):
    if r["stop_ms"] is None:
        tr = await run_trades(r, now)
        for x in tr:
            if x["open"]:
                x["open"] = False
                x["reason"] = "остановлен"
        r["trades"] = cs.pack(tr)
        r["stop_ms"] = now
def vp_active(runs):
    return [r for r in runs if r["stop_ms"] is None and track_of(r["cfg"]) == "vp"]


def vp_tfs_cur(runs):
    a = {r["cfg"]["tf"] for r in vp_active(runs)}
    if a:
        return [t for t in VP_TFS_ALL if t in a]
    s = jload(VP_TFS_FILE, None)
    s = [t for t in VP_TFS_ALL if isinstance(s, list) and t in s]
    return s or list(VP_TFS_DEF)


async def vp_make(runs, sym, tfs, now, tpl_cfg):
    """Новые прогоны Профиля по паре: те же настройки, что у действующих, старт с текущего момента."""
    for tf in tfs:
        await get_df_long(sym, tf)  # заодно проверка, что данные по паре и ТФ есть
    rid = max([r["id"] for r in runs] + [0])
    for tf in tfs:
        rid += 1
        own = [r for r in runs if track_of(r["cfg"]) == "vp" and r["cfg"]["tf"] == tf]  # настройки у каждого таймфрейма свои: берём у прогона того же ТФ
        if own:
            cfg = json.loads(json.dumps(max(own, key=lambda r: r["id"])["cfg"]))
        else:  # у ТФ ещё не было своих настроек: копия общих, но ZigZag «по таймфрейму» (0), чтобы не тащить настройки чужого ТФ
            cfg = json.loads(json.dumps(tpl_cfg))
            cfg["zz_depth"] = cfg["zz_dev"] = cfg["zz_back"] = 0
        cfg["tf"] = tf
        cfg["vp_since"] = now
        runs.append({"id": rid, "name": "Профиль %s %s" % (sym, tf), "sym": sym, "cfg": cfg, "start_ms": now, "stop_ms": None, "trades": None})


_LOCK = []


def _build_lock():
    if not _LOCK:
        _LOCK.append(asyncio.Lock())
    return _LOCK[0]


async def api_prop_chart(req):
    """Данные для графика предложения (вкладка «Вместе»): свечи ТФ прогона, канал/структура, вход, стоп, безубыток, цель."""
    try:
        rid, t_in, side = int(req.query["run"]), int(req.query["t_in"]), req.query["side"]
    except Exception:
        return web.json_response({"error": "bad params"}, status=400)
    run = next((r for r in jload(RUNS_FILE, []) if r["id"] == rid), None)
    if run is None:
        return web.json_response({"error": "прогон не найден"}, status=404)
    now = int(time.time() * 1000)
    tr = await run_trades(run, now)
    x = next((z for z in tr if int(z["t_in"]) == t_in and z["side"] == side), None)
    if x is None:
        return web.json_response({"error": "сделка не найдена"}, status=404)
    sym, tf = run["sym"], run["cfg"]["tf"]
    df = await get_df_long(sym, tf)
    closed, live = split_closed(df)
    ind = an.indicators(closed)
    k = 260
    def sl(v):
        return [None if z is None else an._r(float(z)) for z in v]
    chart = {"t": [int(z) for z in df.t.values[-k:]], "tf": tf}
    for c_ in "ohlc":
        chart[c_] = sl(df[c_].values[-k:])
    e20 = list(ind["ema20"].values)
    if live is not None:
        e20.append(None)
    chart["ema20"] = sl(e20[-k:])
    P = dict(cs.PARAMS, **dict(run["cfg"], sym=sym))
    s = 1 if side == "L" else -1
    pin = float(x["p_in"])
    thr = float(P.get("be_trigger") or 0)
    if P.get("be_atr"):
        try:
            hh, ll, cc = df.h.values.astype(float), df.l.values.astype(float), df.c.values.astype(float)
            i0 = int(x.get("i_in") or 0)
            tr_ = [max(hh[j] - ll[j], abs(hh[j] - cc[j - 1]), abs(ll[j] - cc[j - 1])) for j in range(max(1, i0 - 13), i0 + 1)]
            thr = float(P["be_atr"]) * (sum(tr_) / len(tr_)) / pin * 100.0
        except Exception:
            pass
    if x.get("be_thr") and not P.get("be_atr"):
        thr = float(x["be_thr"])  # точка БУ из самой сделки (учтена be_tp_frac)
    lines = {"entry": an._r(pin), "stop0": an._r(float(x["stop0"])), "stop": an._r(float(x["stop"])),
             "tp": an._r(float(x["tp"])) if x.get("tp") else None,
             "be_trigger": an._r(pin * (1 + s * thr / 100.0)) if thr else None,
             "be": an._r(pin * (1 + s * float(P.get("be_lock", 0.3)) / 100.0)), "be_hit": bool(x["be"])}
    struct = None
    sid = x.get("sid")
    if sid:
        st = next((z for z in hd.load() if z.get("id") == sid), None)
        if st:
            struct = {"id": sid, "kind": st.get("kind"), "tf": st.get("tf"), "A": st.get("A"), "B": st.get("B")}
    ch = None
    if x.get("chlw"):
        w = x["chlw"]  # [нижняя в начале, верхняя в начале, нижняя при входе, верхняя при входе, индекс начала]
        ch = {"lo": [an._r(w[0]), an._r(w[2])], "up": [an._r(w[1]), an._r(w[3])], "i0": int(w[4]), "i1": int(x["i_in"])}
    walls, walls_t = book_walls(sym, None if x["open"] else int(t_in))  # стенки: у открытой — текущие, у закрытой — на момент входа (если запись уже шла)
    return web.json_response({"sym": sym, "tf": tf, "side": side, "sig": x.get("sig"), "t_in": t_in, "open": bool(x["open"]), "reason": x["reason"],
                              "off": int(len(df) - len(chart["t"])), "chart": chart, "lines": lines, "ch": ch, "struct": struct, "walls": walls, "walls_t": walls_t, "vp": x.get("vpx")})


async def build_payload(runs, now):
    out = []
    by_track = {"me": [], "bot": [], "vp": []}
    prop_tr = []  # сделки прогонов бота в режиме «только предлагает» — это предложения для вкладки «Вместе»
    va_ = vp_active(runs)
    vp_since = min((r["start_ms"] for r in va_), default=0)  # счёт «Профиль» идёт с самого раннего старта активных прогонов
    vp_tf_on = {r["cfg"]["tf"] for r in va_}  # остановленные прогоны снятых таймфреймов в счёт не входят
    for r in runs:
        if r["stop_ms"] is None:
            try:
                tr = cs.pack(await run_trades(r, now))
            except Exception as e:
                import traceback; print("run %s error: %r" % (r.get("id"), e)); traceback.print_exc()  # не глотаем молча
                tr = []
        else:
            tr = r["trades"] or []
        st = run_stats(tr)
        st["money"] = apply_stakes(tr, dict(cs.PARAMS, **r["cfg"]))
        tk = track_of(r["cfg"])
        md = r.get("mode") or "auto"
        if tk == "bot" and md == "propose":
            prop_tr += [dict(x, sym=r["sym"], tf=r["cfg"]["tf"], run=r["id"]) for x in tr]
        elif tk == "vp":  # журнал и баланс Профиля: только сделки с даты начала счёта и только текущие таймфреймы (остановленные прогоны старых ТФ/дат раньше попадали в журнал)
            if r["stop_ms"] is None or r["cfg"]["tf"] in vp_tf_on:
                by_track[tk] += [dict(x, sym=r["sym"], tf=r["cfg"]["tf"], run=r["id"]) for x in tr if x["t_in"] >= vp_since]
        elif tk in by_track:
            by_track[tk] += [dict(x, sym=r["sym"], tf=r["cfg"]["tf"], run=r["id"]) for x in tr]
        out.append({"id": r["id"], "name": r["name"], "sym": r["sym"], "track": tk, "mode": md, "cfg": dict(cs.PARAMS, **r["cfg"]), "start_ms": r["start_ms"],
                    "stop_ms": r["stop_ms"], "stats": st, "trades": tr[-300:]})
    cand_raw = jload(CAND_FILE, {}) or {}
    if not cand_raw.get("history"):  # история версий фильтра: у каждой свой период, смена фильтра ничего не стирает
        since0 = int(cand_raw.get("since") or time.time() * 1000)
        cand_raw = {**pr.CAND_DEFAULT, **cand_raw, "since": since0}
        cand_raw["history"] = [{"since": since0, "until": None, "f": {k: cand_raw[k] for k in pr.CAND_DEFAULT}}]
        jsave(CAND_FILE, cand_raw)
    cand_f = dict(pr.CAND_DEFAULT, **{k: v for k, v in cand_raw.items() if k != "history"})
    pd_ = pr.build(prop_tr, jload(PROP_FILE, []), now, ac.MIN_NOTIONAL, man_states(), cand_f)
    accounts = {}
    for k, L in (("me", by_track["me"]), ("bot", by_track["bot"]), ("vp", by_track["vp"])):
        accounts[k] = {"account": ac.sim_account(L), "signals": ac.sim_signals(L, now),
                       "trades": [{"sym": x.get("sym"), "tf": x.get("tf"), "side": x["side"], "sig": x.get("sig"), "t_in": x["t_in"], "net": x["net"], "open": x["open"], "reason": x["reason"], "be": x["be"], "run": x.get("run")}
                                  for x in sorted(L, key=lambda t: -t["t_in"])[:60]]}
    accounts["both"] = {"account": ac.sim_account(pd_["accepted"]), "signals": ac.sim_signals(pd_["allsig"], now), "trades": []}  # «Вместе» = открытые вами предложения; «Все сигналы» = если брать каждое
    accounts["cand"] = {"account": ac.sim_account(pd_["candsig"]), "signals": ac.sim_signals(pd_["candsig"], now), "trades": [],  # «Кандидат» = сигналы бота, прошедшие фильтр; открываются сами, без вашего решения
                        "filter": dict(cand_f, passed=len(pd_["candsig"]), total=len(pd_["allsig"]))}
    def vstat(trs):
        st_ = ac.sim_signals(trs, now)
        cl_ = [x for x in trs if not x["open"]]
        return {"n": st_["n"], "wins": st_["wins"], "win_pct": st_["win_pct"], "open": st_["open"], "total": st_["total"],
                "avg_net": round(sum(x["net"] for x in cl_) / len(cl_), 3) if cl_ else None}
    versions = []
    for hh in reversed(cand_raw["history"]):  # новые сверху
        s0, u0 = int(hh["since"]), (int(hh["until"]) if hh.get("until") else None)
        sub = [x for x in pd_["allsig"] if x["t_in"] >= s0 and (u0 is None or x["t_in"] < u0)]
        sc = [x for x in sub if pr.cand_pass(x, hh["f"])[0]]
        versions.append({"since": s0, "until": u0, "f": hh["f"], "all": vstat(sub), "cand": vstat(sc)})
    accounts["cand"]["versions"] = versions
    accounts["exp"] = exp_summary(out)  # вкладка «Эксп.»: параллельные проверки идей (не счёт)
    bot_modes = {}
    for r in runs:
        if r["stop_ms"] is None and track_of(r["cfg"]) == "bot":
            bot_modes.setdefault(r["sym"], set()).add(r.get("mode") or "auto")
    pairs_all = sorted(set(load_pairs()) | {r["sym"] for r in runs if r["stop_ms"] is None})
    hand_meta = {str(x["id"]): {"kind": x.get("kind"), "tf": x.get("tf"), "created": x.get("created"), "deleted": x.get("deleted")} for x in hd.load()}
    act = [r for r in runs if r["stop_ms"] is None]
    load = {"pairs": len({r["sym"] for r in act}), "runs": len(act), "cap": CAP_PAIRS, "weight": _USED["w"] if time.time() - _USED["ts"] < 120 else 0,
            "limit": 6000, "ban": max(0, int(_BAN.get(BASES[0], 0) - time.time())), "calc_s": _SNAP.get("calc_s")}
    vpa = [r for r in act if track_of(r["cfg"]) == "vp"]
    load["vp"] = {"pairs": len({r["sym"] for r in vpa}), "runs": len(vpa), "cap_pairs": VP_CAP_PAIRS, "cap_runs": VP_CAP_RUNS, "tfs": vp_tfs_cur(runs), "tf_all": VP_TFS_ALL}
    return {"runs": out, "now": now, "notional": cs.PARAMS["notional"], "hand": hand_meta, "accounts": accounts, "load": load,
            "proposals": {"pending": pd_["pending"], "rows": pd_["rows"], "stats": pd_["stats"]}, "pairs_all": pairs_all,
            "manual": {k: {"mode": v["mode"], "pct": v.get("pct"), "lvl": v.get("lvl")} for k, v in man_states().items() if v.get("mode") and not v.get("close") and not v.get("done")},
            "bot_modes": {s: (next(iter(m)) if len(m) == 1 else "mixed") for s, m in bot_modes.items()}}


_SCREEN = {"data": None, "ts": 0.0, "busy": False, "err": None}


async def _screen_getter(path, params):
    last = None
    for base in BASES:
        try:
            return await b_get(base, path, params)
        except Exception as e:
            last = e
    raise RuntimeError(str(last))


def _pair_stats(track=None):
    st = {}
    p = _SNAP["payload"]
    for r in (p["runs"] if p else []):
        if r["stop_ms"] is None and (track is None or r.get("track") == track):
            s = st.setdefault(r["sym"], {"n": 0, "net": 0.0, "start": r["start_ms"]})
            s["n"] += r["stats"]["n"]
            s["net"] += r["stats"]["net"]
            s["start"] = min(s["start"], r["start_ms"])
    return st


async def screen_refresh():
    if _SCREEN["busy"]:
        return
    _SCREEN["busy"] = True
    try:
        rr = jload(RUNS_FILE, [])
        cur = sorted({r["sym"] for r in rr if r["stop_ms"] is None})
        vpp = sorted({r["sym"] for r in vp_active(rr)})
        d = await scr.build(_screen_getter, cur, _pair_stats(), int(time.time() * 1000), vpp, _pair_stats("vp"))
        d["ts"] = time.time()
        _SCREEN["data"], _SCREEN["err"] = d, None
    except Exception as e:
        import traceback; traceback.print_exc()
        _SCREEN["err"] = str(e)
    finally:
        _SCREEN["busy"] = False


async def screen_loop():
    await asyncio.sleep(90)  # сначала даём панели посчитать прогоны
    while True:
        await screen_refresh()
        await asyncio.sleep(1800)


async def api_screen(req):
    if req.method == "POST":
        asyncio.create_task(screen_refresh())
    return web.json_response({"data": _SCREEN["data"], "busy": _SCREEN["busy"], "err": _SCREEN["err"], "now": int(time.time() * 1000)})


async def refresher():
    """Фоновый пересчёт всех прогонов: страница получает готовый снимок сразу, а не ждёт минуту."""
    while True:
        try:
            async with _build_lock():
                t0 = time.time()
                now = int(t0 * 1000)
                runs = jload(RUNS_FILE, [])
                _SNAP["payload"] = await build_payload(runs, now)
                _SNAP["ts"] = time.time()
                _SNAP["calc_s"] = round(time.time() - t0, 1)
                if _RT_DIRTY[0]:
                    _rt_save({r["id"] for r in runs})
        except Exception as e:
            import traceback; print("refresher error: %r" % (e,)); traceback.print_exc()
        await asyncio.sleep(15)


async def api_runs(req):
    now = int(time.time() * 1000)
    try:
        if req.method == "POST":
            j = await req.json()
            act = j.get("action")
            async with _build_lock():
                runs = jload(RUNS_FILE, [])
                if act == "start":
                    sym = str(j.get("sym", "")).upper()
                    if not ok_sym(sym):
                        raise ValueError("плохая пара")
                    cfg = clean_cfg(j.get("config") or {}, base=load_cfg())
                    cfg["period_from"] = cfg["period_to"] = ""  # живой прогон идёт вперёд от текущего момента
                    await get_df_long(sym, cfg["tf"])
                    rid = max([r["id"] for r in runs] + [0]) + 1
                    runs.append({"id": rid, "name": (str(j.get("name") or "Прогон")[:60]), "sym": sym, "cfg": cfg,
                                 "start_ms": now, "stop_ms": None, "trades": None})
                elif act in ("stop", "delete"):
                    r = next((x for x in runs if x["id"] == j.get("id")), None)
                    if r is None:
                        raise ValueError("прогон не найден")
                    if act == "delete":
                        runs.remove(r)
                    else:
                        await _stop_run(r, now)
                elif act == "add_pair":
                    sym = str(j.get("sym", "")).upper()
                    if not ok_sym(sym):
                        raise ValueError("плохая пара")
                    cur = {r["sym"] for r in runs if r["stop_ms"] is None}
                    if sym in cur:
                        raise ValueError("пара уже торгуется")
                    if len(cur) >= CAP_PAIRS:
                        raise ValueError("достигнут ориентир нагрузки: %d пар. Сначала уберите одну" % CAP_PAIRS)
                    tpl = {}
                    for r in runs:
                        tpl.setdefault(track_of(r["cfg"]), r)
                    if "me" not in tpl or "bot" not in tpl:
                        raise ValueError("нет шаблона прогонов «Вы»/«Бот»")
                    try:
                        for tf in TFS_RUN:
                            await get_df_long(sym, tf)  # заодно проверка, что данные по паре есть
                    except RuntimeError as e:
                        raise ValueError("нет данных по паре %s: %s" % (sym, e))
                    rid = max([r["id"] for r in runs] + [0])
                    for tk, nm in (("me", "Мой канал"), ("bot", "Канал бота")):
                        for tf in TFS_RUN:
                            rid += 1
                            cfg = json.loads(json.dumps(tpl[tk]["cfg"]))
                            cfg["tf"] = tf
                            runs.append({"id": rid, "name": "%s %s %s" % (nm, sym, tf), "sym": sym, "cfg": cfg, "start_ms": now, "stop_ms": None, "trades": None})
                    pl = load_pairs()
                    if sym not in pl:
                        save_pairs(pl + [sym])
                elif act == "bot_pair":
                    # управление парами бота отдельно от «Вы»: auto — бот сам открывает и закрывает; propose — только предлагает (вкладка «Вместе»); off — не работает
                    sym = str(j.get("sym", "")).upper()
                    mode = j.get("mode")
                    if mode not in ("auto", "propose", "off"):
                        raise ValueError("неизвестный режим")
                    if not ok_sym(sym):
                        raise ValueError("плохая пара")
                    cur_b = [r for r in runs if r["sym"] == sym and r["stop_ms"] is None and track_of(r["cfg"]) == "bot"]
                    if mode == "off":
                        if not cur_b:
                            raise ValueError("бот по этой паре и так не работает")
                        for r in cur_b:
                            await _stop_run(r, now)
                    else:
                        if cur_b and all((r.get("mode") or "auto") == mode for r in cur_b):
                            raise ValueError("пара уже в этом режиме")
                        if not cur_b:
                            act_syms = {r["sym"] for r in runs if r["stop_ms"] is None}
                            if sym not in act_syms and len(act_syms) >= CAP_PAIRS:
                                raise ValueError("достигнут ориентир нагрузки: %d пар. Сначала уберите одну" % CAP_PAIRS)
                        ref = {}
                        for r in runs:  # шаблон правил для каждого ТФ: сначала прогоны этой же пары, потом любые активные прогоны бота
                            if r["stop_ms"] is None and track_of(r["cfg"]) == "bot":
                                ref.setdefault(r["cfg"]["tf"], r)
                        for r in cur_b:
                            ref[r["cfg"]["tf"]] = r
                        anyb = next((r for r in reversed(runs) if track_of(r["cfg"]) == "bot"), None)
                        if anyb is None:
                            raise ValueError("нет шаблона прогонов «Бот»")
                        try:
                            for tf in TFS_RUN:
                                await get_df_long(sym, tf)
                        except RuntimeError as e:
                            raise ValueError("нет данных по паре %s: %s" % (sym, e))
                        for r in cur_b:
                            await _stop_run(r, now)  # история прежних прогонов сохраняется
                        rid = max([r["id"] for r in runs] + [0])
                        nm = "Канал бота" if mode == "auto" else "Предложение бота"
                        for tf in TFS_RUN:
                            rid += 1
                            cfg = json.loads(json.dumps(ref.get(tf, anyb)["cfg"]))
                            cfg["tf"] = tf
                            runs.append({"id": rid, "name": "%s %s %s" % (nm, sym, tf), "sym": sym, "cfg": cfg, "mode": mode, "start_ms": now, "stop_ms": None, "trades": None})
                        pl = load_pairs()
                        if sym not in pl:
                            save_pairs(pl + [sym])
                elif act in ("pos_close", "pos_stop"):
                    # ручное управление открытой позицией на любой вкладке (Вы / Бот / Вместе): закрыть по текущей цене, поставить стоп или трейлинг на расстоянии в %
                    r = next((x for x in runs if x["id"] == j.get("run")), None)
                    if r is None or r["stop_ms"] is not None:
                        raise ValueError("прогон не найден или остановлен")
                    t_in, side = int(j.get("kt")), str(j.get("side"))
                    x = next((x for x in cs.pack(await run_trades(r, now)) if x["t_in"] == t_in and x["side"] == side), None)
                    if x is None or not x["open"]:
                        raise ValueError("позиция уже закрыта — обновите страницу")
                    if (r.get("mode") or "auto") == "propose":
                        dd = next((d for d in jload(PROP_FILE, []) if d["k"] == pr.dkey(r["id"], t_in, side)), None)
                        if dd is None or dd["dec"] != "open":
                            raise ValueError("эта позиция не открыта вами")
                    try:
                        cur = (await ticker_prices([r["sym"]]))[r["sym"]]
                    except Exception:
                        cur = float(x["p_out"])
                    msd = jload(MAN_FILE, {})
                    k = mkey(r["id"], t_in, side)
                    st = msd.get(k) or {}
                    st.update(run=r["id"], t_in=t_in, side=side, sym=r["sym"], set_ms=now, done=False)
                    if act == "pos_close":
                        st["close"] = {"ms": now, "px": cur, "reason": "ручное закрытие"}
                    else:
                        mode = j.get("mode")
                        if mode == "clear":
                            if not st.get("mode"):
                                raise ValueError("ручного стопа нет")
                            st.update(mode=None, pct=None, lvl=None, mext=None)
                        else:
                            if mode not in ("stop", "trail"):
                                raise ValueError("неизвестный режим")
                            try:
                                pct = float(j.get("pct"))
                            except (TypeError, ValueError):
                                raise ValueError("укажите расстояние в %")
                            if not 0.05 <= pct <= 50:
                                raise ValueError("расстояние должно быть от 0.05 до 50 %")
                            L = side == "L"
                            lvl = cur * (1 - pct / 100.0) if L else cur * (1 + pct / 100.0)
                            if (L and not lvl > float(x["stop"])) or ((not L) and not lvl < float(x["stop"])):
                                raise ValueError("стоп стратегии уже ближе к цене (%s): ручной стоп на %s%% (%s) его не улучшит. Уменьшите расстояние" % (x["stop"], pct, round(lvl, 8)))
                            st.update(mode=mode, pct=pct, lvl=lvl, mext=cur)
                    msd[k] = st
                    jsave(MAN_FILE, msd)
                    _RT.pop(r["id"], None)
                elif act == "decide":
                    dec = j.get("dec")
                    if dec not in ("open", "reject"):
                        raise ValueError("неизвестное решение")
                    r = next((x for x in runs if x["id"] == j.get("run")), None)
                    if r is None or r["stop_ms"] is not None or (r.get("mode") or "auto") != "propose":
                        raise ValueError("предложение недоступно (пара переведена в другой режим или прогон остановлен)")
                    t_in, side = int(j.get("t_in")), str(j.get("side"))
                    x = next((x for x in cs.pack(await run_trades(r, now)) if x["t_in"] == t_in and x["side"] == side), None)
                    if x is None or not x["open"]:
                        raise ValueError("предложение уже закрылось (сработал стоп или цель) — обновите страницу")
                    decs = jload(PROP_FILE, [])
                    k = pr.dkey(r["id"], t_in, side)
                    if any(d["k"] == k for d in decs):
                        raise ValueError("по этому предложению решение уже есть")
                    decs.append({"k": k, "run": r["id"], "sym": r["sym"], "tf": r["cfg"]["tf"], "side": side, "t_in": t_in, "dec": dec,
                                 "t_dec": now, "p_dec": x["p_out"], "p_sig": x["p_in"]})
                    jsave(PROP_FILE, decs)
                elif act == "vp_cfg":  # настройки стратегии «Профиль» — всем активным прогонам профиля; история пересчитается по новым настройкам
                    clean = vp_clean(j.get("cfg") or {})
                    tf_ = j.get("tf")  # настройки отдельного таймфрейма: только прогоны этого ТФ; дата старта профиля общая и тут не меняется
                    if tf_:
                        if tf_ not in VP_TFS_ALL:
                            raise ValueError("плохой таймфрейм")
                        clean.pop("vp_start", None)
                    n_ = 0
                    for r in runs:
                        if r["stop_ms"] is None and track_of(r["cfg"]) == "vp" and (not tf_ or r["cfg"]["tf"] == tf_):
                            r["cfg"].update(clean); _RT.pop(r["id"], None); n_ += 1
                    if not n_:
                        raise ValueError("нет активных прогонов профиля")
                elif act == "vp_start":  # дата начала счёта «Профиль» (UTC «ГГГГ-ММ-ДД ЧЧ:ММ» или «now» = только вперёд): сделки раньше неё в счёт не входят
                    s_ = str(j.get("start") or "").strip()
                    if s_ == "now":
                        ms_ = now
                    elif re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$", s_):
                        ms_ = int(datetime.datetime.strptime(s_.replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
                    else:
                        raise ValueError("дата начала: «ГГГГ-ММ-ДД ЧЧ:ММ» (UTC) или «now»")
                    if ms_ > now:
                        raise ValueError("дата начала в будущем")
                    if ms_ < now - 30 * 86400000:
                        raise ValueError("дата начала раньше чем 30 суток назад — истории не хватит")
                    n_ = 0
                    for r in runs:
                        if r["stop_ms"] is None and track_of(r["cfg"]) == "vp":
                            r["start_ms"] = ms_; r["cfg"]["vp_since"] = ms_; _RT.pop(r["id"], None); n_ += 1
                    if not n_:
                        raise ValueError("нет активных прогонов профиля")
                elif act == "vp_add_pair":  # ротация пар счёта «Профиль»: пара добавляется только в Профиль, на все выбранные таймфреймы
                    sym = str(j.get("sym", "")).upper()
                    if not ok_sym(sym):
                        raise ValueError("плохая пара")
                    va = vp_active(runs)
                    vsyms = {r["sym"] for r in va}
                    if sym in vsyms:
                        raise ValueError("пара уже в Профиле")
                    if not va:
                        raise ValueError("нет шаблона прогонов Профиля")
                    tfs = vp_tfs_cur(runs)
                    if len(vsyms) >= VP_CAP_PAIRS:
                        raise ValueError("достигнут максимум пар Профиля: %d. Сначала уберите одну" % VP_CAP_PAIRS)
                    if len(va) + len(tfs) > VP_CAP_RUNS:
                        raise ValueError("лимит прогонов Профиля: %d (сейчас %d, пара добавит %d)" % (VP_CAP_RUNS, len(va), len(tfs)))
                    act_syms = {r["sym"] for r in runs if r["stop_ms"] is None}
                    if sym not in act_syms and len(act_syms) >= CAP_PAIRS:
                        raise ValueError("достигнут ориентир нагрузки: %d пар. Сначала уберите одну" % CAP_PAIRS)
                    try:
                        await vp_make(runs, sym, tfs, now, va[0]["cfg"])
                    except RuntimeError as e:
                        raise ValueError("нет данных по паре %s: %s" % (sym, e))
                elif act == "vp_drop_pair":  # убрать пару только из Профиля (прогоны других вкладок не трогаем)
                    sym = str(j.get("sym", "")).upper()
                    rs = [r for r in vp_active(runs) if r["sym"] == sym]
                    if not rs:
                        raise ValueError("по этой паре нет активных прогонов Профиля")
                    for r in rs:
                        await _stop_run(r, now)
                elif act == "vp_tfs":  # набор таймфреймов Профиля: новые стартуют с текущего момента, снятые останавливаются (история остаётся)
                    tfs = [t for t in VP_TFS_ALL if t in (j.get("tfs") or [])]
                    if not tfs:
                        raise ValueError("выберите хотя бы один таймфрейм")
                    va = vp_active(runs)
                    if not va:
                        raise ValueError("нет активных прогонов профиля")
                    syms = sorted({r["sym"] for r in va})
                    if len(syms) * len(tfs) > VP_CAP_RUNS:
                        raise ValueError("%d пар x %d ТФ = %d прогонов, лимит %d. Уберите пары или таймфреймы" % (len(syms), len(tfs), len(syms) * len(tfs), VP_CAP_RUNS))
                    have = {(r["sym"], r["cfg"]["tf"]) for r in va}
                    tpl = va[0]["cfg"]
                    try:
                        for s_ in syms:  # сначала создаём недостающие (если данных нет — ничего не меняется), потом останавливаем снятые
                            miss = [tf for tf in tfs if (s_, tf) not in have]
                            if miss:
                                await vp_make(runs, s_, miss, now, tpl)
                    except RuntimeError as e:
                        raise ValueError("нет данных по паре %s: %s" % (s_, e))
                    for r in va:
                        if r["cfg"]["tf"] not in tfs:
                            await _stop_run(r, now)
                    jsave(VP_TFS_FILE, tfs)
                elif act == "drop_pair":
                    sym = str(j.get("sym", "")).upper()
                    rs = [r for r in runs if r["sym"] == sym and r["stop_ms"] is None]
                    if not rs:
                        raise ValueError("по этой паре нет активных прогонов")
                    for r in rs:
                        await _stop_run(r, now)
                else:
                    raise ValueError("неизвестное действие")
                jsave(RUNS_FILE, runs)
                _SNAP["payload"] = await build_payload(runs, now)
                _SNAP["ts"] = time.time()
        p = _SNAP["payload"]
        if p is None:  # после перезапуска первый расчёт ещё идёт
            return web.json_response({"loading": True, "runs": [], "now": now, "notional": cs.PARAMS["notional"], "hand": {}, "accounts": {}})
        return web.json_response(p)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)


LABELS_FILE = os.path.join(HERE, "labels.json")


async def api_labels(req):
    labels = jload(LABELS_FILE, [])
    try:
        if req.method == "POST":
            j = await req.json()
            act = j.get("action")
            sym = str(j.get("sym", "")).upper()
            tf = j.get("tf")
            if not ok_sym(sym) or tf not in ALLTF:
                raise ValueError("плохая пара или таймфрейм")
            if act == "add":
                kind = j.get("kind")
                if kind not in ("L", "S", "X"):
                    raise ValueError("метка: L, S или X")
                t, price = int(j.get("t")), float(j.get("p"))
                labels = [x for x in labels if not (x["sym"] == sym and x["tf"] == tf and x["t"] == t)]
                labels.append({"id": max([x["id"] for x in labels] + [0]) + 1, "sym": sym, "tf": tf, "t": t,
                               "kind": kind, "p": price, "ts": int(time.time() * 1000)})
            elif act == "del_at":
                t = int(j.get("t"))
                labels = [x for x in labels if not (x["sym"] == sym and x["tf"] == tf and x["t"] == t)]
            elif act == "del":
                labels = [x for x in labels if x["id"] != j.get("id")]
            else:
                raise ValueError("неизвестное действие")
            jsave(LABELS_FILE, labels)
        else:
            sym = req.query.get("sym", "").upper()
            tf = req.query.get("tf", "")
            if req.query.get("all"):
                return web.json_response({"labels": labels})
        return web.json_response({"labels": [x for x in labels if x["sym"] == sym and x["tf"] == tf]})
    except (ValueError, TypeError) as e:
        return web.json_response({"error": str(e)}, status=400)


HAND_LEARN_FILE = tl.LEARNED_FILE


def learned_info():
    try:
        with open(HAND_LEARN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def hand_learn():
    """Подбор параметров авто-детектора линий тренда так, чтобы он повторял рисунки пользователя."""
    items = [x for x in hd.load() if not x.get("deleted")]
    if not items:
        return web.json_response({"error": "нет нарисованных структур — сначала нарисуй хотя бы одну"}, status=400)
    data = {}
    for key in {(x["sym"], x["tf"]) for x in items}:
        df = await get_df(*key)
        closed, _ = split_closed(df)
        ind = an.indicators(closed)
        data[key] = dict(t=closed.t.values, o=closed.o.values, c=closed.c.values, h=closed.h.values, l=closed.l.values, atr=ind["atr"].values)
    loop = asyncio.get_running_loop()
    best, rep = await loop.run_in_executor(None, hd.calibrate, data, items)
    if best is None:
        return web.json_response({"error": rep.get("msg", "не удалось")}, status=400)
    tl.set_cfg(best)
    out = {"cfg": {k: best[k] for k in tl.CFG}, "report": rep, "ts": int(time.time() * 1000)}
    jsave(HAND_LEARN_FILE, out)
    return web.json_response({"learn_done": out})


async def api_hand(req):
    items = hd.load()
    try:
        j = {}
        if req.method == "POST":
            j = await req.json()
            act = j.get("action")
            now = int(time.time() * 1000)
            items = [dict(x) for x in items]
            if act == "add":
                sym, tf, kind = str(j.get("sym", "")).upper(), j.get("tf"), j.get("kind")
                if not ok_sym(sym) or tf not in ALLTF:
                    raise ValueError("плохая пара или таймфрейм")
                if kind not in ("channel", "range", "triangle"):
                    raise ValueError("тип: channel, range или triangle")
                A, B = [float(v) for v in j.get("A", [])], [float(v) for v in j.get("B", [])]
                if len(A) != 4 or len(B) != 4:
                    raise ValueError("каждая линия задаётся четырьмя числами")
                for L_ in (A, B):
                    L_[0], L_[2] = int(L_[0]), int(L_[2])
                    if L_[0] == L_[2]:
                        raise ValueError("две точки линии на одном времени")
                anc = [a if a in ("h", "l", "o", "c") else "free" for a in [str(v) for v in (j.get("anc") or [])][:4]]
                items.append({"id": max([x["id"] for x in items] + [0]) + 1, "sym": sym, "tf": tf, "kind": kind, "A": A, "B": B, "anc": anc, "created": now, "deleted": None})
            elif act == "update":  # линии перетащены за опорные точки; момент создания сбрасывается (для честной торговли «только вперёд»)
                A, B = [float(v) for v in j.get("A", [])], [float(v) for v in j.get("B", [])]
                if len(A) != 4 or len(B) != 4:
                    raise ValueError("каждая линия задаётся четырьмя числами")
                for L_ in (A, B):
                    L_[0], L_[2] = int(L_[0]), int(L_[2])
                    if L_[0] == L_[2]:
                        raise ValueError("две точки линии на одном времени")
                for x in items:
                    if x["id"] == j.get("id") and not x.get("deleted"):
                        x["A"], x["B"], x["created"], x["edited"] = A, B, now, now
            elif act == "del":
                for x in items:
                    if x["id"] == j.get("id") and not x.get("deleted"):
                        x["deleted"] = now
            elif act == "undo":
                cand = [x for x in items if x["sym"] == str(j.get("sym", "")).upper() and not x.get("deleted")]
                if cand:
                    max(cand, key=lambda x: x["id"])["deleted"] = now
            elif act == "learn":
                return await hand_learn()
            else:
                raise ValueError("неизвестное действие")
            hd.save(items)
        sym = (str(j.get("sym", "")) if j else req.query.get("sym", "")).upper()
        tf = (j.get("tf") if j else req.query.get("tf", "")) or "15m"
        mine = [x for x in items if x["sym"] == sym]
        live_ = [x for x in mine if not x.get("deleted")]
        sigs = []
        if live_ and tf in ALLTF:
            df = await get_df(sym, tf)
            closed, _ = split_closed(df)
            ind = an.indicators(closed)
            sigs = hd.markers(closed.o.values, closed.h.values, closed.l.values, closed.c.values, ind["atr"].values, closed.t.values, len(closed), live_, forward=False)
        return web.json_response({"items": live_, "sigs": sigs, "learned": learned_info(), "cfg": dict(tl.CFG)})
    except (ValueError, TypeError, KeyError) as e:
        return web.json_response({"error": str(e)}, status=400)


async def index(req):
    return web.Response(text=HTML, content_type="text/html")


HTML = r'''<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1"><title>Classic bot</title>
<style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px system-ui,sans-serif}
.t{display:flex;flex-wrap:wrap;gap:4px;padding:4px 6px}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:4px 8px;font-size:12px}
button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
#info{padding:2px 8px;font:11.5px ui-monospace,monospace;min-height:30px;color:#8b949e}
canvas{display:block;width:100%;touch-action:none}
#legend{padding:2px 8px;font-size:11px;color:#8b949e}
.card{margin:6px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px}
.card h4{margin:0 0 6px;font-size:13px;color:#e6edf3}
table{border-collapse:collapse;width:100%}td,th{padding:3px 6px;text-align:right;border-bottom:1px solid #21262d;font-size:12px}
td:first-child,th:first-child{text-align:left}
.up{color:#26a69a}.dn{color:#ef5350}.fl{color:#8b949e}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-weight:600}
.badge.up{background:#12332f}.badge.dn{background:#3a1b1d}.badge.fl{background:#262c34}
ul{margin:4px 0 0;padding-left:18px}
</style></head><body>
<div class=t id=pairs></div><div class=t id=tfs></div><div class=t id=opts></div><div class=t id=labbar></div><div class=t id=vbar></div><div class=t id=hbar></div>
<div id=info>загрузка…</div><canvas id=c></canvas>
<div id=legend>Паттерны: Мол=молот · ПЗ=падающая звезда · П↑/П↓=поглощение · УЗ/ВЗ=утренняя/вечерняя звезда · Д=доджи. Треугольники — подтверждённые pivot (с задержкой 5 свечей). Пунктирная справа — формирующаяся свеча (в анализе не участвует). Линии тренда: зелёная — поддержка, красная — сопротивление (авто); «✎ Мои каналы» — нарисованные тобой структуры.</div>
<div class=card id=cTrend></div><div class=card id=cMtf></div><div class=card id=cLv></div><div class=card id=cPat></div><div class=card id=cLab style="display:none"></div><div class=card id=cHand style="display:none"></div>
<script>
const TFS=['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
const TFMS={'1m':60000,'3m':180000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000,'2h':7200000,'4h':14400000,'6h':21600000,'8h':28800000,'12h':43200000,'1d':86400000};
const OPTN={ema:'EMA',bb:'Bollinger',lv:'Уровни',pv:'Pivot',pt:'Паттерны',tl:'Линии тренда',fc:'Быстрый канал',vol:'Объём',rsi:'RSI',macd:'MACD'};
const S={sym:localStorage.csym||'BTCUSDT',tf:localStorage.ctf||'15m',n:120,off:0,vz:1,vo:0,hover:-1,D:null,pairs:[],lab:{on:0,items:[]},hand:{on:0,tool:null,pts:[],items:[],sigs:[],learned:null},
 opt:Object.assign({ema:1,bb:0,lv:1,pv:1,pt:1,tl:1,fc:1,vol:1,rsi:1,macd:0},JSON.parse(localStorage.copt||'{}'))};
const G={start:0,end:0,bw:5,L:4};
const $=id=>document.getElementById(id);
const cl=(x,a,b)=>Math.max(a,Math.min(b,x));
function fmt(p){if(p==null)return'—';const a=Math.abs(p);const d=a>=1000?2:a>=100?3:a>=10?4:a>=1?5:a>=0.1?5:7;return p.toFixed(d)}
function fts(t,tf,full){const d=new Date(t),p=n=>String(n).padStart(2,'0');
 const dm=p(d.getDate())+'.'+p(d.getMonth()+1),hm=p(d.getHours())+':'+p(d.getMinutes());
 return tf==='1d'?dm:(full?dm+' '+hm:hm)}
function mk(){
 $('tfs').innerHTML='';TFS.forEach(t=>{const b=document.createElement('button');b.textContent=t;if(t===S.tf)b.className='on';b.onclick=()=>{S.tf=t;localStorage.ctf=t;S.off=0;S.vz=1;S.vo=0;S.hover=-1;S.D=null;S.hand.pts=[];mk();load()};$('tfs').appendChild(b)});
 $('opts').innerHTML='';Object.keys(OPTN).forEach(k=>{const b=document.createElement('button');b.textContent=OPTN[k];if(S.opt[k])b.className='on';b.onclick=()=>{S.opt[k]=S.opt[k]?0:1;localStorage.copt=JSON.stringify(S.opt);mk();draw()};$('opts').appendChild(b)});
 $('pairs').innerHTML='';S.pairs.forEach(p=>{const b=document.createElement('button');b.textContent=p.replace('USDT','');if(p===S.sym)b.className='on';b.onclick=()=>{S.sym=p;localStorage.csym=p;S.off=0;S.vz=1;S.vo=0;S.hover=-1;S.D=null;S.hand.pts=[];S.hand.items=[];S.hand.sigs=[];mk();load();loadMtf()};$('pairs').appendChild(b)});
 const a=document.createElement('button');a.textContent='+';a.onclick=async()=>{const s=prompt('Пара (например SOL или PEPEUSDT):');if(!s)return;const r=await fetch('/api/pairs',{method:'POST',body:JSON.stringify({add:s})});const j=await r.json();if(j.error){alert(j.error);return}S.pairs=j.pairs;S.sym=s.toUpperCase().replace('/','').match(/USDT|USDC|BTC$/)?s.toUpperCase().replace('/',''):s.toUpperCase()+'USDT';localStorage.csym=S.sym;S.D=null;mk();load();loadMtf()};$('pairs').appendChild(a);
 const d=document.createElement('button');d.textContent='−';d.onclick=async()=>{if(!confirm('Убрать '+S.sym+' из списка?'))return;const r=await fetch('/api/pairs',{method:'POST',body:JSON.stringify({del:S.sym})});const j=await r.json();S.pairs=j.pairs;S.sym=S.pairs[0];localStorage.csym=S.sym;S.D=null;mk();load();loadMtf()};$('pairs').appendChild(d);
 mkLab();mkView();mkHand();
}
async function loadLabels(){try{const r=await fetch('/api/labels?sym='+S.sym+'&tf='+S.tf);const j=await r.json();S.lab.items=j.labels||[];renderLab();if(S.D)draw()}catch(e){}}
function renderLab(){const c=$('cLab');const it=S.lab.items;if(!S.lab.on&&!it.length){c.style.display='none';return}c.style.display='block';
 let h='<h4>Разметка: идеальные входы и выходы · '+S.sym+' '+S.tf+'</h4><div style="color:#8b949e;font-size:11.5px">Метка ставится на свечу: вход или выход — по закрытию этой свечи. Время локальное.</div>';
 h+=it.length?'<table><tr><th>Время</th><th>Метка</th><th>Цена</th><th></th></tr>'+it.slice().sort((a,b)=>b.t-a.t).map(b=>'<tr><td>'+fts(b.t,S.tf,true)+'</td><td>'+({L:'вход ЛОНГ',S:'вход ШОРТ',X:'выход'}[b.kind])+'</td><td>'+fmt(b.p)+'</td><td><button onclick="labDel('+b.id+')">✕</button></td></tr>').join('')+'</table>':'<div style="margin-top:6px">меток пока нет</div>';c.innerHTML=h}
async function labPost(o){try{const r=await fetch('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});const j=await r.json();if(j.error){alert(j.error);return}S.lab.items=j.labels||[];renderLab();draw()}catch(e){alert(e)}}
function labAct(k){const D=S.D;if(!D)return;const i=S.hover;if(i<0||i>=D.t.length){alert('Сначала тапни по закрытой свече на графике');return}
 if(k==='DEL')return labPost({action:'del_at',sym:S.sym,tf:S.tf,t:D.t[i]});
 labPost({action:'add',sym:S.sym,tf:S.tf,t:D.t[i],kind:k,p:D.c[i]})}
function labDel(id){labPost({action:'del',id:id,sym:S.sym,tf:S.tf})}
function mkLab(){const b=$('labbar');b.innerHTML='';const t=document.createElement('button');t.textContent='✎ Разметка'+(S.lab.on?': ВКЛ':'');if(S.lab.on)t.className='on';t.onclick=()=>{S.lab.on=S.lab.on?0:1;mkLab();renderLab()};b.appendChild(t);
 if(S.lab.on){[['L','▲ Вход ЛОНГ'],['S','▼ Вход ШОРТ'],['X','■ Выход'],['DEL','✕ Снять']].forEach(([k,l])=>{const x=document.createElement('button');x.textContent=l;x.onclick=()=>labAct(k);b.appendChild(x)});const h=document.createElement('span');h.style.cssText='font-size:11px;color:#8b949e';h.textContent='тапни свечу, потом кнопку';b.appendChild(h)}}
async function load(){
 const key=S.sym+S.tf;
 try{const r=await fetch('/api/chart?sym='+S.sym+'&tf='+S.tf);const j=await r.json();
  if(j.error){$('info').textContent='Ошибка: '+j.error;return}
  if(key!==S.sym+S.tf)return;
  const pn=S.D&&S.D.sym===j.sym&&S.D.tf===j.tf?S.D.t.length:0;
  if(S.off>0&&pn&&j.t.length!==pn)S.off+=j.t.length-pn;
  S.D=j;draw();cards();loadLabels();loadHand()}catch(e){$('info').textContent='Ошибка: '+e}
}
async function loadMtf(){
 try{const r=await fetch('/api/mtf?sym='+S.sym);const j=await r.json();if(j.sym!==S.sym)return;
  const nm={up:['up','ВВЕРХ ▲'],down:['dn','ВНИЗ ▼'],flat:['fl','БОКОВИК ▬']};
  let h='<h4>Тренд по таймфреймам · '+S.sym+'</h4><table><tr><th>ТФ</th><th>Тренд</th><th>Счёт</th><th>RSI</th><th>vs EMA50</th><th>ATR%</th></tr>';
  const dirs=[];
  j.rows.forEach(x=>{if(x.error){h+='<tr><td>'+x.tf+'</td><td colspan=5>'+x.error+'</td></tr>';return}
   dirs.push(x.dir);const n=nm[x.dir];h+='<tr><td>'+x.tf+'</td><td><span class="badge '+n[0]+'">'+n[1]+'</span></td><td>'+(x.score>0?'+':'')+x.score+'/'+x.max+'</td><td>'+x.rsi.toFixed(0)+'</td><td class="'+(x.vs50>=0?'up':'dn')+'">'+(x.vs50>=0?'+':'')+x.vs50.toFixed(2)+'%</td><td>'+x.atrp.toFixed(2)+'</td></tr>'});
  h+='</table>';
  const u=dirs.filter(d=>d==='up').length,d=dirs.filter(d=>d==='down').length;
  h+='<div style="margin-top:6px;color:#8b949e">'+(u===dirs.length?'Все ТФ вверх — согласованный рост':d===dirs.length?'Все ТФ вниз — согласованное падение':'ТФ расходятся: вверх '+u+', вниз '+d+', боковик '+(dirs.length-u-d))+'</div>';
  $('cMtf').innerHTML=h}catch(e){}
}
function cards(){
 const D=S.D;if(!D)return;const T=D.trend;const nm={up:['up','ВВЕРХ ▲'],down:['dn','ВНИЗ ▼'],flat:['fl','БОКОВИК ▬']}[T.dir];
 let h='<h4>Что бот видит на '+D.sym+' '+D.tf+'</h4><span class="badge '+nm[0]+'">'+nm[1]+'</span> счёт '+(T.score>0?'+':'')+T.score+'/'+T.max+' · структура '+T.struct+' · ATR '+fmt(D.atr)+'<ul>';
 T.why.forEach(w=>{h+='<li class="'+(w[0]==='+'?'up':w[0]==='−'?'dn':'fl')+'">'+w+'</li>'});h+='</ul>';$('cTrend').innerHTML=h;
 const lv=D.levels,p=D.last;const sup=lv.filter(x=>x.p<=p).sort((a,b)=>b.p-a.p),res=lv.filter(x=>x.p>p).sort((a,b)=>a.p-b.p);
 let l='<h4>Уровни (кластеры pivot)</h4><table><tr><th>Тип</th><th>Цена</th><th>Расст.</th><th>Касаний</th><th>Возраст</th></tr>';
 res.slice(0,5).reverse().forEach(x=>{l+='<tr><td class=dn>сопр.</td><td>'+fmt(x.p)+'</td><td>+'+x.dist.toFixed(2)+'%</td><td>'+x.n+'</td><td>'+x.age+' св.</td></tr>'});
 l+='<tr><td colspan=5 style="color:#e6edf3">▸ цена '+fmt(p)+'</td></tr>';
 sup.slice(0,5).forEach(x=>{l+='<tr><td class=up>подд.</td><td>'+fmt(x.p)+'</td><td>'+x.dist.toFixed(2)+'%</td><td>'+x.n+'</td><td>'+x.age+' св.</td></tr>'});
 $('cLv').innerHTML=l+'</table>';
 const N=D.t.length;let q='<h4>Последние свечные паттерны</h4>';
 const ps=D.patterns.slice(-8).reverse();
 q+=ps.length?'<table>'+ps.map(x=>'<tr><td>'+fts(D.t[x.i],D.tf,true)+'</td><td>'+x.n+'</td><td class="'+(x.d>0?'up':x.d<0?'dn':'fl')+'">'+(x.d>0?'бычий':x.d<0?'медвежий':'нейтр.')+'</td><td>'+(N-1-x.i)+' св. назад</td></tr>').join('')+'</table>':'нет';
 $('cPat').innerHTML=q;
}


function mkView(){const b=$('vbar');b.innerHTML='';
 [['↔+',()=>{S.n=Math.max(10,Math.round(S.n*0.8))}],['↔−',()=>{S.n=Math.min(1000,Math.round(S.n*1.25))}],['↕+',()=>{S.vz=Math.min(12,S.vz*1.25)}],['↕−',()=>{S.vz=Math.max(0.15,S.vz/1.25)}],
  ['◀',()=>{S.off+=Math.max(1,Math.round(S.n*0.25))}],['▶',()=>{S.off-=Math.max(1,Math.round(S.n*0.25))}],['⟲',()=>{S.n=120;S.off=0;S.vz=1;S.vo=0}]].forEach(([l,f])=>{const x=document.createElement('button');x.textContent=l;x.onclick=()=>{f();draw()};b.appendChild(x)});
 const h=document.createElement('span');h.style.cssText='font-size:11px;color:#8b949e';h.textContent='тяни график — сдвиг (вправо за последнюю свечу — будущее); щипок по горизонтали/вертикали — масштаб; ось цены справа / ось времени снизу — тяни для масштаба';b.appendChild(h)}
function mkHand(){const b=$('hbar');b.innerHTML='';const H=S.hand;
 const t=document.createElement('button');t.textContent='✎ Мои каналы'+(H.on?': ВКЛ':'');if(H.on)t.className='on';t.onclick=()=>{H.on=H.on?0:1;if(!H.on){H.tool=null;H.pts=[]}mkHand();renderHand();draw()};b.appendChild(t);
 if(H.on){[['channel','Канал (3 тапа)'],['triangle','Треугольник (4 тапа)'],['range','Флэт (2 тапа)']].forEach(([k,l])=>{const x=document.createElement('button');x.textContent=l;if(H.tool===k)x.className='on';x.onclick=()=>{H.tool=H.tool===k?null:k;H.pts=[];mkHand();renderHand();draw()};b.appendChild(x)});
  const u=document.createElement('button');u.textContent='↶ Отменить последнюю';u.onclick=()=>handPost({action:'undo',sym:S.sym,tf:S.tf});b.appendChild(u);
  const lr=document.createElement('button');lr.textContent='🧠 Обучить по моим рисункам';lr.onclick=()=>handLearn();b.appendChild(lr);
  const h=document.createElement('span');h.style.cssText='font-size:11px;color:#8b949e;flex-basis:100%';h.id='hhint';b.appendChild(h);hintHand()}}
function hintHand(){const e=$('hhint');if(!e)return;const H=S.hand;
 const m={channel:'Канал: тап 1 и тап 2 — две точки главной линии (например, по двум минимумам), тап 3 — точка, через которую пройдёт параллельная линия',triangle:'Треугольник: тапы 1–2 — первая линия, тапы 3–4 — вторая линия',range:'Флэт: тап 1 — верхняя граница (левый край), тап 2 — нижняя граница (правый край)'};
 e.textContent=H.tool?(m[H.tool]+' · поставлено точек: '+H.pts.length):'выбери тип; тапы прилипают к ближайшему high/low/open/close свечи; линии продолжаются вправо — прокрути график в будущее (▶). Без выбранного типа можно тянуть за белые кружки — линии переносятся (как в TradingView)'}
function renderHand(){const c=$('cHand'),H=S.hand;if(!H.on&&!H.items.length){c.style.display='none';return}c.style.display='block';
 let h='<h4>Мои каналы · '+S.sym+'</h4>';
 h+=H.items.length?'<table><tr><th>№</th><th>Тип</th><th>Нарисован на</th><th>Создан</th><th></th></tr>'+H.items.map(x=>'<tr><td>'+x.id+'</td><td>'+({channel:'канал',range:'флэт',triangle:'треугольник'}[x.kind])+'</td><td>'+x.tf+'</td><td>'+fts(x.created,'15m',true)+'</td><td><button onclick="handPost({action:\'del\',id:'+x.id+',sym:S.sym,tf:S.tf})">✕</button></td></tr>').join('')+'</table>':'<div>структур пока нет</div>';
 h+='<div style="margin-top:8px;color:#8b949e;font-size:11.5px">Бот торгует по ним: в конструкторе (18091) выбери триггер «отбой от моего канала» или «пробой моей границы». На графике сигналы бота по твоим линиям — «⬆/⬇ мой отбой / мой пробой» (показаны и на истории, но честная торговля — только после момента, когда линия нарисована).</div>';
 const Lr=H.learned;if(Lr&&Lr.report)h+='<div style="margin-top:8px"><b>Обучение:</b> структур '+Lr.report.n+', ошибка авто-линий: было '+Lr.report.base_cost+' ATR → стало '+Lr.report.best_cost+' ATR; совпало '+Lr.report.base_hit+' → '+Lr.report.best_hit+' из '+Lr.report.n+'. Опорные точки пользователя: хвосты '+((Lr.report.anchors||{}).wick||0)+', тела '+((Lr.report.anchors||{}).body||0)+' → использую: '+(Lr.cfg.anchor==='body'?'тела':'хвосты')+'. Параметры: pivot '+Lr.cfg.piv_n+', допуск '+Lr.cfg.tol+' ATR, мин. расстояние между опорами '+Lr.cfg.sep+', окно '+Lr.cfg.look+', перебор опор '+Lr.cfg.nback+'</div>';
 c.innerHTML=h}
async function loadHand(){try{const r=await fetch('/api/hand?sym='+S.sym+'&tf='+S.tf);const j=await r.json();if(j.error)return;S.hand.items=j.items||[];S.hand.sigs=j.sigs||[];S.hand.learned=j.learned;renderHand();if(S.D)draw()}catch(e){}}
async function handPost(o){try{const r=await fetch('/api/hand',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});const j=await r.json();if(j.error){alert(j.error);return}
 if(j.learn_done){S.hand.learned=j.learn_done;renderHand();alert('Обучение завершено, параметры применены к авто-линиям тренда');load();return}
 S.hand.items=j.items||[];S.hand.sigs=j.sigs||[];S.hand.learned=j.learned;renderHand();draw()}catch(e){alert(e)}}
async function handLearn(){if(!confirm('Подобрать параметры авто-детектора линий так, чтобы он повторял твои рисунки? Займёт несколько секунд.'))return;await handPost({action:'learn',sym:S.sym,tf:S.tf})}
function handTap(x,y){const H=S.hand,pt=ptAt(x,y);H.pts.push({t:pt.t,p:pt.p,k:pt.k});const need={channel:3,triangle:4,range:2}[H.tool];
 if(H.pts.length>=need)handCommit();else{hintHand();draw()}}
function handCommit(){const H=S.hand,P=H.pts;let A,B;
 if(H.tool==='channel'){const t1=P[0].t,p1=P[0].p,t2=P[1].t,p2=P[1].p;if(t2===t1){alert('Две точки главной линии на одной свече — поставь вторую правее или левее');H.pts=[];hintHand();draw();return}
  const sl=(p2-p1)/(t2-t1),off=P[2].p-(p1+sl*(P[2].t-t1));A=[t1,p1,t2,p2];B=[t1,p1+off,t2,p2+off]}
 else if(H.tool==='triangle'){if(P[0].t===P[1].t||P[2].t===P[3].t){alert('Точки линии на одной свече — поставь их на разных');H.pts=[];hintHand();draw();return}A=[P[0].t,P[0].p,P[1].t,P[1].p];B=[P[2].t,P[2].p,P[3].t,P[3].p]}
 else{let t1=Math.min(P[0].t,P[1].t),t2=Math.max(P[0].t,P[1].t);if(t2===t1)t2=t1+5*G.stepMs;const up=Math.max(P[0].p,P[1].p),lo=Math.min(P[0].p,P[1].p);A=[t1,up,t2,up];B=[t1,lo,t2,lo]}
 const kind=H.tool,anc=P.map(q=>q.k);H.pts=[];hintHand();handPost({action:'add',sym:S.sym,tf:S.tf,kind:kind,A:A,B:B,anc:anc})}
function tmTxt(ms){const s=Math.max(0,Math.floor(ms/1000)),d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60),c=s%60,p=n=>(n<10?'0':'')+n;return d?d+'д '+p(h)+':'+p(m)+':'+p(c):h?h+':'+p(m)+':'+p(c):p(m)+':'+p(c)}
function paintTm(g){const q=G.tm;if(!q)return;g.save();g.setTransform(window.devicePixelRatio||1,0,0,window.devicePixelRatio||1,0,0);g.fillStyle=q.col;g.fillRect(q.x,q.y,q.w,14);g.fillStyle='#fff';g.font='10px system-ui';g.textAlign='left';g.textBaseline='middle';g.fillText(tmTxt(q.close-Date.now()),q.x+3,q.y+7);g.restore()}
function draw(){
 const D=S.D;if(!D)return;
 const cv=$('c'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=Math.round(cl(window.innerHeight*0.62,380,660));
 cv.style.height=H+'px';cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);
 const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.fillStyle='#0d1117';g.fillRect(0,0,W,H);
 const N=D.t.length,live=D.live,total=N+(live?1:0);
 const A=(k,i)=>i<N?D[k][i]:live[k];
 const L=4,R=60,B=16,plotW=W-L-R;
 S.n=cl(Math.round(S.n),10,1000);S.off=cl(Math.round(S.off),-(S.n-5),Math.max(0,total-10));S.vz=cl(S.vz,0.15,12);
 const end=total-S.off,startRaw=end-S.n,start=Math.max(0,startRaw),endV=Math.min(end,total),bw=plotW/(S.n+(S.off===0?3:0));
 const stepMs=TFMS[D.tf]||900000,tAt=i=>i<N?D.t[Math.max(0,i)]:D.t[N-1]+(i-N+1)*stepMs;
 G.start=start;G.end=end;G.endV=endV;G.bw=bw;G.L=L;G.W=W;G.H=H;G.B=B;G.plotW=plotW;G.total=total;G.raw=startRaw;G.stepMs=stepMs;G.handles=[];
 const X=i=>L+(i-startRaw+0.5)*bw;
 const panes=[{id:'main',w:5}];if(S.opt.vol)panes.push({id:'vol',w:1});if(S.opt.rsi)panes.push({id:'rsi',w:1.5});if(S.opt.macd)panes.push({id:'macd',w:1.5});
 const tw=panes.reduce((a,p)=>a+p.w,0),avail=H-B;let y=0;panes.forEach(p=>{p.y0=y;p.y1=y+avail*p.w/tw;y=p.y1});
 const P={};panes.forEach(p=>P[p.id]=p);
 g.font='10px system-ui';g.textBaseline='middle';
 // pane borders + labels
 panes.forEach((p,k)=>{if(k>0){g.strokeStyle='#30363d';g.beginPath();g.moveTo(0,p.y0+.5);g.lineTo(W,p.y0+.5);g.stroke()}});
 // ---- main
 const m=P.main;let hi=-1e99,lo=1e99;for(let i=start;i<endV;i++){hi=Math.max(hi,A('h',i));lo=Math.min(lo,A('l',i))}
 if(hi<lo){hi=D.c[N-1]*1.01;lo=D.c[N-1]*0.99}
 const rng=(hi-lo)||hi*0.01,cen=(hi+lo)/2+S.vo*rng,half=rng*0.525/S.vz;hi=cen+half;lo=cen-half;
 G.hi=hi;G.lo=lo;G.my0=m.y0;G.my1=m.y1;G.pxVo=1.05/S.vz/(m.y1-m.y0-12);
 const py=p=>m.y0+6+(hi-p)/(hi-lo)*(m.y1-m.y0-12);
 g.strokeStyle='#1b222c';g.fillStyle='#6e7681';g.textAlign='left';
 for(let k=0;k<=5;k++){const p=lo+(hi-lo)*k/5,yy=py(p);g.beginPath();g.moveTo(L,yy);g.lineTo(L+plotW,yy);g.stroke();g.fillText(fmt(p),L+plotW+4,yy)}
 // levels
 if(S.opt.lv)D.levels.forEach(x=>{if(x.p<lo||x.p>hi)return;const c=x.k==='S'?'38,166,154':'239,83,80';
  const y1=py(Math.min(x.hi,hi)),y2=py(Math.max(x.lo,lo));g.fillStyle='rgba('+c+',0.10)';g.fillRect(L,y1,plotW,Math.max(2,y2-y1));
  g.strokeStyle='rgba('+c+',0.7)';g.lineWidth=1;g.setLineDash(x.n>=3?[]:[4,3]);g.beginPath();g.moveTo(L,py(x.p));g.lineTo(L+plotW,py(x.p));g.stroke();g.setLineDash([]);
  g.fillStyle='rgba('+c+',0.95)';g.textAlign='left';g.fillText('×'+x.n,L+3,py(x.p)-5)});
 // bollinger
 if(S.opt.bb){g.fillStyle='rgba(88,166,255,0.07)';g.beginPath();let st=false;
  for(let i=start;i<Math.min(end,N);i++){if(D.bbu[i]==null)continue;const x=X(i),yy=py(D.bbu[i]);if(!st){g.moveTo(x,yy);st=true}else g.lineTo(x,yy)}
  for(let i=Math.min(end,N)-1;i>=start;i--){if(D.bbl[i]==null)continue;g.lineTo(X(i),py(D.bbl[i]))}g.closePath();g.fill();
  ['bbu','bbm','bbl'].forEach(k=>line(D[k],'rgba(88,166,255,'+(k==='bbm'?0.35:0.7)+')',1))}
 function line(arr,col,w){g.strokeStyle=col;g.lineWidth=w||1.2;g.beginPath();let on=false;
  for(let i=start;i<Math.min(end,N);i++){const v=arr[i];if(v==null){on=false;continue}const x=X(i),yy=py(v);if(!on){g.moveTo(x,yy);on=true}else g.lineTo(x,yy)}g.stroke();g.lineWidth=1}
 // candles
 for(let i=start;i<endV;i++){const o=A('o',i),h=A('h',i),l=A('l',i),c=A('c',i),x=X(i),up=c>=o,col=up?'#26a69a':'#ef5350',bwid=Math.max(1,bw*0.7),isl=i>=N;
  g.strokeStyle=col;g.fillStyle=col;if(isl)g.globalAlpha=0.55;g.beginPath();g.moveTo(x,py(h));g.lineTo(x,py(l));g.stroke();
  const y1=py(Math.max(o,c)),y2=py(Math.min(o,c));if(isl){g.strokeRect(x-bwid/2,y1,bwid,Math.max(1,y2-y1))}else g.fillRect(x-bwid/2,y1,bwid,Math.max(1,y2-y1));g.globalAlpha=1}
 if(end>total){const xn=X(total-0.5);g.strokeStyle='#30363d';g.setLineDash([4,4]);g.beginPath();g.moveTo(xn,m.y0);g.lineTo(xn,m.y1);g.stroke();g.setLineDash([]);g.fillStyle='#6e7681';g.textAlign='left';g.fillText('будущее →',xn+4,m.y1-8)}
 // ema
 if(S.opt.ema){line(D.ema20,'#e3b341',1.2);line(D.ema50,'#58a6ff',1.2);line(D.ema200,'#bc8cff',1.4)}
 // pivots
 if(S.opt.pv)D.pivots.forEach(p=>{if(p.i<start||p.i>=end)return;const x=X(p.i);g.fillStyle=p.k==='H'?'#f0883e':'#79c0ff';g.beginPath();
  if(p.k==='H'){const yy=py(D.h[p.i])-5;g.moveTo(x-3.5,yy-5);g.lineTo(x+3.5,yy-5);g.lineTo(x,yy)}else{const yy=py(D.l[p.i])+5;g.moveTo(x-3.5,yy+5);g.lineTo(x+3.5,yy+5);g.lineTo(x,yy)}g.fill()});
 // patterns
 // линии тренда: поддержка (зелёная), сопротивление (красная), пунктир — линия уже пробита; ⬆/⬇ — сигналы бота (отбой / пробой)
 if(S.opt.tl&&D.tl){const TL=D.tl;g.save();g.beginPath();g.rect(L,m.y0,plotW,m.y1-m.y0);g.clip();
  [['S','#3fb950'],['R','#f85149']].forEach(([k,col])=>{const ln=TL.lines[k];if(!ln)return;const a=Math.max(start,ln.i1),b=end-1+(S.off===0?2:0);if(b<a)return;
   g.strokeStyle=col;g.lineWidth=1.8;g.setLineDash(ln.broken?[6,4]:[]);g.beginPath();g.moveTo(X(a),py(ln.p1+ln.s*(a-ln.i1)));g.lineTo(X(b),py(ln.p1+ln.s*(b-ln.i1)));g.stroke();g.setLineDash([]);g.lineWidth=1;
   g.fillStyle=col;[[ln.i1,ln.p1],[ln.i2,ln.p2]].forEach(([ii,pp])=>{if(ii<start||ii>=end)return;g.beginPath();g.arc(X(ii),py(pp),3.2,0,6.3);g.fill()})});
  g.font='bold 11px system-ui';g.textAlign='center';TL.sigs.forEach(s=>{if(s.i<start||s.i>=end)return;const x=X(s.i),t=(s.kind==='b'?'отбой':'пробой');
   if(s.side==='L'){g.fillStyle='#00e676';g.fillText('⬆'+t,x,py(D.l[s.i])+(S.opt.pv?52:42))}else{g.fillStyle='#ff1744';g.fillText('⬇'+t,x,py(D.h[s.i])-(S.opt.pv?52:42))}});
  g.restore();g.font='11px system-ui';g.textAlign='left';g.fillStyle='#c9d1d9';g.fillText('Линии тренда: '+TL.label,L+6,m.y0+12);g.font='10px system-ui'}
 // быстрый канал бота (жёлтый; пунктир — канал уже пробит телом, линия обрывается на свече пробоя)
 if(S.opt.fc&&D.fc&&D.fc.items){g.save();g.beginPath();g.rect(L,m.y0,plotW,m.y1-m.y0);g.clip();
  D.fc.items.forEach(it=>{const live=it.end===null;const a=Math.max(start,it.lo.i1),b=live?end-1+(S.off===0?2:0):Math.min(end-1,it.end);if(b<a)return;
   [it.lo,it.up].forEach(ln=>{g.strokeStyle=live?'#ffd33d':'#a08a2e';g.lineWidth=live?2:1.2;g.setLineDash(live?[]:[5,4]);g.beginPath();g.moveTo(X(a),py(ln.p1+ln.s*(a-ln.i1)));g.lineTo(X(b),py(ln.p1+ln.s*(b-ln.i1)));g.stroke();g.setLineDash([]);g.lineWidth=1;g.fillStyle='#ffd33d';[[ln.i1,ln.p1],[ln.i2,ln.p2]].forEach(([ii,pp])=>{if(ii<start||ii>=end)return;g.beginPath();g.arc(X(ii),py(pp),2.6,0,6.3);g.fill()})});
   g.fillStyle='#ffd33d';g.font='bold 10px system-ui';g.textAlign='left';g.fillText('быстр.'+(it.mode==='body'?' (тела)':''),X(a),py(it.up.p1+it.up.s*(a-it.up.i1))-6)});
  g.restore();g.font='10px system-ui'}
 // нарисованные мной структуры (синий — канал, оранжевый — флэт, фиолетовый — треугольник; пунктир — вторая линия) и сигналы бота по ним
 if(S.hand.items.length||S.hand.pts.length){g.save();g.beginPath();g.rect(L,m.y0,plotW,m.y1-m.y0);g.clip();
  const ixf=t=>N-1+(t-D.t[N-1])/stepMs,xr=end+(S.off===0?3:1);
  const seg=(ln,col,dash)=>{const i1=ixf(ln[0]),i2=ixf(ln[2]),sl=(ln[3]-ln[1])/((i2-i1)||1),a=Math.min(i1,i2);g.strokeStyle=col;g.lineWidth=2;g.setLineDash(dash?[8,4]:[]);g.beginPath();g.moveTo(X(a),py(ln[1]+sl*(a-i1)));g.lineTo(X(xr),py(ln[1]+sl*(xr-i1)));g.stroke();g.setLineDash([]);g.lineWidth=1;g.fillStyle=col;[[i1,ln[1]],[i2,ln[3]]].forEach(([ii,pp])=>{g.beginPath();g.arc(X(ii),py(pp),3.5,0,6.3);g.fill()})};
  S.hand.items.forEach(st=>{const col={channel:'#58a6ff',range:'#f0883e',triangle:'#d2a8ff'}[st.kind]||'#58a6ff';seg(st.A,col,false);seg(st.B,col,true);
   const ie=Math.max(ixf(st.A[2]),ixf(st.B[2]));g.fillStyle=col;g.font='bold 11px system-ui';g.textAlign='left';g.fillText('#'+st.id+' '+({channel:'канал',range:'флэт',triangle:'треугольник'}[st.kind]),cl(X(ie)+6,L+4,L+plotW-80),py(Math.max(st.A[3],st.B[3]))-10)});
  const tix={};D.t.forEach((t,i)=>{tix[t]=i});g.font='bold 11px system-ui';g.textAlign='center';
  if(S.hand.on&&!S.hand.tool)S.hand.items.forEach(st=>{const A=st.A,B=st.B,hk=st.kind==='channel'?[['A1',A[0],A[1]],['A2',A[2],A[3]],['B2',B[2],B[3]]]:st.kind==='triangle'?[['A1',A[0],A[1]],['A2',A[2],A[3]],['B1',B[0],B[1]],['B2',B[2],B[3]]]:[['A1',A[0],A[1]],['B2',B[2],B[3]]];
   hk.forEach(([key,t,p])=>{const x=X(ixf(t)),y=py(p);G.handles.push({sid:st.id,key:key,x:x,y:y});g.strokeStyle='#fff';g.lineWidth=2;g.fillStyle='rgba(13,17,23,.85)';g.beginPath();g.arc(x,y,8,0,6.3);g.fill();g.stroke();g.lineWidth=1})});
  S.hand.sigs.forEach(s=>{const i=tix[s.t];if(i==null||i<start||i>=end)return;const x=X(i),tx=s.kind==='b'?'мой отбой':'мой пробой';if(s.side==='L'){g.fillStyle='#00e676';g.fillText('⬆'+tx,x,py(D.l[i])+(S.opt.pv?64:54))}else{g.fillStyle='#ff1744';g.fillText('⬇'+tx,x,py(D.h[i])-(S.opt.pv?64:54))}});
  if((S.hand.tool==='channel'||S.hand.tool==='triangle')&&S.hand.pts.length>=2){const a=S.hand.pts[0],b2=S.hand.pts[1];seg([a.t,a.p,b2.t,b2.p],'#ffd600',false)}
  S.hand.pts.forEach((q,k)=>{const i=ixf(q.t);g.fillStyle='#ffd600';g.beginPath();g.arc(X(i),py(q.p),6,0,6.3);g.fill();g.fillStyle='#000';g.font='bold 9px system-ui';g.textAlign='center';g.fillText(String(k+1),X(i),py(q.p)+0.5)});
  g.restore()}
 if(S.opt.pt){g.textAlign='center';g.font='bold 9px system-ui';D.patterns.forEach(p=>{if(p.i<start||p.i>=end)return;const x=X(p.i);
  const col=p.d>0?'#3fb950':p.d<0?'#f85149':'#8b949e';g.fillStyle=col;
  if(p.d>0)g.fillText('▲'+p.c,x,py(D.l[p.i])+(S.opt.pv?24:14));else g.fillText(p.c+(p.d<0?'▼':''),x,py(D.h[p.i])-(S.opt.pv?24:14))});g.font='10px system-ui'}
 // labels
 if(S.lab.items.length){const tix={};D.t.forEach((t,i)=>{tix[t]=i});S.lab.items.forEach(b=>{const i=tix[b.t];if(i==null||i<start||i>=end)return;const x=X(i);g.textAlign='center';g.font='bold 12px system-ui';
   if(b.kind==='L'){g.fillStyle='#00e676';g.fillText('▲ЛОНГ',x,py(D.l[i])+(S.opt.pv?40:30))}
   else if(b.kind==='S'){g.fillStyle='#ff1744';g.fillText('ШОРТ▼',x,py(D.h[i])-(S.opt.pv?40:30))}
   else{g.fillStyle='#ffd600';g.fillText('■ВЫХОД',x,py(D.c[i]))}});g.font='10px system-ui'}
 // last price
 G.tm=null;const lp=live?live.c:D.c[N-1],lc=lp>=(live?live.o:D.o[N-1])?'#26a69a':'#ef5350';
 if(lp>=lo&&lp<=hi){g.strokeStyle=lc;g.setLineDash([2,3]);g.beginPath();g.moveTo(L,py(lp));g.lineTo(L+plotW,py(lp));g.stroke();g.setLineDash([]);
  g.fillStyle=lc;g.fillRect(L+plotW+1,py(lp)-7,R-2,14);g.fillStyle='#fff';g.textAlign='left';g.fillText(fmt(lp),L+plotW+4,py(lp));G.tm={x:L+plotW+1,y:py(lp)+8,w:R-2,col:lc,close:live?live.t+stepMs:D.t[N-1]+2*stepMs};paintTm(g)}
 // ---- volume
 if(P.vol){const p=P.vol;let mv=1e-9;for(let i=start;i<endV;i++)mv=Math.max(mv,A('v',i));
  for(let i=start;i<endV;i++){const up=A('c',i)>=A('o',i),h=(A('v',i)/mv)*(p.y1-p.y0-8);g.fillStyle=up?'rgba(38,166,154,.55)':'rgba(239,83,80,.55)';g.fillRect(X(i)-Math.max(1,bw*0.7)/2,p.y1-h,Math.max(1,bw*0.7),h)}
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('Vol',6,p.y0+10)}
 // ---- rsi
 if(P.rsi){const p=P.rsi,ry=v=>p.y0+4+(100-v)/100*(p.y1-p.y0-8);
  g.strokeStyle='#30363d';g.setLineDash([3,3]);[30,70].forEach(v=>{g.beginPath();g.moveTo(L,ry(v));g.lineTo(L+plotW,ry(v));g.stroke()});g.setLineDash([]);
  g.strokeStyle='#d2a8ff';g.lineWidth=1.3;g.beginPath();let on=false;for(let i=start;i<Math.min(end,N);i++){const v=D.rsi[i];if(v==null)continue;const x=X(i);if(!on){g.moveTo(x,ry(v));on=true}else g.lineTo(x,ry(v))}g.stroke();g.lineWidth=1;
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('RSI14',6,p.y0+10);g.fillText('70',L+plotW+4,ry(70));g.fillText('30',L+plotW+4,ry(30))}
 // ---- macd
 if(P.macd){const p=P.macd;let mx=1e-12;for(let i=start;i<Math.min(end,N);i++){[D.macd[i],D.sig[i],D.hist[i]].forEach(v=>{if(v!=null)mx=Math.max(mx,Math.abs(v))})}
  const my=v=>p.y0+4+(1-v/mx)/2*(p.y1-p.y0-8);g.strokeStyle='#30363d';g.beginPath();g.moveTo(L,my(0));g.lineTo(L+plotW,my(0));g.stroke();
  for(let i=start;i<Math.min(end,N);i++){const v=D.hist[i];if(v==null)continue;g.fillStyle=v>=0?'rgba(38,166,154,.6)':'rgba(239,83,80,.6)';const a=my(v),b=my(0);g.fillRect(X(i)-Math.max(1,bw*0.7)/2,Math.min(a,b),Math.max(1,bw*0.7),Math.abs(a-b))}
  [['macd','#58a6ff'],['sig','#f0883e']].forEach(([k,c])=>{g.strokeStyle=c;g.beginPath();let on=false;for(let i=start;i<Math.min(end,N);i++){const v=D[k][i];if(v==null)continue;const x=X(i);if(!on){g.moveTo(x,my(v));on=true}else g.lineTo(x,my(v))}g.stroke()});
  g.fillStyle='#6e7681';g.textAlign='left';g.fillText('MACD',6,p.y0+10)}
 // ---- time axis
 g.fillStyle='#6e7681';g.textAlign='center';g.textBaseline='middle';const step=Math.max(1,Math.round(S.n/6));let lastDay=-1;
 for(let i=start;i<end;i+=step){const t=tAt(i),d=new Date(t).getDate();g.fillText(fts(t,D.tf,d!==lastDay&&D.tf!=='1d'),X(i),H-7);lastDay=d}
 // ---- crosshair
 let hv=S.hover;if(hv>=start&&hv<end){const x=X(hv);g.strokeStyle='rgba(201,209,217,.4)';g.setLineDash([3,3]);g.beginPath();g.moveTo(x,0);g.lineTo(x,H-B);g.stroke();g.setLineDash([])}else hv=-1;
 info(hv>=0?hv:total-1);
}
function info(i){
 const D=S.D,N=D.t.length,live=D.live,isl=i>=N;const A=(k)=>isl?live[k]:D[k][i];
 const o=A('o'),h=A('h'),l=A('l'),c=A('c'),v=A('v'),ch=(c/o-1)*100;
 let s=D.sym+' '+D.tf+' '+fts(isl?live.t:D.t[i],D.tf,true)+(isl?' (live)':'')+'  O '+fmt(o)+' H '+fmt(h)+' L '+fmt(l)+' C '+fmt(c)+' ('+(ch>=0?'+':'')+ch.toFixed(2)+'%)  V '+v.toFixed(0);
 if(!isl){s+='  | EMA20 '+fmt(D.ema20[i])+' EMA50 '+fmt(D.ema50[i])+' EMA200 '+fmt(D.ema200[i])+' RSI '+(D.rsi[i]!=null?D.rsi[i].toFixed(1):'—');
  const ps=D.patterns.filter(p=>p.i===i);if(ps.length)s+='  | '+ps.map(p=>p.n).join(', ')}
 $('info').textContent=s;
}
// ---- interaction: жесты и кнопки (масштаб по горизонтали и вертикали, сдвиг в будущее, рисование линий)
const cv=$('c'),ptrs=new Map();let g0=null;
const pxy=e=>{const r=cv.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}};
const zoneAt=(x,y)=>x>G.L+G.plotW?'price':(y>G.H-G.B-2&&y<=G.H)?'time':'plot';
const idxAt=x=>cl(Math.floor(G.raw+(x-G.L)/G.bw),0,G.total-1);
function ptAt(x,y){const D=S.D,N=D.t.length;let kind='free';let i=Math.round(G.raw+(x-G.L)/G.bw-0.5),p=G.hi-(y-G.my0-6)/(G.my1-G.my0-12)*(G.hi-G.lo);
 if(i>=0&&i<G.total){const A=k=>i<N?D[k][i]:D.live[k];let best=14;['h','l','o','c'].forEach(k=>{const v=A(k),yy=G.my0+6+(G.hi-v)/(G.hi-G.lo)*(G.my1-G.my0-12);if(Math.abs(yy-y)<best){best=Math.abs(yy-y);p=v;kind=k}})}
 return{t:i<N?D.t[Math.max(0,i)]:D.t[N-1]+(i-N+1)*G.stepMs,p:p,i:i,k:kind}}
function chanB(A,tb,p){const sl=(A[3]-A[1])/(A[2]-A[0]),ln=t=>A[1]+sl*(t-A[0]),off=p-ln(tb),ta=tb===A[0]?A[2]:A[0];return[ta,ln(ta)+off,tb,p]}
function applyHandle(dr,x,y){const it=S.hand.items.find(z=>z.id===dr.sid);if(!it)return;const o=dr.orig,pt=ptAt(x,y);
 if(o.kind==='channel'){
  if(dr.key==='A1'||dr.key==='A2'){const A=o.A.slice(),slo=(o.A[3]-o.A[1])/(o.A[2]-o.A[0]),off=o.B[3]-(o.A[1]+slo*(o.B[2]-o.A[0]));if(dr.key==='A1'){A[0]=pt.t;A[1]=pt.p}else{A[2]=pt.t;A[3]=pt.p}if(A[0]===A[2])return;const sln=(A[3]-A[1])/(A[2]-A[0]);it.A=A;it.B=chanB(A,o.B[2],A[1]+sln*(o.B[2]-A[0])+off)}
  else{it.B=chanB(o.A,pt.t,pt.p)}}
 else if(o.kind==='triangle'){const A=o.A.slice(),B=o.B.slice();if(dr.key==='A1'){A[0]=pt.t;A[1]=pt.p}else if(dr.key==='A2'){A[2]=pt.t;A[3]=pt.p}else if(dr.key==='B1'){B[0]=pt.t;B[1]=pt.p}else{B[2]=pt.t;B[3]=pt.p}if(A[0]===A[2]||B[0]===B[2])return;it.A=A;it.B=B}
 else{let t1=o.A[0],t2=o.A[2],up=o.A[1],lo=o.B[1];if(dr.key==='A1'){t1=pt.t;up=pt.p}else{t2=pt.t;lo=pt.p}if(t1===t2)return;if(up<lo){const q=up;up=lo;lo=q}it.A=[t1,up,t2,up];it.B=[t1,lo,t2,lo]}}
cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);const q=pxy(e);ptrs.set(e.pointerId,q);
 if(ptrs.size===1){g0={x:q.x,y:q.y,off:S.off,vo:S.vo,vz:S.vz,n:S.n,zone:zoneAt(q.x,q.y),moved:false};
  if(S.hand.on&&!S.hand.tool&&g0.zone==='plot'){let bd=22,hit=null;(G.handles||[]).forEach(h=>{const d=Math.hypot(h.x-q.x,h.y-q.y);if(d<bd){bd=d;hit=h}});if(hit){const it=S.hand.items.find(z=>z.id===hit.sid);g0.drag={sid:hit.sid,key:hit.key,orig:JSON.parse(JSON.stringify(it))}}}}
 else if(ptrs.size===2&&g0){const a=[...ptrs.values()];g0.pinch={dx:Math.abs(a[0].x-a[1].x),dy:Math.abs(a[0].y-a[1].y),n:S.n,vz:S.vz};g0.moved=true}});
cv.addEventListener('pointermove',e=>{const q=pxy(e);
 if(!ptrs.has(e.pointerId)){if(e.pointerType==='mouse'&&S.D){S.hover=idxAt(q.x);draw()}return}
 ptrs.set(e.pointerId,q);if(!g0||!S.D)return;
 if(ptrs.size===2&&g0.pinch){const a=[...ptrs.values()],dx=Math.abs(a[0].x-a[1].x),dy=Math.abs(a[0].y-a[1].y);
  if(g0.pinch.dy>g0.pinch.dx*1.2){S.vz=g0.pinch.vz*Math.max(dy,10)/Math.max(g0.pinch.dy,10)}else{S.n=Math.round(g0.pinch.n*Math.max(g0.pinch.dx,10)/Math.max(dx,10))}draw();return}
 const dx=q.x-g0.x,dy=q.y-g0.y;if(Math.abs(dx)>5||Math.abs(dy)>5)g0.moved=true;if(!g0.moved)return;
 if(g0.drag){applyHandle(g0.drag,q.x,q.y);draw();return}
 if(g0.zone==='price')S.vz=g0.vz*Math.exp(-dy/120);
 else if(g0.zone==='time')S.n=Math.round(g0.n*Math.exp(-dx/120));
 else{S.off=Math.round(g0.off+dx/G.bw);S.vo=g0.vo+dy*G.pxVo}
 draw()});
const up=e=>{const q=ptrs.get(e.pointerId)||pxy(e);
 if(ptrs.size===1&&g0&&g0.drag&&g0.moved){const it=S.hand.items.find(z=>z.id===g0.drag.sid);if(it)handPost({action:'update',id:it.id,sym:S.sym,tf:S.tf,A:it.A,B:it.B})}
 else if(ptrs.size===1&&g0&&!g0.moved&&S.D){if(S.hand.on&&S.hand.tool&&g0.zone==='plot')handTap(q.x,q.y);else{S.hover=idxAt(q.x);draw()}}
 ptrs.delete(e.pointerId);if(!ptrs.size)g0=null};
cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',e=>{ptrs.delete(e.pointerId);if(!ptrs.size)g0=null});
cv.addEventListener('wheel',e=>{e.preventDefault();const f=e.deltaY>0?1.15:0.87;if(e.shiftKey)S.vz=S.vz/f;else if(e.altKey)S.off+=(e.deltaY>0?1:-1)*Math.max(1,Math.round(S.n*0.1));else S.n=Math.round(S.n*f);draw()},{passive:false});
window.addEventListener('resize',draw);
(async()=>{try{const r=await fetch('/api/pairs');S.pairs=(await r.json()).pairs;if(!S.pairs.includes(S.sym))S.sym=S.pairs[0]}catch(e){S.pairs=[S.sym]}
 mk();load();loadMtf();setInterval(load,10000);setInterval(loadMtf,60000);setInterval(()=>{if(S.D&&G.tm)paintTm($('c').getContext('2d'))},1000)})();
</script></body></html>'''


async def serve():
    global SES
    SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    _rt_load()
    asyncio.create_task(refresher())
    asyncio.create_task(manual_loop())
    asyncio.create_task(screen_loop())
    app1 = web.Application()
    app1.router.add_get("/", index)
    app1.router.add_get("/api/chart", api_chart)
    app1.router.add_get("/api/mtf", api_mtf)
    app1.router.add_route("*", "/api/pairs", api_pairs)
    app1.router.add_route("*", "/api/labels", api_labels)
    app1.router.add_route("*", "/api/hand", api_hand)
    app2 = web.Application()
    app2.router.add_get("/", pos_index)
    app2.router.add_get("/api/trades", api_trades)
    app2.router.add_route("*", "/api/pairs", api_pairs)
    app2.router.add_route("*", "/api/config", api_config)
    app2.router.add_route("*", "/api/runs", api_runs)
    app2.router.add_route("*", "/api/cand", api_cand)
    app2.router.add_get("/api/prop_chart", api_prop_chart)
    app2.router.add_route("*", "/api/screen", api_screen)
    for app, port in ((app1, PORT), (app2, PORT2)):
        r = web.AppRunner(app)
        await r.setup()
        await web.TCPSite(r, "127.0.0.1", port).start()
    await asyncio.Event().wait()


def main():
    asyncio.run(serve())


if __name__ == "__main__":
    main()
