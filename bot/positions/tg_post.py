# -*- coding: utf-8 -*-
"""tg_post.py -- компактная подпись поста слежения в экспрессе (по просьбе пользователя 2026-11-17): сначала ВЕРДИКТ, затем короткий набор параметров ✓/✗ по одному в строке, цена входа/стопа/цели.
Читают вердикт, потом график. Чистая функция, только stdlib. compose(w, V, Bk) -> текст или None (нет структурных строк rows: tg_bot тогда строит прежний длинный пост).
Выключить: POS_DIR/tg_post.json {"enabled": false} или удалить файл (tg_bot подключает через try/except).
Из поста убраны (остались в записи feat/журнале и в Радаре): строка режима рынка, матрица BTC 1m «отбой/пробой», 📡 паровозик, «Строгий BTC 1м», «Коррекции по опыту», длинные пояснения.
Порядок параметров фиксирован, чтобы глаз привыкал к местам: линия, реакция/импульс, RSI, R:R, канал, BTC 1м, режим, корреляция, свечи H1/H4."""
import json, os, re

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CFG = os.path.join(D, "tg_post.json")
LBL = {"line": "Закрытия за линией", "dist": "До линии", "react": "Реакция", "rsi": "RSI 5м", "rr": "R:R", "chan": "Канал", "btc": "BTC 1м", "regime": "Режим", "corr": "Корр. с BTC",
       "htf": "Свечи H1/H4", "n": "Закрытия за линией", "beyond": "За линией", "body": "Тело свечи", "cr": "Против режима"}
ORD = ["line", "n", "dist", "beyond", "react", "body", "rsi", "rr", "chan", "btc", "regime", "corr", "cr", "htf"]


def enabled():
    try: return bool(json.load(open(CFG, encoding="utf-8")).get("enabled", True))
    except Exception: return True


def _cut(s, n):
    s = (s or "").strip()
    if len(s) <= n: return s
    c = s[:n - 1]; i = c.rfind(" ")
    return (c[:i] if i > n // 2 else c).rstrip(" ,;:·—-(") + "…"


def _val(key, ok, t):
    """Короткое значение параметра: для ✓ число/факт, для ✗ что именно не так."""
    m = None
    if key in ("line", "n"):
        if key == "n" and ok: return t.split(" ")[0] + " подряд"
        return "нет" if ok else "есть: риск пробоя"
    if key == "dist":
        m = re.search(r"([+-]?\d+\.\d+) ATR", t); d = (m.group(1) + " ATR") if m else _cut(t, 24)
        return d if ok else d + (" · поздно" if "поздно" in t else " · за линией")
    if key == "beyond":
        m = re.search(r"(\d+\.\d+) ATR", t); d = (m.group(1) + " ATR") if m else _cut(t, 24)
        return d if ok else d + (" · ещё не ушла" if "не ушла" in t else " · далеко, не гонимся")
    if key == "react":
        m = re.search(r"хвост (\d+)%", t); d = ("хвост %s%%" % m.group(1)) if m else _cut(t, 24)
        return d if ok else d + " · реакции нет"
    if key == "body":
        m = re.search(r"тело (\d+)%", t); d = (m.group(1) + "%") if m else _cut(t, 24)
        return d if ok else d + " · слабая"
    if key == "rr":
        m = re.search(r"R:R (\d+\.\d+)(?: < (\d+\.\d+))?", t); mt = re.search(r"до цели (\S+)", t)
        d = m.group(1) if m else _cut(t, 24)
        if m and not ok and m.group(2): d += " < %s" % m.group(2)
        return d + ((" (цель %s)" % mt.group(1)) if (mt and ok and mt.group(1) != "0.5") else "")
    if key == "chan":
        return "стабилен" if ok else _cut(t.replace("канал ", ""), 30)
    if key == "rsi":
        m = re.search(r"RSI 5m (\d+)", t); r = m.group(1) if m else "?"
        if ok: return r + (" · сильный" if "сильный" in t else "")
        m2 = re.search(r"(?:только при RSI|зоне|ниже|выше) ([<>]? ?[\d.\-]+)", t)
        return "%s · нужно %s" % (r, m2.group(1)) if m2 else "%s · не проходит" % r
    if key == "btc":
        if ok: return "по ходу сделки"
        t2 = t.split(": ", 1)[1] if ": " in t else t
        return _cut(t2, 44)
    if key == "regime":
        m = re.search(r"режим рынка (\S+) \((\d) из 6\)", t)
        if m: return "%s %s/6 · %s" % (m.group(1), m.group(2), "по течению" if ok else "против течения")
        return "флэт" if "флэт" in t else _cut(t, 30)
    if key == "corr":
        m = re.search(r"корреляция с BTC ([\d.-]+), BTC за 1 ч ([+-][\d.]+)%", t)
        return ("%s · BTC 1ч %s%%" % (m.group(1), m.group(2)) if m else _cut(t, 30)) + (" ⚠" if "⚠" in t and ok else "")
    if key == "htf": return t if ok else _cut(t.split(": ", 1)[0] if ": " in t else t, 60)
    if key == "cr": return "свежий и сильный" if ok else _cut(t.split(": ", 1)[-1], 40)
    return _cut(t, 40)


def _side_ru(side): return "SHORT" if side == "short" else "LONG"


def compose(w, V, Bk=None):
    if not enabled(): return None
    M = V if (V and V.get("call") == "enter") else (Bk or V)
    if not M or not M.get("rows"): return None
    brk = M is Bk; plan = M.get("plan") or {}; side = M.get("side") or plan.get("side") or "?"
    up = (w.get("line") or ("upper" if w.get("side") == "short" else "lower")) == "upper"
    kind = ("пробой %s линии" % ("верхней" if up else "нижней")) if brk else ("отбой от %s линии" % ("верхней" if up else "нижней"))
    rows = M["rows"]; bad = [r for r in rows if not r[0]]
    sym = w.get("sym") or "?"
    if M.get("call") == "enter":
        head = "✅ ЗАХОДИТЬ · %s %s · %s" % (sym, _side_ru(side), kind)
        pl = "вход ~%s · стоп %s · цель %s · R:R %s" % (_px(plan.get("entry")), _px(plan.get("stop")), _px(plan.get("tp")), plan.get("rr"))
    else:
        head = "⏳ ЖДЁМ · %s %s · %s" % (sym, _side_ru(side), kind)
        pl = "не хватает: " + ", ".join(LBL.get(r[1], str(r[1])) for r in bad)
    out = [head, pl]
    if w.get("counter") or (V and V.get("feat", {}).get("counter")): out.append("⚠️ против тренда канала")
    out.append("")
    byk = {}
    for ok, key, t in rows: byk.setdefault(key, (ok, t))
    for key in ORD:
        if key in byk:
            ok, t = byk[key]
            if key == "htf":      # каждая свеча отдельной строкой: цвет, тело от среднего (×), фаза свечи (%)
                for part in t.split(" (против")[0].split(" | "):
                    m = re.match(r"(H\d) (\S+) (\d+\.\d)×·(\d+)%(?: (\S))?", part)
                    if not m: out.append("%s %s" % ("✓" if ok else "✗", _cut(part, 50))); continue
                    nm, col, bx, ph, mkx = m.groups()
                    mk = {"✓": "✓", "✗": ("✗" if not ok else "⚠"), "⚠": "⚠", "·": "➖"}.get(mkx or "✓", "✓")     # ⚠: свеча против, но в режиме shadow вердикт не меняет
                    out.append("%s %s %s тело %s×ср · %s%% свечи" % (mk, nm, col, bx, ph))
                continue
            out.append("%s %s: %s" % ("✓" if ok else "✗", LBL.get(key, key), _val(key, ok, t)))
    for ok, key, t in rows:      # условия с неизвестным ключом не теряем
        if key not in ORD: out.append("%s %s" % ("✓" if ok else "✗", _cut(t, 60)))
    return "\n".join(out)


def _px(p):
    try:
        p = float(p)
        return ("%.1f" % p) if p >= 1000 else (("%.2f" % p) if p >= 100 else (("%.3f" % p) if p >= 10 else (("%.4f" % p) if p >= 1 else "%.5f" % p)))
    except Exception: return "—"
