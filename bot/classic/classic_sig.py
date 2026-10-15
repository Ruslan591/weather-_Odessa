"""classic_pattern.py — выход по свечному паттерну разворота + вход после закрытия за EMA20 (идея пользователя), ZEC 15m.
Выход: лонг закрывается по медвежьему паттерну (падающая звезда, медвежье поглощение, вечерняя звезда), шорт — по бычьему (молот, бычье поглощение, утренняя звезда); исполнение по открытию следующей свечи.
Вход после паттерна: бычий паттерн «взводит» лонг, вход по открытию свечи после первого закрытия выше EMA20 (в пределах K свечей); медвежий — шорт, закрытие ниже EMA20. Входы по пересечению EMA20/EMA200 сохраняются.
Запуск: python classic_pattern.py [SYMBOL] [PAGES]"""
import json, os, sys, time, datetime, warnings, urllib.request
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_strategy as cs
import classic_analysis as an

SYM = sys.argv[1] if len(sys.argv) > 1 else "ZECUSDT"
PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 40
STEP = 900 * 1000
now = int(time.time() * 1000)
parts, end = [], None
for _ in range(PAGES):
    u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=15m&limit=1000" % SYM + ("&endTime=%d" % end if end else "")
    d = json.load(urllib.request.urlopen(u, timeout=20))
    if not d: break
    parts.insert(0, d); end = int(d[0][0]) - 1
    if len(d) < 1000: break
df = pd.DataFrame([r for p in parts for r in p]).iloc[:, [0, 1, 2, 3, 4, 5, 6]]
df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64"); df = df.drop_duplicates("t").reset_index(drop=True)
pre = cs.prepare(df, now)
M, c, e20, e200 = pre["M"], pre["c"], pre["e20"], pre["e200"]
closed = df.iloc[:M].reset_index(drop=True)
ind = an.indicators(closed)
pats = an.detect_patterns(closed, ind)
bull, bear = set(), set()
for p in pats:
    if p["d"] > 0: bull.add(p["i"])
    elif p["d"] < 0: bear.add(p["i"])
START = int(df.t.iloc[0]) + 450 * STEP
SPLIT = START + int((now - START) * 0.6)
d0 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")
L3 = lambda ms: datetime.datetime.fromtimestamp(ms / 1000 + 3 * 3600, datetime.UTC).strftime("%d.%m %H:%M")
print("%s 15m: %d свечей, оценка %s..%s, подбор до %s; паттернов: бычьих %d, медвежьих %d" % (SYM, len(df), d0(START), d0(now), d0(SPLIT), len(bull), len(bear)))
W = cs.PARAMS["warmup"]


def cross_sigs():
    out = {}
    for i in range(W, M):
        pr, cu = e20[i - 1] - e200[i - 1], e20[i] - e200[i]
        if pr <= 0 < cu: out[i] = "L"
        elif pr >= 0 > cu: out[i] = "S"
    return out


def pat_sigs(K):
    out = {}
    for a in sorted(bull | bear):
        if a < W: continue
        up = a in bull
        for j in range(a + 1, min(a + 1 + K, M)):
            if (up and j in bear) or ((not up) and j in bull): break
            if (up and c[j] > e20[j]) or ((not up) and c[j] < e20[j]):
                out.setdefault(j, "L" if up else "S"); break
    return out


def exit_sigs():
    out = {}
    for i in bull: out[i] = "L"
    for i in bear: out.setdefault(i, "S")
    for i in bull & bear: out.pop(i, None)
    return out



o_, h_, l_, v_, atr_ = pre["o"], pre["h"], pre["l"], df.v.values, pre["atr"]
PL = [(q["i"], q["p"], q["conf"]) for q in pre["piv"] if q["k"] == "L"]
PH = [(q["i"], q["p"], q["conf"]) for q in pre["piv"] if q["k"] == "H"]


def near_level(i, kind, price, tol):
    for pi, pp, pc in reversed(PL if kind == "L" else PH):
        if pc > i: continue
        if i - pi > 300: break
        if abs(price - pp) <= tol: return True
    return False


feat = {}
for p in pats:
    i = p["i"]
    if i < W or p["d"] == 0: continue
    up = p["d"] > 0
    f = dict(
        lvl=near_level(i, "L" if up else "H", l_[i] if up else h_[i], 0.5 * atr_[i]),
        vol=bool(v_[i] >= 1.5 * v_[i - 20:i].mean()),
        clx=bool(l_[i - 47:i + 1].min() == l_[i]) if up else bool(h_[i - 47:i + 1].max() == h_[i]),
        stc=bool((e20[i] - c[i]) >= 1.5 * atr_[i]) if up else bool((c[i] - e20[i]) >= 1.5 * atr_[i]))
    feat[i] = (up, f)
print("паттернов с признаками: %d; доли: уровень %.0f%%, объём %.0f%%, экстремум 12ч %.0f%%, растяжение от EMA20 %.0f%%" % (
    len(feat), *[100 * sum(f[k] for _, f in feat.values()) / len(feat) for k in ("lvl", "vol", "clx", "stc")]))
FILT = {
    "любой паттерн": lambda f: True,
    "у уровня": lambda f: f["lvl"],
    "объём ≥1.5×": lambda f: f["vol"],
    "экстремум 12 ч": lambda f: f["clx"],
    "растяжение ≥1.5 ATR": lambda f: f["stc"],
    "уровень + объём": lambda f: f["lvl"] and f["vol"],
    "экстремум + объём": lambda f: f["clx"] and f["vol"],
    "растяжение + объём": lambda f: f["stc"] and f["vol"],
    "любые 2 из 4": lambda f: f["lvl"] + f["vol"] + f["clx"] + f["stc"] >= 2,
}
K = 12


def build(flt):
    bu = {i for i, (up, f) in feat.items() if up and flt(f)}
    be_ = {i for i, (up, f) in feat.items() if (not up) and flt(f)}
    ex = {i: "L" for i in bu - be_}; ex.update({i: "S" for i in be_ - bu})
    arms = {}
    for a in sorted(bu | be_):
        up = a in bu
        for j in range(a + 1, min(a + 1 + K, M)):
            if (up and j in be_) or ((not up) and j in bu): break
            if (up and c[j] > e20[j]) or ((not up) and c[j] < e20[j]):
                arms.setdefault(j, "L" if up else "S"); break
    return ex, arms


CR = cross_sigs()
base = dict(cs.PARAMS, stop_mode="prev", min_stop_pct=1.5, trail_mode="none", trail_dist=0.0, pat_exit=False, be_trigger=1.0)


def stat(T):
    n = len(T)
    if not n: return None
    net = sum(x["net"] for x in T); q = {}
    for x in T:
        k = d0(x["t_in"])[:7]; q[k] = q.get(k, 0) + x["net"]
    ins = [x for x in T if x["t_in"] < SPLIT]; oos = [x for x in T if x["t_in"] >= SPLIT]
    pt = [x for x in T if x["reason"] == "паттерн"]
    return dict(n=n, net=net, avg=net / n, win=sum(x["net"] > 0 for x in T) / n * 100, gross=sum(x["gross"] for x in T),
                ex5=net - sum(sorted((x["net"] for x in T), reverse=True)[:5]), ins=sum(x["net"] for x in ins), nins=len(ins),
                oos=sum(x["net"] for x in oos), noos=len(oos), mp=sum(v > 0 for v in q.values()), mn=len(q), npt=len(pt))


def run(P, sg, ex):
    return [x for x in cs.simulate(df, now, P, pre, None, sg, ex) if x["t_in"] >= START]


def line(lab, s):
    print("%-58s %4d %+7.1f %+6.2f %3.0f%% %+7.1f %+7.1f %+7.1f(%3d) %+7.1f(%3d) %2d/%-2d %3d" % (
        lab, s["n"], s["net"], s["avg"], s["win"], s["gross"], s["ex5"], s["ins"], s["nins"], s["oos"], s["noos"], s["mp"], s["mn"], s["npt"]))


hdr = "%-58s %4s %7s %6s %4s %7s %7s %12s %12s %6s %3s" % ("вариант", "n", "net%", "avg", "win", "gross", "без5", "подбор(n)", "проверка(n)", "мес+", "пат")
print("\n== БЕЗУБЫТОК: стоп на entry ± be_lock (net ≈ +0.1%) вместо entry (net −0.1%)")
print(hdr)
for lk in (0.0, 0.2, 0.3):
    P = dict(base, be_lock=lk)
    line("БУ+1%%, замок %.1f%%, без паттернов" % lk, stat(run(P, None, None)))
P0 = dict(base, be_lock=0.2)
rows = []
pms = (0, 2, 4, 8)
for fn, ff in FILT.items():
    ex, arms = build(ff)
    mg = dict(arms); mg.update(CR)
    for tname, sg in (("перевход", mg), ("только паттерн-входы", dict(arms)), ("выход без перевхода", None)):
        for pm in pms:
            P = dict(P0, pat_min=pm)
            s = stat(run(P, sg, ex))
            if s: rows.append((fn, tname, pm, s))
print("\n== ТАБЛИЦА: net% (подбор/проверка), вход по пересечению + выход по паттерну (без перевхода), по порогу плюса")
print("%-24s" % "фильтр значимости" + "".join("%22s" % ("плюс ≥%d%%" % pm) for pm in pms))
for fn in FILT:
    r = [x for x in rows if x[0] == fn and x[1] == "выход без перевхода"]
    print("%-24s" % fn + "".join("%22s" % ("%+.0f (%+.0f/%+.0f) п%d" % (x[3]["net"], x[3]["ins"], x[3]["oos"], x[3]["npt"])) for x in sorted(r, key=lambda x: x[2])))
print("\n== ТОП-12 по подбору (смотри проверку); n — всего сделок, «пат» — паттерн-выходов")
print(hdr)
for fn, tn, pm, s in sorted(rows, key=lambda r: -r[3]["ins"])[:12]:
    line("%s | %s | ≥%d%%" % (fn, tn, pm), s)
rob = [r for r in rows if r[3]["ins"] > 0 and r[3]["oos"] > 0 and r[3]["ex5"] > 0]
print("\n== УСТОЙЧИВЫЕ (плюс на подборе и на проверке и без 5 лучших сделок): %d из %d; лучшие по сумме" % (len(rob), len(rows)))
print(hdr)
for fn, tn, pm, s in sorted(rob, key=lambda r: -(r[3]["ins"] + r[3]["oos"]))[:10]:
    line("%s | %s | ≥%d%%" % (fn, tn, pm), s)
if rob:
    fn, tn, pm, s = sorted(rob, key=lambda r: -(r[3]["ins"] + r[3]["oos"]))[0]
    ex, arms = build(FILT[fn])
    mg = dict(arms); mg.update(CR)
    sg = mg if tn == "перевход" else (dict(arms) if tn == "только паттерн-входы" else None)
    T = run(dict(P0, pat_min=pm), sg, ex)
    lo, hi = int(pd.Timestamp("2026-10-14 12:00", tz="UTC").value // 10**6), int(pd.Timestamp("2026-10-16 00:00", tz="UTC").value // 10**6)
    print("\nПример 14–15.10 (UTC+3) — %s | %s | плюс ≥%d%%" % (fn, tn, pm))
    for x in T:
        if x["t_out"] >= lo and x["t_in"] <= hi:
            print("  %s %s %.1f -> %s %.1f  %-10s net %+.2f%% %s" % ("ШОРТ" if x["side"] == "S" else "ЛОНГ", L3(x["t_in"]), x["p_in"], L3(x["t_out"]), x["p_out"], x["reason"], x["net"], "(открыта)" if x["open"] else ""))
