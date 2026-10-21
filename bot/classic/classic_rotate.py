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


def backtest(cands, look, guard, step, lo, hi):
    """Еженедельная ротация на [lo, hi): выбор по результату за look дней (guard=None — без сторожа), результат берём за следующий шаг."""
    W = step * DAY
    out = dict(net=0.0, rand=0.0, weeks=0, traded=0, pos=0, picks={})
    w = lo
    while w + W <= hi:
        sc = []
        for k, tr in cands.items():
            n, net_l = window(tr, w - look * DAY, w)
            cur, mdd = eq_state(tr, w)
            _, nxt = window(tr, w, w + W)
            sc.append((k, n, net_l, guard is not None and cur >= guard * max(mdd, 3.0), nxt))
        out["weeks"] += 1
        out["rand"] += statistics.mean(x[4] for x in sc)
        el = [x for x in sc if x[1] >= 3 and not x[3]]
        if el:
            b = max(el, key=lambda x: x[2])
            out["net"] += b[4]; out["traded"] += 1; out["pos"] += b[4] > 0
            out["picks"][b[0]] = out["picks"].get(b[0], 0) + 1
        w += W
    return out


def fixed_sum(cands, lo, hi):
    return {k: window(tr, lo, hi)[1] for k, tr in cands.items()}


def main():
    pairs = arg("--pairs", "ZECUSDT,BTCUSDT,SOLUSDT,NEARUSDT").split(",")
    tfs = arg("--tfs", "15m,30m,1h,2h,4h,6h,12h").split(",")
    days = int(arg("--days", 365)); look = int(arg("--lookback", 30)); guard = float(arg("--guard", 0.6)); step = int(arg("--step", 7))
    nodl = "--no-download" in sys.argv
    d0 = L.pair_dir("_rotation")
    cache = os.path.join(d0, "trades_cache.json")
    t_all = time.time()
    cands, info = {}, {}
    if "--cached" in sys.argv and os.path.exists(cache):
        z = json.load(open(cache))
        cands = {tuple(k.split("|")): [tuple(x) for x in v] for k, v in z["cands"].items()}
        info = {tuple(k.split("|")): v for k, v in z["info"].items()}
        print("из кэша: %d связок" % len(cands))
    else:
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
                    cands[(sym, tf)] = sorted([(int(x["t_out"]), float(x["net"])) for x in T])
                    m = L.metrics(T)
                    info[(sym, tf)] = dict(n=m["n"], net=m["net"], dd=m["dd"], bars=len(df), t0=int(df.t.iloc[min(200, len(df) - 1)]), t1=int(df.t.iloc[-1]))
                    print("%-8s %-4s баров %6d | загрузка %5.1f c, расчёт %5.1f c, симуляция %5.1f c | сделок %3d Net %+7.1f%% DD %5.1f%%" % (sym, tf, len(df), t_dl, t_pre, t_sim, m["n"], m["net"], m["dd"]), flush=True)
                except Exception as e:  # noqa: BLE001
                    print("%-8s %-4s ОШИБКА %s" % (sym, tf, str(e)[:120]), flush=True)
        json.dump({"cands": {"%s|%s" % k: v for k, v in cands.items()}, "info": {"%s|%s" % k: v for k, v in info.items()}}, open(cache, "w"))
        print("\nвремя полного прогона %d связок: %.0f c" % (len(cands), time.time() - t_all))
    if not cands:
        return
    t_end = max(v["t1"] for v in info.values()); t_beg = max(v["t0"] for v in info.values())
    print("общее окно: %s → %s" % (time.strftime("%Y-%m-%d", time.gmtime(t_beg / 1000)), time.strftime("%Y-%m-%d", time.gmtime(t_end / 1000))))
    if "--variants" in sys.argv:
        order = ["15m", "30m", "1h", "2h", "4h", "6h", "12h"]
        sets = {"все ТФ": order, "от 1h": order[2:], "от 2h": order[3:]}
        print("\n=== ВАРИАНТЫ РОТАЦИИ (Net %%, шаг %d дн.; Н1/Н2 — первая/вторая половина окна теста) ===" % step)
        for sname, tl in sets.items():
            sub = {k: v for k, v in cands.items() if k[1] in tl}
            if not sub:
                continue
            for lk in (14, 30, 60):
                lo = t_beg + (lk + 30) * DAY; mid = lo + (t_end - lo) // 2
                fx = fixed_sum(sub, lo, t_end)
                rnd = backtest(sub, lk, None, step, lo, t_end)["rand"]
                best = max(fx.items(), key=lambda kv: kv[1])
                A = backtest(sub, lk, None, step, lo, t_end); A1 = backtest(sub, lk, None, step, lo, mid); A2 = backtest(sub, lk, None, step, mid, t_end)
                row = "%-8s окно %2dд | A: %+7.1f (Н1 %+6.1f / Н2 %+6.1f) нед+ %2d/%2d" % (sname, lk, A["net"], A1["net"], A2["net"], A["pos"], A["traded"])
                for g in (0.4, 0.6, 0.8):
                    row += " | B%.0f%%: %+6.1f" % (g * 100, backtest(sub, lk, g, step, lo, t_end)["net"])
                row += " | случ. %+6.1f | лучшая фикс. %s %s %+.0f | медиана связок %+.1f" % (rnd, best[0][0][:4], best[0][1], best[1], statistics.median(fx.values()))
                print(row)
        return
    lo = t_beg + (look + 30) * DAY
    A = backtest(cands, look, None, step, lo, t_end); B = backtest(cands, look, guard, step, lo, t_end)
    print("A: %+.1f%% | B: %+.1f%% | случайная: %+.1f%%" % (A["net"], B["net"], A["rand"]))


if __name__ == "__main__":
    main()
