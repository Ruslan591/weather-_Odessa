# -*- coding: utf-8 -*-
"""Выход по провалу сценария: после входа 5m свечи закрываются за линией канала ПРОТИВ входа (отбой: за линией, от которой ждали отскок; пробой: обратно за линию, которую пробивали).
Идея пользователя (разбор #299: прибыль была, не зафиксирована; первая плохая свеча через 1 свечу, дальше 22 из 24). Проверка по кэшу минутных путей (scripts/paths_cache.py), реальный движок pos.step,
правила выхода счёта как есть + дополнительный выход по рынку (комиссии и проскальзывание как у рыночного выхода) на закрытии 5m свечи. Итог в R сделки; те же данные (in-sample), обе половины рядом.
Запуск на VPS как entry_study.py."""
import copy, gzip, json, os, sys, urllib.request
os.environ["POS_DIR"] = "/tmp/thstudy_pos"; os.makedirs("/tmp/thstudy_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
open("/tmp/thstudy_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None
trade_mgr._cache[0] = None; trade_mgr._cache[1] = dict(trade_mgr.DEFAULT, enabled=False)
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(REAL + "/orders.json", encoding="utf-8"))}


def line_info(p, o):
    """(линия 'upper'|'lower', плохо = закрытие ВЫШЕ линии (+1) или НИЖЕ (-1)) или None."""
    ch = (o or {}).get("chan"); rule = p.get("rule"); sd = 1 if p["side"] == "long" else -1
    if not ch or not ch.get("upper"): return None
    if rule in ("tg_market", "tg_limit", "tg_stop"):
        ln = o.get("line"); st = o.get("setup")
        if not ln or not st: return None
        up = ln == "upper"
        bad = (1 if up else -1) if st == "bounce" else (-1 if up else 1)       # отбой: плохо за линией; пробой: плохо обратно внутрь
        return ("upper" if up else "lower", bad)
    if rule == "chan_top": return ("upper", 1)
    if rule == "chan_bottom": return ("lower", -1)
    return None


T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"])); o = orders.get(p.get("order_id"))
    if not c or not c["ks"] or p.get("entry") is None: continue
    li = line_info(p, o)
    if not li: continue
    last_t = (p["t_in"] // 60000) * 60000; ks = [k for k in c["ks"] if k[0] > last_t]
    if len(ks) >= 5: T.append(dict(p=p, o=o, ks=ks, li=li, sd=1 if p["side"] == "long" else -1))
N = len(T); ids = sorted(t["p"]["id"] for t in T); half = ids[N // 2]
print("сделок с линией и путями: %d (из %d закрытых)" % (N, len(snap["closed"])))


def build(t):
    p0 = t["p"]; sd = t["sd"]; E = p0["entry"]; R = p0["R"]
    q = {x: copy.deepcopy(p0[x]) for x in ("id", "sym", "side", "stake", "lev", "atr1h", "max_h", "thesis", "rule", "src", "fee_in", "fee_tp") if x in p0}
    q.update(t_in=p0["t_in"], entry=E, px_signal=E, stop0=p0["stop0"], stop=p0["stop0"], tp=p0["tp"], R=R, R_pct=p0["R_pct"], be_r=1.0, lock_pct=0.2, be_px=E + sd * R, lock_px=E * (1 + sd * 0.002), armed=False,
             trail_dist=1.5 * (p0.get("atr1h") or 0), hi=E, lo=E, status="open", last_t=0)
    if p0.get("xr"): q["xr"] = p0["xr"]
    return q


def line_at(o, which, t):
    L = o["chan"][which]; return L["p1"] + L["s"] * (t - L["t1"])


def play(t, rule):
    """rule(None) = как было. rule(ctx) -> True: закрыть по рынку на этом закрытии 5m. ctx: n_bad, consec, unreal_r, bars."""
    q = build(t); o = t["o"]; which, bad = t["li"]; sd = t["sd"]; atr = float(o.get("atr") or 0)
    n_bad = 0; consec = 0; bars = 0; trig = None
    for k in t["ks"]:
        pos.step(q, k)
        if q["status"] != "open": break
        if rule is None: continue
        if (k[0] // 60000) % 5 != 4: continue          # закрытие 5m свечи (последняя минутка бара)
        bars += 1; cl = k[4]; ln = line_at(o, which, k[0] + 60000)
        buf = rule["buf"] * atr
        isbad = (cl > ln + buf) if bad > 0 else (cl < ln - buf)
        n_bad += isbad; consec = consec + 1 if isbad else 0
        if not isbad and not rule.get("any"): continue
        ur = sd * (cl / q["entry"] - 1) * 100 / q["R_pct"]
        ctx = dict(n_bad=n_bad, consec=consec, unreal=ur, bars=bars, isbad=isbad)
        if rule["fn"](ctx):
            pos.close(q, cl, k[0] + 60000, "line", True); trig = ctx; break
    if q["status"] == "open": pos.close(q, t["ks"][-1][4], t["ks"][-1][0] + 60000, "time", True)
    return q, trig


def run(label, rule):
    qs = []; tr = 0
    for t in T:
        q, g = play(t, rule); qs.append((t, q, g)); tr += 1 if g else 0
    rs = [q["net_pct"] / t["p"]["R_pct"] for t, q, g in qs]; tot = sum(rs); h1 = sum(r for (t, q, g), r in zip(qs, rs) if t["p"]["id"] < half)
    st = 100 * sum(q["reason"] == "stop" for t, q, g in qs) / N
    ex = [q["net_pct"] / t["p"]["R_pct"] for t, q, g in qs if g]
    base_ex = [b for (t, q, g), b in zip(qs, BASE) if g]
    print("%-52s сумма %+7.1f R (1/2: %+6.1f / %+6.1f) | на сделку %+5.2f | выходов по правилу %3d | на них: %+.2f R (как было %+.2f) | стоп %3.0f%%" % (
        label, tot, h1, tot - h1, tot / N, tr, sum(ex) / max(1, len(ex)), sum(base_ex) / max(1, len(base_ex)), st))


BASE = []
for t in T:
    q, _ = play(t, None); BASE.append(q["net_pct"] / t["p"]["R_pct"])
print("как было (движок, правила счёта): сумма %+.1f R\n" % sum(BASE))
run("как было", None) if False else None
B0 = dict(buf=0.0)
def mk(buf, fn, any_=False): return dict(buf=buf, fn=fn, any=any_)
print("== Плохое закрытие 5m за линией против входа (буфер 0)")
run("A  первое плохое закрытие: выходим всегда", mk(0, lambda c: c["isbad"]))
run("B  первое плохое закрытие, если в плюсе (>=0 R)", mk(0, lambda c: c["isbad"] and c["unreal"] >= 0))
run("C  первое плохое закрытие, если >= +0.3 R", mk(0, lambda c: c["isbad"] and c["unreal"] >= 0.3))
run("D  второе плохое закрытие (всего): выходим всегда", mk(0, lambda c: c["n_bad"] >= 2))
run("E  два плохих подряд: выходим всегда", mk(0, lambda c: c["consec"] >= 2))
run("F  три плохих всего: выходим всегда", mk(0, lambda c: c["n_bad"] >= 3))
run("G  второе плохое, если не хуже -0.5 R", mk(0, lambda c: c["n_bad"] >= 2 and c["unreal"] >= -0.5))
print("\n== Буфер 0.15 ATR(5m) за линией (меньше шума)")
run("A' первое плохое закрытие: выходим всегда", mk(0.15, lambda c: c["isbad"]))
run("B' первое плохое, если в плюсе", mk(0.15, lambda c: c["isbad"] and c["unreal"] >= 0))
run("D' второе плохое: выходим всегда", mk(0.15, lambda c: c["n_bad"] >= 2))
run("E' два плохих подряд", mk(0.15, lambda c: c["consec"] >= 2))
print("\n== Фиксация по плюсу независимо от линии (для сравнения: любой 5m бар в плюсе >= x R и плохое закрытие)")
for x in (0.5, 0.75, 1.0):
    run("H  плохое закрытие и в плюсе >= %.2f R" % x, mk(0, lambda c, x=x: c["isbad"] and c["unreal"] >= x))
# разбор: сколько прибыли теряется
gv = []
for t in T:
    q, g = play(t, mk(0, lambda c: False)); gv.append(q)
print("\nТрадиционный взгляд: сделки со стопом, у которых MFE >= 0.3 R: %d из %d; в среднем MFE %.2f R" % (
    sum(1 for t, b in zip(T, gv) if b["reason"] == "stop" and b["mfe_pct"] / b["R_pct"] >= 0.3), N,
    sum(b["mfe_pct"] / b["R_pct"] for t, b in zip(T, gv) if b["reason"] == "stop" and b["mfe_pct"] / b["R_pct"] >= 0.3) / max(1, sum(1 for t, b in zip(T, gv) if b["reason"] == "stop" and b["mfe_pct"] / b["R_pct"] >= 0.3))))
