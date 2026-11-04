# -*- coding: utf-8 -*-
"""Автоматический перенос стопа на линию поддержки/сопротивления ПОСЛЕ перехода позиции в безубыток (docs/topics/chan_orders.md, «Первоочередные задачи», 2026-11-04).
Определение пользователя: поддержка/сопротивление = уровень, в который цена неоднократно билась и так и не пробила.
Правила (5m, закрытые свечи после входа; допущения мои, на проверку):
  лонг:  уровни по локальным минимумам (минимум не выше соседних K=2 свечей с каждой стороны); минимумы в пределах 0.25 ATR(5m) образуют уровень;
         уровень подтверждён: >= 2 касаний, между соседними касаниями цена отходила вверх не меньше чем на 0.7 ATR, и ни одна свеча после первого касания не закрылась ниже уровня минус 0.25 ATR (не пробит).
  шорт:  зеркально по максимумам.
  Новый стоп = уровень -+ 0.5 ATR (лонг: ниже, шорт: выше). Берётся самый близкий к цене подходящий уровень. Условия: стоп только подтягивается (лонг: выше текущего, шорт: ниже), и остаётся дальше от цены не меньше чем на 0.3 ATR.
  Трейлинг 1.5 ATR(1h) из pos.py остаётся: стоп двигается тем, что ближе к цене.
Проверка раз на новую закрытую 5m-свечу (p['sr_t']). Журнал: p['sr_hist'], p['sr_level'], файл sr.log. Реальных ордеров нет."""
import os, time
TF5 = 300000; K = 2; MIN_TOUCH = 2; TOL = 0.25; PAD = 0.5; GAP = 0.3; BOUNCE = 0.7
def _atr(d, n=14):
    a = None
    for i in range(1, len(d)):
        h, l, pc = d[i][2], d[i][3], d[i - 1][4]; tr = max(h - l, abs(h - pc), abs(l - pc)); a = tr if a is None else a + (tr - a) / n
    return a

def levels(side, d, t0, atr):
    """Подтверждённые уровни после t0. side=1 лонг (поддержки), -1 шорт (сопротивления). d: [[t,o,h,l,c]...] закрытых 5m."""
    n = len(d); ext = [x[3] for x in d] if side > 0 else [x[2] for x in d]; sw = []
    for j in range(max(K, 0), n - K):
        if d[j][0] < t0: continue
        win = ext[j - K:j + K + 1]
        if (side > 0 and ext[j] <= min(win)) or (side < 0 and ext[j] >= max(win)): sw.append(j)
    sw.sort(key=lambda j: ext[j]); groups = []
    for j in sw:
        if groups and abs(ext[j] - ext[groups[-1][0]]) <= TOL * atr: groups[-1].append(j)
        else: groups.append([j])
    out = []
    for g in groups:
        g = sorted(g); gg = [g[0]]
        for j in g[1:]:
            if j - gg[-1] >= 3: gg.append(j)   # соседние свечи = одно касание
        g = gg
        if len(g) < MIN_TOUCH: continue
        lv = sum(ext[j] for j in g) / len(g); ok = True
        for a, b in zip(g, g[1:]):
            far = (max(x[2] for x in d[a:b + 1]) - lv) if side > 0 else (lv - min(x[3] for x in d[a:b + 1]))
            if far < BOUNCE * atr: ok = False; break
        if not ok: continue
        if any((d[j][4] < lv - TOL * atr) if side > 0 else (d[j][4] > lv + TOL * atr) for j in range(g[0], n)): continue
        out.append({"p": lv, "touches": len(g), "t_touch": [d[j][0] for j in g]})
    return out

def apply(p, kl, now, log=None):
    """Вызывать для открытой позиции после БУ. Возвращает True, если p изменён (стоп или sr_t)."""
    if not p.get("armed") or p["status"] != "open": return False
    d = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in kl(p["sym"], "5m", 300)]
    d = [k for k in d if k[0] + TF5 <= now]
    if len(d) < 30: return False
    if p.get("sr_t") == d[-1][0]: return False
    p["sr_t"] = d[-1][0]
    side = 1 if p["side"] == "long" else -1; atr = _atr(d)
    if not atr: return True
    px = float(kl(p["sym"], "1m", 1)[-1][4]); t0 = (p["t_in"] // TF5) * TF5; best = None
    for lv in levels(side, d, t0, atr):
        ns = lv["p"] - side * PAD * atr
        better = ns > p["stop"] if side > 0 else ns < p["stop"]
        away = (px - ns) / atr if side > 0 else (ns - px) / atr
        if better and away >= GAP and ((lv["p"] < px) if side > 0 else (lv["p"] > px)):
            if best is None or (ns > best[0] if side > 0 else ns < best[0]): best = (ns, lv)
    if best is None: return True
    ns, lv = best; old = p["stop"]; p["stop"] = ns
    p["sr_level"] = {"p": lv["p"], "touches": lv["touches"], "t_touch": lv["t_touch"], "set_t": now, "atr5": atr}
    p.setdefault("sr_hist", []).append({"t": now, "from": old, "to": ns, "level": lv["p"], "touches": lv["touches"], "px": px})
    msg = "SR-STOP #%d %s %s stop %.8g -> %.8g (уровень %.8g, касаний %d, цена %.8g, ATR5 %.6g)" % (p["id"], p["sym"], p["side"], old, ns, lv["p"], lv["touches"], px, atr)
    try:
        open(os.path.join(os.environ.get("POS_DIR", "/opt/trading-bot/positions"), "sr.log"), "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ", time.gmtime()) + msg + "\n")
    except Exception: pass
    if log: log(msg)
    return True
