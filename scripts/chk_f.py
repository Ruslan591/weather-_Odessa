import sys, json, time, datetime, collections
sys.path.insert(0, "/opt/trading-bot/positions")
import shadow_ledger as SL
PR = "/opt/trading-bot/positions_regr"
o = SL.compute(PR)
print("skip", o.get("skip_tf"), o.get("skip_regime"))
for l in o["lines"]: print(l["k"], {k: l.get(k) for k in ("bal", "taken", "closed", "open", "skipped")})
t0 = json.load(open(PR + "/shadow_bal.json"))["t0"]
items = json.load(open(PR + "/shadow.json"))["items"]
def ts(ms): return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%d %H:%M")
c = collections.Counter()
print("--- last 14 A signals (time sym side tf status regime)")
rows = [x for x in items if x.get("var") == "A"]
rows.sort(key=lambda x: x.get("t_sig") or x.get("t0") or 0)
for x in rows[-14:]:
    print(ts(x.get("t_sig") or x.get("t0") or 0), x.get("sym"), x.get("side"), x.get("tf"), x.get("status"), (x.get("rg") or {}).get("regime"))
try: print("regime now", open(PR + "/tg_regime.json").read()[:300])
except Exception as e: print(e)
print("now", datetime.datetime.utcnow().strftime("%d %H:%M"))
