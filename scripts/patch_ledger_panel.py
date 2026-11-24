import sys
d = sys.argv[1]
pw = d + "/live_web.py"; ph = d + "/index.html"
s = open(pw, encoding="utf-8").read()
if "shadow_ledger" in s:
    print("ALREADY"); sys.exit(0)
a = 'POS = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")'
assert s.count(a) == 1, "a"
s = s.replace(a, a + '''
try:
    import sys as _sys; _sys.path.insert(0, "/opt/trading-bot/positions"); import shadow_ledger as SL
except Exception as _e: SL = None''')
b = '            except Exception as e: log("shadow: %s" % e)\n'
assert s.count(b) == 1, "b"
s = s.replace(b, b + '''            try:
                bl = await loop.run_in_executor(None, SL.compute, POS) if SL else None
                bsig = json.dumps(bl, sort_keys=True, ensure_ascii=False, default=str)
                if bsig != ST.get("bsig"): ST["bsig"] = bsig; ST["bal"] = bl; await bcast({"t": "bal", "a": bl})
            except Exception as e: log("bal: %s" % e)
''')
c = '"sh": ST.get("sh") or [],'
assert s.count(c) == 1, "c"
s = s.replace(c, c + ' "bal": ST.get("bal"),')
open(pw, "w", encoding="utf-8").write(s)

h = open(ph, encoding="utf-8").read()
x = "S.sh=m.sh||[];"
assert h.count(x) == 1, "x"
h = h.replace(x, x + "S.bal=m.bal||null;")
y = "else if(m.t==='sh'){S.sh=m.a||[]}"
assert h.count(y) == 1, "y"
h = h.replace(y, y + "\n    else if(m.t==='bal'){S.bal=m.a||null}")
z = "  const done=ALL.filter(p=>p.status==='closed'||p.status==='filtered')"
assert h.count(z) == 1, "z"
js = """  const BL=S.bal;if(BL&&BL.lines){sm.append(h('div','mut small','💰 Виртуальный баланс с '+dts(BL.t0)+', старт '+BL.start.toFixed(2)+' $ · ставка '+BL.stake+' $ ×'+BL.lev+' · слотов max('+BL.min_slots+', баланс/'+BL.slot_eq+' $)'));
    for(const L of BL.lines){const d=h('div','small');d.append(h('b',null,L.name+': '),h('b',cls(L.pnl),L.bal.toFixed(2)+' $ ('+sg(L.pnl,2)+' $)'),' · сделок '+L.closed+' (плюс '+L.wins+')'+(L.open?', открыто '+L.open:'')+' · слотов '+L.slots+(L.skipped?' · не хватило слотов '+L.skipped:''));sm.append(d)}}
"""
h = h.replace(z, js + z)
open(ph, "w", encoding="utf-8").write(h)
print("PATCHED")
