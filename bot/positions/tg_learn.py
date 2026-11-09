# -*- coding: utf-8 -*-
"""tg_learn.py -- журнал «согласен / не согласен открыть сейчас» для режима «Экспресс слежение» и поиск похожих прошлых ситуаций.
Только запись и подсказка: на решения бота и на ордера НЕ влияет. Отключение: кнопка «Обучение» в меню (файл tg_express_cfg.json),
переменная окружения EXPRESS_LEARN=0 или удаление этого файла (tg_bot.py подключает его через try/except).
Файлы в POS_DIR: tg_learn.jsonl (по строке на ответ), tg_express_cfg.json {\"learn\": true|false}."""
import json, os, time

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
LOGF = os.path.join(D, "tg_learn.jsonl"); CFGF = os.path.join(D, "tg_express_cfg.json")
BAR_MS = 300000; HORIZON = 48       # исход считается по 48 свечам (4 ч) после сигнала


def enabled():
    if os.environ.get("EXPRESS_LEARN", "1") == "0": return False
    try: return bool(json.load(open(CFGF, encoding="utf-8")).get("learn", True))
    except Exception: return True


def set_enabled(on):
    with open(CFGF, "w", encoding="utf-8") as f: json.dump({"learn": bool(on)}, f)


def _load():
    out = []
    try:
        for ln in open(LOGF, encoding="utf-8"):
            try: out.append(json.loads(ln))
            except Exception: pass
    except OSError: pass
    return out


def record(V, answer, wid):
    """V - мнение из tg_express.verdict; answer: 1 согласен / 0 не согласен."""
    rec = {"ts": int(time.time() * 1000), "wid": wid, "sym": V["sym"], "side": V["side"], "t": V["t"], "feat": V["feat"], "plan": V["plan"], "ans": int(answer), "res": None}
    with open(LOGF, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def _outcome(rec, kl):
    p = rec["plan"]; s = 1 if p["side"] == "long" else -1; n = 0
    for k in kl:
        if k[0] <= rec["t"]: continue
        n += 1; hi, lo = float(k[2]), float(k[3])
        hit_stop = lo <= p["stop"] if s > 0 else hi >= p["stop"]; hit_tp = hi >= p["tp"] if s > 0 else lo <= p["tp"]
        if hit_stop: return "stop"        # обе в одной свече - считаем стоп (осторожно)
        if hit_tp: return "tp"
        if n >= HORIZON: return "none"
    return None                            # ещё не определилось


def resolve(load_kl):
    """Дописать исход (tp | stop | none) к записям без него. load_kl(sym) -> свечи 5m. Вызывается периодически из tg_bot."""
    recs = _load(); ch = False
    for r in recs:
        if r.get("res") is not None: continue
        try:
            res = _outcome(r, load_kl(r["sym"]) or [])
            if res: r["res"] = res; ch = True
        except Exception: pass
    if ch:
        tmp = LOGF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp, LOGF)


def _dist(a, b):
    return (abs(a["dist"] - b["dist"]) / 1.0 + abs(a["wick"] - b["wick"]) + abs(a["cpos"] - b["cpos"]) + abs(a["rr"] - b["rr"]) / 3.0
            + (0 if a["st"] == b["st"] else 0.5) + (0 if a["counter"] == b["counter"] else 0.4)) / 4.2


def note(V, k=8, max_d=0.35):
    """Строка для поста: что было в похожих прошлых ситуациях (по ближайшим соседям). Пусто, если журнала нет."""
    recs = [r for r in _load() if r.get("side") == V["side"]]
    near = sorted(((_dist(V["feat"], r["feat"]), r) for r in recs), key=lambda x: x[0])
    near = [r for d, r in near[:k] if d <= max_d]
    if not near: return "📚 Похожих ситуаций в журнале пока нет."
    ag = [r for r in near if r["ans"] == 1]; done = [r for r in ag if r.get("res") in ("tp", "stop")]
    s = "📚 Похожих ситуаций: %d, вы соглашались в %d" % (len(near), len(ag))
    if done: s += "; из согласованных завершились: цель %d, стоп %d" % (sum(r["res"] == "tp" for r in done), sum(r["res"] == "stop" for r in done))
    return s + (" (выборка мала, это подсказка, не прогноз)" if len(recs) < 30 else "")
