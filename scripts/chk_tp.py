import sys, os
sys.path.insert(0, "/opt/trading-bot/positions"); os.environ["POS_DIR"] = "/opt/trading-bot/positions_regr"
src = open("/opt/trading-bot/live/live_web.py").read().split("def derive(snap)")[0]
ns = {"__name__": "lw_test", "__file__": "/opt/trading-bot/live/live_web.py"}
exec(compile(src, "lw", "exec"), ns)
sh = ns["build_shadow"]()
n = 0
for r in sh:
    if r.get("tp_plan") and n < 6 and r.get("entry") and r.get("stop"):
        n += 1
        print(r.get("sn"), r.get("sym"), r.get("side"), r.get("tf"), r.get("var"), "entry", r["entry"], "stop", r["stop"], "tp_plan", r["tp_plan"], "tp_engine", r["tp"],
              "plan%", round(abs(r["tp_plan"] / r["entry"] - 1) * 100, 2), "engine%", round(abs(r["tp"] / r["entry"] - 1) * 100, 2), "stop%", round(abs(r["stop"] / r["entry"] - 1) * 100, 2))
print("with tp_plan", sum(1 for r in sh if r.get("tp_plan")), "of", len(sh))
for r in sh:
    if r.get("sn") == 198: print("S198", r.get("var"), r.get("status"), "tp_plan", r.get("tp_plan"), "tp", r.get("tp"))
