# -*- coding: utf-8 -*-
"""Chastota listingov Binance: data pervoj dnevnoj svechi po vsem torguyushchimsya USDT-parom (vyzhivshie) + popytka vzyat' kanal obyavlenij. ASCII output."""
import json, time, urllib.request, collections, datetime as dt
B = "https://data-api.binance.vision"
def get(u, hdr=None):
    r = urllib.request.Request(u, headers=hdr or {"User-Agent": "Mozilla/5.0"}); return json.load(urllib.request.urlopen(r, timeout=30))
info = get(B + "/api/v3/exchangeInfo")
syms = [s["symbol"] for s in info["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING" and s.get("isSpotTradingAllowed")]
print("trading USDT spot symbols:", len(syms), flush=True)
first = {}
for i, s in enumerate(syms):
    try:
        k = get(B + "/api/v3/klines?symbol=%s&interval=1d&startTime=0&limit=1" % s)
        if k: first[s] = int(k[0][0])
    except Exception as e: print("err", s, e)
    time.sleep(0.25)
    if i % 100 == 99: print("progress", i + 1, flush=True)
json.dump(first, open("/tmp/first_candle.json", "w"))
by_m = collections.Counter(dt.datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m") for t in first.values())
by_y = collections.Counter(dt.datetime.utcfromtimestamp(t / 1000).strftime("%Y") for t in first.values())
print("per year:", dict(sorted(by_y.items())))
print("per month (last 28):", [(m, by_m[m]) for m in sorted(by_m)[-28:]])
# poslednie 40 listingov
last = sorted(first.items(), key=lambda z: -z[1])[:30]
print("latest 30:", [(s, dt.datetime.utcfromtimestamp(t / 1000).strftime("%m-%d")) for s, t in last])
# obyavleniya
try:
    a = get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=50")
    arts = a["data"]["catalogs"][0]["articles"]
    print("announcements got:", len(arts))
    for x in arts[:25]: print(dt.datetime.utcfromtimestamp(x["releaseDate"] / 1000).strftime("%Y-%m-%d %H:%M"), x["title"][:110])
except Exception as e: print("announcements failed:", type(e).__name__, str(e)[:150])
print("DONE")
