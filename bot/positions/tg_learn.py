# -*- coding: utf-8 -*-
"""tg_learn.py -- журнал ответов в режиме «Экспресс слежение» и поиск похожих прошлых ситуаций.
Ответы: 1 «согласен открыть сейчас», 0 «не согласен», 2 «здесь надо было заходить» (отметка задним числом на любом посте).
Только запись и подсказка: на решения бота и на ордера НЕ влияет. Исходы записей (цель | стоп | none) и дальность хода (для tg_target) дописываются позже.
Отключение: кнопка «Обучение» в меню (tg_express_cfg.json), EXPRESS_LEARN=0 или удаление файла (tg_bot подключает через try/except).
Файлы в POS_DIR: tg_learn.jsonl, tg_express_cfg.json {"learn": true|false}."""
import json, os, time
try: import tg_target as TG
except Exception: TG = None

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


def has_mark(mid, ans=None):
    return any(r.get("mid") == mid and (ans is None or r.get("ans") == ans) for r in _load())


def record(V, answer, wid, mid=None):
    """V - мнение из tg_express.verdict; answer: 1 согласен / 0 не согласен / 2 надо было заходить здесь; mid - сообщение (пост)."""
    rec = {"ts": int(time.time() * 1000), "wid": wid, "mid": mid, "sym": V["sym"], "side": V["side"], "t": V["t"], "call": V.get("call"), "feat": V["feat"], "plan": V["plan"], "geo": V.get("geo"), "ans": int(answer), "res": None}
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
    """Дописать исход (tp | stop | none) к записям без него и передать дальность хода в tg_target (самообучение цели, один раз на ситуацию).
    load_kl(sym) -> свечи 5m. Вызывается периодически из tg_bot."""
    recs = _load(); ch = False; done_t = {(r["sym"], r["t"]) for r in recs if r.get("sampled")}
    for r in recs:
        try: kl = load_kl(r["sym"]) or []
        except Exception: kl = []
        if r.get("res") is None:
            try:
                res = _outcome(r, kl)
                if res: r["res"] = res; ch = True
            except Exception: pass
        if TG and r.get("geo") and not r.get("sampled") and (r["sym"], r["t"]) not in done_t:
            try:
                g = r["geo"]; side = r["side"]; s = 1 if side == "long" else -1
                ks = [k for k in kl if k[0] > r["t"]]
                res2 = TG.simulate(ks, side, g["line"], g["H"], g["line"], g["line"] - s * g["risk"]) if len(ks) >= HORIZON else None
                if res2:
                    TG.add_sample({"src": "express", "sym": r["sym"], "t": r["t"], "side": side, "counter": int(r["feat"].get("counter", 0)), "hatr": r["feat"].get("width"), "res": res2})
                    r["sampled"] = 1; done_t.add((r["sym"], r["t"])); ch = True
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
    """Строка для поста: что было в похожих прошлых ситуациях, где вы отвечали (по ближайшим соседям; «заходить» = ответы 1 и 2). Пусто, если журнала нет."""
    recs = [r for r in _load() if r.get("side") == V["side"]]
    near = sorted(((_dist(V["feat"], r["feat"]), r) for r in recs), key=lambda x: x[0])
    near = [r for d, r in near[:k] if d <= max_d]
    if not near: return "📚 Похожих ситуаций в журнале пока нет."
    ag = [r for r in near if r["ans"] in (1, 2)]; done = [r for r in ag if r.get("res") in ("tp", "stop")]
    s = "📚 Похожих ситуаций: %d, вы хотели зайти в %d" % (len(near), len(ag))
    if done: s += "; завершились: цель %d, стоп %d" % (sum(r["res"] == "tp" for r in done), sum(r["res"] == "stop" for r in done))
    return s + (" (выборка мала, это подсказка, не прогноз)" if len(recs) < 30 else "")
