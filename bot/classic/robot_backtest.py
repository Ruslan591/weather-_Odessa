# -*- coding: utf-8 -*-
"""Бэктест правил робота (прогоны track=bot из runs.json) на истории Binance за N дней.
Запуск: cd /opt/trading-bot/classic && python3 /tmp/robot_backtest.py 60
Результат: /tmp/robot_bt.json (сделки) и сводка в stdout. Цель: есть ли у входов робота преимущество ДО комиссий."""
import sys, json, time, urllib.request, collections, statistics as st, datetime
import pandas as pd
import classic_strategy as cs

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
OUT = "/tmp/robot_bt.json"
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
TFMS = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "2h": 7200000,
        "4h": 14400000, "6h": 21600000, "8h": 28800000, "12h": 43200000, "1d": 86400000}
ORDER = {"1h": 0, "4h": 1, "15m": 2, "5m": 3, "1d": 4}


def fetch(sym, tf, days):
    need = int((time.time() - days * 86400) * 1000) - 300 * TFMS[tf]
    parts, end = [], None
    for _ in range(260):
        data = None
        for b in BASES:
            try:
                url = "%s/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (b, sym, tf) + ("&endTime=%d" % end if end else "")
                data = json.load(urllib.request.urlopen(url, timeout=25))
                break
            except Exception:
                time.sleep(1.5)
        if not data:
            break
        parts.insert(0, data)
        end = int(data[0][0]) - 1
        if len(data) < 1000 or int(data[0][0]) <= need:
            break
        time.sleep(0.12)
    if not parts:
        raise RuntimeError("нет данных " + sym + " " + tf)
    df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    for col in "ohlcv":
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["ct"] = df["ct"].astype("int64")
    return df.drop_duplicates("t").sort_values("t").reset_index(drop=True)


def is_bot(cfg):
    stg = [x for x in (cfg.get("stages") or []) if x and x.get("t")]
    return bool(stg) and stg[0]["t"].startswith("tl_")


def main():
    runs = json.load(open("runs.json", encoding="utf-8"))
    items = collections.OrderedDict()
    variants = collections.defaultdict(set)
    for r in runs:
        if not is_bot(r["cfg"]):
            continue
        k = (r["sym"], r["cfg"]["tf"])
        variants[k].add(json.dumps(r["cfg"], sort_keys=True))
        items.setdefault(k, r["cfg"])
    keys = sorted(items, key=lambda k: (ORDER.get(k[1], 9), k[0]))
    print("пар/ТФ:", len(keys), "вариантов правил на пару (макс):", max(len(v) for v in variants.values()), flush=True)
    now = int(time.time() * 1000)
    frm = now - DAYS * 86400000
    allt = []
    for k in keys:
        sym, tf = k
        t0 = time.time()
        try:
            df = fetch(sym, tf, DAYS)
            P = dict(cs.PARAMS, **dict(items[k], sym=sym))
            P["sim_from_ms"] = frm
            res = cs.simulate(df, now, P)
        except Exception as e:
            print("ОШИБКА", sym, tf, str(e)[:200], flush=True)
            continue
        n = 0
        for x in res:
            if x["open"] or x["t_in"] < frm:
                continue
            y = {kk: x.get(kk) for kk in ("side", "sig", "t_in", "t_out", "p_in", "stop0", "tp", "reason", "gross", "net", "mfe", "mae")}
            y["sym"], y["tf"] = sym, tf
            y["risk_p"] = abs(x["p_in"] - x["stop0"]) / x["p_in"] * 100
            y["rew_p"] = abs(x["tp"] - x["p_in"]) / x["p_in"] * 100 if x.get("tp") else None
            allt.append(y)
            n += 1
        print("%s %s: свечей %d, сделок %d, %.0f с" % (sym, tf, len(df), n, time.time() - t0), flush=True)
        json.dump(allt, open(OUT, "w"))
    summary(allt)


def stats(v):
    n = len(v)
    if not n:
        return "n 0"
    g = [t["gross"] for t in v]
    net = [t["net"] for t in v]
    sd = st.pstdev(g) if n > 1 else 0
    se = sd / (n ** 0.5) if n > 1 else 0
    return "n %d win%% %d gross %+.3f (se %.3f, t %+.1f) net %+.3f" % (
        n, round(100 * sum(1 for x in net if x > 0) / n), sum(g) / n, se, (sum(g) / n) / se if se else 0, sum(net) / n)


def summary(T):
    print("\n==== СВОДКА: %d сделок за %d дней" % (len(T), DAYS))
    print("всего:", stats(T))

    def grp(f, name):
        g = collections.defaultdict(list)
        for t in T:
            g[f(t)].append(t)
        print("==", name)
        for k in sorted(g, key=str):
            print("  ", k, stats(g[k]))
    grp(lambda t: t["tf"], "ТФ")
    grp(lambda t: t["sig"], "сигнал (k пробой / b отбой)")
    grp(lambda t: (t["sig"], t["side"]), "сигнал+сторона")
    grp(lambda t: (t["tf"], t["sig"]), "ТФ+сигнал")
    d0 = min(t["t_in"] for t in T) if T else 0
    grp(lambda t: "нед%d" % ((t["t_in"] - d0) // (7 * 86400000)), "по неделям (стабильность)")
    g = collections.defaultdict(list)
    for t in T:
        g[t["sym"]].append(t)
    print("== по монетам (gross средний, n)")
    for k, v in sorted(g.items(), key=lambda kv: sum(t["gross"] for t in kv[1]) / len(kv[1])):
        print("  ", k, len(v), "%+.3f" % (sum(t["gross"] for t in v) / len(v)))
    S = [t for t in T if t["reason"] in ("стоп", "цель") and t["rew_p"]]
    if S:
        exp = sum(t["risk_p"] / (t["risk_p"] + t["rew_p"]) for t in S)
        act = sum(1 for t in S if t["reason"] == "цель")
        print("стоп/цель: n %d, целей фактически %d, ожидалось при случайном блуждании %.1f" % (len(S), act, exp))
    for fee in (0.10, 0.07, 0.04):
        print("если комиссия за круг %.2f%%: net на сделку %+.3f" % (fee, sum(t["gross"] for t in T) / len(T) - fee))
    print("медиана стопа %%: %.3f" % st.median([t["risk_p"] for t in T]))


if __name__ == "__main__":
    main()
