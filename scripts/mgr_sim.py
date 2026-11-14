# -*- coding: utf-8 -*-
"""Проверка менеджера сделки на реальных путях цены: для каждой закрытой сделки счёта берутся минутные свечи Binance с момента входа, позиция заново проигрывается РЕАЛЬНЫМ движком (pos.step)
по прежним правилам счёта и по вариантам менеджера. Это не бэктест «шаблона на удачу», а контроль, что менеджер не делает заметно хуже и где меняет итог. На тех же данных (in-sample).
Не учтено: перенос стопа на S/R (sr_stop), ручные действия, проскальзывание реального стакана. Запуск на VPS: cd /tmp/mgrsim && python3 mgr_sim.py (рядом pos.py exit_cfg.py decisions.py trade_mgr.py)."""
import copy, json, os, sys, time, urllib.request, statistics as st
os.environ["POS_DIR"] = "/tmp/mgrsim_pos"; os.makedirs("/tmp/mgrsim_pos", exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pos, exit_cfg, trade_mgr
REAL = "/opt/trading-bot/positions_regr"
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
orders = {o["id"]: o for o in json.load(open(REAL + "/orders.json", encoding="utf-8"))}
open("/tmp/mgrsim_pos/exit_cfg.json", "w").write(open(REAL + "/exit_cfg.json").read()); exit_cfg._cache[0] = None


def candles(sym, start, end):
    out = []; t = start
    while t < end and len(out) < 3000:
        u = "%s?symbol=%s&interval=1m&limit=1000&startTime=%d" % (pos.BASE, sym, t)
        try: d = json.load(urllib.request.urlopen(u, timeout=20))
        except Exception: time.sleep(1.5); continue
        if not d: break
        out += d; t = int(d[-1][0]) + 60000
        if len(d) < 1000: break
    time.sleep(0.1); return [k for k in out if int(k[0]) <= end]


trades = []
for p in snap["closed"]:
    o = orders.get(p.get("order_id")) or {}
    if not p.get("t_in") or not p.get("t_out") or p.get("entry") is None: continue
    t_in = p["t_in"]; last_t = (t_in // 60000) * 60000
    ks = candles(p["sym"], last_t + 60000, p["t_out"] + 3600000 * 6)
    if not ks: continue
    base = {k: copy.deepcopy(p[k]) for k in ("id", "sym", "side", "t_in", "entry", "px_signal", "stop0", "tp", "R", "R_pct", "atr1h", "max_h", "stake", "lev", "thesis", "rule", "fee_in", "fee_tp", "src", "order_id") if k in p}
    base.update(stop=p["stop0"], be_r=1.0, lock_pct=0.2, armed=False, hi=p["entry"], lo=p["entry"], status="open", last_t=last_t, trail_dist=1.5 * (p.get("atr1h") or 0))
    sd = 1 if p["side"] == "long" else -1
    base.update(be_px=p["entry"] + sd * p["R"], lock_px=p["entry"] * (1 + sd * 0.002))
    if p.get("xr"): base["xr"] = p["xr"]
    base["cls"] = trade_mgr.classify(o) if o else "other"
    trades.append((p, base, ks))
print("trades with paths: %d of %d" % (len(trades), len(snap["closed"])), flush=True)


def play(base, ks, cfg):
    trade_mgr._cache[0] = None; trade_mgr._cache[1] = cfg
    p = copy.deepcopy(base)
    if cfg.get("enabled"): trade_mgr.attach(p)
    for k in ks:
        pos.step(p, k)
        if p["status"] != "open": break
    return p


C = copy.deepcopy(trade_mgr.DEFAULT); C["enabled"] = True   # в симуляции менеджер включён явно (по умолчанию в trade_mgr он выключен)
def var(**kw):
    c = copy.deepcopy(C)
    for k, v in kw.items():
        if k == "speed1": c["speed"] = {"min": 1.0, "max": 1.0}
        elif k in ("lad", "be_r", "lock_r"): c["common"][k] = v
        else: c[k] = v
    return c
V = [("OLD  прежние правила", var(enabled=False)), ("M1   менеджер v1 (лесенка 0.5/-0.45, 0.8/-0.10 x скорость класса)", var()),
     ("M2   то же без масштаба по классам", var(speed1=1)), ("M3   лесенка ближе (0.4/-0.5, 0.7/-0.2)", var(lad=[[0.4, -0.5], [0.7, -0.2]])),
     ("M4   лесенка дальше (0.6/-0.5, 1.0/-0.15)", var(lad=[[0.6, -0.5], [1.0, -0.15]])), ("M5   v1 + БУ раньше (0.8 R)", var(be_r=0.8)),
     ("M6   одна ступень (0.5/-0.3)", var(lad=[[0.5, -0.3]]))]
res = {name: [] for name, _ in V}
for p, base, ks in trades:
    for name, cfg in V:
        q = play(base, ks, cfg); res[name].append((p["id"], q.get("r_mult") if q["status"] == "closed" else 0.0, q.get("reason"), base["cls"], q["status"]))
ids = sorted(p["id"] for p, _, _ in trades); half = ids[len(ids) // 2]
act = {p["id"]: p.get("r_mult") or 0 for p, _, _ in trades}
print("\nВерность воспроизведения (OLD в симуляции против фактических итогов): сумма сим %+.1f R, факт %+.1f R, средняя разница по сделке %.2f R" % (
    sum(r for _, r, _, _, _ in res[V[0][0]]), sum(act.values()), st.mean(abs(r - act[i]) for i, r, _, _, _ in res[V[0][0]])))
print("\n%-72s %9s %9s %9s %7s" % ("вариант", "сумма R", "1-я пол.", "2-я пол.", "стоп%"))
for name, _ in V:
    r = res[name]; a = sum(x[1] for x in r if x[0] < half); b = sum(x[1] for x in r if x[0] >= half)
    print("%-72s %+9.1f %+9.1f %+9.1f %6.0f%%" % (name, a + b, a, b, 100 * sum(1 for x in r if x[2] == "stop") / len(r)))
print("\nПо классам (сумма R: OLD -> M1, число сделок):")
cl = sorted({x[3] for x in res[V[0][0]]})
for c in cl:
    o0 = sum(x[1] for x in res[V[0][0]] if x[3] == c); m1 = sum(x[1] for x in res[V[1][0]] if x[3] == c); n = sum(1 for x in res[V[0][0]] if x[3] == c)
    print("  %-20s n=%3d  %+6.1f -> %+6.1f  (%+.1f)" % (c, n, o0, m1, m1 - o0))
d = [(m[1] - o[1]) for o, m in zip(res[V[0][0]], res[V[1][0]])]
print("\nM1 против OLD по сделкам: улучшил %d, ухудшил %d, без изменений %d; средняя разница %+.3f R; медиана %+.3f R" % (sum(x > 0.01 for x in d), sum(x < -0.01 for x in d), sum(abs(x) <= 0.01 for x in d), st.mean(d), st.median(d)))
