# -*- coding: utf-8 -*-
"""Исследование: канал бота (Auto 40..350) против Fixed 100 в момент входа, по закрытым сделкам счёта «Регрессия».
Для каждой сделки: окно Auto (из заявки), ширина Auto в ATR, положение входа в Auto; канал Fixed 100 по 100 закрытым 5m свечам до входа (регрессия по close, +-2 sigma, n-2),
положение входа в Fixed, запас хода до противоположной границы Fixed, согласие направления Fixed со сделкой. Итоги по группам: доля стопов, целей, средний R.
Запуск на VPS: /opt/trading-bot/venv/bin/python chan_combo_study.py [POS_DIR] ; результат в stdout. Только чтение."""
import json, sys, time, urllib.request, collections
import numpy as np

POS = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/positions_regr"
KL = "https://data-api.binance.vision/api/v3/klines"
IV = 300000


def get(u, tries=3):
    for i in range(tries):
        try: return json.load(urllib.request.urlopen(u, timeout=20))
        except Exception: time.sleep(1.5)
    return None


def reg_channel(closes, k=2.0):
    n = len(closes); x = np.arange(n, dtype=float); b, a = np.polyfit(x, closes, 1)
    line = a + b * x; res = closes - line; sig = float(np.sqrt((res ** 2).sum() / max(1, n - 2)))
    mid = a + b * (n - 1)
    return dict(slope=float(b), mid=float(mid), up=float(mid + k * sig), lo=float(mid - k * sig), sig=sig)


snap = get("http://127.0.0.1:18102/api/claude")
orders = {o["id"]: o for o in json.load(open(POS + "/orders.json", encoding="utf-8")) if o.get("chan")}
rows = []; miss = 0
for p in snap["closed"]:
    o = orders.get(p.get("order_id"))
    if not o or not p.get("t_in") or p.get("entry") is None: miss += 1; continue
    ch = o["chan"]; t = p["t_in"]; u, l = ch["upper"], ch["lower"]; upv = u["p1"] + u["s"] * (t - u["t1"]); lov = l["p1"] + l["s"] * (t - l["t1"])
    atr = o.get("atr") or 0; e = p["entry"]; sgn = 1 if p["side"] == "long" else -1
    r = dict(id=p["id"], sym=p["sym"], side=p["side"], rule=p.get("rule"), reason=str(p.get("reason")), R=p.get("r_mult") or 0.0, net=p.get("net_pct") or 0.0,
             mfe=p.get("mfe_pct") or 0.0, mae=p.get("mae_pct") or 0.0, win_n=(t - u["t1"]) / IV, width_atr=(upv - lov) / atr if atr else None,
             pos_auto=(e - lov) / (upv - lov) if upv > lov else None, ctype=ch.get("type"))
    end = (t // IV) * IV - 1
    kl = get("%s?symbol=%s&interval=5m&limit=100&endTime=%d" % (KL, p["sym"], end))
    time.sleep(0.12)
    if not kl or len(kl) < 100: miss += 1; continue
    c = np.array([float(k[4]) for k in kl]); f = reg_channel(c); rng = f["up"] - f["lo"]
    if rng <= 0: miss += 1; continue
    r["pos_fix"] = (e - f["lo"]) / rng
    r["room"] = (e - f["lo"]) / rng if p["side"] == "short" else (f["up"] - e) / rng      # сколько хода осталось до противоположной границы Fixed
    r["fix_dir"] = 1 if f["slope"] > 0 else -1
    r["agree"] = (r["fix_dir"] == sgn)
    r["width_fix_atr"] = rng / atr if atr else None
    r["ratio"] = (upv - lov) / rng                       # какую часть Fixed занимает Auto
    rows.append(r)
print("trades with data: %d, skipped: %d, total closed: %d" % (len(rows), miss, len(snap["closed"])))


def stat(g):
    n = len(g)
    if not n: return "n=0"
    st = sum(1 for x in g if x["reason"] == "stop"); tg = sum(1 for x in g if x["reason"] == "target"); be = sum(1 for x in g if x["reason"].startswith("trail"))
    return "n=%3d  stop %3.0f%%  trail/BE %3.0f%%  target %3.0f%%  avgR %+.2f  avgMFE %.2f%%  sumR %+.1f" % (n, st / n * 100, be / n * 100, tg / n * 100, sum(x["R"] for x in g) / n, sum(x["mfe"] for x in g) / n, sum(x["R"] for x in g))


def table(title, key, edges, labels=None):
    print("\n== " + title)
    for i in range(len(edges) - 1):
        g = [x for x in rows if x.get(key) is not None and edges[i] <= x[key] < edges[i + 1]]
        print("  %-18s %s" % ((labels[i] if labels else "%g..%g" % (edges[i], edges[i + 1])), stat(g)))


print("\n== all trades:  " + stat(rows))
for rule in sorted({x["rule"] for x in rows}): print("  rule %-12s %s" % (rule, stat([x for x in rows if x["rule"] == rule])))
table("Auto: длина окна, свечей (чем меньше, тем уже и круче канал)", "win_n", [0, 60, 100, 160, 260, 1e9], ["<60", "60-100", "100-160", "160-260", ">260"])
table("Auto: ширина канала в ATR", "width_atr", [0, 4, 7, 11, 18, 1e9])
table("Доля Auto от Fixed100 по высоте (меньше 0.5: Auto узкий внутри широкого)", "ratio", [0, 0.25, 0.5, 0.8, 1.2, 1e9])
table("Fixed100: запас хода до противоположной границы (0 = упёрлись, 1 = вся высота впереди)", "room", [-9, 0.1, 0.3, 0.5, 0.7, 1.1, 9])
print("\n== Fixed100: направление наклона относительно сделки")
for a, lab in ((True, "наклон Fixed ПО ходу сделки"), (False, "наклон Fixed ПРОТИВ сделки")): print("  %-30s %s" % (lab, stat([x for x in rows if x["agree"] == a])))
print("\n== Комбинации (Fixed100 + Auto)")
combos = [("по ходу Fixed и запас >=0.5", lambda x: x["agree"] and x["room"] >= 0.5), ("по ходу Fixed и запас <0.5", lambda x: x["agree"] and x["room"] < 0.5),
          ("против Fixed и запас >=0.5", lambda x: (not x["agree"]) and x["room"] >= 0.5), ("против Fixed и запас <0.5", lambda x: (not x["agree"]) and x["room"] < 0.5),
          ("Auto уже 0.5 Fixed, запас <0.3", lambda x: x["ratio"] < 0.5 and x["room"] < 0.3), ("Auto уже 0.5 Fixed, запас >=0.3", lambda x: x["ratio"] < 0.5 and x["room"] >= 0.3),
          ("окно Auto <100 и запас <0.5", lambda x: x["win_n"] < 100 and x["room"] < 0.5), ("окно Auto >=100 и запас >=0.5", lambda x: x["win_n"] >= 100 and x["room"] >= 0.5)]
for lab, f in combos: print("  %-34s %s" % (lab, stat([x for x in rows if f(x)])))
print("\n== Шорты и лонги отдельно")
for sd in ("short", "long"): print("  %-6s %s" % (sd, stat([x for x in rows if x["side"] == sd])))
print("\nmedians: win_n %.0f, width_atr %.1f, ratio %.2f, room %.2f, MFE stop-trades %.2f%%, MAE stop-trades %.2f%%" % (
    np.median([x["win_n"] for x in rows]), np.median([x["width_atr"] for x in rows if x["width_atr"]]), np.median([x["ratio"] for x in rows]), np.median([x["room"] for x in rows]),
    np.median([x["mfe"] for x in rows if x["reason"] == "stop"] or [0]), np.median([x["mae"] for x in rows if x["reason"] == "stop"] or [0])))
