# -*- coding: utf-8 -*-
"""Патч 11 (2026-11-06): журнал решений (decisions.py) и ручная цель в pos.py / exit_cfg.py. Идемпотентный. Запуск: patch_journal.py <каталог с pos.py и exit_cfg.py>
pos.py: запись ручных действий (стоп, цель, трейлинг, возврат в авто, закрытие) с контекстом; автособытий (БУ, старт трейлинга, частичная цель, перенос на S/R); новые действия tp и tp_auto (ручная цель),
journal_get (выгрузка журнала); snapshot отдаёт journal. exit_cfg.levels: ручная цель p['tp_manual'] главнее настроек."""
import sys, os
d = sys.argv[1]; f = os.path.join(d, "pos.py"); s = open(f, encoding="utf-8").read()
if "decisions" in s: print("pos.py already patched")
else:
    def rep(s, old, new, cnt=1):
        assert s.count(old) == cnt, (s.count(old), old[:90]); return s.replace(old, new)
    s = rep(s, "import exit_cfg   # патч 10: настройки выхода счёта (exit_cfg.json в каталоге счёта)\n", "import exit_cfg   # патч 10: настройки выхода счёта (exit_cfg.json в каталоге счёта)\nimport decisions   # патч 11: журнал решений (decisions.jsonl в каталоге счёта)\n")
    # автособытия в step()
    s = rep(s, '        p["armed"] = True; p["armed_t"] = t + 60000\n        if not p.get("stop_manual"): p["stop"] = min(p["stop"], L["lock_px"]) if side < 0 else max(p["stop"], L["lock_px"])\n',
               '        _os = p["stop"]; p["armed"] = True; p["armed_t"] = t + 60000\n        if not p.get("stop_manual"): p["stop"] = min(p["stop"], L["lock_px"]) if side < 0 else max(p["stop"], L["lock_px"])\n        decisions.auto(p, "be", _os, p["stop"], t + 60000, c)\n')
    s = rep(s, '            p["trail_act"] = True; p["trail_t"] = t + 60000\n', '            p["trail_act"] = True; p["trail_t"] = t + 60000; decisions.auto(p, "trail_start", p["stop"], p["stop"], t + 60000, c)\n')
    s = rep(s, 'partial(p, tp1, t + 60000, frac, "tp1"); p["tp1_done"] = True; p["tp1_t"] = t + 60000\n', 'partial(p, tp1, t + 60000, frac, "tp1"); p["tp1_done"] = True; p["tp1_t"] = t + 60000; decisions.auto(p, "tp1", None, tp1, t + 60000, c, frac=frac)\n')
    # перенос на S/R
    s = rep(s, "                if sr_stop.apply(p, kl, now, lambda m: print(m, flush=True)): changed = True\n",
               "                _n0 = len(p.get(\"sr_hist\", []))\n                if sr_stop.apply(p, kl, now, lambda m: print(m, flush=True)): changed = True\n                if len(p.get(\"sr_hist\", [])) > _n0:\n                    _h = p[\"sr_hist\"][-1]; decisions.auto(p, \"sr\", _h.get(\"from\"), _h.get(\"to\"), now, _h.get(\"px\"), level=_h.get(\"level\"), touches=_h.get(\"touches\"))\n")
    # snapshot
    s = rep(s, '"exit_cfg": exit_cfg.load(), "exit_default"', '"journal": decisions.summary(), "exit_cfg": exit_cfg.load(), "exit_default"')
    # действия
    s = rep(s, '    pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)\n    with lock():',
'''    if act == "journal_get":   # патч 11: выгрузка журнала (full=1 - со свечами и уровнями)
        rows = decisions.all_rows(5000, int(o["id"]) if o.get("id") else None)
        if not o.get("full"): rows = [{k: v for k, v in r.items() if k not in decisions.BIG} for r in rows]
        return {"rows": rows, "n": len(rows)}
    pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)
    with lock():''')
    s = rep(s, '            close(p, px, now, "manual", True)\n', '            decisions.manual(p, px, kl, "close", p["stop"], px, o)\n            close(p, px, now, "manual", True)\n')
    s = rep(s, '            p.setdefault("stop_hist", []).append({"t": now, "from": old, "to": sp, "by": "manual"})\n', '            p.setdefault("stop_hist", []).append({"t": now, "from": old, "to": sp, "by": "manual"})\n            decisions.manual(p, px, kl, "stop", old, sp, o)\n')
    s = rep(s, '        elif act == "auto":\n            p.pop("stop_manual", None); p.pop("manual_stop_px", None)\n',
'''        elif act == "tp":   # патч 11: ручная цена цели (лимит), главнее настроек выхода
            try: tg = float(str(o.get("price", "")).replace(",", "."))
            except Exception: return {"error": "укажите цену цели числом"}
            if side > 0 and not (tg > px * 1.0002): return {"error": "лонг: цель должна быть выше текущей цены %.8g" % px}
            if side < 0 and not (tg < px * 0.9998): return {"error": "шорт: цель должна быть ниже текущей цены %.8g" % px}
            old = exit_cfg.levels(p)["tp"]; p["tp_manual"] = tg; p["tp_manual_t"] = now
            p.setdefault("tp_hist", []).append({"t": now, "from": old, "to": tg, "by": "manual"})
            decisions.manual(p, px, kl, "tp", old, tg, o)
        elif act == "tp_auto":
            old = p.get("tp_manual"); p.pop("tp_manual", None); p.pop("tp_manual_t", None)
            decisions.manual(p, px, kl, "tp_release", old, exit_cfg.levels(p)["tp"], o)
        elif act == "auto":
            decisions.manual(p, px, kl, "release", p["stop"], p["stop"], o)
            p.pop("stop_manual", None); p.pop("manual_stop_px", None)
''')
    s = rep(s, '                p["trail_dist"] = dist; p["armed"] = True; p["manual_trail"] = round(pct, 3)\n', '                _os = p["stop"]; p["trail_dist"] = dist; p["armed"] = True; p["manual_trail"] = round(pct, 3)\n')
    s = rep(s, '                p["stop"] = min(p["stop"], tr) if side < 0 else max(p["stop"], tr)\n', '                p["stop"] = min(p["stop"], tr) if side < 0 else max(p["stop"], tr)\n                decisions.manual(p, px, kl, "trail", _os, p["stop"], o, pct=pct)\n')
    open(f, "w", encoding="utf-8").write(s); print("patched pos.py")
fe = os.path.join(d, "exit_cfg.py"); e = open(fe, encoding="utf-8").read()
if "tp_manual" in e: print("exit_cfg.py already patched")
else:
    old = '    t1 = c["tp1"]; tp1 = e + side * dist(p, t1["unit"], t1["val"]) if t1["on"] else None\n'
    assert e.count(old) == 1
    e = e.replace(old, '    if p.get("tp_manual"): tp = p["tp_manual"]   # ручная цель (патч 11) главнее настроек\n' + old)
    open(fe, "w", encoding="utf-8").write(e); print("patched exit_cfg.py")
