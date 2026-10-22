import sys, os, tempfile, datetime as dt
sys.path.insert(0, "/opt/trading-bot/classic")
import pandas as pd
import classic_strategy as cs, classic_learn as L, classic_hand as H
d = tempfile.mkdtemp()
df = L.download("NEARUSDT", "5m", 3, d); now = int(df.ct.iloc[-1]) + 10 ** 6
print("свечей", len(df), "последняя", dt.datetime.fromtimestamp(df.t.iloc[-1] / 1000, dt.timezone.utc) + dt.timedelta(hours=3))
print("структуры NEAR:", [(s["id"], s["tf"], bool(s.get("deleted"))) for s in H.for_sym("NEARUSDT")])
for trig in ("hand_bounce", "hand_breakout"):
    P = dict(L.base_params("NEARUSDT", "5m"), stages=[{"t": trig, "p": 0, "w": 0, "f": "none"}], entry_mode="stages", stop_mode="prev", min_stop_pct=0.0, min_stop_atr=0.5, tp_mode="channel", hand_forward=False, sym="NEARUSDT")
    try:
        T = cs.simulate(df, now, P, pre=cs.prepare(df, now))
        print(trig, "сделок", len(T))
        for x in T[-6:]:
            f = lambda t: (dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc) + dt.timedelta(hours=3)).strftime("%d.%m %H:%M")
            print("  ", x.get("side"), f(x["t_in"]), "->", f(x["t_out"]), "net %.2f" % x["net"], x.get("reason") or x.get("why") or "")
    except Exception as e:
        print(trig, "ошибка", repr(e)[:200])
