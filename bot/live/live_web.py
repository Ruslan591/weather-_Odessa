# -*- coding: utf-8 -*-
"""live_web: живая страница бота по WebSocket. ТОЛЬКО ЧТЕНИЕ: ничего не пишет, торговых команд не принимает.
Источники: POS_DIR (orders.json, tg_watch.json, decisions.jsonl, tg_*.json), acct-api (GET /api/claude), цены Binance (публичный поток, ретрансляция).
Вход: Telegram Mini App (подпись initData по токену бота и TG_USER_ID) или секретная ссылка (token.txt). Не больше 3 подключений.
Настройки: порт LIVE_PORT (18110), Caddy проксирует /live* на него. docs/topics/live_web.md"""
import asyncio, collections, hashlib, hmac, json, os, time, urllib.parse
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType

POS = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
PORT = int(os.environ.get("LIVE_PORT", "18110"))
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = "http://127.0.0.1:%s/api/claude" % os.environ.get("ACCT_PORT", "18102")
BWS = "wss://data-stream.binance.vision/stream"
REST = "https://data-api.binance.vision/api/v3/ticker/price"
MAXC = 3


def _env():
    d = {}
    try:
        for l in open(os.environ.get("TG_ENV", "/opt/trading-bot/tg.env"), encoding="utf-8"):
            l = l.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    except Exception: pass
    return d


ENV = _env(); BOT = ENV.get("TG_TOKEN", ""); UID = str(ENV.get("TG_USER_ID", ""))
try: TOK = open(os.path.join(HERE, "token.txt"), encoding="utf-8").read().strip()
except Exception: TOK = ""

PX = {}; BTCK = {}; DIRTY = set(); CL = set(); EVT = collections.deque(maxlen=120); NEW = []
ST = {"state": None, "sig": None, "syms": set()}; FAILS = {}; CACHE = {}; OSEEN = {}; DEC = {"pos": None, "buf": b""}; BASE = {"orders": False}


def log(m): print("%s %s" % (time.strftime("%m-%d %H:%M:%S", time.gmtime()), m), flush=True)


# ---------- вход ----------
def check_init(init):
    try:
        q = dict(urllib.parse.parse_qsl(init, keep_blank_values=True))
        h = q.pop("hash", "")
        dcs = "\n".join("%s=%s" % (k, q[k]) for k in sorted(q))
        key = hmac.new(b"WebAppData", BOT.encode(), hashlib.sha256).digest()
        if not BOT or not hmac.compare_digest(hmac.new(key, dcs.encode(), hashlib.sha256).hexdigest(), h): return False
        if time.time() - int(q.get("auth_date", "0")) > 86400: return False
        return bool(UID) and str(json.loads(q.get("user", "{}")).get("id")) == UID
    except Exception: return False


def check_tok(t): return bool(TOK) and hmac.compare_digest(str(t), TOK)


def n_fails(ip):
    now = time.time(); FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < 600]; return len(FAILS[ip])


# ---------- данные ----------
def jl(name):
    p = os.path.join(POS, name)
    try: s = os.stat(p); ver = (s.st_mtime_ns, s.st_size)
    except OSError: return None
    c = CACHE.get(name)
    if c and c[0] == ver: return c[1]
    try: d = json.load(open(p, encoding="utf-8"))
    except Exception: return c[1] if c else None
    if name == "orders.json" and isinstance(d, list): d = d[-400:]     # файл на МБ, нужны только свежие ордера
    CACHE[name] = (ver, d); return d


def ev(t, k, x, s="", new=True):
    e = {"t": int(t), "k": k, "x": x, "s": s}; EVT.append(e)
    if new: NEW.append(e)


def fmt_dec(d):
    k = str(d.get("kind") or ""); a = str(d.get("action") or "")
    bits = [("%s/%s" % (k, a)) if a else k, str(d.get("sym") or ""), str(d.get("side") or "")]
    for key in ("reason_text", "reason", "setup", "entry", "price"):
        v = d.get(key)
        if v not in (None, ""): bits.append("%s=%s" % (key, str(v)[:60]))
    return " ".join(b for b in bits if b)[:200]


def tail_decisions():
    p = os.path.join(POS, "decisions.jsonl")
    try: size = os.path.getsize(p)
    except OSError: return
    first = DEC["pos"] is None
    if first: start = max(0, size - 80000)
    else:
        start = DEC["pos"]
        if size < start: start = 0; DEC["buf"] = b""
        if size == start: return
    with open(p, "rb") as f:
        f.seek(start); data = f.read(min(size - start, 400000))
    DEC["pos"] = start + len(data)
    lines = (DEC["buf"] + data).split(b"\n"); DEC["buf"] = lines.pop()
    if first and start > 0 and lines: lines.pop(0)
    for l in lines[-200:]:
        try: d = json.loads(l)
        except Exception: continue
        ev(d.get("t") or time.time() * 1000, "dec", fmt_dec(d), str(d.get("sym") or ""), new=not first)


OPEN_F = ("id", "sym", "side", "entry", "stop", "stop0", "tp", "R", "stake", "lev", "t_in", "armed", "be_px")
CLOSED_F = ("id", "sym", "side", "net_pct", "r_mult", "pnl_usd", "reason", "t_out", "entry", "exit")
ORD_F = ("id", "sym", "side", "price", "stop", "tp", "atr", "line_px", "live1m", "live1m_tries", "rule", "approved_t", "placed_t", "setup")


def derive(snap):
    orders = jl("orders.json") or []; W = jl("tg_watch.json") or {}
    b1 = jl("tg_btc1m_last.json"); reg = jl("tg_regime.json"); sl = jl("tg_slots.json"); mode = jl("tg_mode.json"); lc = jl("tg_live1m.json") or {}
    now = int(time.time() * 1000)
    pend = [{k: o.get(k) for k in ORD_F} for o in orders if o.get("status") == "pending"][-20:]
    for o in orders[-80:]:
        if not str(o.get("rule", "")).startswith("tg_"): continue
        l1 = o.get("live1m") or {}; sig = (o.get("status"), o.get("live1m_tries"), l1.get("ok")); old = OSEEN.get(o["id"]); OSEEN[o["id"]] = sig
        if old is None or old == sig or not BASE["orders"]: continue
        nm = "#%s %s %s" % (o["id"], o.get("sym"), str(o.get("side", "")).upper())
        if old[0] != sig[0]:
            st = o.get("status")
            ev(now, "ord", "Ордер %s: %s%s" % (nm, {"cancelled": "отменён", "expired": "истёк", "filled": "исполнен"}.get(st, str(st)), (" - %s" % o.get("reason")) if o.get("reason") else ""), o.get("sym"))
        elif l1.get("ok") == 0:
            bo, bc = l1.get("o"), l1.get("c")
            ev(now, "l1m", "⏳ %s: свеча BTC 1m не по ходу (%+.3f%%), попытка %s" % (nm, (bc / bo - 1) * 100 if bo else 0, o.get("live1m_tries")), o.get("sym"))
        elif l1.get("ok") == 1:
            ev(now, "l1m", "✅ %s: свеча BTC 1m по ходу, вход открыт (попытка %s)" % (nm, o.get("live1m_tries")), o.get("sym"))
    BASE["orders"] = True
    watch = []
    for w in W.get("items", []):
        if w.get("status") in ("alert", "watching"):
            L = w.get("last") or {}; line = L.get("Rn") if w.get("line") == "upper" else L.get("Sn")
            watch.append({"id": w["id"], "sym": w["sym"], "side": w.get("side"), "line": w.get("line"), "lp": line if line is not None else w.get("line_px"),
                          "atr": L.get("atr") or w.get("atr"), "state": w.get("state"), "nb": w.get("n_beyond"), "ct": w.get("ctype"), "st": w.get("status"), "upd": w.get("updates"), "tf": w.get("t_follow") or w.get("created")})
    watch = watch[-20:]
    s = snap if isinstance(snap, dict) else {}
    st = {"t": "state", "acc": s.get("account"), "open": [{k: p.get(k) for k in OPEN_F} for p in (s.get("open") or [])],
          "closed": [{k: p.get(k) for k in CLOSED_F} for p in (s.get("closed") or [])[-8:]], "pend": pend, "watch": watch,
          "b1": b1, "reg": reg, "slots": sl, "mode": mode, "mx": float(lc.get("max_dist_atr", 0.9)) if lc.get("enabled", True) else None}
    syms = {"BTCUSDT"} | {p["sym"] for p in st["open"]} | {o["sym"] + "USDT" for o in pend} | {w["sym"] + "USDT" for w in watch}
    return st, set(list(syms)[:30])


# ---------- рассылка ----------
async def bcast(msg):
    if not CL: return
    s = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
    for ws in list(CL):
        try: await asyncio.wait_for(ws.send_str(s), 2)
        except Exception:
            CL.discard(ws); asyncio.ensure_future(ws.close())


async def state_loop(app):
    sess = app["sess"]; loop = asyncio.get_running_loop(); nxt = 0; snap = None
    while True:
        try:
            if time.time() >= nxt:
                nxt = time.time() + 3
                try:
                    async with sess.get(SNAP) as r: snap = await r.json()
                except Exception as e: log("snap: %s" % e)
            await loop.run_in_executor(None, tail_decisions)
            st, syms = await loop.run_in_executor(None, derive, snap)
            ST["syms"] = syms; sig = json.dumps(st, sort_keys=True, ensure_ascii=False, default=str)
            if sig != ST["sig"]: ST["sig"] = sig; ST["state"] = st; await bcast(dict(st, srv=int(time.time() * 1000)))
            while NEW: await bcast({"t": "evt", "e": NEW.pop(0)})
            miss = [s for s in syms if s not in PX]
            if miss:
                try:
                    async with sess.get(REST, params={"symbols": json.dumps(miss, separators=(",", ":"))}) as r:
                        for x in await r.json():
                            if isinstance(x, dict) and "price" in x: PX[x["symbol"]] = float(x["price"]); DIRTY.add(x["symbol"])
                except Exception: pass
        except Exception as e: log("state_loop: %s" % e)
        await asyncio.sleep(1)


async def px_loop(app):
    last = None
    while True:
        await asyncio.sleep(0.2)
        if not CL: DIRTY.clear(); continue
        if DIRTY or BTCK.get("c") != last:
            p = {s: PX[s] for s in list(DIRTY) if s in PX}; DIRTY.clear(); last = BTCK.get("c")
            await bcast({"t": "px", "p": p, "k": BTCK, "srv": int(time.time() * 1000)})


async def binance_loop(app):
    sess = app["sess"]; back = 1
    while True:
        try:
            async with sess.ws_connect(BWS, heartbeat=20, receive_timeout=60) as ws:
                back = 1; subs = set(); last = 0
                while True:
                    if time.time() - last > 2:
                        last = time.time(); want = {"btcusdt@kline_1m"} | {s.lower() + "@aggTrade" for s in ST["syms"]}
                        add = sorted(want - subs); rem = sorted(subs - want)
                        if rem: await ws.send_json({"method": "UNSUBSCRIBE", "params": rem, "id": 1})
                        if add: await ws.send_json({"method": "SUBSCRIBE", "params": add, "id": 2})
                        subs = want
                    try: m = await ws.receive(timeout=2)
                    except asyncio.TimeoutError: continue
                    if m.type == WSMsgType.TEXT:
                        d = (json.loads(m.data) or {}).get("data") or {}
                        if d.get("e") == "aggTrade": PX[d["s"]] = float(d["p"]); DIRTY.add(d["s"])
                        elif d.get("e") == "kline":
                            k = d["k"]; BTCK.update(o=float(k["o"]), c=float(k["c"]), h=float(k["h"]), l=float(k["l"]), t=k["t"]); PX["BTCUSDT"] = float(k["c"]); DIRTY.add("BTCUSDT")
                    elif m.type in (WSMsgType.CLOSED, WSMsgType.CLOSING, WSMsgType.ERROR): break
        except Exception as e: log("binance ws: %s" % e)
        await asyncio.sleep(back); back = min(30, back * 2)


# ---------- HTTP ----------
async def index(req):
    try: html = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    except Exception: return web.Response(status=500, text="no page")
    csp = "default-src 'none'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'unsafe-inline'; connect-src 'self' wss://%s; img-src data:; frame-ancestors 'self' https://*.telegram.org https://web.telegram.org" % req.host
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store", "Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


async def ws_handler(req):
    ip = (req.headers.get("X-Forwarded-For") or req.remote or "?").split(",")[0].strip()
    org = req.headers.get("Origin")
    if org and urllib.parse.urlparse(org).netloc != req.host: return web.Response(status=403)
    if len(CL) >= MAXC: return web.Response(status=503)
    if n_fails(ip) >= 8: return web.Response(status=429)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8192); await ws.prepare(req); ok = False
    try:
        m = await asyncio.wait_for(ws.receive(), 8)
        a = json.loads(m.data) if m.type == WSMsgType.TEXT else {}
        ok = check_init(a["init"]) if a.get("init") else check_tok(a.get("tok", ""))
    except Exception: ok = False
    if not ok:
        FAILS.setdefault(ip, []).append(time.time()); log("deny %s" % ip)
        try: await ws.send_json({"t": "deny"})
        except Exception: pass
        await ws.close(); return ws
    CL.add(ws)
    try:
        await ws.send_str(json.dumps({"t": "hello", "state": ST["state"], "px": PX, "k": BTCK, "evt": list(EVT)[-80:], "srv": int(time.time() * 1000)}, ensure_ascii=False, default=str))
        async for _ in ws: pass
    finally: CL.discard(ws)
    return ws


async def on_start(app):
    app["sess"] = ClientSession(timeout=ClientTimeout(total=15))
    app["tasks"] = [asyncio.ensure_future(f(app)) for f in (state_loop, px_loop, binance_loop)]


async def on_stop(app):
    for t in app["tasks"]: t.cancel()
    await app["sess"].close()


def make_app():
    app = web.Application(); app.on_startup.append(on_start); app.on_cleanup.append(on_stop)
    app.router.add_get("/live", lambda r: web.HTTPFound("/live/")); app.router.add_get("/live/", index); app.router.add_get("/live/ws", ws_handler)
    app.router.add_get("/live/health", lambda r: web.Response(text="ok"))
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=PORT, print=None)
