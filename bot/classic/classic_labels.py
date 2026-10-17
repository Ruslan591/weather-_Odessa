"""classic_labels.py — разбор разметки пользователя (labels.json): что предшествует идеальным входам/выходам. ZEC 15m, время UTC+3."""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs, classic_analysis as an
now = int(time.time() * 1000); STEP = 900 * 1000
labels = [x for x in json.load(open("/opt/trading-bot/classic/labels.json")) if x["sym"] == "ZECUSDT" and x["tf"] == "15m"]
parts, end = [], None
for _ in range(6):
    u = "https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval=15m&limit=1000" + ("&endTime=%d" % end if end else "")
    d = json.load(urllib.request.urlopen(u, timeout=20)); parts.insert(0, d); end = int(d[0][0]) - 1
df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
pre = cs.prepare(df, now); M = pre["M"]
o, h, l, c, v, atr, e20, e200, rsi, t = pre["o"], pre["h"], pre["l"], pre["c"], pre["v"], pre["atr"], pre["e20"], pre["e200"], pre["rsi"], pre["t"]
closed = df.iloc[:M].reset_index(drop=True); ind = an.indicators(closed); pats = an.detect_patterns(closed, ind)
print("пример паттерна:", pats[0] if pats else None)
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
idx = {int(x): k for k, x in enumerate(t)}
TR = {"t": "pattern", "f": "none"}; C20 = {"t": "close_ema20", "w": 12}
GA = cs.stage_signals(pre, dict(cs.PARAMS, stages=[TR, C20]))
GP = cs.stage_signals(pre, dict(cs.PARAMS, stages=[TR]))
FL = {(p[0], p[1]): p[2:] for p in pre["pfeat"]}
def pname(p):
    return p.get("name") or p.get("n") or p.get("k") or p.get("t") or "?"
def patnear(i, up, back):
    out = []
    for p in pats:
        j = p["i"]
        if i - back <= j <= i and p["d"] != 0 and (p["d"] > 0) == up:
            f = FL.get((j, up), (0,) * 6)
            fl = "".join(n for n, x in zip(("У", "О", "Э", "Р", "с16", "с48"), f) if x)
            out.append("%s %s (%d св. назад, фильтры:%s)" % (pname(p), "бык" if up else "мед", i - j, fl or "—"))
    return out
rows = sorted(labels, key=lambda x: x["t"])
trades = []; cur = None
for x in rows:
    if x["kind"] in "LS": cur = x
    elif x["kind"] == "X" and cur: trades.append((cur, x)); cur = None
print("\n=== РАЗМЕТКА: %d меток, %d сделок" % (len(rows), len(trades)))
for en, ex in trades:
    a, b = idx[en["t"]], idx[ex["t"]]; Lg = en["kind"] == "L"; sg = 1 if Lg else -1
    pnl = sg * (ex["p"] / en["p"] - 1) * 100
    seg_h, seg_l = h[a + 1:b + 1].max(), l[a + 1:b + 1].min()
    best = (seg_h if Lg else seg_l); peak = sg * (best / en["p"] - 1) * 100
    print("\n--- %s %s → выход %s: %.2f → %.2f = %+.1f%% (пик за сделку %+.1f%%, держал %.1f ч)" % ("ЛОНГ" if Lg else "ШОРТ", L3(en["t"]), L3(ex["t"]), en["p"], ex["p"], pnl, peak, (b - a) / 4))
    i = a
    ext_n = 48; ex_idx = (l[i - ext_n:i + 1].argmin() if Lg else h[i - ext_n:i + 1].argmax()); since = ext_n - ex_idx
    exv = (l[i - ext_n:i + 1].min() if Lg else h[i - ext_n:i + 1].max())
    ext16 = (l[i - 16:i + 1].min() if Lg else h[i - 16:i + 1].max())
    print("ВХОД: закр. vs EMA20 %+.2f ATR | EMA20 %s EMA200 | RSI %.0f | объём %.2f× ср.20 | тело %.2f ATR (%s) | от экстремума 12 ч: %.2f ATR (%d св. назад) | от экстремума 4 ч: %.2f ATR" % (
        (c[i] - e20[i]) / atr[i], ">" if e20[i] > e200[i] else "<", rsi[i], v[i] / pre["vavg"][i], abs(c[i] - o[i]) / atr[i], "бык" if c[i] > o[i] else "мед",
        sg * (c[i] - exv) / atr[i], since, sg * (c[i] - ext16) / atr[i]))
    pn = patnear(i, Lg, 12)
    print("  паттерны в сторону входа за 12 св. до метки:", pn if pn else "нет")
    ga = [(k, GA[k]) for k in range(i - 8, i + 9) if k in GA and GA[k][0] == en["kind"]]
    print("  цепочка бота «паттерн→закрытие за EMA20» в окне ±8 св.:", ["%s (%+d св. от метки)" % (L3(int(t[k])), k - i) for k, _ in ga] or "нет")
    print("  сколько таких сигналов цепочки в тот же день (±48 св.), сторона %s: %d" % (en["kind"], sum(1 for k, g in GA.items() if abs(k - i) <= 48 and g[0] == en["kind"])))
    print("  паттерны-сигналы той же стороны в ±48 св.: %d" % sum(1 for k, g in GP.items() if abs(k - i) <= 48 and g[0] == en["kind"]))
    j = b
    giveb = (best - ex["p"]) * sg / ((best - en["p"]) * sg + 1e-9) * 100
    wick = ((h[j] - max(o[j], c[j])) if Lg else (min(o[j], c[j]) - l[j])) / (h[j] - l[j] + 1e-9)
    print("ВЫХОД: закр. vs EMA20 %+.2f ATR | RSI %.0f | объём %.2f× | тень против позиции %.0f%% свечи | отдано от пика %.0f%% хода" % (
        (c[j] - e20[j]) / atr[j], rsi[j], v[j] / pre["vavg"][j], wick * 100, giveb))
    pe = patnear(j, not Lg, 4)
    print("  встречные паттерны за 4 св. до метки выхода:", pe if pe else "нет")
    print("  экстремум хода: %s" % L3(int(t[a + 1 + (h[a + 1:b + 1].argmax() if Lg else l[a + 1:b + 1].argmin())])))
print("\nГОТОВО")
