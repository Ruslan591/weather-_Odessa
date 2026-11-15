# -*- coding: utf-8 -*-
"""Исследование по мотивам ZEC (шорты отбоем у верхней линии нисходящего канала, пока цена внутри шла вверх и дала пробой):
1) серии стопов по одной паре и стороне: правило «после K стопов подряд по паре и стороне в течение H часов не входить» (честно вперёд: только закрытая ДО входа история), по фактическим итогам;
2) конфликт с локальным ходом цены: движение цены за последние 2 часа до входа в R сделки (минус = цена шла против нашей стороны), по кэшу минутных путей (scripts/paths_cache.py).
Запуск на VPS: python3 zec_study.py (нужны кэш путей и acct-api)."""
import gzip, json, time, urllib.request
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
P = sorted([p for p in snap["closed"] if p.get("t_in") and p.get("t_out")], key=lambda p: p["t_in"]); N = len(P)
R = lambda p: p.get("r_mult") or 0.0
print("закрытых сделок %d, сумма %+.1f R\n" % (N, sum(R(p) for p in P)))
z = [p for p in P if p["sym"] == "ZECUSDT"]
print("== ZEC: сделок %d, стопов %d, сумма %+.1f R; шорты %d (%+.1f R), лонги %d (%+.1f R)" % (len(z), sum(p["reason"] == "stop" for p in z), sum(R(p) for p in z),
      sum(p["side"] == "short" for p in z), sum(R(p) for p in z if p["side"] == "short"), sum(p["side"] == "long" for p in z), sum(R(p) for p in z if p["side"] == "long")))
best = cur = 0; ids = []
for p in z:
    if p["side"] == "short" and p["reason"] == "stop": cur += 1; ids.append(p["id"])
    else: cur = 0; ids = []
    best = max(best, cur)
print("   самая длинная серия стопов подряд по шортам ZEC: %d\n" % best)

print("== 1. Выключатель по серии стопов (пара + сторона), история только до входа")
for K in (1, 2, 3):
    for H in (2, 6, 24):
        skip = []; 
        for i, p in enumerate(P):
            prev = [q for q in P[:i] if q["sym"] == p["sym"] and q["side"] == p["side"] and q["t_out"] < p["t_in"]][-K:]
            if len(prev) == K and all(q["reason"] == "stop" for q in prev) and p["t_in"] - prev[-1]["t_out"] < H * 3600000: skip.append(p)
        print("   после %d стоп(а) подряд, пауза %2d ч: пропущено %3d сделок, их сумма %+6.1f R (средняя %+.2f R) => итог счёта %+.1f R вместо %+.1f R" % (
            K, H, len(skip), sum(R(p) for p in skip), sum(R(p) for p in skip) / max(1, len(skip)), sum(R(p) for p in P) - sum(R(p) for p in skip), sum(R(p) for p in P)))

print("\n== 2. Движение цены за 2 часа до входа в R сделки (плюс = в нашу сторону, минус = против)")
rows = []
for p in P:
    c = cache.get(str(p["id"]))
    if not c: continue
    ks = c["ks"]; before = [k for k in ks if k[0] <= (p["t_in"] // 60000) * 60000]
    if len(before) < 100: continue
    sd = 1 if p["side"] == "long" else -1
    m2 = sd * (p["entry"] / before[-120][4] - 1) * 100 / p["R_pct"] if len(before) >= 120 else None
    m1 = sd * (p["entry"] / before[-60][4] - 1) * 100 / p["R_pct"]
    rows.append((p, m1, m2))
def bucket(label, idx, edges):
    print("  " + label)
    for a, b in zip(edges, edges[1:]):
        g = [(p, m) for p, *ms in [(r[0], r[idx]) for r in rows] for m in [ms[0]] if m is not None and a <= m < b]
        if not g: continue
        print("    %6.1f..%-6.1f n=%3d  стоп %3.0f%%  средний R %+.2f  сумма %+6.1f R" % (a, b, len(g), 100 * sum(p["reason"] == "stop" for p, _ in g) / len(g), sum(R(p) for p, _ in g) / len(g), sum(R(p) for p, _ in g)))
bucket("за 1 час:", 1, [-99, -6, -3, -1, 0, 1, 3, 99])
bucket("за 2 часа:", 2, [-99, -8, -4, -2, 0, 2, 4, 99])
for thr in (-2, -4, -6):
    s = [p for p, m1, m2 in rows if m2 is not None and m2 < thr]
    print("   отсечь входы, когда за 2 часа цена шла против нас больше %d R: отсекается %d сделок, сумма %+.1f R (средняя %+.2f R)" % (-thr, len(s), sum(R(p) for p in s), sum(R(p) for p in s) / max(1, len(s))))
zz = [(p, m1, m2) for p, m1, m2 in rows if p["sym"] == "ZECUSDT"]
print("   ZEC (в выборке %d): " % len(zz) + "; ".join("#%d %s за 2ч %s R итог %+.2f" % (p["id"], p["side"], "%.1f" % m2 if m2 is not None else "-", R(p)) for p, m1, m2 in zz[-6:]))
