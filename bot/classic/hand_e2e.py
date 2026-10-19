import json, urllib.request, sys, warnings, time, os
warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/trading-bot/classic")
import pandas as pd, numpy as np, classic_analysis as an, classic_trendline as tl, classic_hand as hd, classic_strategy as cs
def post(u, o):
    try: return json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:18093" + u, json.dumps(o).encode(), {"Content-Type": "application/json"}), timeout=120))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, "действие", o.get("action"), "->", e.read().decode()[:300]); raise SystemExit
def get(u): return json.load(urllib.request.urlopen("http://127.0.0.1:18093" + u, timeout=120))
d = json.load(urllib.request.urlopen("https://api.binance.com/api/v3/klines?symbol=ZECUSDT&interval=4h&limit=1000", timeout=20))
df = pd.DataFrame(d).iloc[:, [0,1,2,3,4,5,6]]; df.columns = ["t","o","h","l","c","v","ct"]
for k in "ohlcv": df[k] = df[k].astype(float)
df["t"] = df["t"].astype("int64"); df["ct"] = df["ct"].astype("int64")
closed = df.iloc[:-1].reset_index(drop=True); ind = an.indicators(closed); atr = ind["atr"].values
hh, ll = tl.anchor_series(closed.o.values, closed.h.values, closed.l.values, closed.c.values, "wick")
piv = tl.pivots(hh, ll)
# «пользователь» рисует: берём авто-канал на свече M-200 (задним числом), чтобы после него были данные
found = None
for i in range(len(closed) - 260, len(closed) - 120):
    lows = [q for q in piv if q["k"] == "L" and q["conf"] <= i][-8:]; highs = [q for q in piv if q["k"] == "H" and q["conf"] <= i][-8:]
    ch = tl.auto_channel(hh, ll, closed.c.values, atr, i, lows, highs)
    if ch: found = (i, ch); break
if not found: print("канал не найден"); sys.exit()
i, ch = found; lo, up = ch["lower"], ch["upper"]; t = closed.t.values
A = [int(t[lo[0]]), lo[1], int(t[lo[2]]), lo[3]]; B = [int(t[up[0]]), up[1], int(t[up[2]]), up[3]]
print("канал найден на свече", i, ch["kind"], "ширина %.1f ATR, касаний %d/%d" % (ch["width"], ch["t_main"], ch["t_clone"]))
r = post("/api/hand", {"action": "add", "sym": "ZECUSDT", "tf": "4h", "kind": "channel", "A": A, "B": B, "anc": ["l", "l", "h"]})
print("добавлено:", len(r["items"]), "структур | сигналов бота по ней на истории:", len(r["sigs"]), "| отбоев", sum(1 for s in r["sigs"] if s["kind"] == "b"), "пробоев", sum(1 for s in r["sigs"] if s["kind"] == "k"))
USER = dict(tf="4h", entry_mode="stages", entry_trigger="open", tp_r=0.0, max_bars=0, rev_exit=True, stop_mode="prev", min_stop_pct=3.0, min_stop_atr=3.0, be_trigger=1.8, be_lock=1.1, trail_mode="none", trail_dist=0.7, pat_mode="trail", pat_min=2.0, fee=0.05, pat_filter="none")
now = int(time.time() * 1000)
for trig in ("hand_bounce", "hand_breakout"):
    for fwd in (False, True):
        P = dict(cs.PARAMS, **USER, sym="ZECUSDT", hand_forward=fwd, stages=[{"t": trig, "p": 0, "w": 12, "f": "none"}])
        tr = cs.simulate(df, now, P)
        print("%-14s hand_forward=%-5s сделок %d, net %+.2f%%" % (trig, fwd, len(tr), sum(x["net"] for x in tr)))
r = post("/api/hand", {"action": "update", "id": r["items"][0]["id"], "sym": "ZECUSDT", "tf": "4h", "A": [A[0], A[1] * 1.01, A[2], A[3] * 1.01], "B": B})
print("update: created сброшен =", r["items"][0]["created"] > A[2], "| edited есть =", "edited" in r["items"][0])
lr = post("/api/hand", {"action": "learn", "sym": "ZECUSDT", "tf": "4h"})
print("обучение:", json.dumps(lr.get("learn_done", lr), ensure_ascii=False)[:420])
r = post("/api/hand", {"action": "undo", "sym": "ZECUSDT", "tf": "4h"}); print("после отмены активных структур:", len(r["items"]))
