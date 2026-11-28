"""Виртуальный баланс теней (только чтение shadow.json, подсчёт теней не трогает).

Две линии стартуют с одного значения (эквити счёта на момент запуска, shadow_bal.json: t0, start):
  f - «с фильтрами»: тени, которые вошли (A, статус closed/open);
  n - «без фильтра»: все сигналы A: вошедшие по их результату, отфильтрованные по холостому результату cf (вход сразу по цене сигнала).
Правила как у счёта: ставка stake (нотионал), плечо lev, маржа stake/lev на сделку,
слотов max(min_slots, int(баланс // slot_eq)), свободная маржа не меньше маржи сделки.
Результат сделки: stake * net_pct / 100 (net_pct уже с комиссиями, как pos.py).
Линии l<N> (shadow_bal.json: one_per_sym, max_side=[3,2,1]): сделки «без фильтра» с правилами «не больше одной позиции на монету» и «не больше N в одну сторону».
Линия full: стартовый баланс need, при котором не пропущена ни одна сделка, и итог при нём; open_list: открытые сделки (для живого баланса на странице).
Закрытые сделки копятся в shadow_bal_trades.json (не теряются при чистке shadow.json); файл лежит в /opt/trading-bot/live/data (папка tbot внутри единственного пути записи live-web), иначе в pos_dir.
Фильтр обеих линий (shadow_bal.json: skip_tf, skip_regime; по умолчанию ["5m"] и ["flat"]): сделки с таким таймфреймом или режимом
на момент сигнала (x.rg.regime) в баланс не берутся. Пустые списки отключают фильтр. Решение 2026-11-25 по разбору сливов (shadow_notes №20).
"""
import json, os, time

_CACHE = {"mt": None, "out": None}


def _load(p, dflt=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return dflt


def _save(p, o):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(o, f, ensure_ascii=False)
    os.replace(tmp, p)


def _simulate(trades, start, stake, lev, slot_eq, min_slots, one_sym=False, max_side=None):
    """trades: [{t_in, t_out|None, net_pct|None}] -> итог одной линии."""
    margin = stake / lev
    bal = float(start); opn = []; taken = skipped = wins = maxc = skip_rule = 0; rsum = 0.0
    for tr in sorted(trades, key=lambda x: x["t_in"]):
        ex = sorted([o for o in opn if o["t_out"] is not None and o["t_out"] <= tr["t_in"]], key=lambda o: o["t_out"])
        for o in ex:
            bal += stake * o["net_pct"] / 100.0; wins += 1 if o["net_pct"] > 0 else 0; rsum += o.get("r") or 0.0; opn.remove(o)
        slots = max(min_slots, int(bal // slot_eq))
        if (one_sym and any(o.get("sym") == tr.get("sym") for o in opn)) or (max_side and sum(1 for o in opn if o.get("side") == tr.get("side")) >= max_side):
            skipped += 1; skip_rule += 1; continue        # правила: одна позиция на монету, не больше max_side в одну сторону
        if len(opn) < slots and bal - len(opn) * margin >= margin:
            opn.append(tr); taken += 1; maxc = max(maxc, len(opn))
        else: skipped += 1
    for o in sorted([o for o in opn if o["t_out"] is not None], key=lambda o: o["t_out"]):
        bal += stake * o["net_pct"] / 100.0; wins += 1 if o["net_pct"] > 0 else 0; rsum += o.get("r") or 0.0; opn.remove(o)
    closed = taken - len(opn)
    return {"bal": round(bal, 3), "pnl": round(bal - start, 3), "taken": taken, "closed": closed, "wins": wins, "open": len(opn),
            "skipped": skipped, "skip_rule": skip_rule, "skip_slots": skipped - skip_rule, "maxc": maxc, "slots": max(min_slots, int(bal // slot_eq)),
            "r": round(rsum, 3), "open_list": [{"sym": o.get("sym"), "side": o.get("side"), "entry": o.get("entry"), "rp": o.get("rp")} for o in opn]}


def _full(trades, start, stake, lev, slot_eq, min_slots, one_sym=False, max_side=None):
    """Какой стартовый баланс нужен, чтобы ни одна сделка линии не была пропущена (слоты и маржа), и что вышло бы при нём."""
    def run(s0): return _simulate(trades, s0, stake, lev, slot_eq, min_slots, one_sym, max_side)
    lo = float(start); r = run(lo)
    if r["skip_slots"] == 0: need = lo
    else:
        hi = lo * 2.0; rh = run(hi)
        while rh["skip_slots"] and hi < 1e6: hi *= 2.0; rh = run(hi)
        for _ in range(45):
            mid = (lo + hi) / 2.0; rm = run(mid)
            if rm["skip_slots"] == 0: hi, rh = mid, rm
            else: lo = mid
        need = hi; r = rh
    need = round(need + 0.0005, 3); r = run(need)
    r["need"] = need
    return r


def compute(pos_dir):
    cfgp = os.path.join(pos_dir, "shadow_bal.json"); shp = os.path.join(pos_dir, "shadow.json"); jd = os.environ.get("LEDGER_JOURNAL_DIR", "/opt/trading-bot/live/data")   # live-web пишет только в /opt/trading-bot/live (ProtectSystem=strict), сам каталог root, поэтому data/ у tbot
    trp = os.path.join(jd if os.access(jd, os.W_OK) else pos_dir, "shadow_bal_trades.json")
    cfg = _load(cfgp)
    if not cfg or not cfg.get("on", True): return None
    try: mt = (os.path.getmtime(shp), os.path.getmtime(cfgp))
    except Exception: mt = None
    if mt is not None and _CACHE["mt"] == mt and _CACHE["out"] is not None: return _CACHE["out"]
    t0 = int(cfg["t0"]); start = float(cfg["start"]); stake = float(cfg.get("stake", 6.0)); lev = float(cfg.get("lev", 5))
    slot_eq = float(cfg.get("slot_eq", 2.0)); min_slots = int(cfg.get("min_slots", 3))
    items = (_load(shp, {}) or {}).get("items") or []
    saved = _load(trp, {}) or {}
    cur = {}; live = {}
    for x in items:
        if x.get("var") not in ("A", None): continue
        st = x.get("status"); p = x.get("p") or {}; cf = x.get("cf") or {}
        if p.get("legacy"): continue
        iid = str(x.get("id"))
        if st in ("closed", "open") and p.get("t_in"):
            src, k = p, "in"
        elif st == "filtered" and cf.get("t_in"):
            src, k = cf, "cf"
        else: continue
        if src["t_in"] < t0: continue
        done = src.get("status") == "closed" and src.get("t_out") and src.get("net_pct") is not None
        rec = {"id": iid, "sn": x.get("sn"), "sym": x.get("sym"), "side": x.get("side"), "tf": x.get("tf"), "k": k, "t_in": int(src["t_in"]),
               "t_out": int(src["t_out"]) if done else None, "net_pct": float(src["net_pct"]) if done else None, "r": src.get("r_mult") if done else None,
               "rg": (x.get("rg") or {}).get("regime"), "entry": src.get("entry"), "rp": src.get("R_pct")}
        key = iid + k
        if done: cur[key] = rec
        else: live[key] = rec
    changed = False
    for key, rec in cur.items():
        if saved.get(key) != rec: saved[key] = rec; changed = True
    if changed:
        try: _save(trp, saved)
        except Exception: pass
    allr = dict(live); allr.update(saved)          # закрытые из журнала, незакрытые из shadow.json
    for key in list(allr):                           # запись, ушедшая из shadow.json и не закрытая, не учитывается
        if key not in saved and key not in live: allr.pop(key)
    skip_tf = set(cfg.get("skip_tf", ["5m"])); skip_rg = set(cfg.get("skip_regime", ["flat"]))
    for key in list(allr):                           # фильтр «не flat и не 5m» для обеих линий
        r = allr[key]
        if r.get("tf") in skip_tf or (r.get("rg") is not None and r.get("rg") in skip_rg): allr.pop(key)
    F = [r for r in allr.values() if r["k"] == "in"]; N = list(allr.values())
    lines = [dict(k="f", name="с фильтрами", **_simulate(F, start, stake, lev, slot_eq, min_slots)),
             dict(k="n", name="без фильтра", **_simulate(N, start, stake, lev, slot_eq, min_slots))]
    one_sym = bool(cfg.get("one_per_sym", True)); sides = cfg.get("max_side", [3, 2, 1]); sides = sides if isinstance(sides, list) else [sides]
    lims = [(int(m), dict(k="l%d" % int(m), name="лимиты: 1 на монету, не больше %d в сторону" % int(m), **_simulate(N, start, stake, lev, slot_eq, min_slots, one_sym, int(m)))) for m in sides if m]
    lines += [x[1] for x in lims]
    TR = {"f": (F, False, None), "n": (N, False, None)}
    for m, ln in lims: TR[ln["k"]] = (N, one_sym, m)
    for ln in lines:
        T, osy, ms = TR[ln["k"]]
        if ln.get("skip_slots"):
            try: ln["full"] = _full(T, start, stake, lev, slot_eq, min_slots, osy, ms)
            except Exception: pass
    out = {"t0": t0, "start": start, "stake": stake, "lev": lev, "slot_eq": slot_eq, "min_slots": min_slots, "lines": lines, "skip_tf": sorted(skip_tf), "skip_regime": sorted(skip_rg), "now": int(time.time() * 1000)}
    out["now"] = 0   # не меняем подпись без изменения данных
    _CACHE["mt"] = mt; _CACHE["out"] = out
    return out
