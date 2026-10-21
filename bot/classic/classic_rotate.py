#!/usr/bin/env python3
"""classic_rotate.py — прототип ротации «пара × таймфрейм» (без подбора параметров, текущие правила панели как есть).

Запуск: python classic_rotate.py [--pairs ZECUSDT,BTCUSDT,SOLUSDT,NEARUSDT] [--tfs 15m,30m,1h,2h,4h,6h,12h] [--days 365] [--no-download]
        [--lookback 30] [--guard 0.6] [--step 7]

Для каждой связки (пара, ТФ): один прогон текущих правил на годе истории (с замером времени), кривая результата по закрытым сделкам.
Затем исторический тест ротации: каждые --step дней выбирается связка с лучшим результатом за последние --lookback дней
(вариант A) или то же, но без связок «в просадке» (вариант B: текущая просадка от пика >= --guard × историческая максимальная, мин. 3%).
Берётся результат выбранной связки за СЛЕДУЮЩУЮ неделю. Сравнивается со случайным выбором связки и с фиксированными связками.
Живые прогоны и config.json не трогает.
"""
import os, sys, json, time, statistics
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classic_strategy as cs  # noqa: E402
import classic_learn as L  # noqa: E402

DAY = 86400000


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def eq_state(tr, w):
    """(текущая просадка от пика, максимальная просадка) по сделкам, закрытым до момента w; tr отсортирован по t_out."""
    cum = pk = mdd = 0.0
    for t_out, net in tr:
        if t_out >= w:
            break
        cum += net
        pk = max(pk, cum)
        mdd = max(mdd, pk - cum)
    return pk - cum, mdd


def window(tr, a, b):
    n = s = 0
    for t_out, net in tr:
        if a <= t_out < b:
            n += 1
            s += net
    return n, s


def main():
    pairs = arg("--pairs", "ZECUSDT,BTCUSDT,SOLUSDT,NEARUSDT").split(",")
    tfs = arg("--tfs", "15m,30m,1h,2h,4h,6h,12h").split(",")
    days = int(arg("--days", 365)); look = int(arg("--lookback", 30)); guard = float(arg("--guard", 0.6)); step = int(arg("--step", 7))
    nodl = "--no-download" in sys.argv
    d0 = L.pair_dir("_rotation")
    t_all = time.time()
    cands, info = {}, {}
    for sym in pairs:
        for tf in tfs:
            d = L.pair_dir(sym)
            try:
                t0 = time.time()
                df = pd.read_csv(os.path.join(d, "klines_%s.csv" % tf)) if nodl else L.download(sym, tf, days, d)
                t_dl = time.time() - t0
                now = int(df["ct"].iloc[-1]) + 10 ** 6
                P = L.base_params(sym, tf)
                t0 = time.time(); pre = cs.prepare(df, now); t_pre = time.time() - t0
                t0 = time.time(); T = cs.simulate(df, now, P, pre=pre); t_sim = time.time() - t0
                tr = sorted([(int(x["t_out"]), float(x["net"])) for x in T])
                cands[(sym, tf)] = tr
                m = L.metrics(T)
                info[(sym, tf)] = dict(n=m["n"], net=m["net"], dd=m["dd"], dl=t_dl, pre=t_pre, sim=t_sim, bars=len(df), t0=int(df.t.iloc[min(200, len(df) - 1)]), t1=int(df.t.iloc[-1]))
                print("%-8s %-4s баров %6d | загрузка %5.1f c, расчёт сигналов %5.1f c, симуляция %5.1f c | сделок %3d Net %+7.1f%% DD %5.1f%%" % (sym, tf, len(df), t_dl, t_pre, t_sim, m["n"], m["net"], m["dd"]), flush=True)
            except Exception as e:  # noqa: BLE001
                print("%-8s %-4s ОШИБКА %s" % (sym, tf, str(e)[:120]), flush=True)
    if not cands:
        return
    t_end = max(v["t1"] for v in info.values()); t_beg = max(v["t0"] for v in info.values())
    print("\nвремя полного прогона (загрузка + расчёт) %d связок: %.0f c" % (len(cands), time.time() - t_all))
    print("общее окно: %s → %s" % (time.strftime("%Y-%m-%d", time.gmtime(t_beg / 1000)), time.strftime("%Y-%m-%d", time.gmtime(t_end / 1000))))
    # --- исторический тест ротации
    W = step * DAY
    start = t_beg + (look + 30) * DAY
    res = {"rand": 0.0, "A": 0.0, "B": 0.0}
    weeks = wA = wB = posA = posB = 0
    picks = {}
    fixed = {k: 0.0 for k in cands}
    w = start
    while w + W <= t_end:
        sc = []
        for k, tr in cands.items():
            n, net_l = window(tr, w - look * DAY, w)
            cur, mdd = eq_state(tr, w)
            _, nxt = window(tr, w, w + W)
            sc.append((k, n, net_l, cur >= guard * max(mdd, 3.0), nxt))
            fixed[k] += nxt
        weeks += 1
        res["rand"] += statistics.mean(s[4] for s in sc)
        el = [s for s in sc if s[1] >= 3]
        if el:
            a = max(el, key=lambda s: s[2]); res["A"] += a[4]; wA += 1; posA += a[4] > 0
            picks[a[0]] = picks.get(a[0], 0) + 1
        el2 = [s for s in el if not s[3]]
        if el2:
            b = max(el2, key=lambda s: s[2]); res["B"] += b[4]; wB += 1; posB += b[4] > 0
        w += W
    print("\n=== ИСТОРИЧЕСКИЙ ТЕСТ РОТАЦИИ: шаг %d дн., выбор по результату за %d дн., сторож %.0f%% от макс. просадки ===" % (step, look, guard * 100))
    print("недель всего: %d | A (лучшая связка, без сторожа): торговали %d нед., Net %+.1f%%, плюс в %d нед." % (weeks, wA, res["A"], posA))
    print("                  B (лучшая связка, не в просадке): торговали %d нед., Net %+.1f%%, плюс в %d нед." % (wB, res["B"], posB))
    print("                  случайная связка каждую неделю (среднее по всем связкам): Net %+.1f%%" % res["rand"])
    best = sorted(fixed.items(), key=lambda kv: kv[1], reverse=True)
    print("фиксированная связка за то же окно (лучшие 5 по факту / худшие 3 / NEAR 2h):")
    for k, v in best[:5]:
        print("   %s %s: %+.1f%%" % (k[0], k[1], v))
    for k, v in best[-3:]:
        print("   %s %s: %+.1f%%" % (k[0], k[1], v))
    if ("NEARUSDT", "2h") in fixed:
        print("   NEARUSDT 2h (твоя текущая): %+.1f%%" % fixed[("NEARUSDT", "2h")])
    print("средний Net по всем связкам за окно: %+.1f%%, связок в плюсе: %d из %d" % (statistics.mean(fixed.values()), sum(1 for v in fixed.values() if v > 0), len(fixed)))
    print("чаще всего выбирались (A): " + ", ".join("%s %s ×%d" % (k[0], k[1], v) for k, v in sorted(picks.items(), key=lambda kv: -kv[1])[:5]))
    json.dump({"fixed": {"%s|%s" % k: v for k, v in fixed.items()}, "A": res["A"], "B": res["B"], "rand": res["rand"], "weeks": weeks}, open(os.path.join(d0, "rotation_%s.json" % time.strftime("%Y%m%d_%H%M")), "w"))


if __name__ == "__main__":
    main()
