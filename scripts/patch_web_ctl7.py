# -*- coding: utf-8 -*-
"""Слежения, версия 11 (поверх patch_web_ctl6.py): свободный слот занимается новой парой сразу (в пределах цикла ~5 с), а не по закрытию следующей свечи 5m.
Раньше алерт по новому касанию создавался только когда у пары появлялась новая закрытая свеча (watch_scan из cycle). Если слоты были заняты или слежение отменили, пара с эпизодом у линии
ждала до 5 минут. Теперь в cycle для пар, свеча которых уже обработана, при свободном слоте (режим Монитор, алерты включены, активных < max_watch) вызывается tg_gate.watch_scan
с последней закрытой свечой: обновления уже идущих слежений не дублируются (они только при info.t > last.t), создаётся только новый алерт. Вытеснение занятых слотов не включается (вызов только при свободном месте).
Использование: python3 patch_web_ctl7.py chan_orders.py. Деплой: scripts/deploy_web_ctl7.sh. docs/topics/live_web.md"""
import os, sys

FREE_FN = r'''def _tg_free(now):
    """Есть ли свободное место под новое слежение (Монитор, алерты включены, активных меньше max_watch)."""
    try:
        if not tg_gate.ENABLED: return False
        m = tg_gate.load_mode()
        if m["mode"] != "monitor" or m.get("alerts_off"): return False
        return sum(1 for x in tg_gate._wload()["items"] if x["status"] in ("alert", "watching")) < tg_gate.maxw(m)
    except Exception: return False


'''
OLD1 = '            if stt["last"].get(sym) == ti: continue\n'
NEW1 = '''            if stt["last"].get(sym) == ti:
                if _free_:     # слот свободен (слежение отменено или закончилось): новая пара берётся сразу по последней закрытой свече, без ожидания следующей
                    try:
                        info_ = _tg_info(sym, A); tg_gate.watch_scan(info_, now); _free_ = _tg_free(now)
                    except Exception as e_: log("refill %s error: %s" % (sym, e_))
                continue
'''
OLD2 = '    for sym in pairs_:\n        try:\n            A = analyze(sym, now)\n'
NEW2 = '    _free_ = _tg_free(now)\n    for sym in pairs_:\n        try:\n            A = analyze(sym, now)\n'
EDITS = [
 ("fn", "def cycle(dry=False):", FREE_FN + "def cycle(dry=False):", "def _tg_free("),
 ("init", OLD2, NEW2, "_free_ = _tg_free(now)"),
 ("loop", OLD1, NEW1, "refill %s error"),
]
def patch(path):
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in EDITS:
        if marker in out: print("ALREADY", name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0
if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
