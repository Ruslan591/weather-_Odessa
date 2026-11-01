# -*- coding: utf-8 -*-
"""Issledovanie listingov Binance (spot): chastota po obyavleniyam 'Will List', lead-time obyavlenie->start torgov, put' ceny v pervye minuty/chasy. ASCII output.
Ogranicheniya: tolko pary, kotorye eshche torgujutsya (vyzhivshie); pervaya svecha chasto ekstremal'naya - real'nyj vhod vozmozhen lish' posle nee."""
import json, re, time, urllib.request, collections, statistics as st, datetime as dt
UA = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
arts = []
for pg in range(1, 13):
    try:
        a = get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=%d&pageSize=50" % pg)
        x = a["data"]["catalogs"][0]["articles"]
    except Exception as e:
        print("page", pg, "failed", type(e).__name__); break
    if not x: break
    arts += x; time.sleep(0.5)
print("announcements fetched:", len(arts), "oldest", dt.datetime.fromtimestamp(arts[-1]["releaseDate"] / 1000, dt.UTC).strftime("%Y-%m-%d"))
wl = [x for x in arts if "Will List" in x["title"] and "Futures" not in x["title"]]
bm = collections.Counter(dt.datetime.fromtimestamp(x["releaseDate"] / 1000, dt.UTC).strftime("%Y-%m") for x in wl)
print("'Will List' announcements per month:", sorted(bm.items()))
B = "https://data-api.binance.vision"
rows = []
for x in wl:
    m = re.search(r"\(([A-Z0-9]{2,15})\)", x["title"])
    if not m: continue
    sym = m.group(1) + "USDT"; rel = x["releaseDate"]
    try:
        k = get(B + "/api/v3/klines?symbol=%s&interval=1m&startTime=0&limit=1000" % sym)
    except Exception as e:
        continue
    time.sleep(0.3)
    if len(k) < 70: continue
    t0 = int(k[0][0]); o = [float(c[1]) for c in k]; h = [float(c[2]) for c in k]; l = [float(c[3]) for c in k]; c_ = [float(c[4]) for c in k]
    if t0 < rel - 3600000: continue  # para torgovalas do obyavleniya (ne novyj listing)
    rows.append(dict(sym=sym, rel=rel, lead_h=(t0 - rel) / 3600000.0, t0=t0, o0=o[0], c0=c_[0], r_c0=c_[0] / o[0] - 1, hi15=max(h[:15]) / c_[0] - 1,
                     # vhod po zakrytiyu 1-j minuty (bystryj bot) i po zakrytiyu 5-j minuty (realnyj vhod) -> vyhod cherez N minut
                     e1={n: c_[n] / c_[0] - 1 for n in (5, 15, 60, 240, 960) if n < len(c_)}, e5={n: c_[n] / c_[4] - 1 for n in (15, 60, 240, 960) if n < len(c_)},
                     mx5=max(h[5:65]) / c_[4] - 1 if len(h) > 65 else None, mn5=min(l[5:65]) / c_[4] - 1 if len(l) > 65 else None))
print("listings with data:", len(rows), "of", len(wl))
rows.sort(key=lambda r: r["rel"])
lead = [r["lead_h"] for r in rows]
print("lead time announcement->first trade, hours: median %.1f min %.1f max %.1f" % (st.median(lead), min(lead), max(lead)))
def q(a): 
    a = sorted(a); n = len(a); return "p10 %.1f%% med %.1f%% p90 %.1f%%" % (100 * a[int(0.1 * (n - 1))], 100 * st.median(a), 100 * a[int(0.9 * (n - 1))])
print("first 1m candle (close vs open):", q([r["r_c0"] for r in rows]))
print("after the 1st minute: max high of minutes 1-15 vs close of minute 1:", q([r["hi15"] for r in rows]))
for tag, key, ns in (("ENTRY at close of minute 1", "e1", (5, 15, 60, 240, 960)), ("ENTRY at close of minute 5", "e5", (15, 60, 240, 960))):
    print(tag)
    for n in ns:
        a = [r[key][n] for r in rows if n in r[key]]
        print("  exit +%d min: n %d, mean %.1f%%, share>0 %.0f%%, %s, after 0.2%% fees mean %.1f%%" % (n, len(a), 100 * st.mean(a), 100 * sum(1 for v in a if v > 0) / len(a), q(a), 100 * (st.mean(a) - 0.002)))
hold = [r for r in rows if r["mx5"] is not None]
print("from minute-5 close, within next hour: max rise median %.1f%%, max drop median %.1f%%" % (100 * st.median([r["mx5"] for r in hold]), 100 * st.median([r["mn5"] for r in hold])))
print("last 12 listings:", [(r["sym"][:-4], dt.datetime.fromtimestamp(r["t0"] / 1000, dt.UTC).strftime("%m-%d"), round(100 * r["e5"].get(60, 0), 1)) for r in rows[-12:]])
by_half = collections.defaultdict(list)
for r in rows: by_half[dt.datetime.fromtimestamp(r["t0"] / 1000, dt.UTC).strftime("%Y") + ("H1" if dt.datetime.fromtimestamp(r["t0"] / 1000, dt.UTC).month <= 6 else "H2")].append(r["e5"].get(240))
print("entry min5 exit +4h by half-year (mean%, n):", {k: (round(100 * st.mean([v for v in vs if v is not None]), 1), len(vs)) for k, vs in sorted(by_half.items()) if any(v is not None for v in vs)})
json.dump(rows, open("/tmp/listing_rows.json", "w"))
print("DONE")
