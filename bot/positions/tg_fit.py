# -*- coding: utf-8 -*-
"""tg_fit.py -- вписывает подпись поста слежения в лимит Telegram (1024 символа у подписи к фото) БЕЗ обрезки на середине строки. Только stdlib, чистая функция.
fit(text, limit=1020) -> text. Ступени (каждая включается, только пока текст длиннее лимита):
  0) всегда: короткие формы длинных стандартных фраз (рынок, состояние, строка цели);
  1) заголовок мнения «⏳ ждём — причина» без причины (она есть первой строкой ✗ ниже);
  2) все строки ✓ блока в одну короткую строку;
  3) длинные строки ✗ режутся по границе слова;
  4) строка «ℹ️ Строгий BTC 1м» убирается;
  5) строка цели «🎯» ещё короче;
  6) строки-матрицы «отбой/пробой» BTC и «✅ сделка по режиму» убираются;
  7) крайний случай: строки с конца (кроме первой, заголовков 🧠/💥 и 📡) убираются целиком, в конце «…».
Удалить файл -> tg_bot вернётся к старой обрезке по длине."""
import re

LIM = 1020
_OK = [
    (r"^(?:за линию не закрывались|закрытий за линией нет)", "без закрытий"),
    (r"^цена у линии \(([+-]?[\d.]+) ATR\)", r"у линии \1"),
    (r"^есть реакция от линии \(хвост (\d+)%\)", r"реакция \1%"),
    (r"^до цели (\S+) R:R ([\d.-]+)", r"цель \1 R:R \2"),
    (r"^до цели 0\.5 канала R:R ([\d.-]+)", r"R:R \1"),
    (r"^канал стабилен", "канал стаб."),
    (r"^BTC 1m за (?:LONG|SHORT)", "BTC1m ок"),
    (r"^RSI 5m (\d+):", r"RSI5m \1 ок"),
    (r"^корреляция с BTC ([\d.-]+), BTC за 1 ч ([+-][\d.]+)%( ⚠)?", lambda m: "корр %s BTC1ч %s%%%s" % (m.group(1), m.group(2), " ⚠" if m.group(3) else "")),
    (r"^(\d+) закрытия? за линией подряд", r"закрытий \1"),
    (r"^цена за линией на ([\d.]+) ATR", r"за линией \1"),
    (r"^последняя свеча идёт в сторону пробоя \(тело (\d+)%\)", r"тело \1%"),
    (r"^сделка по режиму", "по режиму"),
]


def _cut(s, n):
    if len(s) <= n: return s
    c = s[:n - 1]; i = c.rfind(" ")
    return (c[:i] if i > n // 2 else c).rstrip(" ,;:·—-(") + "…"


def _s0(t):
    t = t.replace(" (минус = за линией)", "")
    t = re.sub(r"\(факторов (\d) из 6; BTC ([+-]?[\d.]+)% за 24 ч, ADX ([\d.]+), (\d+)% корзины в минусе\)", r"\1/6 · BTC \2%/24ч · ADX \3 · корзина \4%↓", t)
    t = re.sub(r"ПРОБОЙ ФОРМИРУЕТСЯ: несколько закрытий за линией", "пробой формируется", t)
    t = re.sub(r" · слежу (\d+)-ю свечу", r" · свеча \1", t)
    t = re.sub(r"🎯 Если заходить: цель (.+?): в похожих ситуациях \((.+?), n=(\d+)\) доходит (\d+)%, средний результат ([+-][\d.]+) R ≈ (\S+)", r"🎯 цель \1 ≈ \6: доходит \4%, ср. \5R (\2, n=\3)", t)
    return t


def _ok_short(s):
    for pat, rep in _OK:
        if re.search(pat, s): return re.sub(pat + r".*" if not callable(rep) else pat, rep, s, count=1) if not callable(rep) else re.sub(pat, rep, s, count=1)
    m = re.split(r"[:(]", s, 1)[0].strip()
    return _cut(m, 26)


def _collapse_ok(lines):
    out = []; idx = {}
    for ln in lines:
        if ln.startswith("✓ "):
            blk = sum(1 for x in out if x.startswith("🧠") or x.startswith("💥"))
            if blk in idx and idx[blk] is not None:
                out[idx[blk]] += " · " + _ok_short(ln[2:])
            else:
                idx[blk] = len(out); out.append("✓ " + _ok_short(ln[2:]))
        else: out.append(ln)
    return out


def fit(text, limit=LIM):
    t = _s0(text)
    if len(t) <= limit: return t
    lines = t.split("\n")
    # 1) заголовки мнения без причины (она видна первой строкой ✗)
    lines = [re.sub(r"^(🧠 Моё мнение: ⏳ ждём) — .*$", r"\1", ln) if ln.startswith("🧠") else (re.sub(r"^(💥 Пробой линии формируется: ⏳ ждём) — .*$", r"\1", ln) if ln.startswith("💥") else ln) for ln in lines]
    t = "\n".join(lines)
    if len(t) <= limit: return t
    # 2) строки ✓ в одну
    lines = _collapse_ok(lines); t = "\n".join(lines)
    if len(t) <= limit: return t
    # 3) длинные ✗
    lines = [_cut(ln, 84) if ln.startswith("✗ ") else ln for ln in lines]; t = "\n".join(lines)
    if len(t) <= limit: return t
    # 4) строгий BTC 1м
    lines = [ln for ln in lines if not ln.startswith("ℹ️")]; t = "\n".join(lines)
    if len(t) <= limit: return t
    # 5) цель короче
    lines = [re.sub(r" \([^()]*, n=\d+\)$", "", ln) if ln.startswith("🎯") else ln for ln in lines]; t = "\n".join(lines)
    if len(t) <= limit: return t
    # 6) матрица BTC 1m и «сделка по режиму»
    lines = [ln for ln in lines if not ln.startswith("   отбой:") and not ln.startswith("✅ сделка по режиму")]; t = "\n".join(lines)
    if len(t) <= limit: return t
    # пустые строки
    lines = [ln for ln in lines if ln.strip()]; t = "\n".join(lines)
    if len(t) <= limit: return t
    # 7) крайний случай: убираем строки с конца, кроме первой, заголовков и 📡
    keep = lambda ln: ln.startswith(("👁", "🧠", "💥", "📡", "⚠️", "🤖"))
    while len("\n".join(lines)) + 2 > limit:
        for i in range(len(lines) - 1, 0, -1):
            if not keep(lines[i]): del lines[i]; break
        else: break
    t = "\n".join(lines) + "\n…"
    return t if len(t) <= limit else t[:limit - 1] + "…"
