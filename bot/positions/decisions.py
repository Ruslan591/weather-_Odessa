# -*- coding: utf-8 -*-
"""Журнал решений счёта Claude (вкладки Классика / AFD / Регрессия / AFD + регрессия, отдельно для каждой: POS_DIR/decisions.jsonl).
Цель: записать, КАК пользователь ведёт сделку (переносы стопа и цели, трейлинг, закрытие), с контекстом на момент действия, чтобы затем вывести правила и построить бота-менеджера («клон мышления»).
Записи ручных действий (by=manual) содержат: цену, стоп и цель до/после (цена, % от цены, ATR 5m и 1h, R), R-результат сделки, пик и откат в R, возраст, 12 свечей 5m и 6 свечей 1h,
ближайшие подтверждённые уровни поддержки/сопротивления (sr_stop.levels), метку причины (tag) и заметку (note). Автоматические события (by=auto): БУ, старт трейлинга, частичная цель, перенос на S/R - короткие записи без свечей.
Строки только добавляются, формат JSON Lines, реальных ордеров нет."""
import json, os, time
D = os.environ.get("POS_DIR", "/opt/trading-bot/positions")
J = os.path.join(D, "decisions.jsonl")
BIG = ("c5", "c1h", "sr")          # поля с контекстом, в компактный вид не входят
_cnt = [None, None]                # (size, число строк)

def _r(x, n=6):
    try: return float("%.*g" % (n, float(x)))
    except Exception: return x

def _write(rec):
    try:
        os.makedirs(D, exist_ok=True)
        with open(J, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e: print("decisions write err", e, flush=True)

def _base(p, px, now):
    side = 1 if p["side"] == "long" else -1; R = p["R"] or 1e-12
    hi, lo = p.get("hi", p["entry"]), p.get("lo", p["entry"])
    peak = ((hi - p["entry"]) if side > 0 else (p["entry"] - lo)) / R
    trough = ((p["entry"] - lo) if side > 0 else (hi - p["entry"])) / R
    r_now = (px - p["entry"]) * side / R
    return dict(t=int(now), id=p["id"], sym=p["sym"], side=p["side"], entry=_r(p["entry"], 8), px=_r(px, 8), R=_r(R, 6), atr1h=_r(p.get("atr1h") or 0, 6),
                r_now=round(r_now, 3), peak_r=round(peak, 3), maxdd_r=round(trough, 3), from_peak_r=round(peak - r_now, 3), age_h=round((now - p["t_in"]) / 3.6e6, 2),
                armed=bool(p.get("armed")), trail_act=bool(p.get("trail_act")), tp1_done=bool(p.get("tp1_done")), rem=p.get("rem", 1.0), stop_manual=bool(p.get("stop_manual")), rule=p.get("o_rule"))

def _dist(p, px, v, atr5):
    """Расстояние уровня v от текущей цены: в % цены, в ATR 5m и 1h, и положение уровня относительно входа в R."""
    side = 1 if p["side"] == "long" else -1; out = {}
    if v is None: return out
    out["to_px_pct"] = round(abs(px - v) / px * 100, 3)
    if atr5: out["to_atr5"] = round(abs(px - v) / atr5, 2)
    if p.get("atr1h"): out["to_atr1h"] = round(abs(px - v) / p["atr1h"], 2)
    out["to_r"] = round((v - p["entry"]) * side / (p["R"] or 1e-12), 3)
    return out

def _context(p, px, kl, now):
    """Свечи и уровни: 12 свечей 5m, 6 свечей 1h, ближайшие подтверждённые уровни поддержки и сопротивления."""
    out = {}
    try:
        import sr_stop
        d = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(p["sym"], "5m", 300)]
        d = [k for k in d if k[0] + 300000 <= now]
        atr5 = sr_stop._atr(d) if len(d) > 20 else None
        out["atr5"] = _r(atr5, 6) if atr5 else None
        out["c5"] = [[k[0] // 1000] + [_r(v, 6) for v in k[1:]] for k in d[-12:]]
        if atr5:
            sr = []
            for sd, nm in ((1, "support"), (-1, "resistance")):
                lv = sorted(sr_stop.levels(sd, d, d[0][0], atr5), key=lambda z: abs(z["p"] - px))[:3]
                sr += [{"kind": nm, "p": _r(z["p"], 8), "touches": z["touches"], "atr5": round(abs(z["p"] - px) / atr5, 2)} for z in lv]
            out["sr"] = sr
        h = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(p["sym"], "1h", 10)]
        h = [k for k in h if k[0] + 3600000 <= now]
        out["c1h"] = [[k[0] // 1000] + [_r(v, 6) for v in k[1:]] for k in h[-6:]]
    except Exception as e:
        out["ctx_err"] = str(e)[:120]
    return out

def manual(p, px, kl, kind, old, new, o=None, **kw):
    """Ручное действие пользователя (kind: stop, tp, trail, release, tp_release, close). old/new - цены до и после. tag и note берутся из запроса o."""
    try:
        now = int(time.time() * 1000); o = o or {}
        rec = _base(p, px, now); ctx = _context(p, px, kl, now); atr5 = ctx.get("atr5")
        rec.update(kind=kind, by="manual", **{"from": _r(old, 8) if old is not None else None, "to": _r(new, 8) if new is not None else None})
        if kind in ("stop", "tp", "trail"): rec.update(_dist(p, px, new, atr5))
        if kind in ("stop", "tp", "trail"): rec.update(_dist_old(p, px, old, atr5))
        rec["tag"] = str(o.get("tag") or "")[:60]; rec["note"] = str(o.get("note") or "")[:300]; rec.update(kw); rec.update(ctx)
        _write(rec)
    except Exception as e: print("decisions manual err", e, flush=True)

def _dist_old(p, px, v, atr5):
    d = _dist(p, px, v, atr5); return {"from_" + k[3:]: x for k, x in d.items() if k.startswith("to_")}

def auto(p, kind, old, new, t, px=None, **kw):
    """Автоматическое событие движка (be, trail_start, tp1, sr): короткая запись без свечей."""
    try:
        px = px if px is not None else p["entry"]; rec = _base(p, px, t)
        rec.update(kind=kind, by="auto", **{"from": _r(old, 8) if old is not None else None, "to": _r(new, 8) if new is not None else None}); rec.update(kw)
        _write(rec)
    except Exception as e: print("decisions auto err", e, flush=True)

def _lines():
    try: sz = os.path.getsize(J)
    except OSError: return 0
    if _cnt[0] == sz: return _cnt[1]
    n = 0
    with open(J, "rb") as f:
        for _ in f: n += 1
    _cnt[0] = sz; _cnt[1] = n; return n

def tail(n=30, compact=True):
    """Последние n записей (компактно: без свечей и уровней). Читается хвост файла."""
    try: sz = os.path.getsize(J)
    except OSError: return []
    with open(J, "rb") as f:
        f.seek(max(0, sz - 400000)); data = f.read().decode("utf-8", "replace").split("\n")
    out = []
    for ln in data[-(n * 3 + 5):]:
        try: r = json.loads(ln)
        except Exception: continue
        if compact: r = {k: v for k, v in r.items() if k not in BIG}
        out.append(r)
    return out[-n:]

def all_rows(limit=5000, pid=None):
    rows = []
    try:
        for ln in open(J, encoding="utf-8"):
            try: r = json.loads(ln)
            except Exception: continue
            if pid is None or r.get("id") == pid: rows.append(r)
    except OSError: pass
    return rows[-limit:]

def summary():
    return {"n": _lines(), "tail": tail(30)}
