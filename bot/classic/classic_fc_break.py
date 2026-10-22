"""classic_fc_break.py БАЗА СТАРШИЙ [ПАРЫ] — ПРОБОЙ быстрого канала (tl_breakout, tl_src=fast): тренд старшего ТФ x выходы x подтверждение.
Пробой = закрытие свечи за границей канала; сделка по тренду старшего ТФ (лонг — пробой вверх при тренде вверх, шорт — вниз при тренде вниз).
Стоп/цель «по каналу» для пробоя не годятся (цель — противоположная линия оказывается позади цены), поэтому проверяем стопы sig3/prev/pivot и цель tp_r (в R)."""
import sys, os
sys.path.insert(0, "/opt/trading-bot/classic")
import numpy as np, pandas as pd
import classic_strategy as cs, classic_learn as L, classic_fastchan as fchan
base_tf, htf = sys.argv[1], sys.argv[2]
pairs = sys.argv[3].split(",") if len(sys.argv) > 3 else ["NEARUSDT", "SOLUSDT", "BTCUSDT", "ZECUSDT", "BNBUSDT"]
B = "/opt/trading-bot/classic/pairs"
ema = lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean().values
orig = fchan.fc_signals
EXITS = [("sig3", 2.0), ("sig3", 0.0), ("prev", 2.0), ("pivot", 2.0), ("sig3", 1.0)]
CONF = [None, ("volume", 0, 3), ("strong_body", 0, 3)]
acc = {}
for sym in pairs:
    f1, f2 = "%s/%s/klines_%s.csv" % (B, sym, base_tf), "%s/%s/klines_%s.csv" % (B, sym, htf)
    if not (os.path.exists(f1) and os.path.exists(f2)):
        continue
    df = pd.read_csv(f1); hd = pd.read_csv(f2); now = int(df.ct.iloc[-1]) + 10 ** 6
    hc = hd.c.values.astype(float); e200, e50 = ema(hc, 200), ema(hc, 50)
    tr = {"e200": np.sign(hc - e200), "slope": np.sign(e50 - np.r_[np.full(5, e50[0]), e50[:-5]])}
    j = np.searchsorted(hd.ct.values, df.t.values, side="right") - 1
    j[j < 200] = 200
    P0 = L.base_params(sym, base_tf)
    warm = int(P0.get("warmup", 200)); t0, t1 = int(df.t.iloc[warm]), int(df.t.iloc[-1]); cut = int(t0 + 0.7 * (t1 - t0))
    for name in [None, "e200", "slope"]:
        def patched(o, h, l, c, atr, M, kind, p=0.0, minw=1.5, maxw=8.0, info=None, cfg=None, start=60, _n=name):
            inf = {} if info is not None else None
            out = orig(o, h, l, c, atr, M, kind, p, minw, maxw, info=inf, cfg=cfg, start=start)
            res = {}
            for i, s in out.items():
                if _n is None or (tr[_n][j[i]] > 0 and s == "L") or (tr[_n][j[i]] < 0 and s == "S"):
                    res[i] = s
                    if info is not None: info[i] = inf[i]
            return res
        fchan.fc_signals = patched
        for sm, tpr in EXITS:
            for cf in CONF:
                stg = [{"t": "tl_breakout", "p": 0, "w": 0, "f": "none"}] + ([{"t": cf[0], "p": cf[1], "w": cf[2], "f": "none"}] if cf else [])
                P = dict(P0, tl_src="fast", stages=stg, entry_mode="stages", stop_mode=sm, tp_mode="r", tp_r=tpr, sym=sym)
                pre = cs.prepare(df, now)
                try:
                    T = cs.simulate(df, now, P, pre=pre)
                    a, b = L.metrics(T, None, cut), L.metrics(T, cut, None)
                except Exception as e:
                    print(sym, name, sm, tpr, cf, "err", repr(e)[:100]); continue
                k = "%s|%s tp%.1f|%s" % (name or "-", sm, tpr, cf[0] if cf else "-")
                r = acc.setdefault(k, {"na": 0, "nta": 0.0, "nb": 0, "ntb": 0.0, "ddb": 0.0, "plus": 0, "pairs": 0, "per": []})
                r["na"] += a["n"]; r["nta"] += a["net"]; r["nb"] += b["n"]; r["ntb"] += b["net"]; r["ddb"] = max(r["ddb"], b["dd"]); r["pairs"] += 1; r["plus"] += 1 if b["net"] > 0 else 0
                r["per"].append("%s%+.0f" % (sym[:3], b["net"]))
    fchan.fc_signals = orig
    print(sym, "готово", flush=True)
print("ПРОБОЙ: база %s / старший %s, пар %d | тренд|стоп tp|подтв. | подбор (сд, %%net) | проверка (сд, %%net, DD, пар в плюсе) | по парам" % (base_tf, htf, len(pairs)))
rows = sorted(acc.items(), key=lambda kv: -kv[1]["ntb"])
for k, r in rows[:10] + [("...", None)] + rows[-3:]:
    if r is None: print("..."); continue
    print("%-26s %5d %+8.1f | %5d %+8.1f DD%5.1f %d/%d | %s" % (k, r["na"], r["nta"], r["nb"], r["ntb"], r["ddb"], r["plus"], r["pairs"], " ".join(r["per"])))
nof = [(k, r) for k, r in acc.items() if k.startswith("-|")]
print("без фильтра по тренду, лучшее по проверке:")
for k, r in sorted(nof, key=lambda kv: -kv[1]["ntb"])[:3]:
    print("%-26s %5d %+8.1f | %5d %+8.1f DD%5.1f %d/%d" % (k, r["na"], r["nta"], r["nb"], r["ntb"], r["ddb"], r["plus"], r["pairs"]))
