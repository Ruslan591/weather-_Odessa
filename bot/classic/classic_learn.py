#!/usr/bin/env python3
"""classic_learn.py — самообучение пары (шаги 1–2): год истории -> папка пары -> подбор параметров стопа/цели/безубытка -> отчёт.

Запуск:  python classic_learn.py NEARUSDT [tf] [--days 365] [--n 500] [--no-download]

Что делает:
 1. pairs/<ПАРА>/klines_<tf>.csv — история за N дней (докачивается, не перекачивается).
 2. Берёт текущие правила панели (config.json) как базу: ПРАВИЛА ВХОДА остаются как есть, подбираются только
    параметры стопа по каналу, цели, безубытка (ch_stop_atr, ch_min_stop_pct, ch_tp_gap_pct, be_trigger, be_lock, цель).
 3. Год делится по времени: первые 70% — ПОДБОР, последние 30% — ПРОВЕРКА (на ней настройки не подбирались).
 4. Пишет pairs/<ПАРА>/best_<tf>.json (кандидат) и tune_<tf>.json (все варианты). config.json и живые прогоны НЕ трогает.
"""
import os, sys, json, time, math, random, urllib.request, urllib.error
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classic_strategy as cs  # noqa: E402

PAIRS_DIR = os.environ.get("CLASSIC_PAIRS_DIR") or os.path.join(HERE, "pairs")
CONFIG_FILE = os.environ.get("CLASSIC_CONFIG_FILE") or os.path.join(HERE, "config.json")
TFMS = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000, "6h": 21600000, "12h": 43200000, "1d": 86400000}
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
TRAIN_FRAC = 0.7

# пространство поиска: только стоп/цель/безубыток (вход не трогаем)
SPACE = {
    "ch_stop_atr": [0.0, 1.0, 2.0, 3.0, 4.0],
    "ch_min_stop_pct": [0.5, 1.0, 1.5, 2.5],
    "ch_tp_gap_pct": [0.0, 0.1, 0.3, 0.6],
    "be_trigger": [0.5, 1.0, 1.5, 2.0, 3.0],
    "be_lock": [0.0, 0.3, 0.5],
    "tp": [("channel", 0.0), ("r", 1.5), ("r", 2.5)],
}


def pair_dir(sym):
    d = os.path.join(PAIRS_DIR, sym)
    os.makedirs(d, exist_ok=True)
    return d


def log(d, msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(os.path.join(d, "learn.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _get(path, params):
    last = None
    for host in HOSTS:
        for k in range(3):
            try:
                u = host + path + "?" + "&".join("%s=%s" % kv for kv in params.items())
                with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "classic-learn"}), timeout=20) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5)
    raise RuntimeError("Binance недоступен: %s" % last)


def download(sym, tf, days, d):
    """Докачивает klines_<tf>.csv до последней закрытой свечи; хранит не больше days дней."""
    fn = os.path.join(d, "klines_%s.csv" % tf)
    step = TFMS[tf]
    now = int(time.time() * 1000)
    df = pd.read_csv(fn) if os.path.exists(fn) else None
    start = int(df["t"].iloc[-1]) + step if df is not None and len(df) else now - days * 86400000 - 250 * step
    rows = []
    while start < now:
        data = _get("/api/v3/klines", {"symbol": sym, "interval": tf, "startTime": start, "limit": 1000})
        if not data:
            break
        rows += [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), int(x[6])) for x in data]
        start = int(data[-1][0]) + step
        if len(data) < 1000:
            break
        time.sleep(0.15)
    new = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct"])
    df = pd.concat([df, new]) if df is not None else new
    df = df.drop_duplicates("t").sort_values("t")
    df = df[df["ct"] < now]  # только закрытые свечи
    df = df[df["t"] >= now - (days * 86400000 + 250 * step)].reset_index(drop=True)
    df.to_csv(fn, index=False)
    return df


def base_params(sym, tf):
    P = dict(cs.PANEL)
    try:
        P.update({k: v for k, v in json.load(open(CONFIG_FILE, encoding="utf-8")).items() if k in cs.PARAMS or k in P or k in ("stages",)})
    except Exception:
        pass
    P.update(tf=tf, sym=sym, window_h=10 ** 7, period_from="", period_to="", hand_forward=False)
    P.pop("sim_from_ms", None)
    return P


def metrics(T, lo=None, hi=None):
    """Net% по закрытию сделок, макс. просадка (по закрытым сделкам, как на панели), серия убытков."""
    X = [x for x in T if (lo is None or x["t_in"] >= lo) and (hi is None or x["t_in"] < hi)]
    X.sort(key=lambda x: x["t_out"])
    cum = pk = dd = 0.0
    worst_from = worst_to = pk_t = 0
    wins = 0
    strk = wstrk = 0
    for x in X:
        cum += x["net"]
        wins += x["net"] > 0
        if cum > pk:
            pk, pk_t = cum, x["t_out"]
        if pk - cum > dd:
            dd, worst_from, worst_to = pk - cum, pk_t, x["t_out"]
        strk = strk + 1 if x["net"] <= 0 else 0
        wstrk = max(wstrk, strk)
    return dict(n=len(X), net=round(cum, 2), dd=round(dd, 2), win=round(wins / len(X) * 100) if X else 0, strk=wstrk,
                dd_from=worst_from, dd_to=worst_to)


def apply(P0, c):
    P = dict(P0)
    P.update(stop_mode="channel", ch_stop_pct=0.0)
    for k, v in c.items():
        if k == "tp":
            P["tp_mode"], P["tp_r"] = v
        else:
            P[k] = v
    return P


G = {}


def _run(c):
    T = cs.simulate(G["df"], G["now"], apply(G["P0"], c), pre=G["pre"])
    cut, t0, t1 = G["cut"], G["t0"], G["t1"]
    tr = metrics(T, None, cut)
    te = metrics(T, cut, None)
    third = (cut - t0) / 3
    blocks = [metrics(T, t0 + i * third, t0 + (i + 1) * third)["net"] for i in range(3)]
    full = metrics(T)
    return dict(c=c, tr=tr, te=te, full=full, blocks=blocks, quarters=[metrics(T, t0 + i * (t1 - t0) / 4, t0 + (i + 1) * (t1 - t0) / 4)["net"] for i in range(4)])


def score(r):
    return r["tr"]["net"] / max(r["tr"]["dd"], 3.0)


def ok(r, min_n):
    return r["tr"]["n"] >= min_n and sum(1 for b in r["blocks"] if b > 0) >= 2


def fmt_c(c):
    return "стоп={}ATR мин{}% | цель={} отступ{}% | БУ {}% лок {}%".format(
        c["ch_stop_atr"], c["ch_min_stop_pct"], ("канал" if c["tp"][0] == "channel" else "%sR" % c["tp"][1]), c["ch_tp_gap_pct"], c["be_trigger"], c["be_lock"])


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sym = a[0].upper() if a else "NEARUSDT"
    tf = a[1] if len(a) > 1 else "2h"
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 365
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 500
    d = pair_dir(sym)
    if "--no-download" in sys.argv:
        df = pd.read_csv(os.path.join(d, "klines_%s.csv" % tf))
    else:
        log(d, "скачиваю %s %s за %d дн." % (sym, tf, days))
        df = download(sym, tf, days, d)
    log(d, "свечей: %d (%s → %s)" % (len(df), time.strftime("%Y-%m-%d", time.gmtime(df.t.iloc[0] / 1000)), time.strftime("%Y-%m-%d", time.gmtime(df.t.iloc[-1] / 1000))))
    now = int(df["ct"].iloc[-1]) + 10 ** 6
    P0 = base_params(sym, tf)
    pre = cs.prepare(df, now)
    warm = int(P0.get("warmup", 200))
    t0, t1 = int(df["t"].iloc[min(warm, len(df) - 1)]), int(df["t"].iloc[-1])
    G.update(df=df, now=now, P0=P0, pre=pre, t0=t0, t1=t1, cut=int(t0 + TRAIN_FRAC * (t1 - t0)))
    # базовая конфигурация = как сейчас в панели
    base_c = {"ch_stop_atr": P0.get("ch_stop_atr", 3.0), "ch_min_stop_pct": P0.get("ch_min_stop_pct", 1.0), "ch_tp_gap_pct": P0.get("ch_tp_gap_pct", 0.1),
              "be_trigger": P0.get("be_trigger", 1.0), "be_lock": P0.get("be_lock", 0.5),
              "tp": ("channel", 0.0) if P0.get("tp_mode") == "channel" else ("r", float(P0.get("tp_r", 0.0)))}
    random.seed(7)
    keys = list(SPACE)
    cands, seen = [base_c], {json.dumps(base_c, sort_keys=True, default=list)}
    tries = 0
    while len(cands) < n and tries < n * 20:
        tries += 1
        c = {k: random.choice(SPACE[k]) for k in keys}
        s = json.dumps(c, sort_keys=True, default=list)
        if s not in seen:
            seen.add(s)
            cands.append(c)
    log(d, "вход (из панели): стадии=%s; кандидатов: %d; подбор до %s" % ([x["t"] for x in P0.get("stages", []) if x.get("t")], len(cands), time.strftime("%Y-%m-%d", time.gmtime(G["cut"] / 1000))))
    t_start = time.time()
    res = []
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=max(1, min(2, os.cpu_count() or 1))) as ex:
        for i, r in enumerate(ex.map(_run, cands, chunksize=4)):
            res.append(r)
            if (i + 1) % 100 == 0:
                log(d, "посчитано %d/%d (%.0f c)" % (i + 1, len(cands), time.time() - t_start))
    base = res[0]
    min_n = max(20, int(base["tr"]["n"] * 0.5))
    good = sorted([r for r in res if ok(r, min_n)], key=score, reverse=True)
    best = good[0] if good else None
    # диагностика переобучения: ранговая корреляция «оценка на подборе» -> «Net на проверке»
    sc = pd.Series([score(r) for r in res]); te = pd.Series([r["te"]["net"] for r in res])
    rho = float(sc.rank().corr(te.rank())) if len(res) > 5 else float("nan")
    top5 = good[:5]
    out = dict(sym=sym, tf=tf, days=days, tuned_at=int(time.time() * 1000), train_to_ms=G["cut"], t0=t0, t1=t1, candidates=len(res), min_trades_train=min_n,
               rank_corr_train_vs_test=round(rho, 3), base=base, best=best, top5=top5,
               status="кандидат, НЕ применено: проверить на «проверке» и на других окнах")
    json.dump(out, open(os.path.join(d, "best_%s.json" % tf), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=list)
    json.dump(res, open(os.path.join(d, "tune_%s.json" % tf), "w", encoding="utf-8"), ensure_ascii=False, default=list)

    def line(name, r):
        return "%-9s подбор: %3d сд %+7.2f%% DD %5.2f%% | ПРОВЕРКА: %3d сд %+7.2f%% DD %5.2f%% win %d%% | блоки подбора %s | кварталы %s" % (
            name, r["tr"]["n"], r["tr"]["net"], r["tr"]["dd"], r["te"]["n"], r["te"]["net"], r["te"]["dd"], r["te"]["win"],
            "/".join("%+.0f" % b for b in r["blocks"]), "/".join("%+.0f" % q for q in r["quarters"]))
    log(d, "=== ОТЧЁТ %s %s ===" % (sym, tf))
    log(d, line("БАЗА", base) + "  [" + fmt_c(base["c"]) + "]")
    for i, r in enumerate(top5):
        log(d, line("топ%d" % (i + 1), r) + "  [" + fmt_c(r["c"]) + "]")
    log(d, "ранговая корреляция «оценка на подборе → результат на проверке» по %d вариантам: %.2f (≈0 или меньше — подбор не переносится на новые данные)" % (len(res), rho))
    pos_te = sum(1 for r in res if r["te"]["net"] > 0)
    log(d, "вариантов с плюсом на проверке: %d из %d; средний Net на проверке: %+.2f%%; база: %+.2f%%" % (pos_te, len(res), float(te.mean()), base["te"]["net"]))
    log(d, "готово за %.0f c" % (time.time() - t_start))


if __name__ == "__main__":
    main()
