# -*- coding: utf-8 -*-
"""tg_shadow_scan.py -- сканер сигналов для теней по таймфреймам, на которых бот сейчас не следит (docs/topics/shadow_positions.md).

Зачем: слежение и посты бота идут на одном таймфрейме (кнопка «Таймфрейм» в Мониторе), поэтому тени без этого сервиса бывают только на нём. Сканер ведёт слежение и мнение «заходить» на остальных таймфреймах
(5m, 15m, 1h, 4h, 1d) теми же каналом, правилами слежения (tg_gate.watch_scan) и вердиктом (tg_express.verdict, verdict_break), что и бот, но молча: ничего не пишется в Telegram и на счёт.

Как: для каждого таймфрейма своя изолированная копия tg_gate (каталог shadow_scan/<tf>/: свои tg_watch.json и tg_mode.json, без событий и без лимита слежений), в chan_orders._tf_scan подставляется эта копия (процесс отдельный,
настоящие слежения не затрагиваются). После прохода по каждой новой свече слежения вердикт считается как в tg_bot.send_watch; при «заходить» сигнал уходит в очередь shadow_in.jsonl, из неё его забирает движок теней (tg_shadow.consume_queue).
Таймфрейм, на котором сейчас реально работает Монитор (посты есть), сканер пропускает: там тени создаёт сам бот по постам. Снимки BTC 1m, которые читает бот, сканер не пишет.

Запуск: сервис tg-shadow-scan (Nice, лимит CPU). Отладка: python3 tg_shadow_scan.py --once [--dry] [--tf 15m]: один проход и сводка (--dry: сигналы в очередь не пишутся).
Отключение: systemctl disable --now tg-shadow-scan; или shadow_cfg.json {"scan": false} (сервис простаивает)."""
import importlib.util, json, os, sys, time, traceback

D = os.environ.get("POS_DIR", "/opt/trading-bot/positions_regr")
CODE = os.environ.get("SHADOW_CODE_DIR", "/opt/trading-bot/positions")
NOTIFY = os.environ.get("SHADOW_NOTIFY_DIR", "/opt/tg-notify")
SD = os.path.join(D, "shadow_scan"); QF = os.path.join(D, "shadow_in.jsonl"); CFGF = os.path.join(D, "shadow_cfg.json")
ALL = ("5m", "15m", "1h", "4h", "1d")
for k_, v_ in (("CHAN_SRC", "regr"), ("CHAN_EDGE", "1"), ("TG_GATE", "1")): os.environ.setdefault(k_, v_)
sys.path.insert(0, NOTIFY); sys.path.append(CODE)
import tg_express as X
import tg_btc1m
tg_btc1m._save_last = lambda *a, **k: None          # снимки BTC 1m для постов пишет только tg_bot
import chan_orders as CO
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(CODE)] + [CODE]
CO.log = lambda m: print(time.strftime("%H:%M:%S"), "кодсчёта:", str(m)[:200], flush=True) if ("error" in str(m) or "ошибка" in str(m)) else None

AO_TGT = {0.25: "q1", 0.5: "mid", 0.75: "q3", 1.0: "opp"}
WK = ("id", "sym", "side", "line", "ctype", "t_alert", "updates", "tf", "last", "chan")
VK = ("call", "plan", "feat", "rows", "b1", "rg", "geo", "t", "tf")
GATES = {}; STT = {}; SEEN = {}


def log(m): print(time.strftime("%H:%M:%S"), "scan:", m, flush=True)


def ao_pick(V, B):
    """Как tg_bot.ao_pick: что поставил бы Автоордер по мнению бота: (setup, цель) или None."""
    if V and V.get("call") == "enter":
        f = float((V.get("plan") or {}).get("f") or 0.5); return "bounce", AO_TGT.get(f) or "f%.2f" % f
    if B and B.get("call") == "enter": return "breakout", "h05"
    return None


def cfg():
    try: return json.load(open(CFGF, encoding="utf-8"))
    except Exception: return {}


def new_gate(tf):
    """Изолированная копия tg_gate: свои файлы в shadow_scan/<tf>/, без событий и лимита числа слежений."""
    d = os.path.join(SD, tf); os.makedirs(d, exist_ok=True); old = os.environ.get("POS_DIR"); os.environ["POS_DIR"] = d
    try:
        spec = importlib.util.spec_from_file_location("tg_gate_" + tf, os.path.join(CODE, "tg_gate.py")); m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
    finally: os.environ["POS_DIR"] = old
    m.emit = lambda ev: None; m.emit_any = lambda ev: None; m.MAXW_HARD = 100000
    return m


def real_mode():
    try: return json.load(open(os.path.join(D, "tg_mode.json"), encoding="utf-8"))
    except Exception: return {}


def write_mode(tf, real):
    m = {k: real[k] for k in ("answer_win", "watch_unanswered", "watch_hours", "express_away", "express_hours") if k in real}
    m.update({"mode": "monitor", "tf": tf, "tf_epoch": 1, "express": True, "autoorder": False, "alerts_off": False, "until": None, "max_watch": 100000, "missed": 0, "max_missed": 1000000})
    p = os.path.join(SD, tf, "tg_mode.json"); tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, p)


def enqueue(tf, x, V, Bk, ao, dry):
    rec = {"t": int(time.time() * 1000), "tf": tf, "w": {k: x.get(k) for k in WK}, "V": {k: (V or {}).get(k) for k in VK} if V else None, "Bk": {k: Bk.get(k) for k in VK} if Bk else None, "ao": list(ao)}
    rec["w"]["tf"] = tf
    if dry: return
    with open(QF, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def scan_tf(tf, real, dry=False):
    """Один проход по таймфрейму: _tf_scan (каналы и слежения в изолированной копии шлюза), затем вердикт по каждой новой свече слежения."""
    G = GATES.get(tf) or GATES.setdefault(tf, new_gate(tf)); write_mode(tf, real)
    CO.tg_gate = G; now = int(time.time() * 1000); stt = STT.setdefault(tf, {}); radar_ = {}
    n = CO._tf_scan(CO.pairs_now(), now, tf, stt, radar_)
    ev = sig = 0
    for x in G._wload()["items"]:
        if x.get("status") not in ("alert", "watching"): continue
        last = x.get("last") or {}; key = (tf, x["id"]); s = (last.get("t"), x.get("updates"))
        if SEEN.get(key) == s: continue
        SEEN[key] = s; ev += 1
        try:
            kl = CO.kl_shared(x["sym"], now, tf); V = X.verdict(x, kl)
            Bk = X.verdict_break(x, kl) if (V and hasattr(X, "verdict_break")) else None
            ao = ao_pick(V, Bk)
            if ao: enqueue(tf, x, V, Bk, ao, dry); sig += 1
        except Exception as e: log("вердикт %s %s: %r" % (tf, x.get("sym"), e))
    return {"tf": tf, "analyzed": n, "watches": sum(1 for x in G._wload()["items"] if x.get("status") in ("alert", "watching")), "evaluated": ev, "signals": sig}


def main():
    once = "--once" in sys.argv; dry = "--dry" in sys.argv; only = sys.argv[sys.argv.index("--tf") + 1] if "--tf" in sys.argv else None
    log("запущен (%s)" % ("один проход" if once else "сервис"))
    while True:
        try:
            if cfg().get("scan", True) is False or cfg().get("enabled", True) is False: time.sleep(30); continue
            real = real_mode(); live = real.get("tf", "5m") if real.get("mode") == "monitor" else None
            for tf in ([only] if only else ALL):
                if tf == live: continue      # здесь тени создаёт бот по своим постам
                t0 = time.time()
                try:
                    r = scan_tf(tf, real, dry)
                    if once: print("RESULT", json.dumps(r), flush=True)
                    log("%s: проанализировано %s, слежений %s, оценено %s, сигналов «заходить» %s (%.1f с)" % (r["tf"], r["analyzed"], r["watches"], r["evaluated"], r["signals"], time.time() - t0))
                except Exception: log("%s: ошибка прохода: %s" % (tf, traceback.format_exc()[-500:]))
        except Exception: log("ошибка цикла: " + traceback.format_exc()[-500:])
        if once: return
        time.sleep(15)


if __name__ == "__main__":
    main()
