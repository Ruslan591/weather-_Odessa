# -*- coding: utf-8 -*-
"""Сетка (усреднение вместо стопа) по кэшу минутных путей (scripts/paths_cache.py).
Вход как был (по цене фактической сделки). Вместо стопа лимиты на доборы против позиции: n доборов через step_R * R друг от друга (R = фактический риск сделки, обычно 0.5% цены),
размер добора = size_mult ^ k от начального. Цель от СРЕДНЕЙ цены входа: +tp_R * R. Аварийный стоп (необязательный) ниже последнего добора на stop_R * R; без него позиция держится до конца данных (до 6 часов после реального выхода) и закрывается по рынку.
Издержки: вход и рыночные выходы 0.05% + 0.02% проскальзывания за сторону, лимитные доборы и цель 0.02%. Итог в % от НАЧАЛЬНОЙ суммы позиции (stake 6 $) и в долларах; смотрим хвосты: худшая сделка, сколько раз сработал аварийный стоп / добор,
какая максимальная сумма позиции потребовалась (счёт 5.87 $ с плечом 5x даёт максимум около 29 $ суммы позиций на все слоты).
Только описание прошлого на тех же данных (in-sample). Запуск на VPS как entry_study.py."""
import gzip, json, urllib.request, statistics as st

cache = json.load(gzip.open("/opt/trading-bot/cache/paths_regr.json.gz", "rt"))
snap = json.load(urllib.request.urlopen("http://127.0.0.1:18102/api/claude", timeout=30))
FEE_T, SLIP, FEE_M = 0.05, 0.02, 0.02
T = []
for p in snap["closed"]:
    c = cache.get(str(p["id"]))
    if not c or not c["ks"] or p.get("entry") is None: continue
    last_t = (p["t_in"] // 60000) * 60000; ks = [k for k in c["ks"] if k[0] > last_t]
    if len(ks) >= 5: T.append(dict(p=p, ks=ks, sd=1 if p["side"] == "long" else -1))
N = len(T); ids = sorted(t["p"]["id"] for t in T); half = ids[N // 2]
print("сделок: %d\n" % N)


def grid(t, n_add, step_R, size_mult, tp_R, stop_R):
    p = t["p"]; sd = t["sd"]; E = p["entry"]; R = p["R"]
    lots = [(E, 1.0)]                      # (цена, размер) в долях начальной суммы
    levels = [E - sd * step_R * (k + 1) * R for k in range(n_add)]; sizes = [size_mult ** (k + 1) for k in range(n_add)]
    filled = 0; stop_px = None
    if stop_R is not None: stop_px = (levels[-1] if levels else E) - sd * stop_R * R
    for k in t["ks"]:
        o, h, l = k[1], k[2], k[3]
        adverse = l if sd > 0 else h; fav = h if sd > 0 else l
        while filled < n_add and ((adverse <= levels[filled]) if sd > 0 else (adverse >= levels[filled])):
            lots.append((levels[filled], sizes[filled])); filled += 1
        size = sum(z for _, z in lots); a = sum(px * z for px, z in lots) / size; tp = a + sd * tp_R * R
        if stop_px is not None and ((adverse <= stop_px) if sd > 0 else (adverse >= stop_px)):
            ex = (min(stop_px, o) if sd > 0 else max(stop_px, o)) * (1 - sd * SLIP / 100)
            return dict(lots=lots, ex=ex, why="stop", filled=filled)
        if (fav >= tp) if sd > 0 else (fav <= tp):
            return dict(lots=lots, ex=tp, why="tp", filled=filled)
    return dict(lots=lots, ex=t["ks"][-1][4] * (1 - sd * SLIP / 100), why="time", filled=filled)


def pnl_pct(t, r):
    """% от начальной суммы позиции: валовая разница по лотам минус комиссии (вход 0.02, лимитные доборы 0.02, цель лимитом 0.02, остальные выходы 0.05; проскальзывание рыночных выходов уже в цене выхода)."""
    sd = t["sd"]; lots = r["lots"]; size = sum(z for _, z in lots)
    gross = sum(z * sd * (r["ex"] / px - 1) * 100 for px, z in lots)
    fees = 0.02 + sum(z for _, z in lots[1:]) * FEE_M + size * (FEE_M if r["why"] == "tp" else FEE_T)
    return gross - fees, size


def run(label, n_add, step_R, size_mult, tp_R, stop_R):
    rows = []
    for t in T:
        r = grid(t, n_add, step_R, size_mult, tp_R, stop_R)
        pc, size = pnl_pct(t, r); rows.append((t, r, pc, size))
    tot = sum(x[2] for x in rows); h1 = sum(x[2] for x in rows if x[0]["p"]["id"] < half)
    stake = 6.0; loss = sorted(x[2] for x in rows)
    nt = sum(1 for x in rows if x[1]["why"] == "tp"); ns = sum(1 for x in rows if x[1]["why"] == "stop"); nm = sum(1 for x in rows if x[1]["why"] == "time")
    full = sum(1 for x in rows if x[1]["filled"] == n_add and n_add)
    print("%-52s сумма %+8.1f%% (1/2: %+7.1f / %+7.1f) | цель %3.0f%% стоп %3.0f%% по времени %2.0f%% | все доборы %3.0f%% | худшая %+6.1f%% (=%+5.2f $), 5-й худший %+6.1f%%, макс. сумма %.0fx" % (
        label, tot, h1, tot - h1, 100 * nt / N, 100 * ns / N, 100 * nm / N, 100 * full / N, loss[0], stake * loss[0] / 100, loss[4], max(x[3] for x in rows)))
    return rows


print("Для сравнения: фактический итог счёта на этих сделках %+.1f%% суммы позиции (стопы 1R, БУ, трейлинг); худшая сделка %+.2f%%\n" % (sum(t["p"]["net_pct"] for t in T), min(t["p"]["net_pct"] for t in T)))
print("== Без аварийного стопа (держим до цели или до конца данных, до 6 часов после реального выхода)")
for n_add, mult in ((1, 1.0), (2, 1.0), (2, 2.0)):
    for tp_R in (0.5, 1.0):
        run("%d добор(а), размер x%.0f, шаг 1R, цель +%.1fR от средней" % (n_add, mult, tp_R), n_add, 1.0, mult, tp_R, None)
print("\n== С аварийным стопом ниже последнего добора")
for n_add, mult in ((1, 1.0), (2, 1.0), (2, 2.0)):
    for stop_R in (1.0, 2.0):
        run("%d добор(а), x%.0f, цель +0.5R, стоп ниже на %.0fR" % (n_add, mult, stop_R), n_add, 1.0, mult, 0.5, stop_R)
print("\n== Широкий шаг 1.5R с аварийным стопом 1R")
for n_add, mult in ((1, 1.0), (2, 1.0)): run("%d добор(а), x%.0f, шаг 1.5R, цель +0.5R, стоп 1R" % (n_add, mult), n_add, 1.5, mult, 0.5, 1.0)
