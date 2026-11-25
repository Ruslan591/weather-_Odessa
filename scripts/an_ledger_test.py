import json, os, shutil, sys, importlib.util, urllib.request
src = urllib.request.urlopen("https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/shadow_ledger.py").read().decode()
open("/tmp/sl_new.py", "w").write(src)
spec = importlib.util.spec_from_file_location("sl_new", "/tmp/sl_new.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
PR = "/opt/trading-bot/positions_regr"
for name, over in (("BEFORE no filter", {"skip_tf": [], "skip_regime": []}), ("AFTER not flat & not 5m", {})):
    d = "/tmp/ldg_" + name[:3]; shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    shutil.copy(PR + "/shadow.json", d); c = json.load(open(PR + "/shadow_bal.json")); c.update(over); json.dump(c, open(d + "/shadow_bal.json", "w"))
    m._CACHE["mt"] = None
    o = m.compute(d)
    print(name)
    for l in o["lines"]: print("  ", l["k"], {k: l[k] for k in ("bal", "pnl", "taken", "closed", "wins", "open", "skipped", "maxc")})
    print("   journal saved:", os.path.exists(d + "/shadow_bal_trades.json"))
