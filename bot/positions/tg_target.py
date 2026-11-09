# -*- coding: utf-8 -*-
"""tg_target.py -- цель сделки по статистике дальности отбоя от линии канала (доли высоты канала от своей линии), с самообучением.
Используется: Авто (chan_orders.propose: цель chan_top/chan_bottom) и мнение бота в экспрессе (tg_express). Только stdlib.
Данные: POS_DIR/reach_samples.jsonl - по строке на ситуацию: {src: seed|auto|express, sym, t, side, counter, hatr (высота канала в ATR), res: {"0.25": R, ...}},
где R = результат сделки в единицах риска (лимит у линии, начальный стоп, 48 свечей 5m, без сопровождения, комиссии не учтены; обе в одной свече = стоп).
Выбор: сегмент (по тренду/против, узкий/широкий канал) -> доля с максимальным средним R; из доль в пределах TOL от максимума берётся ближняя.
Нет данных (коррекции, мало выборки, нет файла) -> минимальная доля 1/4 канала (в Авто цель обязательна).
Отключить: env TG_TARGET=0 или reach_cfg.json {"auto": false} (Авто возвращается к цели «противоположная линия»); обучение: REACH_LEARN=0 или {"learn": false}."""
import json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
SAMPLES = os.path.join(D, "reach_samples.jsonl"); SEEN = os.path.join(D, "reach_seen.json"); CFG = os.path.join(D, "reach_cfg.json")
GRID = (0.25, 0.33, 0.5, 0.75, 1.0); MIN_FR = GRID[0]; MIN_N = 20; TOL = 0.05; HORIZON = 48; BAR_MS = 300000
BASE = "https://data-api.binance.vision/api/v3/klines"
FR_RU = {0.25: "1/4", 0.33: "1/3", 0.5: "1/2", 0.75: "3/4", 1.0: "до противоположной линии"}
_cache = {"mt": None, "rows": []}


def _cfg():
    try: return json.load(open(CFG, encoding="utf-8"))
    except Exception: return {}


def auto_enabled(): return os.environ.get("TG_TARGET", "1") != "0" and bool(_cfg().get("auto", True))
def learn_enabled(): return os.environ.get("REACH_LEARN", "1") != "0" and bool(_cfg().get("learn", True))


def simulate(ks, side, line, H, entry, stop):
    """ks - свечи 5m после сигнала [t,o,h,l,c,...]. Возвращает {"0.25": R|None, ...} или None, если свечей меньше горизонта."""
    s = 1 if side == "long" else -1; risk = abs(entry - stop)
    if risk <= 0 or len(ks) < HORIZON: return None
    ks = ks[:HORIZON]; res = {}
    for f in GRID:
        tp = line + s * f * H; gain = (tp - entry) * s
        if gain <= 0.05 * risk: res["%.2f" % f] = None; continue
        out = None
        for k in ks:
            hi, lo = float(k[2]), float(k[3])
            if (lo <= stop) if s > 0 else (hi >= stop): out = -1.0; break
            if (hi >= tp) if s > 0 else (lo <= tp): out = round(gain / risk, 3); break
        if out is None: out = round((float(ks[-1][4]) - entry) * s / risk, 3)
        res["%.2f" % f] = out
    return res


def _rows():
    try: mt = os.path.getmtime(SAMPLES)
    except OSError: return []
    if _cache["mt"] != mt:
        rows = []
        for ln in open(SAMPLES, encoding="utf-8"):
            try: rows.append(json.loads(ln))
            except Exception: pass
        _cache["mt"] = mt; _cache["rows"] = rows
    return _cache["rows"]


def add_sample(row):
    if not learn_enabled(): return False
    with open(SAMPLES, "a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def choose(width_atr, counter=False):
    """Цель для отбоя: {f, known, p (доля сделок, дошедших до цели), ev (средний R), n, seg, text}. Всегда возвращает цель (минимум 1/4)."""
    allr = _rows(); counter = int(bool(counter))
    rows = [r for r in allr if int(r.get("counter", 0)) == counter]
    hs = sorted(float(r["hatr"]) for r in allr if r.get("hatr")); thr = hs[len(hs) // 2] if len(hs) >= MIN_N else None
    seg = rows; tier = ""
    if thr and rows:
        wide = float(width_atr) >= thr
        s2 = [r for r in rows if (float(r.get("hatr") or 0) >= thr) == wide]
        if len(s2) >= MIN_N: seg = s2; tier = ", широкий канал" if wide else ", узкий канал"
    name = ("против тренда (коррекция)" if counter else "по тренду") + tier
    stats = {}
    for f in GRID:
        xs = [x for x in ((r.get("res") or {}).get("%.2f" % f) for r in seg) if x is not None]
        if len(xs) >= MIN_N: stats[f] = (sum(xs) / len(xs), sum(x > 0 for x in xs) / len(xs), len(xs))
    if not stats:
        return {"f": MIN_FR, "known": False, "n": len(seg), "seg": name, "text": "данных по таким ситуациям нет (%s, n=%d): беру минимальную цель %s канала" % (name, len(seg), FR_RU[MIN_FR])}
    best = max(v[0] for v in stats.values()); f = min(k for k, v in stats.items() if v[0] >= best - TOL); ev, p, n = stats[f]
    return {"f": f, "known": True, "ev": round(ev, 2), "p": round(p, 2), "n": n, "seg": name,
            "text": "цель %s канала: в похожих ситуациях (%s, n=%d) доходит %d%%, средний результат %+.2f R" % (FR_RU[f], name, n, round(p * 100), ev)}


def _jl(path, default):
    try: return json.load(open(path, encoding="utf-8"))
    except Exception: return default


def _fetch(sym, t0):
    sy = sym if sym.endswith("USDT") else sym + "USDT"
    u = "%s?symbol=%s&interval=5m&limit=%d&startTime=%d" % (BASE, sy, HORIZON + 12, int(t0))
    for _ in range(3):
        try: return [k for k in json.load(urllib.request.urlopen(u, timeout=20)) if k[0] > t0]
        except Exception: time.sleep(1)
    return []


def learn_positions(limit=2, src="auto", workers=1):
    """Закрытые позиции счёта (отбой от линии) -> новые строки выборки. Исход считается без сопровождения по свечам 5m после входа.
    Уже учтённые id хранятся в reach_seen.json. Пишет только tg_bot (раз в 5 минут) или разовый посев."""
    if not learn_enabled(): return 0
    pos = _jl(os.path.join(D, "positions.json"), []); orders = {o["id"]: o for o in _jl(os.path.join(D, "orders.json"), [])}
    seen = set(_jl(SEEN, [])); now = int(time.time() * 1000); todo = []
    for p in pos:
        pid = p.get("id", p.get("order_id"))
        if pid in seen or p.get("t_out") is None: continue
        o = orders.get(p.get("order_id"))
        if not o or not o.get("chan") or o.get("setup") == "breakout" or o.get("rule") in ("retest_up", "retest_down"): seen.add(pid); continue
        if now - int(p["t_in"]) < (HORIZON + 3) * BAR_MS: continue
        todo.append((pid, p, o))
        if len(todo) >= limit: break
    def job(x):
        pid, p, o = x; return x, _fetch(p["sym"], p["t_in"])
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex: got = list(ex.map(job, todo))
    n = 0
    for (pid, p, o), ks in got:
        ch = o["chan"]; t = int(p["t_in"])
        try:
            R = ch["upper"]["p1"] + ch["upper"]["s"] * (t - ch["upper"]["t1"]); S = ch["lower"]["p1"] + ch["lower"]["s"] * (t - ch["lower"]["t1"])
            H = R - S; long = p["side"] == "long"; line = S if long else R
            if H <= 0 or not o.get("atr"): seen.add(pid); continue
            res = simulate(ks, p["side"], line, H, float(p["entry"]), float(p["stop0"]))
        except Exception: seen.add(pid); continue
        if res is None: continue          # свечей пока мало / сбой сети - повторим позже
        ct = str(o.get("ctype") or ""); counter = (long and "down" in ct) or ((not long) and "up" in ct)
        add_sample({"src": src, "sym": p["sym"], "t": t, "side": p["side"], "counter": int(counter), "hatr": round(H / float(o["atr"]), 2), "res": res})
        seen.add(pid); n += 1
    json.dump(sorted(seen, key=str), open(SEEN, "w", encoding="utf-8"))
    return n
