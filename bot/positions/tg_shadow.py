# -*- coding: utf-8 -*-
"""tg_shadow.py v2 -- «теневые» бумажные сделки по пропущенным сигналам «ЗАХОДИТЬ». Бот делает то, что сделали бы вы, нажав «Выставить ордер» (вход по рынку), но на счёт это не влияет.

Что делает тень (всё боевым кодом счёта, ничего не переписано):
  1. Сигнал: пост экспресса с мнением «заходить», по которому Автоордер ордер не ставит (tg_bot.send_watch -> record). Что бы поставил Автоордер (сетап, цель), то ставит и тень (ao_pick).
  2. Ордер строит chan_orders._tg_mkorder (те же формулы входа, стопа, цели, что у вашего ордера из слежения).
  3. Фильтр входа: chan_orders._live1m_gate один в один: свеча 1m САМОЙ ПАРЫ в момент входа должна идти по ходу сделки, иначе ждём (до 10 минут), цена ушла от линии дальше max_dist_atr (tg_live1m.json) -> не входим,
     цель слишком близко -> не входим. Настройки читаются из того же tg_live1m.json, поэтому изменение фильтра для вас меняет и тень.
  4. Позиция: те же поля, что при исполнении вашего ордера (стоп по настройкам счёта exit_cfg, комиссии, правило flat_brk), сопровождение pos.step по минутным свечам (БУ, частичная цель, трейлинг, S/R, время, ликвидация) по настройкам счёта.
  5. Отфильтрованный сигнал ведётся «вхолостую» по плану (без фильтра), чтобы потом видеть, чего стоил фильтр (поле cf).
Тень НЕ трогает счёт: не пишет orders.json, positions.json, decisions.jsonl, не занимает слоты, не меняет баланс и пороги самообучения. Только читает свечи и общие настройки.
Если по этому слежению вы всё же поставили реальный ордер (orders.json, src_watch), тень снимается (taken).

Файлы в POS_DIR: shadow.json {seq, items[], msg{}} (пишет только tg_bot через этот модуль), shadow_paths.jsonl (ход цены по 5m в R для каждой закрытой), shadow_cfg.json {"enabled", "max_wait_min", "max_open", "keep_closed", "path", "cf"}.
Отключение: shadow_cfg.json {"enabled": false} или удалить этот файл. Если боевой код недоступен (SHADOW_CODE_DIR, по умолчанию /opt/trading-bot/positions), тень ничего не делает и пишет причину в журнал."""
import copy, json, math, os, re, sys, threading, time, urllib.parse, urllib.request

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CODE = os.environ.get("SHADOW_CODE_DIR", "/opt/trading-bot/positions")
QF = os.path.join(D, "shadow_in.jsonl"); QOFF = os.path.join(D, "shadow_in.off"); NF = os.path.join(D, "shadow_notes.jsonl")
F = os.path.join(D, "shadow.json"); PF = os.path.join(D, "shadow_paths.jsonl"); ORDF = os.path.join(D, "orders.json"); CFGF = os.path.join(D, "shadow_cfg.json")
KL = "https://data-api.binance.vision/api/v3/klines"
DEF = {"enabled": True, "max_wait_min": 10, "keep_closed": 300, "path": True, "cf": True, "b_enabled": True, "b_post": False, "reg_k": 2.0, "tfs": ["5m"]}      # tfs: на каких таймфреймах ведутся тени (пока только 5m: решение пользователя 20.11, выше 5m входы остановлены)      # число одновременных теней не ограничено (не привязаны к балансу и слотам)
TFMS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
REG_LO, REG_HI, REG_FLAT = 40, 350, 0.03      # как chan_src (регрессионный канал: окно 40..350 свечей по максимуму |r|)
WK = ("id", "sym", "side", "line", "ctype", "t_alert", "updates", "tf", "last", "chan")      # поля слежения, нужные для _tg_mkorder
lock = threading.RLock()
S = {"loaded": False, "seq": 0, "nseq": 0, "items": [], "msg": {}}
_E = [None]            # боевой код: None - не пробовали, False - не загрузился, dict - модули
_CUR = [None]          # (рабочая копия записи, "p" | "cf") на время шага движка: сюда hook пишет события сопровождения
_log_once = set()


def num(it): return int(it.get("sn") or it["id"])      # показываемый номер сигнала (поле sn; старое поле n других записей это не оно)
def tag(it): return "%s%s" % (num(it), "B" if it.get("var") == "B" else "")      # показываемый номер: 42 или 42B


def tags(ids):
    """Показываемые номера по внутренним id (для подтверждения заметки): 61 -> 61, 62 -> 61B."""
    with lock:
        _load(); by = {i["id"]: i for i in S["items"]}
    out = []
    for x in ids:
        t = tag(by[x]) if x in by else str(x)
        if t not in out: out.append(t)
    return out


def log(m): print(time.strftime("%H:%M:%S"), "shadow:", m, flush=True)
def log_once(k, m):
    if k not in _log_once: _log_once.add(k); log(m)


def cfg():
    c = dict(DEF)
    try: c.update(json.load(open(CFGF, encoding="utf-8")))
    except Exception: pass
    return c


def enabled(): return bool(cfg().get("enabled", True))
def now_ms(): return int(time.time() * 1000)
def _f(x):
    try: return float(x)
    except Exception: return None
def _clean(x):
    try: return json.loads(json.dumps(x, ensure_ascii=False, default=str))
    except Exception: return None


# ---------- боевой код счёта ----------
def _hook(p, kind, old, new, t, c, **kw):
    """Подмена decisions.auto: события сопровождения тени идут в запись тени, а не в журнал решений счёта."""
    cur = _CUR[0]
    if cur and cur[1] == "p":
        e = {"t": int(t), "k": kind, "old": old, "new": new, "px": c}
        for k, v in kw.items():
            if isinstance(v, (int, float, str)): e[k] = v
        cur[0].setdefault("ev", []).append(e)


def eng():
    """Загружает боевой код (pos, exit_cfg, decisions, chan_orders) из SHADOW_CODE_DIR. Возвращает dict модулей или None."""
    if _E[0] is not None: return _E[0] or None
    try:
        for k_, v_ in (("CHAN_SRC", "regr"), ("CHAN_EDGE", "1"), ("TG_GATE", "1")): os.environ.setdefault(k_, v_)     # как у сервиса chan-orders-regr (источник каналов, настройки ордеров)
        if CODE not in sys.path: sys.path.append(CODE)
        import pos, exit_cfg, decisions, chan_orders as CO
        sys.path[:] = [x for x in sys.path if os.path.abspath(x) != os.path.abspath(CODE)] + [CODE]     # chan_orders ставит свой каталог первым; наши модули должны искаться раньше
        decisions.auto = _hook                  # тень не пишет в журнал решений счёта
        CO._l1m_emit = lambda *a, **k: None     # проверка входа не шлёт события в посты настоящих ордеров
        CO.log = lambda m: None                 # и не пишет в chan.log (ход проверки хранится в записи: it["o"]["live1m"], it["g"])
        _E[0] = {"pos": pos, "exit_cfg": exit_cfg, "CO": CO}
    except Exception as e:
        _E[0] = False; log("боевой код недоступен (%s): тени отключены" % repr(e)[:200])
    return _E[0] or None


# ---------- хранение ----------
def _load():
    if S["loaded"]: return
    try:
        d = json.load(open(F, encoding="utf-8"))
        S["seq"] = int(d.get("seq", 0)); S["items"] = list(d.get("items") or []); S["msg"] = dict(d.get("msg") or {}); S["nseq"] = int(d.get("nseq", 0))
    except Exception: pass
    for it in S["items"]:     # записи первой версии (простая модель без боевого движка): архивные, движок и Telegram их не трогают, страница показывает; открытые снимаем
        if "o" not in it and "p" not in it and "t0" not in it:
            it["legacy"] = 1; it.setdefault("t0", it.get("t_in") or 0)
            if it.get("status") == "open": it["status"] = "void"; it["why"] = "модель v1 снята"
    byid = {}      # показываемый номер sn: у A это его id, у B номер его A (ref) с буквой B; записи без ref берут свой id
    for i in sorted(S["items"], key=lambda x: x["id"]):
        if not i.get("sn"): i["sn"] = (byid.get(i.get("ref")) or i.get("ref") or i["id"]) if i.get("var") == "B" else i["id"]
        byid[i["id"]] = i["sn"]
    S["nseq"] = max([0] + [int(i["sn"]) for i in S["items"]])      # следующий новый сигнал: nseq + 1, у A и B одного сигнала один номер без пропусков
    S["loaded"] = True


def _save():
    tmp = F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump({"seq": S["seq"], "nseq": S.get("nseq", 0), "items": S["items"], "msg": S["msg"]}, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, F)


def snapshot():
    """Копия записей для чтения (страница, Telegram)."""
    with lock: _load(); return copy.deepcopy([i for i in S["items"] if not i.get("legacy")])


def msg_get(iid):
    with lock: _load(); return dict(S["msg"].get(str(iid)) or {})


def msg_set(iid, **kw):
    with lock:
        _load(); m = S["msg"].setdefault(str(iid), {}); m.update(kw); _save()


# ---------- запись сигнала ----------
def record(w, V, Bk=None, mid=None, chat="main", ao=None, now=None):
    """Из tg_bot.send_watch после поста с мнением «заходить» без ордера Автоордера (и из очереди сканера других таймфреймов). ao = (setup, цель). Создаёт две тени: A (как ваш ручной вход) и B (то же + пробой канала регрессии свечи контроля по ходу сделки). Возвращает id записи A или None."""
    try:
        c = cfg()
        if not c.get("enabled", True) or not ao or not eng(): return None     # без боевого кода тень не создаётся
        kind, X = ("bounce", V) if (V and V.get("call") == "enter") else (("break", Bk) if (Bk and Bk.get("call") == "enter") else (None, None))
        if not X: return None
        p = X.get("plan") or {}; sym = str(w.get("sym") or "")
        if not sym or p.get("side") not in ("long", "short"): return None
        t0 = int(now or now_ms()); first = None
        with lock:
            _load()
            tf = str(w.get("tf") or X.get("tf") or "5m")
            if tf not in (c.get("tfs") or ["5m"]): return None      # таймфрейм не разрешён (shadow_cfg.json: tfs)
            nn = None
            for var in (("A", "B") if c.get("b_enabled", True) else ("A",)):
                if any(i.get("status") in ("gate", "open") and i.get("sym") == sym and i.get("side") == p["side"] and i.get("tf") == tf and (i.get("var") or "A") == var for i in S["items"]): continue     # одна открытая тень на пару, сторону, таймфрейм и вариант
                S["seq"] += 1
                if nn is None: S["nseq"] += 1; nn = S["nseq"]      # один номер на сигнал, у B та же цифра с буквой B (не раздуваем нумерацию)
                it = {"id": S["seq"], "sn": nn, "var": var, "sym": sym, "side": p["side"], "kind": kind, "tf": tf, "wid": w.get("id"), "mid": mid, "pchat": chat,
                      "t_sig": X.get("t"), "t0": t0, "status": "gate", "setup": ao[0], "target": ao[1], "plan": _clean({k: p.get(k) for k in ("entry", "stop", "tp", "rr", "f", "side")}),
                      "feat": _clean(X.get("feat")), "rows": _clean(X.get("rows")), "b1": _clean(X.get("b1")), "rg": _clean(X.get("rg")), "geo": _clean(X.get("geo")),
                      "w": _clean({k: w.get(k) for k in WK}), "o": None, "ev": []}
                if var == "B" and first: it["ref"] = first
                S["items"].append(it); first = first or it["id"]
                log("сигнал #%s%s %s %s %s %s (%s, цель %s)" % (it["sn"], var, sym, p["side"], kind, tf, ao[0], ao[1]))
            if first: _save()
        return first
    except Exception as e:
        log("record error: %r" % e); return None


def consume_queue():
    """Сигналы от сканера других таймфреймов (tg_shadow_scan.py пишет shadow_in.jsonl): читаем с сохранённой позиции."""
    try: off = int(open(QOFF).read().strip() or 0)
    except Exception: off = 0
    if cfg().get("scan", True) is False:      # сканер таймфреймов выключен: очередь не разбираем и не копим
        try: open(QF, "w").close(); open(QOFF, "w").write("0")
        except Exception: pass
        return 0
    try: sz = os.path.getsize(QF)
    except Exception: return 0
    if sz <= off: return 0
    n = 0
    with open(QF, "rb") as f:
        f.seek(off); data = f.read()
    end = data.rfind(b"\n")
    if end < 0: return 0
    for ln in data[:end + 1].decode("utf-8", "replace").splitlines():
        try:
            sg = json.loads(ln); w = dict(sg["w"]); w["id"] = None
            if record(w, sg.get("V"), sg.get("Bk"), None, "scan", tuple(sg["ao"]), sg.get("t")): n += 1
        except Exception as e: log("очередь: %r" % e)
    open(QOFF, "w").write(str(off + end + 1)); return n


# ---------- регрессия свечи контроля (как канал регрессии, наложенный на график) ----------
def reg_fit(c, atr_k, lo=REG_LO, hi=REG_HI, flat=REG_FLAT):
    """Порт chan_src.regression_at на чистом Python: окно L (lo..hi) с максимальным |r| по последним hi закрытиям; vk - значение линии на последней свече, slope - наклон на свечу, sd - разброс остатков."""
    n = len(c)
    if n < lo + 2: return None
    hn = min(hi, n); y = c[n - hn:][::-1]; Sx = Sxx = Sy = Sxy = Syy = 0.0; best = None
    for i in range(hn):
        x = float(i); v = y[i]; Sx += x; Sxx += x * x; Sy += v; Sxy += x * v; Syy += v * v; L = i + 1
        if L < lo: continue
        vx = Sxx - Sx * Sx / L; vy = Syy - Sy * Sy / L; cv = Sxy - Sx * Sy / L
        if vx <= 0 or vy <= 0: continue
        r = abs(cv) / math.sqrt(vx * vy)
        if best is None or r > best[0]: best = (r, L, vx, vy, cv, Sy)
    if not best: return None
    r, L, vx, vy, cv, Sy_ = best; rev = cv / vx; sse = max(vy - rev * cv, 0.0); sd = math.sqrt(sse / max(L - 2, 1)); slope = -rev; vk = Sy_ / L - rev * (L - 1) / 2.0
    th = flat * atr_k
    return {"win": L, "r": r, "slope": slope, "vk": vk, "sd": sd, "dir": 1 if slope > th else (-1 if slope < -th else 0)}


_KC = {}


def _klines_last(sym, iv, limit=400, ttl=20):
    """Последние свечи пары (кэш на ttl секунд: B и A по одной паре не дублируют запросы)."""
    key = (sym, iv, limit); c = _KC.get(key)
    if c and time.time() - c[0] < ttl: return c[1]
    q = urllib.parse.urlencode({"symbol": sym + "USDT", "interval": iv, "limit": limit})
    with urllib.request.urlopen(urllib.request.Request(KL + "?" + q, headers={"User-Agent": "tg-shadow"}), timeout=12) as r: d = json.loads(r.read().decode("utf-8"))
    _KC[key] = (time.time(), d)
    if len(_KC) > 200:
        for k_ in [k_ for k_, v_ in _KC.items() if time.time() - v_[0] > 120]: _KC.pop(k_, None)
    return d


def reg_info(sym, ctf, side, px, k=None, rows=None):
    """Канал регрессии свечей контроля (ctf) на момент px: линия на следующую свечу, полосы ±K·sd, z-оценка цены, пробой канала по ходу сделки (long: выше верхней, short: ниже нижней). None, если данных мало."""
    ms = TFMS.get(ctf, 60000); rows = rows or _klines_last(sym, ctf, 400); cl = [r for r in rows if int(r[0]) + ms <= now_ms()]
    if len(cl) < REG_LO + 15: return None
    c = [float(r[4]) for r in cl]; tr = [max(float(r[2]) - float(r[3]), abs(float(r[2]) - c[i - 1]), abs(float(r[3]) - c[i - 1])) for i, r in enumerate(cl) if i > 0]
    atr = sum(tr[-14:]) / 14.0; f = reg_fit(c, atr)
    if not f: return None
    K = float(k or cfg().get("reg_k", 2.0)); mid = f["vk"] + f["slope"]; sd = f["sd"]; up, lo_ = mid + K * sd, mid - K * sd; sgn = 1 if side == "long" else -1
    return {"tf": ctf, "win": f["win"], "r": round(f["r"], 3), "dir": f["dir"], "slope_atr": round(f["slope"] / atr, 3) if atr else None, "z": round((px - mid) / sd, 2) if sd > 0 else None,
            "mid": mid, "up": up, "lo": lo_, "k": K, "px": px, "brk": bool((px > up) if sgn > 0 else (px < lo_))}


# ---------- заметки пользователя из канала ----------
def find_by_msg(mid):
    """id тени по id сообщения канала (сигнал, график или разбор), на которое ответил пользователь."""
    if not mid: return None
    with lock:
        _load()
        for k, m in S["msg"].items():
            if k.isdigit() and mid in (m.get("a"), m.get("b"), m.get("c")): return int(k)
    return None


def note_add(text, mid=None, reply_to=None, t=None):
    """Сохраняет заметку пользователя в shadow_notes.jsonl: текст, привязка к тени (ответ на её сообщение или #номер в тексте). Возвращает список id теней."""
    ids = []; r = find_by_msg(reply_to)
    if r: ids.append(r)
    with lock:
        _load(); its = list(S["items"])
    for x, v in re.findall(r"#\s?(\d{1,5})\s?([AaBbАаВв]?)", text or ""):      # #42 - сигнал 42 (A и B), #42B - только вариант B
        m = [i for i in its if int(i.get("sn") or 0) == int(x)] or [i for i in its if i["id"] == int(x)]
        if v and v.upper() in ("B", "В"): m = [i for i in m if i.get("var") == "B"]
        for i in (m or [{"id": int(x)}]):
            if i["id"] not in ids: ids.append(i["id"])
    with open(NF, "a", encoding="utf-8") as f: f.write(json.dumps({"t": int(t or now_ms()), "mid": mid, "reply_to": reply_to, "trades": ids, "text": text}, ensure_ascii=False, separators=(",", ":")) + "\n")
    return ids


# ---------- вход: ордер, фильтр 1m, позиция ----------
def _snap(fn, *a):
    try: return fn(*a)
    except Exception: return None


def _mkpos(E, it, o, fp, ft, a1):
    """Позиция при исполнении ордера: те же поля и правила, что в chan_orders.cycle при исполнении рыночного ордера из слежения."""
    pos, exit_cfg, CO = E["pos"], E["exit_cfg"], E["CO"]
    side = 1 if o["side"] == "long" else -1
    try: stp = exit_cfg.stop_at_fill(exit_cfg.load(), side, fp, a1, o["stop"])
    except Exception: stp = o["stop"]
    R = abs(fp - stp)
    if R <= 0 or (side > 0 and stp >= fp) or (side < 0 and stp <= fp): return None, "стоп по ту сторону входа"
    th = "Теневой рыночный вход %s %s из слежения по цене %.6g (с проскальзыванием 0.03%%), исполнен %s UTC." % (o["side"], o["sym"], fp, pos.tstr(ft))
    p = {"id": it["id"], "sym": o["sym"] + "USDT", "side": o["side"], "t_in": ft, "entry": fp, "px_signal": o["price"], "stop0": stp, "stop": stp, "tp": o["tp"],
         "R": R, "R_pct": R / fp * 100, "be_r": 1.0, "lock_pct": 0.2, "be_px": fp + side * R, "lock_px": fp * (1 + side * 0.2 / 100), "armed": False,
         "trail_dist": 1.5 * a1, "atr1h": a1, "max_h": (o.get("max_h") or CO.MAXH), "stake": pos.STAKE, "lev": pos.LEV, "thesis": th, "last_t": (ft // 60000) * 60000, "hi": fp, "lo": fp, "status": "open",
         "src": "shadow", "tf": it.get("tf") or "5m", "order_id": None, "rule": o["rule"], "placed_t": o.get("placed_t"), "fee_in": CO.MAK, "fee_tp": CO.MAK}
    try:      # перенос стопа за ближайший экстремум после разворотной свечи (swing_stop): включён -> флаг sw (параллельно считается копия без него, поле pb)
        import swing_stop
        if swing_stop.load().get("enabled", True): p["sw"] = 1
    except Exception as e: log_once("sw", "swing_stop: %r" % e)
    try:      # цель дальше при запасе хода (tp_ext, #38): флаг ext только для теней, у копии pb его нет
        import tp_ext
        if tp_ext.load().get("enabled", True): p["ext"] = 1
    except Exception as e: log_once("ext", "tp_ext: %r" % e)
    if o.get("setup") == "breakout" and (o.get("regime") or {}).get("regime") == "flat":     # правило выхода «флэт + пробой»: 50% на +0.4R, остаток в БУ
        if (o["tp"] - fp) * side > 0.4 * R: p["xr"] = "flat_brk"
    return p, None


def _price(E, sym):
    try: return float(E["CO"]._tg_price(sym))
    except Exception: return None


def _create_order(E, it):
    CO = E["CO"]; w = dict(it["w"]); px = _price(E, it["sym"]) or _f((w.get("last") or {}).get("c"))
    if not px: return False
    o, why = CO._tg_mkorder(w, "market", it["target"], px, it["setup"])
    if not o: it.update(status="void", why=why or "ордер не построен", t_end=now_ms()); return True
    o["id"] = -it["id"]; o["approved_t"] = it["t0"]; o["src_watch"] = w.get("id")
    o["regime"] = _snap(CO.tg_gate.reg_snap); o["b1"] = _snap(CO.tg_gate.b1_snap, o.get("side"))
    it["chan"] = _clean(o.pop("chan", None)); o.pop("why", None)
    it["o"] = _clean(o); it["o0"] = copy.deepcopy(it["o"]); return True


def _tick_gate(E, it):
    CO = E["CO"]; now = now_ms()
    if it.get("o") is None:
        if not _create_order(E, it): return
        if it["status"] != "gate": return
    o = it["o"]; wait = CO._gate_cap_ms(o) if hasattr(CO, "_gate_cap_ms") else int(cfg().get("max_wait_min", 10)) * 60000; ctf = (o.get("live1m") or {}).get("ctf") or (CO._ctrl_tf(o) if hasattr(CO, "_ctrl_tf") else "1m")
    if now - it["t0"] > wait:
        return _filtered(E, it, ("вариант B: пробоя канала регрессии %s по ходу сделки не было за %d мин (попыток %s)" if it.get("var") == "B" else "вход по рынку не выполнен за %d мин: свеча контроля %s так и не показала ход по сделке (попыток %s)") % ((ctf, wait // 60000, o.get("live1m_tries") or 0) if it.get("var") == "B" else (wait // 60000, ctf, o.get("live1m_tries") or 0)), now)
    if now - it.get("gt", 0) < 8000: return      # как цикл боевого сервиса (~9 с): не чаще раза в 8 секунд на тень
    it["gt"] = now; g, why = CO._live1m_gate(o, now)
    it["g"] = {"n": o.get("live1m_tries"), "l1": o.get("live1m"), "t": now}
    if g == "go":      # снимок канала регрессии свечи контроля на входе (для всех теней, для разбора), у варианта B это ещё и условие входа
        try: ri = reg_info(it["sym"], ctf, it["side"], float(o["price"]))
        except Exception as e: ri = None; log_once("reg", "регрессия: %r" % e)
        it["reg"] = ri; it["g"]["reg"] = ri
        if it.get("var") == "B" and ri is not None and not ri["brk"]: return      # B ждёт пробоя канала по ходу сделки
    if g == "cancel": return _filtered(E, it, why or "вход отменён фильтром", now)
    if g == "go":
        a1 = _snap(E["pos"].atr1h, it["sym"] + "USDT") or o["atr"] * 3.46
        p, why = _mkpos(E, it, o, float(o["price"]), now, a1)
        if not p: it.update(status="void", why=why, t_end=now); return
        it.update(status="open", p=p, t_fill=now); it.setdefault("ev", []).append({"t": now, "k": "entry", "px": p["entry"]})
        if p.get("sw"): pb = copy.deepcopy(p); pb.pop("sw", None); pb.pop("ext", None); pb["src"] = "shadow_pb"; it["pb"] = pb      # копия без переноса стопа: что было бы без правила
        log("вход #%s %s %s по %.6g (попыток %s)" % (it["id"], it["sym"], it["side"], p["entry"], o.get("live1m_tries")))


def _filtered(E, it, why, now):
    """Фильтр не пустил: сигнал ведётся вхолостую по плану (вход по цене ордера в момент сигнала), чтобы видеть, чего стоил фильтр."""
    it.update(status="filtered", why=why, t_end=now)
    if cfg().get("cf", True) and it.get("o0"):
        o0 = it["o0"]; a1 = _snap(E["pos"].atr1h, it["sym"] + "USDT") or o0["atr"] * 3.46
        p, w2 = _mkpos(E, it, o0, float(o0["price"]), it["t0"], a1)
        if p: p["src"] = "shadow_cf"; it["cf"] = p
    log("не вошла #%s %s %s: %s" % (it["id"], it["sym"], it["side"], why))


# ---------- сопровождение: движок позиций счёта ----------
def _advance(E, it, key):
    """Прогнать закрытые свечи 1m через pos.step (как pos._update). key: 'p' - настоящая тень (события пишутся), 'cf' - вхолостую. Возвращает True, если что-то изменилось."""
    pos = E["pos"]; p = it[key]; ch = False; now = now_ms(); _CUR[0] = (it, key)
    try:
        try:
            import trade_mgr
            if key == "p" and trade_mgr.attach(p): ch = True
        except Exception: pass
        while p["status"] == "open":
            d = [k for k in pos.kl(p["sym"], "1m", 1000, p["last_t"] + 60000) if int(k[0]) + 60000 <= now]
            if not d: break
            for k in d:
                pos.step(p, k); p["last_t"] = int(k[0]); ch = True
                if p["status"] != "open": break
            if len(d) < 1000: break
        if p["status"] == "open" and p.get("armed"):     # после БУ стоп подтягивается на подтверждённую линию S/R (как pos._update)
            try:
                if E["exit_cfg"].load()["sr"]["on"]:
                    import sr_stop
                    n0 = len(p.get("sr_hist", []))
                    if sr_stop.apply(p, pos.kl, now, lambda m: None): ch = True
                    if len(p.get("sr_hist", [])) > n0 and key == "p":
                        h = p["sr_hist"][-1]; it.setdefault("ev", []).append({"t": now, "k": "sr", "old": h.get("from"), "new": h.get("to"), "px": h.get("px")})
            except Exception as e: log_once("sr", "sr_stop: %r" % e)
    finally: _CUR[0] = None
    return ch


def _R(p, v): return None if v is None or not p.get("R_pct") else v / p["R_pct"]


def _finish(it):
    p = it["p"]; it["status"] = "closed"; it["t_out"] = p.get("t_out")
    it["mfe_r"] = round(_R(p, p.get("mfe_pct")) or 0, 2); it["mae_r"] = round(_R(p, p.get("mae_pct")) or 0, 2)
    it.setdefault("ev", []).append({"t": p.get("t_out"), "k": "close", "px": p.get("exit"), "reason": p.get("reason")})
    if cfg().get("path", True):
        try:
            rows = _klines(it["sym"], p["t_in"] // 300000 * 300000, "5m"); s = 1 if p["side"] == "long" else -1; en, R = p["entry"], p["R"]; out = []
            for k in rows:
                t = int(k[0])
                if t > p["t_out"]: break
                h, l, cl = float(k[2]), float(k[3]), float(k[4])
                out.append([t, round(((h if s > 0 else l) - en) * s / R, 2), round(((l if s > 0 else h) - en) * s / R, 2), round((cl - en) * s / R, 2)])
            with open(PF, "a", encoding="utf-8") as f:
                f.write(json.dumps({"id": it["id"], "sym": it["sym"], "side": it["side"], "kind": it["kind"], "tf": it["tf"], "t_sig": it.get("t_sig"), "t_in": p["t_in"], "t_out": p["t_out"], "entry": p["entry"], "R": p["R"],
                                    "reason": p.get("reason"), "r": p.get("r_mult"), "step": 300000, "hlc": out}, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as e: log("путь #%s: %r" % (it["id"], e))
    log("закрыта #%s %s %s %s %s R" % (it["id"], it["sym"], it["side"], p.get("reason"), p.get("r_mult")))


def _klines(sym, start, iv="1m", limit=1000):
    q = urllib.parse.urlencode({"symbol": sym + "USDT", "interval": iv, "startTime": int(start), "limit": limit})
    with urllib.request.urlopen(urllib.request.Request(KL + "?" + q, headers={"User-Agent": "tg-shadow"}), timeout=12) as r: return json.loads(r.read().decode("utf-8"))


def _orders():
    try: return json.load(open(ORDF, encoding="utf-8"))
    except Exception: return []


def tick():
    """Один проход движка: берёт записи, работает с копиями (сеть без блокировки), результат возвращает в общий список. Вызывается из loop() раз в 5 секунд."""
    if not enabled(): return
    E = eng()
    if not E: return
    try: consume_queue()
    except Exception as e: log("очередь: %r" % e)
    with lock: _load(); ids = [i["id"] for i in S["items"] if not i.get("legacy") and i.get("status") in ("gate", "open", "filtered", "closed") and (i.get("status") != "closed" or not i.get("chk") or (i.get("pb") or {}).get("status") == "open")]
    ords = None; now = now_ms()
    for iid in ids:
        with lock: it0 = next((i for i in S["items"] if i["id"] == iid), None); it = copy.deepcopy(it0) if it0 else None
        if not it: continue
        old = json.dumps(it, sort_keys=True, default=str)
        try:
            if not it.get("chk") and it["status"] in ("gate", "open", "filtered", "closed") and it.get("wid") is not None:     # реальный ордер по этому слежению -> тень снимается
                if now - it["t0"] > 1800000: it["chk"] = 1
                else:
                    if ords is None: ords = _orders()
                    o = next((x for x in ords if x.get("src_watch") == it["wid"] and (x.get("approved_t") or 0) >= it["t0"] - 120000), None)
                    if o: it.update(status="taken", taken_oid=o.get("id"), chk=1)
            if it.get("tf") not in (cfg().get("tfs") or ["5m"]) and it["status"] in ("gate", "open", "filtered"):      # таймфрейм отключён: открытые и ждущие входа снимаем, холостые прогоны не продолжаем
                if it["status"] in ("gate", "open"): it.update(status="void", why="таймфрейм %s отключён" % it.get("tf"), t_end=now)
            elif it["status"] == "gate": _tick_gate(E, it)
            elif it["status"] == "open":
                if _advance(E, it, "p") and it["p"]["status"] == "closed": _finish(it)
                if (it.get("pb") or {}).get("status") == "open": _advance(E, it, "pb")
            elif it["status"] == "closed" and (it.get("pb") or {}).get("status") == "open": _advance(E, it, "pb")
            elif it["status"] == "filtered" and it.get("cf") and it["cf"]["status"] == "open": _advance(E, it, "cf")
        except Exception as e:
            it["fails"] = it.get("fails", 0) + 1; log("ошибка #%s: %r" % (iid, e))
            if it["fails"] >= 30: it.update(status="void", why="ошибки данных: %r" % e)
        if json.dumps(it, sort_keys=True, default=str) != old:
            with lock:
                it0 = next((i for i in S["items"] if i["id"] == iid), None)
                if it0 is not None: it0.clear(); it0.update(it)
                _save()
    with lock:      # чистка
        cl = sorted([i for i in S["items"] if i.get("status") in ("closed", "filtered", "taken", "void")], key=lambda x: x.get("t_out") or x.get("t_end") or x.get("t0") or 0); kc = int(cfg().get("keep_closed", 300))
        if len(cl) > kc:
            drop = {i["id"] for i in cl[:len(cl) - kc]}; S["items"] = [i for i in S["items"] if i["id"] not in drop]
            for d in drop: S["msg"].pop(str(d), None)
            _save()


def loop():
    log("движок запущен")
    while True:
        try: tick()
        except Exception as e: log("tick: %r" % e)
        time.sleep(5)


# ---------- тексты для Telegram и страницы ----------
RS = {"stop": "стоп", "trail/BE": "стоп после БУ/трейла", "target": "цель", "time": "время", "liquidation": "ликвидация", "manual": "вручную"}
KD = {"bounce": "отбой", "break": "пробой"}


def fpx(x):
    try: return "%.5g" % float(x)
    except Exception: return "—"


def _sg(x, nd=2): return "—" if x is None else ("%+.*f" % (nd, x))


def cf_r(it):
    c = it.get("cf")
    return c.get("r_mult") if c and c.get("status") == "closed" else None


def chain_txt(l1, ctf="1m"):
    """Свечи контроля входа: 15m 150/150 с ✓ · 5m 20/50 с ✗ (сколько секунд цена держится по ходу из нужных)."""
    ch = (l1 or {}).get("chain") or []
    if not ch: return ctf
    return " · ".join("%s %s/%s с %s" % (c["tf"], int(c.get("run") or 0), int(c.get("need") or 0), "✓" if c.get("ok") else ("✗" if c.get("side") else "✗ против")) for c in ch)


def text_gate(it, hhmm, link=None):
    pl = it.get("plan") or {}; o = it.get("o") or {}; side = it["side"].upper()
    L = ["👻 ТЕНЬ #%s · %s %s · %s · %s" % (tag(it), it["sym"], side, KD.get(it["kind"], it["kind"]), it.get("tf") or "5m"),
         "сигнал %s%s · план бота: вход ~%s · стоп %s · цель %s · R:R %s" % (hhmm(it["t0"]), (" · " + link) if link else "", fpx(pl.get("entry")), fpx(pl.get("stop")), fpx(pl.get("tp")), pl.get("rr") if pl.get("rr") is not None else "—")]
    st = it["status"]; l1 = o.get("live1m") or {}; ctf = l1.get("ctf") or "1m"
    if st == "gate":
        L.append("⏳ проверка входа (как при ручном ордере): ждём, чтобы свечи пары %s шли по ходу сделки" % chain_txt(l1, ctf) + ((" · сейчас o %s c %s %s, попытка %s" % (fpx(l1.get("o")), fpx(l1.get("c")), "ещё слишком молодая" if l1.get("young") else "не по ходу", o.get("live1m_tries"))) if l1 and not l1.get("ok") else ""))
    elif st in ("open", "closed"):
        p = it["p"]; L.append("✅ вход %s по %s (свечи пары по ходу: %s; o %s c %s, попыток %s) · стоп %s · цель %s" % (hhmm(it.get("t_fill") or p["t_in"]), fpx(p["entry"]), chain_txt(l1, ctf), fpx(l1.get("o")), fpx(l1.get("c")), o.get("live1m_tries") or 1, fpx(p["stop0"]), fpx(p["tp"])))
        L.append("позиция и итог ниже ⬇")
    elif st == "filtered":
        L.append("⛔ не вошла: " + str(it.get("why")))
        r = cf_r(it)
        L.append(("без фильтра (вход сразу по цене сигнала) было бы: %s R, %s" % (_sg(r), RS.get(it["cf"].get("reason"), it["cf"].get("reason")))) if r is not None else "без фильтра: считаем, итог придёт позже")
    elif st == "void": L.append("⚠ не создана: " + str(it.get("why")))
    elif st == "taken": L.append("снята: по этому слежению вы поставили реальный ордер")
    return "\n".join(L)[:1500]


def ev_lines(it, hhmm):
    out = []
    for e in it.get("ev") or []:
        k = e.get("k"); t = hhmm(e["t"]) if e.get("t") else ""
        if k == "entry": out.append("%s вход %s" % (t, fpx(e.get("px"))))
        elif k == "be": out.append("%s БУ: стоп %s → %s" % (t, fpx(e.get("old")), fpx(e.get("new"))))
        elif k == "be2": out.append("%s БУ-2: стоп %s → %s" % (t, fpx(e.get("old")), fpx(e.get("new"))))
        elif k == "tp1": out.append("%s частичная цель %s (закрыто %s%%)" % (t, fpx(e.get("new")), int(round((e.get("frac") or 0) * 100))))
        elif k == "trail_start": out.append("%s трейлинг включён" % t)
        elif k == "sr": out.append("%s стоп на уровень S/R: %s → %s" % (t, fpx(e.get("old")), fpx(e.get("new"))))
        elif k == "swing": out.append("%s стоп за ближайший экстремум: %s → %s" % (t, fpx(e.get("old")), fpx(e.get("new"))))
        elif k == "mgr_ladder": out.append("%s лесенка: стоп %s → %s" % (t, fpx(e.get("old")), fpx(e.get("new"))))
        elif k == "close": out.append("%s закрыта: %s по %s" % (t, RS.get(e.get("reason"), e.get("reason")), fpx(e.get("px"))))
    return out


def _mid_events(it, hhmm): return [x for x in ev_lines(it, hhmm) if "вход" not in x.split(" ", 1)[1][:5] and "закрыта" not in x]


def caption(it, hhmm, last_px=None):
    p = it["p"]; side = 1 if p["side"] == "long" else -1; sym = it["sym"]; cl = p.get("status") == "closed"
    if cl:
        ic = "✅" if (p.get("net_pct") or 0) > 0 else ("❌" if (p.get("net_pct") or 0) < 0 else "⚪")
        L = ["%s 👻 ТЕНЬ #%s %s %s · %s · %s R · net %s%%" % (ic, tag(it), sym, p["side"].upper(), RS.get(p.get("reason"), p.get("reason")), _sg(p.get("r_mult")), _sg(p.get("net_pct"))),
             "вход %s → выход %s · пик +%s R, против до -%s R" % (fpx(p["entry"]), fpx(p.get("exit")), "%.2f" % (it.get("mfe_r") or 0), "%.2f" % abs(it.get("mae_r") or 0))]
    else:
        L = ["🟢 👻 ТЕНЬ #%s %s %s · идёт с %s" % (tag(it), sym, p["side"].upper(), hhmm(p["t_in"])), "вход %s · стоп %s · цель %s · БУ: %s%s" % (fpx(p["entry"]), fpx(p["stop"]), fpx(p.get("tp")), "да" if p.get("armed") else "нет", " · часть закрыта" if p.get("rem", 1) < 0.999 else "")]
        if last_px: L.append("цена %s · %s%% до комиссий" % (fpx(last_px), _sg(side * (last_px / p["entry"] - 1) * 100)))
    ev = _mid_events(it, hhmm)[-6:]
    if ev: L.append("События: " + " · ".join(ev))
    return "\n".join(L)[:1000]


def postmortem(it, hhmm):
    """Разбор итога: что видел фильтр входа, как шла сделка, где возможна ошибка. Факты и правила, без выводов по одной сделке."""
    L = []; o = it.get("o") or {}; l1 = o.get("live1m") or {}; plan = it.get("plan") or {}; vtag = ""
    if it["status"] == "filtered":
        c = it.get("cf"); r = cf_r(it)
        L.append("👻 ТЕНЬ #%s%s %s %s: вход не состоялся" % (tag(it), vtag, it["sym"], it["side"].upper()))
        L.append("Причина фильтра: %s" % it.get("why"))
        if r is not None:
            L.append("Без фильтра (вход сразу по цене сигнала %s): %s, %s R, пик +%.2f R, против -%.2f R." % (fpx(c["entry"]), RS.get(c.get("reason"), c.get("reason")), _sg(r), _R(c, c.get("mfe_pct")) or 0, abs(_R(c, c.get("mae_pct")) or 0)))
            L.append("➡ Фильтр сработал верно: уберёг от убытка." if r < 0 else "➡ Фильтр лишил прибыли: проверить, не слишком ли строго ждём свечу 1m / лимит ухода от линии (tg_live1m.json).")
    else:
        p = it["p"]; mins = int(((p.get("t_out") or now_ms()) - p["t_in"]) / 60000); mfe, mae = it.get("mfe_r") or 0, abs(it.get("mae_r") or 0); delay = int((p["t_in"] - it["t0"]) / 60000)
        L.append("👻 ТЕНЬ #%s%s %s %s: %s · %s R · net %s%%" % (tag(it), vtag, it["sym"], p["side"].upper(), RS.get(p.get("reason"), p.get("reason")), _sg(p.get("r_mult")), _sg(p.get("net_pct"))))
        slip = (p["entry"] / float(plan["entry"]) - 1) * 100 * (1 if p["side"] == "long" else -1) if plan.get("entry") else None
        ctf = l1.get("ctf") or "1m"
        L.append("Вход: сигнал %s → вход %s (%s мин ожидания свечи %s, попыток %s) по %s%s. Свеча %s пары на входе: o %s c %s." % (hhmm(it["t0"]), hhmm(p["t_in"]), delay, ctf, o.get("live1m_tries") or 1, fpx(p["entry"]),
                 (" (хуже плана на %s%%)" % ("%.2f" % slip)) if slip is not None and slip > 0.02 else "", ctf, fpx(l1.get("o")), fpx(l1.get("c"))))
        rg = it.get("reg")
        if rg: L.append("Регрессия %s на входе: окно %s, r %s, наклон %s ATR, цена %s σ от линии, пробой канала по ходу сделки: %s." % (rg.get("tf"), rg.get("win"), rg.get("r"), rg.get("slope_atr"), rg.get("z"), "да" if rg.get("brk") else "нет"))
        L.append("Ход: пик +%.2f R, против до -%.2f R, длительность %s мин." % (mfe, mae, mins))
        evs = _mid_events(it, hhmm)
        if evs: L.append("События: " + " · ".join(evs))
        bad = [r[2] for r in (it.get("rows") or []) if r and not r[0]]
        if bad: L.append("Условия сигнала, которые не выполнялись (⚠): " + "; ".join(str(b) for b in bad[:4]))
        rs = p.get("reason"); why = []
        if rs == "target": why.append("Сделка по плану, ошибки нет.")
        elif rs in ("stop", "trail/BE"):
            if mfe < 0.15 and mins <= 15: why.append("Цена сразу пошла против входа (пик только +%.2f R за %s мин). Смотреть: что было с BTC и режимом в момент входа, какие условия сигнала были ⚠, не вошли ли в самый конец импульса." % (mfe, mins))
            elif mfe >= 0.5 and rs == "stop": why.append("Цена дошла до +%.2f R и вернулась на стоп: кандидат на раннюю фиксацию (частичная цель или БУ раньше +1R)." % mfe)
            elif rs == "trail/BE": why.append("Закрыто по БУ/трейлингу после хода +%.2f R: стоп защитил, цель не достигнута." % mfe)
            else: why.append("Обычный стоп после небольшого хода в плюс (пик +%.2f R)." % mfe)
        elif rs == "time": why.append("Время вышло: цена не дошла ни до цели, ни до стопа (пик +%.2f R)." % mfe)
        if why: L.append("Где ошибка / что проверить: " + " ".join(why))
        pb = it.get("pb")
        if pb and pb.get("status") == "closed": L.append("Без переноса стопа за экстремум было бы: %s, %s R (с правилом %s R)%s" % (RS.get(pb.get("reason"), pb.get("reason")), _sg(pb.get("r_mult")), _sg(p.get("r_mult")), (" · стоп переносился %d раз" % len(p.get("sw_hist") or [])) if p.get("sw_hist") else " · правило не срабатывало"))
    L.append("Выводы по одной сделке не делаем: ход цены сохранён для разбора пачкой.")
    return "\n".join(L)[:3500]


# ---------- статистика ----------
def stats(items=None):
    its = items if items is not None else snapshot()
    cl = [i for i in its if i.get("status") == "closed"]; fl = [i for i in its if i.get("status") == "filtered"]; op = [i for i in its if i.get("status") in ("gate", "open")]
    def agg(xs, get):
        v = [get(i) for i in xs if get(i) is not None]; n = len(v); w = sum(1 for x in v if x > 0)
        return {"n": n, "win": w, "R": round(sum(v), 2), "avg": round(sum(v) / n, 2) if n else 0.0}
    gr = lambda i: i["p"].get("r_mult")
    out = {"open": len(op), "all": agg(cl, gr), "filtered": {"n": len(fl), "cf": agg(fl, cf_r)}}
    for key in ("kind", "side"): out["by_" + key] = {v: agg([i for i in cl if i.get(key) == v], gr) for v in sorted({i.get(key) for i in cl if i.get(key)})}
    out["by_reason"] = {v: agg([i for i in cl if i["p"].get("reason") == v], gr) for v in sorted({i["p"].get("reason") for i in cl if i["p"].get("reason")})}
    return out


def summary_text(hhmm=None, last=8):
    hhmm = hhmm or (lambda ms: time.strftime("%H:%M", time.localtime(ms / 1000)))
    its = [i for i in snapshot() if i.get("var") != "B"]; s = stats(its); a = s["all"]; f = s["filtered"]
    if not its: return "👻 Теневых сделок пока нет: сигналы «ЗАХОДИТЬ», по которым вы не открыли сделку, ведутся на бумаге по тем же правилам, что ваш ручной вход."
    L = ["👻 Тени (пропущенные сигналы «ЗАХОДИТЬ», на счёт не влияют)", "Сейчас в работе: %d · вошли и закрыты: %d (плюс %d / минус %d, итого %s R, среднее %s R)" % (s["open"], a["n"], a["win"], a["n"] - a["win"], _sg(a["R"]), _sg(a["avg"]))]
    if f["n"]: L.append("Отфильтрованы входом: %d; если бы входили без фильтра: %s R (%d из них в плюс)" % (f["n"], _sg(f["cf"]["R"]), f["cf"]["win"]))
    for key, ru in (("by_kind", KD), ("by_side", {"long": "LONG", "short": "SHORT"}), ("by_reason", RS)):
        parts = ["%s %d (%s R)" % (ru.get(k, k), v["n"], _sg(v["R"])) for k, v in s[key].items()]
        if parts: L.append(" · ".join(parts))
    cl = sorted([i for i in its if i.get("status") == "closed"], key=lambda x: x.get("t_out") or 0, reverse=True)[:last]
    for i in cl: L.append("#%s %s %s %s: %s %s R" % (tag(i), i["sym"], i["side"].upper(), KD.get(i["kind"], i["kind"]), RS.get(i["p"].get("reason"), i["p"].get("reason")), _sg(i["p"].get("r_mult"))))
    return "\n".join(L)[:3800]


# ---------- статистика по выбору (меню в канале: таймфрейм и вид сделки) ----------
TFL = ("5m", "15m", "1h", "4h", "1d")
KIND_RU = {"all": "всё", "bl": "отбой LONG", "bs": "отбой SHORT", "brk": "пробой"}


def _sel(it, tf, kind):
    if tf != "all" and it.get("tf") != tf: return False
    k, sd = it.get("kind"), it.get("side")
    return kind == "all" or (kind == "bl" and k == "bounce" and sd == "long") or (kind == "bs" and k == "bounce" and sd == "short") or (kind == "brk" and k == "break")


def _agg(xs, get):
    v = [get(i) for i in xs if get(i) is not None]; n = len(v); w = sum(1 for x in v if x > 0)
    return n, w, round(sum(v), 2)


def stats_text(tf="all", kind="all"):
    """Сводка по выбору: таймфрейм (all | 5m | 15m | 1h | 4h | 1d) и вид (all | bl отбой LONG | bs отбой SHORT | brk пробой). Итоги в R после комиссий."""
    allits = [i for i in snapshot() if _sel(i, tf, kind)]; its = [i for i in allits if i.get("var") != "B"]; itsB = [i for i in allits if i.get("var") == "B"]
    cl = [i for i in its if i.get("status") == "closed" and i.get("p")]; fl = [i for i in its if i.get("status") == "filtered"]; op = [i for i in its if i.get("status") in ("gate", "open")]
    L = ["📊 Тени · %s · %s" % ("все таймфреймы" if tf == "all" else tf, KIND_RU.get(kind, kind)),
         "Сигналов: %d · в работе %d · вошли %d (закрыто) · фильтр входа не пустил %d" % (len(its), len(op), len(cl), len(fl))]
    n, w, r = _agg(cl, lambda i: i["p"].get("r_mult"))
    if n:
        mf = [i.get("mfe_r") or 0 for i in cl]; ma = [abs(i.get("mae_r") or 0) for i in cl]
        L.append("Закрыто %d: плюс %d (%d%%), минус %d · итого %s R · среднее %s R" % (n, w, round(w / n * 100), n - w, _sg(r), _sg(r / n)))
        L.append("В среднем пик +%.2f R, против до -%.2f R" % (sum(mf) / n, sum(ma) / n))
        for rs in ("target", "trail/BE", "stop", "time", "liquidation"):
            xs = [i for i in cl if i["p"].get("reason") == rs]
            if xs: nn, ww, rr = _agg(xs, lambda i: i["p"].get("r_mult")); L.append("  %s: %d (%s R)" % (RS.get(rs, rs), nn, _sg(rr)))
    else: L.append("Закрытых сделок пока нет.")
    if fl:
        nn, ww, rr = _agg(fl, cf_r)
        L.append("Фильтр входа не пустил %d; без фильтра было бы %s R (в плюс %d из %d посчитанных)" % (len(fl), _sg(rr), ww, nn))
    if itsB:
        clB = [i for i in itsB if i.get("status") == "closed" and i.get("p")]; flB = [i for i in itsB if i.get("status") == "filtered"]; nB, wB, rB = _agg(clB, lambda i: i["p"].get("r_mult"))
        L.append("Вариант B (вход ждёт пробоя канала регрессии свечи контроля по ходу): сигналов %d, вошли %d%s, не вошли %d, в работе %d" % (len(itsB), nB, (" (плюс %d, итого %s R, среднее %s R)" % (wB, _sg(rB), _sg(rB / nB))) if nB else "", len(flB), len([i for i in itsB if i.get("status") in ("gate", "open")])))
    if tf == "all":
        parts = []
        for t in TFL:
            xs = [i for i in cl if i.get("tf") == t]
            if xs: nn, ww, rr = _agg(xs, lambda i: i["p"].get("r_mult")); parts.append("%s: %d (%s R)" % (t, nn, _sg(rr)))
        if parts: L.append("По таймфреймам: " + " · ".join(parts))
    if kind == "all":
        parts = []
        for k_, ru in (("bl", "отбой LONG"), ("bs", "отбой SHORT"), ("brk", "пробой")):
            xs = [i for i in cl if _sel(i, "all", k_)]
            if xs: nn, ww, rr = _agg(xs, lambda i: i["p"].get("r_mult")); parts.append("%s: %d (%s R)" % (ru, nn, _sg(rr)))
        if parts: L.append("По видам: " + " · ".join(parts))
    L.append("Обновлено " + time.strftime("%H:%M", time.localtime()))
    return "\n".join(L)[:3800]


def menu_keyboard(tf="all", kind="all"):
    mk = lambda lab, t, k, on: {"text": ("✓ " if on else "") + lab, "callback_data": "shs:%s:%s" % (t, k)}
    r1 = [mk("Все", "all", kind, tf == "all")] + [mk(t, t, kind, tf == t) for t in TFL]
    r2 = [mk("Всё", tf, "all", kind == "all"), mk("Отбой LONG", tf, "bl", kind == "bl"), mk("Отбой SHORT", tf, "bs", kind == "bs"), mk("Пробой", tf, "brk", kind == "brk")]
    return [r1[:3], r1[3:], r2[:2], r2[2:], [{"text": "🔄 Обновить", "callback_data": "shs:%s:%s" % (tf, kind)}]]
