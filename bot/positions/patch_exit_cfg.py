# -*- coding: utf-8 -*-
"""Патч 10 (2026-11-06): настройки выхода счёта (exit_cfg.py) в pos.py. Идемпотентный. Запуск: patch_exit_cfg.py <каталог с pos.py>
Что меняется: close() считает итог с учётом частичных закрытий; step() берёт БУ, замок, трейлинг, цели из настроек счёта (по умолчанию = прежнее поведение), добавлена частичная цель (tp1);
snapshot() считает нереализованный результат с остатком и отдаёт eff (эффективные уровни) и exit_cfg; api_action: exit_cfg_set, exit_cfg_reset, exit_apply_stop; sr_stop включается настройкой."""
import sys, os
f = os.path.join(sys.argv[1], "pos.py"); s = open(f, encoding="utf-8").read()
if "exit_cfg" in s: print("already patched"); sys.exit(0)
def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (s.count(old), old[:80]); return s.replace(old, new)
def seg(s, a, b, new):
    i = s.index(a); j = s.index(b, i); return s[:i] + new + s[j:]

CLOSE_STEP = '''def close(p, px, t, reason, market):
    """Итог сделки с учётом частичных закрытий (p['parts'], доля остатка p['rem']): net = сумма вкладов частей + остаток; комиссия входа распределена по долям."""
    side = 1 if p["side"] == "long" else -1
    ex = px * (1 - side * SLIP / 100) if market else px
    rem = p.get("rem", 1.0); parts_c = sum(x["contrib_pct"] for x in p.get("parts", []))
    net = parts_c + rem * (side * (ex / p["entry"] - 1) * 100 - fees(p, reason))
    p.update(status="closed", t_out=t, exit=ex, reason=reason, net_pct=round(net, 3), r_mult=round(net / p["R_pct"], 3),
             pnl_usd=round(p["stake"] * net / 100, 3),
             mfe_pct=round((p["entry"] - p["lo"]) / p["entry"] * 100 if side < 0 else (p["hi"] - p["entry"]) / p["entry"] * 100, 3),
             mae_pct=round((p["hi"] - p["entry"]) / p["entry"] * 100 if side < 0 else (p["entry"] - p["lo"]) / p["entry"] * 100, 3))

def partial(p, px, t, frac, why):
    """Закрыть долю frac ИСХОДНОЙ позиции лимитом по px (комиссия выхода как у цели). Вклад в итог хранится в p['parts']."""
    side = 1 if p["side"] == "long" else -1; rem = p.get("rem", 1.0); frac = min(frac, rem)
    gross = side * (px / p["entry"] - 1) * 100
    contrib = frac * (gross - fees(p, "target"))
    p.setdefault("parts", []).append({"t": t, "px": px, "frac": round(frac, 6), "why": why, "contrib_pct": round(contrib, 5), "usd": round(p["stake"] * contrib / 100, 4)})
    p["rem"] = round(rem - frac, 6)

def step(p, k):
    t, o, h, l, c = int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])
    side = 1 if p["side"] == "long" else -1; stop = p["stop"]
    cfg = exit_cfg.load(); L = exit_cfg.levels(p, cfg)
    liq = p["entry"] * (1 - side * LIQ / 100)
    if (h >= liq) if side < 0 else (l <= liq):
        rem = p.get("rem", 1.0); parts_c = sum(x["contrib_pct"] for x in p.get("parts", []))
        close(p, liq, t + 60000, "liquidation", False); p["net_pct"] = round(parts_c + rem * (-100.0 / LEV), 3); p["pnl_usd"] = round(p["stake"] * p["net_pct"] / 100, 3); return
    hit = (h >= stop) if side < 0 else (l <= stop)
    if hit:
        gap = max(stop, o) if side < 0 else min(stop, o)
        close(p, gap, t + 60000, "stop" if not (p["armed"] or p.get("trail_act")) else "trail/BE", True); return
    reach = lambda px: (l <= px) if side < 0 else (h >= px)
    tp1 = L["tp1"]
    if tp1 is not None and not p.get("tp1_done") and reach(tp1):   # частичная цель: часть позиции лимитом, остаток дальше
        frac = cfg["tp1"]["part"] / 100.0
        partial(p, tp1, t + 60000, frac, "tp1"); p["tp1_done"] = True; p["tp1_t"] = t + 60000
    if L["tp"] is not None and reach(L["tp"]):
        close(p, L["tp"], t + 60000, "target", False); return
    p["hi"] = max(p["hi"], h); p["lo"] = min(p["lo"], l)
    b = cfg["be"]
    if not p["armed"] and b["on"] and ((L["be_px"] is not None and reach(L["be_px"])) or (b["trig"] == "tp1" and p.get("tp1_done"))):
        p["armed"] = True; p["armed_t"] = t + 60000
        if not p.get("stop_manual"): p["stop"] = min(p["stop"], L["lock_px"]) if side < 0 else max(p["stop"], L["lock_px"])
    tr = cfg["trail"]
    if not p.get("trail_act") and (tr["on"] or p.get("manual_trail")):
        st = tr["start"]
        if p.get("manual_trail") or (st == "be" and p["armed"]) or st == "now" or (st == "tp1" and p.get("tp1_done")) or (L["trail_px"] is not None and reach(L["trail_px"])):
            p["trail_act"] = True; p["trail_t"] = t + 60000
    if p.get("trail_act") and (tr["on"] or p.get("manual_trail")) and not p.get("stop_manual"):
        tl = p["lo"] + L["trail_dist"] if side < 0 else p["hi"] - L["trail_dist"]
        p["stop"] = min(p["stop"], tl) if side < 0 else max(p["stop"], tl)
    mh = cfg["maxh"] if cfg["maxh"] is not None else p["max_h"]
    if mh and (t + 60000 - p["t_in"]) / 3600000 >= mh: close(p, c, t + 60000, "time", True)

'''
s = seg(s, "def close(p, px, t, reason, market):", "def cmd_update():", CLOSE_STEP)
s = rep(s, "import argparse, contextlib, fcntl, json, os, sys, time, urllib.request\n", "import argparse, contextlib, fcntl, json, os, sys, time, urllib.request\nimport exit_cfg   # патч 10: настройки выхода счёта (exit_cfg.json в каталоге счёта)\n")
# sr_stop включается настройкой
s = rep(s, '        if p["status"] == "open" and p.get("armed"):\n            try:\n                import sr_stop', '        if p["status"] == "open" and p.get("armed") and exit_cfg.load()["sr"]["on"]:\n            try:\n                import sr_stop')
# snapshot: нереализованный результат с остатком, эффективные уровни
s = rep(s, 'px = price(p["sym"]); u = side * (px / p["entry"] - 1) * 100 - fees(p); ud = p["stake"] * u / 100; m = p["stake"] / p.get("lev", LEV)',
        'px = price(p["sym"]); rem = p.get("rem", 1.0); u = sum(x["contrib_pct"] for x in p.get("parts", [])) + rem * (side * (px / p["entry"] - 1) * 100 - fees(p)); ud = p["stake"] * u / 100; m = p["stake"] / p.get("lev", LEV) * rem')
s = rep(s, 'trail_pct=round(p["trail_dist"] / px * 100, 3),', 'trail_pct=round(exit_cfg.levels(p)["trail_dist"] / px * 100, 3), rem=rem, eff=_eff(p), tp=_eff(p)["tp"] if _eff(p)["tp"] is not None else p["tp"], be_px=_eff(p)["be_px"] if _eff(p)["be_px"] is not None else p["be_px"],')
s = rep(s, 'def snapshot():', '''def _eff(p):
    L = exit_cfg.levels(p); L["liq"] = p["entry"] * (1 - (1 if p["side"] == "long" else -1) * LIQ / 100); L["atr1h"] = p.get("atr1h"); L["R"] = p["R"]; return L

def snapshot():''')
s = rep(s, '"open": opn, "closed": closed, "orders": _orders(),', '"open": opn, "closed": closed, "exit_cfg": exit_cfg.load(), "exit_default": exit_cfg.DEFAULT, "orders": _orders(),')
# api_action
s = rep(s, '    act = o.get("action"); pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)\n    with lock():',
'''    act = o.get("action")
    if act in ("exit_cfg_set", "exit_cfg_reset", "exit_apply_stop"):   # патч 10
        with lock():
            if act == "exit_cfg_reset": exit_cfg.save(exit_cfg.DEFAULT_COPY())
            elif act == "exit_cfg_set":
                c, err = exit_cfg.validate(o.get("cfg"))
                if err: return {"error": err}
                exit_cfg.save(c)
            else: return _apply_stop()
        return snapshot()
    pid = int(o.get("id", 0)); pct = float(o.get("pct", 0) or 0)
    with lock():''')
s = rep(s, 'def api_action(o):', '''def _apply_stop():
    """Применить режим стопа (pct|atr) к ОТКРЫТЫМ позициям, которые ещё не в БУ, без частичной цели и без ручного стопа: новый начальный стоп на расстоянии от входа, пересчёт R."""
    c = exit_cfg.load()
    if c["stop"]["mode"] == "rule": return {"error": "режим стопа «как в заявке»: менять нечего"}
    ps = _update(); n = 0; now = int(time.time() * 1000)
    for p in ps:
        if p["status"] != "open" or p.get("armed") or p.get("tp1_done") or p.get("stop_manual"): continue
        side = 1 if p["side"] == "long" else -1; ns = exit_cfg.stop_at_fill(c, side, p["entry"], p.get("atr1h") or 0.0, p["stop0"])
        if not ns or (side > 0 and ns >= p["entry"]) or (side < 0 and ns <= p["entry"]): continue
        px = price(p["sym"])
        if (side > 0 and ns >= px) or (side < 0 and ns <= px): continue   # цена уже за новым стопом: не трогаем
        old = p["stop"]; R = abs(p["entry"] - ns); p.update(stop=ns, stop0=ns, R=R, R_pct=R / p["entry"] * 100, be_px=p["entry"] + side * R * p.get("be_r", 1.0)); n += 1
        p.setdefault("stop_hist", []).append({"t": now, "from": old, "to": ns, "by": "exit_cfg"})
    save(ps); r = snapshot(); r["applied"] = n; return r

def api_action(o):''')
open(f, "w", encoding="utf-8").write(s); print("patched pos.py")
