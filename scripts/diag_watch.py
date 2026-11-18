import json, time, os
D = "/opt/trading-bot/positions_regr"
now = time.time() * 1000
m = json.load(open(D + "/tg_mode.json"))
print("mode", {k: m.get(k) for k in ("mode", "alerts_off", "express", "max_watch")})
W = json.load(open(D + "/tg_watch.json")); it = W["items"]
print("active", [(x["sym"], x["status"]) for x in it if x["status"] in ("alert", "watching")])
print("cooldown_30min", [(x["sym"], x["side"], x.get("reason"), int((now - x.get("t_end", 0)) / 60000)) for x in it if x["status"] == "done" and now - x.get("t_end", 0) < 1800000])
r = json.load(open(D + "/radar_state.json"))
print("radar_keys", list(r)[:5] if isinstance(r, dict) else type(r))
d = r.get("pairs", r.get("radar", r)) if isinstance(r, dict) else {}
rows = []
for s, v in d.items():
    if not isinstance(v, dict): continue
    if not v.get("ctype") or v.get("R") is None: rows.append((99, s, "no channel")); continue
    a = v["atr"]; c = v["c"]; w = (v["R"] - v["S"]) / a
    du = (v["R"] - c) / a; dl = (c - v["S"]) / a
    rows.append((min(abs(du), abs(dl)), s, "%s width %.1f ATR, to upper %.2f, to lower %.2f, age %d min" % (v["ctype"], w, du, dl, (now - v["t"]) / 60000)))
rows.sort()
print("pairs", len(rows))
for x in rows[:25]: print("%.2f %s %s" % x)
