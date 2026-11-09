# -*- coding: utf-8 -*-
"""tg_review.py -- разбор закрытых сделок из Telegram-слежения и самообучение входов (коррекции порогов). Только stdlib.
По закрытии позиции (ордер rule tg_*, в том числе Автоордер): факты по свечам 5m, причины убытка, вывод бота, коррекция порогов (tg_corr.json) и сообщение в Telegram.
Коррекция: только после повторения одной причины (corr_min_repeat раз среди последних 6 разобранных сделок), на один шаг, в пределах LIMITS; без убытков в последних 6 разборах пороги по шагу возвращаются к исходным.
Каждая коррекция в журнале hist с id, откат кнопкой (revert). Отключить: файл tg_corr.json {"enabled": false} или удалить модуль (tg_bot/tg_express подключают через try/except).
Файлы POS_DIR: tg_corr.json (params, hist, cfg), tg_reviewed.json (разобранные id), tg_reviews.jsonl (журнал разборов)."""
import json, os, time, urllib.request
try: import tg_target as TG
except Exception: TG = None

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CORRF = os.path.join(D, "tg_corr.json"); REVF = os.path.join(D, "tg_reviewed.json"); LOGF = os.path.join(D, "tg_reviews.jsonl")
BASE = getattr(TG, "BASE", "https://data-api.binance.vision/api/v3/klines"); BAR = 300000
DEFAULTS = {"wick_min": 0.4, "dist_max": 0.9, "rr_add": 0.0, "rr_add_counter": 0.0, "brk_n_min": 2, "brk_body_min": 0.3, "brk_beyond_max": 1.5}
# (минимум, максимум, шаг, направление ужесточения)
LIMITS = {"wick_min": (0.4, 0.7, 0.05, 1), "dist_max": (0.4, 0.9, 0.1, -1), "rr_add": (0.0, 0.6, 0.1, 1), "rr_add_counter": (0.0, 0.6, 0.1, 1),
          "brk_n_min": (2, 4, 1, 1), "brk_body_min": (0.3, 0.7, 0.1, 1), "brk_beyond_max": (0.8, 1.5, 0.2, -1)}
PNAME = {"wick_min": "минимальный хвост (реакция от линии)", "dist_max": "макс. удаление цены от линии, ATR", "rr_add": "надбавка к R:R (по тренду)", "rr_add_counter": "надбавка к R:R (против тренда)",
         "brk_n_min": "закрытий за линией для пробоя", "brk_body_min": "мин. тело свечи пробоя", "brk_beyond_max": "макс. уход за линию (не гонимся), ATR"}
CAUSE_PARAM = {"no_reaction": ("wick_min", 1), "line_broken": ("wick_min", 1), "late": ("dist_max", -1), "brk_return": ("brk_n_min", 1), "brk_chased": ("brk_beyond_max", -1), "brk_weak": ("brk_body_min", 1)}
CAUSE_RU = {"no_reaction": "вход без реакции от линии", "line_broken": "линия пробита против входа", "late": "вход поздно (цена далеко от линии)", "fast_stop": "быстрый стоп без явной причины",
            "gave_back": "прибыль была, но не зафиксирована", "slow": "затянувшаяся сделка", "spike": "резкая свеча на выходе (шум, новости)", "brk_return": "ложный пробой: цена быстро вернулась за линию",
            "brk_chased": "вход в пробой в погоне (далеко за линией)", "brk_weak": "слабая свеча пробоя"}
_cache = {"mt": None, "v": None}


def _jl(path, d):
    try: return json.load(open(path, encoding="utf-8"))
    except Exception: return d


def _cfg_full():
    c = _jl(CORRF, {}); c.setdefault("params", {}); c.setdefault("hist", []); c.setdefault("cfg", {}); return c


def _save(c):
    tmp = CORRF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(c, f, ensure_ascii=False)
    os.replace(tmp, CORRF)


def corr():
    """Действующие пороги (по умолчанию DEFAULTS + коррекции). Кэш по mtime файла."""
    try: mt = os.path.getmtime(CORRF)
    except OSError: mt = None
    if _cache["v"] is not None and _cache["mt"] == mt: return _cache["v"]
    c = _cfg_full(); v = dict(DEFAULTS)
    if c["cfg"].get("enabled", True):
        for k, x in c["params"].items():
            if k in v:
                try: v[k] = float(x) if k not in ("brk_n_min",) else int(x)
                except Exception: pass
    _cache.update(mt=mt, v=v); return v


def corr_note():
    """Строка для поста: какие пороги отличаются от исходных (пусто, если коррекций нет)."""
    v = corr(); ch = ["%s %s" % (k, ("%g" % v[k])) for k in DEFAULTS if abs(v[k] - DEFAULTS[k]) > 1e-9]
    return ("⚙️ Коррекции по опыту: " + ", ".join(ch)) if ch else ""


def _fetch(sym, t0, t1):
    sy = sym if sym.endswith("USDT") else sym + "USDT"; out = []; t = int(t0)
    for _ in range(3):
        try:
            u = "%s?symbol=%s&interval=5m&limit=1000&startTime=%d&endTime=%d" % (BASE, sy, t, int(t1)); return json.load(urllib.request.urlopen(u, timeout=20))
        except Exception: time.sleep(1)
    return out


def _fp(p):
    p = float(p)
    return "%.1f" % p if p >= 1000 else "%.3f" % p if p >= 10 else "%.4f" % p if p >= 1 else "%.5f" % p


def analyze(p, o, ks):
    """p - закрытая позиция, o - её ордер (с chan, line, setup, atr), ks - свечи 5m вокруг сделки. Возвращает dict с фактами, причинами и текстом."""
    side = p["side"]; s = 1 if side == "long" else -1; setup = o.get("setup") or "bounce"; counter = bool(o.get("counter")); brk = setup == "breakout"
    ln = (o.get("chan") or {}).get(o.get("line") or "")
    a = float(o.get("atr") or 0) or float(p.get("R") or 0) / 1.2
    t_in, t_out = int(p["t_in"]), int(p["t_out"]); Rp = float(p.get("R_pct") or 0) or 1.0
    r = float(p.get("r_mult") or 0); mfe = float(p.get("mfe_pct") or 0) / Rp; mae = float(p.get("mae_pct") or 0) / Rp
    bars = max(1, int(round((t_out - t_in) / BAR))); entry = float(p["entry"])
    lat = (lambda t: ln["p1"] + ln["s"] * (t - ln["t1"])) if ln else None
    cl = [k for k in ks if k[0] + BAR > t_in and k[0] + BAR <= t_out]
    n_bad = 0; first_bad = None
    if lat:
        for i, k in enumerate(cl):
            c = float(k[4]); L = lat(int(k[0]))
            if (c < L) if s > 0 else (c > L):
                n_bad += 1; first_bad = i + 1 if first_bad is None else first_bad
    sig = next((k for k in reversed(ks) if k[0] + BAR <= t_in), None); wick = body = None
    if sig:
        o_, h_, l_, c_ = (float(sig[i]) for i in (1, 2, 3, 4)); rng = max(h_ - l_, 1e-12)
        wick = ((min(o_, c_) - l_) if s > 0 else (h_ - max(o_, c_))) / rng; body = (c_ - o_) * s / rng
    d = ((entry - lat(t_in)) * s / a) if (lat and a) else None
    last = cl[-1] if cl else None; spike = bool(last and a and (float(last[2]) - float(last[3])) >= 3 * a)
    res = "win" if r > 0.15 else ("loss" if r < -0.15 else "flat"); causes = []
    if res == "loss":
        if brk:
            if first_bad is not None and first_bad <= 3: causes.append("brk_return")
            if d is not None and d > 1.0: causes.append("brk_chased")
            if body is not None and body < 0.45: causes.append("brk_weak")
        else:
            if n_bad >= 2: causes.append("line_broken")
            if bars <= 4 and mfe < 0.3 and (wick is None or wick < 0.5): causes.append("no_reaction")
            elif bars <= 4 and mfe < 0.3 and n_bad < 2: causes.append("fast_stop")
            if d is not None and d > 0.6: causes.append("late")
        if mfe >= 0.6: causes.append("gave_back")
        if bars > 24: causes.append("slow")
        if spike: causes.append("spike")
        if not causes: causes.append("fast_stop")
    f = {"setup": setup, "counter": int(counter), "bars": bars, "mfe_r": round(mfe, 2), "mae_r": round(mae, 2), "n_bad": n_bad, "first_bad": first_bad, "wick": None if wick is None else round(wick, 2),
         "body": None if body is None else round(body, 2), "d": None if d is None else round(d, 2), "spike": int(spike)}
    return {"res": res, "r": r, "net": float(p.get("net_pct") or 0), "causes": causes, "facts": f, "reason": p.get("reason"), "auto": bool(o.get("auto_express"))}


def _facts_text(A):
    f = A["facts"]; brk = f["setup"] == "breakout"; out = []
    if f["d"] is not None: out.append(("Вход был на %.2f ATR %s линии" % (abs(f["d"]), "за" if brk and f["d"] >= 0 else "от")) + ("" if f["wick"] is None else ", хвост сигнальной свечи %d%%" % round(f["wick"] * 100)) + ("" if f["body"] is None else ", тело %d%%" % round(f["body"] * 100)) + ".")
    out.append("Сделка шла %d свечей 5m (%s). Максимум в плюсе %+.2f R, максимум против %.2f R." % (f["bars"], "%d ч %02d мин" % divmod(f["bars"] * 5, 60), f["mfe_r"], f["mae_r"]))
    if f["n_bad"]: out.append("После входа %d свечей закрылись %s линии (первая через %d)." % (f["n_bad"], "с обратной стороны" if brk else "за линией против входа", f["first_bad"] or 0))
    elif brk: out.append("Закрытий обратно за линию не было.")
    if f["spike"]: out.append("Свеча выхода очень широкая (≥3 ATR): резкое движение.")
    return out


def _params_changed(hist_n=0):
    return None


def _recent(n=6):
    rows = []
    try:
        for ln in open(LOGF, encoding="utf-8"):
            try: rows.append(json.loads(ln))
            except Exception: pass
    except OSError: pass
    return rows[-n:]


def _update(c, A, pid):
    """Коррекции по результату разбора. Возвращает список изменений [{id,param,old,new,cause}] и список примечаний."""
    ch = []; notes = []; cfg = c["cfg"]; minrep = int(cfg.get("min_repeat", 2)); now = int(time.time() * 1000)
    if not cfg.get("enabled", True): return ch, ["Самообучение выключено (enabled=false): коррекции не вводятся."]
    recent = _recent(6)       # последние разборы, включая текущий (он уже записан)
    for cause in A["causes"]:
        pr = CAUSE_PARAM.get(cause)
        if not pr: continue
        if A["facts"]["setup"] != "breakout" and cause == "line_broken" and A["facts"]["counter"]: pr = ("rr_add_counter", 1)
        par, sign = pr; lo, hi, step, tight = LIMITS[par]; cur = float(c["params"].get(par, DEFAULTS[par]))
        reps = sum(1 for r in recent if cause in (r.get("causes") or []))
        last = max([h["ts"] for h in c["hist"] if h["param"] == par and h.get("cause") != "relax"] + [0])
        if reps < minrep: notes.append("«%s»: пока %d из %d нужных повторов в последних 6 сделках; порог «%s» не меняю." % (CAUSE_RU[cause], reps, minrep, PNAME[par])); continue
        if now - last < 6 * 3600000: notes.append("«%s»: порог «%s» менялся меньше 6 часов назад, жду." % (CAUSE_RU[cause], PNAME[par])); continue
        new = cur + tight * step
        new = min(hi, max(lo, new)) if lo <= hi else new
        if abs(new - cur) < 1e-9: notes.append("«%s»: порог «%s» уже на пределе (%g)." % (CAUSE_RU[cause], PNAME[par], cur)); continue
        new = round(new, 3) if par != "brk_n_min" else int(new)
        hid = max([h["id"] for h in c["hist"]] + [0]) + 1
        h = {"id": hid, "ts": now, "param": par, "old": cur, "new": new, "cause": cause, "pos": pid}; c["hist"].append(h); c["params"][par] = new; ch.append(h)
    return ch, notes


def _relax(c):
    """Если в последних 6 разборах нет убытков, один порог возвращается на шаг к исходному."""
    rec = _recent(6)
    if len(rec) < 6 or any(r.get("res") == "loss" for r in rec) or not c["cfg"].get("enabled", True): return None
    off = [(k, v) for k, v in c["params"].items() if k in DEFAULTS and abs(float(v) - DEFAULTS[k]) > 1e-9]
    if not off: return None
    now = int(time.time() * 1000); k, v = min(off, key=lambda kv: max([h["ts"] for h in c["hist"] if h["param"] == kv[0]] + [0])); lo, hi, step, tight = LIMITS[k]
    new = float(v) - tight * step; new = DEFAULTS[k] if (new - DEFAULTS[k]) * tight < 0 else new; new = round(new, 3) if k != "brk_n_min" else int(new)
    hid = max([h["id"] for h in c["hist"]] + [0]) + 1; h = {"id": hid, "ts": now, "param": k, "old": float(v), "new": new, "cause": "relax", "pos": None}
    c["hist"].append(h); c["params"][k] = new; return h


def _text(p, o, A, ch, notes, rel):
    f = A["facts"]; sym = p["sym"]; side = p["side"].upper(); auto = A["auto"]
    head = "%s Разбор сделки #%s %s %s (%s%s)" % ("✅" if A["res"] == "win" else ("🔻" if A["res"] == "loss" else "➖"), p.get("id"), sym, side, "пробой" if f["setup"] == "breakout" else "отбой", ", Автоордер" if auto else "")
    lines = [head, "Итог: %+.2f R (net %+.2f%%), выход: %s." % (A["r"], A["net"], A["reason"] or "—")] + _facts_text(A)
    if A["res"] == "loss":
        lines.append("")
        lines.append("Что пошло не так: " + "; ".join(CAUSE_RU[c] for c in A["causes"]) + ".")
        extra = {"gave_back": "Максимум в плюсе был %+.2f R: цель оказалась далеко, часть хода не забрали (дальность цели обучается отдельно)." % f["mfe_r"]}
        for c in A["causes"]:
            if c in extra: lines.append(extra[c])
        if ch:
            lines.append(""); lines.append("Коррекция входа:")
            for h in ch: lines.append("• %s: %g → %g (причина: %s)" % (PNAME[h["param"]], h["old"], h["new"], CAUSE_RU.get(h["cause"], h["cause"])))
        for n in notes: lines.append("• " + n)
    elif A["res"] == "win":
        lines.append(""); lines.append("Вывод: сделка сработала по плану, коррекций не нужно. Записано в базу как успешный вход.")
    else: lines.append(""); lines.append("Вывод: около нуля (безубыток/частичная фиксация), коррекций нет.")
    if rel: lines.append("↩️ Давно нет убытков: порог «%s» возвращён %g → %g." % (PNAME[rel["param"]], rel["old"], rel["new"]))
    cn = corr_note()
    if cn: lines.append(cn)
    return "\n".join(lines)


def run(limit=3):
    """Разобрать новые закрытые сделки. Возвращает [{text, buttons: [(hid, label)]}]. Первый запуск только помечает уже закрытые (без рассылки старых)."""
    pos = _jl(os.path.join(D, "positions.json"), []); orders = {o["id"]: o for o in _jl(os.path.join(D, "orders.json"), [])}
    closed = [p for p in pos if p.get("status") == "closed" and p.get("t_out") is not None]
    if not os.path.exists(REVF):
        json.dump(sorted([p.get("id") for p in closed], key=str), open(REVF, "w")); return []
    seen = set(_jl(REVF, [])); out = []
    for p in closed:
        pid = p.get("id")
        if pid in seen: continue
        if len(out) >= limit: break
        o = orders.get(p.get("order_id"))
        if not o or not str(o.get("rule", "")).startswith("tg_") or not o.get("chan"): seen.add(pid); continue
        ks = _fetch(p["sym"], int(p["t_in"]) - 4 * BAR, int(p["t_out"]) + BAR)
        if not ks: continue            # свечей нет (сеть): попробуем в следующий раз
        try: A = analyze(p, o, ks)
        except Exception: seen.add(pid); continue
        c = _cfg_full(); rec = {"ts": int(time.time() * 1000), "pid": pid, "oid": o.get("id"), "sym": p["sym"], "side": p["side"], "setup": A["facts"]["setup"], "res": A["res"], "r": A["r"], "causes": A["causes"], "facts": A["facts"], "auto": A["auto"]}
        with open(LOGF, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        ch, notes = _update(c, A, pid) if A["res"] == "loss" else ([], [])
        rel = _relax(c) if (A["res"] != "loss" and not ch) else None
        if ch or rel: _save(c)
        rec["changes"] = [h["id"] for h in ch] + ([rel["id"]] if rel else [])
        out.append({"text": _text(p, o, A, ch, notes, rel), "buttons": [(h["id"], "↩ Откатить: %s %g→%g" % (h["param"], h["old"], h["new"])) for h in ch + ([rel] if rel else [])]})
        seen.add(pid)
    json.dump(sorted(seen, key=str), open(REVF, "w")); return out


def revert(hid):
    """Откат коррекции по id (если параметр ещё равен new). Возвращает текст ответа."""
    c = _cfg_full(); h = next((x for x in c["hist"] if x["id"] == hid), None)
    if not h: return "Коррекция не найдена."
    if h.get("reverted"): return "Уже откатена."
    if abs(float(c["params"].get(h["param"], DEFAULTS[h["param"]])) - float(h["new"])) > 1e-9: return "Порог уже изменён позже, откатывать вручную нечего."
    c["params"][h["param"]] = h["old"]; h["reverted"] = True; _save(c)
    return "Откатил: %s %g → %g." % (PNAME[h["param"]], h["new"], h["old"])


def summary(lrn=None):
    """Текст для /learn: пороги, история коррекций, базы обучения."""
    c = _cfg_full(); v = corr(); rows = _recent(200); n = len(rows); loss = sum(1 for r in rows if r.get("res") == "loss"); win = sum(1 for r in rows if r.get("res") == "win")
    s = ["🧠 Самообучение", "Разобрано сделок: %d (успех %d, убыток %d)." % (n, win, loss), "Порог повторов для коррекции: %d. Самообучение: %s." % (int(c["cfg"].get("min_repeat", 2)), "вкл" if c["cfg"].get("enabled", True) else "выкл"), "", "Пороги (исходный → действующий):"]
    for k in DEFAULTS: s.append("• %s: %g → %g%s" % (PNAME[k], DEFAULTS[k], v[k], "" if abs(v[k] - DEFAULTS[k]) < 1e-9 else "  ⚙️"))
    h = [x for x in c["hist"] if not x.get("reverted")][-5:]
    if h:
        s.append(""); s.append("Последние коррекции:")
        for x in h: s.append("• %s %s: %g → %g (%s)" % (time.strftime("%m-%d %H:%M", time.gmtime(x["ts"] / 1000)), x["param"], x["old"], x["new"], CAUSE_RU.get(x["cause"], x["cause"])))
    if lrn:
        try: s.append(""); s.append(lrn.stats_text())
        except Exception: pass
    return "\n".join(s)
