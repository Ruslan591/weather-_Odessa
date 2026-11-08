
import time, chan_orders as c, tg_gate
now = int(time.time()*1000)
print("PAIR ctype width_atr dist_upper_atr dist_lower_atr episode_up episode_low")
for sym in c.PAIRS:
    try:
        A = c.analyze(sym, now)
        if not A: print(sym, "no data"); continue
        i = c._tg_info(sym, A)
        if not i["ctype"]: print(sym, "no channel"); continue
        a = i["atr"]; w = (i["R"]-i["S"])/a
        print(sym, i["ctype"], "w=%.1f" % w, "up=%.2f" % ((i["R"]-i["h"])/a), "low=%.2f" % ((i["l"]-i["S"])/a), (tg_gate._episode(i,"upper") or {}).get("state"), (tg_gate._episode(i,"lower") or {}).get("state"))
    except Exception as e: print(sym, "ERR", e)
