import json, urllib.request, datetime
P = "/opt/trading-bot/positions_regr/"
sh = json.load(open(P + "shadow.json")); items = sh["items"]
t0 = json.load(open(P + "shadow_bal.json"))["t0"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M")
def cut(o, n=420): return json.dumps(o, ensure_ascii=True, default=str)[:n]
first = None
for x in items:
    if x.get("var") == "A" and (x.get("t_sig") or 0) >= t0 and x.get("sn") == 206: first = x
print("KEYS-206")
for k in ("feat", "b1", "reg", "rg", "chan", "geo", "w", "g", "gt", "plan", "setup", "chk", "cf", "mfe_r", "mae_r"):
    print(k, cut(first.get(k)))
print("p", cut({k: v for k, v in (first.get("p") or {}).items() if k not in ("ext_hist", "sw_hist", "thesis")}, 700))
print("BTC15m")
try:
    u = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=96"
    for k in json.load(urllib.request.urlopen(u, timeout=20)):
        print(ts(k[0]), k[1][:8], k[2][:8], k[3][:8], k[4][:8])
except Exception as e:
    print("ERR", e)
print("REGIME", open(P + "tg_regime.json").read()[:400])
